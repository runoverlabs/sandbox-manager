"""A sandbox's repo: RepoRef as the only reader of `repo`, and the wizard
following where the repo lives instead of assuming GitHub."""

import contextlib
import io
import os
import tomllib
import unittest.mock

from tests.harness import MsbctlTest


class RepoRefTest(MsbctlTest):

    def test_github_forms_all_store_owner_name(self):
        for text in ("owner/name", "owner/name.git", "https://github.com/owner/name",
                     "https://github.com/owner/name.git", "https://github.com/owner/name/",
                     "git@github.com:owner/name.git", "ssh://git@github.com/owner/name.git",
                     "  owner/name\n"):
            with self.subTest(text=text):
                ref = self.m.RepoRef.parse(text)
                self.assertEqual(ref.kind, "github")
                self.assertEqual(ref.stored, "owner/name")
                self.assertEqual(ref.url, "git@github.com:owner/name.git")
                self.assertEqual(ref.name, "name")

    def test_another_forge_keeps_its_url(self):
        url = "ssh://git@git.example.org:2222/you/project.git"
        ref = self.m.RepoRef.parse(url)
        self.assertEqual((ref.kind, ref.host, ref.ssh_port, ref.path, ref.name),
                         ("generic", "git.example.org", 2222, "you/project", "project"))
        self.assertEqual(ref.url, url)
        self.assertEqual(ref.stored, url)
        self.assertEqual(ref.known_hosts_name, "[git.example.org]:2222")
        # Stored and read back, it is the same repo.
        self.assertEqual(self.m.RepoRef.parse(ref.stored), ref)

    def test_kinds_and_known_hosts_names(self):
        cases = {
            "git@codeberg.org:someone/thing.git": ("forgejo", "codeberg.org"),
            "https://codeberg.org/someone/thing": ("forgejo", ""),
            "https://gitlab.example.org/group/sub/thing.git": ("generic", ""),
            "ssh://git@git.example.org:22/a/b": ("generic", "git.example.org"),
            "ssh://git.example.org/a/b": ("generic", "git.example.org"),
        }
        for text, (kind, known) in cases.items():
            with self.subTest(text=text):
                ref = self.m.RepoRef.parse(text)
                self.assertEqual(ref.kind, kind)
                self.assertEqual(ref.known_hosts_name, known)

    def test_not_a_repo(self):
        for text in ("", "   ", "name", "http://git.example.org/a/b", "git://host/a/b",
                     'ssh://git@host/a/b"', "https://host/a b", "ssh://git@host:99999/a/b",
                     "https://github.com/owner/name/tree/main", "file:///srv/a.git"):
            with self.subTest(text=text):
                self.assertIsNone(self.m.RepoRef.parse(text))


class WizardTestCase(MsbctlTest):
    """`msbctl add` driven through its numbered prompts, every answer its default."""

    def add(self, repo, name="cell", private=False):
        project = os.path.join(self.tmp, name)
        os.makedirs(project)
        self.m.mark_welcomed()
        os.environ["TERM"] = "dumb"     # numbered prompts: each takes its default
        patch = unittest.mock.patch.object
        with patch(self.m, "confirm", lambda *a, **k: False), \
                patch(self.m, "available_digest", lambda image: None), \
                patch(self.m, "known_host", lambda ref: True), \
                patch(self.m, "_resolves_privately", lambda host: private):
            code, out, err = self.run_main("add", project, stdin="\n" + repo + "\n" + "\n" * 60,
                                           tty=True)
        self.assertEqual(code, 0, err)
        with open(self.entry_path(name), "rb") as fh:
            entry = tomllib.load(fh)
        with open(os.path.join(project, ".msb", "sandbox.toml"), "rb") as fh:
            policy = tomllib.load(fh)
        return entry, policy, out + err

    def local_config(self):
        with open(self.m.CONFIG_FILE, "rb") as fh:
            return tomllib.load(fh)


