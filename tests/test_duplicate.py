"""`msbctl duplicate`: a second sandbox with the first one's host-side settings
on another folder, the first one, the folder and its .msb/ left as they are."""

import contextlib
import io
import os
import unittest.mock

from tests.harness import MsbctlTest

POLICY = 'rule_groups = ["github"]\nextra_rules = ["allow@one.example:tcp:443"]\n'


class DuplicateTest(MsbctlTest):

    def other_folder(self, name="web-2", sandbox_toml=None):
        path = os.path.join(self.tmp, "projects", name)
        os.makedirs(path, exist_ok=True)
        if sandbox_toml is not None:
            os.makedirs(os.path.join(path, ".msb"), exist_ok=True)
            with open(os.path.join(path, ".msb", "sandbox.toml"), "w", encoding="utf-8") as fh:
                fh.write(sandbox_toml)
        return path

    def entry(self, name):
        return self.m.read_toml(self.entry_path(name))

    def test_copies_the_host_side_and_leaves_the_source(self):
        project = self.make_folder_sandbox(
            "web", sandbox_toml=POLICY,
            entry_extra='identity = "work"\nvolumes = "old"\nports = ["8080:80"]\n'
                        '# `msbctl keys web` lists them\n')
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", "planted-dup-value")
        self.set_state(web="running")
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            before = fh.read()
        target = self.other_folder(sandbox_toml=POLICY)

        code, out, err = self.run_main("duplicate", "web", "web-2", target)
        self.assertEqual(code, 0, err)
        new = self.entry("web-2")
        self.assertEqual((new["name"], new["project"], new["identity"]),
                         ("web-2", target, "work"))
        self.assertNotIn("volumes", new)
        self.assertNotIn("ports", new)
        self.assertIn("published ports", out)
        with open(self.entry_path("web-2"), encoding="utf-8") as fh:
            self.assertIn("msbctl keys web-2", fh.read())
        self.assertEqual(self.m.read_env_file(self.secrets_file("web-2")).get("NPM_TOKEN"),
                         "planted-dup-value")
        # The same policy is approved already: the duplicate starts without asking.
        code, out, _ = self.run_main("policy", "web-2")
        self.assertIn("[approved]", out)

        # Nothing of the source moved or changed, and msb was not touched.
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertTrue(os.path.isfile(self.secrets_file("web")))
        self.assertEqual([c for c in self.msb_calls() if c["argv"][:1] in (["stop"], ["rm"])], [])
        self.assertTrue(os.path.isdir(os.path.join(project, ".msb")))

    def test_never_copies_msb_into_the_folder(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY)
        target = self.other_folder()
        code, _, err = self.run_main("duplicate", "web", "web-2", target)
        self.assertEqual(code, 0, err)
        self.assertEqual(os.listdir(target), [])
        self.assertIn("no .msb/sandbox.toml", err)

    def test_a_different_policy_still_needs_approval(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY)
        target = self.other_folder(sandbox_toml=POLICY + "cpus = 8\n")
        code, _, err = self.run_main("duplicate", "web", "web-2", target)
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_main("policy", "web-2")
        self.assertIn("NOT APPROVED", out)
        self.assertIn("+ cpus = 8", out)

    def test_refusals(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.make_folder_sandbox("shop")
        cases = [(("web", "shop", self.other_folder()), "already registered"),
                 (("web", "web-2", project), "own folder"),
                 (("web", "web-2", os.path.join(self.tmp, "projects", "shop")), "project of shop"),
                 (("web", "web-2", os.path.join(self.tmp, "nowhere")), "not a directory")]
        for argv, why in cases:
            code, _, err = self.run_main("duplicate", *argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn(why, err)
        self.assertFalse(os.path.exists(self.entry_path("web-2")))

    def test_refuses_a_leftover_secrets_file(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", "planted-dup-value")
        self.store_secret(self.secrets_file("web-2"), "NPM_TOKEN", "an-older-one")
        code, _, err = self.run_main("duplicate", "web", "web-2", self.other_folder())
        self.assertNotEqual(code, 0)
        self.assertIn("left over", err)
        self.assertFalse(os.path.exists(self.entry_path("web-2")))

    def test_host_serve_refuses_it(self):
        self.assertIsNotNone(self.m.restricted_problem(["duplicate", "web", "web-2", "/tmp"]))

    def test_the_edit_menu_offers_it(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        target = self.other_folder(sandbox_toml=POLICY)
        # project folder, duplicate folder, its name, the (unchanged) name; the
        # guest path is a picker, stubbed below.
        answers = iter([project, target, "web-2", "web"])
        box = self.m.Sandbox("web", self.m.load_config())
        ctx = {"rebuild": set()}
        with unittest.mock.patch("builtins.input", lambda _prompt: next(answers)), \
                unittest.mock.patch.object(self.m, "pick_guest_path", return_value=box.guest_path_setting), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.m.section_place(box, self.m.load_config(), ctx)
        self.assertEqual(self.entry("web-2")["project"], target)
        self.assertEqual(self.entry("web")["project"], project)
        self.assertEqual(ctx["rebuild"], set())
        self.assertNotIn("name", ctx)
