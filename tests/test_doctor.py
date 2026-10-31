"""`msbctl doctor`: one record per check, ok/warn/fail, exit 1 only when
something failed, no prompts, and `remote test` asking a host for it."""

import json
import os
import shutil
import subprocess
from collections import namedtuple
from unittest import main, mock

from tests.harness import MsbctlTest

Usage = namedtuple("Usage", "total used free")
GIB = 1024 ** 3
SECRET = "ghp_doctorTestValue0123456789abcdef"


class DoctorTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.kvm = "rw"
        self.free = 100 * GIB
        self.enterContext(mock.patch.object(self.m, "kvm_status", lambda: self.kvm))
        self.enterContext(mock.patch.object(
            self.m, "msb_disk_usage", lambda: Usage(500 * GIB, 500 * GIB - self.free, self.free)))

    def doctor(self, *extra):
        code, out, err = self.run_main("doctor", "--json", *extra)
        data = json.loads(out)
        return code, {c["id"]: c for c in data["checks"]}, data, err

    def test_a_working_machine(self):
        code, checks, data, err = self.doctor()
        self.assertEqual(code, 0, err)
        self.assertTrue(data["ok"])
        self.assertEqual(set(data), {"msbctl", "restricted", "ok", "checks"})
        for c in data["checks"]:
            self.assertEqual(set(c), {"id", "status", "message", "fix"})
            self.assertIn(c["status"], ("ok", "warn", "fail"))
            self.assertNotEqual(c["status"], "fail", c)
            if c["status"] == "ok":
                self.assertEqual(c["fix"], "")
            else:
                self.assertTrue(c["fix"], c)
        for id in ("kvm", "msb", "python", "git", "disk", "config-dir", "secrets", "secret-store",
                   "swap", "authorized-keys", "registry"):
            self.assertIn(id, checks)
        self.assertEqual(checks["msb"]["status"], "ok")
        self.assertIn("0.7.12", checks["msb"]["message"])
        self.assertNotIn("msb-doctor", checks)      # this fake msb has none

    def test_no_kvm_fails(self):
        for state, words in (("missing", "nested virtualization"), ("denied", "usermod -aG kvm")):
            with self.subTest(state):
                self.kvm = state
                code, checks, data, _ = self.doctor()
                self.assertEqual(code, 1)
                self.assertFalse(data["ok"])
                self.assertEqual(checks["kvm"]["status"], "fail")
                self.assertIn(words, checks["kvm"]["fix"])

    def test_text_report(self):
        self.kvm = "missing"
        code, out, _ = self.run_main("doctor")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  kvm", out)
        self.assertIn("→ msbctl runs on the host", out)
        self.assertIn("1 failed: kvm", out)
        self.kvm = "rw"
        code, out, _ = self.run_main("doctor")
        self.assertEqual(code, 0)
        self.assertIn("this machine can run sandboxes", out)

    def test_msb(self):
        real = shutil.which
        with mock.patch.object(self.m.shutil, "which", lambda n: None if n == "msb" else real(n)):
            code, checks, _, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(checks["msb"]["status"], "fail")
        self.assertIn("install.sh", checks["msb"]["fix"])
        os.environ["FAKE_MSB_VERSION"] = "0.9.1"
        code, checks, _, _ = self.doctor()
        self.assertEqual(code, 0)
        self.assertEqual(checks["msb"]["status"], "warn")
        self.assertIn("0.9.1", checks["msb"]["message"])

    def test_an_older_msb_fails(self):
        # The version msbctl is developed against is also the oldest it supports.
        os.environ["FAKE_MSB_VERSION"] = "0.7.7"
        code, checks, _, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(checks["msb"]["status"], "fail")
        self.assertIn("older than 0.7.12", checks["msb"]["message"])
        self.assertIn("install.sh", checks["msb"]["fix"])

    def test_msb_table_reads_the_json_listing(self):
        listing = json.dumps([{"name": "web", "status": "Running"}, {"name": "api", "status": "Stopped"},
                              {"name": "odd"}, "not a row", {"status": "Running"}])
        done = subprocess.CompletedProcess(["msb"], 0, listing, "")
        with mock.patch.object(self.m.subprocess, "run", lambda *a, **k: done):
            self.assertEqual(self.m.msb_table(), {"web": "running", "api": "stopped"})
        for out, code in (("not json", 0), ("[]", 1), ('{"name": "web"}', 0)):
            bad = subprocess.CompletedProcess(["msb"], code, out, "")
            with mock.patch.object(self.m.subprocess, "run", lambda *a, _b=bad, **k: _b):
                self.assertEqual(self.m.msb_table(), {}, out)

    def test_every_other_command_refuses_an_older_msb(self):
        self.assertIsNone(self.m.local_problem())
        os.environ["FAKE_MSB_VERSION"] = "0.7.11"
        self.assertIn("older than 0.7.12", self.m.local_problem())
        os.environ["FAKE_MSB_VERSION"] = "0.10.0"     # numbers, not strings: 10 > 7
        self.assertIsNone(self.m.local_problem())

    def test_msb_doctor_when_msb_has_one(self):
        for mode, status, words in (("ok", "ok", "host setup is ready"),
                                    ("warn", "warn", "Root clone: copy fallback"),
                                    ("fail", "fail", "KVM access          permission denied")):
            with self.subTest(mode):
                os.environ["FAKE_MSB_DOCTOR"] = mode
                code, checks, _, _ = self.doctor()
                self.assertEqual(checks["msb-doctor"]["status"], status)
                self.assertIn(words, checks["msb-doctor"]["message"])
                self.assertEqual(code, 1 if status == "fail" else 0)
        self.assertIn("/dev/kvm is not accessible", checks["msb-doctor"]["message"])
        self.assertIn("msb doctor --fix", checks["msb-doctor"]["fix"])

    def test_disk(self):
        for gib, status, code_wanted in ((50, "ok", 0), (5, "warn", 0), (1, "fail", 1)):
            with self.subTest(gib):
                self.free = gib * GIB
                code, checks, _, _ = self.doctor()
                self.assertEqual(checks["disk"]["status"], status)
                self.assertEqual(code, code_wanted)

    def test_registry(self):
        project = self.make_folder_sandbox("web")
        self.make_folder_sandbox("api")
        os.rename(project, project + ".moved")
        with open(self.entry_path("bad"), "w", encoding="utf-8") as fh:
            fh.write('name = "bad"\nsource = "bogus"\n')
        self.set_state(api="running", stray="stopped")
        code, checks, _, _ = self.doctor()
        self.assertEqual(code, 0)       # each is about one sandbox
        self.assertEqual(checks["registry"]["status"], "warn")
        self.assertIn("bad (bad.toml: source is 'bogus'", checks["registry"]["message"])
        self.assertEqual(checks["project-missing"]["status"], "warn")
        self.assertIn("web", checks["project-missing"]["message"])
        self.assertNotIn("api", checks["project-missing"]["message"])
        self.assertEqual(checks["orphans"]["status"], "warn")
        self.assertIn("stray", checks["orphans"]["message"])
        self.assertNotIn("api", checks["orphans"]["message"])

    def test_an_entry_that_does_not_parse_is_a_finding(self):
        self.make_folder_sandbox("web")
        with open(self.entry_path("web"), "a", encoding="utf-8") as fh:
            fh.write("autostart = true\n")
        with open(self.entry_path("bad"), "w", encoding="utf-8") as fh:
            fh.write("[[[ not toml\n")
        code, checks, _, err = self.doctor()
        self.assertEqual(code, 0, err)
        self.assertEqual(checks["registry"]["status"], "warn")
        self.assertIn("bad (", checks["registry"]["message"])
        self.assertIn("1 sandbox(es) marked autostart", checks["autostart"]["message"])

    def test_a_secret_file_that_vanishes_is_skipped(self):
        os.makedirs(self.m.SECRETS_DIR, mode=0o700, exist_ok=True)
        os.chmod(self.m.SECRETS_DIR, 0o700)
        os.symlink("/nonexistent", os.path.join(self.m.SECRETS_DIR, "old.env"))
        code, checks, _, err = self.doctor()
        self.assertEqual(code, 0, err)
        self.assertEqual(checks["secrets"]["status"], "ok")

    def test_an_msb_that_hangs_or_will_not_run(self):
        real = subprocess.run
        for exc in (subprocess.TimeoutExpired(["msb"], 15), PermissionError(13, "Permission denied")):
            with self.subTest(type(exc).__name__):
                def fake(argv, *a, exc=exc, **kw):
                    if argv and argv[0] == "msb" and argv[1:] in (["--help"], ["--version"]):
                        raise exc
                    return real(argv, *a, **kw)
                with mock.patch.object(self.m.subprocess, "run", fake):
                    code, checks, _, err = self.doctor()
                self.assertEqual(code, 0, err)
                self.assertEqual(checks["msb"]["status"], "warn")
                self.assertNotIn("msb-doctor", checks)

    def test_ssh_agent_only_when_a_sandbox_may_use_a_key(self):
        self.make_folder_sandbox("web")         # ssh_keys = []: no agent needed
        _, checks, _, _ = self.doctor()
        self.assertNotIn("ssh-agent", checks)
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            text = fh.read().replace("ssh_keys = []\n", "")
        with open(self.entry_path("web"), "w", encoding="utf-8") as fh:
            fh.write(text)
        code, checks, _, _ = self.doctor()
        self.assertEqual(code, 0)
        self.assertEqual(checks["ssh-agent"]["status"], "warn")
        self.assertIn("web", checks["ssh-agent"]["message"])

    def test_a_broken_config_is_reported(self):
        self.m.ensure_local_config()
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("\n[[[ not toml\n")
        code, checks, _, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(checks["config"]["status"], "fail")
        self.assertNotIn("registry", checks)
        self.assertNotIn("secret-store", checks)    # one cause, one failure

    def test_kandev_key_sees_no_operator_sandbox(self):
        self.make_folder_sandbox("web")
        with open(self.entry_path("web"), "a", encoding="utf-8") as fh:
            fh.write("autostart = true\n")
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", SECRET)
        os.chmod(self.secrets_file("web"), 0o644)
        with open(self.entry_path("k-lab"), "w", encoding="utf-8") as fh:
            fh.write('name = "k-lab"\nsource = "kandev"\nkandev_env = "lab"\n')
        with open(self.entry_path("k-bad"), "w", encoding="utf-8") as fh:
            fh.write("[[[ not toml\n")
        self.set_state(stray="stopped", **{"k-lab": "running", "k-orphan": "running"})
        state = self.fake_state()
        state["_labels"] = {"k-lab": ["msbctl.owner=kandev"], "k-orphan": ["msbctl.owner=kandev"]}
        with open(os.environ["FAKE_MSB_STATE"], "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.environ["MSB_RESTRICTED"] = "kandev"
        code, checks, data, err = self.doctor()
        self.assertEqual(code, 0, err)
        self.assertTrue(data["restricted"])
        # The host, in full; the operator's sandboxes, not at all.
        for id in ("kvm", "msb", "disk", "swap", "authorized-keys"):
            self.assertIn(id, checks)
        for id in ("github-token", "secret-store", "autostart"):
            self.assertNotIn(id, checks)
        self.assertEqual(checks["secrets"]["status"], "warn")
        self.assertIn("not 0600: 1 file(s)", checks["secrets"]["message"])
        # Kandev's own entries and VMs, with what is wrong with them.
        self.assertEqual(checks["registry"]["status"], "warn")
        self.assertIn("2 Kandev sandbox(es)", checks["registry"]["message"])
        self.assertIn("k-bad (", checks["registry"]["message"])
        self.assertEqual(checks["orphans"]["status"], "warn")
        self.assertIn("k-orphan", checks["orphans"]["message"])
        text = json.dumps(data)
        for name in ("web", "stray", "GH_TOKEN"):
            self.assertNotIn(name, text)
        self.assert_not_in_output(SECRET, text, err)

    def test_never_prints_a_secret(self):
        self.make_folder_sandbox("web")
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", SECRET)
        code, out, err = self.run_main("doctor", "--json")
        self.assertEqual(code, 0, err)
        self.assert_not_in_output(SECRET, out, err)
        checks = {c["id"]: c for c in json.loads(out)["checks"]}
        self.assertEqual(checks["github-token"]["status"], "ok")
        code, out, err = self.run_main("doctor")
        self.assert_not_in_output(SECRET, out, err)

    def test_host_check_keeps_its_shape(self):
        self.kvm = "missing"
        code, out, err = self.run_main("host", "check", "--json")
        self.assertEqual(code, 0, err)      # host check never failed, and still does not
        data = json.loads(out)
        kvm = next(c for c in data["checks"] if c["check"] == "kvm")
        self.assertEqual(set(kvm), {"check", "ok", "detail"})
        self.assertIs(kvm["ok"], False)


class RemoteDoctorTest(MsbctlTest):
    """`remote test` reads the host's doctor, or an older host's host check."""

    def setUp(self):
        super().setUp()
        self.m.ensure_local_config()
        self.m.set_toml_key(self.m.CONFIG_FILE, "ssh", "msb@sbx-01.example", table="remotes.sbx-01")
        self.mine = self.m.version_string().split()[0]

    def remote_test(self, answer):
        real = subprocess.run
        calls = []

        def fake(argv, *a, **kw):
            if argv and argv[0] == "ssh":
                calls.append(argv[-1])
                return answer(argv)
            return real(argv, *a, **kw)
        with mock.patch.object(self.m.subprocess, "run", fake):
            code, out, err = self.run_main("remote", "test", "sbx-01")
        with open(os.path.join(self.m.REMOTES_DIR, "sbx-01.test.json"), encoding="utf-8") as fh:
            return code, out, err, calls, json.load(fh)

    def test_a_failed_check_there_is_a_problem(self):
        doctor = {"msbctl": self.mine, "restricted": True, "ok": False, "checks": [
            {"id": "kvm", "status": "fail", "message": "no /dev/kvm", "fix": "a host with KVM"}]}
        code, out, err, calls, cached = self.remote_test(
            lambda argv: subprocess.CompletedProcess(argv, 1, json.dumps(doctor), ""))
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, ["msbctl doctor --json"])
        self.assertIn("FAIL  kvm", out)
        self.assertIn("→ a host with KVM", out)
        self.assertFalse(cached["ok"])
        self.assertIn("failed: kvm", cached["summary"])

    def test_an_older_host_is_asked_for_host_check(self):
        check = {"msbctl": self.mine, "restricted": True, "checks": [
            {"check": "swap", "ok": False, "detail": "/dev/sda2 — not encrypted"},
            {"check": "restricted", "ok": None, "detail": "yes"}]}

        def answer(argv):
            if "doctor" in argv[-1]:
                return subprocess.CompletedProcess(argv, 126, "", "msbctl host serve: refused\n")
            return subprocess.CompletedProcess(argv, 0, json.dumps(check), "")
        code, out, err, calls, cached = self.remote_test(answer)
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, ["msbctl doctor --json", "msbctl host check --json"])
        self.assertIn("WARN  swap", out)
        self.assertIn("ok    restricted", out)
        self.assertTrue(cached["ok"], cached)

    def test_an_older_host_without_msb_or_kvm_failed(self):
        check = {"msbctl": self.mine, "restricted": True, "checks": [
            {"check": "msb", "ok": False, "detail": "no /dev/kvm"}]}

        def answer(argv):
            if "doctor" in argv[-1]:
                return subprocess.CompletedProcess(argv, 2, "", "invalid choice: 'doctor'\n")
            return subprocess.CompletedProcess(argv, 0, json.dumps(check), "")
        _, out, _, _, cached = self.remote_test(answer)
        self.assertIn("FAIL  msb", out)
        self.assertFalse(cached["ok"])
        self.assertIn("failed: msb", cached["summary"])


if __name__ == "__main__":
    main()
