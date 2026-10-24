"""append_toml_list / remove_from_toml_list: line-level edits of a top-level list
that must leave every other line, and the file's validity, alone."""

import os
import tomllib
import unittest

from tests.harness import MsbctlTest

MULTILINE = """\
# a comment that must survive
rule_groups = ["github"]

extra_rules = [
    "allow@archive.ubuntu.com:tcp:443",
    "allow@[fd00::1]:tcp:22",
    "allow@192.168.2.8:tcp:30000-30099",
]

[resources]
memory = "4G"
"""


class TomlListTest(MsbctlTest):

    def write(self, text):
        path = os.path.join(self.home, "list.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        return text, tomllib.loads(text)

    def test_a_new_key_goes_after_a_multiline_anchor_not_inside_it(self):
        path = self.write(MULTILINE)
        added = self.m.append_toml_list(path, "secret_binds", ["TOKEN@git.example"],
                                        after_key="extra_rules")
        self.assertEqual(added, ["TOKEN@git.example"])
        text, data = self.read(path)
        self.assertEqual(data["secret_binds"], ["TOKEN@git.example"])
        self.assertEqual(len(data["extra_rules"]), 3)
        self.assertEqual(data["resources"], {"memory": "4G"})
        self.assertIn("# a comment that must survive", text)
        self.assertLess(text.index("30099"), text.index("secret_binds"))
        self.assertLess(text.index("secret_binds"), text.index("[resources]"))

    def test_an_ipv6_rule_does_not_end_the_list_early(self):
        path = self.write(MULTILINE)
        self.m.append_toml_list(path, "extra_rules", ["allow@new.example:tcp:443"])
        _, data = self.read(path)
        self.assertEqual(data["extra_rules"][-2:],
                         ["allow@192.168.2.8:tcp:30000-30099", "allow@new.example:tcp:443"])
        self.m.remove_from_toml_list(path, "extra_rules", "allow@archive.ubuntu.com:tcp:443")
        _, data = self.read(path)
        self.assertEqual(len(data["extra_rules"]), 3)
        self.assertEqual(data["resources"], {"memory": "4G"})

    def test_a_key_inside_a_table_is_not_the_top_level_list(self):
        path = self.write('rule_groups = []\n\n[llm.x]\nextra_rules = ["kept"]\n')
        self.m.append_toml_list(path, "extra_rules", ["allow@a.example:tcp:443"],
                                after_key="rule_groups")
        _, data = self.read(path)
        self.assertEqual(data["extra_rules"], ["allow@a.example:tcp:443"])
        self.assertEqual(data["llm"]["x"]["extra_rules"], ["kept"])

    def test_removing_the_last_item_leaves_an_empty_list(self):
        path = self.write('secret_binds = ["A@a.example"]\n')
        self.m.remove_from_toml_list(path, "secret_binds", "A@a.example")
        self.assertEqual(self.read(path)[1], {"secret_binds": []})


if __name__ == "__main__":
    unittest.main()
