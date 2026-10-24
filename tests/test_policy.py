"""The policy pin: a project's egress rules, bindings and resources are applied
only once approved on the host, and never approved without a person asked."""

import contextlib
import io
import os
import unittest

from tests.harness import MsbctlTest

POLICY = 'rule_groups = ["github"]\nextra_rules = ["allow@one.example:tcp:443"]\n'


class PolicyTest(MsbctlTest):

    def write_project(self, project, text):
        with open(os.path.join(project, ".msb", "sandbox.toml"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_first_create_needs_approval(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY, approve=False)
        code, out, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("msbctl policy web approve", err)
        self.assertIn("first time", out)
        self.assertEqual(self.msb_calls("create"), [])

        code, out, err = self.run_main("policy", "web", "approve", stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.msb_calls("create")), 1)

    def test_a_changed_policy_stops_a_rebuild_before_anything_is_removed(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.set_state(web="running")
        self.write_project(project, POLICY.replace(
            '"allow@one.example:tcp:443"', '"allow@one.example:tcp:443", "allow@evil.example:tcp:443"'))
        code, out, err = self.run_main("rebuild", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("+   allow@evil.example:tcp:443", out)
        self.assertIn("policy not approved", err)
        self.assertEqual(self.msb_calls("rm"), [])
        self.assertEqual(self.msb_calls("create"), [])

    def test_restricted_refuses_even_with_a_terminal(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.write_project(project, POLICY + 'memory = "64G"\n')
        os.environ["MSB_RESTRICTED"] = "1"
        code, _, err = self.run_main("start", "web", stdin="y\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.msb_calls("create"), [])
        code, _, err = self.run_main("policy", "web", "approve", stdin="y\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("refused", err)

    def test_resources_are_pinned(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.set_state(web="stopped")
        self.write_project(project, POLICY + 'memory = "256G"\n')
        code, out, _ = self.run_main("rebuild", "web")
        self.assertNotEqual(code, 0)
        self.assertIn('+ memory = "256G"', out)

    def test_declining_changes_nothing(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.write_project(project, POLICY + "allow_private_dns = true\n")
        code, _, err = self.run_main("start", "web", stdin="n\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("not approved, nothing changed", err)
        self.assertEqual(self.msb_calls("create"), [])

    def test_allow_asks_about_a_foreign_change_first(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.write_project(project, POLICY + 'secret_binds = ["NPM_TOKEN@npm.evil.example"]\n')
        code, out, err = self.run_main("allow", "web", "two.example", stdin="n\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("NPM_TOKEN@npm.evil.example", out)
        with open(os.path.join(project, ".msb", "sandbox.toml"), encoding="utf-8") as fh:
            self.assertNotIn("two.example", fh.read())

        # Approved, the operator's own rule is then written and approved with it.
        code, out, err = self.run_main("allow", "web", "two.example", stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        argv = self.msb_calls("create")[0]["argv"]
        self.assertIn("allow@two.example:tcp:443", argv)

    def test_allow_without_a_terminal_works_when_nothing_is_pending(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY)
        code, _, err = self.run_main("allow", "web", "two.example")
        self.assertEqual(code, 0, err)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def test_an_empty_policy_needs_nothing(self):
        self.make_folder_sandbox("web", sandbox_toml='[bootstrap]\npackages = ["jq"]\n', approve=False)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def test_show(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        code, out, _ = self.run_main("policy", "web")
        self.assertEqual(code, 0)
        self.assertIn("[approved]", out)
        self.write_project(project, POLICY + "cpus = 16\n")
        code, out, _ = self.run_main("policy", "web", "show")
        self.assertIn("NOT APPROVED", out)
        self.assertIn("+ cpus = 16", out)

    def test_the_project_policy_is_read_only_in_the_guest(self):
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        self.run_main("start", "web")
        argv = self.msb_calls("create")[0]["argv"]
        rw = argv.index(f"{project}:/work:uid={os.getuid()},gid={os.getgid()}")
        ro = argv.index(f"{project}/.msb:/work/.msb:ro")
        self.assertLess(rw, ro)

    def test_rename_and_purge_carry_the_approval(self):
        self.make_folder_sandbox("web", sandbox_toml=POLICY)
        approved = os.path.join(self.m.POLICY_APPROVED_DIR, "web.json")
        self.assertTrue(os.path.isfile(approved))
        code, _, err = self.run_main("rename", "web", "shop", "-y")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(approved))
        moved = os.path.join(self.m.POLICY_APPROVED_DIR, "shop.json")
        self.assertTrue(os.path.isfile(moved))
        code, out, err = self.run_main("policy", "shop")
        self.assertIn("[approved]", out)
        code, _, err = self.run_main("purge", "shop", "-y")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(moved))

    def test_escape_sequences_cannot_hide_a_line_of_the_diff(self):
        # TOML spells ESC as \u001b: unescaped, the last key's cursor-up and
        # erase-line would wipe the added rule from the screen being approved.
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY + "[secrets]\ngithub = true\n")
        self.write_project(project, POLICY.replace('443"]', '443", "allow@public:tcp:any"]')
                           + '[secrets]\ngithub = true\n"\\u001b[1A\\u001b[2K" = false\n')
        code, out, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertNotIn("\x1b[1A", out)
        self.assertIn('"\\u001b[1A\\u001b[2K"', out)
        self.assertIn("+   allow@public:tcp:any", out)

    def edit_while_the_guest_writes(self, guest_text=None, **run):
        """An edit section that writes one key; `guest_text` lands in the
        project's sandbox.toml while it waits on the operator."""
        project = self.make_folder_sandbox("web", sandbox_toml=POLICY)
        config = self.m.load_config()
        box = self.m.Sandbox("web", config)
        path = os.path.join(project, ".msb", "sandbox.toml")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                self.m.approving_edits(box, config):
            self.m.set_toml_key(path, "cpus", 4)
            if guest_text:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(guest_text)
        return self.m.policy_pinned(self.m.Sandbox("web", config))

    def test_an_edit_approves_what_msbctl_wrote(self):
        self.assertTrue(self.edit_while_the_guest_writes())

    def test_an_edit_does_not_approve_what_the_guest_wrote_meanwhile(self):
        self.assertFalse(self.edit_while_the_guest_writes('secret_binds = ["NPM_TOKEN@evil.example"]\n'))
        code, out, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("NPM_TOKEN@evil.example", out)
        self.assertEqual(self.msb_calls("create"), [])


if __name__ == "__main__":
    unittest.main()
