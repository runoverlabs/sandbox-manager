"""Remotes on the laptop: host:name addressing, and ls across hosts."""

import json
import os
import subprocess
from unittest import main, mock

from tests.harness import MsbctlTest

REMOTE_LS = {"msbctl": "0.2.4", "sandboxes": [
    {"name": "app", "state": "running", "source": "repo", "location": "github:acme/app@main",
     "repo": "acme/app", "ref": "", "autostart": True, "updates": []}]}


class Exec(Exception):
    pass


class RemoteTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.add_remote("sbx-01", "msb@sbx-01.example")

    def add_remote(self, name, dest):
        self.m.ensure_local_config()
        self.m.set_toml_key(self.m.CONFIG_FILE, "ssh", dest, table=f"remotes.{name}")

    def execvp(self, *argv, stdin=""):
        """Run msbctl; return the argv it exec'd ssh with (or fail)."""
        seen = {}

        def fake(path, args):
            seen["path"], seen["argv"] = path, args
            raise Exec

        with mock.patch.object(self.m.os, "execvp", fake):
            try:
                code, out, err = self.run_main(*argv, stdin=stdin)
            except Exec:
                return seen["argv"]
        raise self.failureException(f"no exec: {code} {err}")

    def ssh_answers(self, answer):
        """subprocess.run, with every ssh call answered by `answer(argv)`."""
        real = subprocess.run
        calls = []

        def fake(argv, *a, **kw):
            if argv and argv[0] == "ssh":
                calls.append(argv)
                return answer(argv)
            return real(argv, *a, **kw)
        return mock.patch.object(self.m.subprocess, "run", fake), calls

    def test_dotted_table_with_a_dash(self):
        cfg = self.m.load_config()
        self.assertEqual(cfg["remotes"]["sbx-01"]["ssh"], "msb@sbx-01.example")
        self.assertTrue(self.m.remove_toml_table(self.m.CONFIG_FILE, "remotes.sbx-01"))
        self.assertNotIn("sbx-01", self.m.load_config().get("remotes", {}))

    def test_exec_is_a_clean_pipe(self):
        argv = self.execvp("exec", "sbx-01:app", "--", "cat")
        self.assertEqual(argv[0], "ssh")
        self.assertIn("-T", argv)
        self.assertNotIn("-t", argv)
        self.assertEqual(argv[-3:], ["msb@sbx-01.example", "--", "msbctl exec app -- cat"])
        self.assertIn("ControlMaster=auto", argv)

    def test_quoting_survives(self):
        argv = self.execvp("exec", "sbx-01:app", "--", "sh", "-c", 'echo "a b"; echo sbx-01:app')
        self.assertEqual(argv[-1], """msbctl exec app -- sh -c 'echo "a b"; echo sbx-01:app'""")

    def test_shell_and_show(self):
        self.assertEqual(self.execvp("shell", "sbx-01:app", "-u", "root")[-1], "msbctl shell app -u root")
        self.assertEqual(self.execvp("show", "sbx-01:app", "--json")[-1], "msbctl show app --json")

    def test_unknown_remote_and_dot(self):
        code, _, err = self.run_main("show", "nope:app")
        self.assertNotEqual(code, 0)
        self.assertIn("unknown remote", err)
        code, _, err = self.run_main("show", "sbx-01:.")
        self.assertNotEqual(code, 0)
        self.assertIn("give the sandbox's name", err)

    def test_port_and_allow_specs_stay_local(self):
        self.make_folder_sandbox("web")
        for argv in (("port", "web", "3000:5173"), ("allow", "web", "mirror:443")):
            with self.subTest(argv=argv):
                with mock.patch.object(self.m.os, "execvp", side_effect=AssertionError("ssh")):
                    code, out, err = self.run_main(*argv)
                self.assertEqual(code, 0, err)
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            self.assertIn("3000:5173", fh.read())

    def test_a_remote_name_needs_no_msb(self):
        args = self.m.parse_cli(["exec", "sbx-01:app", "--", "cat"])
        with mock.patch.object(self.m.shutil, "which", lambda name: None):
            self.m.preflight(args)                  # does not die
            with self.assertRaises(SystemExit):
                self.m.preflight(self.m.parse_cli(["exec", "web", "--", "cat"]))

    def test_add_remote_forwards_the_rest(self):
        argv = self.execvp("add", "--remote", "sbx-01", "--repo", "acme/app", "-y")
        self.assertEqual(argv[-1], "msbctl add --repo acme/app -y")

    def test_mixed_start(self):
        self.make_folder_sandbox("web")
        patch, calls = self.ssh_answers(lambda argv: subprocess.CompletedProcess(argv, 0, "", ""))
        with patch:
            code, _, err = self.run_main("start", "sbx-01:app", "web", "sbx-01:api")
        self.assertEqual(code, 0, err)
        self.assertEqual([c[-1] for c in calls], ["msbctl start app", "msbctl start api"])
        self.assertEqual(len(self.msb_calls("create")), 1)

    def test_update_keeps_its_flags_after_the_name(self):
        patch, calls = self.ssh_answers(lambda argv: subprocess.CompletedProcess(argv, 3, "", ""))
        with patch:
            code, _, err = self.run_main("update", "sbx-01:app", "-c", "claude", "gh")
        self.assertNotEqual(code, 0)                # the remote's failure is counted
        self.assertEqual(calls[0][-1], "msbctl update app -c claude gh")

    def test_ls_merges_hosts(self):
        self.make_folder_sandbox("web")
        patch, calls = self.ssh_answers(
            lambda argv: subprocess.CompletedProcess(argv, 0, json.dumps(REMOTE_LS), ""))
        with patch:
            code, out, err = self.run_main("ls")
            self.assertEqual(code, 0, err)
            self.assertIn("HOST", out)
            lines = out.splitlines()
            self.assertTrue(any(line.startswith("local") and "web" in line for line in lines))
            self.assertTrue(any(line.startswith("sbx-01") and " app " in line for line in lines))
            self.assertIn("BatchMode=yes", calls[0])
            self.assertEqual(calls[0][-1], "msbctl ls --json")
            code, out, _ = self.run_main("ls", "--porcelain")
            self.assertIn("sbx-01:app\trunning\tgithub:acme/app@main\t-\tyes", out.splitlines())
            code, out, _ = self.run_main("ls", "--picker")
            self.assertTrue(any(line.startswith("sbx-01:app\t") for line in out.splitlines()))

    def test_ls_reports_an_old_host(self):
        patch, _ = self.ssh_answers(lambda argv: subprocess.CompletedProcess(
            argv, 2, "", "usage: msbctl ls [-h] [--refresh]\nmsbctl ls: error: unrecognized arguments: --json"))
        with patch:
            code, out, err = self.run_main("ls")
        self.assertIn("host msbctl too old", out)

    def test_ls_serves_the_cache_when_a_host_is_down(self):
        ok = lambda argv: subprocess.CompletedProcess(argv, 0, json.dumps(REMOTE_LS), "")
        down = lambda argv: subprocess.CompletedProcess(argv, 255, "", "ssh: connect: No route to host")
        patch, _ = self.ssh_answers(ok)
        with patch:
            self.run_main("ls")
        patch, calls = self.ssh_answers(down)
        with patch:
            code, out, _ = self.run_main("ls")
            self.assertIn("unreachable", out)
            self.assertIn("stale", out)
            self.assertIn("app", out)
            # Down a moment ago: not tried again until --refresh.
            self.run_main("ls")
            self.assertEqual(len(calls), 1)
            self.run_main("ls", "--refresh")
            self.assertEqual(len(calls), 2)

    def test_remote_ls_and_rm(self):
        code, out, _ = self.run_main("remote", "ls")
        self.assertIn("msb@sbx-01.example", out)
        code, out, err = self.run_main("remote", "rm", "sbx-01")
        self.assertEqual(code, 0, err)
        self.assertIn("untouched", out)
        code, out, _ = self.run_main("remote", "ls")
        self.assertIn("no remotes", out)

    def test_remote_add_validates(self):
        for name, dest in (("Bad", "msb@x"), ("ok", "-oProxyCommand=evil"), ("ok", "a b")):
            code, _, _ = self.run_main("remote", "add", name, dest)
            self.assertNotEqual(code, 0)

    def test_remote_test_warns_about_an_unrestricted_key(self):
        check = {"msbctl": "0.0.1", "restricted": False, "checks": [
            {"check": "user", "ok": True, "detail": "msb"}]}
        patch, _ = self.ssh_answers(lambda argv: subprocess.CompletedProcess(argv, 0, json.dumps(check), ""))
        with patch:
            code, out, err = self.run_main("remote", "test", "sbx-01")
        self.assertEqual(code, 0, err)
        self.assertIn("can get a shell", err)
        self.assertIn("0.0.1", err)


class NoRemotesTest(MsbctlTest):

    def test_output_is_unchanged(self):
        self.make_folder_sandbox("web")
        code, out, _ = self.run_main("ls", "--porcelain")
        project = os.path.join(self.tmp, "projects", "web")
        self.assertEqual(out, f"web\tabsent\t{project}\t-\tno\n")
        code, out, _ = self.run_main("ls")
        self.assertNotIn("HOST", out)


if __name__ == "__main__":
    main()
