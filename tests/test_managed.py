"""msbctl managed: sandboxes owned by a client other than Kandev (protocol 2),
kept apart from Kandev's and from each other."""

import contextlib
import hashlib
import io
import json
import os
import tomllib
from unittest import main, mock

from tests.harness import MsbctlTest
import tests.test_kandev as tk
from tests.test_kandev import IMAGE, KandevTest, request

PLANTED_CI = "planted-ci-secret"
PLANTED_CI_NONCE = "planted-ci-nonce"
CI = """
[clients.ci]
enabled = true
env_prefix = "CI_"
guest_ports = [8765, 9000]
allow_extra = ["pypi.org", "*.example.org"]
body_secret_hosts = ["llm.example.org"]
max_sandboxes = 3
"""


def ci_request(**over):
    """A protocol-2 request: no callback unless a test adds one."""
    req = {"operation_id": "op-c1", "input_digest": "sha256:c1", "image": IMAGE,
           "cpus": 2, "memory_mib": 2048, "workspace_gib": 5,
           "expires_at": "2099-01-01T00:00:00Z", "egress_allow": ["llm.example.org"],
           "secrets": [{"name": "LLM_KEY", "value": PLANTED_CI, "hosts": ["llm.example.org"]}]}
    req.update(over)
    return json.dumps({k: v for k, v in req.items() if v is not None}) + "\n"


class Identity(MsbctlTest):
    """Who the key is, and whose an entry is: read in one place."""

    def test_the_key(self):
        for value, client in (("kandev", "kandev"), ("client:ci", "ci"), ("1", None), ("", None)):
            with self.subTest(value=value):
                os.environ["MSB_RESTRICTED"] = value
                self.assertEqual(self.m.key_client(), client)
                self.assertEqual(self.m.kandev_key(), client == "kandev")
                self.assertEqual(self.m.restricted(), value != "")
        os.environ.pop("MSB_RESTRICTED")
        self.assertIsNone(self.m.key_client())
        self.assertFalse(self.m.restricted())

    def test_a_key_msbctl_does_not_know_fails_closed(self):
        # Never the everyday key's, and never unrestricted.
        for value in ("client:", "client:Bad", "client:repo", "client:" + "x" * 17, "ci", "0"):
            with self.subTest(value=value):
                os.environ["MSB_RESTRICTED"] = value
                try:
                    self.assertTrue(self.m.restricted())
                    with self.assertRaises(SystemExit):
                        self.m.key_client()
                    code, _, err = self.run_main("ls")
                    self.assertNotEqual(code, 0)
                    self.assertIn("does not know", err)
                finally:
                    os.environ.pop("MSB_RESTRICTED")

    def test_an_entry(self):
        m = self.m
        self.assertEqual(m.entry_client({"source": "kandev", "kandev_env": "e1"}), "kandev")
        self.assertEqual(m.entry_env({"source": "kandev", "kandev_env": "e1"}), "e1")
        self.assertEqual(m.entry_client({"source": "managed", "client": "ci", "client_env": "e2"}), "ci")
        self.assertEqual(m.entry_env({"source": "managed", "client": "ci", "client_env": "e2"}), "e2")
        # A managed entry cannot pass itself off as Kandev's, or as no one's.
        for bad in ("kandev", "", None, "Ci", "folder"):
            self.assertIsNone(m.entry_client({"source": "managed", "client": bad}))
        for source in ("folder", "repo", None):
            self.assertIsNone(m.entry_client({"source": source}))
        self.assertIsNone(m.entry_client("not a table"))

    def test_a_sandbox(self):
        os.makedirs(self.m.REGISTRY_DIR, exist_ok=True)
        with open(self.entry_path("c-e1"), "w", encoding="utf-8") as fh:
            fh.write('name = "c-e1"\nsource = "managed"\nclient = "ci"\nclient_env = "e1"\n')
        box = self.m.Sandbox("c-e1", self.m.load_config())
        self.assertEqual((box.client, box.is_managed, box.is_kandev), ("ci", True, True))
        self.assertEqual(box.location, "ci:e1")
        with open(self.entry_path("c-e2"), "w", encoding="utf-8") as fh:
            fh.write('name = "c-e2"\nsource = "managed"\nclient = "kandev"\n')
        code, _, err = self.run_main("show", "c-e2")
        self.assertNotEqual(code, 0)
        self.assertIn("client is not a client name", err)


# A value of every TOML type, for keys that want another (the fuzz tests).
# None: a nested table, [<table>.<key>].
WRONG_TYPES = {"int": "7", "str": '"x"', "list of lists": '[["base"]]', "dict": "{ a = 1 }",
               "bool": "true", "float": "1.5", "nested table": None}
UNKNOWN_KEYS = ("colour", "Enabled", "max-sandboxes")
# Client keys for which that type is the right one: not a wrong value there.
RIGHT_TYPES = {("enabled", "bool"), ("require_callback", "bool"), ("max_sandboxes", "int"),
               ("max_cpus", "int")}


def toml_key(table, key, kind, header=""):
    """`table` holding `key` set to a value of type `kind`, after `header`
    (the table's other lines)."""
    value = WRONG_TYPES[kind]
    if value is None:
        return f"\n[{table}]\n{header}[{table}.{key}]\na = 1\n"
    return f"\n[{table}]\n{header}{key} = {value}\n"


