"""Agent tool bundles: machine-owned capabilities attached to a sandbox.

A bundle is a folder under ~/.config/msb/tools, so every test writes its own;
what is under test is what msbctl makes of it — the rules and env it emits, the
adapter files it installs and takes away again, and what it refuses.
"""

import json
import os
from unittest import main

from tests.harness import MsbctlTest

WEB = """\
description = "search the web and read what it returns"
hosts = ["search.test", "fetch.test:8443"]

[env]
WEB_SEARCH_URL = "https://search.test/search"
WEB_FETCH_URL = "https://fetch.test:8443/fetch"
"""
PI_TS = "export default function (pi) { pi.registerTool({ name: 'websearch' }) }\n"
SKILL = "---\nname: web\n---\n\ncurl \"$WEB_SEARCH_URL\" -G --data-urlencode \"q=$1\"\n"


class BundleBase(MsbctlTest):
    def bundle(self, name="web", toml=WEB, pi=PI_TS, claude=SKILL):
        folder = os.path.join(self.m.TOOLS_DIR, name)
        os.makedirs(os.path.join(folder, "claude"), exist_ok=True)
        if toml is not None:
            with open(os.path.join(folder, "bundle.toml"), "w", encoding="utf-8") as fh:
                fh.write(toml)
        if pi is not None:
            with open(os.path.join(folder, self.m.PI_BUNDLE_FILE), "w", encoding="utf-8") as fh:
                fh.write(pi)
        if claude is not None:
            with open(os.path.join(folder, self.m.CLAUDE_BUNDLE_FILE), "w", encoding="utf-8") as fh:
                fh.write(claude)
        return folder

    def default_tools(self, *names):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[defaults]\ntools = {json.dumps(list(names))}\n")

    def create_argv(self):
        return self.msb_calls("create")[0]["argv"]

    def flag_values(self, flag):
        argv = self.create_argv()
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    def start(self, name="web"):
        code, out, err = self.run_main("start", name)
        self.assertEqual(code, 0, err)
        return out + err

    def extension(self, name="web", sandbox="web"):
        return os.path.join(self.m.STATE_DIR, "pi", sandbox, "agent",
                            "extensions", f"msb-{name}.ts")


