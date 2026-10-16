---
title: Remote hosts
section: Guides
order: 55
description: Run sandboxes on another Linux machine, driven over ssh by a key that cannot read their secrets or change their policy.
---

A remote host is an ordinary msb-manager install on another Linux machine
with KVM. `msbctl` there behaves exactly as it does here, and you drive it over
ssh. Its sandboxes have no folder on your laptop: they are
[cloned from a repo](advanced.md#sandboxes-without-a-folder), and they keep
running, and start after a reboot, with the laptop switched off.

## What the setup protects against

The threat is code running **as you on the laptop**: an agent run outside any
sandbox, or a compromised dependency during local development. It can read
every file you can, use every key in your ssh-agent, and reuse any open ssh
connection. So the key the laptop uses every day must not be able to read a
token stored on the host, or point one at a host of its choosing, and a plain
shell does both (`cat ~/.config/msb/secrets/global.env`).

That key therefore gets a **forced command**, `msbctl host serve`: it runs
msbctl commands from an allowlist and nothing else, and it runs them with
`MSB_RESTRICTED=1`, so nothing it runs can approve a change to a sandbox's
egress rules or secret bindings, even at a prompt (code on the laptop can
answer a prompt as easily as you can). Policy changes are made on the host
itself, or with a second, admin key that the laptop's agent doesn't hold: a
FIDO2 `sk-` key, which needs a touch.

The restricted key can still *use* what it can reach: `exec` in a sandbox
whose GitHub token can push. That's inherent in a key that manages sandboxes,
and it's bounded by each token's scope, so give each sandbox a fine-grained,
per-repo, expiring token.

## Setting up a host

On the host, as a dedicated user with no sudo and a 0700 home (msb needs
`/dev/kvm` and nothing else):

```console
$ curl -fsSL https://github.com/microsandbox/microsandbox/releases/latest/download/install.sh | sh
$ curl -fsSL https://github.com/runoverlabs/sandbox-manager/releases/latest/download/get.sh | sh
$ msbctl host authorize "ssh-ed25519 AAAA... you@laptop"     # the laptop's everyday key
$ msbctl host authorize --admin "sk-ssh-ed25519@openssh.com AAAA... you@laptop"   # optional
$ msbctl host autostart install
$ msbctl host check
```

`host authorize` writes the `authorized_keys` line:

```text
restrict,pty,command="/home/msb/.local/bin/msbctl host serve" ssh-ed25519 AAAA... you@laptop
```

`--admin` writes the key without a forced command, and asks first unless it's
an `sk-` key, since a plain key in the laptop's agent is exactly what the
forced command is there to contain.

`host autostart install` writes a systemd user unit that runs
`msbctl start --autostart` at boot. A user unit runs with nobody logged in only
with lingering on, once, as root: `loginctl enable-linger msb`.

`host check` reports what it can see, as heuristics: whether the user can
become root, the modes of the home and secrets directories, core dumps, swap,
whether the disk holding the home sits on dm-crypt, whether every
`authorized_keys` line is restricted or an `sk-` key, lingering and the
autostart unit, and the `msb`, `msbctl` and `/dev/kvm` it finds. Full-disk
encryption is a prerequisite msb-manager can't provide; `host check` only says
whether it found one.

## Using it

From the laptop it's plain
ssh. Quote the command as one argument; the host's shell never sees it, `host
serve` splits it.

```console
$ ssh msb@host -- 'msbctl add --repo acme/webshop -y'
$ pass show github/webshop | ssh msb@host -- 'msbctl secret set webshop GH_TOKEN --stdin'
$ ssh msb@host -- 'msbctl start webshop'
$ ssh -t msb@host -- 'msbctl shell webshop'
$ ssh msb@host -- 'msbctl exec webshop -- claude-agent-acp'     # a clean stdio pipe
```

### What the restricted key may run

| Command | Allowed |
| --- | --- |
| `ls`, `status`, `show`, `config`, `start` (and `--autostart`), `stop`, `reclaim`, `shell`, `exec`, `update`, `resize`, `rebuild`, `purge`, `rename`, `--version` | yes |
| `self-update` | without `--version` (that is the way back to an older `host serve`) |
| `cache` | `ls`, `clear` |
| `observe` | `report`, `off` (`on` turns egress filtering off) |
| `secret` | `ls`, `set`, `rm` (`add` binds a value to a host) |
| `setup` | only `--claude-token NAME --stdin` |
| `add` | only `--repo` (a folder `add` mounts a host path) |
| `policy` | `show` |
| `host` | `check` |
| `allow`, `mount`, `port`, `keys`, `code`, `move`, `entry`, `edit`, the menu | no |

Every sandbox must be named: `.` and an omitted name mean the host's current
folder, which means nothing to the caller. `exec` and `shell` pass on only the
`msb exec` flags known to act inside the guest (`-e`, `-w`, `-u`, `-t`,
`--no-tty`, `--no-stdin`, `--timeout`, `--rlimit`, `-q`, `--stream`). A refusal
is one line on stderr, `msbctl host serve: refused: <reason>`, and exit
status 126. A `rebuild` whose repo policy changed refuses too: approve it on
the host with `msbctl policy <name> update`.
