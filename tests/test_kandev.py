"""msbctl kandev: Kandev's sandboxes on this host, driven over ssh as JSON."""

import hashlib
import json
import os
import socket
from unittest import main, mock

from tests.harness import MsbctlTest

IMAGE = "ghcr.io/acme/api-sbx@sha256:" + "a" * 64
SECRET = "npm-secret-planted-4d1"
NONCE = "nonce-planted-9c2"
PASSWORD = "registry-password-planted-7e5"
API_ADDR = "100.64.0.5"


def request(**over):
    req = {"operation_id": "op-1", "input_digest": "sha256:1", "image": IMAGE,
           "cpus": 2, "memory_mib": 2048, "disk_gib": 10, "expires_at": "2099-01-01T00:00:00Z",
           "kandev_api": {"host": "kandev.example.ts.net", "port": 443},
           "egress_allow": ["pypi.org"],
           "env": [{"name": "NODE_ENV", "value": "development"}],
           "secrets": [{"name": "NPM_TOKEN", "value": SECRET, "hosts": ["registry.npmjs.org"]}]}
    req.update(over)
    return json.dumps(req) + "\n"


class KandevTest(MsbctlTest):

    env_keys = ("NPM_TOKEN", "MSB_CONFIG_PATH", "MSBCTL_REGISTRY_PASSWORD")

    def setUp(self):
        super().setUp()
        self.configure()
        self.probe = True

    def configure(self, **over):
        values = {"enabled": True, "base_url": '"https://sbx-01.example.ts.net"', "serve": '"none"',
                  "allow_extra": '["pypi.org"]', "max_sandboxes": 12}
        values.update(over)
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write("[kandev]\n" + "".join(
                f"{k} = {str(v).lower() if isinstance(v, bool) else v}\n" for k, v in values.items()))

    def kandev(self, *argv, stdin=""):
        """(exit code, the one JSON document on stdout)."""
        fake_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (API_ADDR, 443))]
        with mock.patch.object(self.m.socket, "getaddrinfo", lambda *a, **k: fake_dns), \
                mock.patch.object(self.m, "kandev_probe", lambda port, timeout=1.0: self.probe), \
                mock.patch.object(self.m.time, "sleep", lambda s: None):
            code, out, err = self.run_main("kandev", *argv, stdin=stdin if isinstance(stdin, bytes)
                                           else stdin.encode())
        try:
            return code, json.loads(out)
        except ValueError:
            self.fail(f"stdout is not one JSON document: {out!r}\n{err}")

    def ok(self, *argv, stdin=""):
        code, doc = self.kandev(*argv, stdin=stdin)
        self.assertEqual(code, 0, doc)
        return doc

    def error(self, code_name, *argv, stdin=""):
        code, doc = self.kandev(*argv, stdin=stdin)
        self.assertEqual(code, 3, doc)
        self.assertEqual(doc["error"]["code"], code_name, doc)
        return doc["error"]

    def provision(self, env="6f1c2b9e", **over):
        return self.ok("provision", env, stdin=request(**over))["record"]

    def assert_nowhere_on_disk(self, value):
        for root, _, files in os.walk(self.tmp):
            for name in files:
                path = os.path.join(root, name)
                if path == os.environ["FAKE_MSB_LOG"]:
                    continue        # the fake records the env keys a test asks for
                with open(path, "rb") as fh:
                    if value.encode() in fh.read():
                        self.fail(f"the value under test was written to {os.path.relpath(path, self.tmp)}")

    def tailscale_calls(self):
        try:
            with open(os.environ["FAKE_TAILSCALE_LOG"], encoding="utf-8") as fh:
                return [json.loads(line) for line in fh]
        except FileNotFoundError:
            return []


