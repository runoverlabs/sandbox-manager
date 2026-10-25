"""The refused-host loop: `observe report --json`, `allow --from-observe`, and
`allow` offering a rebuild on a terminal only — so `observe on`, the workload,
`allow --from-observe --rebuild`, `observe off` runs with no one to ask."""

import json
import os
import tomllib
from unittest import main

from tests.harness import MsbctlTest

POLICY = ('rule_groups = []\n'
          'extra_rules = ["allow@known.example:tcp:443", "deny@blocked.example:tcp:443"]\n')

# The shapes msb writes at --log-level debug (see OBSERVED_TLS in msbctl), and
# the WARN line for a request the secret policy killed.
LOG = """\
2026-10-24T10:00:00.000Z DEBUG engine::tls::proxy: TLS intercept sni=registry.example dst=203.0.113.5:443
2026-10-24T10:00:01.000Z DEBUG engine::tls::proxy: TLS intercept sni=registry.example dst=203.0.113.5:443
2026-10-24T10:00:02.000Z DEBUG engine::tls::proxy: TLS intercept sni=known.example dst=203.0.113.6:443
2026-10-24T10:00:03.000Z DEBUG engine::tls::proxy: TLS intercept sni=alt.example dst=203.0.113.7:8443
2026-10-24T10:00:04.000Z DEBUG engine::tls::proxy: TLS intercept sni=blocked.example dst=203.0.113.8:443
2026-10-24T10:00:05.000Z DEBUG engine::tls::proxy: TLS intercept sni=public dst=203.0.113.9:443
2026-10-24T10:00:06.000Z DEBUG engine::tls::proxy: TLS intercept sni=10.0.0.0/8 dst=10.0.0.1:443
2026-10-24T10:00:07.000Z DEBUG engine::dns::forwarder: DNS query family is inactive domain=db.example
2026-10-24T10:00:08.000Z DEBUG engine::dns::forwarder: DNS query family is inactive domain=registry.example
2026-10-24T10:00:09.000Z WARN engine::secrets: secret violation: placeholder detected secret_env_var=GH_TOKEN host=api.example location=body
"""