class WizardForgeTest(WizardTestCase):

    def test_a_forge_repo_asks_nothing_about_github(self):
        url = "ssh://git@git.example.org:2222/you/project.git"
        entry, policy, text = self.add(url)
        self.assertEqual(entry["repo"], url)
        self.assertFalse(policy["secrets"]["github"])
        self.assertNotIn("github", policy["rule_groups"])
        self.assertNotIn("git@github.com:", text)
        self.assertNotIn("GitHub token", text)
        self.assertNotIn("personal-access-tokens", text)
        self.assertNotIn("languages from GitHub", text)
        self.assertIn(f"git uses the remote as it is: {url}", text)
        self.assertIn("clone into ~", text.replace(self.tmp, "~"))

    def test_a_github_repo_is_unchanged(self):
        entry, policy, text = self.add("https://github.com/owner/cell.git")
        self.assertEqual(entry["repo"], "owner/cell")
        self.assertIn("github", policy["rule_groups"])
        # Offered; with no token pasted the binding stays off, as it always has.
        self.assertIn("Only select repositories -> owner/cell", text)
        self.assertIn("git push", text)

    def test_a_typo_is_refused_before_anything_is_written(self):
        project = os.path.join(self.tmp, "cell")
        os.makedirs(project)
        self.m.mark_welcomed()
        os.environ["TERM"] = "dumb"
        code, _, err = self.run_main("add", project, stdin="\nhttp://host/a/b\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("is not a repo", err)
        self.assertFalse(os.path.exists(self.entry_path("cell")))


class SandboxForgeTest(MsbctlTest):

    def sandbox_on(self, name, repo):
        self.make_folder_sandbox(name)
        path = self.entry_path(name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read().replace('repo = ""', f'repo = "{repo}"')
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return self.m.Sandbox(name, self.m.load_config())

    def test_a_forge_repo_binds_no_github_and_says_so(self):
        box = self.sandbox_on("thing", "git@codeberg.org:someone/thing.git")
        self.assertFalse(box.on_github)
        self.assertFalse(box.wants_github)
        self.assertEqual(box.repo_ref.host, "codeberg.org")
        section = self.m.sandbox_profile_section(box)
        self.assertIn("on **codeberg.org**, not GitHub", section)
        self.assertIn("over ssh, through the forwarded agent", section)

    def test_a_github_repo_binds_github(self):
        box = self.sandbox_on("web", "owner/web")
        self.assertTrue(box.on_github and box.wants_github)
        self.assertNotIn("not GitHub", self.m.sandbox_profile_section(box))

    def test_add_repo_refuses_another_forge(self):
        code, _, err = self.run_main("add", "--repo", "https://codeberg.org/someone/thing")
        self.assertNotEqual(code, 0)
        self.assertIn("codeberg.org is not GitHub", err)


class ForgeEgressTest(WizardTestCase):

    URL = "ssh://git@git.example.org:2222/you/project.git"

    def test_an_unknown_forge_gets_a_machine_local_group(self):
        entry, policy, text = self.add(self.URL)
        rules = self.local_config()["rules"]["forge-git-example-org"]
        self.assertEqual(rules, ["allow@git.example.org:tcp:443", "allow@git.example.org:tcp:2222"])
        self.assertEqual(entry["extra_rule_groups"], ["forge-git-example-org"])
        self.assertNotIn("forge-git-example-org", policy["rule_groups"])
        # The forge's name stays on this machine: never in the committed policy.
        with open(os.path.join(self.tmp, "cell", ".msb", "sandbox.toml"), encoding="utf-8") as fh:
            self.assertNotIn("git.example.org", fh.read())
        self.assertIn("no rule group allows git.example.org", text)
        box = self.m.Sandbox("cell", self.m.load_config())
        self.assertIn("allow@git.example.org:tcp:2222", box.net_rules())
        self.assertFalse(box.allow_private_dns)

    def test_a_forge_on_the_lan_brings_private_dns(self):
        self.add(self.URL, private=True)
        self.assertIn("forge-git-example-org",
                      self.local_config()["defaults"]["private_dns_groups"])
        self.assertTrue(self.m.Sandbox("cell", self.m.load_config()).allow_private_dns)

    def test_the_next_sandbox_on_that_forge_reuses_the_group(self):
        self.add(self.URL)
        entry, _, text = self.add("ssh://git@git.example.org:2222/you/other.git", name="other")
        self.assertEqual(entry["extra_rule_groups"], ["forge-git-example-org"])
        self.assertNotIn("no rule group allows", text)
        self.assertEqual(list(self.local_config()["rules"]), ["forge-git-example-org"])

    def test_https_needs_only_443(self):
        self.add("https://git.example.org/you/project.git")
        self.assertEqual(self.local_config()["rules"]["forge-git-example-org"],
                         ["allow@git.example.org:tcp:443"])

    def test_codeberg_gets_the_shipped_group(self):
        entry, policy, text = self.add("git@codeberg.org:you/project.git")
        self.assertIn("codeberg", policy["rule_groups"])
        self.assertNotIn("extra_rule_groups", entry)
        self.assertNotIn("Forge egress", text)

    def test_a_covering_group_left_unticked_is_said_not_overridden(self):
        config = {"rules": {"mine": ["allow@git.example.org:tcp:443",
                                     "allow@git.example.org:tcp:2222"]}}
        ref = self.m.RepoRef.parse(self.URL)
        self.assertEqual(self.m.forge_groups(ref, config), ["mine"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(self.m.ensure_forge_egress(ref, [], config))
        self.assertIn("mine would", err.getvalue())
        self.assertIsNone(self.m.ensure_forge_egress(ref, ["mine"], config))

    def test_github_is_left_to_its_feature(self):
        ref = self.m.RepoRef.parse("owner/name")
        self.assertEqual(self.m.forge_groups(ref, {"rules": {}}), [])
        self.assertIsNone(self.m.ensure_forge_egress(ref, [], {"rules": {}}))
