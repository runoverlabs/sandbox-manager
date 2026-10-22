"""The host itself, for the Kandev plugin: health.host (F22), `host kandev
configure` (F23) and `self-update --json` under the plugin's key (F24)."""

import os
import subprocess
from unittest import main, mock

from tests.harness import MsbctlTest
from tests.test_kandev import KandevTest

MEMINFO = "MemTotal:       65536000 kB\nMemFree:  1000 kB\nMemAvailable:   52224000 kB\n"


class HostFacts(KandevTest):

    def facts(self, os_release='PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n'):
        files = {"os-release": os_release, "meminfo": MEMINFO, "uptime": "86400.73 1234.5\n"}
        for name, body in files.items():
            if body is not None:
                with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as fh:
                    fh.write(body)
        with mock.patch.object(self.m, "OS_RELEASE", os.path.join(self.tmp, "os-release")), \
                mock.patch.object(self.m, "PROC_MEMINFO", os.path.join(self.tmp, "meminfo")), \
                mock.patch.object(self.m, "PROC_UPTIME", os.path.join(self.tmp, "uptime")), \
                mock.patch.object(self.m.os, "getloadavg", lambda: (0.4217, 0.3, 0.2)):
            return self.ok("health")["host"]

    def test_health_reports_the_machine(self):
        host = self.facts()
        self.assertEqual(host["os"], "Debian GNU/Linux 13 (trixie)")
        self.assertEqual(host["kernel"], os.uname().release)
        self.assertEqual(host["cpus"], os.cpu_count())
        self.assertEqual((host["memory_total_mib"], host["memory_available_mib"]), (64000, 51000))
        self.assertEqual(host["load_1m"], 0.42)
        self.assertEqual(host["uptime_seconds"], 86400)
        self.assertGreater(host["disk_total_gib"], 0)
        self.assertLessEqual(host["disk_free_gib"], host["disk_total_gib"])

    def test_what_cannot_be_read_is_left_out(self):
        host = self.facts(os_release=None)
        self.assertNotIn("os", host)
        for key in ("kernel", "cpus", "memory_total_mib", "load_1m", "disk_free_gib", "uptime_seconds"):
            self.assertIn(key, host)

    def test_strings_are_printable_and_short(self):
        host = self.facts(os_release="PRETTY_NAME='Odd\x1b[31m " + "x" * 300 + "'\n")
        self.assertTrue(host["os"].isprintable())
        self.assertEqual(len(host["os"]), 120)


COMMENTED = """\
# my own notes, kept
[defaults]
cpus = 4

[kandev]
# the operator's comment about this host
enabled = false
serve = "none"
max_sandboxes = 3
"""


