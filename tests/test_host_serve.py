"""host serve, the forced command: which commands a laptop's key may run."""

import os
from unittest import main, mock

from tests.harness import MsbctlTest

ALLOWED = [
    "msbctl ls",
    # A laptop that recorded msbctl's path before the key was restricted.
    "/home/msb/.local/bin/msbctl ls",
    "msbctl ls --json",
    "msbctl --version",
    "msbctl status",
    "msbctl show web",
    "msbctl show web --json",
    "msbctl config",
    "msbctl start web api",
    "msbctl start --autostart",
    "msbctl stop web",
    "msbctl reclaim web",
    "msbctl shell web",
    "msbctl shell web -u root",
    "msbctl exec web -- cat",
    """msbctl exec web -- sh -c 'echo "a b"'""",
    "msbctl exec web -e A=b --timeout 5m -- true",
    "msbctl exec web --no-tty -- true",
    "msbctl update web -c claude gh",
    "msbctl resize web --memory 4G",
    "msbctl rebuild web",
    "msbctl purge web -y",
    "msbctl rename web shop -y",
    "msbctl self-update",
    "msbctl self-update --version v99.0.0",
    "msbctl cache web",
    "msbctl cache web clear npm",
    "msbctl observe web",
    "msbctl observe web report",
    "msbctl observe web off",
    "msbctl secret ls web",
    "msbctl secret set web GH_TOKEN --stdin",
    "msbctl secret rm web NPM_TOKEN",
    "msbctl setup --claude-token work --stdin",
    "msbctl add --repo acme/webshop -y",
    "msbctl policy web",
    "msbctl policy web show",
    "msbctl host check",
    "msbctl host check --json",
]

REFUSED = [
    "msbctl;rm -rf ~",
    # The host's own settings, not a credential: remote setup copies these
    # before the key is restricted.
    "msbctl setup --identity work --git-name A --git-email a@example.com",
    "msbctl setup --claude-token main --stdin --default",
    "/bin/sh -c ls",
    "/home/msb/.local/bin/msbctl-evil ls",
    "./msbctl ls",
    "rm -rf ~",
    "cat ~/.config/msb/secrets/global.env",
    "bash",
    "",
    "msbctl",
    "msbctl 'unterminated",
    "msbctl show .",
    "msbctl show",
    "msbctl show ../x",
    "msbctl start",
    "msbctl exec . -- true",
    "msbctl exec -- true",
    "msbctl exec web --unknown-flag -- true",
    "msbctl exec web -e",
    "msbctl rename web ../x",
    "msbctl self-update --version v0.1.0",
    "msbctl self-update --version latest",
    "msbctl host kandev configure --allow-extra '*'",
    "msbctl observe web on",
    "msbctl secret add web",
    "msbctl setup",
    "msbctl setup --welcome",
    "msbctl setup --claude-token work",
    "msbctl add ~/x",
    "msbctl add",
    "msbctl policy web approve",
    "msbctl policy web update",
    "msbctl host authorize 'ssh-ed25519 AAAA'",
    "msbctl host autostart install",
    "msbctl host kandev install",
    "msbctl host serve",
    "msbctl host serve --kandev",
    "msbctl host authorize 'ssh-ed25519 AAAA' --kandev",
    "msbctl allow web evil.example",
    "msbctl mount web /etc",
    "msbctl port web 8080",
    "msbctl keys web",
    "msbctl code web",
    "msbctl move web /tmp",
    "msbctl entry web",
    "msbctl edit web",
    "msbctl _agent-filter web",
    "msbctl ls --bogus",
]


# The Kandev plugin's key: `host serve --kandev`. Each kandev verb is allowed
# there and refused under the everyday key; the generic verbs only in the one
# JSON shape the plugin uses; every operator verb is refused there.
KANDEV_VERBS = [
    "msbctl kandev health",
    "msbctl kandev provision 6f1c2b9e-aaaa",
    "msbctl kandev agentctl 6f1c2b9e-aaaa",
    "msbctl kandev start 6f1c2b9e-aaaa",
    "msbctl kandev expiry 6f1c2b9e-aaaa --at 2026-10-17T15:00:00Z",
    "msbctl kandev lease 6f1c2b9e-aaaa 8765",
    "msbctl kandev tls install",
    "msbctl kandev restart-proxy",
]

