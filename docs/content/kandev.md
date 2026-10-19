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
and nothing else. The only thing listening on the host is a small TLS proxy
that carries Kandev's connections to a sandbox's ports, each one checked for a
short-lived lease token.

Kandev's sandboxes are kept apart from yours:

- The plugin finds them only through registry entries with
  `source = "kandev"`, named `k-…`. Nothing its key runs can reach one of your
  sandboxes, whatever it's called, and new names of yours can't start with `k-`.
- Your own verbs may `ls`, `show`, `shell` and `exec` into one while it runs,
  and, on the host itself, `stop` and `purge` it. They refuse everything else,
  and your laptop's key can't stop or purge one. Kandev starts its sandboxes,
  with secrets only its requests carry.
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
   enabled      = true
   base_url     = "https://sbx-01.tailnet.example"
   proxy_listen = "100.64.0.7"
   allow_extra  = ["pypi.org", "*.pythonhosted.org"]
   ```

   `base_url` names this host as the Kandev server will reach it, and
   `proxy_listen` is its address on that network (a tailnet or LAN IP). Every
   key is described in `defaults.toml` and [below](#the-kandev-section).
3. Authorize the plugin's public key, which the plugin's Sandbox Hosts page
   shows: `msbctl host authorize 'ssh-ed25519 AAAA… kandev' --kandev`.
4. Install the reaper and the TLS proxy: `msbctl host kandev install`.
   Lingering has to be on for them to run with nobody logged in; the command
   says so if it isn't.
5. Let only the Kandev server reach `proxy_listen` on `proxy_port_pool`
   (30000–39999), with your tailnet's ACL or a firewall.

Then add the host on the plugin's Sandbox Hosts page. Its test runs
`msbctl kandev health`, and the plugin then issues the host a certificate and
installs it with [`kandev tls install`](#the-tls-proxy). `health` reports
`serve.ok` once the proxy runs with it.

## The `[kandev]` section

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Kandev may create sandboxes here only when true. Otherwise every verb but `health` answers `denied` |
| `max_sandboxes` | `12` | Kandev sandboxes that exist at once. Yours don't count |
| `max_cpus` | `32` | summed over them |
| `max_memory` | `"96G"` | summed over them |
| `port_pool` | `"20000-29999"` | host ports published on 127.0.0.1, four per sandbox |
| `base_url` | `""` | the HTTPS address Kandev reaches this host's sandboxes at. With `serve = "proxy"`, only its host name counts, and the certificate must name it |
| `serve` | `"proxy"` | what serves `base_url`: the [TLS proxy](#the-tls-proxy), `"tailscale"` for `tailscale serve`, or `"none"` to route it yourself. A change applies to new sandboxes |
| `proxy_listen` | `""` | the address the proxy's ports bind: this host's tailnet or LAN IP. Required for `"proxy"` |
| `proxy_port_pool` | `"30000-39999"` | the proxy's public TLS ports, four per sandbox. Must not overlap `port_pool` |
| `rule_groups` | `["github", "npm", "python", "claude"]` | egress every Kandev sandbox gets, after `base` |
| `allow_extra` | `[]` | hostname patterns a profile's extra egress may add. Empty allows nothing extra; `["*"]` trusts Kandev's profiles |

Nothing in a request can raise these limits or remove a base rule. Profiles add
egress only within `allow_extra`.

## How Kandev reaches a sandbox

Each sandbox publishes four guest ports on 127.0.0.1: agentctl's control port
(8765) and the three instance ports it is told to use (41001–41003). Previews
and the embedded editor travel inside those through agentctl's own proxy, so no
other port is ever needed.

With `serve = "proxy"`, the default, each of the four also gets a public TLS
port on `proxy_listen`, and a lease is `https://<base_url's host>:<that port>`
with a token for its `X-Msb-Lease` header, reported to expire in 10 minutes (see
[the TLS proxy](#the-tls-proxy)). Kandev talks to this host directly, and needs
no Tailscale: headscale, WireGuard or a LAN work as well.

With `serve = "tailscale"`, each one is mapped under `base_url` with `tailscale
serve --set-path=/vm/<name>/p/<port>`, using the node's own certificate. Only
Tailscale's hosted control plane issues those: on headscale, `health` reports
`serve.ok = false`. Grant your user serve rights once, as root: `sudo tailscale
set --operator=$USER`. A lease is that URL with a 10-minute expiry, and has no
token: reaching :443 takes the tailnet ACL, and reaching agentctl takes Kandev's
own token from its nonce handshake.

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

`msbctl kandev` holds only what needs Kandev's own input. For the rest, the
plugin uses the ordinary verbs with `--json`, which under its key see Kandev's
sandboxes and nothing else (any other name is `not_found`, or `absent` for
`purge`):

| Plugin needs | Runs | Gets |
| --- | --- | --- |
| the list | `ls --json` | `sandboxes`, each with `kandev`, the record (its `operation_id` is how the plugin finds a lost provision) |
| one record | `show NAME --json` | `kandev`, the record, with agentctl checked live; `not_found` with no such sandbox |
| to stop one | `stop NAME --json` | `sandboxes`: what `show` says afterwards. Its disk is kept; a stopped one is a no-op |
| to remove one | `purge NAME -y --json` | `{"purged": [...], "absent": [...]}`. Serve mappings, VM and entry go; nothing there is a success too. A VM under that name without the Kandev label is `conflict`, and left alone |

`NAME` is the `name` every record carries, which the plugin stores and never
derives. Each `kandev` verb, and each of these, prints one JSON document on
stdout. Exit 0 is success. Exit 3 comes with
`{"error": {"code": …, "message": …}}`, where `code` is one of Kandev's
(`invalid_config`, `denied`, `unsupported`, `not_found`, `expired`, `conflict`,
`unavailable`, `rate_limited` with `retry_after_seconds`, `cleanup_pending`).
Exit 126 is a refusal by `host serve`. Everything else msbctl prints goes to
stderr. `ENV` is Kandev's environment id, `[A-Za-z0-9_-]{1,128}`.

| Verb | Stdin | Does |
| --- | --- | --- |
| `health` | – | protocol (1), versions, KVM, capacity used and free, whether `serve` works and why not (`mode`, `listen`, `running`, `reason`), and the installed certificate (`tls`: `subject`, `not_after`, `issuer_sha256`) |
| `provision ENV` | a JSON line: image (digest-pinned), resources, `expires_at`, `kandev_api`, `egress_allow`, `env`, `secrets`, `registry` | creates the sandbox. The same operation and input again returns it; anything else under that ENV is `conflict` |
| `agentctl ENV` | a JSON line (`sha256`, `size`, `nonce`, `runtime_port`, `args`, `env`), then the binary | verifies, installs and starts Kandev's agentctl, and waits for it to answer |
| `start ENV` | a JSON line with exactly the secrets it binds | starts a stopped sandbox; bumps `generation` |
| `expiry ENV --at TIME` | – | moves `expires_at`, never past the one it was created with |
| `lease ENV PORT` | – | `base_url`, `expires_at` and `generation` for one guest port, plus `headers` with its token through the proxy |
| `tls install` | a JSON line: `cert_pem` (the leaf, then its issuer), `key_pem` | checks and stores the proxy's certificate, and prints `{"tls": …}` as `health` does |

The record `provision`, `start` and `expiry` return, and `ls`/`show` give as `kandev`,
has the env and name, the operation and input digest, `state` (`creating`,
`running`, `stopped`, or `absent` when the VM is gone), platform, image,
timestamps, `generation`, the port map and agentctl's state. It never holds a
secret.

## The TLS proxy

`msbctl host kandev proxy` is the one long-running piece, a systemd user service
written by `host kandev install`. With `serve = "proxy"` it listens on
`proxy_listen`, one TLS port per published guest port. For each connection it
completes the handshake, reads the first request head (16 KiB, 10 s at most)
and checks the token in its one `X-Msb-Lease` header. A missing token, two of
them, or one for another sandbox, another port or an earlier provision of the
same name gets a fixed `401`, and the connection closes. A valid one is spliced
to that port's `127.0.0.1` port, and from then on bytes pass both ways
untouched until either side closes, so WebSockets and streaming need nothing
special. `Authorization` is never looked at: it carries Kandev's own token for
agentctl, and reaches the guest as it was sent (which is also why the lease
can't use it: Kandev refuses a lease that sets it). There is no path routing:
one port per lease means a connection can only ever reach one VM port.

- **The certificate** comes from the Kandev plugin, which acts as a small
  certificate authority: a root name-constrained to your hosts' domain,
  trusted on the Kandev server only. `kandev tls install` takes the pair on
  stdin and checks it whole before writing anything: the key matches the leaf,
  the leaf is valid now and names `base_url`'s host, and the certificate after
  it issued it. The pair is stored in `~/.config/msb/kandev/tls/` (the key
  0600), and the proxy picks a new one up without a restart. Until one is
  installed it listens on nothing, and `health` says why. `health.tls` gives
  `not_after`, which drives the plugin's renewal, and `issuer_sha256`, the
  SHA-256 of the issuing certificate, so the plugin can tell a certificate from
  an old root.
- **Tokens** are `v1.<valid_until>.<HMAC-SHA256>` over the sandbox's name, the
  guest port, its incarnation (its `created_at` and a value drawn at
  provision) and `valid_until`, keyed by 32 random bytes in
  `~/.local/state/msb/kandev/lease.key`. `lease` and the proxy share nothing
  else, so a proxy restart invalidates no lease. A lease reports `expires_at`
  10 minutes out, but its token is accepted until `valid_until`, 15 minutes
  out, plus 30 s of clock skew: Kandev asks for a new lease only 30 s before
  `expires_at`, and keeps using the one it has until then, whatever it's
  answered. For the same reason a token survives a stop and start (they bump
  `generation`, not the incarnation); only a destroy and a new provision
  retire it.
- **Rotating the key:** `msbctl host kandev rotate-lease-key` makes a new one
  and keeps the old one as `lease.key.prev`, still accepted for 15 minutes,
  so no lease already handed out breaks. Rotate at most every 15 minutes.
- **What it follows:** the Kandev entries. It looks every 2 seconds, so a new
  sandbox's ports open within that. A destroyed sandbox's ports close, and
  their open connections are cut. It also re-reads the entry on every
  connection, so a destroyed sandbox refuses at once.
- **What it logs:** the sandbox, the guest port and the outcome, one line per
  connection, in the service's journal. Never a token, a request head or
  anything that passes through.

## The reaper

`msbctl host kandev reap` runs every minute from the timer `host kandev install`
writes. It isn't a daemon: each run makes one pass and exits.

- A sandbox past its `expires_at` is destroyed.
- A create that never finished is destroyed after 15 minutes.
- An entry whose VM is gone is marked `absent`, and waits for Kandev's purge
  or its expiry.
- A VM carrying the Kandev label with no entry, older than an hour, is removed.

It never touches a sandbox that lacks either the `kandev` source or the label.

## The plugin key

The line `host authorize --kandev` writes is
`restrict,command="…/msbctl host serve --kandev" <key>`, with no `pty`. That key
runs `msbctl kandev …`, `ls`, `show`, `stop` and `purge -y` with `--json` on
one named sandbox, and `msbctl --version`. Nothing else, and none of `host`:
the reaper and the proxy are this host's own. Your laptop's everyday key is
refused every `kandev` verb, since one could create a sandbox with any egress.

The Kandev key does set egress and secret bindings, which the everyday key may
never do. A Kandev profile is the policy for its own sandboxes, and the Kandev
server is yours to run. What bounds it is `[kandev]`, the reserved variable
names (`GH_TOKEN`, Claude's, `AGENTCTL_*`, `MSB_*` and the like), and the fact
that its verbs only ever see Kandev's sandboxes.
