# What msb can and cannot change on an existing sandbox

Verified on msb 0.7.6, re-checked on 0.7.7 (`msb --help` is more reliable than
its published docs). This is the table to consult before deciding whether a
setting needs a rebuild — the answer is not intuitive and a wrong guess costs
a rebuild cycle you could have planned for.

| Setting | `msb modify` | Takes effect | msbctl path |
|---|---|---|---|
| cpus | yes | after restart | `resize`, `edit` → Resources |
| memory | yes | after restart | `resize`, `edit` → Resources |
| root disk | yes, **grow only** | live | `resize`, `pick_disks()` |
| env | yes | after restart | `modify -e` |
| secrets | yes | add on next start, removal live | `secret set/add/rm`, `bind_secret_live()` |
| network rules | **no** | rebuild | `allow`, `edit` → Egress |
| TLS interception | **no** | rebuild | emitted at create with the rules |
| DNS rebind protection | **no** | rebuild | `allow_private_dns` |
| mounts (dir, named, owned) | **no** | rebuild | `mount`, `edit` → Extra folders |
| published ports | **no** (`modify` has no port option in the 0.7.7 source) | rebuild | `port` |
| owned / named disks | **no** | rebuild | `pick_caches()`, `pick_disks()` |
| image | **no** | rebuild | `dev.yaml` `image:` + `rebuild` |

`msb modify` keeps the sandbox's state, which is why `resize` and `secret` can
use it and everything else cannot. **CLI flags override `--conf`.**

## Passing secrets to `modify`

Always pass `box.secret_env()` when applying `modify`: on 0.7.6 the call fails
if any bound secret's host-side variable is unset. Re-enabling interception
after it was lost also goes through `modify --secret`.

## Disks

- `--mount-owned DEST:kind=disk,size=…` — deleted with its sandbox.
- `--mount-named NAME:DEST:kind=disk,size=…` — a volume that **outlives** the
  sandbox, so a rebuild keeps it. The guest path must contain **no dot**
  ("invalid or reserved device id" otherwise, on both versions): `/d` and
  `/mnt/cache/npm` work, `/root/.npm` fails. That is why caches mount at
  `/mnt/cache/<key>` and bootstrap symlinks the tool's dotted directory to it.
- A volume's size is fixed at creation and `create` fails if the requested
  size differs, so `named_disk_flags()` keeps the existing capacity rather than
  restating it.
- `msb volume rm` refuses an attached volume.
- A directory mount with `quota=` also works, but it is a virtiofs share:
  roughly 12–20x slower for tiny files. Node `node_modules` is nothing but
  tiny files.

## Snapshots: close, but not built

A full snapshot restored with `msb restore --disk-only` *can* change network
rules and mounts **and keep state** — the one route around create-time-only
networking. But it drops TLS interception (re-enable via `modify --secret`),
drops env (re-add with `modify -e`), and resets DNS rebind protection **with no
way back**. msbctl does not build on this. Do not reach for it as a
no-rebuild path without re-verifying all three.

Forking a sandbox with a host mount does **not** give an isolated workspace:
unmapped paths give EIO, remapped ones give ESTALE.

## What msb logs

| Event | Logged? |
|---|---|
| intercepted HTTPS connection | `TLS intercept sni=<host> dst=<ip:port>`, at `--log-level debug` |
| a name resolved | a `dns::` line, debug |
| **an egress denial** | **never, at any level** — checked on 0.7.7 at `--debug` and `--trace` |
| a plain TCP connect on a non-443 port | nothing |

So on :443 you can reconstruct where a sandbox went, and off :443 a DNS lookup
is the only evidence. Combined with "denials are never logged", the only way
to learn what a sandbox needs is to stop blocking and record: `egress_mode =
"observe"`, then `msbctl observe <name>`.

Location: `~/.microsandbox/sandboxes/<name>/logs/runtime.log`. Secret
placeholder blocks (see the passthrough note in `SKILL.md`) are logged at
**WARN**, so they appear in enforce mode too — `msbctl observe` reports them.
