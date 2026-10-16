"""A project's dev.yaml is read for its image and never handed to msb."""

import os
import unittest

from tests.harness import MsbctlTest, repo_image


class ConfTest(MsbctlTest):

    def create_argv(self):
        creates = self.msb_calls("create")
        self.assertEqual(len(creates), 1)
        return creates[0]["argv"]

    def test_plain_sandbox_gets_no_conf(self):
        self.make_folder_sandbox("web")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertNotIn("--conf", self.create_argv())

    def test_msb_conf_comes_first(self):
        conf = os.path.join(self.tmp, "mine.yaml")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("user: root\n")
        self.make_folder_sandbox("web", entry_extra=f'msb_conf = "{conf}"')
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        argv = self.create_argv()
        self.assertEqual(argv[3:5], ["--conf", conf])
        self.assertEqual(argv.count("--conf"), 1)

    def test_msb_conf_with_interpolation_dies(self):
        conf = os.path.join(self.tmp, "mine.yaml")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write('env:\n  X: "${GH_TOKEN}"\n')
        self.make_folder_sandbox("web", entry_extra=f'msb_conf = "{conf}"')
        code, _, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("${", err)
        self.assertEqual(self.msb_calls("create"), [])

    def test_msb_conf_must_be_absolute(self):
        self.make_folder_sandbox("web", entry_extra='msb_conf = "mine.yaml"')
        code, _, _ = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.msb_calls("create"), [])

    def test_dev_yaml_that_says_more_is_refused(self):
        image = repo_image()
        for body in (f"image: {image}\nenv:\n  A: b\n",
                     f"image: {image}\nmounts: [\"../..:/h\"]\n",
                     f"{{image: {image}}}\n",
                     f"image: {image}\npatches:\n  - copy_file: {{src: /etc/passwd}}\n"):
            with self.subTest(body=body):
                self.fresh()
                self.make_folder_sandbox("web", dev_yaml=body)
                code, _, err = self.run_main("start", "web")
                self.assertNotEqual(code, 0)
                self.assertIn("never passed to msb", err)
                self.assertEqual(self.msb_calls("create"), [])

    def test_old_keys_are_accepted(self):
        self.make_folder_sandbox("web", dev_yaml=(
            f"# a comment\n---\nimage: {repo_image()}\n\ncpus: 4\nmemory: \"8G\"\nworkdir: /work\n"))
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)

    def test_existing_sandbox_still_starts(self):
        self.make_folder_sandbox("web", dev_yaml=f"image: {repo_image()}\nenv:\n  A: b\n")
        self.set_state(web="stopped")
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.msb_calls("start")), 1)

    def test_show_warns(self):
        self.make_folder_sandbox("web", dev_yaml=f"image: {repo_image()}\nenv:\n  A: b\n")
        code, _, err = self.run_main("show", "web")
        self.assertEqual(code, 0, err)
        self.assertIn("a rebuild will refuse", err)

    def test_path_images_die(self):
        for ref in ("/home/you", "./rootfs"):
            with self.subTest(ref=ref):
                self.fresh()
                self.make_folder_sandbox("web", dev_yaml=f"image: {ref}\n")
                code, _, err = self.run_main("start", "web")
                self.assertNotEqual(code, 0)
                self.assertIn("not an image reference", err)
                self.assertEqual(self.msb_calls("create"), [])

    def test_image_ref_shapes(self):
        good = [repo_image(), "ubuntu", "ubuntu:24.04", "ghcr.io/acme/web:v1",
                "localhost:5000/x/y:latest", "docker.io/library/alpine@sha256:" + "a" * 64]
        bad = ["/home/you", "./rootfs", "../x", "~/x", "file:///x", "ubuntu 24.04",
               " ubuntu", "Ubuntu", "acme/Web", ""]
        for ref in good:
            self.assertIsNone(self.m.image_problem(ref), ref)
        for ref in bad:
            self.assertIsNotNone(self.m.image_problem(ref), ref)

    def test_conf_outside_the_project_dies(self):
        for conf in ("/etc/passwd", "../outside.yaml"):
            with self.subTest(conf=conf):
                self.fresh()
                self.make_folder_sandbox("web", sandbox_toml=f'conf = "{conf}"\n', approve=False)
                code, _, err = self.run_main("start", "web")
                self.assertNotEqual(code, 0)
                self.assertIn("outside the project", err)
                self.assertEqual(self.msb_calls("create"), [])

    def test_conf_problems_lines(self):
        path = os.path.join(self.tmp, "d.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("image: x\nnetwork:\n  rules: []\n")
        problems = self.m.conf_problems(path)
        self.assertEqual(len(problems), 2)
        self.assertIn("`network`", problems[0])
        self.assertIn("nested", problems[1])
        self.assertEqual(self.m.conf_problems(os.path.join(self.tmp, "missing.yaml")), [])


if __name__ == "__main__":
    unittest.main()