class Configure(KandevTest):

    def configure_json(self, *flags):
        return self.msbctl_json("host", "kandev", "configure", *flags, "--json", plugin=False)

    def config_text(self):
        with open(self.m.CONFIG_FILE, encoding="utf-8") as fh:
            return fh.read()

    def write_config(self, text):
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_adds_the_section(self):
        self.write_config("[defaults]\ncpus = 4\n")
        code, doc = self.configure_json("--enabled", "--serve", "proxy", "--proxy-listen", "10.0.1.23",
                                        "--base-url", "https://sbx-01.example.com", "--allow-extra", "*",
                                        "--allow-extra", "192.168.2.6:8788")
        self.assertEqual(code, 0, doc)
        self.assertEqual(doc["changed"], ["enabled", "serve", "proxy_listen", "base_url", "allow_extra"])
        self.assertEqual(doc["kandev"]["proxy_listen"], "10.0.1.23")
        self.assertEqual(doc["kandev"]["allow_extra"], ["*", "192.168.2.6:8788"])
        self.assertEqual(doc["kandev"]["proxy_port_pool"], "30000-39999")
        self.assertTrue(self.config_text().startswith("[defaults]\ncpus = 4\n"))
        # What a verb loads afterwards is what configure reported.
        self.assertEqual(self.ok("health")["base_url"], "https://sbx-01.example.com")

    def test_changes_only_the_named_keys(self):
        self.write_config(COMMENTED)
        code, doc = self.configure_json("--enabled", "--serve", "proxy")
        self.assertEqual((code, doc["changed"]), (0, ["enabled", "serve"]))
        self.assertEqual(self.config_text(), COMMENTED.replace("enabled = false", "enabled = true")
                         .replace('serve = "none"', 'serve = "proxy"'))
        self.assertEqual(doc["kandev"]["max_sandboxes"], 3)

    def test_is_idempotent(self):
        self.write_config(COMMENTED)
        self.configure_json("--serve", "proxy")
        before = self.config_text()
        code, doc = self.configure_json("--serve", "proxy")
        self.assertEqual((code, doc["changed"]), (0, []))
        self.assertEqual(self.config_text(), before)

    def test_a_bad_value_leaves_the_file(self):
        self.write_config(COMMENTED)
        for flags in (["--proxy-listen", "sbx-01"], ["--serve", "carrier-pigeon"],
                      ["--base-url", "http://sbx-01"], ["--allow-extra", "10.0.0.0/4"],
                      ["--enabled", "--proxy-listen", "sbx-01"]):
            with self.subTest(flags=flags):
                code, doc = self.configure_json(*flags)
                self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"))
                self.assertEqual(self.config_text(), COMMENTED)
        self.assertEqual(os.listdir(self.m.CONFIG_DIR).count("config.toml"), 1)
        self.assertFalse([f for f in os.listdir(self.m.CONFIG_DIR) if f.startswith(".config-")])

    def test_an_empty_allow_extra_allows_nothing(self):
        self.configure_json("--allow-extra", "*")
        code, doc = self.configure_json("--allow-extra", "")
        self.assertEqual((code, doc["kandev"]["allow_extra"]), (0, []))
        self.assertIn("allow_extra = []", self.config_text())

    def test_private_names(self):
        code, doc = self.configure_json("--private-name", "git.example.com")
        self.assertEqual((code, doc["changed"]), (0, ["private_names"]))
        self.assertEqual(doc["kandev"]["private_names"], ["git.example.com"])
        code, doc = self.configure_json("--private-name", "*.example.com")
        self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"))
        code, doc = self.configure_json("--private-name", "")
        self.assertEqual((code, doc["kandev"]["private_names"]), (0, []))

    def test_without_json(self):
        code, out, err = self.run_main("host", "kandev", "configure", "--proxy-listen", "sbx-01")
        self.assertNotEqual(code, 0)
        self.assertIn("is unchanged", err)
        code, out, err = self.run_main("host", "kandev", "configure", "--serve", "proxy")
        self.assertEqual(code, 0, err)
        self.assertIn("set serve", out)

    def test_the_flags_go_with_configure_only(self):
        code, out, err = self.run_main("host", "check", "--serve", "proxy")
        self.assertNotEqual(code, 0)
        self.assertIn("go with host kandev configure", err)

    def test_neither_key_may_configure(self):
        for key in ("1", "kandev"):
            with self.subTest(key=key):
                os.environ["MSB_RESTRICTED"] = key
                try:
                    code, out, err = self.run_main("host", "kandev", "configure", "--allow-extra", "*")
                finally:
                    os.environ.pop("MSB_RESTRICTED")
                self.assertNotEqual(code, 0)
                self.assertNotIn("*", self.config_text())


FAKE_GET = """\
#!/bin/sh
# A stand-in for the packaged get.sh: switches `current` to the release asked
# for (default 0.5.2), as the real one does through install.sh.
echo "$@" > "$(dirname "$0")/get.args"
version=0.5.2
[ "$1" = --version ] && version="${2#v}"
[ -n "$FAKE_GET_FAIL" ] && exit 1
prefix="$(dirname "$(dirname "$(dirname "$0")")")"
mkdir -p "$prefix/versions/$version"
echo "$version" > "$prefix/versions/$version/VERSION"
ln -sfn "versions/$version" "$prefix/current"
"""


