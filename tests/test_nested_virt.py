"""nested_virt: whether a sandbox's guest gets /dev/kvm (msb's --nested-virt).

Always passed to msb, true or false, so msb's own sandbox_defaults never
decide; resolved registry entry > project > [defaults]; pinned like the
other policy keys; and the podman feature turns it on."""

import json
import os
from unittest import main, mock

from tests.harness import MsbctlTest


class NestedVirtTest(MsbctlTest):

    def nested_flags(self, name="web"):
        code, _, err = self.run_main("start", name)
        self.assertEqual(code, 0, err)
        argv = self.msb_calls("create")[-1]["argv"]
        return [a for a in argv if a.startswith("--nested-virt")]

    def config(self, text):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write(text)

    def test_off_unless_asked_and_always_stated(self):
        self.make_folder_sandbox("web")
        self.assertEqual(self.nested_flags(), ["--nested-virt=false"])

    def test_the_machine_default(self):
        self.config("[defaults]\nnested_virt = true\n")
        self.make_folder_sandbox("web")
        self.assertEqual(self.nested_flags(), ["--nested-virt=true"])

    def test_the_project_over_the_default_and_the_entry_over_both(self):
        self.config("[defaults]\nnested_virt = false\n")
        self.make_folder_sandbox("web", sandbox_toml="nested_virt = true\n")
        self.assertEqual(self.nested_flags(), ["--nested-virt=true"])
        self.fresh()
        self.make_folder_sandbox("web", sandbox_toml="nested_virt = true\n",
                                 entry_extra="nested_virt = false")
        self.assertEqual(self.nested_flags(), ["--nested-virt=false"])

    def test_not_a_boolean_dies_naming_the_file(self):
        self.make_folder_sandbox("web", sandbox_toml='nested_virt = "yes"\n', approve=False)
        code, _, err = self.run_main("start", "web")
        self.assertEqual(code, 1)
        self.assertIn("nested_virt 'yes' is not true or false", err)
        self.assertIn("sandbox.toml", err)
        self.assertEqual(self.msb_calls("create"), [])

    def test_a_project_turning_it_on_needs_approval(self):
        project = self.make_folder_sandbox("web")
        with open(os.path.join(project, ".msb", "sandbox.toml"), "a", encoding="utf-8") as fh:
            fh.write("nested_virt = true\n")
        box = self.m.Sandbox("web", self.m.load_config())
        self.assertFalse(self.m.policy_pinned(box))
        # Unattended, a create refuses rather than handing out KVM unasked.
        code, _, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("policy not approved", err)
        self.assertEqual(self.msb_calls("create"), [])

    def test_show_json(self):
        self.make_folder_sandbox("web", sandbox_toml="nested_virt = true\n")
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["nested_virt"], True)

    def test_podman_turns_it_on(self):
        features = lambda title, options, selected, locked=None: (  # noqa: E731
            [o for o in options if o.startswith("podman")] if title == "features" else list(selected))
        with mock.patch.object(self.m, "toggle_list", features):
            plan = self.m.pick_features([], [], config={}, agents=[])
        self.assertEqual(plan["features"], ["podman"])
        self.assertIs(plan["nested_virt"], True)
        none = lambda title, options, selected, locked=None: []  # noqa: E731
        with mock.patch.object(self.m, "toggle_list", none):
            self.assertIs(self.m.pick_features([], [], config={}, agents=[])["nested_virt"], False)


if __name__ == "__main__":
    main()