class Settings(MsbctlTest):
    """[managed] for the host, [clients.<name>] (and [kandev]) per client."""

    def write(self, text):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(text)

    def refused(self, text, *words):
        self.write(text)
        with self.assertRaises(self.m.KandevError) as caught:
            self.m.clients_settings(self.m.load_config())
            self.m.kandev_settings(self.m.load_config())
            self.m.managed_host_settings(self.m.load_config())
        self.assertEqual(caught.exception.code, "invalid_config")
        for word in words:
            self.assertIn(word, caught.exception.message)

    def invalid(self, text, name, *words):
        """clients_settings() of `text`: `name`'s own invalid_config, with
        `words` in it, and Kandev unharmed. The whole dict."""
        self.write(text)
        found = self.m.clients_settings(self.m.load_config())
        self.assertIsInstance(found[name], self.m.KandevError)
        self.assertEqual(found[name].code, "invalid_config")
        for word in words:
            self.assertIn(word, found[name].message)
        self.assertIsInstance(found["kandev"], dict)
        self.m.kandev_settings(self.m.load_config())          # raises nothing
        return found

    def client(self, name, text):
        self.write(text)
        found = self.m.clients_settings(self.m.load_config())[name]
        if isinstance(found, Exception):
            raise found
        return found

    def test_the_shipped_defaults_alone(self):
        config = self.m.load_config()
        settings = self.m.kandev_settings(config)
        self.assertEqual(sorted(settings), sorted(self.m.KANDEV_SETTINGS_KEYS))
        self.assertFalse(settings["enabled"])
        self.assertEqual(list(self.m.clients_settings(config)), ["kandev"])
        host = self.m.managed_host_settings(config)
        self.assertIsNone(host["host_max_sandboxes"])

    def test_legacy_and_new_tables_say_the_same(self):
        legacy = ('[kandev]\nenabled = true\nbase_url = "https://sbx.example.org"\nserve = "none"\n'
                  'max_sandboxes = 3\nallow_extra = ["pypi.org"]\nport_pool = "21000-21999"\n')
        moved = ('[managed]\nbase_url = "https://sbx.example.org"\nserve = "none"\n'
                 'port_pool = "21000-21999"\n[clients.kandev]\nenabled = true\nmax_sandboxes = 3\n'
                 'allow_extra = ["pypi.org"]\n')
        half = ('[managed]\nbase_url = "https://sbx.example.org"\nserve = "none"\n'
                'port_pool = "21000-21999"\n[kandev]\nenabled = true\nmax_sandboxes = 3\n'
                'allow_extra = ["pypi.org"]\n')
        got = []
        for text in (legacy, moved, half):
            self.write(text)
            got.append(self.m.kandev_settings(self.m.load_config()))
        self.assertEqual(got[0], got[1])
        self.assertEqual(got[0], got[2])
        self.assertEqual(got[0]["port_pool"], (21000, 21999))

    def test_one_key_in_two_tables_is_refused(self):
        self.refused('[kandev]\nbase_url = "https://a.example.org"\n[managed]\nbase_url = "https://b.example.org"\n',
                     "[managed]", "[kandev]", "base_url")
        self.refused("[kandev]\nenabled = true\n[clients.kandev]\nenabled = true\n",
                     "[kandev]", "[clients.kandev]")
        # Host keys in [kandev] beside [clients.kandev] are not a second Kandev table.
        self.write('[kandev]\nserve = "none"\n[clients.kandev]\nenabled = true\n')
        self.assertTrue(self.m.kandev_settings(self.m.load_config())["enabled"])

    def test_host_totals_come_from_managed_only(self):
        self.write('[managed]\nmax_sandboxes = 5\nmax_cpus = 8\nmax_memory = "16G"\n')
        host = self.m.managed_host_settings(self.m.load_config())
        self.assertEqual((host["host_max_sandboxes"], host["host_max_cpus"], host["host_max_memory_mib"]),
                         (5, 8, 16384))
        self.refused('[managed]\nmax_memory = "lots"\n', "[managed] max_memory")

    def test_a_client_starts_from_the_shipped_kandev_values(self):
        got = self.client("ci", "[clients.ci]\n")
        shipped = self.m.kandev_settings(self.m.load_config())
        for key in ("enabled", "max_sandboxes", "max_cpus", "max_memory_mib", "rule_groups"):
            self.assertEqual(got[key], shipped[key], key)
        self.assertEqual((got["name_prefix"], got["env_prefix"], got["guest_ports"], got["require_callback"],
                          got["body_secret_hosts"]),
                         ("c-", "AGENTCTL_", [8765, 41001, 41002, 41003], False, []))
        # The operator's [kandev] is Kandev's, not every client's.
        got = self.client("ci", "[kandev]\nmax_sandboxes = 2\n[clients.ci]\n")
        self.assertEqual(got["max_sandboxes"], shipped["max_sandboxes"])

    def test_kandev_keeps_what_protocol_1_fixed(self):
        kandev = self.client("kandev", "[kandev]\n")
        self.assertEqual((kandev["name_prefix"], kandev["env_prefix"], kandev["require_callback"]),
                         ("k-", "AGENTCTL_", True))
        self.assertEqual(kandev["body_secret_hosts"], list(self.m.AGENT_TRANSCRIPT_HOSTS))
        for line in ('name_prefix = "x-"', 'env_prefix = "X_"', "guest_ports = [8765]",
                     "require_callback = false", 'body_secret_hosts = ["llm.example.org"]'):
            with self.subTest(line=line):
                self.refused(f"[kandev]\n{line}\n", "fixed for Kandev")
                self.refused(f"[clients.kandev]\n{line}\n", "fixed for Kandev")

    def test_one_clients_typo_is_its_own(self):
        self.write("[clients.ci]\nmax_cpus = -1\n[clients.lab]\n")
        found = self.m.clients_settings(self.m.load_config())
        self.assertIsInstance(found["ci"], self.m.KandevError)
        self.assertIn("[clients.ci] max_cpus", found["ci"].message)
        self.assertIsInstance(found["lab"], dict)
        self.assertIsInstance(found["kandev"], dict)

    def test_client_key_checks(self):
        for line, words in (
                ('name_prefix = "c"', "name_prefix"), ('name_prefix = "C-"', "name_prefix"),
                ('name_prefix = "toolong1-"', "name_prefix"),
                ('env_prefix = "ci_"', "env_prefix"), ('env_prefix = "MSB_X_"', "env_prefix"),
                ('env_prefix = "LD_"', "env_prefix"), ('env_prefix = "CI"', "env_prefix"),
                ("guest_ports = []", "guest_ports"), ("guest_ports = [1, 2, 3, 4, 5]", "guest_ports"),
                ("guest_ports = [8765, 8765]", "twice"), ("guest_ports = [80]", "guest_ports"),
                ("require_callback = 1", "require_callback"),
                ('body_secret_hosts = ["llm.example.org"]', "none of allow_extra, rule_groups or private_names"),
                ('body_secret_hosts = ["*.example.org"]', "exact"),
                ("nonsense = 1", "not a client key")):
            with self.subTest(line=line):
                self.write(f"[clients.ci]\n{line}\n")
                found = self.m.clients_settings(self.m.load_config())["ci"]
                self.assertIsInstance(found, self.m.KandevError)
                self.assertIn(words, found.message)

    def test_body_secret_hosts_must_be_reachable(self):
        got = self.client("ci", '[clients.ci]\nallow_extra = ["*.example.org"]\n'
                                'private_names = ["git.example.net"]\n'
                                'body_secret_hosts = ["llm.example.org", "git.example.net"]\n')
        self.assertEqual(got["body_secret_hosts"], ["llm.example.org", "git.example.net"])
        # Through a rule group the client has (the shipped ones include claude),
        # and an address allow_extra names with a port: reachable either way.
        got = self.client("ci", '[clients.ci]\nallow_extra = ["192.0.2.10:8788"]\n'
                                'body_secret_hosts = ["api.anthropic.com", "192.0.2.10"]\n')
        self.assertEqual(got["body_secret_hosts"], ["api.anthropic.com", "192.0.2.10"])
        self.write('[clients.ci]\nrule_groups = ["python"]\nbody_secret_hosts = ["api.anthropic.com"]\n')
        found = self.m.clients_settings(self.m.load_config())["ci"]
        self.assertIsInstance(found, self.m.KandevError)
        self.assertIn("api.anthropic.com is in none of", found.message)

    def test_names_and_prefixes(self):
        # Each is the problem of the client(s) it concerns; Kandev and lab go on.
        found = self.invalid("[clients.Bad]\n[clients.lab]\n", "Bad", "[clients.Bad]", "not a client name")
        self.assertEqual(found["lab"]["name_prefix"], "l-")
        self.invalid("[clients.repo]\n", "repo", "reserved")
        found = self.invalid('[clients.ci]\nname_prefix = "c-"\n[clients.cx]\nname_prefix = "c-"\n[clients.lab]\n',
                             "ci", "[clients.ci] name_prefix 'c-' is also [clients.cx]'s")
        self.assertIn("[clients.cx] name_prefix 'c-' is also [clients.ci]'s", found["cx"].message)
        self.assertEqual(found["lab"]["name_prefix"], "l-")
        # Two clients defaulting to the same first letter must say which is which.
        found = self.invalid("[clients.ci]\n[clients.cd]\n", "ci", "name_prefix", "cd")
        self.assertIsInstance(found["cd"], self.m.KandevError)
        self.assertEqual(self.client("cd", '[clients.ci]\n[clients.cd]\nname_prefix = "cd-"\n')["name_prefix"],
                         "cd-")

    def test_an_entry_under_clients_that_is_not_a_table(self):
        found = self.invalid("[clients]\nfoo = 1\n[clients.lab]\n", "foo", "[clients] foo: a client is a table")
        self.assertEqual(found["lab"]["name_prefix"], "l-")
        self.invalid('[clients]\nBad = "x"\n', "Bad", "not a client name")
        # It still holds its prefix: no other client takes f- meanwhile.
        found = self.invalid("[clients]\nfoo = 1\n[clients.fx]\nname_prefix = \"f-\"\n", "fx", "'f-'")
        # Kandev's own entry is Kandev's own problem, as a bad key in [kandev] is.
        self.write("[clients]\nkandev = 1\n[clients.lab]\n")
        found = self.m.clients_settings(self.m.load_config())
        self.assertIn("[clients] kandev: a client is a table", found["kandev"].message)
        self.assertEqual(found["lab"]["name_prefix"], "l-")

    def test_clients_that_is_not_a_table_names_no_client(self):
        # Nothing can be read from it, so no client is configured, and Kandev
        # (whose table is [kandev] then) goes on; doctor reports it.
        self.write("clients = 1\n[kandev]\nenabled = true\n")
        found = self.m.clients_settings(self.m.load_config())
        self.assertEqual(list(found), ["kandev"])
        self.assertTrue(found["kandev"]["enabled"])

    def test_host_keys_are_refused_in_a_client_table(self):
        # Moving all of [kandev] to [clients.kandev] would otherwise drop
        # base_url, serve and proxy_listen without a word.
        for name in ("kandev", "ci"):
            for line in ('base_url = "https://sbx.example.org"', 'serve = "none"', 'proxy_listen = "192.0.2.1"',
                         'port_pool = "21000-21999"', 'proxy_port_pool = "31000-31999"'):
                with self.subTest(name=name, line=line):
                    self.write(f"[clients.{name}]\nenabled = true\n{line}\n")
                    found = self.m.clients_settings(self.m.load_config())[name]
                    self.assertIsInstance(found, self.m.KandevError)
                    self.assertIn(f"[clients.{name}] {line.split()[0]}: a host key", found.message)
                    self.assertIn("[managed]", found.message)
        self.write('[clients.kandev]\nenabled = true\nbase_url = "https://sbx.example.org"\n')
        with self.assertRaises(self.m.KandevError) as caught:
            self.m.kandev_settings(self.m.load_config())
        self.assertIn("a host key", caught.exception.message)
        # Where they belong, beside [clients.kandev], they are read.
        got = self.client("kandev", '[managed]\nbase_url = "https://sbx.example.org"\n[clients.kandev]\n'
                                    'enabled = true\n')
        self.assertTrue(got["enabled"])
        self.assertEqual(self.m.kandev_settings(self.m.load_config())["base_url"], "https://sbx.example.org")

    def test_kandevs_prefix_is_never_anothers(self):
        # Asked for outright: that client's own problem; Kandev and the rest work.
        self.write('[clients.ci]\nname_prefix = "k-"\n[clients.lab]\n')
        found = self.m.clients_settings(self.m.load_config())
        self.assertIsInstance(found["ci"], self.m.KandevError)
        self.assertIn("k- is always Kandev's", found["ci"].message)
        self.assertIsInstance(found["kandev"], dict)
        self.assertIsInstance(found["lab"], dict)
        # By default: a name starting with k takes its next letter or digit.
        for name, prefix in (("kube", "ku-"), ("k8s", "k8-"), ("k-ci", "kc-"), ("ci", "c-")):
            with self.subTest(name=name):
                self.assertEqual(self.client(name, f"[clients.{name}]\n")["name_prefix"], prefix)
        for name in ("k", "k-"):
            with self.subTest(name=name):
                self.write(f"[clients.{name}]\n")
                found = self.m.clients_settings(self.m.load_config())
                self.assertIn("the default, k-, is Kandev's", found[name].message)
                self.assertIsInstance(found["kandev"], dict)
        self.assertEqual(self.client("k", '[clients.k]\nname_prefix = "kx-"\n')["name_prefix"], "kx-")

    def test_kandev_broken_then_fixed_keeps_k(self):
        # With Kandev's table broken a client could once take k-, and fixing
        # Kandev's then took Kandev's protocol 1 down.
        self.write('[kandev]\nmax_cpus = -1\n[clients.kube]\nname_prefix = "k-"\n')
        found = self.m.clients_settings(self.m.load_config())
        self.assertIsInstance(found["kandev"], self.m.KandevError)
        self.assertIn("k- is always Kandev's", found["kube"].message)
        self.write('[kandev]\nmax_cpus = 4\n[clients.kube]\nname_prefix = "k-"\n')
        self.assertEqual(self.m.kandev_settings(self.m.load_config())["max_cpus"], 4)
        self.assertIsInstance(self.m.clients_settings(self.m.load_config())["kube"], self.m.KandevError)

    def test_a_broken_tables_prefix_is_still_its_own(self):
        # ci's table is broken; no one takes ci's prefix meanwhile, by default
        # or outright. ci keeps its own problem; the other is told of the clash.
        found = self.invalid("[clients.ci]\nmax_cpus = -1\n[clients.cx]\n[clients.lab]\n",
                             "cx", "[clients.cx] name_prefix 'c-' is also [clients.ci]'s")
        self.assertIn("max_cpus", found["ci"].message)
        self.assertEqual(found["lab"]["name_prefix"], "l-")
        found = self.invalid('[clients.ci]\nmax_cpus = -1\nname_prefix = "q-"\n[clients.lab]\nname_prefix = "q-"\n',
                             "lab", "'q-'")
        self.assertIn("max_cpus", found["ci"].message)
        # A broken table whose prefix is itself unreadable holds none.
        self.write("[clients.ci]\nname_prefix = 7\n[clients.cx]\n")
        found = self.m.clients_settings(self.m.load_config())
        self.assertIsInstance(found["ci"], self.m.KandevError)
        self.assertEqual(found["cx"]["name_prefix"], "c-")

    def test_a_clients_key_hears_no_other_clients_name(self):
        text = '[clients.ci]\n[clients.secretco]\nname_prefix = "c-"\n[clients.lab]\n'
        self.invalid(text, "ci", "secretco", "'c-'")                # the operator: named
        for key in ("client:ci", "client:lab", "kandev"):
            with self.subTest(key=key):
                os.environ["MSB_RESTRICTED"] = key
                try:
                    found = self.m.clients_settings(self.m.load_config())
                finally:
                    os.environ.pop("MSB_RESTRICTED")
                self.assertIsInstance(found["kandev"], dict)
                self.assertIsInstance(found["lab"], dict)
                for name in ("ci", "secretco"):
                    self.assertIsInstance(found[name], self.m.KandevError)
                    self.assertNotIn("secretco", found[name].message)
                    self.assertNotIn("c-", found[name].message)
                    self.assertIn("msbctl doctor", found[name].message)

    def settles(self, fn):
        """fn()'s result, or None when it answers invalid_config; never
        anything else (an internal error stops every client and the proxy)."""
        try:
            return fn()
        except self.m.KandevError as exc:
            self.assertEqual(exc.code, "invalid_config", exc.message)
            return None

    def test_a_value_of_any_wrong_type(self):
        config = self.m.load_config
        # In a client's table: that client's invalid_config, and no one else's.
        for key in (*self.m.CLIENT_KEYS, *self.m.MANAGED_HOST_KEYS, *UNKNOWN_KEYS):
            for kind in WRONG_TYPES:
                if (key, kind) in RIGHT_TYPES:
                    continue
                with self.subTest(table="clients.zz", key=key, kind=kind):
                    self.invalid(toml_key("clients.zz", key, kind, "" if key == "enabled" else "enabled = true\n")
                                 + "[clients.lab]\nenabled = true\n", "zz")
                    self.assertIsInstance(self.m.clients_settings(config())["lab"], dict)
        # In Kandev's [kandev], or the host's [managed]: invalid_config (or a
        # value that happens to check out), never an internal error.
        for table, keys in (("kandev", (*self.m.CLIENT_KEYS, *self.m.MANAGED_HOST_KEYS, *UNKNOWN_KEYS)),
                            ("managed", (*self.m.MANAGED_HOST_KEYS, *self.m.MANAGED_HOST_TOTALS, *UNKNOWN_KEYS))):
            for key in keys:
                for kind in WRONG_TYPES:
                    with self.subTest(table=table, key=key, kind=kind):
                        self.write(toml_key(table, key, kind) + "[clients.lab]\nenabled = true\n")
                        found = self.m.clients_settings(config())
                        self.assertEqual(set(found), {"kandev", "lab"})
                        self.settles(lambda: self.m.kandev_settings(config()))
                        self.settles(lambda: self.m.managed_host_settings(config()))
                        if table == "kandev" and key in self.m.CLIENT_KEYS:
                            self.assertIsInstance(found["lab"], dict)

    def test_a_base_url_that_is_not_a_url(self):
        self.refused('[managed]\nbase_url = "https://[x"\n', "[managed] base_url: https://host[:port]")

    def test_allow_extras_example_is_a_documentation_address(self):
        # Protocol 1's error (`kandev provision`, `host kandev configure`)
        # names a documentation address, never a LAN one.
        self.refused('[kandev]\nallow_extra = ["not a host!"]\n', 'addresses ("192.0.2.6")',
                     'address:port ("192.0.2.6:8788"', 'CIDRs ("192.0.2.0/24")')


