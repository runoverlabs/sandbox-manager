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


if __name__ == "__main__":
    main()
