"""pi: a second coding agent, driven by this machine's [llm] model endpoints."""

import contextlib
import io
import json
import os
from unittest import main, mock

from tests.harness import MsbctlTest

KEY = "planted-llm-key"
QWEN = ('[llm.qwen]\nbase_url = "https://llm.home.example:8443/v1"\n'
        'models = ["qwen-coder", "qwen-small"]\ncontext_window = 131072\nprivate_dns = true\n')
PI_ON = "[bootstrap]\npi = true\n"


class PiBase(MsbctlTest):
    """Helpers for the tests below."""
    env_keys = ("LLM_KEY_QWEN", "LLM_KEY_ROUTER", "GH_TOKEN")

    def config(self, text, default=("qwen",)):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        with open(self.m.CONFIG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[defaults]\nllm = {json.dumps(list(default))}\n\n{text}")

    def start(self, name="web"):
        code, out, err = self.run_main("start", name)
        self.assertEqual(code, 0, err)
        return out + err

    def create_argv(self):
        return self.msb_calls("create")[0]["argv"]

    def secret_flags(self):
        argv = self.create_argv()
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--secret"]

    def flag_values(self, flag):
        argv = self.create_argv()
        return [argv[i + 1] for i, a in enumerate(argv) if a == flag]

    def agent_file(self, name, file):
        return os.path.join(self.m.STATE_DIR, "pi", name, "agent", file)

    def agent_json(self, name, file):
        with open(self.agent_file(name, file), encoding="utf-8") as fh:
            return json.load(fh)


class PiTest(PiBase):

    # ------------------------------------------------------------ off / on

    def test_off_by_default_even_with_endpoints(self):
        self.config(QWEN)
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_QWEN", KEY)
        self.make_folder_sandbox("web")
        self.start()
        argv = self.create_argv()
        self.assertFalse(any("llm.home.example" in a for a in argv))
        self.assertFalse(any(a.endswith(":/root/.pi:uid=" + str(os.getuid()) + f",gid={os.getgid()}")
                             for a in argv))
        self.assertNotIn("LLM_KEY_QWEN", self.msb_calls("create")[0]["env"])
        self.assertIn("export MSB_WANT_PI='0'", self.msb_calls("exec")[0]["argv"][-1])
        self.assertFalse(os.path.exists(self.agent_file("web", "models.json")))

    def test_a_lan_endpoint_brings_everything_it_needs(self):
        ca = os.path.join(self.tmp, "home-ca.pem")
        with open(ca, "w", encoding="utf-8") as fh:
            fh.write("not really a certificate\n")
        self.config(QWEN + f'ca_cert = "{ca}"\n')
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_QWEN", KEY)
        self.make_folder_sandbox("web", sandbox_toml="[secrets]\ngithub = true\n" + PI_ON)
        self.store_secret(self.secrets_file("web"), "GH_TOKEN", "planted-gh")
        self.start()
        argv = self.create_argv()
        self.assertIn("allow@llm.home.example:tcp:8443", argv)
        # 443 restated: one --tls-intercept-port replaces msb's default.
        self.assertEqual(self.flag_values("--tls-intercept-port"), ["443", "8443"])
        self.assertEqual(self.flag_values("--tls-upstream-ca-cert-for"), [f"llm.home.example={ca}"])
        self.assertIn("--no-dns-rebind-protection", argv)
        flags = self.secret_flags()
        self.assertIn("LLM_KEY_QWEN:passthrough=[api.anthropic.com,platform.claude.com,"
                      "llm.home.example]@llm.home.example", flags)
        # Every binding: the endpoint now receives the whole transcript.
        gh = next(f for f in flags if f.startswith("GH_TOKEN"))
        self.assertIn("llm.home.example]", gh)
        self.assertEqual(self.msb_calls("create")[0]["env"].get("LLM_KEY_QWEN"), KEY)
        self.assert_not_in_argv(KEY)
        self.assertIn("export MSB_WANT_PI='1'", self.msb_calls("exec")[0]["argv"][-1])
        self.assertIn(f"export MSB_PI_PACKAGE='{self.m.PI_PACKAGE}'",
                      self.msb_calls("exec")[0]["argv"][-1])
        self.assertTrue(any(a.endswith(":/root/.pi:uid=" + str(os.getuid()) + f",gid={os.getgid()}")
                            for a in argv))

    def test_port_443_needs_no_intercept_port(self):
        self.config('[llm.box]\nbase_url = "https://llm.example.com/v1"\nmodels = ["m"]\n',
                    default=["box"])
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        out = self.start()
        self.assertIn("allow@llm.example.com:tcp:443", self.create_argv())
        self.assertEqual(self.flag_values("--tls-intercept-port"), [])
        self.assertNotIn("--no-dns-rebind-protection", self.create_argv())
        self.assertIn("no LLM_KEY_BOX stored", out)

    def test_the_sandboxes_own_key_wins(self):
        self.config(QWEN)
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_QWEN", "planted-shared")
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.store_secret(self.secrets_file("web"), "LLM_KEY_QWEN", KEY)
        self.start()
        self.assertEqual(self.msb_calls("create")[0]["env"].get("LLM_KEY_QWEN"), KEY)

    def test_the_registry_entry_picks_its_own(self):
        self.config(QWEN + '\n[llm.router]\nprovider = "openrouter"\n')
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_ROUTER", KEY)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON, entry_extra='llm = ["router"]')
        self.start()
        argv = self.create_argv()
        self.assertIn("allow@openrouter.ai:tcp:443", argv)
        self.assertFalse(any("llm.home.example" in a for a in argv))
        models = self.agent_json("web", "models.json")
        self.assertEqual(models, {"providers": {"openrouter": {
            "baseUrl": "https://openrouter.ai/api/v1", "apiKey": "$LLM_KEY_ROUTER"}}})
        settings = self.agent_json("web", "settings.json")
        self.assertEqual(settings["defaultProvider"], "openrouter")
        self.assertNotIn("defaultModel", settings)

    # ------------------------------------------------------- pi's own files

    def test_start_writes_pis_config_without_the_key(self):
        self.config(QWEN)
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_QWEN", KEY)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.start()
        with open(self.agent_file("web", "models.json"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(KEY, text)
        qwen = json.loads(text)["providers"]["qwen"]
        self.assertEqual(qwen["baseUrl"], "https://llm.home.example:8443/v1")
        # The `$` is what makes pi resolve it: pi >=1.0 interpolates $NAME and
        # takes a bare name as a literal key (0.73 was the other way round).
        self.assertEqual(qwen["apiKey"], "$LLM_KEY_QWEN")
        self.assertEqual(qwen["api"], "openai-completions")
        self.assertFalse(qwen["compat"]["supportsDeveloperRole"])
        self.assertEqual(qwen["models"][0], {"id": "qwen-coder", "contextWindow": 131072})
        settings = self.agent_json("web", "settings.json")
        self.assertEqual((settings["defaultProvider"], settings["defaultModel"]),
                         ("qwen", "qwen-coder"))
        self.assertIs(settings["enableInstallTelemetry"], False)
        with open(self.agent_file("web", "AGENTS.md"), encoding="utf-8") as fh:
            agents = fh.read()
        self.assertIn("Working inside a microsandbox", agents)
        self.assertIn("## This sandbox", agents)

    def test_settings_are_merged_and_a_choice_in_pi_is_kept(self):
        self.config(QWEN)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        os.makedirs(os.path.dirname(self.agent_file("web", "settings.json")))
        with open(self.agent_file("web", "settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"theme": "light", "enableInstallTelemetry": True}, fh)
        self.start()
        self.assertEqual(self.agent_json("web", "settings.json"),
                         {"defaultProvider": "qwen", "defaultModel": "qwen-coder",
                          "theme": "light", "enableInstallTelemetry": False})
        # You switch models inside pi; the next start leaves that alone.
        settings = self.agent_json("web", "settings.json")
        settings["defaultModel"] = "qwen-small"
        with open(self.agent_file("web", "settings.json"), "w", encoding="utf-8") as fh:
            json.dump(settings, fh)
        self.run_main("stop", "web")
        self.start()
        self.assertEqual(self.agent_json("web", "settings.json")["defaultModel"], "qwen-small")

    def test_a_model_chosen_in_msbctl_wins_over_the_one_in_pi(self):
        self.config(QWEN)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.start()
        self.m.set_toml_key(self.m.CONFIG_FILE, "default_model", "qwen-small", table="llm.qwen")
        self.run_main("stop", "web")
        self.start()
        self.assertEqual(self.agent_json("web", "settings.json")["defaultModel"], "qwen-small")

    def test_a_model_the_endpoint_no_longer_lists_is_replaced(self):
        self.config(QWEN)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        os.makedirs(os.path.dirname(self.agent_file("web", "settings.json")))
        with open(self.agent_file("web", "settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"defaultProvider": "qwen", "defaultModel": "Qwen3.8"}, fh)
        self.start()
        self.assertEqual(self.agent_json("web", "settings.json")["defaultModel"], "qwen-coder")

    # ------------------------------------------------------------- refusals

    def test_endpoint_problems(self):
        cases = {
            "plain http": ({"base_url": "http://llm.lan:8000/v1", "models": ["m"]}, "https://"),
            "port 80": ({"base_url": "https://llm.lan:80/v1", "models": ["m"]}, "port 80"),
            "credentials": ({"base_url": "https://u:p@llm.lan/v1", "models": ["m"]}, "credentials"),
            "empty default": ({"base_url": "https://llm.lan/v1", "default_model": ""},
                              "default_model"),
            "a typo": ({"base_url": "https://llm.lan/v1", "models": ["m"], "modle": 1}, "modle"),
            "unknown provider": ({"provider": "acme"}, "base_url instead"),
            "nothing": ({"models": ["m"]}, "needs base_url"),
            "bad size": ({"base_url": "https://llm.lan/v1", "models": ["m"],
                          "context_window": "big"}, "positive integer"),
            "missing ca": ({"base_url": "https://llm.lan/v1", "models": ["m"],
                            "ca_cert": "/nope/ca.pem"}, "PEM file"),
        }
        for label, (spec, says) in cases.items():
            with self.subTest(label):
                self.assertIn(says, self.m.llm_problem("qwen", spec) or "")
        self.assertIn("pi's own providers", self.m.llm_problem("openai", {
            "base_url": "https://llm.lan/v1", "models": ["m"]}))
        self.assertIsNone(self.m.llm_problem("qwen", {"base_url": "https://llm.lan:8443/v1",
                                                      "models": ["m"]}))
        # No models: the server's own list, asked on every start.
        self.assertIsNone(self.m.llm_problem("qwen", {"base_url": "https://llm.lan/v1"}))

    def test_an_unknown_endpoint_dies_before_create(self):
        self.config(QWEN, default=["nope"])
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        code, _, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("'nope'", err)
        self.assertEqual(self.msb_calls("create"), [])

    def test_a_project_cannot_rebind_an_endpoint_key(self):
        self.config(QWEN)
        self.make_folder_sandbox(
            "web", sandbox_toml='secret_binds = ["LLM_KEY_QWEN@evil.example"]\n' + PI_ON)
        self.store_secret(self.secrets_file("web"), "LLM_KEY_QWEN", KEY)
        code, _, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.msb_calls("create"), [])
        self.assertTrue(self.m.is_reserved_var("LLM_KEY_QWEN"))

    def test_a_project_turning_pi_on_needs_approval(self):
        self.config(QWEN)
        project = self.make_folder_sandbox("web")
        box = self.m.Sandbox("web", self.m.load_config())
        self.assertTrue(self.m.policy_pinned(box))
        with open(os.path.join(project, ".msb", "sandbox.toml"), "w", encoding="utf-8") as fh:
            fh.write(PI_ON)
        code, _, err = self.run_main("start", "web")
        self.assertNotEqual(code, 0)
        self.assertIn("policy not approved", err)
        self.assertEqual(self.msb_calls("create"), [])

    # ------------------------------------------------------- show and edit

    def test_show_json_says_stored_never_the_value(self):
        self.config(QWEN)
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_QWEN", KEY)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        code, out, err = self.run_main("show", "web", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertIn("pi", data["agents"])
        self.assertEqual(data["llm"], [{"name": "qwen", "base_url": "https://llm.home.example:8443/v1",
                                        "model": "qwen-coder", "key_stored": True,
                                        "problem": None}])
        self.assertNotIn(KEY, out)

    def test_edit_pins_the_endpoints_and_offers_a_rebuild(self):
        self.config(QWEN + '\n[llm.router]\nprovider = "openrouter"\n')
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        box = self.m.Sandbox("web", self.m.load_config())
        ctx = {"rebuild": set()}
        with mock.patch.object(self.m, "toggle_list", lambda *a, **k: ["qwen", "router"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.m.section_llm(box, self.m.load_config(), ctx)
        self.assertEqual(self.m.read_toml(self.entry_path("web"))["llm"], ["qwen", "router"])
        self.assertIn("pi's model endpoints", ctx["rebuild"])
        # Back to exactly the default: the pin goes, so it follows [defaults] again.
        box = self.m.Sandbox("web", self.m.load_config())
        with mock.patch.object(self.m, "toggle_list", lambda *a, **k: ["qwen"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.m.section_llm(box, self.m.load_config(), {"rebuild": set()})
        self.assertNotIn("llm", self.m.read_toml(self.entry_path("web")))

    def test_update_installs_the_latest_pi(self):
        self.config(QWEN)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.start()
        code, _, err = self.run_main("update", "web", "-c", "pi")
        self.assertEqual(code, 0, err)
        scripts = [c["argv"][-1] for c in self.msb_calls("exec")]
        self.assertIn(f"npm install -g {self.m.PI_PACKAGE}@latest", scripts[-1])



GUFO = '[llm.gufo]\nbase_url = "https://gufo.example/v1"\ndefault_model = "Qwen3.8 Flash Next"\n'
SERVED = {"object": "list", "data": [
    {"id": "Qwen3.8 Flash Next", "object": "model", "max_model_len": 131072},
    {"id": "Qwen3.8 Small", "object": "model"}]}


class FakeServer:
    """_llm_get() answers by URL: a dict is the JSON, an LlmError kind is raised.
    Records the headers of every call, to check where the key went."""

    def __init__(self, m, answers):
        self.m, self.answers, self.calls = m, answers, []

    def __call__(self, url, headers, ca_cert, timeout):
        self.calls.append((url, dict(headers), ca_cert))
        answer = self.answers.get(url, "absent")
        if isinstance(answer, str):
            raise self.m.LlmError(answer, f"{url}: {answer}")
        return answer


class ServedModelsTest(PiBase):

    def serve(self, answers):
        fake = FakeServer(self.m, answers)
        patcher = mock.patch.object(self.m, "_llm_get", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    # ------------------------------------------------------------ the probe

    def test_a_bare_url_is_found_under_v1(self):
        fake = self.serve({"https://gufo.example/v1/models": SERVED})
        base, api, models = self.m.probe_llm_server("https://gufo.example/", KEY)
        self.assertEqual((base, api), ("https://gufo.example/v1", "openai-completions"))
        self.assertEqual(models[0], {"id": "Qwen3.8 Flash Next", "context": 131072})
        url, headers, _ = fake.calls[0]
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertNotIn(KEY, url)

    def test_a_url_with_v1_is_kept(self):
        self.serve({"https://llm.example/v1/models": SERVED})
        base, _, _ = self.m.probe_llm_server("https://llm.example/v1", KEY)
        self.assertEqual(base, "https://llm.example/v1")

    def test_a_server_at_its_own_path(self):
        self.serve({"https://llm.example/openai/models": SERVED})
        base, api, _ = self.m.probe_llm_server("https://llm.example/openai", KEY)
        self.assertEqual((base, api), ("https://llm.example/openai", "openai-completions"))

    def test_an_anthropic_shaped_server(self):
        fake = self.serve({"https://llm.example/v1/models": "auth"})
        # Anthropic's list is also at /v1/models: answer only its own headers.
        def answer(url, headers, ca_cert, timeout):
            fake.calls.append((url, dict(headers), ca_cert))
            if url == "https://llm.example/v1/models" and "x-api-key" in headers:
                return {"data": [{"type": "model", "id": "claude-x", "display_name": "X"}]}
            raise self.m.LlmError("auth", "refused")
        with mock.patch.object(self.m, "_llm_get", answer):
            base, api, models = self.m.probe_llm_server("https://llm.example", KEY)
        self.assertEqual((base, api, models[0]["id"]),
                         ("https://llm.example", "anthropic-messages", "claude-x"))

    def test_a_refused_key_and_an_untrusted_certificate_say_so(self):
        self.serve({"https://gufo.example/v1/models": "auth"})
        with self.assertRaises(self.m.LlmError) as caught:
            self.m.probe_llm_server("https://gufo.example", KEY)
        self.assertEqual(caught.exception.kind, "auth")
        self.serve({"https://gufo.example/v1/models": "tls"})
        with self.assertRaises(self.m.LlmError) as caught:
            self.m.probe_llm_server("https://gufo.example", KEY)
        self.assertEqual(caught.exception.kind, "tls")

    def test_provider_lists_use_their_own_auth(self):
        fake = self.serve({
            "https://api.anthropic.com/v1/models": {"data": [{"id": "claude-a", "type": "model"}]},
            "https://generativelanguage.googleapis.com/v1beta/models": {"models": [
                {"name": "models/gemini-x", "supportedGenerationMethods": ["generateContent"],
                 "inputTokenLimit": 1048576},
                {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]}})
        self.assertEqual(self.m.fetch_llm_models({"provider": "anthropic"}, KEY)[0]["id"], "claude-a")
        self.assertEqual(fake.calls[-1][1]["x-api-key"], KEY)
        self.assertEqual(self.m.fetch_llm_models({"provider": "google"}, KEY),
                         [{"id": "gemini-x", "context": 1048576}])
        self.assertEqual(fake.calls[-1][1]["x-goog-api-key"], KEY)

    # ------------------------------------------------------ on every start

    def test_pi_gets_what_the_server_serves_now(self):
        self.config(GUFO, default=["gufo"])
        self.store_secret(self.m.GLOBAL_ENV, "LLM_KEY_GUFO", KEY)
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.serve({"https://gufo.example/v1/models": SERVED})
        self.start()
        models = self.agent_json("web", "models.json")["providers"]["gufo"]["models"]
        self.assertEqual(models, [{"id": "Qwen3.8 Flash Next", "contextWindow": 131072},
                                  {"id": "Qwen3.8 Small"}])
        self.assertEqual(self.agent_json("web", "settings.json")["defaultModel"],
                         "Qwen3.8 Flash Next")

    def test_a_model_no_longer_served_falls_back_and_says_how_to_change(self):
        self.config(GUFO, default=["gufo"])
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.serve({"https://gufo.example/v1/models": {"data": [{"id": "Qwen4 Mini"}]}})
        out = self.start()
        self.assertIn("no longer serves 'Qwen3.8 Flash Next'", out)
        self.assertIn("choose a model", out)
        self.assertEqual(self.agent_json("web", "settings.json")["defaultModel"], "Qwen4 Mini")
        ids = [m["id"] for m in self.agent_json("web", "models.json")["providers"]["gufo"]["models"]]
        self.assertEqual(ids, ["Qwen4 Mini"])

    def test_an_unreachable_server_uses_the_last_list(self):
        self.config(GUFO, default=["gufo"])
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.serve({"https://gufo.example/v1/models": SERVED})
        self.start()
        self.run_main("stop", "web")
        self.serve({"https://gufo.example/v1/models": "unreachable"})
        out = self.start()
        self.assertIn("using the list from", out)
        ids = [m["id"] for m in self.agent_json("web", "models.json")["providers"]["gufo"]["models"]]
        self.assertEqual(ids, ["Qwen3.8 Flash Next", "Qwen3.8 Small"])

    def test_with_no_list_ever_the_chosen_model_is_still_offered(self):
        self.config(GUFO, default=["gufo"])
        self.make_folder_sandbox("web", sandbox_toml=PI_ON)
        self.serve({})
        self.start()
        ids = [m["id"] for m in self.agent_json("web", "models.json")["providers"]["gufo"]["models"]]
        self.assertEqual(ids, ["Qwen3.8 Flash Next"])

    # ------------------------------------------------------------ choosing

    def test_pick_model_filters_a_long_list_and_takes_a_typed_id(self):
        models = [{"id": f"vendor/model-{i}", "context": None} for i in range(40)]
        answers = iter(["model-3"])
        with mock.patch.object(self.m, "ask", lambda *a, **k: next(answers)), \
                mock.patch.object(self.m, "choose_one", lambda title, opts, d=0: opts[0]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.pick_model(models), "vendor/model-3")
        answers = iter(["", "my custom id"])
        with mock.patch.object(self.m, "ask", lambda *a, **k: next(answers)), \
                mock.patch.object(self.m, "choose_one",
                                  lambda title, opts, d=0: "type a model id"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.pick_model(models), "my custom id")

    def test_adding_a_server_detects_it_and_picks_from_its_list(self):
        os.makedirs(self.m.CONFIG_DIR, exist_ok=True)
        open(self.m.CONFIG_FILE, "w", encoding="utf-8").close()
        self.serve({"https://gufo.example/v1/models": SERVED})
        choices = iter(["your own server (vLLM, llama.cpp, Ollama, LiteLLM, …)",
                        "Qwen3.8 Flash Next  131k context"])
        answers = iter(["gufo.example", ""])           # the URL, then the name's default
        # Like the real ask(): a blank answer is the default.
        with mock.patch.object(self.m, "ask", lambda q, d="": next(answers) or d), \
                mock.patch.object(self.m, "choose_one", lambda *a, **k: next(choices)), \
                mock.patch.object(self.m, "read_secret_hidden", lambda p: KEY), \
                mock.patch.object(self.m, "confirm", lambda q: False), \
                mock.patch.object(self.m, "_resolves_privately", lambda h: True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.m._add_llm(self.m.load_config())
        spec = self.m.load_config()["llm"]["gufo"]
        self.assertEqual(spec, {"base_url": "https://gufo.example/v1", "api": "openai-completions",
                                "private_dns": True, "default_model": "Qwen3.8 Flash Next"})
        self.assertEqual(self.m.read_env_file(self.m.GLOBAL_ENV)["LLM_KEY_GUFO"], KEY)
        with open(self.m.CONFIG_FILE, encoding="utf-8") as fh:
            self.assertNotIn(KEY, fh.read())

    def test_choosing_again_replaces_a_fixed_list_with_the_live_one(self):
        self.config('[llm.gufo]\nbase_url = "https://gufo.example/v1"\n'
                    'models = ["Qwen3.8", "Flash", "Next"]\n', default=["gufo"])
        self.serve({"https://gufo.example/v1/models": SERVED})
        spec = self.m.load_config()["llm"]["gufo"]
        with mock.patch.object(self.m, "choose_one",
                               lambda *a, **k: "Qwen3.8 Flash Next  131k context"), \
                mock.patch.object(self.m, "confirm", lambda q: True), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.m._choose_llm_model("gufo", spec)
        self.assertIn("'Qwen3.8' is no longer served", out.getvalue())
        spec = self.m.load_config()["llm"]["gufo"]
        self.assertEqual(spec.get("default_model"), "Qwen3.8 Flash Next")
        self.assertNotIn("models", spec)


if __name__ == "__main__":
    main()