class HealthAndConfig(KandevTest):

    def test_health_is_the_fixed_document(self):
        doc = self.ok("health")
        self.assertEqual(doc["protocol"], 1)
        self.assertTrue(doc["enabled"])
        self.assertEqual(doc["base_url"], "https://sbx-01.example.ts.net")
        self.assertEqual(doc["capacity"]["max_sandboxes"], 12)
        self.assertEqual(doc["capacity"]["max_memory_mib"], 96 * 1024)
        self.assertEqual(doc["serve"]["ok"], True)
        for key in ("msbctl_version", "msb_version", "kvm", "platform"):
            self.assertIn(key, doc)

    def test_disabled_answers_health_and_denies_the_rest(self):
        self.configure(enabled=False)
        self.assertFalse(self.ok("health")["enabled"])
        self.error("denied", "provision", "e1", stdin=request())
        self.error("denied", "list")

    def test_bad_config_is_named(self):
        for key, value in (("port_pool", '"10-20"'), ("max_memory", '"lots"'),
                           ("base_url", '"http://x"'), ("base_url", '"https://x/path"'),
                           ("rule_groups", '["nope"]'), ("allow_extra", '["not a host"]')):
            with self.subTest(key=key):
                self.configure(**{key: value})
                self.assertIn(key, self.error("invalid_config", "health")["message"])

    def test_serve_reports_tailscale(self):
        self.configure(serve='"tailscale"')
        doc = self.ok("health")
        self.assertEqual(doc["serve"], {"ok": True, "mode": "tailscale"})


