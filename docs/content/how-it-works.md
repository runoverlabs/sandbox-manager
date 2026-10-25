---
title: How it works
section: Concepts
order: 10
description: The security model, what it does not protect, the four configuration layers, and what is fixed at create time.
---

## The security model in one table

| Threat | What stops it |
| --- | --- |
| The agent sends your code or data somewhere you didn't approve | deny-by-default egress: only hosts in the project's rule groups are reachable, per port |
| The agent reads a token and leaks it | tokens never enter the VM. The guest holds a placeholder, and the real value is swapped in on the host, in headers, for named hosts only |
| The agent steals an SSH key | keys never enter the VM. A per-sandbox filter in front of your agent only lists and signs, and only with the keys you picked |
| The agent rewrites your git identity or host config | identity is set with `git config --system` *inside* the guest, never in `/work/.git/config`; your host config isn't mounted |
| One project's sandbox reads another's transcripts or your Claude login | each sandbox has its own `~/.claude`, and the Claude credential is a placeholder too |
| The agent edits the project's `.msb/sandbox.toml` to widen its own egress or re-aim a secret | the [policy pin](egress.md#the-policy-pin): a changed policy is shown and must be approved on the host before a rebuild applies it, and `.msb/` is read-only in the guest |
| The central instructions get edited by the agent | `CLAUDE.md` is copied in from a read-only mount on every start |

## What it does not protect

The table is only half the model. The other half is what an agent in a sandbox
can still do, by design or because nothing short of taking its network away
would stop it. Choose rule groups and tokens the way you'd choose what a new
contractor gets.

- **Anything an allowed host accepts.** An allowlist decides *where* data can
  go, not *what* goes there. If a host accepts uploads (a package registry, an
  issue tracker, a paste service, a git server), the agent can send it your
  code. A rule group is a list of places your project may write to, so keep
  groups narrow and leave out the ones the project doesn't need.
- **What a token is allowed to do.** The agent can't read a token, but it can
  *use* it on the hosts it's bound to, with every permission it carries. A
  GitHub token for all your repositories lets the agent push to all of them.
  That's why [Get started](quickstart.md#the-github-token) asks for a
  fine-grained token for one repository. The same goes for an SSH key you pick
  with `msbctl keys`, and for the Claude token, which spends your usage.
- **DNS.** Every sandbox can resolve names, so data spelled into a lookup
  (`<data>.example.org`) reaches whoever runs that domain's nameservers. It's
  slow and small, but it is a way out that no egress rule closes.
