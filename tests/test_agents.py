"""The agent choice, followed through: what is asked, read and bound depends on
which coding agents a sandbox has, and `[defaults] agents` decides for a new one."""

import contextlib
import io
import os
import tomllib
import unittest.mock

from tests.harness import MsbctlTest

TOKEN = "sk-ant-oat01-placeholder-for-tests"   # not a real token


class AgentsTest(MsbctlTest):

    def set_default_agents(self, agents):
        self.m.ensure_local_config()
        self.m.set_toml_key(self.m.CONFIG_FILE, "agents", agents, table="defaults")

    def store_claude_tokens(self, *names):
        for name in names:
            self.m.set_env_file_value(self.m.GLOBAL_ENV, self.m.claude_token_var(name), TOKEN)

    # ------------------------------------------------------------ defaults

    def test_default_agents(self):
        cases = [
            ({}, ["claude"]),
            ({"agents": []}, []),
            ({"agents": ["pi"]}, ["pi"]),
            ({"agents": ["claude"], "llm": ["local"]}, ["claude", "pi"]),
            ({"agents": [], "llm": ["local"]}, ["pi"]),
        ]
        for defaults, want in cases:
            with self.subTest(defaults=defaults):
                self.assertEqual(self.m.default_agents({"defaults": defaults}), want)

    def test_an_unknown_agent_is_named_and_dropped(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            picked = self.m.default_agents({"defaults": {"agents": ["claude", "codex"]}})
        self.assertEqual(picked, ["claude"])
        self.assertIn("no agent called 'codex'", err.getvalue())

    # -------------------------------------------------------------- wizard

    def add(self):
        project = os.path.join(self.tmp, "shop")
        os.makedirs(project)
        self.m.mark_welcomed()
        os.environ["TERM"] = "dumb"     # numbered prompts: each takes its default
        patch = unittest.mock.patch.object
        with patch(self.m, "confirm", lambda *a, **k: False), \
                patch(self.m, "available_digest", lambda image: None):
            code, out, err = self.run_main("add", project, stdin="\n" * 80, tty=True)
        self.assertEqual(code, 0, err)
        with open(os.path.join(project, ".msb", "sandbox.toml"), "rb") as fh:
            return tomllib.load(fh)["bootstrap"], out + err

    def test_no_claude_means_no_claude_token_step(self):
        self.store_claude_tokens("main", "work")       # two: the step would be offered
        self.set_default_agents([])
        boot, text = self.add()
        self.assertFalse(boot["claude"])
        self.assertFalse(boot["pi"])
        self.assertNotIn("which Claude account", text)
        self.assertIn("A coding agent keeps its sessions per path", text)
        # Asked before the guest path, so everything after can follow it.
        self.assertLess(text.index("Coding agents"), text.index("Project path inside"))

    def test_claude_by_default_still_asks_which_token(self):
        self.store_claude_tokens("main", "work")
        boot, text = self.add()
        self.assertTrue(boot["claude"])
        self.assertIn("which Claude account", text)

    # --------------------------------------------------------------- start

    def test_a_sandbox_without_claude_never_reads_or_binds_its_token(self):
        self.store_claude_tokens("main")
        self.make_folder_sandbox("pi-only", sandbox_toml="[bootstrap]\nclaude = false\npi = true\n")
        self.make_folder_sandbox("with-claude")
        config = self.m.load_config()
        lone = self.m.Sandbox("pi-only", config)
        self.assertNotIn(self.m.CLAUDE_TOKEN_VAR, lone.global_secret_vars())
        flags, env = lone.secret_env()
        self.assertNotIn(self.m.CLAUDE_TOKEN_VAR, env)
        self.assertFalse(any(self.m.CLAUDE_TOKEN_VAR in f for f in flags))
        both = self.m.Sandbox("with-claude", config)
        flags, env = both.secret_env()
        self.assertEqual(env.get(self.m.CLAUDE_TOKEN_VAR), TOKEN)
        self.assertTrue(any(f.startswith(self.m.CLAUDE_TOKEN_VAR) for f in flags))

    def test_edit_says_the_claude_token_is_not_used(self):
        self.make_folder_sandbox("pi-only", sandbox_toml="[bootstrap]\nclaude = false\npi = true\n")
        box = self.m.Sandbox("pi-only", self.m.load_config())
        self.assertEqual(self.m._summary_claude_token(box), "not used: no Claude Code here")

    # --------------------------------------------------------------- setup

    def test_first_run_skips_the_logins_no_sandbox_would_use(self):
        self.set_default_agents([])
        out = io.StringIO()

        def choose(title, options, default=0):
            return "skip" if title.startswith("next:") else options[default]

        with unittest.mock.patch.object(self.m, "choose_one", choose), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.m.cmd_setup(self.m.verb_args("setup", welcome=True), self.m.load_config())
        text = out.getvalue()
        self.assertIn("Claude login: skipped, as no new sandbox gets claude", text)
        self.assertIn("Model endpoints: skipped, as no new sandbox gets pi", text)
        self.assertNotIn("next: Claude login", text)