class Provision(KandevTest):

    def test_create_argv_and_record(self):
        rec = self.provision()
        self.assertEqual((rec["name"], rec["state"], rec["generation"]), ("k-6f1c2b9e", "running", 1))
        self.assertEqual(sorted(rec["ports"]), ["41001", "41002", "41003", "8765"])
        create = self.msb_calls("create")
        self.assertEqual(len(create), 1)
        argv = create[0]["argv"]
        self.assertEqual(argv[-1], IMAGE)
        self.assertIn("--pull", argv)
        self.assertEqual(argv[argv.index("--pull") + 1], "never")
        self.assertIn("msbctl.owner=kandev", argv)
        self.assertIn("kandev.env=6f1c2b9e", argv)
        self.assertIn(f"allow@{API_ADDR}:tcp:443", argv)
        self.assertIn("allow@pypi.org:tcp:443", argv)
        self.assertIn("NODE_ENV=development", argv)
        ports = [argv[i + 1] for i, a in enumerate(argv) if a == "--port"]
        self.assertTrue(all(p.startswith("127.0.0.1:") for p in ports) and len(ports) == 4)
        # None of msbctl's own plumbing: no agent socket, no mounts, no
        # rebind protection switched off.
        for flag in ("--vsock", "--mount-dir", "--mount-file", "--no-dns-rebind-protection", "--conf"):
            self.assertNotIn(flag, argv)
        secret = [argv[i + 1] for i, a in enumerate(argv) if a == "--secret"]
        self.assertEqual(len(secret), 1)
        self.assertTrue(secret[0].startswith("NPM_TOKEN:passthrough=["))
        self.assertEqual(create[0]["env"].get("NPM_TOKEN"), SECRET)
        self.assert_not_in_argv(SECRET)
        self.assert_nowhere_on_disk(SECRET)
        # The only exec is the API pin in /etc/hosts: no bootstrap, no profile.
        execs = self.msb_calls("exec")
        self.assertEqual(len(execs), 1)
        self.assertEqual(execs[0]["argv"][-2:], [API_ADDR, "kandev.example.ts.net"])

    def test_entry_is_kandevs(self):
        self.provision()
        box = self.m.Sandbox("k-6f1c2b9e", self.m.load_config())
        self.assertTrue(box.is_kandev)
        self.assertEqual(box.entry["kandev_env"], "6f1c2b9e")
        self.assertEqual(box.entry["secret_binds"], ["NPM_TOKEN@registry.npmjs.org"])
        self.assertFalse(box.entry["autostart"])

    def test_idempotent_by_operation(self):
        first = self.provision()
        again = self.provision()
        self.assertEqual(first["ports"], again["ports"])
        self.assertEqual(len(self.msb_calls("create")), 1)
        self.error("conflict", "provision", "6f1c2b9e", stdin=request(input_digest="sha256:2"))
        self.error("conflict", "provision", "other", stdin=request())

    def test_capacity_and_ports(self):
        self.configure(max_sandboxes=1)
        self.provision("e1")
        err = self.error("rate_limited", "provision", "e2", stdin=request(operation_id="op-2"))
        self.assertEqual(err["retry_after_seconds"], 30)
        self.configure(max_sandboxes=3)
        two = self.provision("e2", operation_id="op-2")
        one = self.ok("inspect", "e1")["record"]
        self.assertFalse(set(one["ports"].values()) & set(two["ports"].values()))

    def test_refused_requests(self):
        cases = [
            ("invalid_config", {"image": "ghcr.io/acme/api:latest"}),
            ("invalid_config", {"image": "/home/you/rootfs"}),
            ("invalid_config", {"expires_at": "2001-01-01T00:00:00Z"}),
            ("invalid_config", {"secrets": [{"name": "GH_TOKEN", "value": "x", "hosts": ["a.example"]}]}),
            ("invalid_config", {"secrets": [{"name": "MSB_HOME", "value": "x", "hosts": ["a.example"]}]}),
            ("invalid_config", {"secrets": [{"name": "AGENTCTL_X", "value": "x", "hosts": ["a.example"]}]}),
            ("invalid_config", {"secrets": [{"name": "NODE_ENV", "value": "x", "hosts": ["a.example"]}]}),
            ("invalid_config", {"secrets": [{"name": "TOK", "value": "x"}]}),
            ("invalid_config", {"kandev_api": None}),
            ("invalid_config", {"egress_allow": ["evil.example"]}),
            ("invalid_config", {"egress_allow": ["allow@evil.example"]}),
        ]
        for code, over in cases:
            with self.subTest(over=over):
                self.error(code, "provision", "e1", stdin=request(**over))
        self.assertEqual(self.msb_calls("create"), [])
        self.error("invalid_config", "provision", "bad id!", stdin=request())
        self.error("invalid_config", "provision", "e1", stdin="not json\n")
        self.error("invalid_config", "provision", "e1", stdin='{"no": "newline"}')

    def test_allow_extra_star(self):
        self.configure(allow_extra='["*"]')
        self.provision(egress_allow=["anything.example", "10.0.0.5:22"])

    def test_private_registry_password_stays_in_one_environment(self):
        self.provision(registry={"username": "bot", "password": PASSWORD})
        pull = self.msb_calls("pull")[0]
        self.assertEqual(pull["argv"], ["pull", IMAGE])
        self.assertEqual(pull["env"]["MSBCTL_REGISTRY_PASSWORD"], PASSWORD)
        auth = pull["msb_config"]["registries"]["hosts"]["ghcr.io"]["auth"]
        self.assertEqual(auth, {"username": "bot", "password_env": "MSBCTL_REGISTRY_PASSWORD"})
        self.assertFalse(os.path.exists(pull["env"]["MSB_CONFIG_PATH"]))
        self.assertNotIn("MSBCTL_REGISTRY_PASSWORD", self.msb_calls("create")[0]["env"])
        self.assert_not_in_argv(PASSWORD)
        self.assert_nowhere_on_disk(PASSWORD)

    def test_registry_needs_a_registry_host(self):
        self.error("invalid_config", "provision", "e1", stdin=request(
            image="acme/api@sha256:" + "a" * 64, registry={"username": "u", "password": "p"}))

    def test_a_failed_create_leaves_the_entry_for_reap(self):
        os.environ["FAKE_MSB_FAIL"] = "create"
        self.error("unavailable", "provision", "e1", stdin=request())
        self.assertEqual(self.ok("list")["sandboxes"][0]["state"], "creating")

    def test_names(self):
        self.assertEqual(self.m.kandev_name("6f1c2b9e-aaaa"), "k-6f1c2b9e-aaaa")
        for env in ("UPPER", "under_score", "x" * 60):
            with self.subTest(env=env):
                name = self.m.kandev_name(env)
                self.assertRegex(name, r"^k-[0-9a-f]{24}$")
                self.assertEqual(name, "k-" + hashlib.sha256(env.encode()).hexdigest()[:24])

    def test_tailscale_serve_mappings(self):
        self.configure(serve='"tailscale"')
        rec = self.provision()
        mapped = [c for c in self.tailscale_calls() if c[:2] == ["serve", "--bg"]]
        self.assertEqual(len(mapped), 4)
        self.assertIn("--set-path=/vm/k-6f1c2b9e/p/8765", mapped[0] + mapped[1] + mapped[2] + mapped[3])
        self.assertIn(f"http://127.0.0.1:{rec['ports']['8765']}", sum(mapped, []))
        self.ok("destroy", "6f1c2b9e")
        off = [c for c in self.tailscale_calls() if c[-1:] == ["off"]]
        self.assertEqual(len(off), 4)


