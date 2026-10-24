"""Secret values in the OS keyring ([secrets] store), against the fake
secret-tool and busctl in tests/fake: where a value goes, that it never reaches
an argv or the output, that a locked keyring is asked to unlock (and a dismissed
prompt counts as no value), that nothing is called with no Secret Service, and
that autostart alongside the keyring is said, asked about on a terminal, and
skips at boot what a locked keyring would hold up."""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

from tests.harness import MsbctlTest

SECRET = "planted-keyring-value"


class KeyringTest(MsbctlTest):
    env_keys = ("NPM_TOKEN", "GH_TOKEN")
    follows_store_env = False

    def set_store(self, store):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(f'[secrets]\nstore = "{store}"\n')

    def env_text(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def assert_never_prompted(self):
        self.assertEqual([c for c in self.keyring_calls() if "PROMPTED" in c], [])
        self.assert_no_call_without_service()

    def assert_prompted(self):
        self.assertTrue(any("PROMPTED" in c for c in self.keyring_calls()))

    def assert_no_call_without_service(self):
        self.assertEqual([c for c in self.keyring_calls() if "NO_SERVICE" in c], [])

    def npm_sandbox(self, entry_extra=""):
        self.make_folder_sandbox("web", sandbox_toml='secret_binds = ["NPM_TOKEN@registry.npmjs.org"]\n',
                                 entry_extra=entry_extra)
        return self.secrets_file("web")

    # ------------------------------------------------------------- where it goes

    def test_keyring_store_keeps_only_a_marker_in_the_file(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=SECRET)
        self.assertEqual(code, 0, err)
        self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))
        self.assertNotIn(SECRET, self.env_text(path))
        self.assertEqual([i["secret"] for i in self.keyring_items()], [SECRET])
        self.assertIn("stored in the keyring", out)
        self.assert_not_in_output(SECRET, out, err)
        self.assert_not_in_argv(SECRET)
        self.assert_never_prompted()

    def test_a_start_reads_it_back_into_msbs_environment_only(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        code, out, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.msb_calls("create")[0]["env"].get("NPM_TOKEN"), SECRET)
        self.assert_not_in_argv(SECRET)
        self.assert_not_in_output(SECRET, out, err)

    def test_auto_uses_the_keyring_whenever_there_is_one(self):
        for mode, where in (("unlocked", "keyring"), ("locked", "keyring"), (None, "file")):
            with self.subTest(keyring=mode):
                self.fresh()
                path = self.npm_sandbox()
                self.set_store("auto")
                self.use_keyring(mode)
                self.store_secret(path, "NPM_TOKEN", SECRET)
                self.assertEqual("NPM_TOKEN=@keyring" in self.env_text(path), where == "keyring")
                self.assertEqual(f"NPM_TOKEN={SECRET}" in self.env_text(path), where == "file")
                self.assertEqual(any("PROMPTED" in c for c in self.keyring_calls()), mode == "locked")
                self.assert_no_call_without_service()

    def test_keyring_and_autostart_mix(self):
        for store in ("auto", "keyring"):
            with self.subTest(store=store):
                self.fresh()
                path = self.npm_sandbox(entry_extra="autostart = true")
                self.set_store(store)
                self.use_keyring("unlocked")
                self.store_secret(path, "NPM_TOKEN", SECRET)
                self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))

    def test_file_is_the_default_and_never_asks_the_keyring(self):
        path = self.npm_sandbox()
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.assertIn(f"NPM_TOKEN={SECRET}", self.env_text(path))
        self.assertEqual(self.keyring_calls(), [])

    # ----------------------------------------------------------------- refusals

    def test_explicit_keyring_refuses_when_there_is_none(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring(None)
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=SECRET)
        self.assertNotEqual(code, 0)
        self.assertIn("nothing was written", err)
        self.assertFalse(os.path.exists(path) and SECRET in self.env_text(path))
        self.assertEqual(self.keyring_calls(), [])
        self.assert_not_in_output(SECRET, out, err)

    def test_a_locked_keyring_asks_to_unlock_when_storing(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("locked")
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=SECRET)
        self.assertEqual(code, 0, err)
        self.assert_prompted()
        self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))
        self.assertEqual([i["secret"] for i in self.keyring_items()], [SECRET])

    def test_a_dismissed_prompt_writes_nothing(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("locked")
        os.environ["FAKE_KEYRING_PROMPT"] = "dismiss"
        code, out, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=SECRET)
        self.assertNotEqual(code, 0)
        self.assertIn("nothing was written", err)
        self.assertFalse(os.path.exists(path) and "NPM_TOKEN" in self.env_text(path))
        self.assert_not_in_output(SECRET, out, err)

    def test_a_failed_store_writes_nothing(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        os.environ["FAKE_KEYRING_FAIL"] = "store"
        code, _, err = self.run_main("secret", "set", "web", "NPM_TOKEN", "--stdin", stdin=SECRET)
        self.assertNotEqual(code, 0)
        self.assertIn("did not take", err)
        self.assertFalse(os.path.exists(path) and "NPM_TOKEN" in self.env_text(path))

    # ------------------------------------------------------------- autostart

    def test_installing_the_boot_unit_asks_on_a_terminal(self):
        self.set_store("keyring")
        code, _, err = self.run_main("host", "autostart", "install", stdin="n\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("SKIPS", err)
        self.assertFalse(os.path.exists(os.path.join(self.m.SYSTEMD_USER_DIR, self.m.AUTOSTART_UNIT)))

    def test_turning_autostart_on_off_a_terminal_only_says_so(self):
        path = self.npm_sandbox()
        self.set_store("auto")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.assertTrue(self.m.keyring_in_use())
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch("builtins.input") as asked:
            self.assertTrue(self.m.autostart_keyring_ok(False))
        asked.assert_not_called()
        self.assertIn("SKIPS", err.getvalue())

    def test_nothing_is_said_without_the_keyring(self):
        self.npm_sandbox()
        self.use_keyring("unlocked")
        self.assertFalse(self.m.keyring_in_use())     # store = "file", nothing in it

    def test_a_boot_skips_what_a_locked_keyring_holds(self):
        path = self.npm_sandbox(entry_extra="autostart = true")
        self.make_folder_sandbox("plain", entry_extra="autostart = true")
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        for mode, started in (("locked", ["plain"]), (None, ["plain"]), ("unlocked", ["plain", "web"])):
            with self.subTest(keyring=mode):
                self.use_keyring(mode)
                os.environ["FAKE_MSB_STATE"] = os.path.join(self.tmp, f"msb-{mode}.json")
                os.environ["FAKE_MSB_LOG"] = os.path.join(self.tmp, f"msb-{mode}.log")
                code, _, err = self.run_main("start", "--autostart")
                self.assertEqual(code, 0, err)
                self.assertEqual(sorted(c["argv"][2] for c in self.msb_calls("create")), started)
                self.assertEqual("skipped" in err, mode != "unlocked")
        self.assertEqual([c for c in self.keyring_calls() if "PROMPTED" in c], [])
        self.assert_no_call_without_service()

    def test_a_boot_skips_everything_when_global_values_are_in_it(self):
        self.make_folder_sandbox("plain", entry_extra="autostart = true")
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_LAN", SECRET)
        self.use_keyring("locked")
        code, _, err = self.run_main("start", "--autostart")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.msb_calls("create"), [])
        self.assertIn("plain", err)

    def test_the_picker_on_a_terminal_starts_them_and_asks(self):
        path = self.npm_sandbox(entry_extra="autostart = true")
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.use_keyring("locked")
        code, _, err = self.run_main("start", "--autostart", tty=True)
        self.assertEqual(code, 0, err)
        self.assertEqual([c["argv"][2] for c in self.msb_calls("create")], ["web"])
        self.assert_prompted()

    # --------------------------------------------------------- locked at start

    def stored_then(self, mode, prompt=None):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.use_keyring(mode)
        if prompt:
            os.environ["FAKE_KEYRING_PROMPT"] = prompt
        return path

    def test_a_locked_keyring_at_start_asks_and_uses_the_value(self):
        self.stored_then("locked")
        code, out, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assert_prompted()
        self.assertEqual(self.msb_calls("create")[0]["env"].get("NPM_TOKEN"), SECRET)
        self.assert_not_in_argv(SECRET)

    def test_a_dismissed_prompt_or_no_keyring_at_start_skips_the_secret(self):
        for mode, prompt in (("locked", "dismiss"), (None, None)):
            with self.subTest(keyring=mode):
                self.fresh()
                path = self.stored_then(mode, prompt)
                code, out, err = self.run_main("start", "web")
                self.assertEqual(code, 0, err)
                self.assertIn("cannot be read", err)
                self.assertNotIn("NPM_TOKEN", self.msb_calls("create")[0]["env"])
                self.assert_no_call_without_service()
                # Still counted as stored, so `secret ls` does not claim it is missing.
                self.assertIn("NPM_TOKEN", self.m.read_env_file(path))

    # ------------------------------------------------------------------ migrate

    def test_migrate_there_and_back_is_idempotent(self):
        path = self.npm_sandbox()
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_LAN", "planted-global-key")

        code, out, err = self.run_main("secret", "migrate", "--to", "keyring", "--json")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(sorted(m["var"] for m in doc["moved"]), ["LLM_KEY_LAN", "NPM_TOKEN"])
        self.assertEqual(doc["store"], "keyring")
        self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))
        self.assertIn("LLM_KEY_LAN=@keyring", self.env_text(self.m.GLOBAL_ENV))
        self.assertEqual(self.m.secret_store_setting(self.m.load_config()), "keyring")
        for value in (SECRET, "planted-global-key"):
            self.assert_not_in_output(value, out, err)
            self.assert_not_in_argv(value)

        code, out, err = self.run_main("secret", "migrate", "--to", "keyring", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["moved"], [])
        self.assertEqual(json.loads(out)["already"], 2)

        code, out, err = self.run_main("secret", "migrate", "--to", "file")
        self.assertEqual(code, 0, err)
        self.assertIn(f"NPM_TOKEN={SECRET}", self.env_text(path))
        self.assertEqual(self.keyring_items(), [])
        self.assertEqual(self.m.secret_store_setting(self.m.load_config()), "file")
        self.assert_never_prompted()

    def test_migrate_to_keyring_leaves_auto_alone(self):
        self.npm_sandbox()
        self.set_store("auto")
        self.use_keyring("unlocked")
        code, out, err = self.run_main("secret", "migrate", "--to", "keyring", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["store"], "auto")

    def test_migrate_refuses_without_a_keyring(self):
        path = self.npm_sandbox()
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.use_keyring(None)
        code, _, err = self.run_main("secret", "migrate", "--to", "keyring")
        self.assertNotEqual(code, 0)
        self.assertIn(f"NPM_TOKEN={SECRET}", self.env_text(path))
        self.assertEqual(self.keyring_calls(), [])

    def test_migrate_back_stops_at_a_dismissed_prompt(self):
        path = self.stored_then("locked", "dismiss")
        code, _, err = self.run_main("secret", "migrate", "--to", "file")
        self.assertNotEqual(code, 0)
        self.assertIn("give back", err)
        self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))
        self.assertEqual(len(self.keyring_items()), 1)
        self.assertEqual(self.m.secret_store_setting(self.m.load_config()), "keyring")

    def test_migrate_with_autostart_says_so_and_asks_on_a_terminal(self):
        path = self.npm_sandbox(entry_extra="autostart = true")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        code, _, err = self.run_main("secret", "migrate", "--to", "keyring", stdin="n\n", tty=True)
        self.assertNotEqual(code, 0)
        self.assertIn("SKIPS", err)
        self.assertIn(f"NPM_TOKEN={SECRET}", self.env_text(path))
        code, _, err = self.run_main("secret", "migrate", "--to", "keyring")
        self.assertEqual(code, 0, err)
        self.assertIn("SKIPS", err)
        self.assertIn("NPM_TOKEN=@keyring", self.env_text(path))

    def test_migrate_takes_no_sandbox_and_others_still_need_one(self):
        code, _, err = self.run_main("secret", "migrate", "web", "--to", "file")
        self.assertNotEqual(code, 0)
        self.assertIn("takes no sandbox", err)
        code, _, err = self.run_main("secret", "ls")
        self.assertNotEqual(code, 0)
        self.assertIn("name the sandbox", err)

    def test_host_serve_refuses_migrate(self):
        self.assertIn("for the host itself",
                      self.m.restricted_problem(["secret", "migrate", "--to", "file"]))

    # -------------------------------------------------------- rename and purge

    def test_rename_moves_the_keyring_items(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        code, _, err = self.run_main("rename", "web", "shop")
        self.assertEqual(code, 0, err)
        new = self.secrets_file("shop")
        self.assertEqual(self.m.read_env_file(new).get("NPM_TOKEN"), SECRET)
        self.assertEqual([i["attrs"]["file"] for i in self.keyring_items()], ["shop"])

    def test_rename_refuses_when_the_values_cannot_be_read(self):
        path = self.stored_then("locked", "dismiss")
        code, _, err = self.run_main("rename", "web", "shop")
        self.assertNotEqual(code, 0)
        self.assertIn("nothing has been renamed", err)
        self.assertTrue(os.path.exists(path))
        self.assertEqual([i["attrs"]["file"] for i in self.keyring_items()], ["web"])

    def test_purge_clears_the_keyring_items(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        code, _, err = self.run_main("purge", "web", "-y")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.keyring_items(), [])
        self.assertFalse(os.path.exists(path))

    def test_removing_a_value_clears_its_item(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        self.store_secret(path, "NPM_TOKEN", None)
        self.assertEqual(self.keyring_items(), [])
        self.assertNotIn("NPM_TOKEN", self.env_text(path))

    def test_a_second_install_does_not_see_this_ones_items(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        dirs = {i["attrs"]["dir"] for i in self.keyring_items()}
        self.assertEqual(dirs, {os.path.realpath(self.m.SECRETS_DIR)})

    # --------------------------------------------------------------- host check

    def test_host_check_reports_the_store(self):
        path = self.npm_sandbox()
        self.set_store("keyring")
        self.use_keyring("unlocked")
        self.store_secret(path, "NPM_TOKEN", SECRET)
        check = self.m.secret_store_check()
        self.assertIsNone(check["ok"])
        self.assertIn('store = "keyring"', check["detail"])
        self.assertIn("unlocked", check["detail"])
        self.assertIn("1 value(s) in the keyring", check["detail"])
        self.use_keyring("locked")      # asks on first use: fine
        self.assertIsNone(self.m.secret_store_check()["ok"])
        self.use_keyring(None)          # nothing here to read them from
        self.assertFalse(self.m.secret_store_check()["ok"])
        self.assert_no_call_without_service()


if __name__ == "__main__":
    unittest.main()
