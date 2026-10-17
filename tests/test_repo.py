"""Sandboxes cloned from a repo: no host folder, the policy fetched at a commit."""

import base64
import json
import os
import shutil
from unittest import main, mock

from tests.harness import MsbctlTest, repo_image

SHA1 = "1" * 40
SHA2 = "2" * 40
POLICY1 = 'rule_groups = ["github"]\nextra_rules = ["allow@one.example:tcp:443"]\n'
POLICY2 = ('rule_groups = ["github"]\n'
           'extra_rules = ["allow@one.example:tcp:443", "allow@two.example:tcp:443"]\n')


class FakeGitHub:
    """github_api() answers, keyed by path. `files[sha][path]` is a file's text."""

    def __init__(self, private=False):
        self.private = private
        self.tip = SHA1
        self.files = {SHA1: {".msb/sandbox.toml": POLICY1, ".msb/dev.yaml": f"image: {repo_image()}\n"}}
        self.fail = {}          # path prefix -> status
        self.calls = []

    def __call__(self, path, token=None):
        self.calls.append(path)
        for prefix, status in self.fail.items():
            if path.startswith(prefix):
                return status, None
        if path == "/repos/acme/webshop":
            return 200, {"default_branch": "main", "private": self.private}
        if path.startswith("/repos/acme/webshop/branches/"):
            return (200, {}) if path.endswith("/main") else (404, None)
        if path.startswith("/repos/acme/webshop/commits/"):
            return 200, {"sha": self.tip}
        if path.startswith("/repos/acme/webshop/contents/"):
            rest = path[len("/repos/acme/webshop/contents/"):]
            file, _, query = rest.partition("?ref=")
            text = self.files.get(query, {}).get(file)
            if text is None:
                return 404, None
            raw = text.encode()
            return 200, {"type": "file", "size": len(raw),
                         "content": base64.b64encode(raw).decode(), "encoding": "base64"}
        return 404, None