class Lifecycle(KandevTest):

    def agentctl_input(self, blob=b"\x7fELF fake agentctl", **over):
        header = {"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob), "version": "0.97.0",
                  "nonce": NONCE, "runtime_port": 8765, "args": ["-port=8765"],
                  "env": {"AGENTCTL_LISTEN_HOST": "0.0.0.0"}}  # noqa: S104 — the guest's own listener
        header.update(over)
        return json.dumps(header).encode() + b"\n" + blob

    def test_agentctl(self):
        self.provision()
        os.environ["FAKE_MSB_READ_STDIN"] = "1"
        blob = b"\x7fELF fake agentctl \x00\xff"
        rec = self.ok("agentctl", "6f1c2b9e", stdin=self.agentctl_input(blob))["record"]
        self.assertTrue(rec["agentctl"]["running"])
        self.assertEqual(rec["agentctl"]["sha256"], hashlib.sha256(blob).hexdigest())
        execs = self.msb_calls("exec")[1:]
        self.assertEqual(execs[0]["stdin"]["sha256"], hashlib.sha256(blob).hexdigest())
        self.assertEqual(execs[1]["stdin"]["sha256"], hashlib.sha256(NONCE.encode() + b"\n").hexdigest())
        self.assertIn("AGENTCTL_LISTEN_HOST=0.0.0.0", execs[1]["argv"])
        self.assert_not_in_argv(NONCE)
        self.assert_nowhere_on_disk(NONCE)
        # The same binary again, still answering: nothing is written.
        self.ok("agentctl", "6f1c2b9e", stdin=self.agentctl_input(blob))
        self.assertEqual(len(self.msb_calls("exec")), 3)

    def test_agentctl_refuses_before_anything_runs(self):
        self.provision()
        good = self.agentctl_input()
        self.error("invalid_config", "agentctl", "6f1c2b9e", stdin=good[:-1] + b"X")
        self.error("invalid_config", "agentctl", "6f1c2b9e", stdin=good[:-3])
        self.error("invalid_config", "agentctl", "6f1c2b9e",
                   stdin=self.agentctl_input(env={"PATH": "/tmp"}))
        self.error("invalid_config", "agentctl", "6f1c2b9e",
                   stdin=self.agentctl_input(env={"AGENTCTL_BOOTSTRAP_NONCE": "x"}))
        self.error("invalid_config", "agentctl", "6f1c2b9e", stdin=self.agentctl_input(runtime_port=22))
        self.assertEqual(len(self.msb_calls("exec")), 1)          # the API pin only

    def test_agentctl_that_never_answers(self):
        self.provision()
        self.probe = False
        with mock.patch.object(self.m, "KANDEV_AGENTCTL_WAIT", 0):
            self.error("unavailable", "agentctl", "6f1c2b9e", stdin=self.agentctl_input())

    def test_inspect_find_list_lease(self):
        self.provision()
        self.assertEqual(self.ok("inspect", "6f1c2b9e")["record"]["state"], "running")
        self.error("not_found", "inspect", "nope")
        self.assertEqual(self.ok("find", "--operation", "op-1")["record"]["env"], "6f1c2b9e")
        self.error("not_found", "find", "--operation", "op-9")
        self.assertEqual([s["env"] for s in self.ok("list")["sandboxes"]], ["6f1c2b9e"])
        lease = self.ok("lease", "6f1c2b9e", "41001")["lease"]
        self.assertEqual(lease["base_url"], "https://sbx-01.example.ts.net/vm/k-6f1c2b9e/p/41001")
        self.assertEqual(lease["generation"], "1")
        self.error("not_found", "lease", "6f1c2b9e", "22")
        self.configure(base_url='""')
        self.error("unavailable", "lease", "6f1c2b9e", "8765")

    def test_stop_start_needs_its_secrets(self):
        self.provision()
        self.assertEqual(self.ok("stop", "6f1c2b9e")["record"]["state"], "stopped")
        self.error("unavailable", "lease", "6f1c2b9e", "8765")
        self.error("invalid_config", "start", "6f1c2b9e", stdin="")
        wrong = json.dumps({"secrets": [{"name": "OTHER", "value": "v", "hosts": ["a.example"]}]})
        self.error("invalid_config", "start", "6f1c2b9e", stdin=wrong + "\n")
        right = json.dumps({"secrets": [{"name": "NPM_TOKEN", "value": SECRET}]})
        rec = self.ok("start", "6f1c2b9e", stdin=right + "\n")["record"]
        self.assertEqual((rec["state"], rec["generation"]), ("running", 2))
        start = self.msb_calls("start")[0]
        self.assertEqual(start["env"]["NPM_TOKEN"], SECRET)
        # msb writes a fresh /etc/hosts on every boot, so the pin is re-applied.
        self.assertEqual(self.msb_calls("exec")[-1]["argv"][-1], "kandev.example.ts.net")
        self.assert_not_in_argv(SECRET)
        self.assert_nowhere_on_disk(SECRET)

    def test_expiry_is_clamped(self):
        self.provision(expires_at="2090-01-01T00:00:00Z")
        rec = self.ok("expiry", "6f1c2b9e", "--at", "2095-01-01T00:00:00Z")["record"]
        self.assertEqual(rec["expires_at"], "2090-01-01T00:00:00Z")
        rec = self.ok("expiry", "6f1c2b9e", "--at", "2080-06-01T12:00:00+00:00")["record"]
        self.assertEqual(rec["expires_at"], "2080-06-01T12:00:00Z")
        self.error("invalid_config", "expiry", "6f1c2b9e", "--at", "tomorrow")

    def test_destroy_is_always_safe(self):
        self.provision()
        self.assertEqual(self.ok("destroy", "6f1c2b9e"), {"destroyed": True})
        self.assertEqual(self.ok("destroy", "6f1c2b9e"), {"destroyed": True})
        self.assertEqual(self.ok("list")["sandboxes"], [])
        self.assertNotIn("k-6f1c2b9e", self.fake_state())

    def test_an_operator_sandbox_named_like_one_is_never_touched(self):
        self.make_folder_sandbox("k-x")
        self.set_state(**{"k-x": "running"})
        self.assertEqual(self.ok("destroy", "x"), {"destroyed": True})
        self.error("not_found", "inspect", "x")
        self.error("conflict", "provision", "x", stdin=request())
        self.ok("reap")
        self.assertEqual(self.fake_state()["k-x"], "running")
        self.assertTrue(os.path.exists(self.entry_path("k-x")))
        self.assertEqual(self.ok("list")["sandboxes"], [])


