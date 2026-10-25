---
title: Network & egress
section: Guides
order: 20
description: Rule groups, the rule grammar, the three properties that are easy to get backwards, and adding hosts.
---

Every sandbox is **deny-by-default**. A connection gets out only if a rule
allows it, and the rules are built from named groups that each project picks.

## Rule groups

A group is a named list of rules. msb-manager ships these in `defaults.toml`:

| Group | Allows |
| --- | --- |
| `base` | DNS, the Ubuntu mirrors over HTTPS, and a **deny** of plain HTTP. Always applied, always first |
| `github` | github.com (HTTPS and SSH), the API, release assets, raw content, Actions logs, attestation verification |
| `claude` | `api.anthropic.com` and `platform.claude.com`. Claude Code needs both |
| `npm` | the npm registry and NodeSource |
| `bun` | the GitHub release assets bun is installed from |
| `python` | PyPI |
| `rust` | crates.io |
| `go` | the Go module proxy and checksum database |
| `containers` | Docker Hub (all three hosts it needs), ghcr.io, codeberg.org |
| `playwright` | Playwright's browser downloads (the `browsers` feature) |

New sandboxes start with `github` and `claude`, and the wizard adds whatever
the chosen features need. A project lists its groups in `.msb/sandbox.toml`:

```toml title=".msb/sandbox.toml"
rule_groups = ["github", "claude", "npm"]
extra_rules = ["allow@mirror.example.com:tcp:443"]   # one-offs, emitted last
```