class RepoTest(MsbctlTest):

    def setUp(self):
        super().setUp()
        self.gh = FakeGitHub()

    def fresh(self):
        super().fresh()
        self.gh = FakeGitHub()

    def main(self, *argv, **kw):
        with mock.patch.object(self.m, "github_api", self.gh):
            return self.run_main(*argv, **kw)

    def add(self, *extra):
        code, out, err = self.main("add", "--repo", "acme/webshop", "-y", *extra)
        self.assertEqual(code, 0, err)
        return out

    def create_argv(self, n=0):
        return self.msb_calls("create")[n]["argv"]

    def test_add_writes_entry_policy_and_pin(self):
        self.add()
        with open(self.entry_path("webshop"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('source   = "repo"', text)
        self.assertIn('repo     = "acme/webshop"', text)
        self.assertNotIn("project =", text)
        pdir = self.m.policy_dir("webshop")
        with open(os.path.join(pdir, ".msb", "sandbox.toml"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), POLICY1)
        with open(os.path.join(pdir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual((meta["sha"], meta["branch"], meta["private"]), (SHA1, "main", False))
        box = self.m.Sandbox("webshop", self.m.load_config())
        self.assertTrue(self.m.policy_pinned(box))
        self.assertTrue(box.entry["policy_pin"].startswith("sha256:"))

    def test_start_mounts_the_workspace_and_clones(self):
        self.add()
        code, _, err = self.main("start", "webshop")
        self.assertEqual(code, 0, err)
        argv = self.create_argv()
        self.assertIn("webshop-workspace:/work:kind=disk,size=20G", argv)
        self.assertFalse(any(a.endswith(":/work:uid=" + str(os.getuid()) + f",gid={os.getgid()}")
                             for a in argv))
        self.assertFalse(any("/.msb:" in a for a in argv))
        boot = self.msb_calls("exec")[0]["argv"][-1]
        self.assertIn("export MSB_CLONE_URL='https://github.com/acme/webshop.git'", boot)
        self.assertIn("export MSB_CLONE_REF='main'", boot)
        self.assertIn("allow@one.example:tcp:443", argv)
        self.assertIn("webshop-workspace", self.fake_state()["_volumes"])

    def test_a_server_error_is_never_a_missing_file(self):
        self.gh.fail["/repos/acme/webshop/contents/.msb/dev.yaml"] = 500
        code, _, err = self.main("add", "--repo", "acme/webshop", "-y")
        self.assertNotEqual(code, 0)
        self.assertIn("500", err)
        self.assertFalse(os.path.exists(self.entry_path("webshop")))

    def test_a_missing_file_means_the_defaults(self):
        del self.gh.files[SHA1][".msb/sandbox.toml"]
        del self.gh.files[SHA1][".msb/dev.yaml"]
        self.add()
        code, _, err = self.main("start", "webshop")
        self.assertEqual(code, 0, err)
        argv = self.create_argv()
        image = self.m.load_config()["defaults"]["image"]
        self.assertEqual(argv[-1], image)

    def test_rebuild_with_a_lost_policy_dies_on_an_error(self):
        self.add()
        shutil.rmtree(self.m.policy_dir("webshop"))
        self.gh.fail["/repos/acme/webshop/contents/"] = 500
        code, _, err = self.main("rebuild", "webshop")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.msb_calls("create"), [])

    def test_lost_policy_is_refetched_at_the_approved_commit(self):
        self.add()
        shutil.rmtree(self.m.policy_dir("webshop"))
        self.gh.tip = SHA2
        self.gh.files[SHA2] = {".msb/sandbox.toml": POLICY2}
        code, _, err = self.main("start", "webshop")
        self.assertEqual(code, 0, err)
        self.assertIn(f"/repos/acme/webshop/contents/.msb/sandbox.toml?ref={SHA1}", self.gh.calls)
        self.assertNotIn("allow@two.example:tcp:443", self.create_argv())

    def test_guest_path_must_suit_a_volume(self):
        for path in ("host", "/home/x/.work"):
            with self.subTest(path=path):
                self.fresh()
                self.add()
                self.m.set_toml_key(self.entry_path("webshop"), "guest_path", path)
                code, _, err = self.main("start", "webshop")
                self.assertNotEqual(code, 0)
                self.assertEqual(self.msb_calls("create"), [])
        code, _, err = self.main("add", "--repo", "acme/other", "-y", "--guest-path", "/a.b")
        self.assertNotEqual(code, 0)

    def test_rebuild_stays_on_the_pinned_commit_until_updated(self):
        self.add()
        self.set_state(webshop="running")
        self.gh.tip = SHA2
        self.gh.files[SHA2] = {".msb/sandbox.toml": POLICY2}
        calls_before = len(self.gh.calls)
        code, _, err = self.main("rebuild", "webshop")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.gh.calls), calls_before)          # fetched nothing
        self.assertNotIn("allow@two.example:tcp:443", self.create_argv())

        code, out, err = self.main("policy", "webshop", "update")
        self.assertNotEqual(code, 0)
        self.assertIn("+   allow@two.example:tcp:443", out)
        self.assertIn(SHA2[:12], out)
        with open(os.path.join(self.m.policy_dir("webshop"), "meta.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["sha"], SHA1)              # nothing swapped

        code, out, err = self.main("policy", "webshop", "update", stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        code, _, err = self.main("rebuild", "webshop")
        self.assertEqual(code, 0, err)
        self.assertIn("allow@two.example:tcp:443", self.create_argv(1))

    def test_private_repo_without_a_token_warns_before_create(self):
        self.gh.private = True
        self.add()
        code, out, err = self.main("start", "webshop")
        self.assertIn("clone will fail", err)
        self.assertEqual(len(self.msb_calls("create")), 1)

    def test_a_repo_cannot_choose_its_conf(self):
        self.gh.files[SHA1][".msb/sandbox.toml"] = POLICY1 + 'conf = "other.yaml"\n'
        code, _, err = self.main("add", "--repo", "acme/webshop", "-y")
        self.assertNotEqual(code, 0)
        self.assertIn("conf", err)

    def test_a_repo_dev_yaml_that_says_more_is_refused(self):
        self.gh.files[SHA1][".msb/dev.yaml"] = f"image: {repo_image()}\nenv:\n  A: b\n"
        code, _, err = self.main("add", "--repo", "acme/webshop", "-y")
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(self.entry_path("webshop")))

    def test_purge_removes_the_volume_policy_and_entry(self):
        self.add()
        self.main("start", "webshop")
        code, out, err = self.main("purge", "webshop", "-y")
        self.assertEqual(code, 0, err)
        self.assertIn("repository on GitHub is not touched", out)
        self.assertNotIn("webshop-workspace", self.fake_state().get("_volumes", {}))
        self.assertFalse(os.path.exists(self.m.policy_dir("webshop")))
        self.assertFalse(os.path.exists(self.entry_path("webshop")))

    def test_move_refuses(self):
        self.add()
        code, _, err = self.main("move", "webshop", "/tmp")
        self.assertNotEqual(code, 0)
        self.assertIn("no folder on this machine", err)

    def test_allow_adds_to_the_repo_rules(self):
        self.add()
        code, _, err = self.main("allow", "webshop", "mine.example")
        self.assertEqual(code, 0, err)
        self.main("start", "webshop")
        argv = self.create_argv()
        self.assertIn("allow@one.example:tcp:443", argv)
        self.assertIn("allow@mine.example:tcp:443", argv)

    def test_the_current_folder_never_names_a_repo_sandbox(self):
        self.add()
        os.chdir(self.tmp)
        code, _, err = self.main("show")
        self.assertNotEqual(code, 0)

    def test_dir_and_repo_together(self):
        code, _, err = self.main("add", "somewhere", "--repo", "acme/webshop")
        self.assertNotEqual(code, 0)
        code, _, err = self.main("add", "somewhere", "--ref", "main")
        self.assertNotEqual(code, 0)
        self.assertIn("only with --repo", err)


if __name__ == "__main__":
    main()