class Reap(KandevTest):

    def test_expired_stuck_gone_and_orphans(self):
        self.provision("old", operation_id="op-a")
        self.provision("gone", operation_id="op-b")
        self.provision("live", operation_id="op-c")
        self.m.set_toml_key(self.entry_path("k-old"), "expires_at", "2001-01-01T00:00:00Z")
        state = self.fake_state()
        del state["k-gone"]
        state["k-orphan"] = "running"
        state.setdefault("_labels", {})["k-orphan"] = ["msbctl.owner=kandev"]
        state.setdefault("_created", {})["k-orphan"] = "2001-01-01T00:00:00.5+00:00"
        state["k-young"] = "running"
        state["_labels"]["k-young"] = ["msbctl.owner=kandev"]
        state["_created"]["k-young"] = "2099-01-01T00:00:00+00:00"
        with open(os.environ["FAKE_MSB_STATE"], "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        # A create that never finished, an hour ago.
        os.environ["FAKE_MSB_FAIL"] = "create"
        self.error("unavailable", "provision", "stuck", stdin=request(operation_id="op-d"))
        del os.environ["FAKE_MSB_FAIL"]
        self.m.set_toml_key(self.entry_path("k-stuck"), "created_at", "2001-01-01T00:00:00Z")

        out = self.ok("reap")
        self.assertEqual(sorted(out["destroyed"]), ["k-old", "k-stuck"])
        self.assertEqual(out["marked_absent"], ["k-gone"])
        self.assertEqual(out["orphans_removed"], ["k-orphan"])
        self.assertEqual(out["errors"], [])
        left = self.fake_state()
        self.assertIn("k-live", left)
        self.assertIn("k-young", left)
        states = {s["name"]: s["state"] for s in self.ok("list")["sandboxes"]}
        self.assertEqual(states, {"k-gone": "absent", "k-live": "running"})


class OperatorSide(KandevTest):

    def test_operator_verbs_look_but_do_not_touch(self):
        self.provision()
        for argv in (["rebuild", "k-6f1c2b9e"], ["start", "k-6f1c2b9e"], ["stop", "k-6f1c2b9e"],
                     ["resize", "k-6f1c2b9e", "--memory", "4G"], ["allow", "k-6f1c2b9e", "x.example"],
                     ["purge", "k-6f1c2b9e", "-y"], ["edit", "k-6f1c2b9e"],
                     ["secret", "ls", "k-6f1c2b9e"]):
            with self.subTest(argv=argv):
                code, _, err = self.run_main(*argv)
                self.assertNotEqual(code, 0)
                self.assertIn("Kandev sandbox", err)
        code, out, err = self.run_main("ls", "--json")
        self.assertEqual(code, 0, err)
        row = json.loads(out)["sandboxes"][0]
        self.assertEqual((row["source"], row["location"]), ("kandev", "kandev:6f1c2b9e"))
        code, out, err = self.run_main("show", "k-6f1c2b9e", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["kandev"]["env"], "6f1c2b9e")
        code, out, err = self.run_main("show", "k-6f1c2b9e")
        self.assertEqual(code, 0, err)
        self.assertNotIn(SECRET, out + err)

    def test_shell_only_while_running(self):
        self.provision()
        self.ok("stop", "6f1c2b9e")
        code, _, err = self.run_main("exec", "k-6f1c2b9e", "--", "true")
        self.assertNotEqual(code, 0)
        self.assertIn("only Kandev starts it", err)
        self.assertEqual(self.msb_calls("start"), [])

    def test_host_kandev_install_writes_the_timer(self):
        with mock.patch.object(self.m.shutil, "which",
                               lambda name: "/home/x/.local/bin/msbctl" if name == "msbctl" else None):
            code, _, err = self.run_main("host", "kandev", "install")
        self.assertEqual(code, 0, err)
        unit = os.path.join(self.m.SYSTEMD_USER_DIR, "msb-kandev-reap")
        with open(unit + ".service", encoding="utf-8") as fh:
            self.assertIn("ExecStart=/home/x/.local/bin/msbctl kandev reap", fh.read())
        with open(unit + ".timer", encoding="utf-8") as fh:
            self.assertIn("OnUnitActiveSec=60s", fh.read())

    def test_new_names_cannot_take_the_prefix(self):
        self.assertIn("Kandev", self.m.name_problem("k-mine"))


if __name__ == "__main__":
    main()
