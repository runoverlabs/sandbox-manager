"""Setting a remote host up from here, and putting a new sandbox on one."""

import base64
import json
import os
import subprocess
from unittest import main, mock

from tests.harness import MsbctlTest

KEY = "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x0bssh-ed25519" + b"k" * 36).decode() + " me@laptop"
OTHER = "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x0bssh-ed25519" + b"o" * 36).decode() + " other"
CHECK = {"msbctl": "0.0.0", "restricted": True, "checks": []}


def probe(**over):
    # The fake msb here says 0.7.7: the same, so no test meets a mismatch by accident.
    values = {"user": "msb", "path": "", "bare": "", "msb": "msb 0.7.7", "msbctl": "", "kvm": "rw",
              "curl": "/usr/bin/curl",
              "linger": "yes", "unit": "yes", "sudo": "no", **over}
    return "".join(f"{k}={v}\n" for k, v in values.items())


class RemoteSetupTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.m.ensure_local_config()
        self.m.set_toml_key(self.m.CONFIG_FILE, "ssh", "msb@sbx-01.example", table="remotes.sbx-01")
        self.mine = self.m.version_string().split()[0]
        self.enterContext(mock.patch.object(self.m, "remote_key_candidates", lambda: [("agent", KEY)]))
        # Numbered prompts, even where a test claims a terminal.
        self.enterContext(mock.patch.dict(os.environ, {"TERM": "dumb"}))

    def ssh(self, probe_text="", probe_code=0, probe_err="", grep=""):
        """subprocess.run with every ssh call answered by what it runs."""
        real = subprocess.run
        calls = []

        def fake(argv, *a, **kw):
            if not argv or argv[0] != "ssh":
                return real(argv, *a, **kw)
            calls.append(argv)
            cmd = argv[-1]
            if "linger=" in cmd:
                return subprocess.CompletedProcess(argv, probe_code, probe_text, probe_err)
            if "grep -F" in cmd:
                return subprocess.CompletedProcess(argv, 0 if grep else 1, grep, "")
            if "host check --json" in cmd:
                return subprocess.CompletedProcess(argv, 0, json.dumps(CHECK), "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return mock.patch.object(self.m.subprocess, "run", fake), calls

    def commands(self, calls):
        return [c[-1] for c in calls]

    def test_installs_what_is_missing_when_asked(self):
        CHECK["msbctl"] = self.mine
        patch, calls = self.ssh(probe(msb="", msbctl="", linger="no", unit="no"))
        with patch:
            # msb: yes; msbctl: yes; autostart: no; key: not now.
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="y\ny\nn\n2\n")
        self.assertEqual(code, 0, err)
        cmds = self.commands(calls)
        # msb at this machine's version, through that release's own installer.
        pinned = [c for c in cmds if "get_latest_version" in c]
        self.assertEqual(len(pinned), 1, cmds)
        self.assertTrue(pinned[0].endswith(f"sh {self.m.MSB_RELEASES} 0.7.7"), pinned[0])
        self.assertTrue(any("get.sh" in c and "| sh" in c for c in cmds), cmds)
        self.assertFalse(any("host autostart" in c or "authorize" in c for c in cmds), cmds)
        self.assertTrue(any("host check --json" in c for c in cmds))

    def test_a_different_msb_there_is_offered_this_one(self):
        patch, calls = self.ssh(probe(msb="msb 0.7.8", msbctl=f"msbctl {self.mine}"))
        with patch:
            # replace: no; key: not now.
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="n\n\n")
        self.assertEqual(code, 0, err)
        self.assertIn("msb 0.7.8 on sbx-01, 0.7.7 here", err)
        self.assertIn("replace msb 0.7.8 on sbx-01 with 0.7.7?", out)
        self.assertFalse(any("get_latest_version" in c for c in self.commands(calls)))
        patch, calls = self.ssh(probe(msb="msb 0.7.8", msbctl=f"msbctl {self.mine}"))
        with patch:
            self.run_main("remote", "setup", "sbx-01", stdin="y\n\n")
        self.assertTrue(any(c.endswith(f"sh {self.m.MSB_RELEASES} 0.7.7") for c in self.commands(calls)))

    def test_without_msb_here_the_latest(self):
        patch, calls = self.ssh(probe(msb="", msbctl=f"msbctl {self.mine}"))
        with patch, mock.patch.object(self.m, "local_msb_version", lambda: None):
            self.run_main("remote", "setup", "sbx-01", stdin="y\n\n")
        cmds = self.commands(calls)
        self.assertTrue(any(self.m.MSB_INSTALLER in c for c in cmds), cmds)
        self.assertFalse(any("get_latest_version" in c for c in cmds))

    def test_the_pinned_installer_script_is_valid_sh(self):
        proc = subprocess.run(["sh", "-n", "-c", self.m.MSB_PINNED_INSTALL])
        self.assertEqual(proc.returncode, 0)

    def program(self):
        return self.m.load_config()["remotes"]["sbx-01"].get("msbctl", "msbctl")

    def test_msbctl_off_the_ssh_path_is_used_by_its_path(self):
        found = "/home/msb/.local/bin/msbctl"
        patch, calls = self.ssh(probe(msbctl=f"msbctl {self.mine}", path=found))
        with patch:
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.program(), found)
        self.assertIn(f"using {found}", out)
        self.assertEqual(calls[-1][-1], f"{found} host check --json")
        patch, calls = self.ssh()
        with patch:
            self.run_main("ls")
        self.assertEqual(calls[0][-1], f"{found} ls --json")

    def test_on_the_ssh_path_it_stays_bare(self):
        patch, _ = self.ssh(probe(msbctl=f"msbctl {self.mine}", path="/usr/bin/msbctl", bare="/usr/bin/msbctl"))
        with patch:
            self.run_main("remote", "setup", "sbx-01", stdin="\n")
        self.assertEqual(self.program(), "msbctl")

    def test_restricting_the_key_forgets_the_path(self):
        found = "/home/msb/.local/bin/msbctl"
        patch, _ = self.ssh(probe(msbctl=f"msbctl {self.mine}", path=found), grep=KEY + "\n")
        with patch:
            code, _, err = self.run_main("remote", "setup", "sbx-01", stdin="1\ny\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.program(), "msbctl")

    def test_ls_says_what_to_do_about_a_missing_msbctl(self):
        real = subprocess.run

        def fake(argv, *a, **kw):
            if argv and argv[0] == "ssh":
                return subprocess.CompletedProcess(argv, 127, "", "bash: line 1: msbctl: command not found\n")
            return real(argv, *a, **kw)
        with mock.patch.object(self.m.subprocess, "run", fake):
            code, out, err = self.run_main("ls")
        self.assertIn("msbctl remote setup sbx-01", out)

    def test_a_checkout_offers_the_release_it_started_from(self):
        patch, calls = self.ssh(probe())
        with patch:
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="n\n")
        base = self.mine.split("+")[0]
        self.assertIn(f"install msbctl v{base}", out)

    def test_a_bad_recorded_program_is_refused(self):
        self.m.set_toml_key(self.m.CONFIG_FILE, "msbctl", "msbctl; rm -rf ~", table="remotes.sbx-01")
        code, _, err = self.run_main("ls")
        self.assertNotEqual(code, 0)
        self.assertIn("not `msbctl` or an absolute path", err)

    def test_nothing_runs_without_a_yes(self):
        patch, calls = self.ssh(probe(msb="", msbctl="", unit="no"))
        with patch:
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="n\nn\n")
        self.assertEqual(code, 0, err)
        cmds = self.commands(calls)
        self.assertFalse(any("| sh" in c for c in cmds))
        # No msbctl there: autostart, the key and the test are not offered.
        self.assertIn("nothing more to set up", out)
        self.assertFalse(any("host " in c for c in cmds), cmds)

    def test_the_key_prompt_defaults_to_not_now(self):
        patch, calls = self.ssh(probe(msbctl=f"msbctl {self.mine}"), grep=KEY + "\n")
        with patch:
            code, _, err = self.run_main("remote", "setup", "sbx-01", stdin="\n")
        self.assertEqual(code, 0, err)
        self.assertFalse(any("host authorize" in c for c in self.commands(calls)))

    def test_restricting_the_key_this_connection_uses(self):
        patch, calls = self.ssh(probe(msbctl=f"msbctl {self.mine}"), grep=KEY + "\n")
        with patch:
            code, out, err = self.run_main("remote", "setup", "sbx-01", stdin="1\ny\n")
        self.assertEqual(code, 0, err)
        self.assertIn("no longer will", err)
        authorize = [c for c in calls if "host authorize" in c[-1]]
        self.assertEqual(len(authorize), 1)
        self.assertIn("--replace", authorize[0][-1])
        self.assertIn(KEY.split()[1], authorize[0][-1])
        # The shared connection still has the shell: it is closed.
        self.assertTrue(any("-O" in c and "exit" in c for c in calls))

    def test_declining_the_warning_leaves_the_key(self):
        patch, calls = self.ssh(probe(msbctl=f"msbctl {self.mine}"), grep=KEY + "\n")
        with patch:
            self.run_main("remote", "setup", "sbx-01", stdin="1\nn\n")
        self.assertFalse(any("host authorize" in c for c in self.commands(calls)))

    def test_a_restricted_key_is_already_set_up(self):
        patch, calls = self.ssh(probe_code=126, probe_err="msbctl host serve: refused: sh is not msbctl\n")
        with patch:
            code, out, err = self.run_main("remote", "setup", "sbx-01")
        self.assertEqual(code, 0, err)
        self.assertIn("already runs", out)
        self.assertFalse(any("| sh" in c for c in self.commands(calls)))

    def test_no_kvm_is_the_end(self):
        patch, _ = self.ssh(probe(kvm="missing"))
        with patch:
            code, _, err = self.run_main("remote", "setup", "sbx-01")
        self.assertNotEqual(code, 0)
        self.assertIn("no /dev/kvm", err)

    def test_add_asks_where_and_hands_the_rest_to_the_host(self):
        patch, calls = self.ssh()
        with patch:
            # where: 2 = sbx-01; repo; name (default); start now: no.
            code, out, err = self.run_main("add", stdin="2\nacme/web-app\n\nn\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn("msbctl add --repo acme/web-app --name web-app", self.commands(calls))
        self.assertIn("sbx-01:web-app", out)
        self.assertEqual(self.msb_calls(), [])

    def test_add_on_a_host_without_msbctl_offers_setup(self):
        real = subprocess.run

        def fake(argv, *a, **kw):
            if argv and argv[0] == "ssh":
                return subprocess.CompletedProcess(argv, 127, "", "bash: line 1: msbctl: command not found\n")
            return real(argv, *a, **kw)
        with mock.patch.object(self.m.subprocess, "run", fake):
            # where: 2 = sbx-01; set it up now: no.
            code, out, err = self.run_main("add", stdin="2\nn\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("has no msbctl", err)
        self.assertIn("remote setup sbx-01", err)
        self.assertNotIn("GitHub repo", out)

    def test_add_here_still_works(self):
        patch, calls = self.ssh()
        with patch:
            # where: 1 = this machine; then the folder wizard, cancelled.
            self.run_main("add", stdin="1\n", tty=True)
        self.assertEqual(calls, [])

    def test_status_shows_the_remotes_from_the_cache(self):
        self.m.write_json(self.m._remote_cache_path("sbx-01"), {"at": 1, "sandboxes": [
            {"name": "app", "state": "running", "location": "github:acme/app@main"}]})
        code, out, err = self.run_main("status", "--quick")
        self.assertEqual(code, 0, err)
        self.assertIn("sbx-01:app", out)
        self.assertIn("github:acme/app@main", out)

    def test_a_laptop_without_msb_drives_remotes(self):
        with mock.patch.object(self.m.shutil, "which", lambda cmd: None):
            for argv in (["status", "--quick"], ["ls"], ["add"], []):
                with self.subTest(argv=argv):
                    self.m.preflight(self.m.parse_cli(argv))       # does not die
            with self.assertRaises(SystemExit):
                self.m.preflight(self.m.parse_cli(["start", "web"]))

    def test_the_menu_has_remote_hosts(self):
        keys = [key for key, _ in self.m.MENU]
        with mock.patch.object(self.m.shutil, "which", lambda cmd: None):
            # remote hosts; then sbx-01 is row 1, "add" 2, "back" 3.
            code, out, err = self.run_main(stdin=f"{keys.index('remotes') + 1}\n3\nq\n")
        self.assertEqual(code, 0, err)
        self.assertIn("msb@sbx-01.example", out)


class AuthorizeReplaceTest(MsbctlTest):

    def test_replace_rewrites_only_that_key(self):
        path = self.m.authorized_keys_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"{OTHER}\n{KEY}\n")
        code, _, err = self.run_main("host", "authorize", KEY)
        self.assertNotEqual(code, 0)
        self.assertIn("--replace", err)
        code, _, err = self.run_main("host", "authorize", KEY, "--replace")
        self.assertEqual(code, 0, err)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines[0], OTHER)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("restrict,pty,command="))
        self.assertIn("host serve", lines[1])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    main()