Your own groups go in `~/.config/msb/config.toml` (`msbctl setup` → "your
network" writes them for you):

```toml title="~/.config/msb/config.toml"
[rules]
# By address and port: precise, and safe to use for SSH.
my-servers = [
    "allow@10.0.0.10:tcp:22",
]
# By name over HTTPS. A suffix doesn't cover the apex, so list both.
my-services = [
    "allow@*.example.com:tcp:443",
    "allow@example.com:tcp:443",
]
```

## The rule grammar

```text
<action>[:<direction>]@<target>[:<proto>[:<ports>]]

allow@github.com:tcp:443          a hostname, HTTPS
allow@10.0.0.10:tcp:22            an address and one port
deny@public:tcp:80                a class of addresses
allow@dns                         DNS itself
```

## Three properties that are easy to get backwards

### Rules are first-match-wins

A leading deny can't be undone by appending an allow later. That's why `base`
is always emitted first, and why nothing a project writes can come before it.
In particular, **a plaintext :80 allow can't be added from a project**: the
`base` deny has already matched by the time the project's rule is considered.
Fix it with the `https://` URL; that almost always works.

### A hostname rule only means a hostname over HTTPS

On :443, msb's TLS interception reads the server name (SNI) from each
connection, so a name backed by a pool of addresses is fine. On any other port
nothing inspects the traffic, and the rule is enforced as *the addresses that
name resolved to*, which breaks against address pools. Prefer HTTPS everywhere.
For SSH, prefer a rule by address.

### DNS resolution is part of the rule

msb allows a connection based on the addresses *it* resolved from the allowed
names. A name it can't resolve fails exactly like a name you never allowed:
NXDOMAIN inside the guest, then a refused connection.

This bites on home and office networks. A name like `git.example.com` can be a
real public record pointing at `192.168.x.x`, and msb drops such answers as DNS
rebind protection. The fix is per project:

```toml title=".msb/sandbox.toml"
allow_private_dns = true
```

A group you list under `private_dns_groups` in your config gets this set
automatically by `msbctl add` and `msbctl edit`.

## Adding a host

When a connection is refused, treat it as policy first, not an outage. Then
add exactly the host and port that was refused:

```console
$ msbctl allow . registry.example.com          # HTTPS (:443)
$ msbctl allow . git.example.com:22            # a TCP port
$ msbctl allow . allow@10.0.0.5:tcp:5432       # a full rule
$ msbctl allow . pypi.example.com --rebuild    # and apply it now
```

`allow` appends to `extra_rules` in the project's `.msb/sandbox.toml` (or in
the registry entry, if that already overrides the list), and approves the
change (see [the policy pin](#the-policy-pin)). Rules are fixed at create time,
so they take effect at the next `msbctl rebuild`.

If more than one project needs the same host, make it a group in your
`config.toml` instead and give it to each sandbox with `msbctl edit` →
"Features & agents". A group only your machine defines is written to the
sandbox's registry entry (`extra_rule_groups`), not to the project, so it
never reaches anyone who clones it; see [Hosts on your network](#hosts-on-your-network).

## Hosts on your network

For hosts on your LAN (a Git server, a package mirror), define a group once in
`config.toml`, or use `msbctl setup` → "your network". If those names resolve
to private addresses, list the group under `private_dns_groups`, so sandboxes
that use it get `allow_private_dns` automatically.

A group of your own stays on your machine. `msbctl add` and `msbctl edit` →
"Features & agents" put it in the sandbox's registry entry as
`extra_rule_groups`, which adds to the project's `rule_groups`, rather than
in the project's committed `.msb/sandbox.toml`: nobody who clones the project
has that group, and in their copy it would make every create fail with
"unknown rule group". A shipped group you redefined keeps its name everywhere,
so it stays in the project. If an older msbctl put one of yours in the
project, `msbctl show` warns, and `msbctl edit` → "Features & agents" moves
it. Machine-local groups aren't part of the [policy pin](egress.md#the-policy-pin). See
[DNS resolution is part of the rule](egress.md#dns-resolution-is-part-of-the-rule).

## The policy pin

The project's `.msb/sandbox.toml` is committed, and the project folder is
writable from inside the sandbox, so code running in there could add its own
`allow@` rule or a secret binding and wait for the next rebuild. msbctl
doesn't apply what that file says just because it says it. Its egress rules,
secret bindings and resources are recorded when you approve them, and a
create or rebuild that finds them changed shows the difference first:

```console
$ msbctl rebuild .
== web: the project's policy changed since it was approved
     from ~/workspaces/web/.msb/sandbox.toml, before create:
       extra_rules:
     +   allow@paste.example:tcp:443
   approve this policy for web? [y/N]
```

Answer no and nothing changes. Without a terminal (a script, a cron job) it
refuses outright, saying to run `msbctl policy <name> approve`, and the
sandbox is left as it was: the check runs before a rebuild removes anything.
`msbctl allow`, `msbctl secret` and `msbctl edit` approve what *you* change
through them, after asking about any change that was already waiting, so a
pending edit from someone else is never approved along with yours. One that
lands while they wait on you (a menu, a pasted secret) is shown and asked
about as you leave, and so is a change you make in your editor; msbctl only
approves unasked what it wrote itself. Any text in the difference that could
move the cursor or recolour the terminal is shown escaped (`"\u001b[1A"`),
so a line can't be hidden from the screen you're approving. A policy
`msbctl add` wrote for you is approved when it's written; one it found in a
cloned repo is shown at the first start.

Inside the sandbox, `.msb/` is also mounted read-only over the project, so an
edit fails straight away with "Read-only file system". That's a tripwire, not
the control: root in the guest can unmount it. The pin is what stops the
change from being applied.

See [which keys are pinned](configuration.md#the-policy-pin).

## Finding out what a sandbox needs

msb **never logs what it denied**, at any log level. It does log what it
allows. So the only way to learn what a sandbox needs is to stop blocking for a
while and write down where it goes. That's **observe mode**:

```console
$ msbctl observe . on --rebuild       # stop blocking, start recording
$ #  … use the sandbox normally for a while …
$ msbctl observe .                    # every host it reached, and which no rule covers
$ msbctl allow . <the ones that belong>   # or --from-observe: all of them
$ msbctl observe . off --rebuild      # back to deny-by-default
```

While observe mode is on, the sandbox is created with egress allowed by
default, **no** `--net-rule` at all, debug logging and DNS rebind protection
off: nothing is blocked and every host is written to the sandbox's runtime
log. Your rules stay in the config and keep being curated; they're just not
emitted. The report prints a ready-made `msbctl allow` line for whatever no
rule covers.

The mode lives in the sandbox's **registry entry only**, set by
`msbctl observe`, never in `.msb/sandbox.toml`. That file is committed, and an
unfiltered sandbox must never ship to everyone who clones the project. It's
also writable from inside the sandbox, which must not be able to switch its
own filtering off, so an `egress_mode` written there is ignored with a warning.

The report also shows **secret-policy blocks**: requests msb killed because
they carried a placeholder somewhere substitution isn't allowed. Those are
logged even in normal (enforce) mode.

> **Warning:** In observe mode nothing is blocked. Secrets stay protected
> (substitution still happens on the host and only to their named hosts), but
> the agent can reach anywhere. Turn it off as soon as you've collected what
> you need.

The whole loop runs without a terminal, so a script or an agent outside the
sandbox can drive it:

```console
$ msbctl observe . on -y --rebuild
$ #  … run the workload …
$ msbctl observe . --json                     # what was reached, and what covers it
$ msbctl allow . --from-observe --rebuild     # every uncovered host, one write
$ msbctl observe . off --rebuild
```

`--from-observe` takes the hosts seen over TLS, each on the port it was seen
on. A name seen only as a DNS lookup carries no port, so it's skipped unless
you add `--with-dns`, which allows it on 443. It also skips a name an earlier
`deny` rule decides (an added rule can't come before it), plaintext `:80`, and
anything that isn't a plain DNS name: the log's names are whatever the guest
put in its requests, and a target like `public` would allow far more than one
host. That's also why the result is worth a look before it's committed. It's
what the sandbox reached, not what it ought to reach.

Coverage is judged by name only. A rule on an address, a CIDR, `public` or
`private` can't be matched against a name without resolving it the way the
guest would, so it's treated as not deciding anything. A host allowed that way
gets a redundant rule, which does no harm. A host denied that way, by
`deny@public` say, gets an allow appended after the deny, and the deny still
wins, so first take out the rule that blocks it.

`observe --json` prints one document: `hosts` (each with `host`, `port`,
`null` when seen only in DNS, `seen` as `"tls"` or `"dns"`, `hits`, `first`,
`last`, `allowed`, and the `rule` that decides it), `secret_blocks`, `logs` and
`egress_mode`. Like the other `--json` verbs, it exits 3 with `{"error": …}` on
failure.