KANDEV_ALLOWED = ["msbctl --version", *KANDEV_VERBS,
                  "msbctl ls --json",
                  "msbctl show k-6f1c2b9e-aaaa --json",
                  "msbctl stop k-6f1c2b9e-aaaa --json",
                  "msbctl purge k-6f1c2b9e-aaaa -y --json",
                  "msbctl self-update --json",
                  "msbctl self-update --version 99.0.0 --json"]

KANDEV_REFUSED = [
    "msbctl ls", "msbctl status", "msbctl show web", "msbctl shell web",
    "msbctl exec web -- true", "msbctl secret set web GH_TOKEN --stdin", "msbctl setup",
    "msbctl allow web x.example", "msbctl add --repo acme/web -y", "msbctl edit web",
    "msbctl rm web", "msbctl purge web -y", "msbctl start web", "msbctl host check",
    "msbctl kandev bogus", "msbctl kandev", "/bin/sh -c ls", "",
    # The generic verbs in any other shape: text output, a prompt, a re-probe,
    # several names, or the host's own folder.
    "msbctl stop web", "msbctl purge web --json", "msbctl stop a b --json",
    "msbctl show . --json", "msbctl show --json", "msbctl ls --json --refresh",
    "msbctl ls --json --porcelain",
    # Folded into the generic verbs, or the host's own.
    "msbctl kandev list", "msbctl kandev inspect x", "msbctl kandev destroy x",
    "msbctl kandev stop x", "msbctl kandev find --operation op", "msbctl kandev reap",
    "msbctl host kandev reap", "msbctl host kandev proxy", "msbctl host kandev install",
    # Its own egress is the operator's to decide; an update only forward.
    "msbctl host kandev configure --allow-extra '*' --json",
    "msbctl host kandev configure --private-name git.example.com --json",
    "msbctl self-update", "msbctl self-update --version 0.4.0 --json",
]


class Exec(Exception):
    pass


class HostServeTest(MsbctlTest):

    def serve(self, command, kandev=False):
        os.environ["SSH_ORIGINAL_COMMAND"] = command
        seen = {}

        def fake_execv(path, argv):
            seen["argv"] = argv
            seen["restricted"] = os.environ.get("MSB_RESTRICTED")
            seen["path"] = os.environ["PATH"]
            raise Exec

        with mock.patch.object(self.m.os, "execv", fake_execv):
            try:
                code, out, err = self.run_main("host", "serve", *(["--kandev"] if kandev else []))
            except Exec:
                return 0, seen, ""
        return code, seen, err

    def test_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                code, seen, err = self.serve(command)
                self.assertEqual(code, 0, err)
                self.assertIn("argv", seen, err)
                self.assertEqual(seen["restricted"], "1")
                self.assertTrue(seen["path"].startswith(os.path.join(self.home, ".local", "bin")))
                import shlex
                self.assertEqual(seen["argv"][2:], shlex.split(command)[1:])
                self.assertEqual(seen["argv"][1], os.path.realpath(self.m.__file__))

    def test_refused(self):
        for command in REFUSED:
            with self.subTest(command=command):
                code, seen, err = self.serve(command)
                self.assertEqual(code, 126, err)
                self.assertNotIn("argv", seen)
                self.assertIn("msbctl host serve: refused:", err)

    def test_kandev_key_runs_kandev_verbs_only(self):
        for command in KANDEV_ALLOWED:
            with self.subTest(command=command):
                code, seen, err = self.serve(command, kandev=True)
                self.assertEqual(code, 0, err)
                self.assertEqual(seen["restricted"], "kandev")
        for command in KANDEV_REFUSED:
            with self.subTest(command=command):
                code, seen, err = self.serve(command, kandev=True)
                self.assertEqual(code, 126, err)
                self.assertNotIn("argv", seen)

    def test_everyday_key_runs_no_kandev_verb(self):
        for command in KANDEV_VERBS:
            with self.subTest(command=command):
                code, seen, err = self.serve(command)
                self.assertEqual(code, 126, err)
                self.assertIn("Kandev plugin's key", err)

    def test_no_forced_command(self):
        os.environ.pop("SSH_ORIGINAL_COMMAND", None)
        code, _, err = self.run_main("host", "serve")
        self.assertEqual(code, 126)
        self.assertIn("gets no shell", err)

    def test_restricted_policy_and_host_verbs_refuse_themselves(self):
        os.environ["MSB_RESTRICTED"] = "1"
        code, _, err = self.run_main("host", "authorize", "ssh-ed25519 AAAA")
        self.assertNotEqual(code, 0)
        code, _, err = self.run_main("host", "autostart", "install")
        self.assertNotEqual(code, 0)
        code, _, err = self.run_main("host", "kandev", "install")
        self.assertNotEqual(code, 0)


