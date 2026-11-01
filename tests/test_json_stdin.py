"""Machine-readable output and secrets from stdin: for scripts, never a value."""

import json
import os
import unittest.mock

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
        # Saved for the next start, then restarted by msbctl itself, which
        # binds the values and redoes the per-boot plumbing.
        self.assertIn("--next-start", modify)
        self.assertNotIn("--restart", modify)
        self.assertTrue(modify[modify.index("--secret") + 1].startswith("NPM_TOKEN"))
        self.assertEqual(len(self.msb_calls("stop")), 1)
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


class LiveRotationTest(MsbctlTest):
    """A new value for a binding msb already has reaches a running sandbox
    live, through `msb modify --secret` with the spec it was started with: no
    restart, and the value only ever in msb's environment."""
    env_keys = ("NPM_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
    NEW = "planted-rotated-value-5d2e"

    def setUp(self):
        super().setUp()
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n'
                                                     "[bootstrap]\nclaude = true\n")
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", PLANTED)
        self.store_secret(self.m.GLOBAL_ENV, "CLAUDE_CODE_OAUTH_TOKEN", PLANTED)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def modifies(self):
        return self.msb_calls("modify")

    def test_secret_set_rotates_without_a_restart(self):
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        [call] = self.modifies()
        # No options: msb keeps the stored rule and passthrough hosts.
        self.assertEqual(call["argv"], ["modify", "web", "--secret", "NPM_TOKEN@registry.npmjs.org"])
        self.assertNotIn("--restart", call["argv"])
        self.assertNotIn("--next-start", call["argv"])
        self.assertEqual(call["env"]["NPM_TOKEN"], self.NEW)
        self.assertEqual(self.msb_calls("stop"), [])
        self.assertIn("uses the new value now", out + err)
        self.assert_not_in_argv(self.NEW)

    def test_a_stopped_sandbox_reads_it_at_its_next_start(self):
        self.set_state(web="stopped")
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.modifies(), [])
        self.assertIn("next start", out + err)

    def test_a_replaced_claude_token_reaches_running_sandboxes(self):
        code, out, err = self.run_main("setup", "--claude-token", "main", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        [call] = self.modifies()
        self.assertEqual(call["argv"][3], "CLAUDE_CODE_OAUTH_TOKEN@api.anthropic.com,platform.claude.com")
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], self.NEW)
        self.assertEqual(self.msb_calls("stop"), [])
        self.assert_not_in_argv(self.NEW)
        self.assert_not_in_output(self.NEW, out, err)

    def test_restart_asked_for_is_a_real_restart(self):
        code, _, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", "--restart",
                                     stdin=self.NEW)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.modifies(), [])
        self.assertEqual(len(self.msb_calls("stop")), 1)
        self.assertEqual(self.msb_calls("start")[-1]["env"]["NPM_TOKEN"], self.NEW)

    def test_hosts_come_from_msb_not_from_the_config(self):
        # Edited since create: the live update keeps the binding msb has.
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@npm.example.org"]\n'
                                                     "[bootstrap]\nclaude = true\n")
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", PLANTED)
        code, _, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.modifies()[-1]["argv"][3], "NPM_TOKEN@registry.npmjs.org")

    def test_a_refused_update_is_a_warning_not_a_failure(self):
        os.environ["FAKE_MSB_FAIL"] = "modify"
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        self.assertIn("did not take the new NPM_TOKEN live", err)
        self.assertEqual(self.m.read_env_file(self.secrets_file("web"))["NPM_TOKEN"], self.NEW)

    def test_a_new_default_token_reaches_the_sandboxes_following_the_default(self):
        code, _, err = self.run_main("setup", "--claude-token", "work", "--stdin", "--default",
                                     stdin=self.NEW)
        self.assertEqual(code, 0, err)
        [call] = self.modifies()
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], self.NEW)

    def test_another_token_name_leaves_it_alone(self):
        code, _, err = self.run_main("setup", "--claude-token", "work", "--stdin", stdin=self.NEW)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.modifies(), [])


class SecretOptionsTest(MsbctlTest):
    """A binding with options (`:query`, `:body`) goes through `msb modify`
    like any other (msb 0.7.9+ keeps them): no rebuild."""
    env_keys = ("API_KEY",)

    def setUp(self):
        super().setUp()
        self.make_folder_sandbox("web")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def test_secret_add_with_query_is_bound_with_modify(self):
        presets = len(self.m.load_config().get("secret_presets", {}))
        # custom, its name, its host, "also query"; the value from the hidden prompt.
        with unittest.mock.patch.object(self.m, "read_secret_hidden", lambda prompt: PLANTED):
            code, out, err = self.run_main("secret", "add", "web",
                                           stdin=f"{presets + 1}\nAPI_KEY\napi.example.org\n2\n")
        self.assertEqual(code, 0, err)
        self.assertNotIn("rebuild", out + err)
        [call] = self.msb_calls("modify")
        spec = call["argv"][call["argv"].index("--secret") + 1]
        self.assertTrue(spec.startswith("API_KEY:query,passthrough=["), spec)
        self.assertTrue(spec.endswith("@api.example.org"), spec)
        # Not a terminal, so not asked: bound for the next start.
        self.assertIn("--next-start", call["argv"])
        self.assertEqual(call["env"]["API_KEY"], PLANTED)
        self.assert_not_in_argv(PLANTED)

    def add_custom(self, var, host, where, restart):
        presets = len(self.m.load_config().get("secret_presets", {}))
        with unittest.mock.patch.object(self.m, "read_secret_hidden", lambda prompt: PLANTED):
            return self.run_main("secret", "add", "web",
                                 stdin=f"{presets + 1}\n{var}\n{host}\n{where}\n{restart}\n")

    def test_adding_hosts_to_a_variable_msb_binds_rebinds_it(self):
        code, _, err = self.add_custom("API_KEY", "a.example.org", 1, "n")
        self.assertEqual(code, 0, err)
        code, _, err = self.add_custom("API_KEY", "b.example.org", 2, "y")
        self.assertEqual(code, 0, err)
        call = self.msb_calls("modify")[-1]["argv"]
        specs = [call[i + 1] for i, a in enumerate(call) if a == "--secret"]
        # Every binding of the variable, so msb merges them: not a bare rotation.
        self.assertEqual([s.rpartition("@")[2] for s in specs], ["a.example.org", "b.example.org"])
        self.assertTrue(specs[1].startswith("API_KEY:query,passthrough=["))
        self.assertIn("--next-start", call)
        # "y" to the restart, read from the pipe as before: msbctl restarts it.
        self.assertEqual(len(self.msb_calls("stop")), 1)

    def test_a_stopped_sandbox_takes_it_without_a_flag(self):
        self.set_state(web="stopped")
        # Declared, as `secret add` writes it: nothing is bound without a value.
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["API_KEY:body@api.example.org"]\n')
        self.store_secret(self.secrets_file("web"), "API_KEY", PLANTED)
        box = self.m.Sandbox("web", self.m.load_config())
        self.m.bind_secret_live(box, self.m.load_config(), "API_KEY:body@api.example.org", None)
        [call] = self.msb_calls("modify")
        spec = call["argv"][call["argv"].index("--secret") + 1]
        self.assertTrue(spec.startswith("API_KEY:body,passthrough=["), spec)
        self.assertNotIn("--restart", call["argv"])
        self.assertNotIn("--next-start", call["argv"])


if __name__ == "__main__":
    unittest.main()
