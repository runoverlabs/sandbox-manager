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

    def test_show_and_the_profile_say_which(self):
        box = self.box()
        self.assertIs(self.m.show_data(box)["git_checkstat"], True)
        self.assertIn(self.m.GIT_CHECKSTAT_PROFILE[True], self.m.sandbox_profile_section(box))
        self.fresh()
        box = self.box("git_checkstat = false\n")
        self.assertIs(self.m.show_data(box)["git_checkstat"], False)
        self.assertIn(self.m.GIT_CHECKSTAT_PROFILE[False], self.m.sandbox_profile_section(box))

    def test_show_json_is_null_where_it_does_not_apply(self):
        box = self.box()
        box.is_repo, box.shares_host_index = True, False
        self.assertIsNone(self.m.show_data(box)["git_checkstat"])
        self.assertNotIn(self.m.GIT_CHECKSTAT_PROFILE[True], self.m.sandbox_profile_section(box))

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


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitCheckstatScriptTest(MsbctlTest):
    """The guest-side script itself, run by a real sh against real repos."""

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=False).stdout.strip()

    def script(self, force=False):
        self.make_folder_sandbox("web")
        with mock.patch.object(self.m, "GIT_CHECKSTAT_MARKER", self.marker):
            self.m.ensure_git_checkstat(self.m.Sandbox("web", self.m.load_config()), force)
        return [c["argv"] for c in self.msb_calls("exec")
                if "core.checkStat" in " ".join(c["argv"])][-1][-1]

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.tmp, "marker")
        self.work = tempfile.mkdtemp(dir=self.tmp)

    def run_script(self, script):
        subprocess.run(["sh", "-c", script], cwd=self.work, check=True)

    def init(self, rel):
        path = os.path.join(self.work, rel)
        os.makedirs(path, exist_ok=True)
        self.git("init", "-q", ".", cwd=path)
        return path

    def checkstat(self, rel):
        return self.git("config", "--local", "--get", "core.checkStat",
                        cwd=os.path.join(self.work, rel))

    def test_which_repos_it_sets(self):
        repos = {".": "minimal", "a": "minimal", "g/b": "minimal", "set": "default",
                 "node_modules/x": "", "g/h/deep": "", ".hidden/r": ""}
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

    def test_once_per_boot_unless_forced(self):
        self.run_script(self.script())
        self.init("late")
        self.run_script(self.script())
        boot_id = "/proc/sys/kernel/random/boot_id"
        if os.path.exists(boot_id):
            self.assertEqual(self.checkstat("late"), "")    # this boot already walked
            with open(self.marker, encoding="utf-8") as fh, open(boot_id, encoding="utf-8") as b:
                self.assertEqual(fh.read(), b.read())
        self.run_script(self.script(force=True))
        self.assertEqual(self.checkstat("late"), "minimal")

if __name__ == "__main__":
    main()
