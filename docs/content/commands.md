---
title: Commands
section: Reference
order: 10
description: Every msbctl subcommand, its arguments and options.
---

`msbctl --help` and `msbctl <command> --help` are always current. This page
explains them: each command's synopsis, what it does, and a table of its
options.

## Naming the sandbox

- **`name`**: optional. Inside a registered project folder it defaults to that
  folder's sandbox. Elsewhere, it's required.
- **`name…`**: optional and repeatable. None, or `.`, means the current
  folder's sandbox; several names act on each in turn, and every failure is
  reported, not just the first.
- **`name|.`**: required, because another argument follows it. `.` is the
  shorthand for the current folder's sandbox.

See [Everyday use](everyday.md#the-current-folder-names-the-sandbox) for the
rules behind this. A name like `sbx-01:webshop`, in any of those places, is a
sandbox on the [remote](remote-hosts.md) called `sbx-01`.

## Registering and inspecting

### `msbctl add`

```text
msbctl add [dir] [--remote HOST]
msbctl add --repo owner/name [--ref REF] [--name NAME] [--guest-path PATH]
           [--workspace-disk SIZE] [--identity NAME] [--claude-token NAME] [--autostart] [-y]
```

Register a project with the setup wizard. Nothing is started. A bare `dir`
resolves under your workspaces folder and is created if missing; a path
starting with `/`, `~`, `./` or `../` is taken as written. Without one it asks,
defaulting to the current directory. It also asks where the project appears
inside the sandbox: [`/work`, the host's own path, or a custom
one](folders.md#where-the-project-appears-in-the-sandbox). See
[Get started](quickstart.md#2-register-a-project).

With [remotes](remote-hosts.md#on-the-laptop) configured and no folder given,
it first asks where the sandbox should run: this machine or one of them. On a
remote it asks for the repo and the sandbox's name, then runs the host's own
`add --repo` over ssh for the rest, and offers to start it.

With `--repo`, there's no folder: the sandbox clones the GitHub repo into a
disk volume inside itself, and its policy is the repo's own `.msb/`, fetched at
the commit it resolves to now. It shows what the repo asks for (commit, rule
groups, rules, secret bindings, image) and asks before registering. At a
terminal it also asks for the sandbox's GitHub token, which a private repo
needs. Without a terminal, anything not given takes its default. See
[Sandboxes without a folder](repo-sandboxes.md).

| Option | Meaning |
| --- | --- |
| `--remote HOST` | register it on that remote instead of asking where; the rest of the arguments are run there |
| `--repo OWNER/NAME` | no folder: clone this GitHub repo (or URL) inside the sandbox |
| `--ref REF` | with `--repo`: a branch, tag or commit. Default: the default branch |
| `--name NAME` | with `--repo`: the sandbox's name. Default: the repo's |
| `--guest-path PATH` | with `--repo`: where the clone appears. Default: `/work` |
| `--workspace-disk SIZE` | with `--repo`: the clone's volume size, such as `20G`; fixed once created |
| `--identity NAME` | with `--repo`: an [`[identities]`](configuration.md#identitiesname) name |
| `--claude-token NAME` | with `--repo`: a stored Claude token's name |
| `--autostart` | with `--repo`: start it with the other [autostart](maintaining.md#autostart) sandboxes |
| `-y`, `--yes` | with `--repo`: register without asking |

### `msbctl ls`

```text
msbctl ls [--refresh] [--porcelain | --picker | --json]
```

One line per sandbox: name, state, project, pending updates, autostart.

| Option | Meaning |
| --- | --- |
| `--refresh` | check upstream versions first, instead of using the cache |
| `--porcelain` | tab-separated fields, for scripts |
| `--picker` | the format `msb-picker` reads |
| `--json` | one JSON document; see below |

`--json` prints `{"msbctl": version, "sandboxes": [...]}`, each with `name`,
`state`, `source`, `location`, `repo`, `ref`, `autostart` and `updates`. It
lists this machine's sandboxes only, which is what a laptop asks a remote for.
A [Kandev](kandev.md) sandbox's row also has `kandev`, its record.

With `--json`, `ls`, `show`, `stop` and `purge` print exactly one JSON
document on stdout, everything else going to stderr, and exit 0. On failure
they exit 3 with `{"error": {"code": …, "message": …}}`. The code is
`not_found` for a name with no sandbox under it, else `unavailable` (or, under
the Kandev key, `denied` and `conflict`).

### `msbctl status`

```text
msbctl status [--quick]
```

One block per sandbox, as shown beside the menu: state, RAM and CPU, identity,
image, folder. Then each remote's sandboxes, one line each, asked for as `ls`
asks.

| Option | Meaning |
| --- | --- |
| `--quick` | skip reading figures from inside each guest, and show the remotes from what `ls` last cached, with no ssh |

### `msbctl show`

```text
msbctl show [name] [--json]
```

Everything about one sandbox: resources, disks, extra folders, installed
versions, environment, every egress rule in the order it's emitted, published
ports with their clickable URL, and the identity, keys and secrets bound to it.
For a Kandev sandbox it's its record, with agentctl checked live.

| Option | Meaning |
| --- | --- |
| `--json` | the essentials as one JSON document, with a `port_urls` map of each port to its URL and `git_checkstat` (`null` where it does not apply). For each secret it says whether a value is **stored**, never what it is |

### `msbctl config`

```text
msbctl config
```

The merged configuration (`defaults.toml` plus your `config.toml`), with where
each value comes from.

### `msbctl doctor`

```text
msbctl doctor [--json]
```

Checks that this machine can run sandboxes, one line per check, with the fix
for anything that isn't right. It looks at `/dev/kvm` (and whether you can
open it), `msb` and its version against the ones msbctl is tested on, and
`msb doctor`'s own verdict. It also covers `git`, `fzf` and a stored
`GH_TOKEN`, free disk under msb's home, and the modes of the config and
secrets directories. For the registry, it checks that each entry loads, that
its project folder still exists, that an SSH agent is reachable when a sandbox
may use a key, and that msb has no sandbox no entry names. Last come
[`host check`](#msbctl-host)'s hygiene heuristics. It never asks anything and
changes nothing.

It exits 1 when a check **failed** (no KVM, no msb, under 2 GiB free, secrets
nothing can read) and 0 otherwise, including with warnings, so a script can
gate on it. A remote host's `host serve` allows it, and the Kandev plugin's
key may run `doctor --json`: for that key the report covers the host and
Kandev's own sandboxes only, and names none of the operator's.

| Option | Meaning |
| --- | --- |
| `--json` | print `{"checks": [{"id", "status", "message", "fix"}, …]}` with `status` one of `ok`, `warn` or `fail`, plus `ok`, `msbctl` and `restricted`, and nothing else |

### `msbctl entry`

```text
msbctl entry [name]
```

Open the sandbox's [registry entry](configuration.md#the-registry-entry)
(`~/.config/msb/sandboxes/<name>.toml`) in a terminal editor.

## Lifecycle

### `msbctl start`

```text
msbctl start [name…]
msbctl start --autostart
```

Start a stopped sandbox, or create it if it doesn't exist yet. Creating runs
the [bootstrap](how-it-works.md#the-bootstrap), once.

| Option | Meaning |
| --- | --- |
| `--autostart` | with no names: every sandbox whose registry entry says `autostart = true` and isn't running. The picker runs this when it opens, and so does the unit [`msbctl host autostart install`](#msbctl-host) writes |

### `msbctl stop`

```text
msbctl stop [name…] [--json]
```

Stop it. Everything is kept.

| Option | Meaning |
| --- | --- |
| `--json` | print `{"sandboxes": [...]}`, what `show --json` says of each afterwards |

### `msbctl rebuild`

```text
msbctl rebuild [name…]
```

Destroy and recreate. Needed after changing anything fixed at create time:
egress rules, mounts, the image, environment variables. Your files, the Claude
state, package caches and container images survive; packages installed by
hand don't. Doesn't ask first, unless the project's
[policy](egress.md#the-policy-pin) changed since it was approved.

### `msbctl purge`

```text
msbctl purge [name…] [-y] [--json]
```

Destroy the sandbox and deregister it: the VM, its Claude state, its disk
volumes, its secrets file and its registry entry. Your project folder is never
touched. It lists exactly what it will delete and asks once per sandbox.
Remember to revoke its GitHub token too. A name with nothing registered under
it isn't an error: it says "nothing found" and succeeds, so purging twice is
fine. A Kandev sandbox loses its VM and its entry; nothing else of msbctl's
exists for one.

| Option | Meaning |
| --- | --- |
| `-y`, `--yes` | don't ask |
| `--json` | with `-y`, since it can't ask: print `{"purged": [...], "absent": [...]}` |

### `msbctl rename`

```text
msbctl rename name|. new-name [-y]
```

Give a sandbox a new name. msb can't rename a VM, so this recreates it, like a
rebuild; settings, secrets, Claude state, caches and container images all move
with it. See [Maintaining a sandbox](maintaining.md#renaming-a-sandbox-or-moving-its-project).

| Option | Meaning |
| --- | --- |
| `-y`, `--yes` | don't ask |

### `msbctl move`

```text
msbctl move name|. dir [--rebuild]
```

Point a sandbox at another project folder. `dir` is read as it is for `add`.
Offers to copy `.msb/` across if the new folder lacks it, and re-detects the
GitHub repo. The folder is mounted at create time, so this needs a rebuild.

| Option | Meaning |
| --- | --- |
| `--rebuild` | rebuild now, so it takes effect |

### `msbctl resize`

```text
msbctl resize [name] [--cpus N] [--memory SIZE] [--root-disk SIZE] [-y]
```

Change resources and keep the sandbox's state. With no options it asks.

| Option | Meaning |
| --- | --- |
| `--cpus N` | needs a restart, which it asks for |
| `--memory SIZE` | such as `16G`; a ceiling, not a reservation. Needs a restart |
| `--root-disk SIZE` | grows live; shrinking is refused |
| `-y`, `--yes` | restart without asking |

### `msbctl reclaim`

```text
msbctl reclaim [name…]
```

Give the guest's page cache back to the host. Harmless, and takes about a
second.

## Working inside

### `msbctl shell`

```text
msbctl shell [name] [msb exec flags…]
```

An interactive login shell, with the SSH agent wired up, starting in the
subfolder of the project that matches your current directory (under `/work`,
or wherever [`guest_path`](folders.md#where-the-project-appears-in-the-sandbox)
puts it). Starts a stopped sandbox; never creates one. Flags after the name go
to `msb exec` as they are (see [Passing flags to `msb exec`](#passing-flags-to-msb-exec)).

### `msbctl exec`

```text
msbctl exec name|. [--] command…
msbctl exec [name|.] [msb exec flags…] -- command…
msbctl exec -- command…
```

Run one command in the sandbox, like `shell` but non-interactive. `exec -- cmd`
is the short form for the current folder's sandbox.

#### Passing flags to `msb exec`

`shell` and `exec` hand any flag they do not use themselves to `msb exec`
unchanged, so everything `msb exec --help` lists works. Put the flags after
the name, and for `exec` end them with `--`:

```text
$ msbctl shell -u root                      # this folder's sandbox, as root
$ msbctl exec myproject --timeout 5m -- make test
$ msbctl exec -e DEBUG=1 --no-tty -- ./run.sh
```

`-w`/`--workdir` replaces the matching subfolder of the project, and for `shell`,
`--no-tty` or `--stream` replaces the terminal it would otherwise allocate.

## Changing a sandbox

### `msbctl edit`

```text
msbctl edit [name]
```

The setup wizard as a menu of sections, run one at a time against an existing
sandbox: name and folder, features and agents, resources, package caches,
container storage, extra folders, published ports, egress rules, SSH keys,
git push, host editor (the `core.checkStat` fix), Claude token, models for pi,
GitHub token, secrets, identity and autostart, or the files themselves in your editor. "View the CLAUDE.md it
gets" shows the [instructions](instructions.md) its agent is given on the next
start. Applies what it can immediately and offers one rebuild at the end for
the rest.

### `msbctl allow`

```text
msbctl allow name|. [target…] [--from-observe [--with-dns]] [--rebuild|--no-rebuild]
```

Add egress rules to the project's `extra_rules`, and approve that change. Each
target is one of:

| Target | Allows |
| --- | --- |
| `host` | HTTPS, :443 |
| `host:port` | that TCP port |
| `host:udp:port` | that UDP port |
| `[fd00::5]:22` | an IPv6 address, in brackets |
| `allow@10.0.0.5:tcp:5432` | a full [rule](egress.md#the-rule-grammar), as written |

| Option | Meaning |
| --- | --- |
| `--from-observe` | also every host the [observation log](egress.md#finding-out-what-a-sandbox-needs) shows reached and no rule covers |
| `--with-dns` | with `--from-observe`: names seen only as a DNS lookup too, on 443 |
| `--rebuild` | rebuild now, so the rules take effect |
| `--no-rebuild` | don't rebuild, and don't ask |

With neither `--rebuild` nor `--no-rebuild`, it asks on a terminal; off one,
it never asks and doesn't rebuild. See [Adding a host](egress.md#adding-a-host).

### `msbctl policy`

```text
msbctl policy name|. [show|approve|update [REF]]
```

The project-layer values the [policy pin](egress.md#the-policy-pin) covers.

| Action | Does |
| --- | --- |
| `show` (default) | print them, whether they're the approved ones, and what changed since |
| `approve` | show the change and ask; needs a terminal |
| `update [REF]` | for a [sandbox without a folder](repo-sandboxes.md): fetch the repo's `.msb/` at the tip of its ref (or of `REF`, which becomes its ref), show what that commit changes, and swap it in once approved. A `rebuild` then applies it; the clone inside the sandbox isn't touched |

### `msbctl observe`

```text
msbctl observe name|. [report|on|off] [--rebuild] [-y] [--json]
```

[Observe mode](egress.md#finding-out-what-a-sandbox-needs): stop blocking for
a while and record where the sandbox goes.

| Action | Does |
| --- | --- |
| `report` (default) | read the record back, and print the `msbctl allow` line for what no rule covers |
| `on` | stop blocking and record every host the sandbox reaches; asks first |
| `off` | restore deny-by-default |

| Option | Meaning |
| --- | --- |
| `--rebuild` | rebuild now, so `on` or `off` takes effect |
| `-y`, `--yes` | turn it on without asking |
| `--json` | the report [as one document](egress.md#finding-out-what-a-sandbox-needs): hosts, ports, coverage, secret blocks |

### `msbctl mount`

```text
msbctl mount name|. SRC[:DEST][:ro|rw] [--rw] [--rebuild]
```

Add an [extra host folder](folders.md#extra-folders). `DEST` defaults to
`/mnt/<folder name>`. Needs a rebuild.

| Option | Meaning |
| --- | --- |
| `--rw` | read-write, the same as `:rw`. Default: read-only |
| `--rebuild` | rebuild now, so it takes effect |

### `msbctl port`

```text
msbctl port name|. [PORT|HOST:GUEST|BIND:HOST:GUEST[/udp]…] [--rm PORT] [--rebuild]
```

Publish a host port to a server inside the sandbox, so `http://localhost:PORT`
on this machine reaches it. A bare `PORT` is the same on both sides. With no
ports given it lists them, each tcp port's host side a clickable hyperlink to
its URL (on a terminal). Needs a rebuild. See [Reaching a server in the
sandbox](folders.md#reaching-a-server-in-the-sandbox).

| Option | Meaning |
| --- | --- |
| `--rm PORT` | stop publishing this one; repeatable |
| `--rebuild` | rebuild now, so it takes effect |

### `msbctl secret`

```text
msbctl secret add name|.
msbctl secret ls  name|.
msbctl secret rm  name|. VAR
msbctl secret set name|. VAR [--stdin] [--restart]
msbctl secret migrate --to keyring|file [--json]
```

Tokens the sandbox can use but never see.

| Action | Does |
| --- | --- |
| `add` | bind a new variable: offers the presets, or takes your own binding |
| `ls` | list the sandbox's extra bindings, and whether each has a value stored |
| `rm VAR` | unbind one; substitution stops at once |
| `set VAR` | store a new value for a variable the sandbox already binds (`GH_TOKEN`, or one of its `secret_binds`), from a hidden prompt. A running sandbox uses it from its next start |
| `migrate` | move every stored value, for every sandbox, into the desktop keyring or back into the files, and set `[secrets] store` to match |

| Option | Meaning |
| --- | --- |
| `--stdin` | `set`: read the value from standard input; one trailing newline is dropped |
| `--restart` | `set`: restart a running sandbox, so the value is used now |
| `--to keyring\|file` | `migrate`: where the values go |
| `--json` | `migrate`: print what moved as one JSON document, never a value |

See [Credentials & SSH](credentials.md#more-secrets),
[Scripting](credentials.md#scripting-storing-a-token-from-a-password-manager)
and [the keyring](credentials.md#keeping-the-values-in-the-keyring).

### `msbctl keys`

```text
msbctl keys [name] [--all]
```

Choose which keys from your SSH agent (and `~/.ssh`) the sandbox can list and
sign with. Takes effect immediately.

| Option | Meaning |
| --- | --- |
| `--all` | remove the restriction: every key |

### `msbctl cache`

```text
msbctl cache name|. [ls|clear] [key]
```

Show the [package-cache](toolchains.md#package-caches) disks (`ls`, the
default), or empty one with `clear key`, or all of them with `clear` alone.

### `msbctl update`

```text
msbctl update [name…] [-c component…]
```

Update components in place, without a rebuild. Versions installed this way are
recorded so a rebuild reproduces them. Run `msbctl ls --refresh` first for
`npm`, `gh`, `gitleaks` and `bun`.

| Option | Meaning |
| --- | --- |
| `-c`, `--components` | any of `claude` (the default), `pi`, `npm`, `gh`, `gitleaks`, `bun`, `apt`. `pi` also updates pi's packages, except a pinned one |

## The machine and msb-manager itself

### `msbctl setup`

```text
msbctl setup [--welcome]
msbctl setup --claude-token NAME [--stdin] [--default]
msbctl setup --identity KEY --git-name NAME --git-email EMAIL [--default]
```

Your machine-level settings as a menu: git identities, coding agents (the
`[defaults] agents` a new sandbox gets ticked), Claude login, model
endpoints (for [pi](models.md)), [agent tools](agent-tools.md), your network,
new-sandbox defaults, or the config file itself. The options skip the menu;
they're how `msbctl remote setup` copies your settings to a host, and through
a restricted key only `--claude-token NAME --stdin` is allowed.

| Option | Meaning |
| --- | --- |
| `--welcome` | the first-time walk-through |
| `--claude-token NAME` | store one Claude token under that name, from a hidden prompt. `main` is the default one |
| `--stdin` | with `--claude-token`: read it from standard input |
| `--identity KEY` | add or change a git identity, without a signing key |
| `--git-name NAME` | with `--identity`: the name commits carry |
| `--git-email EMAIL` | with `--identity`: the email commits carry |
| `--default` | with either: also make it the default for new sandboxes |

### `msbctl self-update`

```text
msbctl self-update [--version vX.Y.Z] [--json]
```

Upgrade a packaged install to the latest release, or a given one, verifying it
the same way the installer does. In a git checkout it tells you to `git pull`.
After a successful install it restarts the Kandev proxy's service if that is
running an older release, which cuts its open connections.

| Option | Meaning |
| --- | --- |
| `--version VERSION` | a specific release; `0.6.1` and `v0.6.1` name the same one. Under `host serve`, with either key, it may not name a release older than the running one |
| `--json` | print `{"msbctl_version", "updated", "proxy"}` once installed, with the installer's output on stderr |

### `msbctl completion`

```text
msbctl completion bash|zsh|fish
```

Print a Tab-completion script for your shell. It completes the verbs, their
flags and fixed choices (`observe . on`, `secret migrate --to keyring`), and the
sandbox names, including `HOST:name` for each remote's sandboxes. After `exec
NAME` (or past its `--`), the command is completed by your shell as if typed
alone; in bash that takes the bash-completion package, else it offers command
names and then files. Nothing is installed for you. Turn it on with one line:

```console
$ echo 'source <(msbctl completion bash)' >> ~/.bashrc
$ echo 'source <(msbctl completion zsh)' >> ~/.zshrc      # after compinit
$ msbctl completion fish > ~/.config/fish/completions/msbctl.fish
```

The names are looked up at each Tab from the registry and from what `msbctl ls`
last cached for each remote. A Tab never starts `msb` or ssh, so a remote shows
up once `ls` has listed it. The verbs and flags are fixed in the script when
it's printed. bash and zsh print it again at each new shell. A fish file is
written once, so write it again after an upgrade.

## Remote hosts

### `msbctl host`

```text
msbctl host serve [--kandev]
msbctl host authorize "PUBLIC KEY LINE" [--admin | --kandev] [--replace]
msbctl host check [--json]
msbctl host autostart install
msbctl host kandev install | reap | proxy | rotate-lease-key
msbctl host kandev configure [--[no-]enabled] [--serve MODE] [--proxy-listen IP]
                             [--base-url URL] [--allow-extra ENTRY …]
                             [--private-name HOST …] [--json]
```

For running this machine as a [remote host](remote-hosts.md). Under
`host serve`, only `check` is allowed.

| Action | Does |
| --- | --- |
| `serve` | the forced command a laptop's key runs: reads `SSH_ORIGINAL_COMMAND`, refuses anything outside [its allowlist](remote-hosts.md#what-the-restricted-key-may-run) with exit status 126, and runs the rest with `MSB_RESTRICTED=1` |
| `authorize` | add a key to `~/.ssh/authorized_keys` with that forced command. A key that's already there is refused |
| `check` | [`doctor`](#msbctl-doctor)'s report under its older name, in its older JSON shape (`check`, `ok`, `detail`). It always exits 0 |
| `autostart install` | write and enable a systemd user unit that runs `msbctl start --autostart` at boot |
| `kandev reap` | one pass of the [reaper](kandev.md#the-reaper) |
| `kandev proxy` | the [TLS proxy](kandev.md#the-tls-proxy) |
| `kandev rotate-lease-key` | replace the key its tokens are signed with, honouring the old one for 15 minutes |
| `kandev install` | write and enable a systemd user timer for the reaper and a service for the proxy, and restart the proxy |
| `kandev configure` | set the [`[kandev]` keys](kandev.md#setting-a-host-up) it is given in `config.toml`, keeping everything else, and only if the result is valid |

| Option | Meaning |
| --- | --- |
| `--admin` | `authorize`: no forced command. Use a FIDO2 `sk-` key |
| `--kandev` | `authorize`, `serve`: the [Kandev plugin's key](kandev.md#the-plugin-key). Its line runs `host serve --kandev`, which admits `msbctl kandev` verbs and `ls`, `show`, `stop`, `purge` and `self-update` with `--json`, seeing only Kandev's sandboxes. The everyday key runs no `kandev` verb |
| `--replace` | `authorize`: rewrite the key's existing line instead of refusing |
| `--json` | `check`, `kandev configure`: one JSON document |
| `--enabled`, `--no-enabled` | `kandev configure`: `[kandev] enabled` |
| `--serve MODE` | `kandev configure`: `proxy`, `tailscale` or `none` |
| `--proxy-listen IP` | `kandev configure`: the address the proxy binds |
| `--base-url URL` | `kandev configure`: `https://host[:port]` |
| `--allow-extra ENTRY` | `kandev configure`: the whole `allow_extra` list, one entry per flag; `''` alone empties it |
| `--private-name HOST` | `kandev configure`: the whole `private_names` list, one host per flag; `''` alone empties it |

### `msbctl kandev`

```text
msbctl kandev health
msbctl kandev provision|agentctl|start ENV
msbctl kandev expiry ENV --at TIME
msbctl kandev lease ENV PORT
msbctl kandev tls install
msbctl kandev restart-proxy
```

What the Kandev plugin runs over ssh to keep [Kandev's sandboxes](kandev.md)
on this host. Each prints one JSON document on stdout and exits 0, or 3 with
`{"error": {"code", "message"}}`; secrets, the agentctl binary and its nonce,
and the certificate and key for `tls install` come on stdin. Off until
`[kandev] enabled = true`. [Every verb](kandev.md#the-verbs) is described on
the Kandev hosts page. Only what needs Kandev's own input is here: the plugin
lists, inspects, stops and removes Kandev's sandboxes with `ls`, `show`, `stop`
and `purge` and `--json`, and the reaper and the TLS proxy are
[`host kandev reap|proxy`](#msbctl-host).

| Option | Meaning |
| --- | --- |
| `--at TIME` | `expiry`: the new `expires_at`, RFC 3339 |

### `msbctl remote`

```text
msbctl remote add NAME user@host
msbctl remote setup NAME
msbctl remote ls
msbctl remote test NAME
msbctl remote rm NAME
```

The other machines this one drives; the menu's **remote hosts** does the same.
Once one is added, `NAME:sandbox` addresses a sandbox there for every verb, and
`ls` shows every host. See [Remote hosts](remote-hosts.md#on-the-laptop).

| Action | Does |
| --- | --- |
| `add` | record `[remotes.NAME]` in `config.toml`. At a terminal it then runs `setup`; otherwise it prints the `msbctl host authorize` line to run there and tests the connection |
| `setup` | look at the host over ssh and offer, one question each, what's missing: msb and msbctl at this machine's versions, the kvm group, autostart, your git identities, Claude tokens (sent on stdin), and last restricting this machine's key to `host serve` (with a warning first when that key is the one with a shell there). Then it tests |
| `ls` | list them |
| `test` | run the host's [`doctor`](#msbctl-doctor) (`host check` on a host whose msbctl predates it), show each check, and warn about a failed one, an unrestricted key or a version mismatch |
| `rm` | forget it; the host isn't touched |

## Environment variables

| Variable | Effect |
| --- | --- |
| `MSB_CONFIG_DIR` | config directory (default `~/.config/msb`) |
| `MSB_STATE_DIR` | state directory (default `~/.local/state/msb`) |
| `MSB_NO_AUTOSTART=1` | the picker doesn't start autostart sandboxes |
| `MSB_MANAGER_SKIP_ATTEST=1` | installer and `self-update`: skip the provenance check |
| `MSB_MANAGER_REPO`, `MSB_MANAGER_BASE_URL` | installer: another repository, or a mirror (`file://` works; needs `--version`) |
