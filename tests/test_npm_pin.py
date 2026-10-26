"""npm: pinned over the one node's major line bundles."""

import subprocess
import tomllib
from unittest import main

from tests.harness import MsbctlTest, ROOT


class NpmPinTest(MsbctlTest):

    def bootstrap_script(self, name="web"):
        code, _, err = self.run_main("start", name)
        self.assertEqual(code, 0, err)
        return self.msb_calls("exec")[0]["argv"][-1]

    def test_the_shipped_pin_reaches_bootstrap(self):
        with open(f"{ROOT}/defaults.toml", "rb") as fh:
            pin = tomllib.load(fh)["versions"]["npm"]
        self.make_folder_sandbox("web")
        self.assertIn(f"export MSB_NPM_VERSION='{pin}'", self.bootstrap_script())

    def test_an_empty_pin_keeps_nodes_own(self):
        self.make_folder_sandbox("web", entry_extra='[versions]\nnpm = ""\n')
        self.assertIn("export MSB_NPM_VERSION=''", self.bootstrap_script())

    def test_the_update_script_is_valid_bash(self):
        script = self.m.installer_script("npm", "12.2.1")
        self.assertIn("npm@12.2.1", script)
        self.assertEqual(subprocess.run(["bash", "-n", "-c", script]).returncode, 0)


if __name__ == "__main__":
    main()
