"""Published ports: `port_url` builds the http:// URL, and the listing / show
render it as an OSC 8 hyperlink only on a real, non-dumb, local terminal. `show
--json` keeps `ports` as strings and adds a `port_urls` map."""

import json
import os
from unittest import main, mock

from tests.harness import MsbctlTest

# The OSC 8 escape that wraps `localhost:3000` in a hyperlink to its URL.
OSC8 = "\x1b]8;;http://127.0.0.1:3000/\x1b\\localhost:3000\x1b]8;;\x1b\\"

# A real terminal: the harness's tty=True makes stdout a tty, and TERM has to be
# a real value too (msbctl treats an unset TERM as "dumb", like its TUI menus).
REAL_TERM = {"TERM": "xterm-256color"}


class PortUrlTest(MsbctlTest):

    def make_web(self, ports='ports = ["3000:5173"]\n'):
        return self.make_folder_sandbox("web", entry_extra=ports)

    # ------------------------------------------------------------------- urls

    def test_url(self):
        self.assertEqual(self.m.port_url("127.0.0.1", 3000, "tcp"),
                         "http://127.0.0.1:3000/")
        self.assertIsNone(self.m.port_url("127.0.0.1", 3000, "udp"))

    def test_url_unspecified_maps_to_its_own_loopback(self):
        self.assertEqual(self.m.port_url("0.0.0.0", 8080, "tcp"),  # noqa: S104 — a string, not a bind
                         "http://127.0.0.1:8080/")
        self.assertEqual(self.m.port_url("::", 8080, "tcp"),
                         "http://[::1]:8080/")

    def test_url_brackets_ipv6(self):
        self.assertEqual(self.m.port_url("::1", 8080, "tcp"),
                         "http://[::1]:8080/")
        self.assertEqual(self.m.port_url("192.168.1.5", 8080, "tcp"),
                         "http://192.168.1.5:8080/")

    def test_url_percent_encodes_a_zone_id(self):
        self.assertEqual(self.m.port_url("fe80::1%eth0", 8080, "tcp"),
                         "http://[fe80::1%25eth0]:8080/")

    # ---------------------------------------------------------------- listing

    def test_port_listing_prints_the_plain_label(self):
        self.make_web()
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:3000 -> 5173", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_port_listing_hyperlinks_on_a_terminal(self):
        self.make_web()
        with mock.patch.dict(os.environ, REAL_TERM):
            code, out, err = self.run_main("port", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn(OSC8, out)

    def test_port_listing_skips_the_link_on_a_dumb_terminal(self):
        self.make_web()
        with mock.patch.dict(os.environ, {"TERM": "dumb"}):
            code, out, err = self.run_main("port", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:3000 -> 5173", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_port_listing_skips_the_link_over_ssh(self):
        self.make_web()
        with mock.patch.dict(os.environ, {**REAL_TERM,
                                          "SSH_CONNECTION": "10.0.0.1 1 10.0.0.2 22"}):
            code, out, err = self.run_main("port", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:3000 -> 5173", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_udp_has_no_link(self):
        self.make_web('ports = ["8080:80/udp"]\n')
        code, out, err = self.run_main("port", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("localhost:8080 -> 80/udp", out)
        self.assertNotIn("http://", out)
        with mock.patch.dict(os.environ, REAL_TERM):
            code, out, err = self.run_main("port", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertNotIn("\x1b]8;;", out)

    # ------------------------------------------------------------------- show

    def test_show_prints_the_plain_label(self):
        self.make_web()
        code, out, err = self.run_main("show", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("port       localhost:3000 -> 5173", out)
        self.assertNotIn("\x1b]8;;", out)

    def test_show_hyperlinks_on_a_terminal(self):
        self.make_web()
        with mock.patch.dict(os.environ, REAL_TERM):
            code, out, err = self.run_main("show", "web", tty=True)
        self.assertEqual(code, 0, err)
        self.assertIn(OSC8, out)

    def test_show_json_keeps_ports_and_adds_port_urls(self):
        self.make_web('ports = ["3000:5173", "8080:80/udp"]\n')
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(doc["ports"], ["3000:5173", "8080:80/udp"])
        self.assertEqual(doc["port_urls"], {"3000:5173": "http://127.0.0.1:3000/"})



class PortApplyTest(MsbctlTest):
    """`msbctl port` changes an existing sandbox with `msb modify` (msb 0.7.9+),
    which keeps it: no rebuild. msb saves it for the next start; a restart,
    when asked for, is msbctl's own stop and start."""
    env_keys = ("NPM_TOKEN",)

    def setUp(self):
        super().setUp()
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n',
                                 entry_extra='ports = ["3000:5173"]\n')
        self.store_secret(self.secrets_file("web"), "NPM_TOKEN", "planted-port-test")

    def created(self, state="running"):
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.set_state(web=state)

    def port(self, *argv):
        code, out, err = self.run_main("port", "web", *argv)
        self.assertEqual(code, 0, err)
        return out + err

    def modifies(self):
        return [c["argv"][2:] for c in self.msb_calls("modify")]

    def ports_in_msb(self):
        return self.fake_state()["_ports"]["web"]

    def test_not_created_yet_only_records(self):
        out = self.port("8080")
        self.assertIn("published when the sandbox is created", out)
        self.assertEqual(self.modifies(), [])
        self.assertIn("8080:8080", self.m.read_toml(self.entry_path("web"))["ports"])

    def test_stopped_applies_without_a_restart(self):
        self.created("stopped")
        out = self.port("8080")
        self.assertEqual(self.modifies(), [["--port", "8080:8080"]])
        self.assertIn("published from the next start", out)
        self.assertEqual(self.msb_calls("rm"), [])
        self.assertEqual(self.msb_calls("modify")[0]["env"]["NPM_TOKEN"], "planted-port-test")

    def test_running_waits_for_the_next_start_unless_restart(self):
        self.created()
        self.port("8080")
        self.assertEqual(self.modifies(), [["--port", "8080:8080", "--next-start"]])
        self.assertEqual(self.msb_calls("stop"), [])
        starts = len(self.msb_calls("start"))
        self.port("9090", "--restart")
        self.assertEqual(self.modifies()[-1], ["--port", "9090:9090", "--next-start"])
        # Restarted by msbctl, which binds the secrets again: never modify --restart.
        self.assertEqual(len(self.msb_calls("stop")), 1)
        self.assertEqual(len(self.msb_calls("start")), starts + 1)
        self.assertEqual(self.msb_calls("start")[-1]["env"]["NPM_TOKEN"], "planted-port-test")
        self.assertFalse(any("--restart" in m for m in self.modifies()))

    def test_removal_names_the_host_endpoint(self):
        self.created("stopped")
        self.port("--rm", "3000:5173")
        self.assertEqual(self.modifies(), [["--port-rm", "127.0.0.1:3000/tcp"]])
        self.assertEqual(self.ports_in_msb(), [])

    def test_a_new_guest_port_replaces_the_mapping(self):
        self.created("stopped")
        out = self.port("3000:80")
        self.assertIn("replaces  3000:5173", out)
        self.assertEqual(self.m.read_toml(self.entry_path("web"))["ports"], ["3000:80"])
        self.assertEqual(self.modifies(), [["--port", "3000:80"]])

    def test_a_port_msbctl_did_not_publish_is_left_alone(self):
        self.created("stopped")
        state = self.fake_state()
        state["_ports"]["web"].append({"host_bind": "127.0.0.1", "host_port": 5432,
                                       "guest_port": 5432, "protocol": "tcp"})
        with open(os.environ["FAKE_MSB_STATE"], "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        self.port("8080")
        self.assertEqual(self.modifies(), [["--port", "8080:8080"]])

    def test_rebuild_still_rebuilds(self):
        self.created()
        with mock.patch.object(self.m, "cmd_rebuild") as rebuild:
            self.port("8080", "--rebuild")
        rebuild.assert_called_once()
        self.assertEqual(self.modifies(), [])

    def test_nothing_to_send_when_msb_already_has_them(self):
        self.created("stopped")
        self.m.apply_ports(self.m.Sandbox("web", self.m.load_config()), self.m.load_config())
        self.assertEqual(self.modifies(), [])


if __name__ == "__main__":
    main()
