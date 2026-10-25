"""git_checkstat: core.checkStat=minimal in a mounted project's repos, so a
host editor's git does not rewrite .git/index under the guest's."""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import main, mock

from tests.harness import MsbctlTest


class GitCheckstatTest(MsbctlTest):

    def box(self, entry_extra=""):
        self.make_folder_sandbox("web", entry_extra=entry_extra)
        return self.m.Sandbox("web", self.m.load_config())

    def defaults(self, text):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write("[defaults]\n" + text)

    def checkstat_calls(self, box):
        self.m.ensure_git_checkstat(box)
        return [c["argv"] for c in self.msb_calls("exec")
                if "core.checkStat" in " ".join(c["argv"])]

    def test_on_by_default_in_the_project_folder(self):
        box = self.box()
        self.assertIs(box.git_checkstat, True)
        (argv,) = self.checkstat_calls(box)
        self.assertEqual(argv[argv.index("--workdir") + 1], box.guest_project)

    def test_the_entry_turns_it_off(self):
        self.assertEqual(self.checkstat_calls(self.box("git_checkstat = false\n")), [])

    def test_the_entry_wins_over_defaults(self):
        self.defaults("git_checkstat = false\n")
        self.assertEqual(self.checkstat_calls(self.box()), [])
        self.fresh()
        self.defaults("git_checkstat = false\n")
        self.assertEqual(len(self.checkstat_calls(self.box("git_checkstat = true\n"))), 1)

    def test_not_a_boolean_dies(self):
        with self.assertRaises(SystemExit):
            self.box('git_checkstat = "yes"\n')

    def test_a_bad_default_names_config_toml(self):
        self.defaults('git_checkstat = "no"\n')
        with mock.patch.object(self.m, "die", side_effect=SystemExit) as die:
            with self.assertRaises(SystemExit):
                self.box()
        self.assertIn("config.toml", die.call_args[0][0])

    def test_read_write_extra_mounts_are_walked_too(self):
        extra = [tempfile.mkdtemp(dir=self.tmp) for _ in range(2)]
        box = self.box(f'mounts = ["{extra[0]}:/lib:rw", "{extra[1]}:/ref:ro"]\n')
        (argv,) = self.checkstat_calls(box)
        self.assertEqual(argv[-2:], [box.guest_project, "/lib"])

    def test_show_and_the_profile_say_which(self):
        box = self.box()
        self.assertIs(self.m.show_data(box)["git_checkstat"], True)
        self.assertIn(self.m.GIT_CHECKSTAT_PROFILE[True], self.m.sandbox_profile_section(box))
        self.fresh()
        box = self.box("git_checkstat = false\n")
        self.assertIs(self.m.show_data(box)["git_checkstat"], False)
        self.assertIn(self.m.GIT_CHECKSTAT_PROFILE[False], self.m.sandbox_profile_section(box))

    def test_never_touches_a_kandev_sandbox(self):
        os.makedirs(self.m.REGISTRY_DIR, exist_ok=True)
        with open(self.entry_path("k-lab"), "w", encoding="utf-8") as fh:
            fh.write('name = "k-lab"\nsource = "kandev"\nkandev_env = "lab"\n')
        box = self.m.Sandbox("k-lab", self.m.load_config())
        self.assertIs(box.shares_host_index, False)
        self.assertEqual(self.checkstat_calls(box), [])
        self.assertTrue(self.m._summary_git_checkstat(box).startswith("not needed"))

    def test_edit_writes_only_a_difference_from_defaults(self):
        box = self.box()
        path = self.entry_path("web")
        with mock.patch.object(self.m, "choose_one", lambda title, opts, d=0: opts[1]):
            self.m.section_git_checkstat(box, self.m.load_config(), {"rebuild": set()})
        self.assertIs(self.m.read_toml(path)["git_checkstat"], False)
        box = self.m.Sandbox("web", self.m.load_config())
        with mock.patch.object(self.m, "choose_one", lambda title, opts, d=0: opts[0]):
            self.m.section_git_checkstat(box, self.m.load_config(), {"rebuild": set()})
        self.assertNotIn("git_checkstat", self.m.read_toml(path))

    def test_edit_walks_a_running_sandbox_only_when_turned_on(self):
        box = self.box()
        with mock.patch.object(self.m, "choose_one", lambda title, opts, d=0: opts[0]), \
             mock.patch.object(self.m, "state_of", lambda name: "running"):
            self.m.section_git_checkstat(box, self.m.load_config(), {"rebuild": set()})
            self.assertEqual(self.msb_calls("exec"), [])    # already on
            box.git_checkstat = False
            self.m.section_git_checkstat(box, self.m.load_config(), {"rebuild": set()})
        (call,) = self.msb_calls("exec")
        self.assertEqual(call["argv"][call["argv"].index("--") + 7], "1")   # forced


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitCheckstatScriptTest(MsbctlTest):
    """The guest-side script itself, run by a real sh against real repos."""

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=False).stdout.strip()

    def script(self, force=False):
        """The guest-side argv, with the project root pointed at self.work."""
        self.make_folder_sandbox("web")
        box = self.m.Sandbox("web", self.m.load_config())
        with mock.patch.object(self.m, "GIT_CHECKSTAT_MARKER", self.marker), \
             mock.patch.object(self.m, "GIT_CHECKSTAT_BOOT_ID", self.boot_id):
            self.m.ensure_git_checkstat(box, force)
        argv = self.msb_calls("exec")[-1]["argv"]
        argv = argv[argv.index("--") + 1:]
        return [self.work if a == box.guest_project else a for a in argv]

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp, "marker")
        self.boot_id = os.path.join(self.tmp, "boot_id")
        self.boot("boot-1")
        self.work = tempfile.mkdtemp(dir=self.tmp)

    def boot(self, ident):
        with open(self.boot_id, "w", encoding="utf-8") as fh:
            fh.write(ident + "\n")

    def run_script(self, argv, env=None):
        subprocess.run(argv, cwd=self.work, check=True, env=env)

    def init(self, rel):
        path = os.path.join(self.work, rel)
        os.makedirs(path, exist_ok=True)
        self.git("init", "-q", ".", cwd=path)
        return path

    def checkstat(self, rel):
        return self.git("config", "--local", "--get", "core.checkStat",
                        cwd=os.path.join(self.work, rel))

    def unset(self, rel):
        self.git("config", "--local", "--unset", "core.checkStat",
                 cwd=os.path.join(self.work, rel))

    def test_which_repos_it_sets(self):
        repos = {".": "minimal", "a": "minimal", "g/b": "minimal", "set": "default",
                 "node_modules/x": "", "g/node_modules": "", "g/h/deep": "",
                 ".hidden/r": ""}
        for rel in repos:
            self.init(rel)
        self.git("config", "core.checkStat", "default", cwd=os.path.join(self.work, "set"))
        # A linked worktree's .git is a file naming a gitdir elsewhere: skipped.
        os.makedirs(os.path.join(self.work, "wt"))
        with open(os.path.join(self.work, "wt", ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: /nonexistent\n")
        # A checkout reached through a symlink is covered, as a glob follows it.
        shared = tempfile.mkdtemp(dir=self.tmp)
        self.git("init", "-q", ".", cwd=shared)
        os.symlink(shared, os.path.join(self.work, "api"))
        self.run_script(self.script())
        for rel, want in repos.items():
            with self.subTest(rel):
                self.assertEqual(self.checkstat(rel), want)
        self.assertEqual(self.checkstat("api"), "minimal")

    def test_a_repo_owned_by_another_user_is_still_set(self):
        # The guest's case: root, over files presented as the host user.
        if os.geteuid() != 0:
            self.skipTest("needs root to own files as someone else")
        self.init("g/b")
        for root, dirs, files in os.walk(self.work):
            for name in [root] + [os.path.join(root, f) for f in dirs + files]:
                os.lchown(name, 65534, 65534)
        self.run_script(self.script())
        self.assertEqual(self.git("-c", "safe.directory=*", "config", "--local", "--get",
                                  "core.checkStat", cwd=os.path.join(self.work, "g/b")),
                         "minimal")

    def test_skipped_until_the_repos_or_the_boot_change(self):
        self.init(".")
        self.run_script(self.script())
        with open(self.marker, encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith("boot-1\n"))
        # Same boot, same repos: no git runs, so an unset value stays unset.
        self.unset(".")
        self.run_script(self.script())
        self.assertEqual(self.checkstat("."), "")
        # A repo cloned since changes the list, and the walk runs again.
        self.init("late")
        self.run_script(self.script())
        self.assertEqual((self.checkstat("."), self.checkstat("late")), ("minimal", "minimal"))
        # A new boot walks again too.
        self.unset(".")
        self.boot("boot-2")
        self.run_script(self.script())
        self.assertEqual(self.checkstat("."), "minimal")

    def test_forced_walks_regardless(self):
        self.init(".")
        self.run_script(self.script())
        self.unset(".")
        self.run_script(self.script(force=True))
        self.assertEqual(self.checkstat("."), "minimal")

    def test_no_git_leaves_no_marker(self):
        self.init(".")
        bindir = tempfile.mkdtemp(dir=self.tmp)
        os.symlink(shutil.which("cat"), os.path.join(bindir, "cat"))
        argv = self.script()
        self.run_script([shutil.which("sh"), *argv[1:]], env={"PATH": bindir})
        self.assertFalse(os.path.exists(self.marker))
        self.run_script(argv)
        self.assertEqual(self.checkstat("."), "minimal")

    def test_a_failed_repo_leaves_no_marker(self):
        self.init(".")
        os.chmod(os.path.join(self.work, ".git", "config"), 0o444)
        os.chmod(os.path.join(self.work, ".git"), 0o555)
        self.addCleanup(os.chmod, os.path.join(self.work, ".git"), 0o755)
        if os.access(os.path.join(self.work, ".git"), os.W_OK):
            self.skipTest("running as root: permissions do not stop git")
        self.run_script(self.script())
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    main()
