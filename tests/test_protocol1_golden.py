"""Protocol 1, pinned byte for byte: what the Kandev plugin's key sees.

Every `kandev` verb, the generic verbs under the Kandev key, the `--kandev`
authorized_keys line, `host kandev configure --json` and the file it writes,
the units `host kandev install` writes and one reaper pass, each run in the
harness with the clock, the randomness, the versions, the machine and whether
msbctl runs from a git checkout (23-self-update says which) fixed.
Each step's exit code, its exact stdout and the argv of every `msb` call it
made are compared with tests/golden/protocol1/<step>.json.

The plugin requires `protocol == 1` and reads these documents as they are,
so a diff here is a change to a frozen protocol. The fixtures are written by
hand, never by CI:

    MSBCTL_GOLDEN_WRITE=1 python3 -I -m unittest tests.test_protocol1_golden

and a rewrite belongs in its own commit, which says why.
"""

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
from unittest import main, mock

from tests.harness import ROOT, MsbctlTest

GOLDEN = os.path.join(ROOT, "tests", "golden", "protocol1")
REAL_WHICH = shutil.which
WRITE = os.environ.get("MSBCTL_GOLDEN_WRITE") == "1"
IMAGE = "ghcr.io/acme/api-sbx@sha256:" + "a" * 64
API_ADDR = "192.0.2.10"
T0 = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
       " plugin@example")
BLOB = b"\x7fELF golden agentctl \x00\xff"
HOST_FACTS = {"os": "Example Linux 1", "kernel": "6.0.0", "cpus": 8, "memory_total_mib": 32768,
              "memory_available_mib": 16384, "load_1m": 0.5, "disk_total_gib": 100.0,
              "disk_free_gib": 50.0, "uptime_seconds": 1000}
CONFIG = """\
[kandev]
enabled = true
base_url = "https://sbx-01.example.ts.net"
serve = "none"
allow_extra = ["pypi.org", "git.example.org", "192.0.2.0/24"]
private_names = ["git.example.org"]
max_sandboxes = 3
port_pool = "20000-20099"
proxy_port_pool = "30000-30099"
"""


def request(**over):
    req = {"operation_id": "op-1", "input_digest": "sha256:1", "image": IMAGE,
           "cpus": 2, "memory_mib": 2048, "disk_gib": 10, "workspace_gib": 20,
           "expires_at": "2030-01-02T00:00:00Z",
           "kandev_api": {"host": "kandev.example.ts.net", "port": 443},
           "egress_allow": ["pypi.org"],
           "env": [{"name": "NODE_ENV", "value": "development"}],
           "secrets": [{"name": "NPM_TOKEN", "value": "golden-npm-value", "hosts": ["registry.npmjs.org"]}]}
    req.update(over)
    return (json.dumps(req) + "\n").encode()


def agentctl_input(**over):
    header = {"sha256": hashlib.sha256(BLOB).hexdigest(), "size": len(BLOB), "version": "0.97.0",
              "nonce": "golden-nonce", "runtime_port": 8765, "args": ["-port=8765"],
              "env": {"AGENTCTL_LISTEN_HOST": "0.0.0.0"}}  # noqa: S104 — the guest's own listener
    header.update(over)
    return json.dumps(header).encode() + b"\n" + BLOB


def doctor_scope(out):
    """What of `doctor --json` is the key's scope rather than this machine:
    which of the operator's checks it leaves out, and the registry and orphan
    checks whole."""
    doc = json.loads(out)
    ids = {c["id"] for c in doc["checks"]}
    operator_only = ("github-token", "secret-store", "autostart")
    return json.dumps({"restricted": doc["restricted"],
                       "left_out": [i for i in operator_only if i not in ids],
                       "scoped": [c for c in doc["checks"] if c["id"] in ("registry", "orphans")]},
                      indent=2, sort_keys=True)


