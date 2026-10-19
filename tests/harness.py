"""The test harness: a throwaway HOME, the fake msb on PATH, msbctl loaded fresh.

msbctl computes CONFIG_DIR, STATE_DIR and friends from the environment at
import, so every test sets the environment first and then loads its own copy of
the module under a unique name. What reaches `msb` is read back from the fake's
log (tests/fake/msb), argv and the environment variables a test asks for.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
from unittest import TestCase, mock
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSBCTL = os.path.join(ROOT, "msbctl")
FAKE_BIN = os.path.join(ROOT, "tests", "fake")
_SEQ = itertools.count()


def repo_image():
    """The image line of this repo's own .msb/dev.yaml: a real, pinned ref."""
    with open(os.path.join(ROOT, ".msb", "dev.yaml"), encoding="utf-8") as fh:
        for line in fh:
            if re.match(r"^image:\s*\S+\s*$", line):
                return line.split(":", 1)[1].strip()
    raise RuntimeError("no image: line in .msb/dev.yaml")


def _no_network(*_args, **_kwargs):
    raise urllib.error.URLError("the network is off in tests")


class MsbctlTest(TestCase):
    """setUp gives each test its own HOME and its own msbctl module (self.m)."""

    env_keys = ()          # variables the fake msb records, per test class

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="msbctl-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._saved_env = dict(os.environ)
        self.addCleanup(self._restore_env)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        # Not the checkout: its own .msb/ would name a sandbox for the cwd.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.tmp)
        os.environ.update({
            "HOME": self.home,
            "MSB_CONFIG_DIR": os.path.join(self.home, ".config", "msb"),
            "MSB_STATE_DIR": os.path.join(self.home, ".local", "state", "msb"),
            "MSB_HOME": os.path.join(self.home, ".microsandbox"),
            "FAKE_MSB_LOG": os.path.join(self.tmp, "msb.log"),
            "FAKE_MSB_STATE": os.path.join(self.tmp, "msb.json"),
            "FAKE_MSB_ENV_KEYS": ",".join(self.env_keys),
            "FAKE_TAILSCALE_LOG": os.path.join(self.tmp, "tailscale.log"),
            "PATH": FAKE_BIN + os.pathsep + os.environ.get("PATH", ""),
        })
        for var in ("SSH_AUTH_SOCK", "GH_TOKEN", "MSB_RESTRICTED", "SSH_ORIGINAL_COMMAND",
                    "CLAUDE_CODE_OAUTH_TOKEN", "FAKE_MSB_EXEC_OUT", "FAKE_MSB_READ_STDIN",
                    "FAKE_MSB_FAIL", "MSB_CONFIG_PATH", "FAKE_TAILSCALE_NO_CERTS"):
            os.environ.pop(var, None)
        self.m = self.load_msbctl()

    def fresh(self):
        """A new HOME and a new msbctl, for each case of a subTest loop. The
        cleanups stack, so the environment is still restored to the original."""
        self.setUp()

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    @staticmethod
    def load_msbctl():
        name = f"msbctl_under_test_{next(_SEQ)}"
        loader = importlib.machinery.SourceFileLoader(name, MSBCTL)
        spec = importlib.util.spec_from_file_location(name, MSBCTL, loader=loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    # ---------------------------------------------------------------- running

    def run_main(self, *argv, stdin="", tty=False):
        """Run msbctl's main() with argv; returns (exit code, stdout, stderr).

        The preflight (msb on PATH, /dev/kvm) and the ssh-agent filter daemon
        are switched off: neither belongs in a unit test. The network is off
        too, so nothing a test does can reach GitHub by accident. stdout and
        stderr are real files, because msbctl hands them to subprocesses.
        `tty` makes stdin and stdout claim to be a terminal, for the prompts
        that are only offered on one; the answers still come from `stdin`."""
        out = tempfile.TemporaryFile("w+", encoding="utf-8")
        err = tempfile.TemporaryFile("w+", encoding="utf-8")
        # Bytes for a verb that reads binary stdin (`kandev agentctl`).
        fake_in = io.TextIOWrapper(io.BytesIO(stdin)) if isinstance(stdin, bytes) else io.StringIO(stdin)
        if tty:
            fake_in.isatty = out.isatty = lambda: True
        code = 0
        with contextlib.ExitStack() as stack:
            stack.enter_context(out)
            stack.enter_context(err)
            stack.enter_context(mock.patch.object(sys, "argv", ["msbctl", *argv]))
            stack.enter_context(mock.patch.object(sys, "stdin", fake_in))
            stack.enter_context(mock.patch.object(self.m, "preflight", lambda args: None))
            stack.enter_context(mock.patch.object(self.m, "local_problem", lambda: None))
            stack.enter_context(mock.patch.object(self.m, "ensure_agent_filter", lambda box: None))
            stack.enter_context(mock.patch.object(self.m, "stop_agent_filter", lambda box: None))
            stack.enter_context(mock.patch("urllib.request.urlopen", _no_network))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                self.m.main()
            except SystemExit as exc:
                if isinstance(exc.code, str):
                    print(exc.code, file=err)
                    code = 1
                else:
                    code = exc.code or 0
            finally:
                self.m.BOOTSTRAP_FAILURES.clear()
            out.flush()
            err.flush()
            out.seek(0)
            err.seek(0)
            return code, out.read(), err.read()

    # ---------------------------------------------------------------- fixtures

    @property
    def registry_dir(self):
        return self.m.REGISTRY_DIR

    def entry_path(self, name):
        return os.path.join(self.m.REGISTRY_DIR, f"{name}.toml")

    def make_folder_sandbox(self, name, sandbox_toml="", dev_yaml=None, entry_extra="",
                            approve=True):
        """A project folder with .msb/ and a minimal registry entry. Returns
        the project path. Its project policy is approved (pinned) unless
        `approve` is False, as `msbctl add` does for a policy it wrote."""
        project = os.path.join(self.tmp, "projects", name)
        os.makedirs(os.path.join(project, ".msb"), exist_ok=True)
        with open(os.path.join(project, ".msb", "sandbox.toml"), "w", encoding="utf-8") as fh:
            fh.write(sandbox_toml)
        if dev_yaml is None:
            dev_yaml = f"image: {repo_image()}\n"
        with open(os.path.join(project, ".msb", "dev.yaml"), "w", encoding="utf-8") as fh:
            fh.write(dev_yaml)
        os.makedirs(self.m.REGISTRY_DIR, exist_ok=True)
        with open(self.entry_path(name), "w", encoding="utf-8") as fh:
            fh.write(f'name = "{name}"\nproject = "{project}"\nguest_path = "/work"\n'
                     f'repo = ""\nssh_keys = []\n{entry_extra}\n')
        if approve:
            self.approve(name)
        return project

    def approve(self, name):
        """Pin the sandbox's current project policy, as `msbctl policy approve` would."""
        self.m.approve_policy(self.m.Sandbox(name, self.m.load_config()))

    def store_secret(self, path, var, value):
        self.m.set_env_file_value(path, var, value)

    def secrets_file(self, name):
        return os.path.join(self.m.SECRETS_DIR, f"{name}.env")

    # ---------------------------------------------------------------- reading

    def msb_calls(self, verb=None):
        """Every recorded call ({"argv", "env"}), or those whose argv starts with verb."""
        try:
            with open(os.environ["FAKE_MSB_LOG"], encoding="utf-8") as fh:
                calls = [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            calls = []
        if verb is not None:
            calls = [c for c in calls if c["argv"][:1] == [verb]]
        return calls

    def assert_not_in_argv(self, value):
        """No recorded argv element contains `value`. The failure message says
        where, never what: `value` is usually a planted secret."""
        for n, call in enumerate(self.msb_calls()):
            for i, arg in enumerate(call["argv"]):
                if value in arg:
                    self.fail(f"the value under test reached argv: call {n} "
                              f"(msb {call['argv'][0]}), argument {i}")

    def assert_not_in_output(self, value, *texts):
        """Like assert_not_in_argv, for captured output."""
        for i, text in enumerate(texts):
            if value in text:
                self.fail(f"the value under test was printed (output #{i})")

    def set_state(self, **state):
        """Seed the fake's sandboxes: set_state(web="running")."""
        path = os.environ["FAKE_MSB_STATE"]
        try:
            with open(path, encoding="utf-8") as fh:
                current = json.load(fh)
        except FileNotFoundError:
            current = {}
        current.update(state)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(current, fh)

    def fake_state(self):
        try:
            with open(os.environ["FAKE_MSB_STATE"], encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}
