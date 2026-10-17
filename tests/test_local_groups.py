"""Egress groups only this machine defines live in its registry entry."""

import os
import tomllib
from unittest import main, mock


from tests.harness import MsbctlTest


class LocalGroupsTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.m.ensure_local_config()
        # As `msbctl setup` → Your network writes them.
        self.m.set_toml_key(self.m.CONFIG_FILE, "homelab", ["allow@git.home.example:tcp:443"],
                            table="rules")
        self.m.set_toml_key(self.m.CONFIG_FILE, "private_dns_groups", ["homelab"], table="defaults")

    def test_split(self):
        self.assertEqual(self.m.split_groups(["github", "homelab", "npm"]),
                         (["github", "npm"], ["homelab"]))

    def test_registry_groups_add_to_the_project_and_bring_private_dns(self):
        self.make_folder_sandbox("web", sandbox_toml='rule_groups = ["github"]\n',
                                 entry_extra='extra_rule_groups = ["homelab"]')
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        argv = self.msb_calls("create")[0]["argv"]
        self.assertIn("allow@github.com:tcp:443", argv)
        self.assertIn("allow@git.home.example:tcp:443", argv)
        self.assertIn("--no-dns-rebind-protection", argv)

    def test_not_part_of_the_pinned_policy(self):
        self.make_folder_sandbox("web", sandbox_toml='rule_groups = ["github"]\n')
        self.m.set_toml_key(self.entry_path("web"), "extra_rule_groups", ["homelab"])
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def test_one_in_the_project_is_warned_about(self):
        self.make_folder_sandbox("web", sandbox_toml='rule_groups = ["github", "homelab"]\n')
        code, _, err = self.run_main("show", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("defined only in this machine", err)

    def test_edit_moves_a_stray_group_to_the_registry(self):
        project = self.make_folder_sandbox("web", sandbox_toml='rule_groups = ["github", "homelab"]\n')
        config = self.m.load_config()
        box = self.m.Sandbox("web", config)
        plan = {"groups": ["github", "homelab"], "packages": [], "bun": False, "gitleaks": False,
                "agents": ["claude"], "features": []}
        with mock.patch.object(self.m, "pick_features", lambda *a, **k: plan):
            with self.m.approving_edits(box, config):
                self.m.section_features(box, config, {"rebuild": set()})
        with open(os.path.join(project, ".msb", "sandbox.toml"), "rb") as fh:
            self.assertEqual(tomllib.load(fh)["rule_groups"], ["github"])
        box = self.m.Sandbox("web", config)
        self.assertEqual(box.entry["extra_rule_groups"], ["homelab"])
        self.assertEqual(box.rule_groups, ["github", "homelab"])
        self.assertTrue(self.m.policy_pinned(box))

    def test_the_entry_template_renders_them(self):
        text = self.m.render("registry.toml.in", NAME="web", PROJECT="/p", GUEST_PATH="/work",
                             REPO="", DATE="2026-10-16", IDENTITY="", GIT_PUSH="gh", CLAUDE_TOKEN="",
                             SSH_KEYS="ssh_keys = []", MOUNTS="", AUTOSTART="false",
                             EXTRA_RULE_GROUPS=self.m.format_list("extra_rule_groups", ["homelab"], ""))
        self.assertEqual(tomllib.loads(text)["extra_rule_groups"], ["homelab"])


if __name__ == "__main__":
    main()
