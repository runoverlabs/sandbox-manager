"""`msbctl completion bash|zsh|fish` and the `_complete` fast path behind it.

The scripts are generated from build_parser(), so the test that matters is
that every verb the parser has reaches every script, and that the bash one,
run for real, offers what the parser would accept."""

import json
import os
import shutil
import subprocess
from unittest import main, mock, skipUnless

from tests.harness import MSBCTL, MsbctlTest


class Completion(MsbctlTest):

    def visible_verbs(self, parser=None, path=""):
        """Every "verb" and "verb subverb" a user can type, read from the parser."""
        parser = parser or self.m.build_parser()
        found = []
        for action in parser._actions:
            if isinstance(action, self.m.argparse._SubParsersAction):
                hidden = {c.dest for c in action._choices_actions
                          if c.help == self.m.argparse.SUPPRESS}
                for name, child in action.choices.items():
                    if name in hidden:
                        continue
                    full = f"{path} {name}".strip()
                    found.append(full)
                    found += self.visible_verbs(child, full)
        return found

    def script(self, shell):
        code, out, err = self.run_main("completion", shell)
        self.assertEqual(code, 0, err)
        return out

    def add_remote(self, name, rows):
        self.m.ensure_local_config()
        self.m.set_toml_key(self.m.CONFIG_FILE, "ssh", f"msb@{name}.example", table=f"remotes.{name}")
        if rows is not None:
            os.makedirs(self.m.REMOTES_DIR, exist_ok=True)
            with open(self.m._remote_cache_path(name), "w", encoding="utf-8") as fh:
                json.dump({"at": 1, "sandboxes": rows}, fh)

    # ------------------------------------------------------------ the scripts

    def test_every_verb_is_in_every_script(self):
        verbs = self.visible_verbs()
        self.assertIn("secret migrate", verbs)
        self.assertIn("completion", verbs)
        for shell in self.m.COMPLETION_SHELLS:
            text = self.script(shell)
            for verb in verbs:
                # Each verb is a case of the spec table, in sh and fish alike.
                self.assertRegex(text, rf"(?m)^\s+(case )?'{verb}'\)?", f"{shell}: {verb}")

    def test_hidden_verbs_are_not_offered(self):
        model = self.m.completion_model()
        for hidden in ("_agent-filter", "_complete"):
            self.assertNotIn(hidden, model[""]["subs"])
            self.assertNotIn(hidden, model)

    def test_slots_follow_the_parser(self):
        model = self.m.completion_model()
        self.assertEqual((model["start"]["slots"], model["start"]["repeat"]), (["sandbox"], True))
        self.assertEqual(model["observe"]["slots"], ["sandbox", "words:report,on,off"])
        self.assertEqual(model["remote"]["slots"][1], "remote")
        self.assertEqual(model["move"]["slots"], ["sandbox", "dir"])
        self.assertEqual(model["secret migrate"]["values"], {"--to": "words:keyring,file"})
        self.assertEqual(model["add"]["values"]["--remote"], "remote")
        # exec's command is the shell's to complete, not a slot of msbctl's.
        self.assertEqual(model["exec"]["slots"], ["sandbox"])

    def test_scripts_parse(self):
        checks = {"bash": ["bash", "-n"], "zsh": ["zsh", "-n"], "fish": ["fish", "--no-execute"]}
        for shell, argv in checks.items():
            if not shutil.which(argv[0]):
                continue
            path = os.path.join(self.tmp, f"c.{shell}")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.script(shell))
            proc = subprocess.run(argv + [path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{shell}: {proc.stderr}")

    def test_unknown_shell_is_refused(self):
        code, _, err = self.run_main("completion", "tcsh")
        self.assertNotEqual(code, 0)
        self.assertIn("invalid choice", err)

    # ------------------------------------------------------- the names a Tab gets

    def test_names_are_local_then_each_remote_from_its_cache(self):
        self.make_folder_sandbox("web")
        self.make_folder_sandbox("api")
        self.add_remote("box", [{"name": "far"}, {"name": "Not A Name"}, "junk"])
        self.add_remote("never-listed", None)
        code, out, err = self.run_main("_complete", "names")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.split(), ["api", "web", "box:far"])
        code, out, _ = self.run_main("_complete", "remotes")
        self.assertEqual(out.split(), ["box", "never-listed"])

    def test_a_tab_runs_neither_msb_nor_ssh(self):
        self.make_folder_sandbox("web")
        self.add_remote("box", [{"name": "far"}])
        with self.m_patch("query_remote_ls"), self.m_patch("ssh_argv"):
            code, out, err = self.run_main("_complete", "names")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.msb_calls(), [])

    def test_a_tab_needs_no_msb_on_this_machine(self):
        # A real process with no msb on PATH, which the preflight would die on:
        # run_main() switches the preflight off, so it cannot show this.
        self.make_folder_sandbox("web")
        env = dict(os.environ, PATH=os.pathsep.join(
            d for d in os.environ["PATH"].split(os.pathsep)
            if d and not os.path.exists(os.path.join(d, "msb"))))
        for argv in (["_complete", "names"], ["completion", "bash"]):
            proc = subprocess.run([MSBCTL, *argv], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(subprocess.run([MSBCTL, "_complete", "names"], capture_output=True,
                                        text=True, env=env).stdout.split(), ["web"])

    def test_a_broken_config_still_completes_local_names(self):
        self.make_folder_sandbox("web")
        self.m.ensure_local_config()
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write("this is = = not toml\n")
        code, out, _ = self.run_main("_complete", "names")
        self.assertEqual((code, out.split()), (0, ["web"]))

    def m_patch(self, name):
        """Replace msbctl's `name` with something that fails the test if called."""
        def called(*_args, **_kwargs):
            raise AssertionError(f"{name} was called for a Tab")
        return mock.patch.object(self.m, name, called)

    # ------------------------------------------------------------ bash, for real

    @skipUnless(shutil.which("bash"), "no bash")
    def test_bash_offers_what_the_parser_takes(self):
        self.make_folder_sandbox("web")
        self.make_folder_sandbox("api")
        self.add_remote("box", [{"name": "far"}])
        script = os.path.join(self.tmp, "c.bash")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(self.script("bash"))

        def offered(line):
            """COMPREPLY for `line`, its words split as bash splits them (at `:` too)."""
            words = line.replace(":", " : ").split() + ([""] if line.endswith(" ") else [])
            body = (f'source "$1"; COMP_LINE="$2"; COMP_POINT=${{#COMP_LINE}}; '
                    f'COMP_WORDS=("$3" "${{@:4}}"); COMP_CWORD={len(words) - 1}; '
                    '_msbctl; printf "%s\\n" "${COMPREPLY[@]}"')
            proc = subprocess.run(["bash", "-c", body, "bash", script, line.replace("msbctl", MSBCTL, 1),
                                   MSBCTL, *words[1:]], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout.split()

        self.assertEqual(offered("msbctl st"), ["status", "start", "stop"])
        self.assertEqual(offered("msbctl start "), ["api", "web", "box:far"])
        self.assertEqual(offered("msbctl start web w"), ["web"])
        # bash replaces only what follows the last `:`, even right after it.
        self.assertEqual(offered("msbctl shell box:f"), ["far"])
        self.assertEqual(offered("msbctl shell box:"), ["far"])
        self.assertEqual(offered("msbctl observe web "), ["report", "on", "off"])
        self.assertIn("--from-observe", offered("msbctl allow web --"))
        self.assertEqual(offered("msbctl secret "), ["add", "rm", "ls", "set", "migrate"])
        self.assertEqual(offered("msbctl secret set "), ["api", "web", "box:far"])
        self.assertEqual(offered("msbctl secret migrate --to "), ["keyring", "file"])
        self.assertEqual(offered("msbctl remote test "), ["box"])
        self.assertEqual(offered("msbctl rename web "), [])
        self.assertEqual(offered("msbctl port --rm 8080 "), ["api", "web", "box:far"])
        self.assertEqual(offered("msbctl exec web -- "), [])


if __name__ == "__main__":
    main()
