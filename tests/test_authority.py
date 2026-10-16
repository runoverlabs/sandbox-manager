"""What a project's sandbox.toml may decide: not the reserved bindings, not the
shared secrets, and not whether egress is filtered at all."""

import os
import unittest

from tests.harness import MsbctlTest


class ReservedTest(MsbctlTest):
    env_keys = ("GH_TOKEN",)

    def test_project_cannot_rebind_reserved_variables(self):
        for spec in ("GH_TOKEN@evil.example", "CLAUDE_CODE_OAUTH_TOKEN@evil.example",
                     "CLAUDE_CODE_OAUTH_TOKEN_WORK@evil.example"):
            with self.subTest(spec=spec):
                self.fresh()
                self.make_folder_sandbox(
                    "web", sandbox_toml=f'secret_binds = ["{spec}"]\nextra_rules = '
                                        '["allow@evil.example:tcp:443"]\n')
                self.store_secret(self.secrets_file("web"), spec.split("@")[0], "planted-value-1")
                code, out, err = self.run_main("start", "web")
                self.assertNotEqual(code, 0)
                self.assertIn("fixed bindings", err)
                self.assertEqual(self.msb_calls("create"), [])
                self.assert_not_in_output("planted-value-1", out, err)

    def test_registry_cannot_either(self):
        self.make_folder_sandbox("web", entry_extra='secret_binds = ["GH_TOKEN@evil.example"]')
        code, _, _ = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.msb_calls("create"), [])

    def test_an_existing_sandbox_starts_without_the_binding(self):
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["GH_TOKEN@evil.example"]\n')
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", "planted-value-2")
        self.set_state(web="stopped")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("is ignored", err)
        starts = self.msb_calls("start")
        self.assertEqual(len(starts), 1)
        # No [secrets] github and no repo: nothing may carry the token at all.
        self.assertNotIn("GH_TOKEN", starts[0]["env"])

    def test_secret_add_refuses_a_reserved_custom_variable(self):
        self.make_folder_sandbox("web")
        # choose_one numbered fallback: the last row is "custom".
        presets = len(self.m.load_config().get("secret_presets", {}))
        code, _, err = self.run_main("secret", "add", "web",
                                     stdin=f"{presets + 1}\nGH_TOKEN\n")
        self.assertIn("fixed binding", err)
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            self.assertNotIn("secret_binds", fh.read())


class SharedValueTest(MsbctlTest):
    env_keys = ("NPM_TOKEN",)

    def secret_flags(self):
        argv = self.msb_calls("create")[0]["argv"]
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--secret"]

    def test_project_binding_does_not_read_global_env(self):
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n')
        self.store_secret(self.m.GLOBAL_ENV, "NPM_TOKEN", "planted-shared-npm")
        code, out, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        create = self.msb_calls("create")[0]
        self.assertNotIn("NPM_TOKEN", create["env"])
        self.assertFalse(any(f.startswith("NPM_TOKEN") for f in self.secret_flags()))
        self.assertIn("only", out)

    def test_project_binding_reads_its_own_file(self):
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n')
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", "planted-own-npm")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.msb_calls("create")[0]["env"].get("NPM_TOKEN"), "planted-own-npm")
        self.assert_not_in_argv("planted-own-npm")

    def test_registry_binding_reads_global_env(self):
        self.make_folder_sandbox("web", entry_extra='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]')
        self.store_secret(self.m.GLOBAL_ENV, "NPM_TOKEN", "planted-shared-npm")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.msb_calls("create")[0]["env"].get("NPM_TOKEN"), "planted-shared-npm")
        self.assertTrue(any(f.startswith("NPM_TOKEN") for f in self.secret_flags()))
        self.assert_not_in_argv("planted-shared-npm")


class EgressModeTest(MsbctlTest):

    def flag_value(self, flag):
        argv = self.msb_calls("create")[0]["argv"]
        return argv[argv.index(flag) + 1]

    def test_project_cannot_turn_on_observe(self):
        self.make_folder_sandbox("web", sandbox_toml='egress_mode = "observe"\n')
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.flag_value("--net-default-egress"), "deny")
        self.assertIn("machine-local only", err)

    def test_registry_can(self):
        self.make_folder_sandbox("web", entry_extra='egress_mode = "observe"')
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.flag_value("--net-default-egress"), "allow")

    def test_observe_writes_the_registry_only(self):
        project = self.make_folder_sandbox("web")
        code, _, err = self.run_main("observe", "web", "on", "-y")
        self.assertEqual(code, 0, err)
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            self.assertIn('egress_mode = "observe"', fh.read())
        with open(os.path.join(project, ".msb", "sandbox.toml"), encoding="utf-8") as fh:
            self.assertNotIn("egress_mode", fh.read())


if __name__ == "__main__":
    unittest.main()
