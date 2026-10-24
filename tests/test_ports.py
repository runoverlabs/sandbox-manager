"""Published ports print a clickable URL: an OSC 8 hyperlink when stdout is a
terminal, the plain URL otherwise, and `show --json` gets a `url` per port."""

import json
from unittest import main

from tests.harness import MsbctlTest

OSC8 = "\x1b]8;;http://127.0.0.1:3000/\x1b\\"


class PortUrlTest(MsbctlTest):

    def make_web(self, ports='ports = ["3000:5173"]\n'):
        return self.make_folder_sandbox("web", entry_extra=ports)

    def test_port_listing_prints_the_plain_url(self):
        self.make_web()
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:3000 -> 5173", out)
        self.assertIn("http://127.0.0.1:3000/", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_port_listing_hyperlinks_on_a_terminal(self):
        self.make_web()
        code, out, err = self.run_main("port", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn(OSC8, out)

    def test_show_prints_the_plain_url(self):
        self.make_web()
        code, out, err = self.run_main("show", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("http://127.0.0.1:3000/", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_show_hyperlinks_on_a_terminal(self):
        self.make_web()
        code, out, err = self.run_main("show", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn(OSC8, out)

    def test_show_json_gets_a_url_per_port(self):
        self.make_web('ports = ["3000:5173", "8080:80/udp"]\n')
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["ports"], [
            {"spec": "3000:5173", "url": "http://127.0.0.1:3000/"},
            {"spec": "8080:80/udp", "url": None},
        ])

    def test_udp_has_no_url(self):
        self.make_web('ports = ["8080:80/udp"]\n')
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:8080 -> 80/udp", out)
        self.assertNotIn("http://", out)

    def test_a_specific_bind_names_that_address(self):
        self.make_web('ports = ["192.168.1.5:8080:80"]\n')
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("http://192.168.1.5:8080/", out)

    def test_an_unspecified_bind_names_loopback(self):
        self.make_web('ports = ["0.0.0.0:8080:80"]\n')
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("http://127.0.0.1:8080/", out)


if __name__ == "__main__":
    main()
