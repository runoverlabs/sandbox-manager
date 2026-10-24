---
title: Agent tools
section: Guides
order: 40
description: Give every sandbox a capability your own endpoints back — web search, page reading, anything else — with one folder on the host and nothing in the project.
---

## Why a tool has to come from the host

An agent inside a sandbox has no internet. That is the design: egress is
deny-by-default, so Claude's `WebFetch` and `WebSearch` and pi's equivalents
fail the moment they dial out, and they fail as a connection error rather than
as a rule you could add one host at a time.

The way out is a service that does the leaving-on-its-own for the agent: it
searches, or fetches a page, and returns the text over HTTPS. The sandbox then
needs a rule for two named hosts instead of one for every site the agent might
want to read — which is both the fix and the honest description of the cost:
whatever that endpoint can reach, every sandbox holding the bundle can read.

A **tool bundle** is how you attach such a capability to a sandbox without
touching the project:

```text
~/.config/msb/tools/web/
├── bundle.toml        what it is, the hosts egress must allow, its [env]
├── pi.ts              a pi extension
└── claude/SKILL.md    a Claude Code skill
```

It lives on the host for the same reason a machine-only rule group does: the
endpoints are yours. A project that committed `tools = ["web"]` would fail on
every other clone, where `web` names nothing — and a project cannot be trusted
to ask for egress anyway, since the bundle's hosts are decided by whoever wrote
the bundle.

Turn bundles on in `msbctl setup` → **Agent tools** (`[defaults] tools`, for
every new sandbox), or per sandbox in `msbctl edit <name>` → **Agent tools**
(`tools` in its registry entry).

## A worked example

```toml
# ~/.config/msb/tools/web/bundle.toml
description = "`websearch` and `webread`: web search and page text, served by
this machine's own endpoints"

hosts = ["search.example.com", "fetch.example.com"]

[env]
WEB_SEARCH_URL = "https://search.example.com/search"
WEB_FETCH_URL = "https://fetch.example.com/fetch"
```

`pi.ts` registers the two tools with pi — self-contained, importing only what
pi's loader aliases (`typebox`, pi's own packages) and what node provides:

```ts
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent"
import { Type } from "typebox"

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "websearch",
    description: "Search the web. Returns ranked title, URL and snippet.",
    parameters: Type.Object({ query: Type.String() }),
    async execute(_id, args) {
      const url = new URL(process.env.WEB_SEARCH_URL!)
      url.search = new URLSearchParams({ q: args.query, format: "json" }).toString()
      const reply = await fetch(url, { headers: { accept: "application/json" } })
      return { content: await reply.text() }
    },
  })
}
```

`claude/SKILL.md` says the same thing to Claude Code as prose: here is
`$WEB_SEARCH_URL`, `curl` it like this, these are the fields back, this is what
each failure means.

From those three files, on every `msbctl start`:

| What | How |
| --- | --- |
| egress | `allow@search.example.com:tcp:443` and `allow@fetch.example.com:tcp:443`, after the rule groups, before `extra_rules` |
| TLS | interception on any port other than 443, or the rules are silent denies |
| environment | the `[env]` table, as ordinary `--env` variables |
| pi | the extension at `~/.pi/agent/extensions/msb-web.ts`, discovered by pi itself |
| Claude Code | the skill at `~/.claude/skills/msb-web/SKILL.md` |
| the agent's context | the bundle's `description` in the "This sandbox" section of its `CLAUDE.md` / `AGENTS.md` — only for an agent the bundle has an adapter for |

Nothing is mounted for it and nothing runs in the guest to install it: the
adapters are copied into state directories that are already mounted, which is
how pi's model config and the managed `CLAUDE.md` arrive too.

## What is derived, and when

| Change | Lands on |
| --- | --- |
| an adapter file (`pi.ts`, `SKILL.md`) | the next start — or immediately, on pi's `/reload` |
| the bundle's `description` | the next start |
| `hosts` or `[env]` | a rebuild: rules and environment variables are fixed at create |
| attaching or detaching a bundle | a rebuild, for the same reason |

`msbctl show <name>` lists the bundles, their hosts and which agents they have
adapters for; `msbctl show <name> --json` puts the same under `tools`. A bundle
that is missing or broken is flagged there with what to fix (`problem` in the
JSON), and `msbctl start` refuses that sandbox until it is fixed. A broken
bundle no sandbox names stops nothing: `msbctl setup` → Agent tools shows it
with its error.

## Rules worth knowing

**A bundle's rules come from its `hosts` and nowhere else.** There is no key to
write them in, so a sandbox cannot have the tool and lack the route, or the
route and not the tool. HTTPS only, any port but 80 — `base` denies plaintext
before anything allows it.

**`[env]` is not a secret store.** Its values go to the guest verbatim, with no
placeholder and no substitution. A bundle that needs a key declares a
`secret_binds` entry in the sandbox as usual and reads the placeholder; the two
are separate on purpose. Names starting `MSB_` are refused: msb identifies a
credential placeholder by its `$MSB_<VAR>` shape and destroys a request that
carries one where substitution is not allowed, so prose that merely mentions
`$MSB_SOMETHING` would be at risk.

**Everything an agent can be told, it will be told.** The `description` goes
into the agent's context verbatim, so it is the place to name the tools, what
they are for, and what the endpoints cannot do.

**An adapter is one file.** msbctl copies it and nothing beside it, so a
relative import dangles, and no `npm install` ever runs in the guest: use pi's
aliases, node builtins and globals, or nothing.

**A bundle is validated before anything is created.** A missing folder, a
missing `description`, an `env` URL that `hosts` does not list, a port-80 host:
each is refused with the file named, because a tool an agent was promised and
does not have arrives as a mysterious absence, and a refused connection looks
like an outage from inside the guest.

**Kandev sandboxes get none.** They are provisioned by their own path with their
own egress and none of the per-boot seeding a bundle needs.

## Turning it off

Untick the bundle and rebuild. The rules and the variables go with it, and
msbctl removes the adapter files it wrote — it remembers what it installed, so
an extension or a skill you put in those directories yourself is never touched.
