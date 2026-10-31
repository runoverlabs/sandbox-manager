"""The GitHub and Claude tokens, and every shipped secret preset, are
substituted in the Authorization header only (msb's `headers=`): anywhere else
the placeholder goes out as itself, so no allowed host can echo the real value
back from a header the guest chose."""

from unittest import main

from tests.harness import MsbctlTest

TOKEN = "planted-scope-test-value"


class HeaderScopeTest(MsbctlTest):

    def secret_flags(self):
        argv = self.msb_calls("create")[0]["argv"]
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--secret"]

    def test_github_and_claude_bindings_name_the_header(self):
        self.make_folder_sandbox("web", sandbox_toml="[secrets]\ngithub = true\n"
                                                     "[bootstrap]\nclaude = true\n")
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", TOKEN)
        self.store_secret(self.m.GLOBAL_ENV, "CLAUDE_CODE_OAUTH_TOKEN", TOKEN)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        flags = {self.m.binding_var(f): f for f in self.secret_flags()}
        self.assertEqual(flags["GH_TOKEN"],
                         "GH_TOKEN:headers=[authorization],passthrough=[api.anthropic.com,"
                         "platform.claude.com]@github.com,api.github.com")
        self.assertEqual(flags["CLAUDE_CODE_OAUTH_TOKEN"],
                         "CLAUDE_CODE_OAUTH_TOKEN:headers=[authorization],passthrough=["
                         "api.anthropic.com,platform.claude.com]@api.anthropic.com,platform.claude.com")
        self.assert_not_in_argv(TOKEN)

    def test_every_shipped_preset_is_scoped(self):
        presets = self.m.load_config()["secret_presets"]
        self.assertTrue(presets)
        for name, preset in presets.items():
            with self.subTest(name):
                spec = self.m.preset_spec(preset)
                self.assertTrue(spec.startswith(f"{preset['env']}:headers=[authorization]@"), spec)

    def test_a_preset_without_headers_keeps_every_header(self):
        self.assertEqual(self.m.preset_spec({"env": "X_TOKEN", "hosts": ["a.example.org", "b.example.org"]}),
                         "X_TOKEN@a.example.org,b.example.org")

    def test_a_bound_variable_is_not_offered_again(self):
        presets = self.m.load_config()["secret_presets"]
        taken = [self.m.preset_spec(presets["npm"]).replace(":headers=[authorization]", "")]
        rows = []
        self.m.choose_one = lambda title, options, default=0: rows.extend(options) or options[-1]
        self.m.ask = lambda *a, **k: ""
        self.m.choose_secret(self.m.load_config(), taken)
        self.assertFalse(any(r.startswith("npm ") for r in rows))
        self.assertTrue(any(r.startswith("ghcr ") for r in rows))


if __name__ == "__main__":
    main()