class ObserveLoop(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.project = self.make_folder_sandbox("web", sandbox_toml=POLICY)

    def write_log(self, text=LOG):
        folder = os.path.join(os.environ["MSB_HOME"], "sandboxes", "web", "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "runtime.log"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def extra_rules(self):
        with open(os.path.join(self.project, ".msb", "sandbox.toml"), "rb") as fh:
            return tomllib.load(fh)["extra_rules"]

    def json_run(self, *argv):
        code, out, err = self.run_main(*argv)
        try:
            doc = json.loads(out)
        except ValueError:
            self.fail(f"stdout is not one JSON document: {out!r}\n{err}")
        return code, doc, err

    # ------------------------------------------------------------ the report

    def test_report_json(self):
        self.write_log()
        code, doc, err = self.json_run("observe", "web", "report", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual((doc["name"], doc["egress_mode"]), ("web", "enforce"))
        hosts = {(h["host"], h["port"]): h for h in doc["hosts"]}
        reg = hosts[("registry.example", 443)]
        self.assertEqual((reg["seen"], reg["hits"], reg["allowed"], reg["rule"]),
                         ("tls", 2, False, None))
        # The DNS lookup of a host also reached over TLS says nothing more.
        self.assertNotIn(("registry.example", None), hosts)
        self.assertEqual(hosts[("db.example", None)]["seen"], "dns")
        self.assertEqual(hosts[("known.example", 443)]["rule"], "allow@known.example:tcp:443")
        self.assertTrue(hosts[("known.example", 443)]["allowed"])
        self.assertFalse(hosts[("blocked.example", 443)]["allowed"])
        self.assertEqual(hosts[("alt.example", 8443)]["port"], 8443)
        # Uncovered first.
        self.assertFalse(doc["hosts"][0]["allowed"])
        self.assertEqual(doc["secret_blocks"], [{"var": "GH_TOKEN", "host": "api.example",
                                                 "location": "body", "hits": 1,
                                                 "last": "2026-10-24 10:00:09"}])

    def test_report_json_with_no_log(self):
        code, doc, err = self.json_run("observe", "web", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual((doc["logs"], doc["hosts"]), ([], []))

    def test_json_is_for_the_report_only(self):
        code, doc, _ = self.json_run("observe", "web", "on", "--json")
        self.assertEqual((code, doc["error"]["code"]), (3, "unavailable"))
        with open(self.entry_path("web"), encoding="utf-8") as fh:
            self.assertNotIn("egress_mode", fh.read())

    def test_text_report_names_the_port_and_the_shortcut(self):
        self.write_log()
        code, out, err = self.run_main("observe", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("msbctl allow web registry.example alt.example:8443", out)
        self.assertIn("msbctl allow web --from-observe", out)
        self.assertIn("public: not a plain DNS name", out)

    def test_udp_and_ingress_rules_do_not_cover_a_tls_connection(self):
        self.make_folder_sandbox("web", sandbox_toml=(
            'rule_groups = []\nextra_rules = ["allow@registry.example:udp:443", '
            '"deny:ingress@alt.example"]\n'))
        self.write_log()
        code, doc, err = self.json_run("observe", "web", "--json")
        self.assertEqual(code, 0, err)
        hosts = {(h["host"], h["port"]): h for h in doc["hosts"]}
        self.assertEqual(hosts[("registry.example", 443)]["rule"], None)
        self.assertEqual(hosts[("alt.example", 8443)]["rule"], None)
        code, _, err = self.run_main("allow", "web", "--from-observe")
        self.assertEqual(code, 0, err)
        self.assertIn("allow@registry.example:tcp:443", self.extra_rules())
        self.assertIn("allow@alt.example:tcp:8443", self.extra_rules())

    def test_no_shortcut_when_it_would_add_nothing(self):
        self.write_log("2026-10-24T10:00:05.000Z DEBUG engine::tls::proxy: "
                       "TLS intercept sni=public dst=203.0.113.9:443\n"
                       "2026-10-24T10:00:07.000Z DEBUG engine::dns::forwarder: "
                       "DNS query family is inactive domain=db.example\n")
        code, out, err = self.run_main("observe", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("msbctl allow web db.example", out)
        self.assertNotIn("--from-observe", out)

    # ------------------------------------------------------- allow --from-observe

    def test_from_observe(self):
        self.write_log()
        code, out, err = self.run_main("allow", "web", "--from-observe")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.extra_rules(), [
            "allow@known.example:tcp:443", "deny@blocked.example:tcp:443",
            "allow@registry.example:tcp:443", "allow@alt.example:tcp:8443"])
        for skipped in ("blocked.example", "public", "10.0.0.0/8", "db.example"):
            self.assertIn(f"skipped {skipped}", out)
        # Off a terminal nothing is asked and nothing is rebuilt.
        self.assertEqual(self.msb_calls("create"), [])
        self.assertIn("msbctl rebuild web", out)

    def test_from_observe_with_dns_and_a_named_target(self):
        self.write_log()
        code, _, err = self.run_main("allow", "web", "extra.example", "--from-observe", "--with-dns")
        self.assertEqual(code, 0, err)
        rules = self.extra_rules()
        for rule in ("allow@extra.example:tcp:443", "allow@db.example:tcp:443",
                     "allow@registry.example:tcp:443"):
            self.assertIn(rule, rules)
        self.assertFalse(any("public" in r or "10.0.0.0" in r for r in rules), rules)

    def test_from_observe_twice_changes_nothing(self):
        self.write_log()
        self.assertEqual(self.run_main("allow", "web", "--from-observe")[0], 0)
        before = self.extra_rules()
        code, out, err = self.run_main("allow", "web", "--from-observe")
        self.assertEqual(code, 0, err)
        self.assertIn("nothing observed that the current rules do not already cover", out)
        self.assertEqual(self.extra_rules(), before)

    def test_from_observe_needs_a_log(self):
        code, _, err = self.run_main("allow", "web", "--from-observe")
        self.assertNotEqual(code, 0)
        self.assertIn("no runtime log", err)

    def test_allow_needs_something(self):
        code, _, err = self.run_main("allow", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("--from-observe", err)
        code, _, err = self.run_main("allow", "web", "x.example", "--with-dns")
        self.assertNotEqual(code, 0)
        self.assertIn("--with-dns goes with --from-observe", err)

    # ------------------------------------------------------- the rebuild offer

    def test_a_terminal_is_asked_about_a_rebuild(self):
        self.set_state(web="running")
        code, out, err = self.run_main("allow", "web", "one.example", stdin="n\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn("rebuild now", out)
        self.assertEqual(self.msb_calls("create"), [])
        code, out, err = self.run_main("allow", "web", "two.example", stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.msb_calls("create")), 1)

    def test_no_rebuild_is_not_asked(self):
        code, out, err = self.run_main("allow", "web", "one.example", "--no-rebuild",
                                       stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertNotIn("rebuild now", out)
        self.assertEqual(self.msb_calls("create"), [])

    def test_restricted_is_never_asked(self):
        os.environ["MSB_RESTRICTED"] = "1"
        code, out, _ = self.run_main("allow", "web", "one.example", stdin="y\n", tty=True)
        self.assertNotIn("rebuild now", out)
        self.assertEqual(self.msb_calls("create"), [])

    # ------------------------------------------------------------ headless

    def test_the_loop_runs_headless(self):
        self.set_state(web="running")
        code, _, err = self.run_main("observe", "web", "on", "-y", "--rebuild")
        self.assertEqual(code, 0, err)
        self.assertIn("--net-default-egress", self.msb_calls("create")[-1]["argv"])
        self.write_log()
        code, _, err = self.run_main("allow", "web", "--from-observe", "--rebuild")
        self.assertEqual(code, 0, err)
        code, _, err = self.run_main("observe", "web", "off", "--rebuild")
        self.assertEqual(code, 0, err)
        argv = self.msb_calls("create")[-1]["argv"]
        self.assertEqual(argv[argv.index("--net-default-egress") + 1], "deny")
        self.assertIn("allow@registry.example:tcp:443", argv)
        self.assertIn("allow@alt.example:tcp:8443", argv)
        self.assertNotIn("allow@public:tcp:443", argv)


if __name__ == "__main__":
    main()