class Dialects(MsbctlTest):
    """Protocol 1 is a constant; protocol 2 is built from a client's table."""

    def test_kandev_is_protocol_1(self):
        d = self.m.KANDEV_DIALECT
        self.assertEqual((d.protocol, d.client, d.row_key, d.callback_keys, d.callback_required,
                          d.env_prefix, d.default_ports, d.guest_ports_settable, d.agentctl_path,
                          d.record_has_client, d.name_prefix),
                         (1, "kandev", "kandev", ("kandev_api",), True, "AGENTCTL_",
                          (8765, 41001, 41002, 41003), False, "/opt/kandev/agentctl", False, "k-"))
        self.assertEqual(d.body_secret_hosts, self.m.AGENT_TRANSCRIPT_HOSTS)

    def test_a_client_is_protocol_2(self):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write('[clients.ci]\nenv_prefix = "CI_"\nguest_ports = [8765]\nrequire_callback = true\n')
        d = self.m.managed_dialect(self.m.clients_settings(self.m.load_config())["ci"])
        self.assertEqual((d.protocol, d.client, d.row_key, d.callback_keys, d.callback_required,
                          d.env_prefix, d.default_ports, d.agentctl_path, d.record_has_client,
                          d.name_prefix, d.body_secret_hosts),
                         (2, "ci", "record", ("callback", "kandev_api"), True, "CI_", (8765,),
                          "/opt/ci/agentctl", True, "c-", ()))

    def test_names_and_labels(self):
        m = self.m
        self.assertEqual(m.managed_name("c-", "e1"), "c-e1")
        self.assertEqual(m.kandev_name("e1"), "k-e1")
        long = "x" * 60
        self.assertEqual(m.managed_name("c-", long), "c-" + m.hashlib.sha256(long.encode()).hexdigest()[:24])
        self.assertEqual(m.managed_name("c-", "E1"), "c-" + m.hashlib.sha256(b"E1").hexdigest()[:24])
        self.assertEqual(m.owner_labels("kandev", "e1"), ["msbctl.owner=kandev", "kandev.env=e1"])
        self.assertEqual(m.owner_labels("ci", "e1"), ["msbctl.owner=ci", "msbctl.env=e1"])

    def test_kandev_in_protocol_2_keeps_its_ports(self):
        # Its agentctl is protocol 1's first port: a request may not move it.
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write("[clients.ci]\n")
        clients = self.m.clients_settings(self.m.load_config())
        d = self.m.managed_dialect(clients["kandev"])
        self.assertEqual((d.protocol, d.guest_ports_settable, d.default_ports),
                         (2, False, self.m.KANDEV_GUEST_PORTS))
        self.assertTrue(self.m.managed_dialect(clients["ci"]).guest_ports_settable)

    def test_messages_name_the_table_a_host_key_is_in(self):
        m = self.m
        # Kandev's say [kandev], as protocol 1 always has; another client's, where it is.
        self.assertEqual(m.host_table({"client": "kandev", "host_tables": {"base_url": "managed"}}, "base_url"),
                         "kandev")
        self.assertEqual(m.host_table({"base_url": ""}, "base_url"), "kandev")
        self.assertEqual(m.host_table({"client": "ci", "host_tables": {"base_url": "kandev"}}, "base_url"),
                         "kandev")
        self.assertEqual(m.host_table({"client": "ci", "host_tables": {}}, "base_url"), "managed")
        full = {"port_pool": (1, 0), "proxy_port_pool": (1, 0), "proxy_listen": ""}
        for settings, table in ((full, "kandev"), ({**full, "client": "ci", "host_tables": {}}, "managed")):
            with self.subTest(table=table):
                with self.assertRaises(m.KandevError) as caught:
                    m.alloc_ports(settings, 1)
                self.assertIn(f"[{table}] port_pool", caught.exception.message)
                with self.assertRaises(m.KandevError) as caught:
                    m.alloc_proxy_ports(settings, 1)
                self.assertIn(f"[{table}] proxy_port_pool", caught.exception.message)


class ManagedTest(KandevTest):
    """Kandev (as in tests/test_kandev.py) and a second client, ci, on one host."""

    env_keys = ("NPM_TOKEN", "LLM_KEY")
    ci_table = CI

    def configure(self, **over):
        super().configure(**over)
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write(self.ci_table)

    def as_ci(self, *argv, stdin="", key="client:ci"):
        """(exit code, the JSON document) of `msbctl <argv>` under ci's key."""
        os.environ["MSB_RESTRICTED"] = key
        try:
            return self._msbctl_json(argv, stdin)
        finally:
            os.environ.pop("MSB_RESTRICTED", None)

    def ci_ok(self, *argv, stdin=""):
        code, doc = self.as_ci(*argv, stdin=stdin)
        self.assertEqual(code, 0, doc)
        return doc

    def ci_error(self, code_name, *argv, stdin=""):
        code, doc = self.as_ci(*argv, stdin=stdin)
        self.assertEqual(code, 3, doc)
        self.assertEqual(doc["error"]["code"], code_name, doc)
        return doc["error"]

    def ci_provision(self, env="e1", **over):
        return self.ci_ok("managed", "provision", env, stdin=ci_request(**over))["record"]