class BundleModelTest(BundleBase):

    def test_host_forms(self):
        self.assertEqual(self.m.bundle_host("search.test"), ("search.test", 443))
        self.assertEqual(self.m.bundle_host(" fetch.test:8443 "), ("fetch.test", 8443))
        self.assertEqual(self.m.bundle_host("[fd00::1]:8443"), ("fd00::1", 8443))
        for bad in ("https://search.test", "search.test:tcp:443", "search.test:",
                    "", "@search.test:tcp:443", "[fd00::1", "search.test:https"):
            self.assertIsNone(self.m.bundle_host(bad), bad)

    def test_rules_come_from_hosts(self):
        spec = self.m.read_toml(os.path.join(self.bundle(), "bundle.toml"))
        self.assertEqual(self.m.bundle_rules(spec),
                         ["allow@search.test:tcp:443", "allow@fetch.test:tcp:8443"])

    def test_valid_bundle_has_no_problem(self):
        self.assertIsNone(self.m.bundle_problem("web", self.m.read_toml(
            os.path.join(self.bundle(), "bundle.toml"))))

    def test_refusals(self):
        good = self.m.read_toml(os.path.join(self.bundle(), "bundle.toml"))
        cases = [
            ("not a table", "bundle.toml must be a table"),
            ({**good, "ports": []}, "unknown key"),
            ({k: v for k, v in good.items() if k != "description"}, "description is required"),
            ({**good, "description": "two\nlines"}, "one line"),
            ({**good, "hosts": []}, "hosts is required"),
            ({**good, "hosts": ["http://search.test"]}, "must be HOST"),
            ({**good, "hosts": ["search.test:80"]}, "port 80 is denied"),
            ({**good, "env": {"GH_TOKEN": "x"}}, "fixed binding"),
            ({**good, "env": {"LLM_KEY_QWEN": "x"}}, "fixed binding"),
            ({**good, "env": {"9LIVES": "x"}}, "not a shell variable name"),
            ({**good, "env": {"MSB_WEB_URL": "https://search.test/"}}, "placeholder namespace"),
            ({**good, "env": {"WEB_URL": "http://search.test/search"}}, "plain http"),
            ({**good, "env": {"WEB_URL": "https://elsewhere.test/"}}, "which hosts does not list"),
        ]
        for spec, wanted in cases:
            with self.subTest(spec=sorted(spec)):
                self.assertIn(wanted, self.m.bundle_problem("web", spec))

    def test_unknown_bundle_name_is_named_with_its_folder(self):
        self.default_tools("web")
        self.make_folder_sandbox("web")
        code, _out, err = self.run_main("start", "web")
        self.assertEqual(code, 1)
        self.assertIn("tool bundle 'web'", err)
        self.assertIn("holds nothing yet", err)

    def test_show_flags_a_missing_bundle_instead_of_failing(self):
        self.default_tools("web")
        self.make_folder_sandbox("web")
        code, _out, err = self.run_main("show", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("holds nothing yet", err)
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        self.assertIn("holds nothing yet", json.loads(out)["tools"][0]["problem"])

    def test_a_broken_bundle_stops_only_the_sandboxes_naming_it(self):
        self.bundle()
        self.bundle("draft", toml='description = "half-written\n')
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        self.assertIn("does not parse", self.m.available_bundles()["draft"][1])
        self.m.set_toml_key(self.entry_path("web"), "tools", ["draft"])
        code, _out, err = self.run_main("start", "web")
        self.assertEqual(code, 1)
        self.assertIn("does not parse", err)

    def test_hosts_match_urls_whatever_their_case(self):
        good = self.m.read_toml(os.path.join(self.bundle(), "bundle.toml"))
        self.assertIsNone(self.m.bundle_problem("web", {
            **good, "hosts": ["Search.Test"], "env": {"U": "https://search.TEST/q"}}))

    def test_name_must_be_a_slug(self):
        folder = self.bundle("Web_Tool", toml='description = "x"\nhosts = ["a.test"]\n',
                             pi="", claude=None)
        problem = self.m.bundle_problem("Web_Tool", self.m.read_toml(
            os.path.join(folder, "bundle.toml")))
        self.assertIn("folder name must be lowercase", problem)


class BundleCreateTest(BundleBase):

    def test_rules_and_env_when_enabled(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        self.assertIn("allow@search.test:tcp:443", self.flag_values("--net-rule"))
        self.assertIn("allow@fetch.test:tcp:8443", self.flag_values("--net-rule"))
        self.assertIn("WEB_SEARCH_URL=https://search.test/search", self.flag_values("--env"))
        self.assertIn("WEB_FETCH_URL=https://fetch.test:8443/fetch", self.flag_values("--env"))

    def test_nothing_when_disabled(self):
        self.bundle()
        self.make_folder_sandbox("web")
        self.start()
        argv = self.create_argv()
        self.assertFalse(any("search.test" in a for a in argv), argv)
        self.assertFalse(any(a.startswith("WEB_") for a in argv), argv)

    def test_registry_entry_overrides_the_default(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web", entry_extra='tools = []\n')
        self.start()
        self.assertFalse(any("search.test" in a for a in self.create_argv()))

    def test_off_port_is_intercepted_too(self):
        # Without the port, an HTTPS rule for it is a silent deny; 443 has to be
        # restated because --tls-intercept-port replaces msb's default.
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        self.assertEqual(self.flag_values("--tls-intercept-port"), ["443", "8443"])

    def test_443_alone_restores_msb_default(self):
        self.bundle(toml='description = "x"\nhosts = ["search.test"]\n')
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        self.assertEqual(self.flag_values("--tls-intercept-port"), [])

    def test_kandev_gets_none(self):
        # Kandev is provisioned by its own path, with its own egress and none of
        # the per-boot seeding; a bundle there would be rules with no tool.
        self.bundle()
        self.default_tools("web")
        os.makedirs(self.m.REGISTRY_DIR, exist_ok=True)
        with open(self.entry_path("k-lab"), "w", encoding="utf-8") as fh:
            fh.write('name = "k-lab"\nsource = "kandev"\nenv = "lab"\n')
        box = self.m.Sandbox("k-lab", self.m.load_config())
        self.assertEqual(box.bundles, [])
        self.assertFalse(any("search.test" in r for r in box.net_rules()))


class BundleAdapterTest(BundleBase):

    def test_pi_extension_written_and_removed(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web", sandbox_toml="[bootstrap]\npi = true\n")
        self.start()
        with open(self.extension(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), PI_TS)
        # Turn it off: the tool goes away with the bundle, and an extension the
        # operator wrote by hand stays.
        mine = os.path.join(os.path.dirname(self.extension()), "mine.ts")
        with open(mine, "w", encoding="utf-8") as fh:
            fh.write("// mine\n")
        self.m.set_toml_key(self.entry_path("web"), "tools", [])
        self.start()
        self.assertFalse(os.path.exists(self.extension()))
        self.assertTrue(os.path.exists(mine))

    def skill(self, name="msb-web", sandbox="web"):
        return os.path.join(self.m.STATE_DIR, "claude", sandbox, "skills", name, "SKILL.md")

    def test_claude_skill_written_on_the_host(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        with open(self.skill(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), SKILL)
        # Never through the exec: no skill text in any script or argument.
        self.assertNotIn(SKILL, [a for c in self.msb_calls("exec") for a in c["argv"]])

    def test_claude_skill_removed_with_the_bundle_and_yours_kept(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        self.start()
        # A skill of the operator's under the bundle's own name: the prefix
        # keeps the bundle off it, both while enabled and on the way out.
        mine = self.skill("web")
        os.makedirs(os.path.dirname(mine))
        with open(mine, "w", encoding="utf-8") as fh:
            fh.write("mine\n")
        self.m.set_toml_key(self.entry_path("web"), "tools", [])
        self.start()
        self.assertFalse(os.path.exists(os.path.dirname(self.skill())))
        self.assertTrue(os.path.exists(mine))
        self.assertEqual(self.m.read_json(os.path.join(
            self.m.TOOLS_STATE_DIR, "web.json")).get("claude"), [])

    def test_bundle_with_only_one_adapter(self):
        self.bundle(claude=None)
        self.default_tools("web")
        self.make_folder_sandbox("web", sandbox_toml="[bootstrap]\npi = true\n")
        self.start()
        self.assertTrue(os.path.exists(self.extension()))
        self.assertFalse(os.path.exists(self.skill()))


class BundleSurfaceTest(BundleBase):

    def test_show_json(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        row = json.loads(out)["tools"][0]
        self.assertEqual(row["name"], "web")
        self.assertEqual(row["hosts"], ["search.test:443", "fetch.test:8443"])
        self.assertEqual(row["env"], ["WEB_FETCH_URL", "WEB_SEARCH_URL"])
        self.assertEqual(row["adapters"], ["claude", "pi"])

    def test_profile_announces_it(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web")
        box = self.m.Sandbox("web", self.m.load_config())
        text = self.m.sandbox_profile_section(box)
        self.assertIn("**web**: search the web and read what it returns", text)

    def test_profile_names_a_bundle_only_to_its_harness(self):
        self.bundle(claude=None)
        self.default_tools("web")
        self.make_folder_sandbox("web")
        box = self.m.Sandbox("web", self.m.load_config())
        self.assertIn("search the web", self.m.sandbox_profile_section(box, "pi"))
        self.assertNotIn("search the web", self.m.sandbox_profile_section(box, "claude"))

    def test_profile_says_nothing_without_one(self):
        self.bundle()
        self.make_folder_sandbox("web")
        text = self.m.sandbox_profile_section(self.m.Sandbox("web", self.m.load_config()))
        self.assertNotIn("search the web", text)

    def test_rename_moves_the_marker(self):
        self.bundle()
        self.default_tools("web")
        self.make_folder_sandbox("web", sandbox_toml="[bootstrap]\npi = true\n")
        self.start()
        self.assertTrue(os.path.exists(os.path.join(self.m.TOOLS_STATE_DIR, "web.json")))
        self.m.rename_sandbox(self.m.Sandbox("web", self.m.load_config()), "web2")
        self.assertFalse(os.path.exists(os.path.join(self.m.TOOLS_STATE_DIR, "web.json")))
        self.assertTrue(os.path.exists(os.path.join(self.m.TOOLS_STATE_DIR, "web2.json")))


if __name__ == "__main__":
    main()
