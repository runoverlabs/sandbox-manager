"""The "This sandbox" section: what an agent is told about where things are.

The section is appended per sandbox to the managed CLAUDE.md (Claude) and to
~/.pi/agent/AGENTS.md (pi) — both OUTSIDE the project mount, so every path the
agent might need has to be spelled out here in guest terms.
"""

from unittest import main

from tests.harness import MsbctlTest


class ProfileSectionTest(MsbctlTest):

    def section(self, **entry):
        """The section for a folder sandbox whose registry entry has these keys
        changed after the harness wrote it (it pins guest_path = "/work")."""
        self.make_folder_sandbox("web")
        path = self.entry_path("web")
        for key, value in entry.items():
            self.m.set_toml_key(path, key, value)
        return self.m.sandbox_profile_section(self.m.Sandbox("web", self.m.load_config()))

    def test_names_the_guest_project_and_where_its_skills_live(self):
        text = self.section()
        self.assertIn("**/work**", text)
        self.assertIn("`/work/.agents/skills/`", text)

    def test_the_entrys_guest_path_is_used_and_not_the_default(self):
        text = self.section(guest_path="/src")
        self.assertIn("Your project folder here is **/src**", text)
        self.assertIn("`/src/.agents/skills/`", text)
        self.assertNotIn("/work", text)

    def test_the_path_is_absolute_however_the_section_reads(self):
        # A relative `.agents/skills/` would resolve against the agent's cwd,
        # which for this file is its home, not the project.
        for line in self.section().splitlines():
            if ".agents/skills" in line:
                self.assertIn("`/work/.agents/skills/`", line)
                self.assertNotIn(" .agents/skills", line)

    def test_survives_a_sandbox_with_no_features(self):
        # The harness's folder sandbox has no features, so the feature block is
        # absent entirely; the path is unconditional and must still be there.
        text = self.section()
        self.assertIn("git reaches GitHub", text)
        self.assertIn("`/work/.agents/skills/`", text)


if __name__ == "__main__":
    main()
