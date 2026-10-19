"""`ls`, `show`, `stop` and `purge` with --json: one document on stdout, exit 0,
or exit 3 with {"error": {"code", "message"}}; and `purge` of a name with
nothing under it, which succeeds."""

import json
import os
from unittest import main

from tests.harness import MsbctlTest


class JsonVerbs(MsbctlTest):

    def json_run(self, *argv):
        code, out, err = self.run_main(*argv)
        try:
            doc = json.loads(out)
        except ValueError:
            self.fail(f"stdout is not one JSON document: {out!r}\n{err}")
        return code, doc

    def test_ls_and_show(self):
        self.make_folder_sandbox("web")
        code, doc = self.json_run("ls", "--json")
        self.assertEqual(code, 0, doc)
        self.assertEqual([r["name"] for r in doc["sandboxes"]], ["web"])
        code, doc = self.json_run("show", "web", "--json")
        self.assertEqual((code, doc["name"]), (0, "web"))

    def test_an_unknown_name_is_not_found(self):
        for argv in (["show", "nope", "--json"], ["stop", "nope", "--json"]):
            with self.subTest(argv=argv):
                code, doc = self.json_run(*argv)
                self.assertEqual(code, 3)
                self.assertEqual(doc["error"]["code"], "not_found")

    def test_stop(self):
        self.make_folder_sandbox("web")
        self.set_state(web="running")
        code, doc = self.json_run("stop", "web", "--json")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["sandboxes"][0]["name"], "web")
        self.assertEqual(self.msb_calls("stop")[0]["argv"], ["stop", "web"])

    def test_purge(self):
        self.make_folder_sandbox("web")
        code, doc = self.json_run("purge", "web", "nope", "-y", "--json")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc, {"purged": ["web"], "absent": ["nope"]})
        self.assertFalse(os.path.exists(self.entry_path("web")))

    def test_purge_json_cannot_ask(self):
        self.make_folder_sandbox("web")
        code, doc = self.json_run("purge", "web", "--json")
        self.assertEqual((code, doc["error"]["code"]), (3, "unavailable"))
        self.assertTrue(os.path.exists(self.entry_path("web")))

    def test_purging_nothing_succeeds(self):
        code, out, err = self.run_main("purge", "nope", "-y")
        self.assertEqual(code, 0, err)
        self.assertIn("nothing found named nope", out + err)


if __name__ == "__main__":
    main()