- **Your project folder.** It's shared read-write, and anything the agent
  writes there is yours on the host: source, build scripts, lockfiles, CI
  workflows. Review what changed before you run or push it from the host. The
  same is true of an [extra folder](folders.md#extra-folders) mounted
  read-write. Only `.msb/` is protected, by the policy pin.
- **Your model provider.** The agent sends its context, which includes your
  code, to the endpoint it talks to. That's how an agent works, not a leak,
  but it decides which provider is in the loop.
- **Observe mode.** While it's on, nothing is blocked. Secrets are still
  substituted only for their own hosts, but the agent can reach anywhere.
- **The guest itself.** The agent runs as root in its VM. Nothing inside the
  guest is protected from it, including its own tools and settings. The
  central `CLAUDE.md` comes back on every start, and that is all.
- **The hypervisor.** A bug in msb, libkrun or KVM that lets a guest out is a
  bug in those projects. msb-manager depends on them to keep the VM a VM.

[Compared with alternatives](alternatives.md) sets this model beside other
agent sandboxes.

## What runs where

```text title="host and guest"
 HOST                                         GUEST (microVM, one per project)
 msbctl            ─ creates, starts, edits   bootstrap.sh  piped in over stdin, once
 ~/.config/msb/    config, registry, tokens   /work         your project (shared folder)
 ~/.local/state/msb/claude/<name>  ────────▶  /root/.claude its own Claude state
 ~/.local/state/msb/profile/  ─ read-only ─▶  CLAUDE.md, copied in each start
 msbctl _agent-filter <name> ◀── vsock ────── socat bridge at /tmp/ssh-agent.sock
```

`msbctl` runs on the **host** and needs `/dev/kvm`. None of msb-manager's own
code is mounted into the guest: the bootstrap is piped in over stdin, and the
`CLAUDE.md` comes from an assembled copy, never from the installed tree.

## The four configuration layers

Settings resolve through four TOML files. Later ones win:

| # | File | Who writes it | Holds |
| --- | --- | --- | --- |
| 1 | `defaults.toml` | ships with msb-manager | egress groups, version pins, default resources |
| 2 | `~/.config/msb/config.toml` | you | your overrides: identities, your own groups, defaults |
| 3 | `<project>/.msb/sandbox.toml` | the wizard, then you | this project's policy; portable, committed |
| 4 | `~/.config/msb/sandboxes/<name>.toml` | the wizard, then you | this machine's paths, keys, identity; never committed |

**Merging.** Between layers 1 and 2, tables merge key by key and everything else
is replaced whole. That includes an egress group: redefining `github` replaces
it entirely rather than splicing two host lists together, because rule order
matters and half a group is worse than either. For a sandbox, the registry
entry overrides the project file, which overrides your machine defaults. `[env]`
tables *merge* across the layers, so a project adding one variable keeps the
telemetry opt-outs (which come from `[agent_env.claude]` when the sandbox has
Claude Code).

```console
$ msbctl config      # every value, and which file it came from
$ msbctl show        # what one sandbox resolves to
```

> **Note:** Nothing machine-local goes in `.msb/sandbox.toml`: no host paths, no
> tokens, no sandbox name. That's what makes it safe to commit, so the policy
> travels with every clone.

### Two project layouts

Both are normal:

- **The project is the repo.** `<project>/.git` exists, so `.msb/` sits inside
  the checkout and is committed with it.
- **The project contains the repo.** `msbctl add` produces this when it clones
  for you: `<project>/<repo>/.git`, with `.msb/` *beside* the checkout. There
  `.msb/` is machine-local by position, and a fresh clone elsewhere won't have
  it.

## Create time vs. restart

Some settings are baked into the VM when it's created, and only a rebuild
changes them. Others can change on a running sandbox.

| Change | How it applies |
| --- | --- |
| egress rules, observe mode, DNS rebind protection | `msbctl rebuild` |
| mounts, extra folders, project folder | `msbctl rebuild` |
| the image, environment variables, disks | `msbctl rebuild` |
| cpus, memory | `msbctl resize`: a restart, state kept |
| root disk | `msbctl resize`: grows live |
| secrets (add or remove) | `msbctl secret`: live or a restart |
| SSH key selection | `msbctl keys`: immediately |
| git identity, autostart | the next start |

`msbctl edit` knows which is which: it applies what it can immediately and
collects the rest into a single rebuild offer when you're done.

## The bootstrap

`bootstrap.sh` runs once inside the guest at create time. It:

1. moves apt to HTTPS (plain HTTP is denied by policy), then installs the base
   tools (`socat`, `jq`, `curl`, `ripgrep`, `fd`, `tree`, `shellcheck`,
   `yamllint`, `nano`, `openssh-client` and a few more) plus the project's
   extra packages;
2. links the package caches and sets up podman storage, if the project uses
   them;
3. installs node from NodeSource, verifying the signing key's fingerprint, then
   Claude Code and its ACP adapter (`claude-agent-acp`), unless the project
   turned it off, and [pi](models.md) if it turned that on;
4. installs `gh`, and `bun` and `gitleaks` if asked for, from pinned,
   checksum-verified GitHub releases;
5. marks the project folder and the repos in it as git `safe.directory`
   entries (each `shell`/`exec` adds any found since), then runs the project's own setup
   script if it names one.

It's deliberately not `set -e`. Every step records its outcome and the failures
are summarized together at the end, so a too-tight allowlist can be fixed in
one round trip.