class Health(ManagedTest):

    def test_protocol_2_for_a_client(self):
        doc = self.ci_ok("managed", "health")
        self.assertEqual((doc["protocol"], doc["protocols"], doc["client"], doc["enabled"]),
                         (2, [2], "ci", True))
        self.assertEqual(doc["client_settings"], {
            "name_prefix": "c-", "env_prefix": "CI_", "guest_ports": [8765, 9000],
            "require_callback": False, "body_secret_hosts": ["llm.example.org"]})
        self.assertIn("managed_namespace", doc["features"])
        self.assertEqual(doc["capacity"]["max_sandboxes"], 3)
        self.assertEqual(doc["egress"]["allow_extra"], ["pypi.org", "*.example.org"])
        self.assertNotIn("host_capacity", doc)
        for key in ("msbctl_version", "msb_version", "kvm", "platform", "base_url", "serve", "tls", "host"):
            self.assertIn(key, doc)

    def test_kandev_may_speak_both(self):
        doc = self.ok("health")
        self.assertEqual(doc["protocol"], 1)
        self.assertIn("managed_namespace", doc["features"])
        doc = self.jok("managed", "health")
        self.assertEqual((doc["protocol"], doc["protocols"], doc["client"]), (2, [1, 2], "kandev"))
        self.assertEqual(doc["client_settings"]["name_prefix"], "k-")

    def test_a_client_with_no_table_is_disabled(self):
        code, doc = self.as_ci("managed", "health", key="client:lab")
        self.assertEqual((code, doc["enabled"], doc["client"]), (0, False, "lab"))
        code, doc = self.as_ci("managed", "provision", "e1", stdin=ci_request(), key="client:lab")
        self.assertEqual((code, doc["error"]["code"]), (3, "denied"))
        code, doc = self.as_ci("ls", "--json", key="client:lab")
        self.assertEqual((code, doc["error"]["code"]), (3, "denied"))

    def test_host_totals(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[managed]\nmax_sandboxes = 2\n")
        self.provision("k1")
        doc = self.ci_ok("managed", "health")
        self.assertEqual(doc["host_capacity"], {"max_sandboxes": 2, "sandboxes": 1, "cpus": 2,
                                                "memory_mib": 2048})

    def test_the_operator_names_the_client(self):
        code, doc = self.msbctl_json("managed", "health", plugin=False)
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"))
        code, doc = self.msbctl_json("managed", "health", "--client", "ci", plugin=False)
        self.assertEqual((code, doc["client"]), (0, "ci"))


class Provisioning(ManagedTest):

    def test_entry_labels_and_record(self):
        rec = self.ci_provision()
        self.assertEqual((rec["client"], rec["name"], rec["env"], rec["state"]), ("ci", "c-e1", "e1", "running"))
        self.assertEqual(sorted(rec["ports"]), ["8765", "9000"])
        entry = self.m.read_toml(self.entry_path("c-e1"))
        self.assertEqual((entry["source"], entry["client"], entry["client_env"]), ("managed", "ci", "e1"))
        argv = self.msb_calls("create")[0]["argv"]
        labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
        self.assertEqual(labels, ["msbctl.owner=ci", "msbctl.env=e1"])
        self.assertEqual(len([a for a in argv if a == "--port"]), 2)
        # The secret's placeholder may travel in a body to the client's LLM
        # host only (body_secret_hosts), never Anthropic's by default.
        secret = argv[argv.index("--secret") + 1]
        self.assertEqual(secret, "LLM_KEY:passthrough=[llm.example.org]@llm.example.org")
        self.assert_not_in_argv(PLANTED_CI)
        self.assert_nowhere_on_disk(PLANTED_CI)
        self.assertEqual(self.msb_calls("create")[0]["env"].get("LLM_KEY"), PLANTED_CI)
        long_env = "x" * 60
        rec = self.ci_provision(long_env, operation_id="op-c2")
        self.assertEqual(rec["name"], "c-" + hashlib.sha256(long_env.encode()).hexdigest()[:24])

    def test_no_body_secret_hosts_means_no_passthrough(self):
        self.ci_table = CI.replace('body_secret_hosts = ["llm.example.org"]\n', "")
        self.configure()
        self.ci_provision()
        argv = self.msb_calls("create")[0]["argv"]
        self.assertEqual(argv[argv.index("--secret") + 1], "LLM_KEY@llm.example.org")

    def test_idempotent_and_conflicts(self):
        first = self.ci_provision()
        self.assertEqual(self.ci_provision(), first)
        self.assertEqual(len(self.msb_calls("create")), 1)
        self.ci_error("conflict", "managed", "provision", "e1", stdin=ci_request(input_digest="sha256:x"))
        self.ci_error("conflict", "managed", "provision", "e2", stdin=ci_request())

    def test_no_callback_means_no_rule_and_no_hosts_line(self):
        self.ci_provision()
        entry = self.m.read_toml(self.entry_path("c-e1"))
        self.assertEqual((entry["callback"], entry["callback_ip"]), ("", ""))
        self.assertFalse(any("allow@100.64.0.5" in r for r in entry["extra_rules"]))
        self.assertFalse(any("100.64.0.5" in arg for arg in self.msb_calls("create")[0]["argv"]))
        self.assertEqual(self.msb_calls("exec"), [])
        self.ci_ok("stop", "c-e1", "--json")
        self.ci_ok("managed", "start", "e1", stdin=json.dumps({"secrets": [
            {"name": "LLM_KEY", "value": PLANTED_CI, "hosts": ["llm.example.org"]}]}) + "\n")
        self.assertEqual(self.msb_calls("exec"), [])

    def test_a_callback(self):
        # ci.example.org resolves to 100.64.0.5 here (CGNAT, not public), so
        # *.example.org admits it only with the name in private_names.
        self.ci_table = CI + 'private_names = ["ci.example.org"]\n'
        self.configure()
        rec = self.ci_provision(callback={"host": "ci.example.org", "port": 8443})
        entry = self.m.read_toml(self.entry_path(rec["name"]))
        self.assertEqual((entry["callback"], entry["callback_ip"]), ("ci.example.org", "100.64.0.5"))
        self.assertIn("allow@100.64.0.5:tcp:8443", entry["extra_rules"])
        self.assertEqual(self.msb_calls("exec")[0]["argv"][-2:], ["100.64.0.5", "ci.example.org"])
        # kandev_api is the same key under its protocol-1 name; both is ambiguous.
        self.ci_provision("e2", operation_id="op-2", kandev_api={"host": "ci.example.org"})
        self.assertIn("one of", self.ci_error("invalid_config", "managed", "provision", "e3", stdin=ci_request(
            operation_id="op-3", callback={"host": "a.example.org"}, kandev_api={"host": "a.example.org"}))["message"])

    def test_a_callback_is_checked_when_given(self):
        for bad in ({"port": 443}, {"host": 5}, "ci.example.org", {"host": "*.example.org"},
                    {"host": "not a host"}, {"host": "ci.example.org", "port": 0},
                    {"host": "ci.example.org", "port": "443"}, {"host": "ci.example.org", "port": True}):
            with self.subTest(callback=bad):
                self.assertIn("callback", self.ci_error("invalid_config", "managed", "provision", "e1",
                                                        stdin=ci_request(callback=bad))["message"])
        self.assertEqual((self.msb_calls("create"), self.msb_calls("exec")), ([], []))
        self.assertFalse(os.path.exists(self.entry_path("c-e1")))

    def test_kandev_still_needs_its_callback(self):
        """Optional for a client, never for Kandev: protocol 1 refuses a
        provision without `kandev_api` as it always has, and so does the
        Kandev key's protocol 2."""
        body = json.loads(request(operation_id="op-9"))
        del body["kandev_api"]
        for argv, key in ((("kandev", "provision", "e9"), "kandev_api"),
                          (("managed", "provision", "e9"), "callback")):
            with self.subTest(argv=argv):
                code, doc = self.msbctl_json(*argv, stdin=json.dumps(body) + "\n")
                self.assertEqual((code, doc), (3, {"error": {"code": "invalid_config",
                                                             "message": f"{key} needs a host"}}))
        self.assertEqual(self.msb_calls("create"), [])
        self.assertFalse(os.path.exists(self.m.registry_path_for("k-e9")))

    def test_require_callback(self):
        self.ci_table = CI + 'require_callback = true\nprivate_names = ["ci.example.org"]\n'
        self.configure()
        self.assertIn("callback", self.ci_error("invalid_config", "managed", "provision", "e1",
                                                stdin=ci_request())["message"])
        self.ci_provision(callback={"host": "ci.example.org"})

    def test_a_callback_outside_allow_extra_is_refused(self):
        """A callback is egress to one address and port, so ci's own
        allow_extra (pypi.org, *.example.org) must admit it, as it must an
        egress_allow target: refused otherwise, before anything is created."""
        for key, callback, shown in (
                ("callback", {"host": "192.0.2.9", "port": 22}, "192.0.2.9:22"),
                ("kandev_api", {"host": "192.0.2.9", "port": 22}, "192.0.2.9:22"),
                # A name allow_extra does not list, resolved here to an
                # address it does not list either.
                ("callback", {"host": "ci.example.net"}, "ci.example.net:443")):
            with self.subTest(key=key, callback=callback):
                self.assertEqual(self.ci_error("invalid_config", "managed", "provision", "e1",
                                               stdin=ci_request(**{key: callback}))["message"],
                                 f"{key} {shown} is not allowed by [clients.ci] allow_extra")
        # The same address through egress_allow is refused as it always was.
        self.ci_error("invalid_config", "managed", "provision", "e1",
                      stdin=ci_request(egress_allow=["llm.example.org", "192.0.2.9:22"]))
        self.assertEqual((self.msb_calls("create"), self.msb_calls("exec")), ([], []))
        self.assertFalse(os.path.exists(self.entry_path("c-e1")))

    def test_a_callback_allow_extra_admits(self):
        """By its host at any port (test_a_callback), by its address at an
        address:port entry's one port, or by its resolved address in a CIDR."""
        self.ci_table = CI.replace('allow_extra = ["pypi.org", "*.example.org"]',
                                   'allow_extra = ["pypi.org", "*.example.org", "192.0.2.9:22", "100.64.0.0/10"]')
        self.configure()
        rec = self.ci_provision(callback={"host": "192.0.2.9", "port": 22})
        entry = self.m.read_toml(self.entry_path(rec["name"]))
        self.assertIn("allow@192.0.2.9:tcp:22", entry["extra_rules"])
        argv = self.msb_calls("create")[0]["argv"]
        self.assertTrue(any("allow@192.0.2.9:tcp:22" in a for a in argv), argv)
        self.assertIn("allow_extra", self.ci_error("invalid_config", "managed", "provision", "e2", stdin=ci_request(
            operation_id="op-2", callback={"host": "192.0.2.9", "port": 23}))["message"])
        rec = self.ci_provision("e3", operation_id="op-3", callback={"host": "ci.example.net", "port": 8443})
        entry = self.m.read_toml(self.entry_path(rec["name"]))
        self.assertEqual((entry["callback"], entry["callback_ip"]), ("ci.example.net", "100.64.0.5"))
        self.assertIn("allow@100.64.0.5:tcp:8443", entry["extra_rules"])

    def test_a_callback_by_pattern_must_resolve_public(self):
        """A hostname pattern admits a callback by name only when the address
        it resolves to on the host is public: the rule pins that address, so
        msb's DNS rebind protection never sees it, and the same name in
        egress_allow would get no private answer without private_names."""
        for addr in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "100.64.0.5", "192.88.99.1"):
            with self.subTest(addr=addr), mock.patch.object(tk, "API_ADDR", addr):
                err = self.ci_error("invalid_config", "managed", "provision", "e1",
                                    stdin=ci_request(callback={"host": "lan.example.org", "port": 22}))
                self.assertEqual(err["message"], "callback lan.example.org resolves to a private or reserved "
                                 "address on this host: allow_extra admits only a public one by name. "
                                 "List lan.example.org in [clients.ci] private_names, or its address in allow_extra")
                self.assertNotIn(addr, err["message"])
        # The same name as egress_allow: private_names too, or refused.
        self.ci_error("invalid_config", "managed", "provision", "e1", stdin=ci_request(
            egress_allow=["llm.example.org", "lan.example.org:22"], private_names=["lan.example.org"]))
        self.assertEqual((self.msb_calls("create"), self.msb_calls("exec")), ([], []))
        self.assertFalse(os.path.exists(self.entry_path("c-e1")))
        # A public answer is what the pattern was written for (93.184.216.34
        # is IANA's, example.com's historical address: any public one is real).
        with mock.patch.object(tk, "API_ADDR", "93.184.216.34"):
            rec = self.ci_provision(callback={"host": "lan.example.org", "port": 22})
        self.assertIn("allow@93.184.216.34:tcp:22", self.m.read_toml(self.entry_path(rec["name"]))["extra_rules"])

    def test_a_private_callback_by_private_names_or_address(self):
        """A private answer is admitted when the operator said so: the name in
        ci's private_names, or an address, CIDR or address:port entry that
        covers it. Rebind protection stays on: the rule names the address."""
        for n, (addr, table) in enumerate((
                ("10.0.0.5", 'private_names = ["lan.example.org"]\n'),
                ("127.0.0.1", 'private_names = ["lan.example.org"]\n'),
                ("169.254.169.254", 'private_names = ["lan.example.org"]\n'),
                ("10.0.0.5", None),
                ("127.0.0.1", None),
                ("169.254.169.254", None))):
            with self.subTest(addr=addr, table=table), mock.patch.object(tk, "API_ADDR", addr):
                base = CI.replace("max_sandboxes = 3", "max_sandboxes = 8")
                self.ci_table = base + table if table else base.replace(
                    'allow_extra = ["pypi.org", "*.example.org"]',
                    'allow_extra = ["pypi.org", "*.example.org", "10.0.0.0/8", "127.0.0.1:22", "169.254.169.254"]')
                self.configure()
                env = f"e{n}"
                rec = self.ci_provision(env, operation_id="op-" + env,
                                        callback={"host": "lan.example.org", "port": 22})
                entry = self.m.read_toml(self.entry_path(rec["name"]))
                self.assertEqual((entry["callback"], entry["callback_ip"]), ("lan.example.org", addr))
                self.assertIn(f"allow@{addr}:tcp:22", entry["extra_rules"])
                argv = self.msb_calls("create")[-1]["argv"]
                self.assertNotIn("--no-dns-rebind-protection", argv)
                self.assertTrue(any(f"allow@{addr}:tcp:22" in a for a in argv), argv)
        # An address:port entry covers that port only; the pattern alone then
        # needs the address public.
        with mock.patch.object(tk, "API_ADDR", "127.0.0.1"):
            self.assertIn("private_names", self.ci_error("invalid_config", "managed", "provision", "e9", stdin=ci_request(
                operation_id="op-e9", callback={"host": "lan.example.org", "port": 23}))["message"])

    def test_star_admits_any_address_but_a_name_only_as_a_pattern(self):
        """`*` in allow_extra: a literal callback address is admitted whatever
        it is, private and reserved included, since the operator trusts the
        client with everything. For a name `*` counts as a pattern, so a
        private answer needs the name in private_names (or its address listed)."""
        star = CI.replace('allow_extra = ["pypi.org", "*.example.org"]', 'allow_extra = ["*"]').replace(
            "max_sandboxes = 3", "max_sandboxes = 8")
        self.ci_table = star
        self.configure()
        with mock.patch.object(tk, "API_ADDR", "10.0.0.5"):
            err = self.ci_error("invalid_config", "managed", "provision", "e1",
                                stdin=ci_request(callback={"host": "lan.example.org", "port": 22}))
            self.assertEqual(err["message"], "callback lan.example.org resolves to a private or reserved "
                             "address on this host: allow_extra admits only a public one by name. "
                             "List lan.example.org in [clients.ci] private_names, or its address in allow_extra")
            self.assertEqual((self.msb_calls("create"), self.msb_calls("exec")), ([], []))
            rec = self.ci_provision("e2", operation_id="op-e2", callback={"host": "10.0.0.5", "port": 22})
            entry = self.m.read_toml(self.entry_path(rec["name"]))
            self.assertEqual((entry["callback"], entry["callback_ip"]), ("10.0.0.5", "10.0.0.5"))
            self.assertIn("allow@10.0.0.5:tcp:22", entry["extra_rules"])
            self.ci_table = star + 'private_names = ["lan.example.org"]\n'
            self.configure()
            rec = self.ci_provision("e3", operation_id="op-e3", callback={"host": "lan.example.org", "port": 22})
            entry = self.m.read_toml(self.entry_path(rec["name"]))
            self.assertEqual((entry["callback"], entry["callback_ip"]), ("lan.example.org", "10.0.0.5"))
            self.assertIn("allow@10.0.0.5:tcp:22", entry["extra_rules"])

    def test_an_unlisted_callback_name_is_never_resolved(self):
        """A name no allow_extra entry could admit (no matching pattern or `*`,
        and no IPv4 address, CIDR or address:port entry at its port that its
        answer could fall in) is refused before the host looks it up: no
        resolver oracle, no lookups on a key's say."""
        settings = self.m.clients_settings(self.m.load_config())["ci"]
        dialect = self.m.managed_dialect(settings)
        req = {"callback": {"host": "x.example.net", "port": 443}}
        # Address entries that cannot hold the answer: another port, or IPv6
        # (a name resolves to IPv4 only).
        for extra in ((), ("192.0.2.9:22",), ("2001:db8::/32", "[2001:db8::9]:443", "192.0.2.9:22")):
            with self.subTest(extra=extra):
                narrow = dict(settings, allow_extra_entries=settings["allow_extra_entries"]
                              + [self.m.kandev_allow_entry(e) for e in extra])
                with mock.patch.object(self.m.socket, "getaddrinfo",
                                       side_effect=AssertionError("resolved")) as lookup:
                    with self.assertRaises(self.m.KandevError) as cm:
                        self.m.request_callback(req, dialect, narrow)
                self.assertEqual((cm.exception.code, cm.exception.message),
                                 ("invalid_config",
                                  "callback x.example.net:443 is not allowed by [clients.ci] allow_extra"))
                lookup.assert_not_called()
        # Under the key, it reads the same whether the name resolves or not.
        self.assertEqual(self.ci_error("invalid_config", "managed", "provision", "e1", stdin=ci_request(
            callback={"host": "x.example.net"}))["message"],
            "callback x.example.net:443 is not allowed by [clients.ci] allow_extra")
        # A pattern that matches, or any address entry, needs the answer: then it is looked up.
        fake = [(self.m.socket.AF_INET, self.m.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        for extra in ("*.example.net", "192.0.2.0/24", "192.0.2.9:443", "*"):
            with self.subTest(extra=extra):
                wider = dict(settings, allow_extra_entries=settings["allow_extra_entries"]
                             + [self.m.kandev_allow_entry(extra)])
                with mock.patch.object(self.m.socket, "getaddrinfo", return_value=fake) as lookup:
                    try:
                        self.m.request_callback(req, dialect, wider)
                    except self.m.KandevError:
                        pass
                lookup.assert_called_once()

    def test_guest_ports(self):
        rec = self.ci_provision(guest_ports=[8765])
        self.assertEqual(list(rec["ports"]), ["8765"])
        entry = self.m.read_toml(self.entry_path("c-e1"))
        self.assertEqual(len(entry["ports"]), 1)
        for bad in ([1, 2, 3, 4, 5], [8765, 8765], [80], [], "8765", [True]):
            with self.subTest(ports=bad):
                self.assertIn("guest_ports", self.ci_error(
                    "invalid_config", "managed", "provision", "e9",
                    stdin=ci_request(operation_id="op-9", guest_ports=bad))["message"])

    def test_one_guest_port_one_proxy_port(self):
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        self.ci_provision(guest_ports=[8765])
        entry = self.m.read_toml(self.entry_path("c-e1"))
        self.assertEqual((len(entry["ports"]), len(entry["proxy_ports"])), (1, 1))

    def test_the_env_prefix_is_reserved(self):
        for field in ("env", "secrets"):
            item = {"name": "CI_TOKEN", "value": "x", "hosts": ["llm.example.org"]}
            with self.subTest(field=field):
                self.assertIn("reserved", self.ci_error(
                    "invalid_config", "managed", "provision", "e1",
                    stdin=ci_request(**{field: [item]}))["message"])
        # Still agentctl's own, whatever the client's prefix.
        self.ci_error("invalid_config", "managed", "provision", "e1",
                      stdin=ci_request(env=[{"name": "AGENTCTL_X", "value": "1"}]))


class Agentctl(ManagedTest):

    def agentctl_input(self, blob=b"\x7fELF ci agentctl", **over):
        header = {"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
                  "nonce": PLANTED_CI_NONCE, "env": {"CI_LISTEN": "1"}}
        header.update(over)
        return json.dumps(header).encode() + b"\n" + blob

    def test_the_clients_prefix_path_and_port(self):
        self.ci_provision(guest_ports=[9000, 8765])
        os.environ["FAKE_MSB_READ_STDIN"] = "1"
        rec = self.ci_ok("managed", "agentctl", "e1", stdin=self.agentctl_input())["record"]
        self.assertTrue(rec["agentctl"]["running"])
        write, launch = self.msb_calls("exec")
        self.assertIn("/opt/ci/agentctl", write["argv"][-1])
        self.assertIn("CI_LISTEN=1", launch["argv"])
        self.assertIn('CI_BOOTSTRAP_NONCE="$n"', launch["argv"][launch["argv"].index("-c") + 1])
        self.assertIn("-port=9000", launch["argv"])          # the first port it published
        self.assertEqual(launch["stdin"]["sha256"], hashlib.sha256(PLANTED_CI_NONCE.encode() + b"\n").hexdigest())
        self.assert_not_in_argv(PLANTED_CI_NONCE)
        self.assert_nowhere_on_disk(PLANTED_CI_NONCE)

    def test_only_the_clients_prefix(self):
        self.ci_provision()
        for env in ({"AGENTCTL_LISTEN": "1"}, {"CI_BOOTSTRAP_NONCE": "x"}, {"PATH": "/tmp"}):
            with self.subTest(env=env):
                self.assertIn("CI_*", self.ci_error("invalid_config", "managed", "agentctl", "e1",
                                                    stdin=self.agentctl_input(env=env))["message"])
        self.assertEqual(self.msb_calls("exec"), [])


class Isolation(ManagedTest):
    """Two clients on one host: neither sees, stops or purges the other's."""

    def setUp(self):
        super().setUp()
        self.provision("e1")                     # Kandev's k-e1
        self.ci_provision("e1")                  # ci's c-e1, the same environment id

    def test_lists_are_disjoint(self):
        self.assertEqual([r["name"] for r in self.jok("ls", "--json")["sandboxes"]], ["k-e1"])
        rows = self.ci_ok("ls", "--json")["sandboxes"]
        self.assertEqual([(r["name"], r["source"], r["client"], r["location"]) for r in rows],
                         [("c-e1", "managed", "ci", "ci:e1")])
        self.assertEqual(rows[0]["record"]["client"], "ci")
        self.assertNotIn("kandev", rows[0])
        # The operator at the host sees both, each under its own key.
        code, doc = self.msbctl_json("ls", "--json", plugin=False)
        rows = {r["name"]: r for r in doc["sandboxes"]}
        self.assertIn("kandev", rows["k-e1"])
        self.assertNotIn("client", rows["k-e1"])
        self.assertEqual(rows["c-e1"]["record"]["env"], "e1")

    def test_the_others_sandbox_does_not_exist(self):
        self.jerror("not_found", "show", "c-e1", "--json")
        self.jerror("not_found", "stop", "c-e1", "--json")
        self.ci_error("not_found", "show", "k-e1", "--json")
        self.ci_error("not_found", "stop", "k-e1", "--json")
        self.assertEqual(self.purge("c-e1"), {"purged": [], "absent": ["c-e1"]})
        self.assertEqual(self.ci_ok("purge", "k-e1", "-y", "--json"), {"purged": [], "absent": ["k-e1"]})
        self.assertEqual(self.fake_state()["k-e1"], "running")
        self.assertEqual(self.fake_state()["c-e1"], "running")
        self.ci_error("not_found", "managed", "lease", "nope", "8765")
        self.assertEqual(self.ci_ok("show", "c-e1", "--json")["record"]["name"], "c-e1")
        self.assertEqual(self.ci_ok("purge", "c-e1", "-y", "--json"), {"purged": ["c-e1"], "absent": []})
        self.assertNotIn("c-e1", self.fake_state())

    def test_a_key_cannot_name_another_client(self):
        self.ci_error("denied", "managed", "health", "--client", "kandev")
        code, doc = self.msbctl_json("managed", "health", "--client", "ci")
        self.assertEqual((code, doc["error"]["code"]), (3, "denied"))

    def test_the_reaper_minds_each_clients_label(self):
        state = self.fake_state()
        # A VM named like ci's sandbox but labelled Kandev's: not ci's to remove.
        state["_labels"]["c-e1"] = ["msbctl.owner=kandev"]
        for name, owner in (("c-orphan", "ci"), ("x-stray", "lab")):
            state[name] = "running"
            state["_labels"][name] = [f"msbctl.owner={owner}"]
            state["_created"][name] = "2001-01-01T00:00:00+00:00"
        with open(os.environ["FAKE_MSB_STATE"], "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        for name in ("k-e1", "c-e1"):
            self.m.set_toml_key(self.entry_path(name), "expires_at", "2001-01-01T00:00:00Z")
        out = self.reap()
        self.assertEqual(out["destroyed"], ["k-e1"])
        self.assertEqual(out["errors"], ["c-e1"])                 # without ci's label: left alone
        self.assertEqual(out["orphans_removed"], ["c-orphan"])     # lab has no table: not reaped
        left = self.fake_state()
        self.assertIn("c-e1", left)
        self.assertIn("x-stray", left)

    def test_a_broken_kandev_table_stops_no_ones_expiry(self):
        # [kandev]'s client keys are Kandev's alone: the reaper reads only the
        # host's, so ci's expired sandbox goes, and Kandev's own too, by its
        # label. A wrong value or a wrong type alike.
        for over in ({"max_sandboxes": '"twelve"'}, {"rule_groups": '[["base"]]'}):
            with self.subTest(**over):
                self.configure()
                self.provision("e1")
                self.ci_provision("e1")
                for name in ("k-e1", "c-e1"):
                    self.m.set_toml_key(self.entry_path(name), "expires_at", "2001-01-01T00:00:00Z")
                self.configure(**over)
                self.assertEqual(self.error("invalid_config", "health")["code"], "invalid_config")
                self.assertTrue(self.ci_ok("managed", "health")["enabled"])
                self.assertEqual(sorted(self.reap()["destroyed"]), ["c-e1", "k-e1"])
                self.assertNotIn("c-e1", self.fake_state())

    def test_a_broken_client_table_stops_no_ones_expiry(self):
        for name in ("k-e1", "c-e1"):
            self.m.set_toml_key(self.entry_path(name), "expires_at", "2001-01-01T00:00:00Z")
        self.ci_table = CI.replace("max_sandboxes = 3", 'max_sandboxes = "x"')
        self.configure()
        self.assertEqual(sorted(self.reap()["destroyed"]), ["c-e1", "k-e1"])

    def test_only_the_hosts_keys_stop_the_reaper(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write('[managed]\nbase_url = "https://[x"\n')
        code, doc = self.msbctl_json("host", "kandev", "reap", plugin=False)
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"))

    def test_caps_are_per_client(self):
        self.ci_provision("e2", operation_id="op-2")
        self.ci_provision("e3", operation_id="op-3")
        self.ci_error("rate_limited", "managed", "provision", "e4", stdin=ci_request(operation_id="op-4"))
        self.provision("e2", operation_id="op-k2")              # Kandev's cap is its own (12)

    def test_host_totals_cap_both(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[managed]\nmax_cpus = 6\n")
        self.ci_provision("e2", operation_id="op-2")             # 2 + 2 + 2 cpus
        err = self.ci_error("rate_limited", "managed", "provision", "e3", stdin=ci_request(operation_id="op-3"))
        self.assertIn("[managed]", err["message"])
        self.assertIn("[managed]", self.error("rate_limited", "provision", "e3",
                                              stdin=request(operation_id="op-k3"))["message"])

    def test_the_operator_looks_but_does_not_touch(self):
        code, _, err = self.run_main("start", "c-e1")
        self.assertNotEqual(code, 0)
        self.assertIn("client ci's sandbox", err)
        self.assertIn("ci", self.m.name_problem("c-mine"))
        self.assertIn("Kandev", self.m.name_problem("k-mine"))
        self.assertIsNone(self.m.name_problem("d-mine"))

    def test_doctor_is_scoped(self):
        _code, doc = self.as_ci("doctor", "--json")       # exit 1 without /dev/kvm here
        checks = {c["id"]: c for c in doc["checks"]}
        self.assertEqual(checks["registry"]["message"], "1 ci sandbox(es) registered")
        for gone in ("github-token", "secret-store", "autostart"):
            self.assertNotIn(gone, checks)

    def test_proxy_wants_enabled_clients_only(self):
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        self.ci_provision("p1", operation_id="op-p1")
        self.provision("p1", operation_id="op-kp1")
        held, why = self.m.kandev_proxy_wanted({})
        self.assertIsNone(why)
        self.assertEqual({client for _, _, client in held.values()}, {"kandev", "ci"})
        self.ci_table = CI.replace("enabled = true", "enabled = false")
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        want, _ = self.m.kandev_proxy_wanted(held)
        self.assertEqual({client for _, _, client in want.values()}, {"kandev"})
        # A table that does not check out keeps the ports it has open (one
        # being edited), and gets no new ones.
        self.ci_table = CI.replace("max_sandboxes = 3", "max_sandboxes = -3")
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        with mock.patch.object(self.m, "kandev_proxy_log", lambda line: None):
            want, _ = self.m.kandev_proxy_wanted(held)
            self.assertEqual(want, held)
            want, _ = self.m.kandev_proxy_wanted({k: v for k, v in held.items() if v[2] == "kandev"})
        self.assertEqual({client for _, _, client in want.values()}, {"kandev"})


class ClientClashes(ManagedTest):
    """A problem in [clients] is the problem of the clients it concerns:
    Kandev, and every client it does not concern, go on as before."""

    ci_table = CI + "\n[clients.cd]\nenabled = true\n[clients.lab]\nenabled = true\n"   # cd: c-, as ci

    def assert_kandev_and_lab_go_on(self):
        self.assertTrue(self.ok("health")["enabled"])
        self.provision("e1")
        self.assertEqual([r["env"] for r in self.listed()], ["e1"])
        self.assertEqual(self.jok("show", self.listed()[0]["name"], "--json")["kandev"]["env"], "e1")
        code, doc = self.as_ci("managed", "health", key="client:lab")
        self.assertEqual((code, doc["enabled"], doc["client_settings"]["name_prefix"]), (0, True, "l-"), doc)
        code, doc = self.as_ci("ls", "--json", key="client:lab")
        self.assertEqual((code, doc["sandboxes"]), (0, []), doc)

    def test_two_clients_sharing_a_prefix(self):
        self.assert_kandev_and_lab_go_on()
        for key in ("client:ci", "client:cd"):
            for argv, stdin in ((("managed", "health"), ""), (("managed", "provision", "e2"), ci_request()),
                                (("ls", "--json"), "")):
                with self.subTest(key=key, argv=argv):
                    code, doc = self.as_ci(*argv, stdin=stdin, key=key)
                    self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
                    # Neither hears the other's name, nor the prefix.
                    self.assertNotIn("c-", doc["error"]["message"])
                    self.assertNotIn("[clients.", doc["error"]["message"])
                    self.assertIn("msbctl doctor", doc["error"]["message"])
        self.assertEqual(self.m.registered(), ["k-e1"])
        code, doc = self.msbctl_json("managed", "health", "--client", "ci", plugin=False)
        self.assertIn("[clients.ci] name_prefix 'c-' is also [clients.cd]'s", doc["error"]["message"])

    def test_a_table_whose_name_is_not_a_client_name(self):
        self.ci_table = CI + "\n[clients.Bad]\nenabled = true\n[clients.lab]\nenabled = true\n"
        self.configure()
        self.assert_kandev_and_lab_go_on()
        self.assertEqual(self.ci_ok("managed", "health")["client"], "ci")

    def test_an_entry_under_clients_that_is_not_a_table(self):
        self.ci_table = "\n[clients]\nfoo = 1\n" + CI + "\n[clients.lab]\nenabled = true\n"
        self.configure()
        self.assert_kandev_and_lab_go_on()
        self.assertEqual(self.ci_ok("managed", "health")["client"], "ci")
        code, doc = self.as_ci("managed", "health", key="client:foo")
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)

    def test_the_proxy_goes_on_serving_kandev(self):
        self.ci_table = CI
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        self.ci_provision("p1", operation_id="op-p1")
        held, _ = self.m.kandev_proxy_wanted({})
        self.ci_table = CI + "\n[clients.cd]\nenabled = true\n"
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        self.provision("p2", operation_id="op-kp2")          # after the clash: still gets its ports
        said = []
        with mock.patch.object(self.m, "kandev_proxy_log", said.append):
            want, why = self.m.kandev_proxy_wanted(held)
        self.assertIsNone(why)
        owners = {(name, client) for name, _, client in want.values()}
        # ci, clashing, keeps the ports it has open, as any table that does not check out.
        self.assertEqual(owners, {("k-p2", "kandev"), ("c-p1", "ci")})
        self.assertTrue(any("[clients.ci] name_prefix" in line for line in said), said)


class WrongTypes(ManagedTest):
    """A value of any wrong type, anywhere a client or the host reads one,
    answers invalid_config to whom it concerns and stops no one else: Kandev's
    protocol 1 and ci go on, and the proxy keeps every port it holds."""

    def setUp(self):
        super().setUp()
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
        self.provision("p1", operation_id="op-kp1")
        self.ci_provision("p1", operation_id="op-p1")
        self.held = self.scan({})
        self.assertEqual({(n, c) for n, _, c in self.held.values()}, {("k-p1", "kandev"), ("c-p1", "ci")})

    def scan(self, current):
        """What the proxy loop holds after one scan: on a config that raises
        (KandevError only), what is open and still backed."""
        with mock.patch.object(self.m, "kandev_proxy_log", lambda line: None):
            try:
                return self.m.kandev_proxy_wanted(current)[0]
            except self.m.KandevError:
                return self.m.kandev_proxy_backed(current, self.m.managed_entries())

    def answers(self, code, doc):
        """True when it answered normally, False on invalid_config; never
        anything else."""
        if code == 0:
            return True
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        return False

    def assert_proxy_holds(self):
        want = self.scan(self.held)
        self.assertEqual({k: v for k, v in want.items() if k in self.held}, self.held)

    def test_in_another_clients_table(self):
        for key in (*self.m.CLIENT_KEYS, *self.m.MANAGED_HOST_KEYS, *UNKNOWN_KEYS):
            for kind in WRONG_TYPES:
                if (key, kind) in RIGHT_TYPES:
                    continue
                with self.subTest(key=key, kind=kind):
                    self.ci_table = CI + toml_key("clients.zz", key, kind,
                                                  "" if key == "enabled" else "enabled = true\n")
                    self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"')
                    self.assertTrue(self.ok("health")["enabled"])
                    self.assertEqual([r["env"] for r in self.listed()], ["p1"])
                    self.assertEqual(self.ci_ok("managed", "health")["client"], "ci")
                    self.assertFalse(self.answers(*self.as_ci("managed", "health", key="client:zz")))
                    self.assert_proxy_holds()

    def test_in_kandevs_table_or_the_hosts(self):
        host = {"serve": '"proxy"', "proxy_listen": '"127.0.0.1"'}
        for table, keys in (("kandev", (*self.m.CLIENT_KEYS, *self.m.MANAGED_HOST_KEYS, *UNKNOWN_KEYS)),
                            ("managed", (*self.m.MANAGED_HOST_KEYS, *self.m.MANAGED_HOST_TOTALS, *UNKNOWN_KEYS))):
            for key in keys:
                for kind, value in WRONG_TYPES.items():
                    with self.subTest(table=table, key=key, kind=kind):
                        # The key leaves [kandev]'s usual lines: set there and
                        # in [managed] would be refused before its type is read.
                        over = {**host, key: None}
                        if table == "managed":
                            self.ci_table = toml_key(table, key, kind) + CI
                        elif value is None:     # after configure()'s [kandev]
                            self.ci_table = f"\n[kandev.{key}]\na = 1\n" + CI
                        else:
                            over[key], self.ci_table = value, CI
                        self.configure(**over)
                        self.answers(*self.kandev("health"))
                        self.answers(*self.as_ci("managed", "health"))
                        self.assert_proxy_holds()

    def test_in_a_registry_entry(self):
        # proxy_ports written by hand: no one's port, never the end of the proxy.
        for kind, value in WRONG_TYPES.items():
            for enabled in ("true", "false"):
                with self.subTest(kind=kind, enabled=enabled):
                    self.ci_table = CI.replace("enabled = true", f"enabled = {enabled}")
                    self.configure(enabled=enabled, serve='"proxy"', proxy_listen='"127.0.0.1"')
                    path = self.m.registry_path_for("c-p1")
                    with open(path, encoding="utf-8") as fh:
                        kept = fh.read()
                    bad = tomllib.loads(f"v = {value}")["v"] if value is not None else {"a": 1}
                    self.m.kandev_set("c-p1", proxy_ports=7)          # one line, then by hand
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read().replace("proxy_ports = 7\n", "" if value is None
                                                 else f"proxy_ports = {value}\n")
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text + ("[proxy_ports]\na = 1\n" if value is None else ""))
                    try:
                        self.assertEqual(self.m.read_toml(path)["proxy_ports"], bad)
                        want, fresh = self.scan(self.held), self.scan({})     # held, and after a restart
                        self.answers(*self.kandev("health"))
                        self.answers(*self.as_ci("managed", "health"))
                    finally:
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(kept)
                    ours = {k: v for k, v in self.held.items() if v[2] == "kandev"}
                    self.assertEqual({k: v for k, v in want.items() if v[2] == "kandev"},
                                     ours if enabled == "true" else {})
                    self.assertFalse([v for v in want.values() if v[0] == "c-p1"])
                    self.assertEqual(fresh, want)


class ProxyFreeze(ManagedTest):
    """A client whose table does not check out keeps exactly the proxy ports
    it has open and gets none from the registry, as a broken [kandev] always
    has: it never reopens what `enabled = false` closed, and after a proxy
    restart it opens none until it is fixed. Kandev behaves as it does on a
    host where it is the only client."""

    def set_tables(self, ci_table, **kandev):
        self.ci_table = ci_table
        self.configure(serve='"proxy"', proxy_listen='"127.0.0.1"', **kandev)

    def scan(self, current):
        """What the proxy loop holds after one scan from `current`: on a
        config that raises, it keeps everything it has whose sandbox is
        still there."""
        with mock.patch.object(self.m, "kandev_proxy_log", lambda line: None):
            try:
                return self.m.kandev_proxy_wanted(current)[0]
            except (self.m.KandevError, SystemExit):
                return self.m.kandev_proxy_backed(current, self.m.managed_entries())

    @staticmethod
    def owners(held):
        return {(name, client) for name, _, client in held.values()}

    def ci_closed_by_disabling(self):
        """ci's c-p1 served, then ci disabled: what the proxy holds after."""
        self.set_tables(CI)
        self.ci_provision("p1", operation_id="op-p1")
        held = self.scan({})
        self.assertEqual(self.owners(held), {("c-p1", "ci")})
        self.set_tables(CI.replace("enabled = true", "enabled = false"))
        held = self.scan(held)
        self.assertEqual(held, {})
        return held

    def test_a_clash_does_not_reopen_a_disabled_client(self):
        held = self.ci_closed_by_disabling()
        # cd, added by hand, defaults to c- as ci does: both break.
        self.set_tables(CI.replace("enabled = true", "enabled = false") + "\n[clients.cd]\nenabled = true\n")
        self.assertEqual(self.scan(held), {})

    def test_a_typo_does_not_reopen_a_disabled_client(self):
        held = self.ci_closed_by_disabling()
        self.set_tables(CI.replace("enabled = true", "enabled = false")
                        .replace("max_sandboxes = 3", "max_sandboxes = -3"))
        self.assertEqual(self.scan(held), {})

    def test_after_a_restart_a_broken_client_opens_nothing(self):
        self.set_tables(CI)
        self.ci_provision("p1", operation_id="op-p1")
        self.provision("p2", operation_id="op-kp2")
        held = self.scan({})
        self.set_tables(CI + "\n[clients.cd]\nenabled = true\n")
        self.assertEqual(self.scan(held), held)                  # running: kept as open
        # A fresh proxy (restart-proxy, a reboot, an update) holds nothing yet.
        self.assertEqual(self.owners(self.scan({})), {("k-p2", "kandev")})

    def health_ports(self, held):
        """Kandev's health `serve.ports` while the proxy holds `held`."""
        self.m.write_json(self.m.KANDEV_PROXY_STATE, {"version": "v", "ports": sorted(k[1] for k in held)})
        with mock.patch.object(self.m, "kandev_proxy_version", lambda: "v"):
            return self.ok("health")["serve"]["ports"]

    def test_a_sandbox_removed_while_broken_loses_its_ports(self):
        self.set_tables(CI)
        self.ci_provision("p1", operation_id="op-p1")
        self.ci_provision("p2", operation_id="op-p2")
        held = self.scan({})
        p1 = {k[1] for k, v in held.items() if v[0] == "c-p1"}
        self.set_tables(CI.replace("max_sandboxes = 3", "max_sandboxes = -3"))      # broken
        self.assertEqual(self.scan(held), held)
        code, doc = self.msbctl_json("purge", "c-p1", "-y", "--json", plugin=False)
        self.assertEqual(code, 0, doc)
        held = self.scan(held)
        # Closed on the next scan: no longer ci's, so no one's, and no other
        # client's health lists it.
        self.assertEqual(self.owners(held), {("c-p2", "ci")})
        self.assertFalse(p1 & set(self.health_ports(held)))
        self.assertEqual(self.scan(held), held)                  # and still nothing reopens

    def test_a_kandev_sandbox_removed_while_kandevs_table_is_broken(self):
        # Kandev-only, its table broken: the loop keeps what it has, but not
        # a port whose sandbox is gone.
        self.set_tables("")
        self.provision("p1", operation_id="op-kp1")
        self.provision("p2", operation_id="op-kp2")
        held = self.scan({})
        self.set_tables("", max_sandboxes=-1)
        self.assertEqual(self.scan(held), held)
        code, doc = self.msbctl_json("purge", "k-p1", "-y", "--json", plugin=False)     # the operator, or the reaper
        self.assertEqual(code, 0, doc)
        self.assertEqual(self.owners(self.scan(held)), {("k-p2", "kandev")})

    def test_said_again_when_broken_again(self):
        self.set_tables(CI)
        self.ci_provision("p1", operation_id="op-p1")
        held = self.scan({})
        said = []
        for table in (CI.replace("max_sandboxes = 3", "max_sandboxes = -3"),) * 2 + (CI,) + \
                (CI.replace("max_sandboxes = 3", "max_sandboxes = -3"),):
            self.set_tables(table)
            with mock.patch.object(self.m, "kandev_proxy_log", said.append):
                held = self.m.kandev_proxy_wanted(held)[0]
        self.assertEqual(len([line for line in said if "[clients.ci] max_sandboxes" in line]), 2, said)

    def test_kandev_as_on_a_kandev_only_host(self):
        seen = {}
        for host, ci_table in (("kandev-only", ""), ("with ci", CI)):
            with self.subTest(host=host):
                self.set_tables(ci_table)
                self.provision("p1", operation_id="op-kp1")
                served = self.scan({})
                self.assertEqual(self.owners(served), {("k-p1", "kandev")})
                self.set_tables(ci_table, max_sandboxes=-1)             # broken while serving
                broken = (self.scan(served), self.scan({}))
                self.assertEqual(broken, (served, {}))
                self.set_tables(ci_table, enabled="false")
                closed = self.scan(served)
                self.assertEqual(closed, {})
                self.set_tables(ci_table, enabled="false", max_sandboxes=-1)   # disabled, then a typo
                after = self.scan(closed)
                self.assertEqual(after, {})
                seen[host] = (self.owners(served), [self.owners(h) for h in broken], after)
                self.set_tables(ci_table)
                self.purge("k-p1")
        self.assertEqual(seen["kandev-only"], seen["with ci"])


class ClientNames(ManagedTest):

    def write_entry(self, name):
        os.makedirs(self.m.REGISTRY_DIR, exist_ok=True)
        with open(self.entry_path(name), "w", encoding="utf-8") as fh:
            fh.write(f'name = "{name}"\nsource = "folder"\nproject = "/tmp"\n')

    def test_a_taken_name_is_not_named_to_a_client(self):
        # The operator's own sandbox under ci's prefix: ci hears that the name
        # is taken, never what it is.
        self.write_entry("c-e1")
        err = self.ci_error("conflict", "managed", "provision", "e1", stdin=ci_request())
        self.assertEqual(err["message"], "this environment's name is taken on this host by a sandbox "
                                         "that is not ci's")
        # Kandev's words are protocol 1's.
        self.write_entry("k-e1")
        err = self.error("conflict", "provision", "e1", stdin=request())
        self.assertEqual(err["message"], "k-e1 is a sandbox that is not Kandev's")


class KandevsPrefix(ManagedTest):
    """k- is Kandev's on every host: no client takes it, by default or
    outright, while Kandev's table is broken or after, and a client that asks
    for it is the only one that stops."""

    ci_table = '\n[clients.kube]\nenabled = true\nallow_extra = ["pypi.org"]\n'

    def kube(self, *argv, stdin=""):
        return self.as_ci(*argv, stdin=stdin, key="client:kube")

    def test_while_kandevs_table_is_broken(self):
        self.configure(max_cpus=-1)
        code, doc = self.kube("managed", "provision", "e1",
                              stdin=ci_request(secrets=None, egress_allow=["pypi.org"]))
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["record"]["name"], "ku-e1")
        self.configure()                        # Kandev's fixed: both work
        code, doc = self.kandev("health")
        self.assertEqual((code, doc["enabled"]), (0, True), doc)
        self.assertEqual(self.kube("managed", "health")[0], 0)

    def test_asked_for_outright(self):
        self.ci_table += 'name_prefix = "k-"\n'
        self.configure()
        code, doc = self.kube("managed", "provision", "e1",
                              stdin=ci_request(secrets=None, egress_allow=["pypi.org"]))
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        self.assertIn("k- is always Kandev's", doc["error"]["message"])
        self.assertEqual(self.kandev("health")[0], 0)
        self.assertEqual(self.provision("k1")["name"], "k-k1")


class KandevsGuestPorts(ManagedTest):
    """Kandev's entries keep protocol 1's four ports, in either protocol."""

    def test_managed_provision_refuses_others(self):
        code, doc = self.msbctl_json("managed", "provision", "e9",
                                     stdin=request(guest_ports=[41001], operation_id="op-9"))
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        self.assertIn("guest_ports: Kandev's are fixed", doc["error"]["message"])
        self.assertFalse(os.path.exists(self.m.registry_path_for("k-e9")))
        # Its own four, said outright, are what it gets anyway.
        ports = list(self.m.KANDEV_GUEST_PORTS)
        code, doc = self.msbctl_json("managed", "provision", "e9",
                                     stdin=request(guest_ports=ports, operation_id="op-9"))
        self.assertEqual(code, 0, doc)
        entry = self.m.read_toml(self.m.registry_path_for("k-e9"))
        self.assertEqual(sorted(self.m.kandev_ports(entry)), sorted(ports))
        self.assertEqual(self.m.agentctl_port(entry), ports[0])

    def test_protocol_1_never_read_them(self):
        code, doc = self.kandev("provision", "e8", stdin=request(guest_ports=[41001], operation_id="op-8"))
        self.assertEqual(code, 0, doc)
        entry = self.m.read_toml(self.m.registry_path_for("k-e8"))
        self.assertEqual(sorted(self.m.kandev_ports(entry)), sorted(self.m.KANDEV_GUEST_PORTS))


class ConfigProblemsUnderAKey(ManagedTest):
    """What a client's key hears of the host's config: its own table's
    problems, never another client's name or prefix, and a host key in its
    table refused outright."""

    def test_a_clash_names_no_one(self):
        self.ci_table = CI + '\n[clients.secretco]\nname_prefix = "c-"\n'
        self.configure()
        err = self.ci_error("invalid_config", "managed", "health")
        self.assertNotIn("secretco", err["message"])
        self.assertIn("msbctl doctor", err["message"])
        self.assertEqual(self.kandev("health")[0], 0)
        code, doc = self.msbctl_json("managed", "health", "--client", "ci", plugin=False)
        self.assertIn("secretco", doc["error"]["message"])      # the operator: named

    def test_a_host_key_in_a_client_table(self):
        self.ci_table = CI + 'base_url = "https://other.example.org"\n'
        self.configure()
        err = self.ci_error("invalid_config", "managed", "health")
        self.assertIn("[clients.ci] base_url: a host key", err["message"])
        self.assertEqual(self.kandev("health")[0], 0)

    def test_messages_name_the_host_table(self):
        self.configure(serve='"proxy"')
        doc = self.ci_ok("managed", "health")
        self.assertEqual(doc["serve"]["reason"], "[managed] proxy_listen is not set")
        code, doc = self.kandev("health")
        self.assertEqual(doc["serve"]["reason"], "[kandev] proxy_listen is not set")   # protocol 1's words
        self.configure(base_url=None)
        self.ci_provision()
        err = self.ci_error("unavailable", "managed", "lease", "e1", "8765")
        self.assertEqual(err["message"], "[managed] base_url is not set")

    def test_a_broken_tables_prefix_stays_reserved(self):
        self.ci_table = CI + "max_cpus = -1\n"
        self.configure()
        problem = self.m.name_problem("c-mine")
        self.assertIn("kept for ci", problem)

    def test_what_no_check_foresaw_is_named_and_traced_at_the_host(self):
        # A check that raises something else (a value of a type no check
        # knows, or a bug in the check) is invalid_config naming the
        # exception's type. Its traceback goes to stderr at the host (the
        # operator's terminal, the reaper's journal), once per process; never
        # under a key, where stderr crosses ssh; never into the JSON.
        def regression(_text):
            raise NameError("a regression")

        self.m._CONFIG_TRACES.clear()
        bug = mock.patch.object(self.m, "kandev_allow_entry", regression)
        with bug:
            os.environ["MSB_RESTRICTED"] = "client:ci"
            try:
                code, out, err = self.run_main("ls", "--json")
            finally:
                os.environ.pop("MSB_RESTRICTED", None)
            self.assertEqual((code, json.loads(out)["error"]["code"]), (3, "invalid_config"))
            self.assertEqual(json.loads(out)["error"]["message"], "[clients.ci] does not check out "
                             "(NameError; `msbctl config` shows where it is set)")
            self.assertNotIn("Traceback", err)
            code, out, err = self.run_main("host", "kandev", "reap")
            self.assertEqual(code, 0, err)
            self.assertNotIn("Traceback", out)
            json.loads(out)
            self.assertIn("Traceback", err)
            self.assertIn("NameError: a regression", err)
            code, out, err = self.run_main("host", "kandev", "reap")
            self.assertEqual(code, 0, err)
            self.assertNotIn("Traceback", err)                  # once per process
            # The client's name, however it is passed.
            config = self.m.load_config()
            with contextlib.redirect_stderr(io.StringIO()):
                for call, table in ((lambda: self.m.client_settings(config, name="ci"), "[clients.ci]"),
                                    (lambda: self.m.client_settings(config=config, name="kandev"), "[kandev]"),
                                    (lambda: self.m.client_settings(config, "ci", operator=None), "[clients.ci]")):
                    with self.assertRaises(self.m.KandevError) as caught:
                        call()
                    self.assertTrue(caught.exception.message.startswith(f"{table} does not check out (NameError;"),
                                    caught.exception.message)


class Configure(ManagedTest):
    """`host managed configure`: the operator's way to set [managed] and
    [clients.NAME], checked whole before the file changes."""

    ci_table = ""

    def configure_json(self, *flags):
        return self.msbctl_json("host", "managed", "configure", *flags, "--json", plugin=False)

    def text(self):
        with open(self.m.CONFIG_FILE, encoding="utf-8") as fh:
            return fh.read()

    def test_a_client_table(self):
        code, doc = self.configure_json("--client", "ci", "--enabled", "--env-prefix", "CI_",
                                        "--guest-port", "8765", "--allow-extra", "*.example.org",
                                        "--body-secret-host", "llm.example.org", "--max-sandboxes", "2")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["changed"], ["enabled", "max_sandboxes", "allow_extra", "env_prefix",
                                          "guest_ports", "body_secret_hosts"])
        self.assertEqual((doc["client"], doc["settings"]["name_prefix"], doc["settings"]["guest_ports"]),
                         ("ci", "c-", [8765]))
        self.assertIn("[clients.ci]", self.text())
        self.assertTrue(self.ci_ok("managed", "health")["enabled"])
        code, doc = self.configure_json("--client", "ci", "--enabled")
        self.assertEqual((code, doc["changed"]), (0, []))

    def test_host_keys_go_where_they_are(self):
        # [kandev] holds base_url (KandevTest.configure): it stays the one copy.
        code, doc = self.configure_json("--base-url", "https://sbx.example.org", "--max-cpus", "8")
        self.assertEqual(code, 0, doc)
        config = self.m.read_toml(self.m.CONFIG_FILE)
        self.assertEqual(config["kandev"]["base_url"], "https://sbx.example.org")
        self.assertEqual(config["managed"], {"max_cpus": 8})
        self.assertEqual(doc["host"]["host_max_cpus"], 8)

    def test_refusals_leave_the_file(self):
        before = self.text()
        for flags, word in ((["--client", "ci", "--env-prefix", "ci_"], "env_prefix"),
                            (["--client", "ci", "--name-prefix", "k-"], "name_prefix"),
                            (["--client", "kandev", "--env-prefix", "X_"], "fixed for Kandev"),
                            (["--client", "ci", "--serve", "none"], "--serve"),
                            (["--enabled"], "--client"),
                            (["--client", "Bad", "--enabled"], "client name"),
                            (["--client", "ci", "--body-secret-host", "llm.example.org"], "body_secret_hosts")):
            with self.subTest(flags=flags):
                code, doc = self.configure_json(*flags)
                self.assertEqual(code, 3, doc)
                self.assertIn(word, doc["error"]["message"])
                self.assertEqual(self.text(), before)

    def test_a_prefix_an_operator_sandbox_already_has(self):
        self.make_folder_sandbox("c-web")
        code, doc = self.configure_json("--client", "ci", "--enabled")
        self.assertEqual(code, 3, doc)
        self.assertIn("c-web", doc["error"]["message"])
        code, doc = self.configure_json("--client", "ci", "--enabled", "--name-prefix", "ci-")
        self.assertEqual(code, 0, doc)
        self.assertIn("ci", self.m.name_problem("ci-mine"))

    def test_a_new_prefix_while_the_old_one_has_sandboxes(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write(CI)
        self.ci_provision("e1")
        before = self.text()
        code, doc = self.configure_json("--client", "ci", "--name-prefix", "ci-")
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        self.assertIn("ci still has c-e1 under its old prefix", doc["error"]["message"])
        self.assertIn("purge", doc["error"]["message"])
        self.assertEqual(self.text(), before)
        # Its other keys are still set; once purged, the prefix moves.
        code, doc = self.configure_json("--client", "ci", "--max-sandboxes", "2")
        self.assertEqual((code, doc["changed"]), (0, ["max_sandboxes"]), doc)
        code, _, err = self.run_main("purge", "c-e1", "-y")
        self.assertEqual(code, 0, err)
        code, doc = self.configure_json("--client", "ci", "--name-prefix", "ci-")
        self.assertEqual((code, doc["settings"]["name_prefix"]), (0, "ci-"), doc)
        self.assertEqual(self.ci_provision("e1")["name"], "ci-e1")

    def test_only_at_the_host(self):
        for key in ("kandev", "client:ci", "1"):
            with self.subTest(key=key):
                os.environ["MSB_RESTRICTED"] = key
                code, _, err = self.run_main("host", "managed", "configure", "--client", "ci", "--enabled")
                os.environ.pop("MSB_RESTRICTED")
                self.assertNotEqual(code, 0)
                self.assertIn("for the host itself", err)
        self.assertNotIn("[clients.ci]", self.text())
        code, _, err = self.run_main("host", "kandev", "configure", "--env-prefix", "X_")
        self.assertNotEqual(code, 0)
        self.assertIn("host managed configure", err)

    def test_without_json(self):
        code, out, err = self.run_main("host", "managed", "configure", "--client", "ci", "--enabled")
        self.assertEqual(code, 0, err)
        self.assertIn("client ci", out + err)

    def test_doctor_names_a_broken_table(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[clients.ci]\nmax_cpus = -1\n[clients.lab]\nenabled = true\n")
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertEqual(checks["clients"]["status"], "warn")
        self.assertIn("ci: [clients.ci] max_cpus", checks["clients"]["message"])
        os.environ["MSB_RESTRICTED"] = "client:lab"
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertEqual((checks["clients"]["status"], checks["clients"]["message"]), ("ok", "enabled: lab"))

    def test_doctor_says_a_broken_table_keeps_its_open_ports(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write('[clients.lab]\nenabled = "false"\n')
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertIn("the proxy keeps the ports its sandboxes have open and opens no new ones",
                      checks["clients"]["message"])
        self.assertNotIn("enabled = false", checks["clients"]["message"])

    def test_doctor_under_a_key_names_no_other_client(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write('[clients.ci]\nenabled = true\n[clients.secretco]\nname_prefix = "c-"\n')
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertIn("secretco", checks["clients"]["message"])           # the operator's
        os.environ["MSB_RESTRICTED"] = "client:ci"
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertEqual(checks["clients"]["status"], "warn")
        self.assertNotIn("secretco", checks["clients"]["message"])
        self.assertNotIn("'c-'", checks["clients"]["message"])

    def test_kandevs_prefix_and_host_keys_are_refused(self):
        before = self.text()
        code, doc = self.configure_json("--client", "ci", "--name-prefix", "k-")
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        self.assertIn("k- is always Kandev's", doc["error"]["message"])
        self.assertEqual(self.text(), before)
        code, doc = self.configure_json("--client", "kube", "--enabled")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["settings"]["name_prefix"], "ku-")
        self.assertNotIn("host_tables", doc["host"])


    def test_a_clash_refuses_only_the_clients_in_it(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[clients.ci]\nenabled = true\n[clients.cd]\nenabled = true\n")
        before = self.text()
        code, doc = self.configure_json("--client", "ci", "--max-cpus", "4")
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
        self.assertIn("is also [clients.cd]'s", doc["error"]["message"])
        self.assertEqual(self.text(), before)
        # A client outside it, and the host's keys, are set; the clash is listed.
        code, doc = self.configure_json("--client", "lab", "--enabled")
        self.assertEqual(code, 0, doc)
        self.assertEqual(sorted(doc["problems"]), ["cd", "ci"])
        code, doc = self.configure_json("--max-sandboxes", "20")
        self.assertEqual(code, 0, doc)
        # Giving one of them its own prefix ends it.
        code, doc = self.configure_json("--client", "cd", "--name-prefix", "cd-")
        self.assertEqual((code, doc["problems"]), (0, {}), doc)

    def test_doctor_on_a_clash(self):
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[clients.ci]\nenabled = true\n[clients.cd]\nenabled = true\n")
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertEqual(checks["clients"]["status"], "warn")
        message = checks["clients"]["message"]
        self.assertIn("cd: [clients.cd] name_prefix 'c-' is also [clients.ci]'s", message)
        self.assertIn("ci: [clients.ci] name_prefix 'c-' is also [clients.cd]'s", message)
        self.assertIn("the others go on", message)
        self.assertNotIn("no client's verbs work", message)

    def test_doctor_on_clients_that_is_not_a_table(self):
        text = self.text()
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write("clients = 1\n" + text)       # before any table, so a top-level key
        config = self.m.load_config()
        self.assertEqual(config["clients"], 1)
        checks = {c["id"]: c for c in self.m.doctor_checks(config)}
        self.assertEqual(checks["clients"]["status"], "warn")
        self.assertIn("[clients] is not a table", checks["clients"]["message"])
        self.assertEqual(self.kandev("health")[0], 0)
        self.assertEqual(self.provision("k1")["name"], "k-k1")

    def test_doctor_names_a_prefix_an_operator_sandbox_has(self):
        self.make_folder_sandbox("c-web")
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("[clients.ci]\nenabled = true\n")      # by hand: configure would refuse it
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertEqual(checks["client-prefixes"]["status"], "warn")
        self.assertIn("ci's name_prefix 'c-' is the start of c-web, which ci does not own",
                      checks["client-prefixes"]["message"])
        # Not under the client's key: the operator's to act on.
        os.environ["MSB_RESTRICTED"] = "client:ci"
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertNotIn("client-prefixes", checks)
        os.environ.pop("MSB_RESTRICTED")
        # The client's own sandboxes are no finding.
        os.remove(self.m.registry_path_for("c-web"))
        checks = {c["id"]: c for c in self.m.doctor_checks(self.m.load_config())}
        self.assertNotIn("client-prefixes", checks)


if __name__ == "__main__":
    main()
