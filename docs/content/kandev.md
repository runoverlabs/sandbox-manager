---
title: Kandev hosts
section: Guides
order: 57
description: Let the Kandev plugin run one microVM per agent session on this host, over ssh, with no daemon and no secret stored here.
---

[Kandev](https://github.com/kdlbs/kandev) runs each agent session in its own
environment. Its microsandbox plugin puts every session in a microVM on a
sandbox host: an ordinary msb-manager install, usually also a
[remote host](remote-hosts.md). The plugin drives the host the way your laptop
does, over ssh, through a forced command that admits the `msbctl kandev` verbs
and nothing else. There is no daemon on the host, and no port or token scheme
of its own.

Kandev's sandboxes are kept apart from yours:

- The kandev verbs find them only through registry entries with
  `source = "kandev"`, named `k-…`. No kandev verb can reach one of your
  sandboxes, whatever it's called, and new names of yours can't start with `k-`.
- Your own verbs may `ls`, `show`, `shell` and `exec` into one while it runs,
  and refuse everything else. Kandev starts its sandboxes, with secrets only its
  requests carry, and `msbctl kandev destroy ENV` removes one.
- None of msbctl's own credential setup applies to them: no bootstrap, no
  CLAUDE.md, no git identity or [git push](credentials.md#git-push-gh-or-ssh)
  rewrites, no ssh agent, no Claude token or `GH_TOKEN`. Kandev delivers agent
  and git credentials itself, through its agentctl.
- Profile secrets, registry passwords and agentctl's bootstrap nonce arrive on
  stdin. They go into the environment of one `msb` process, or the stdin of one
  `msb exec`, and are never written to a file, argv or a log. A host reboot
  leaves Kandev's sandboxes stopped, because their secrets exist nowhere on it;
  Kandev's next attach starts them again with the values.

## Setting a host up

1. Set the host up as a [remote host](remote-hosts.md) (`msbctl remote setup`
   from your laptop), or install msb-manager on it by hand.
2. Turn Kandev on and set its limits in the host's `~/.config/msb/config.toml`:

   ```toml title="~/.config/msb/config.toml"
   [kandev]
   enabled     = true
   base_url    = "https://sbx-01.tailnet.ts.net"
   allow_extra = ["pypi.org", "*.pythonhosted.org"]
   ```

   Every key is described in `defaults.toml` and [below](#the-kandev-section).
3. Let your user run `tailscale serve` (once, as root):
   `sudo tailscale set --operator=$USER`.
4. Authorize the plugin's public key, which the plugin's Sandbox Hosts page
   shows: `msbctl host authorize 'ssh-ed25519 AAAA… kandev' --kandev`.
5. Install the reaper: `msbctl host kandev install`. Lingering has to be on
   for it to run with nobody logged in; the command says so if it isn't.
6. In your tailnet's ACL, let only the Kandev server reach sandbox hosts on
   :443.

Then add the host on the plugin's Sandbox Hosts page; its test runs
`msbctl kandev health`.

## The `[kandev]` section

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Kandev may create sandboxes here only when true. Otherwise every verb but `health` answers `denied` |
| `max_sandboxes` | `12` | Kandev sandboxes that exist at once. Yours don't count |
| `max_cpus` | `32` | summed over them |
| `max_memory` | `"96G"` | summed over them |
| `port_pool` | `"20000-29999"` | host ports published on 127.0.0.1, four per sandbox |
| `base_url` | `""` | the HTTPS address Kandev reaches this host's sandboxes at |
| `serve` | `"tailscale"` | what serves `base_url`: `tailscale serve`, or `"none"` to route it yourself |
| `rule_groups` | `["github", "npm", "python", "claude"]` | egress every Kandev sandbox gets, after `base` |
| `allow_extra` | `[]` | hostname patterns a profile's extra egress may add. Empty allows nothing extra; `["*"]` trusts Kandev's profiles |

Nothing in a request can raise these limits or remove a base rule. Profiles add
egress only within `allow_extra`.

## How Kandev reaches a sandbox

Each sandbox publishes four guest ports on 127.0.0.1: agentctl's control port
(8765) and the three instance ports it is told to use (41001–41003). Previews
and the embedded editor travel inside those through agentctl's own proxy, so no
other port is ever needed.

With `serve = "tailscale"`, each one is mapped under `base_url` with `tailscale
serve --set-path=/vm/<name>/p/<port>`, using the node's own certificate. A
lease is that URL with a 10-minute expiry. There is no bearer token: reaching
:443 takes the tailnet ACL, and reaching agentctl takes Kandev's own token
from its nonce handshake.

The guest reaches Kandev's API through one rule naming the address the API host
resolved to **on the host**, and that name is written into the guest's
`/etc/hosts`. The address is usually a MagicDNS `100.x`, which DNS rebind
protection would otherwise discard in the guest. That protection stays on.
msb writes a fresh `/etc/hosts` on every boot, so `kandev start` writes the
line again.

## Private images

A request's `registry` credentials are used for one `msb pull`. The password is
in that process's environment. msb finds it through a throwaway copy of its
config, which names the variable and the username, never the value. The
sandbox is then created with `--pull never`, so the credential never becomes
part of its configuration. A private image must name its registry
(`ghcr.io/…`).

## The verbs

Each prints one JSON document on stdout. Exit 0 is success. Exit 3 comes with
`{"error": {"code": …, "message": …}}`, where `code` is one of Kandev's
(`invalid_config`, `denied`, `unsupported`, `not_found`, `expired`, `conflict`,
`unavailable`, `rate_limited` with `retry_after_seconds`, `cleanup_pending`).
Exit 126 is a refusal by `host serve`. Everything else msbctl prints goes to
stderr. `ENV` is Kandev's environment id, `[A-Za-z0-9_-]{1,128}`.

| Verb | Stdin | Does |
| --- | --- | --- |
| `health` | – | protocol (1), versions, KVM, capacity used and free, whether `tailscale serve` works |
| `list` | – | every Kandev sandbox: env, name, state, created, expires |
| `provision ENV` | a JSON line: image (digest-pinned), resources, `expires_at`, `kandev_api`, `egress_allow`, `env`, `secrets`, `registry` | creates the sandbox. The same operation and input again returns it; anything else under that ENV is `conflict` |
| `agentctl ENV` | a JSON line (`sha256`, `size`, `nonce`, `runtime_port`, `args`, `env`), then the binary | verifies, installs and starts Kandev's agentctl, and waits for it to answer |
| `inspect ENV` | – | the record, with agentctl checked live |
| `find --operation OP` | – | the record for a Kandev operation id |
| `start ENV` | a JSON line with exactly the secrets it binds | starts a stopped sandbox; bumps `generation` |
| `stop ENV` | – | stops it, keeping its disk |
| `expiry ENV --at TIME` | – | moves `expires_at`, never past the one it was created with |
| `lease ENV PORT` | – | `base_url`, `expires_at` and `generation` for one guest port |
| `destroy ENV` | – | removes the serve mappings, the VM and the entry. Always succeeds when there's nothing left |
| `reap` | – | one pass of the reaper, below |

The record `provision`, `inspect`, `find`, `start`, `stop` and `expiry` return
has the env and name, the operation and input digest, `state` (`creating`,
`running`, `stopped`, or `absent` when the VM is gone), platform, image,
timestamps, `generation`, the port map and agentctl's state. It never holds a
secret.

## The reaper

`msbctl kandev reap` runs every minute from the timer `host kandev install`
writes. It isn't a daemon: each run makes one pass and exits.

- A sandbox past its `expires_at` is destroyed.
- A create that never finished is destroyed after 15 minutes.
- An entry whose VM is gone is marked `absent`, and waits for Kandev's destroy
  or its expiry.
- A VM carrying the Kandev label with no entry, older than an hour, is removed.

It never touches a sandbox that lacks either the `kandev` source or the label.

## The plugin key

The line `host authorize --kandev` writes is
`restrict,command="…/msbctl host serve --kandev" <key>`, with no `pty`. That key
runs `msbctl kandev …` and `msbctl --version`, nothing else. Your laptop's
everyday key is refused every kandev verb, since one could create a sandbox with
any egress.

The Kandev key does set egress and secret bindings, which the everyday key may
never do. A Kandev profile is the policy for its own sandboxes, and the Kandev
server is yours to run. What bounds it is `[kandev]`, the reserved variable
names (`GH_TOKEN`, Claude's, `AGENTCTL_*`, `MSB_*` and the like), and the fact
that its verbs only ever see Kandev's sandboxes.
