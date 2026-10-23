---
title: Your own models (pi)
section: Guides
order: 35
description: Run the pi coding agent against your own model server or any provider, with the API key kept on the host.
---

## pi, the agent for any model

Claude Code talks to Anthropic. For anything else (a model you serve
yourself, OpenRouter, OpenAI and so on) a sandbox can run
[pi](https://pi.dev), a small open-source (MIT) terminal coding agent that works with any
OpenAI-compatible server and with most providers' own APIs. pi can be on next
to Claude or instead of it.

Two things set it up:

1. **Model endpoints**, once per machine: `msbctl setup` → "Model endpoints".
   Each one is an `[llm.<name>]` table in `~/.config/msb/config.toml` and a key
   in `secrets/global.env`.
2. **pi in a sandbox**: tick `pi` under "Coding agents" in `msbctl add`, or
   later in `msbctl edit` → "Features & agents". That writes `pi = true` under
   `[bootstrap]` in the project's `sandbox.toml`. Which endpoints it gets is
   machine-local: `[defaults] llm`, or `llm` in the sandbox's registry entry
   (`msbctl edit` → "Models for pi").

Then rebuild and run `pi` inside, or `msbctl exec . -- pi -p "…"`. The first
endpoint is pi's default; `/model` (or Ctrl+L) switches between them.

## Your own server

```toml
[llm.qwen]
base_url = "https://llm.home.example:8443/v1"
models = ["Qwen3-Coder-Next"]
context_window = 131072
private_dns = true
ca_cert = "/home/you/.config/msb/home-ca.pem"
```

The server has to speak **HTTPS**, on any port but 80. msb only puts the real
key into a TLS connection it intercepts, so over plain HTTP the key would have
to be inside the VM, and `base` denies port 80 anyway. A server on your LAN
needs a certificate and nothing more. If your own CA signed it, `ca_cert` makes
msb trust that CA for that one host. `private_dns = true` says the name resolves
to a LAN address, which msb otherwise discards
([allow_private_dns](egress.md#three-properties-that-are-easy-to-get-backwards)).

From that one table, msbctl derives everything the sandbox needs:

| What | How |
| --- | --- |
| egress | `allow@llm.home.example:tcp:8443`, after the rule groups |
| TLS | interception on 8443 as well as 443, and the CA for that host only |
| the key | `LLM_KEY_QWEN`, bound to that host alone: a placeholder inside, the real value put into the `Authorization` header on the way out |
| the transcript | the host is added to every binding's passthrough list ([why](credentials.md#why-a-placeholder-can-break-an-agent-and-why-it-doesnt-here)) |
| pi's config | `~/.pi/agent/models.json` and `settings.json`, written on every start |

Egress, TLS and the key binding are fixed at create time. Changing an
endpoint, or which endpoints a sandbox gets, needs a rebuild. Its models and
pi's settings are rewritten on every start.

The other keys: `api` (`openai-completions` by default; also
`openai-responses`, `anthropic-messages`, `google-generative-ai`), `max_tokens`,
`reasoning`, and `compat`, which is handed to pi as it is (see pi's
`docs/models.md`). For `openai-completions` msbctl sets pi's
`supportsDeveloperRole` and `supportsReasoningEffort` to false, because vLLM,
llama.cpp and Ollama need that. For a Qwen model on vLLM that thinks,
`compat = { thinkingFormat = "qwen-chat-template" }` is the usual addition.

> **Note:** tool calling is the server's job as much as the model's. On vLLM
> pick the matching `--tool-call-parser`; on llama.cpp start it with `--jinja`.
> Serve at least 64k of context: pi's system prompt and tools come first.

## A provider pi knows

```toml
[llm.router]
provider = "openrouter"
models = ["qwen/qwen3-coder"]     # optional: only picks the default
```

`provider` is one of `anthropic`, `openai`, `openrouter`, `google`, `mistral`,
`groq`, `deepseek`, `xai`, `cerebras`, `fireworks`, `huggingface`. pi already
knows their models; msbctl knows their host, so the egress rule and the key
binding come from the same table. Its key is `LLM_KEY_ROUTER`, not pi's usual
`OPENROUTER_API_KEY`. msbctl points pi at its own variable. `base_url` sends a
provider through a proxy of yours instead.

## Keys

`LLM_KEY_<NAME>` lives in `secrets/global.env`. A sandbox's own
`secrets/<name>.env` wins if it has one. "Model endpoints" → "store or replace
a key" sets it, and a stopped sandbox picks it up on its next start. An
endpoint with no key stored sends none, which suits a server that wants none.

`LLM_KEY_*` variables are reserved like `GH_TOKEN`. No `secret_binds` entry in
any layer may name one, so nothing can send an endpoint's key to another host.
A project can turn pi on, but only this machine decides which endpoints it
reaches, and a project that turns it on later is a policy change: the next
rebuild shows it and asks first, like a new egress rule.

pi's state, including its sessions, is kept on the host at
`~/.local/state/msb/pi/<name>/` and survives a rebuild. Don't use pi's own
`/login` in a sandbox: it would store a real credential in that directory,
where the guest can read it.

pi's update check and install ping are off (`PI_OFFLINE = "1"` in
`[agent_env.pi]`). `msbctl update <name> -c pi` installs the latest version.