KEY = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
       " laptop@example")


class AuthorizeTest(MsbctlTest):

    def authorized(self):
        with open(os.path.join(self.home, ".ssh", "authorized_keys"), encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_writes_the_forced_command(self):
        with mock.patch.object(self.m.shutil, "which", lambda name: "/home/x/.local/bin/msbctl"):
            code, out, err = self.run_main("host", "authorize", KEY)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.authorized(), [
            'restrict,pty,command="/home/x/.local/bin/msbctl host serve" ' + KEY])
        mode = os.stat(os.path.join(self.home, ".ssh", "authorized_keys")).st_mode & 0o777
        self.assertEqual(mode, 0o600)

        code, out, err = self.run_main("host", "authorize", KEY)
        self.assertNotEqual(code, 0)
        self.assertIn("already", err)
        self.assertEqual(len(self.authorized()), 1)

    def test_kandev_line(self):
        with mock.patch.object(self.m.shutil, "which", lambda name: "/home/x/.local/bin/msbctl"):
            code, out, err = self.run_main("host", "authorize", KEY, "--kandev")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.authorized(), [
            'restrict,command="/home/x/.local/bin/msbctl host serve --kandev" ' + KEY])
        code, _, err = self.run_main("host", "authorize", KEY, "--kandev", "--admin", "--replace")
        self.assertNotEqual(code, 0)
        self.assertIn("two different keys", err)

    def test_admin_plain_key_asks(self):
        code, _, _ = self.run_main("host", "authorize", KEY, "--admin", stdin="n\n")
        self.assertNotEqual(code, 0)
        code, _, err = self.run_main("host", "authorize", KEY, "--admin", stdin="y\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.authorized(), [KEY])

    def test_refuses_garbage(self):
        for bad in ("", "ssh-ed25519", "ssh-ed25519 not-base64!", KEY + "\nssh-rsa AAAA"):
            code, _, _ = self.run_main("host", "authorize", bad)
            self.assertNotEqual(code, 0)


class AutostartTest(MsbctlTest):

    def test_starts_only_the_flagged_entries(self):
        self.make_folder_sandbox("one", entry_extra="autostart = true")
        self.make_folder_sandbox("two")
        self.make_folder_sandbox("three", entry_extra="autostart = true")
        self.set_state(three="running")
        code, _, err = self.run_main("start", "--autostart")
        self.assertEqual(code, 0, err)
        created = [c["argv"][2] for c in self.msb_calls("create")]
        self.assertEqual(created, ["one"])
        self.assertEqual(self.msb_calls("start"), [])

    def test_check_runs_and_says_json(self):
        import json
        code, out, err = self.run_main("host", "check", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["restricted"])
        self.assertIn("swap", {c["check"] for c in data["checks"]})


if __name__ == "__main__":
    main()
