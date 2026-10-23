---
title: Commands
section: Reference
order: 10
description: Every msbctl subcommand, its arguments and options.
---

`msbctl --help` and `msbctl <command> --help` are always current. This page
explains them.

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
msbctl add [dir]
msbctl add --repo owner/name [--ref REF] [--name NAME] [--guest-path PATH]
           [--workspace-disk SIZE] [--identity NAME] [--claude-token NAME] [--autostart] [-y]
```

Register a project with the setup wizard. Nothing is started. With
[remotes](remote-hosts.md#on-the-laptop) configured and no folder given, it
first asks where the sandbox should run: this machine or one of them. On a
remote it asks for the repo and the sandbox's name, then runs the host's own
`add --repo` over ssh for the rest, and offers to start it. `--remote HOST`
skips the question: the rest of the arguments are run there. A bare name
resolves under your workspaces folder and is created if missing; a path
starting with `/`, `~`, `./` or `../` is taken as written. Without an argument
it asks, defaulting to the current directory. It also asks where the project
appears inside the sandbox: [`/work`, the host's own path, or a custom
one](advanced.md#where-the-project-appears-in-the-sandbox). See
[Get started](quickstart.md#2-register-a-project).

With `--repo`, there's no folder: the sandbox clones the GitHub repo into a
disk volume inside itself, and its policy is the repo's own `.msb/`, fetched at
the commit it resolves to now. The flags answer what it would otherwise ask;
without a terminal, anything not given takes its default (`/work`, the default
branch, the repo's name). It shows what the repo asks for (commit, rule groups,
rules, secret bindings, image) and asks before registering, unless `-y`. At a
terminal it also asks for the sandbox's GitHub token, which a private repo
needs. See [Sandboxes without a folder](advanced.md#sandboxes-without-a-folder).

### `msbctl ls`

```text
msbctl ls [--refresh] [--porcelain] [--picker] [--json]
```

One line per sandbox: name, state, project, pending updates, autostart.
`--refresh` checks upstream versions first. `--porcelain` prints tab-separated
fields for scripts; `--picker` is the format `msb-picker` reads. `--json` prints
one JSON document, `{"msbctl": version, "sandboxes": [...]}`, each with
`name`, `state`, `source`, `location`, `repo`, `ref`, `autostart` and
`updates`: this machine's sandboxes only, which is what a laptop asks a
remote for. A [Kandev](kandev.md) sandbox's row also has `kandev`, its record.

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
asks. `--quick` skips reading figures from inside each guest, and shows the
remotes from what `ls` last cached, with no ssh.

### `msbctl show`

```text
msbctl show [name] [--json]
```

Everything about one sandbox: resources, disks, extra folders, installed
versions, environment, every egress rule in the order it's emitted, and the
identity, keys and secrets bound to it. `--json` prints the essentials as one
JSON document; for each secret it says whether a value is **stored**, never
what it is. For a Kandev sandbox it's its record, with agentctl checked live.

### `msbctl config`

```text
msbctl config
```

The merged configuration (`defaults.toml` plus your `config.toml`), with where
each value comes from.

### `msbctl entry`

```text
msbctl entry [name]
```

Open the sandbox's registry entry (`~/.config/msb/sandboxes/<name>.toml`) in a
terminal editor.

## Lifecycle

### `msbctl start`

```text
msbctl start [name…]
msbctl start --autostart
```

Start a stopped sandbox, or create it if it doesn't exist yet. Creating runs
the bootstrap, once. `--autostart` starts every sandbox whose registry entry
says `autostart = true` and isn't running; the picker runs it when it opens,
and so does the unit [`msbctl host autostart install`](#msbctl-host) writes.

### `msbctl stop`

```text
msbctl stop [name…] [--json]
```

Stop it. Everything is kept. `--json` prints `{"sandboxes": [...]}`, what
`show --json` says of each afterwards.

### `msbctl rebuild`

```text
msbctl rebuild [name…]
```

Destroy and recreate. Needed after changing anything fixed at create time:
egress rules, mounts, the image, environment variables. Your files, the Claude
state, package caches and container images survive; packages installed by
hand don't. Doesn't ask first.

### `msbctl purge`

```text
msbctl purge [name…] [-y] [--json]
```

Destroy the sandbox and deregister it: the VM, its Claude state, its disk
volumes, its secrets file and its registry entry. Your project folder is never
touched. Lists exactly what it will delete, and asks once per sandbox unless
`-y` is given. Remember to revoke its GitHub token too. A name with nothing
registered under it isn't an error: it says "nothing found" and succeeds, so
purging twice is fine. `--json` (with `-y`, since it can't ask) prints
`{"purged": [...], "absent": [...]}`. A Kandev sandbox loses its VM and its
entry; nothing else of msbctl's exists for one.

### `msbctl rename`

```text
msbctl rename name|. new-name [-y]
```

Give a sandbox a new name. msb can't rename a VM, so this recreates it, like a
rebuild; settings, secrets, Claude state, caches and container images all move
with it. See [Advanced usage](advanced.md#renaming-a-sandbox-or-moving-its-project).

### `msbctl move`

```text
msbctl move name|. dir [--rebuild]
```

Point a sandbox at another project folder. `dir` is read as it is for `add`.
Offers to copy `.msb/` across if the new folder lacks it, and re-detects the
GitHub repo. The folder is mounted at create time, so this needs a rebuild:
`--rebuild` does it now.

### `msbctl resize`

```text
msbctl resize [name] [--cpus N] [--memory SIZE] [--root-disk SIZE] [-y]
```

Change resources and keep the sandbox's state. cpus and memory need a restart
(asks first unless `-y` is given); the root disk grows live and can't shrink.
With no options it asks.

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
or wherever [`guest_path`](advanced.md#where-the-project-appears-in-the-sandbox)
puts it). Starts a stopped
sandbox; never creates one. Flags after the name go to `msb exec` as they are
(see [Passing flags to `msb exec`](#passing-flags-to-msb-exec)).

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
git push, Claude token, models for pi, GitHub token,
secrets, identity and autostart, or the files themselves in your editor. "View
the CLAUDE.md it gets" shows the instructions its agent is given on the next
start. Applies
what it can immediately and offers one rebuild at the end for the rest.

### `msbctl allow`

```text
msbctl allow name|. target… [--rebuild]
```

Add egress rules. Each target is `host` (HTTPS, :443), `host:port` (TCP),
`host:udp:port`, or a full rule such as `allow@10.0.0.5:tcp:5432`; an IPv6
address goes in brackets, `[fd00::5]:22`. Written to the project's
`extra_rules`. See [Adding a host](egress.md#adding-a-host).

### `msbctl policy`

```text
msbctl policy name|. [show|approve|update [REF]]
```

`show` (the default) prints the project-layer values the [policy
pin](egress.md#the-policy-pin) covers, whether they're the approved ones, and
what changed since. `approve` shows the change and asks; it needs a terminal.
`update`, for a sandbox cloned from a repo, fetches the repo's `.msb/` at the
tip of its ref (or of `REF`, which becomes its ref), shows what that commit
changes, and swaps it in once approved; a `rebuild` then applies it. The clone
inside the sandbox isn't touched.

### `msbctl observe`

```text
msbctl observe name|. [report|on|off] [--rebuild] [-y]
```

`on` stops blocking and records every host the sandbox reaches; `report` (the
default) reads that record back and prints the `msbctl allow` line for what no
rule covers; `off` restores deny-by-default. Turning it on asks first unless
`-y` is given. See [Observe mode](advanced.md#observe-mode-building-an-allowlist).

### `msbctl mount`

```text
msbctl mount name|. SRC[:DEST][:ro|rw] [--rw] [--rebuild]
```

Add an extra host folder. `DEST` defaults to `/mnt/<folder name>`; read-only
unless `rw` or `--rw` is given. Needs a rebuild.

### `msbctl port`

```text
msbctl port name|. [PORT|HOST:GUEST|BIND:HOST:GUEST[/udp]…] [--rm PORT] [--rebuild]
```

Publish a host port to a server inside the sandbox, so `http://localhost:PORT`
on this machine reaches it. A bare `PORT` is the same on both sides; with no
ports given it lists them, and `--rm` stops publishing one. Needs a rebuild. See
[Reaching a server in the sandbox](advanced.md#reaching-a-server-in-the-sandbox).

### `msbctl secret`

```text
msbctl secret add name|.
msbctl secret ls  name|.
msbctl secret rm  name|. VAR
msbctl secret set name|. VAR [--stdin] [--restart]
```

Tokens the sandbox can use but never see. `add` offers the presets or takes
your own binding. `set` stores a new value for a variable the sandbox already
binds (`GH_TOKEN`, or one of its `secret_binds`), from a hidden prompt or, with
`--stdin`, from standard input; binding a new variable is `add`. A running
sandbox uses the new value from its next start, or now with `--restart`. See
[Credentials & SSH](credentials.md#more-secrets) and
[Scripting](credentials.md#scripting-storing-a-token-from-a-password-manager).

### `msbctl keys`

```text
msbctl keys [name] [--all]
```

Choose which keys from your SSH agent (and `~/.ssh`) the sandbox can list and
sign with. Takes effect immediately. `--all` removes the restriction.

### `msbctl cache`

```text
msbctl cache name|. [ls|clear] [key]
```

Show the package-cache disks, or empty one (or all of them, if no key is
given). See [Package caches](advanced.md#package-caches).

### `msbctl update`

```text
msbctl update [name…] [-c component…]
```

Update components in place, without a rebuild. Components: `claude` (the
default), `pi`, `gh`, `gitleaks`, `bun`, `apt`. Versions installed this way are
recorded so a rebuild reproduces them. Run `msbctl ls --refresh` first for
`gh`, `gitleaks` and `bun`.

## The machine and msb-manager itself

### `msbctl setup`

```text
msbctl setup [--welcome]
msbctl setup --claude-token NAME [--stdin] [--default]
msbctl setup --identity KEY --git-name NAME --git-email EMAIL [--default]
```

Your machine-level settings as a menu: git identities, Claude login, model
endpoints (for [pi](models.md)), your network, new-sandbox defaults, or the
config file itself. `--welcome` runs the
first-time walk-through. `--claude-token NAME` skips the menu and stores one
Claude token under that name (`main` is the default one), from a hidden prompt
or `--stdin`. `--identity` adds or changes a git identity the same way, without
a signing key. `--default` also makes either one the default for new sandboxes.
These are how `msbctl remote setup` copies your settings to a host; through a
restricted key, only `--claude-token NAME --stdin` is allowed.

### `msbctl self-update`

```text
msbctl self-update [--version vX.Y.Z] [--json]
```

Upgrade a packaged install to the latest release, or a given one, verifying it
the same way the installer does. In a git checkout it tells you to `git pull`.
`--version 0.6.1` and `--version v0.6.1` name the same release. After a
successful install it restarts the Kandev proxy's service if that is running
an older release, which cuts its open connections. `--json` prints
`{"msbctl_version", "updated", "proxy"}` once it is installed, with the
installer's output on stderr. Under `host serve`, either key, `--version` may
not name a release older than the running one.

## Remote hosts

### `msbctl host`

```text
msbctl host serve [--kandev]
msbctl host authorize "PUBLIC KEY LINE" [--admin | --kandev] [--replace]
msbctl host check [--json]
msbctl host autostart install
msbctl host kandev install | reap | proxy | rotate-lease-key
msbctl host kandev configure [--[no-]enabled] [--serve MODE] [--proxy-listen IP]
                             [--base-url URL] [--allow-extra ENTRY …] [--json]
```

For running this machine as a [remote host](remote-hosts.md). `serve` is the
forced command a laptop's key runs: it reads `SSH_ORIGINAL_COMMAND`, refuses
anything outside [its allowlist](remote-hosts.md#what-the-restricted-key-may-run)
with exit status 126, and runs the rest with `MSB_RESTRICTED=1`. `authorize`
adds a key to `~/.ssh/authorized_keys` with that forced command, or with
`--admin` without one; a key that's already there is refused unless
`--replace`, which rewrites its line. `check` reports the host's hygiene, as heuristics.
`autostart install` writes and enables a systemd user unit that runs `msbctl
start --autostart` at boot. Under `host serve`, only `check` is allowed.
`--kandev` is the [Kandev plugin's key](kandev.md#the-plugin-key): its line
runs `host serve --kandev`, which admits `msbctl kandev` verbs and `ls`,
`show`, `stop`, `purge` and `self-update` with `--json` (seeing only Kandev's
sandboxes), while the everyday key runs no `kandev` verb. `kandev reap` is one pass of the
[reaper](kandev.md#the-reaper), and `kandev proxy` is the
[TLS proxy](kandev.md#the-tls-proxy); `kandev rotate-lease-key` replaces the key
its tokens are signed with, honouring the old one for 15 minutes. `kandev
install` writes and enables a
systemd user timer for the first and a service for the second, and restarts
the proxy. `kandev configure` sets the [`[kandev]` keys](kandev.md#setting-a-host-up)
it is given in `config.toml`, keeping everything else, and only if the result
is valid.

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

### `msbctl remote`

```text
msbctl remote add NAME user@host
msbctl remote setup NAME
msbctl remote ls
msbctl remote test NAME
msbctl remote rm NAME
```

The other machines this one drives; the menu's **remote hosts** does the same.
`add` records `[remotes.NAME]` in `config.toml`. At a terminal it then runs
`setup`; otherwise it prints the `msbctl host authorize` line to run there and
tests the connection. `setup` looks at the host over ssh and offers, one
question each, what's missing: msb and msbctl, both at this machine's versions,
the kvm group, autostart, copying your git identities and sending Claude
tokens (on stdin), and last restricting this machine's key to
`host serve` (it warns first when that key is the one with a shell there). Then
it tests. `test` runs
the host's `host check` and warns about an unrestricted key or a version
mismatch. `rm` forgets it; the host isn't touched. Then `NAME:sandbox`
addresses a sandbox there for every verb, and `ls` shows every host. See
[Remote hosts](remote-hosts.md#on-the-laptop).

## Environment variables

| Variable | Effect |
| --- | --- |
| `MSB_CONFIG_DIR` | config directory (default `~/.config/msb`) |
| `MSB_STATE_DIR` | state directory (default `~/.local/state/msb`) |
| `MSB_NO_AUTOSTART=1` | the picker doesn't start autostart sandboxes |
| `MSB_MANAGER_SKIP_ATTEST=1` | installer and `self-update`: skip the provenance check |
| `MSB_MANAGER_REPO`, `MSB_MANAGER_BASE_URL` | installer: another repository, or a mirror (`file://` works; needs `--version`) |