class _AnyPort:
    """socket.socket for the port allocators: every port binds, so the ports a
    fixture holds do not depend on what else this machine is running."""

    def __init__(self, *_a, **_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def bind(self, _addr):
        pass

    def close(self):
        pass


class Protocol1Golden(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.now = T0
        self.seq = 0
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        self.write_config(CONFIG)
        self.seen = set()
        self.mismatches = []

    def write_config(self, text):
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(text)

    def urandom(self, n):
        self.seq += 1
        return hashlib.sha256(f"golden-{self.seq}".encode()).digest()[:n].ljust(n, b"\0")

    @staticmethod
    def which(name, *args, **kwargs):
        """msbctl at a fixed path; no tailscale or systemctl, whatever this
        machine has; the fake msb as it is."""
        if name == "msbctl":
            return "/opt/msb/bin/msbctl"
        if name in ("tailscale", "systemctl"):
            return None
        return REAL_WHICH(name, *args, **kwargs)

    def normal(self, text):
        text = text.replace(os.path.realpath(self.tmp), "<TMP>").replace(self.tmp, "<TMP>") \
            .replace(ROOT, "<ROOT>")
        return re.sub(r"enable-linger \S+", "enable-linger <USER>", text)

    def run_step(self, label, *argv, stdin=b"", key="kandev", pick=None):
        """One step: run it as `key` ("kandev", or None for the operator at
        the host), and compare (or write) its fixture."""
        before = len(self.msb_calls())
        if key:
            os.environ["MSB_RESTRICTED"] = key
        fake_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (API_ADDR, 443))]
        m = self.m
        try:
            with mock.patch.object(m.socket, "getaddrinfo", lambda *a, **k: fake_dns), \
                    mock.patch.object(m.socket, "socket", _AnyPort), \
                    mock.patch.object(m, "kandev_probe", lambda port, timeout=1.0: True), \
                    mock.patch.object(m.time, "sleep", lambda s: None), \
                    mock.patch.object(m, "utc_now", lambda: self.now), \
                    mock.patch.object(m.os, "urandom", self.urandom), \
                    mock.patch.object(m, "version_string", lambda: "0.0.0-golden"), \
                    mock.patch.object(m, "local_msb_version", lambda: "0.7.7"), \
                    mock.patch.object(m, "kandev_host_facts", lambda: dict(HOST_FACTS)), \
                    mock.patch.object(m, "host_platform", lambda: "linux-amd64"), \
                    mock.patch.object(m, "kvm_status", lambda: "rw"), \
                    mock.patch.object(m, "lingering", lambda user=None: False), \
                    mock.patch.object(m, "IS_CHECKOUT", True), \
                    mock.patch.object(m.shutil, "which", self.which):
                code, out, _err = self.run_main(*argv, stdin=stdin)
        finally:
            os.environ.pop("MSB_RESTRICTED", None)
        if pick:
            out = pick(out)
        got = {"argv": list(argv), "key": key, "exit": code, "stdout": self.normal(out),
               "msb": [[self.normal(a) for a in c["argv"]] for c in self.msb_calls()[before:]]}
        self.check(label, got)
        return got

    def check(self, label, got):
        self.assertNotIn(label, self.seen)
        self.seen.add(label)
        path = os.path.join(GOLDEN, f"{label}.json")
        if WRITE:
            os.makedirs(GOLDEN, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(got, fh, indent=1, sort_keys=True)
                fh.write("\n")
            return
        with open(path, encoding="utf-8") as fh:
            want = json.load(fh)
        if want != got:
            self.mismatches.append(label)
        self.assertEqual(want, got, f"protocol 1 changed in step {label}")

    def check_file(self, label, path):
        with open(path, encoding="utf-8") as fh:
            self.check(label, {"file": self.normal(fh.read())})

    # ------------------------------------------------------------------ steps

    def test_the_kandev_verbs(self):
        s = self.run_step
        s("01-health", "kandev", "health")
        s("02-provision", "kandev", "provision", "e1", stdin=request())
        s("03-provision-again", "kandev", "provision", "e1", stdin=request())
        s("04-provision-conflict", "kandev", "provision", "e1", stdin=request(input_digest="sha256:2"))
        s("05-provision-refused", "kandev", "provision", "e9",
          stdin=request(operation_id="op-9", egress_allow=["example.com"]))
        s("06-agentctl", "kandev", "agentctl", "e1", stdin=agentctl_input())
        s("07-agentctl-refused", "kandev", "agentctl", "e1",
          stdin=agentctl_input(env={"AGENTCTL_BOOTSTRAP_NONCE": "x"}))
        s("08-lease", "kandev", "lease", "e1", "8765")
        s("09-lease-unknown-port", "kandev", "lease", "e1", "22")
        s("10-expiry", "kandev", "expiry", "e1", "--at", "2031-01-01T00:00:00Z")
        s("11-ls", "ls", "--json")
        s("12-show", "show", "k-e1", "--json")
        s("13-stop", "stop", "k-e1", "--json")
        s("14-start-without-secrets", "kandev", "start", "e1", stdin=b"{}\n")
        s("15-start", "kandev", "start", "e1", stdin=(json.dumps({"secrets": [
            {"name": "NPM_TOKEN", "value": "golden-npm-value", "hosts": ["registry.npmjs.org"]}]})
            + "\n").encode())
        s("16-provision-private", "kandev", "provision", "e2",
          stdin=request(operation_id="op-2", egress_allow=["git.example.org", "192.0.2.7:22"],
                        private_names=["git.example.org"], secrets=[], env=[],
                        kandev_api={"host": "192.0.2.10", "port": 8443}))
        s("17-provision-at-capacity-ok", "kandev", "provision", "e3",
          stdin=request(operation_id="op-3", cpus=1, memory_mib=512))
        s("18-provision-rate-limited", "kandev", "provision", "e4", stdin=request(operation_id="op-4"))
        s("19-restart-proxy", "kandev", "restart-proxy")
        s("20-tls-needs-a-pair", "kandev", "tls", "install", stdin=b"{}\n")
        s("21-lease-not-found", "kandev", "lease", "nope", "8765")
        s("22-provision-needs-env", "kandev", "provision")
        s("23-self-update", "self-update", "--json")
        s("24-purge", "purge", "k-e2", "-y", "--json")
        s("25-purge-absent", "purge", "k-e2", "-y", "--json")
        self.make_folder_sandbox("web")
        s("26-show-operator-sandbox", "show", "web", "--json")
        s("27-stop-operator-sandbox", "stop", "web", "--json")
        s("28-purge-operator-sandbox", "purge", "web", "-y", "--json")
        s("29-ls-after", "ls", "--json")
        s("29-doctor-scoped", "doctor", "--json", pick=doctor_scope)
        self.set_state(**{"k-gone": "running"})
        state = self.fake_state()
        state.setdefault("_labels", {})["k-gone"] = ["msbctl.owner=kandev", "kandev.env=gone"]
        state.setdefault("_created", {})["k-gone"] = "2029-12-31T00:00:00.5+00:00"
        with open(os.environ["FAKE_MSB_STATE"], "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        self.now = T0 + dt.timedelta(days=1, hours=1)
        s("30-reap", "host", "kandev", "reap", key=None)
        s("31-ls-after-reap", "ls", "--json")
        s("32-health-after", "kandev", "health")

    def test_disabled(self):
        self.write_config("[kandev]\nenabled = false\n")
        self.run_step("40-disabled-health", "kandev", "health")
        self.run_step("41-disabled-provision", "kandev", "provision", "e1", stdin=request())
        self.run_step("42-disabled-ls", "ls", "--json")

    def test_bad_config(self):
        self.write_config('[kandev]\nenabled = true\nserve = "nope"\n')
        self.run_step("43-bad-config-health", "kandev", "health")

    def test_proxy_mode(self):
        self.write_config(CONFIG.replace('serve = "none"', 'serve = "proxy"\nproxy_listen = "127.0.0.1"'))
        os.makedirs(self.m.KANDEV_TLS_DIR, exist_ok=True)
        for path in (self.m.KANDEV_TLS_CERT, self.m.KANDEV_TLS_KEY):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("not a certificate\n")
        self.run_step("50-proxy-health", "kandev", "health")
        self.run_step("51-proxy-provision", "kandev", "provision", "e1", stdin=request())
        self.run_step("52-proxy-lease", "kandev", "lease", "e1", "41001")
        self.run_step("53-proxy-show", "show", "k-e1", "--json")
        self.run_step("54-proxy-purge", "purge", "k-e1", "-y", "--json")

    def test_host_side(self):
        self.write_config("[defaults]\ncpus = 4\n")
        self.run_step("60-authorize", "host", "authorize", KEY, "--kandev", key=None)
        self.check_file("61-authorized-keys", os.path.join(self.home, ".ssh", "authorized_keys"))
        self.run_step("62-authorize-replace", "host", "authorize", KEY, "--kandev", "--replace", key=None)
        self.check_file("63-authorized-keys-replaced", os.path.join(self.home, ".ssh", "authorized_keys"))
        self.run_step("64-configure", "host", "kandev", "configure", "--enabled", "--serve", "proxy",
                      "--proxy-listen", "192.0.2.1", "--base-url", "https://sbx-01.example.org",
                      "--allow-extra", "pypi.org", "--private-name", "git.example.org", "--json", key=None)
        self.check_file("65-configured", self.m.CONFIG_FILE)
        self.run_step("66-configure-refused", "host", "kandev", "configure", "--serve", "nope", "--json",
                      key=None)
        self.run_step("67-configure-again", "host", "kandev", "configure", "--enabled", "--json", key=None)
        self.run_step("68-install", "host", "kandev", "install", key=None)
        for unit in ("msb-kandev-reap.service", "msb-kandev-reap.timer", "msb-kandev-proxy.service"):
            self.check_file(f"69-{unit}", os.path.join(self.m.SYSTEMD_USER_DIR, unit))


if __name__ == "__main__":
    main()
