"""git_push: how the guest's git reaches GitHub, applied on every start."""

import base64
import os
from unittest import main

from tests.harness import MsbctlTest



def key(fill):
    return "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x0bssh-ed25519" + fill * 36).decode() + " laptop"


PUSH = key(b"p")


class GitPushTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.push_fp = self.m._parse_pub_line(PUSH)[0]

    def box(self, entry_extra="", identity_extra=""):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write('[identities.me]\nname = "Me"\nemail = "me@example.com"\n' + identity_extra)
        self.make_folder_sandbox("web", entry_extra='identity = "me"\n' + entry_extra,
                                 approve=False)
        if "ssh_keys" in entry_extra:
            # Instead of the harness's own `ssh_keys = []`, not as well as it.
            path = self.entry_path("web")
            with open(path, encoding="utf-8") as fh:
                text = fh.read().replace("ssh_keys = []\n", "", 1)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        self.approve("web")
        return self.m.Sandbox("web", self.m.load_config())

    def push_call(self, box):
        self.m.ensure_git_push(box)
        calls = [c["argv"] for c in self.msb_calls("exec") if "pushInsteadOf" in " ".join(c["argv"])]
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        return argv[argv.index("_") + 1:]

    def test_gh_is_the_default(self):
        box = self.box()
        self.assertEqual(box.git_push, "gh")
        self.assertEqual(self.push_call(box), ["gh"])

    def test_ssh_passes_the_identitys_push_key(self):
        box = self.box('git_push = "ssh"\n' + f'ssh_keys = ["{self.push_fp}"]\n',
                       f'push_key = "{PUSH}"\n')
        self.assertTrue(box.push_active)
        self.assertEqual(self.push_call(box), ["ssh", *PUSH.split()[:2]])

    def test_the_entrys_push_key_wins(self):
        other = key(b"o")
        box = self.box(f'git_push = "ssh"\npush_key = "{other}"\nssh_keys = []\n',
                       f'push_key = "{PUSH}"\n')
        self.assertEqual(box.push_pub, other)

    def test_a_key_the_sandbox_may_not_use_is_not_pinned(self):
        box = self.box('git_push = "ssh"\n', f'push_key = "{PUSH}"\n')   # ssh_keys = []
        self.assertFalse(box.push_active)
        self.assertEqual(self.push_call(box), ["ssh"])

    def test_an_unknown_mode_dies(self):
        self.box()
        with open(self.entry_path("web"), "a", encoding="utf-8") as fh:
            fh.write('git_push = "ftp"\n')
        with self.assertRaises(SystemExit):
            self.m.Sandbox("web", self.m.load_config())

    def test_the_default_comes_from_config(self):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write('[defaults]\ngit_push = "ssh"\n')
        box = self.box()
        self.assertEqual(box.git_push, "ssh")

    def test_start_applies_it_and_the_profile_says_so(self):
        box = self.box()
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertTrue(any("insteadOf" in " ".join(c["argv"]) for c in self.msb_calls("exec")))
        self.assertIn("over **gh**", self.m.sandbox_profile_section(box))

    def test_show_json_reports_it(self):
        box = self.box('git_push = "ssh"\n')
        self.assertEqual(self.m.show_data(box)["git_push"], "ssh")


if __name__ == "__main__":
    main()
