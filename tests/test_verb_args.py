"""Handlers called from inside msbctl get the arguments the parser would give."""

import ast
from unittest import main, mock

from tests.harness import MsbctlTest


class VerbArgsTest(MsbctlTest):

    def test_every_option_is_present_at_its_default(self):
        args = self.m.verb_args("ls", refresh=True)
        self.assertTrue(args.refresh)
        self.assertFalse(args.json)
        self.assertIs(args.func, self.m.cmd_ls)
        self.assertIsNone(self.m.verb_args("add").repo)

    def test_an_unknown_option_is_refused(self):
        with self.assertRaises(TypeError):
            self.m.verb_args("ls", no_such_option=True)

    def test_every_call_in_msbctl_names_real_options(self):
        with open(self.m.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "verb_args"]
        self.assertGreater(len(calls), 10)
        for call in calls:
            with self.subTest(line=call.lineno):
                self.m.verb_args(call.args[0].value, **{k.arg: None for k in call.keywords})

    def test_the_menus_add_reaches_the_wizard(self):
        # Without fzf the menu is numbered: 1 is "add". The wizard then runs out
        # of input, which the menu reports and survives; "q" quits.
        with mock.patch.object(self.m.shutil, "which", lambda cmd: None):
            code, _, err = self.run_main(stdin="1\n\n\nq\n")
        self.assertNotIn("Traceback", err)
        self.assertNotIn("AttributeError", err)

    def test_the_menus_refresh_lists(self):
        self.make_folder_sandbox("web")
        with mock.patch.object(self.m.shutil, "which", lambda cmd: None):
            refresh = [key for key, _ in self.m.MENU].index("refresh") + 1
            code, out, err = self.run_main(stdin=f"{refresh}\nq\n")
        self.assertEqual(code, 0, err)
        self.assertIn("web", out)


if __name__ == "__main__":
    main()
