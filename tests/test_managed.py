"""msbctl managed: sandboxes owned by a client other than Kandev (protocol 2),
kept apart from Kandev's and from each other."""

import os
from unittest import main

from tests.harness import MsbctlTest


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


if __name__ == "__main__":
    main()