class SelfUpdate(KandevTest):

    def setUp(self):
        super().setUp()
        prefix = os.path.join(self.tmp, "share", "msb-manager")
        self.here = os.path.join(prefix, "versions", "0.5.1")
        os.makedirs(self.here)
        with open(os.path.join(self.here, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("0.5.1\n")
        with open(os.path.join(self.here, "get.sh"), "w", encoding="utf-8") as fh:
            fh.write(FAKE_GET)
        os.symlink("versions/0.5.1", os.path.join(prefix, "current"))
        for name, value in (("HERE", self.here), ("IS_CHECKOUT", False),
                            ("VERSION_FILE", os.path.join(self.here, "VERSION"))):
            patch = mock.patch.object(self.m, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def get_args(self):
        with open(os.path.join(self.here, "get.args"), encoding="utf-8") as fh:
            return fh.read().split()

    def test_the_plugin_key_updates(self):
        self.assertEqual(self.jok("self-update", "--json"),
                         {"msbctl_version": "0.5.2", "updated": True, "proxy": {"state": "not_running"}})

    def test_forward_only(self):
        self.assertEqual(self.jok("self-update", "--version", "v0.6.0", "--json")["msbctl_version"], "0.6.0")
        self.assertEqual(self.jok("self-update", "--version", "0.5.1", "--json")["updated"], False)

    def test_a_bare_version_is_its_tag(self):
        self.jok("self-update", "--version", "0.6.0", "--json")
        self.assertEqual(self.get_args(), ["--version", "v0.6.0"])

    def test_the_proxy_is_restarted_onto_the_new_release(self):
        with mock.patch.object(self.m, "kandev_restart_proxy",
                               lambda v: {"state": "restarted", "version": v}):
            doc = self.jok("self-update", "--json")
        self.assertEqual(doc["proxy"], {"state": "restarted", "version": "0.5.2"})

    def test_without_json_it_installs_and_restarts(self):
        seen = []
        with mock.patch.object(self.m, "kandev_restart_proxy",
                               lambda v: seen.append(v) or {"state": "restarted", "version": v}):
            code, out, err = self.run_main("self-update")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, ["0.5.2"])
        self.assertIn("restarted the Kandev proxy", out)

    def test_never_down(self):
        self.jerror("denied", "self-update", "--version", "0.4.0", "--json")
        self.assertEqual(os.readlink(os.path.join(os.path.dirname(os.path.dirname(self.here)), "current")),
                         "versions/0.5.1")

    def test_a_failed_install(self):
        os.environ["FAKE_GET_FAIL"] = "1"
        self.assertIn("get.sh", self.jerror("unavailable", "self-update", "--json")["message"])

    def test_a_checkout_cannot(self):
        with mock.patch.object(self.m, "IS_CHECKOUT", True):
            self.assertIn("git pull", self.jerror("unsupported", "self-update", "--json")["message"])

    def test_disabled(self):
        self.configure(enabled=False)
        self.jerror("denied", "self-update", "--json")


class RestartProxy(KandevTest):

    def restart(self, versions, installed="0.6.1", code=0):
        """kandev_restart_proxy() with the proxy reporting `versions` in turn
        (None: not running) and systemctl answering `code`."""
        calls, seen = [], iter(versions)
        last = [None]

        def version():
            last[0] = next(seen, last[0])
            return last[0]

        proc = mock.Mock(returncode=code, stderr="Unit not found.")
        with mock.patch.object(self.m, "kandev_proxy_version", version), \
                mock.patch.object(self.m, "run", lambda argv, **kw: calls.append(argv) or proc), \
                mock.patch.object(self.m.shutil, "which", lambda name: f"/usr/bin/{name}"), \
                mock.patch.object(self.m.time, "sleep", lambda s: None):
            return self.m.kandev_restart_proxy(installed, wait=0.5), calls

    def test_an_old_proxy_is_restarted(self):
        result, calls = self.restart(["0.6.0", "0.6.0", "0.6.1"])
        self.assertEqual(result, {"state": "restarted", "version": "0.6.1"})
        self.assertEqual(calls, [["systemctl", "--user", "try-restart", "msb-kandev-proxy.service"]])

    def test_one_from_before_0_6_1_says_nothing_and_is_restarted(self):
        self.assertEqual(self.restart(["", "0.6.1"])[0]["state"], "restarted")

    def test_a_current_or_stopped_proxy_is_left_alone(self):
        for versions, state in ((["0.6.1"], "current"), ([None], "not_running")):
            with self.subTest(state=state):
                result, calls = self.restart(versions)
                self.assertEqual((result["state"], calls), (state, []))

    def test_failures_say_why(self):
        result, _ = self.restart(["0.6.0"], code=5)
        self.assertEqual(result["state"], "failed")
        self.assertIn("Unit not found", result["reason"])
        # A unit that runs a pinned old path comes back as the old release.
        result, _ = self.restart(["0.6.0", "0.6.0"])
        self.assertIn("host kandev install", result["reason"])

    def test_the_verb(self):
        with mock.patch.object(self.m, "kandev_restart_proxy",
                               lambda v: {"state": "restarted", "version": v}):
            self.assertEqual(self.ok("restart-proxy")["proxy"]["state"], "restarted")
        with mock.patch.object(self.m, "kandev_restart_proxy",
                               lambda v: {"state": "failed", "version": "0.6.0", "reason": "why"}):
            self.assertEqual(self.error("unavailable", "restart-proxy")["message"], "why")


class GetSh(MsbctlTest):

    def test_a_bare_version_is_its_tag(self):
        get = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "get.sh")
        for given in ("0.6.0", "v0.6.0"):
            with self.subTest(given=given):
                out = subprocess.run(["sh", get, "--version", given, "--print-version"],
                                     env={**os.environ, "MSB_MANAGER_BASE_URL": "file:///nowhere"},
                                     capture_output=True, text=True, check=True).stdout
                self.assertEqual(out.strip(), "v0.6.0")


if __name__ == "__main__":
    main()
