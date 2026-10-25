---
title: Configuration
section: Reference
order: 20
description: Every key in config.toml, .msb/sandbox.toml and the registry entry, and where files live.
---

Four TOML files, later ones winning. See
[How it works](how-it-works.md#the-four-configuration-layers) for how they
merge. The comments in the shipped `defaults.toml` and in the files the wizard
writes are the long-form documentation of every key; this page is the map.

## Files and directories

| Path | What |
| --- | --- |
| `<install>/defaults.toml` | the shipped defaults. Never edit; an upgrade replaces it |
| `~/.config/msb/config.toml` | your overrides |
| `~/.config/msb/CLAUDE.local.md` | your additions to every sandbox's `CLAUDE.md` |
| `~/.config/msb/sandboxes/<name>.toml` | one registry entry per sandbox |
| `~/.config/msb/secrets/global.env` | the Claude token, and an optional `GH_TOKEN` for version checks (0600) |
| `~/.config/msb/secrets/<name>.env` | that sandbox's tokens (0600) |
| `<project>/.msb/sandbox.toml` | the project's portable policy |
| `~/.local/state/msb/policy/<name>/` | a repo sandbox's `.msb/`, as fetched from GitHub, and `meta.json` |
| `<project>/.msb/dev.yaml` | the image, and nothing else; read by msbctl, never passed to msb |
| `~/.local/state/msb/claude/<name>/` | that sandbox's `~/.claude` |
| `~/.local/state/msb/profile/` | the assembled `CLAUDE.md`, mounted read-only |
| `~/.local/state/msb/agent/` | the SSH-agent filters' sockets and logs |
| `~/.local/state/msb/versions.json` | the cached version checks |
| `~/.local/state/msb/policy-approved/<name>.json` | the project policy last approved for that sandbox |

`MSB_CONFIG_DIR` and `MSB_STATE_DIR` move the two roots.

## Value types

The tables below name a type for each key. These are what the types mean, and
what msbctl checks before it hands a value to msb.

| Type | Written as | Checked |
| --- | --- | --- |
| size | `"8G"`: a whole number and `M`, `G` or `T` | disk sizes when the disk is made (`is not a size like 5G or 512M`); `memory` is passed to msb as it is |
| rule | `"allow@github.com:tcp:443"`, see [the rule grammar](egress.md#the-rule-grammar) | its shape, before create, naming the file it's in; msb checks the target |
| group | a name from `[rules]`, shipped or yours | an unknown name stops the create with `unknown rule group` |
| guest path | an absolute path inside the sandbox | no `:`; not inside `/bin`, `/boot`, `/dev`, `/etc`, `/lib*`, `/proc`, `/run`, `/sbin`, `/sys` or `/usr`; not one of `/`, `/home`, `/media`, `/mnt`, `/opt`, `/root`, `/srv`, `/tmp` or `/var`; not over a folder msbctl mounts itself |
| host path | absolute, or starting with `~` | `~` is expanded to your home |
| image reference | `registry/name:tag@sha256:…` | a path is refused: msb would boot a host folder |
| list | a TOML array, `["a", "b"]` | |

## config.toml

Keep it short: a value copied here from `defaults.toml` stops following the
shipped one. Tables merge with the shipped ones key by key; anything else,
including a whole egress group, replaces the shipped value.

### `[defaults]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `workspaces` | host path | `"~/workspaces"` | where a bare name given to `msbctl add` resolves. `""` resolves against the current directory |
| `guest_path` | `"/work"`, `"host"` or a guest path | `"/work"` | where a new sandbox mounts its project. `"host"` means the host's own path |
| `image` | image reference | a pinned devcontainers Ubuntu digest | the image a new sandbox starts from |
| `cpus` | integer | `4` | |
| `memory` | size | `"8G"` | a ceiling, not a reservation |
| `root_disk` | size | `"16G"` | the writable root disk |
| `rule_groups` | list of groups | `["github", "claude"]` | groups a new sandbox gets on top of `base` |
| `egress_mode` | `"enforce"` or `"observe"` | `"enforce"` | `"observe"` stops blocking for every sandbox; per sandbox is better (`msbctl observe`) |
| `private_dns_groups` | list of groups | `[]` | groups whose names resolve to private addresses; projects using one get `allow_private_dns` |
| `claude_auth` | `"secret"` or `"mount"` | `"secret"` | `"mount"` shares the host's real `~/.claude` instead of a placeholder token. A fallback only |
| `claude_token` | token name | `"main"` | the stored Claude token a sandbox uses unless its registry entry sets `claude_token` |
| `llm` | list of endpoint names | `[]` | the [model endpoints](models.md) a sandbox with pi gets unless its registry entry sets `llm`; the first is pi's default |
| `tools` | list of tool names | `[]` | the [agent tools](agent-tools.md) a new sandbox gets unless its registry entry sets `tools`; each is a folder under `~/.config/msb/tools` |
| `identity` | identity name | `""` | the `[identities]` entry new sandboxes use |
| `git_push` | `"gh"` or `"ssh"` | `"gh"` | how a new sandbox's git reaches GitHub: `"gh"` is https with the GitHub token, `"ssh"` the filtered agent. See [git push](credentials.md#git-push-gh-or-ssh) |
| `git_checkstat` | boolean | `true` | set `core.checkStat = minimal` in each mounted project's repos at every start, so a [host editor](troubleshooting.md#gitindex-disappears-for-a-few-seconds-after-a-git-command) doesn't rewrite `.git/index` under the sandbox |
| `workspace_disk` | size | `"20G"` | the clone's disk volume for a sandbox [without a folder](repo-sandboxes.md); fixed when created |

### `[identities.<name>]`

```toml
[identities.public]
name        = "yourhandle"
email       = "12345+yourhandle@users.noreply.github.com"
signing_key = "ssh-ed25519 AAAA..."      # optional: sign commits with this key
push_key    = "ssh-ed25519 AAAA..."      # optional: push over ssh with this key
```

Applied inside the guest with `git config --system`, the lowest of git's three
layers, so a repo's own identity still wins. See
[commit signing](credentials.md#commit-signing) and
[git push](credentials.md#git-push-gh-or-ssh).

### `[rules]`

Egress groups, `name = [rule, …]`. Yours are added to the shipped ones; a
shipped name redefined here replaces that group entirely. See
[Network & egress](egress.md).

### `[env]`

Environment variables every sandbox gets. The shipped set is `DO_NOT_TRACK = "1"`
and `EDITOR = "nano"`. Projects merge their own over these. Fixed at create
time.

### `[agent_env.claude]`

Environment variables only for sandboxes with Claude Code. The shipped set turns
off telemetry, error reporting, feedback prompts and the auto-updater, and sets
`IS_SANDBOX = "1"`. Claude Code runs as root in the sandbox, and without that
setting it and `claude-agent-acp` (the adapter Zed uses) don't offer bypass-permissions mode
(`--dangerously-skip-permissions`). Every `[env]` table, yours or a project's,
overrides these. Fixed at create time.

### `[agent_env.pi]`

The same for sandboxes with pi: `PI_OFFLINE = "1"`, which turns off its update
check and install ping.

### `[llm.<name>]`

A model endpoint for pi: `base_url` (HTTPS) for your own server, or `provider`
for one pi knows, and `default_model`, the model pi starts with. Without a
fixed `models` list, pi is offered whatever the server serves at each start.
Also `api`, `context_window`, `max_tokens`, `reasoning`, `private_dns`,
`ca_cert` and `compat`. None ship; `msbctl
setup` → "Model endpoints" writes them, and its key goes to `secrets/global.env`
as `LLM_KEY_<NAME>`. See [Your own models](models.md).

### `[versions]`

Component pins for the bootstrap: `node` (major), `gh`, `gitleaks`, `bun`. A
sandbox's own `[versions]` overrides these.

### `[version_check]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `ttl_hours` | integer | `6` | how long upstream version checks are cached |
| `use_global_token` | boolean | `true` | use `GH_TOKEN` from `secrets/global.env` for them, if present |

### `[secrets]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `store` | `"file"`, `"keyring"` or `"auto"` | `"file"` | where new secret values go. See [the keyring](credentials.md#keeping-the-values-in-the-keyring); `msbctl secret migrate` moves the existing ones and sets this |

### `[secret_presets.<name>]`

What `msbctl secret add` offers. Shipped: `npm`, `dockerhub`, `ghcr`, `pypi`,
`crates`.

```toml
[secret_presets.mytool]
env   = "MYTOOL_TOKEN"
hosts = ["api.mytool.example"]
help  = "https://mytool.example/settings/tokens"
usage = "mytool login --token \"$MYTOOL_TOKEN\""
```

## .msb/sandbox.toml

The project's policy. It never contains a host path, a token or a sandbox
name, so it's safe to commit.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `rule_groups` | list of groups | `[defaults] rule_groups` | egress groups, on top of `base` |
| `extra_rules` | list of rules | `[]` | one-off rules, emitted last |
| `allow_private_dns` | boolean | `false` | accept DNS answers that point at private addresses |
| `secret_binds` | list of `"ENV[:OPTIONS]@HOST[,HOST]"` | `[]` | extra secrets; the values live in `secrets/<name>.env` or the keyring |
| `cpus` | integer | `[defaults] cpus` | |
| `memory`, `root_disk` | size | `[defaults]` | |
| `containers_disk` | size | none | a disk for `/var/lib/containers`, kept across rebuilds |
| `identity` | identity name | `[defaults] identity` | the `[identities]` entry this project commits as |
| `[env]` | table of strings | | extra environment variables, merged over the machine-wide set |
| `[caches]` | table of sizes | | one disk per package manager: `npm`, `bun`, `python`, `rust`, `go` |
| `[secrets] github` | boolean | `true` with a GitHub repo | bind this project's `GH_TOKEN` |

### `[bootstrap]`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `packages` | list | `[]` | extra apt packages |
| `claude` | boolean | `true` | install Claude Code and its ACP adapter, `claude-agent-acp` |
| `pi` | boolean | `false` | install [pi](models.md), the agent for any model. Which endpoints it gets is machine-local |
| `bun`, `gitleaks` | boolean | `false` | install these |
| `containers_storage` | `"fuse-overlayfs"` | none | for [podman](toolchains.md#containers-inside-a-sandbox-podman) without a container disk |
| `script` | path inside the project | none | a project script run last, inside the guest, from the project folder |

## .msb/dev.yaml

One line msbctl reads: `image:`, which must be an image reference
(`registry/name:tag@sha256:…`); a path is refused. The file is **never passed
to msb**. msb's own config file can mount host paths, copy host files into the
guest and fill in `${VAR}` from msb's environment, which holds the bound
secrets, and the project folder is writable from inside the sandbox. So a
create or rebuild refuses a `dev.yaml` that sets anything else. The `cpus`,
`memory` and `workdir` keys older versions wrote are accepted and ignored.
`msbctl show` warns about a file a rebuild would refuse; a sandbox that already
exists keeps starting.

| A `dev.yaml` with | moves to |
| --- | --- |
| `env:` | `[env]` in `.msb/sandbox.toml` |
| `cpus:`, `memory:` | `.msb/sandbox.toml` |
| `mounts:`, `ports:` | `msbctl mount`, `msbctl port` (the registry entry) |
| anything else | a file of your own, named by `msb_conf` in the registry entry |

`msb_conf` is the operator's escape hatch for msb features msbctl doesn't model
(`user`, `rlimits`, `security`, …). It lives in the registry entry only, must
be an absolute path, and may not contain `${`. The flags msbctl emits win over
it.

### The policy pin

These keys in `.msb/sandbox.toml` are applied only once approved on the host
(see [the policy pin](egress.md#the-policy-pin)): `rule_groups`,
`extra_rules`, `allow_private_dns`, `secret_binds`, `[secrets]`, `cpus`,
`memory`, `root_disk`, `containers_disk`, `[caches]` and, once it is on,
`[bootstrap] pi`, which brings this machine's [model endpoints](models.md)
with it. They decide what may
leave the sandbox, which host a stored value is sent to, and what the sandbox
takes from the host: a committed `memory = "256G"` is as much a change as a
new rule. `image`, the rest of `[bootstrap]` and `[env]` aren't pinned; they
act only inside the guest. The approved values are kept in
`~/.local/state/msb/policy-approved/<name>.json`, and their digest as
`policy_pin` in the registry entry. Keys in the registry entry itself are
yours and are never re-approved.

## The registry entry

`~/.config/msb/sandboxes/<name>.toml` is machine-local and never committed.
Any key it sets overrides the project's file.

| Key | Type | Meaning |
| --- | --- | --- |
| `name`, `project` | string, host path | the sandbox's name and the absolute path of its project folder |
| `source`, `repo`, `ref` | strings | `source = "repo"` for a sandbox [without a folder](repo-sandboxes.md), which has `repo` and an optional `ref` instead of `project` |
| `guest_path` | `"/work"`, `"host"` or a guest path | where the project appears inside: `"/work"`, `"host"` (the same path as `project`) or an absolute path. Absent means the `[defaults]` value. Needs a rebuild |
| `repo` | `owner/name` | `owner/name` on GitHub, for the token binding and the picker |
| `identity` | identity name | an `[identities]` name; applied at every start |
| `claude_token` | token name | a stored Claude token's name; absent means `[defaults] claude_token` |
| `llm` | list of endpoint names | the [model endpoints](models.md) pi gets, first being its default; absent means `[defaults] llm`. Needs a rebuild |
| `tools` | list of tool names | the [agent tools](agent-tools.md) it gets, by folder name; absent means `[defaults] tools`. Their rules and environment need a rebuild; the adapter files refresh at every start |
| `git_checkstat` | boolean | absent means `[defaults] git_checkstat`. Applied at every start; `false` doesn't remove the value from repos that already have it |
| `autostart` | boolean | started when the picker opens |
| `ssh_keys` | list of fingerprints | key fingerprints this sandbox may use. Absent means all, `[]` means none |
| `mounts` | list | extra folders, as `"HOST[:GUEST][:ro\|rw]"` |
| `extra_rule_groups` | list of groups | egress groups only this machine defines (your `[rules]`), added to the project's `rule_groups`. `msbctl add` and `edit` put yours here. Needs a rebuild |
| `ports` | list | published ports, as `"PORT"`, `"HOST:GUEST"` or `"BIND:HOST:GUEST"`, optionally `/udp`. Needs a rebuild |
| `egress_mode` | `"enforce"` or `"observe"` | `"observe"` while measuring; only ever set here, never in the project |
| `volumes` | string | the disk-volume prefix, set by `msbctl rename` to keep the old disks |
| `policy_pin` | string | written by msbctl: the digest of the project policy last approved |
| `msb_conf` | absolute host path | your own msb config file, passed as `--conf`: an absolute path, never in a project, no `${` in it. See [dev.yaml](#msbdevyaml) |
| `image`, `cpus`, `memory`, `root_disk`, `conf`, `rule_groups`, `extra_rules` | as above | per-machine overrides. `conf` must name a file inside the project |
| `[versions]` | table | what `msbctl update` installed, so a rebuild reproduces it |
