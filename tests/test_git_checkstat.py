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

    def test_which_repos_it_sets(self):
        self.make_folder_sandbox("web")
        self.m.ensure_git_checkstat(self.m.Sandbox("web", self.m.load_config()))
        (call,) = [c["argv"] for c in self.msb_calls("exec")
                   if "core.checkStat" in " ".join(c["argv"])]
        script = call[-1]
        work = tempfile.mkdtemp(dir=self.tmp)
        repos = {".": "minimal", "a": "minimal", "g/b": "minimal", "set": "default",
                 "node_modules/x": "", "g/h/deep": ""}
        for rel in repos:
            os.makedirs(os.path.join(work, rel), exist_ok=True)
            self.git("init", "-q", ".", cwd=os.path.join(work, rel))
        self.git("config", "core.checkStat", "default", cwd=os.path.join(work, "set"))
        # A linked worktree's .git is a file naming a gitdir elsewhere: skipped.
        os.makedirs(os.path.join(work, "wt"))
        with open(os.path.join(work, "wt", ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: /nonexistent\n")
        subprocess.run(["sh", "-c", script], cwd=work, check=True)
        for rel, want in repos.items():
            with self.subTest(rel):
                self.assertEqual(self.git("config", "--local", "--get", "core.checkStat",
                                          cwd=os.path.join(work, rel)), want)


if __name__ == "__main__":
    main()
