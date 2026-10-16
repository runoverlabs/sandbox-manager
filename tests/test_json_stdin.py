"""Machine-readable output and secrets from stdin: for scripts, never a value."""

import json
import os
import unittest

from tests.harness import MsbctlTest

PLANTED = "planted-secret-value-93c1"


class JsonTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n'
                                                     '[secrets]\ngithub = true\n')
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", PLANTED)
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", PLANTED + "-gh")
        self.store_secret(self.m.GLOBAL_ENV, "CLAUDE_CODE_OAUTH_TOKEN", PLANTED + "-claude")

    def test_ls_json(self):
        code, out, err = self.run_main("ls", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIn("msbctl", data)
        row = data["sandboxes"][0]
        self.assertEqual((row["name"], row["state"], row["source"]), ("web", "absent", "folder"))
        self.assertEqual(row["updates"], [])
        self.assert_not_in_output(PLANTED, out, err)

    def test_show_json(self):
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(data["policy_approved"])
        self.assertTrue(data["github_token_stored"])
        self.assertEqual(data["claude_token"], {"name": "main", "stored": True})
        self.assertEqual(data["secrets"], [{"var": "NPM_TOKEN", "hosts": ["registry.npmjs.org"],
                                            "origin": "project", "reserved": False,
                                            "stored": True}])
        self.assertEqual(data["egress_mode"], "enforce")
        self.assert_not_in_output(PLANTED, out, err)

    def test_plain_ls_is_unchanged(self):
        code, out, _ = self.run_main("ls", "--porcelain")
        self.assertEqual(out.split("\t")[:2], ["web", "absent"])


class SecretSetTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n')

    def stored(self, var):
        return self.m.read_env_file(self.secrets_file("web")).get(var)

    def test_set_from_stdin(self):
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin",
                                       stdin=PLANTED + "\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.stored("NPM_TOKEN"), PLANTED)
        self.assert_not_in_output(PLANTED, out, err)
        self.assert_not_in_argv(PLANTED)
        mode = os.stat(self.secrets_file("web")).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_a_running_sandbox_gets_the_binding(self):
        self.set_state(web="running")
        code, _, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", "--restart",
                                     stdin=PLANTED)
        self.assertEqual(code, 0, err)
        modify = self.msb_calls("modify")[0]["argv"]
        self.assertIn("--restart", modify)
        self.assertTrue(modify[modify.index("--secret") + 1].startswith("NPM_TOKEN"))
        self.assert_not_in_argv(PLANTED)

    def test_unbound_and_reserved_variables_die(self):
        for var in ("OTHER", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_WORK"):
            with self.subTest(var=var):
                code, _, err = self.run_main("secret", "set", "web", var, "--stdin", stdin=PLANTED)
                self.assertNotEqual(code, 0)
                self.assertIsNone(self.stored(var))

    def test_bad_values_are_refused_without_echo(self):
        for value in ("", "\n", "two words", "x" * 9000):
            with self.subTest(value=value[:10]):
                code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin",
                                               stdin=value)
                self.assertNotEqual(code, 0)
                self.assertIsNone(self.stored("NPM_TOKEN"))
                if value.strip():
                    self.assert_not_in_output(value, out, err)

    def test_gh_token_turns_github_on(self):
        # Under `host serve` that is a policy change, so it is refused there.
        os.environ["MSB_RESTRICTED"] = "1"
        code, _, err = self.run_main("secret", "set", "web", "GH_TOKEN", "--stdin", stdin=PLANTED)
        self.assertNotEqual(code, 0)
        self.assertIn("on the host", err)
        self.assertIsNone(self.stored("GH_TOKEN"))
        # The operator's own command, nothing else pending: written and approved.
        del os.environ["MSB_RESTRICTED"]
        code, _, err = self.run_main("secret", "set", "web", "GH_TOKEN", "--stdin", stdin=PLANTED)
        self.assertEqual(code, 0, err)
        box = self.m.Sandbox("web", self.m.load_config())
        self.assertTrue(box.project_cfg["secrets"]["github"])
        self.assertTrue(self.m.policy_pinned(box))

    def test_gh_token_on_a_sandbox_that_binds_it(self):
        self.make_folder_sandbox("api", sandbox_toml="[secrets]\ngithub = true\n")
        code, _, err = self.run_main("secret", "set", "api", "GH_TOKEN", "--stdin", stdin=PLANTED)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.m.read_env_file(self.secrets_file("api"))["GH_TOKEN"], PLANTED)

    def test_an_unapproved_binding_is_not_bound(self):
        self.make_folder_sandbox("api", sandbox_toml='secret_binds = ["NPM_TOKEN@npm.evil.example"]\n',
                                 approve=False)
        self.set_state(api="running")
        code, _, err = self.run_main("secret", "set", "api", "NPM_TOKEN", "--stdin", stdin=PLANTED)
        self.assertNotEqual(code, 0)
        self.assertIn("policy not approved", err)
        self.assertEqual(self.msb_calls("modify"), [])

    def test_flags_only_for_set(self):
        code, _, err = self.run_main("secret", "ls", "web", "--stdin")
        self.assertNotEqual(code, 0)


class ClaudeTokenTest(MsbctlTest):

    def test_setup_claude_token_from_stdin(self):
        code, out, err = self.run_main("setup", "--claude-token", "work", "--stdin", stdin=PLANTED + "\n")
        self.assertEqual(code, 0, err)
        env = self.m.read_env_file(self.m.GLOBAL_ENV)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN_WORK"], PLANTED)
        self.assert_not_in_output(PLANTED, out, err)
        code, _, _ = self.run_main("setup", "--claude-token", "main", "--stdin", stdin=PLANTED)
        self.assertEqual(self.m.read_env_file(self.m.GLOBAL_ENV)["CLAUDE_CODE_OAUTH_TOKEN"], PLANTED)

    def test_bad_names(self):
        code, _, _ = self.run_main("setup", "--claude-token", "Bad Name", "--stdin", stdin=PLANTED)
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
