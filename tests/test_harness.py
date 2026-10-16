"""The harness itself: the fake msb sees what msbctl hands it, and nothing else."""

import unittest

from tests.harness import MsbctlTest, repo_image


class HarnessTest(MsbctlTest):
    env_keys = ("GH_TOKEN",)

    def test_ls_with_nothing_registered(self):
        code, out, _ = self.run_main("ls")
        self.assertEqual(code, 0)
        self.assertIn("nothing registered", out)

    def test_start_creates_once_and_the_token_stays_out_of_argv(self):
        token = "planted-gh-value-7f3a91"
        self.make_folder_sandbox("web", sandbox_toml="[secrets]\ngithub = true\n")
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", token)

        code, out, err = self.run_main("start", "web")
        self.assertEqual(code, 0, err)
        creates = self.msb_calls("create")
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["argv"][-1], repo_image())
        self.assertEqual(creates[0]["env"].get("GH_TOKEN"), token)
        self.assert_not_in_argv(token)
        self.assert_not_in_output(token, out, err)

    def test_unexpected_msb_call_fails(self):
        import subprocess
        proc = subprocess.run(["msb", "frobnicate"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
