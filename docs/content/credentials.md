---
title: Credentials & SSH
section: Guides
order: 30
description: Tokens a sandbox can use but never see, the filtered SSH agent, and commit signing.
---

## Secrets: usable, never visible

msb-manager binds tokens with msb's `--secret ENV@HOST`. Inside the guest the
variable holds a placeholder, `$MSB_<ENV>`. When a request leaves the VM, msb
replaces the placeholder with the real value, **on the host**, in **request
headers only**, and only for the named hosts.

```console
$ echo "$GH_TOKEN"                     # inside the sandbox
$MSB_GH_TOKEN
$ gh api user --jq .login              # still works: substituted on the way out
yourhandle
```

What this means in practice:

- `curl -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/user` works.
- `https://x:$GH_TOKEN@github.com/…` works too: curl turns the user info into an
  `Authorization` header before sending.
- A placeholder in a **query string** or a **request body** is not substituted,
  unless the binding opts in with `:query` or `:body`.
- Sending a token to a host it isn't bound to sends the placeholder text, which
  is useless to whoever receives it.

The real values live in `~/.config/msb/secrets/`: `global.env` for the Claude
token, and `<name>.env` per sandbox. Both are mode 0600, outside every project,
and can instead keep each value in your desktop keyring, as below.

### Keeping the values in the keyring

A 0600 file is readable by anything running as you, and by every backup of your
home folder. On a desktop with a keyring (GNOME Keyring, KWallet, KeePassXC: any
Secret Service), the values can live there instead, through `secret-tool`
(`libsecret-tools` on Debian and Ubuntu, `libsecret` on Fedora). The files stay,
and still name every variable, but each value becomes `VAR=@keyring`:

```console
$ msbctl secret migrate --to keyring     # every stored value, every file
$ msbctl secret migrate --to file        # and back
```

`migrate` is safe to run again, never prints a value, has `--json`, and sets
`[secrets] store` in `config.toml` to match, which decides where *new* values
go. Moving back to the files stops at a value a line can't hold (a line break,
or a space or quote at either end) and leaves it in the keyring. A
`VAR=@keyring` line whose item you deleted in your keyring's own tool has no
value to move, so `migrate` drops that line and says so:

| `store` | New values go to |
| --- | --- |
| `"file"` (default) | the 0600 file |
| `"keyring"` | the keyring. Storing **refuses** when there's no keyring at all, rather than writing a plaintext copy you didn't ask for |
| `"auto"` | the keyring if there is one, otherwise the file |

A locked keyring is fine: the first time msbctl reads or writes a value, your
keyring shows its usual unlock prompt, once per command however many values
it reads. If you dismiss it, nothing else prompts during that command: a sandbox
starts without the secrets kept there, with a warning naming each one, exactly
as if they had never been stored. Storing a value, `migrate`, `rename` and
`purge` stop instead, and change nothing. Listing what is stored (`secret ls`,
`ls`, `show`, the `edit` menu) reads only the file, so it never prompts. Before any of that, msbctl asks D-Bus whether a Secret
Service exists at all (`busctl`, or `gdbus`), so on a machine without one it
never calls `secret-tool`. `msbctl host check` shows the store, whether the
keyring is there and unlocked, and how many values are in it.

**Autostart and servers.** A sandbox started at boot by `msbctl host autostart
install` starts before anyone logs in. A desktop keyring is usually still locked
then, and nobody is there to answer its prompt. So `msbctl start --autostart`
run without a terminal (the boot unit) **skips** each sandbox that needs a
keyring value while the keyring is locked, and names them: unlock it and start
them yourself. A value in `global.env` counts only for the sandboxes that use
it: the Claude token each one logs in with, its model endpoints' keys, and
bindings in its registry entry. Nothing else there is read for it. From the picker, on a terminal, they
start as usual and the keyring asks. Turning autostart on while secrets are in
the keyring (`msbctl edit`, `add`, `host autostart install`), or moving them
there with autostart on, says this and asks you to confirm when there's a
terminal. Without one it only warns. `msbctl host check` flags the combination
while the keyring is locked.

A remote host, a Kandev host or an ssh session usually has no Secret Service at
all, and `"auto"` keeps the file there. If a headless machine does run one, keep
it unlocked or without a password, since an unlock prompt there has nobody to
answer it. For a server, `"file"` on an encrypted disk is the recommendation
(`msbctl host check` looks for one).

Renaming a sandbox moves its keyring values with it, and purging it deletes
them, before anything else. If the keyring refuses, nothing is renamed or
purged. With no Secret Service on that machine at all, `purge` goes ahead and
prints the `secret-tool clear` command for wherever the values are. Each value is one keyring item labelled `msb-manager: VAR (file)`, so
your keyring's own tool shows them too.

### Claude

`msbctl setup` → "Claude login" stores a long-lived token from
`claude setup-token` in `secrets/global.env`. Every sandbox gets
`CLAUDE_CODE_OAUTH_TOKEN` as a placeholder bound to `api.anthropic.com` and
`platform.claude.com`, plus its own `~/.claude`, kept on the host at
`~/.local/state/msb/claude/<name>/`.

You can keep more than one, one per account. "Add a Claude token" asks for a
name (`work`, `personal`) and stores each under its own variable; "choose the
default Claude token" sets `[defaults] claude_token` in `config.toml`, which
every sandbox uses unless it picks its own with `msbctl edit` → "Claude token".
That choice is `claude_token` in the sandbox's registry entry, never in the
committed `sandbox.toml`. The value is read on every start, so switching is a
restart, not a rebuild, and the guest sees the same `CLAUDE_CODE_OAUTH_TOKEN`
placeholder whichever token is behind it. `msbctl show` names the one in use. A
token stored before names existed is the one called `main`.

> **Note:** `claude_auth = "mount"` in your config shares the host's real
> `~/.claude` with every sandbox instead. That means shared history, but also
> your real credentials and every project's transcripts in every VM. It's a
> fallback for when `spikes/07-claude-token-secret.sh` fails, not a preference.

### Model endpoints

A key for one of pi's [model endpoints](models.md) is stored as
`LLM_KEY_<NAME>` in `secrets/global.env` (or the sandbox's own file, which
wins) and bound to that endpoint's host alone, like the Claude token. The
endpoint must be HTTPS for the key to stay outside.

### GitHub

One fine-grained token per project, scoped to that one repository (see
[Get started](quickstart.md#the-github-token)). It's bound as `GH_TOKEN` to
`github.com` and `api.github.com`. Replace or remove it with `msbctl edit` →
"GitHub token".

### More secrets

```console
$ msbctl secret add .            # pick a preset or type your own binding
$ msbctl secret ls .
$ msbctl secret rm . NPM_TOKEN
```

The presets: `npm`, `dockerhub`, `ghcr`, `pypi`, `crates`. Each knows its
variable name, the hosts it goes to, where to create the token and how the tool
picks it up. You can add your own presets under `[secret_presets.<name>]` in
`config.toml`. A hand-written binding uses msb's own syntax:

```text
NPM_TOKEN@registry.npmjs.org
MY_TOKEN:query@api.example.com          # also substitute in the query string
MY_TOKEN@one.example.com,two.example.com
```

**Where the value comes from** depends on where the binding is written. A
binding in the project's `.msb/sandbox.toml` takes its value from that
sandbox's own `secrets/<name>.env` only, never from `global.env`: that file is
committed and writable from inside the sandbox, and it decides which host the
value is sent to. A binding in the registry entry (yours, machine-local) may
also use a value from `global.env`, shared between sandboxes. `msbctl secret
add` stores the value per sandbox either way.

**Reserved variables.** `GH_TOKEN` and the Claude token variables
(`CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_<NAME>`) have fixed
bindings and can't appear in `secret_binds` in any file: a second
`GH_TOKEN@somewhere.example` would send the real token there. A create or
rebuild refuses such a line; a sandbox that already exists starts without it.

A secret doesn't open the network: its hosts must also be allowed by an egress
rule. `msbctl add` warns when they aren't; after `msbctl secret add`, check
with `msbctl show` and [`msbctl allow`](egress.md#adding-a-host) what's
missing.

### Scripting: storing a token from a password manager

Every token can be stored without a menu, and without the value ever being an
argument (where `ps` and your shell history would see it):

```console
$ pass show github/webshop | msbctl secret set webshop GH_TOKEN --stdin
$ op read op://dev/npm/token | msbctl secret set webshop NPM_TOKEN --stdin --restart
$ pass show claude/work | msbctl setup --claude-token work --stdin
```

One trailing newline is dropped; an empty value, one with whitespace in it, or
one over 8 KiB is refused, and nothing is printed back. `secret set` only
stores values for variables the sandbox already binds. `msbctl ls --json` and
`msbctl show --json` say whether a token is stored, and never what it is.

### Why a placeholder can break an agent, and why it doesn't here

msb blocks any outbound request carrying a placeholder in a place where
substitution isn't allowed, such as a request body. Coding agents send their
whole transcript in the request body on every turn. So once an agent has read
`$MSB_GH_TOKEN` (from `env`, say), every later request would carry it and be
killed, which Claude Code reports as `API Error: Connection dropped
(ECONNRESET)`.

msbctl prevents this by adding `passthrough=` for the agent's own API hosts to
every binding it emits: Anthropic's, and in a sandbox with pi, each of its
model endpoints. Passthrough lets the harmless *placeholder* travel to
those hosts and never substitutes the real value, so the real token still goes
only into headers, only to its own hosts.

## SSH: the filtered agent

A sandbox never gets your SSH agent directly. Its `--vsock` points at a small
per-sandbox daemon, `msbctl _agent-filter <name>`, which forwards exactly two
kinds of request to your real agent:

- **list identities**, answered with only the keys this sandbox may use;
- **sign**, refused for any key not on that list.

Everything else (adding keys, removing them, locking the agent) is refused.
Signing still happens in your host agent, so passphrases, hardware keys and
`ssh-add -c` confirmations all keep working.

```console
$ msbctl keys .            # pick keys: one list, agent keys and ~/.ssh files
$ msbctl keys . --all      # remove the restriction: every key in the agent
```

The selection is read on every request, so a change takes effect immediately.
In the registry entry, `ssh_keys` absent means every key, and `ssh_keys = []`
means none. If a selected key isn't loaded in your agent at start, msbctl
finds it in `~/.ssh` and `ssh-add`s it, asking for a passphrase if it needs one.

Inside the guest, `SSH_AUTH_SOCK` is `/tmp/ssh-agent.sock` in `msbctl shell`
and `exec`. Your `~/.ssh/known_hosts` is mounted **read-only**: the sandbox can
check hosts you already trust, but can't quietly add a new one.

## git push: gh or ssh

Each sandbox pushes to GitHub one of two ways, chosen in `msbctl add` and
changed with `msbctl edit` → "Git push" (`git_push` in the registry entry,
default `[defaults] git_push`). gh handles PRs, Actions and the API in both
modes. The choice only decides how git itself gets to GitHub.

| `git_push` | Fetch | Push | Needs |
| --- | --- | --- | --- |
| `"gh"` (default) | https | https | the [GitHub token](#github) |
| `"ssh"` | as the remote says | ssh, through the filtered agent | a push key the sandbox is allowed |

The repo's own remote is never changed: in a folder sandbox `.git/config` is
your host checkout, so rewriting it for the guest would change how you push on
the host too. msbctl sets rewrites in the guest's `/etc/gitconfig` on every
start instead. With `"gh"`, a `git@github.com:` origin is fetched and pushed
over https (`insteadOf`), and gh's credential helper passes git the `GH_TOKEN`
placeholder. With `"ssh"`, an https origin is pushed over ssh
(`pushInsteadOf`). Switching needs a restart, not a rebuild.

With `"ssh"`, github.com is offered **one** key: the identity's `push_key`, or
the registry entry's own `push_key` if it has one. Without one, ssh offers
every key the sandbox is allowed, and GitHub takes the first it knows, which
may belong to another account:

```toml title="~/.config/msb/config.toml"
[identities.work]
name     = "yourhandle"
email    = "12345+yourhandle@users.noreply.github.com"
push_key = "ssh-ed25519 AAAA..."
```

`msbctl setup` → "Git identities" picks it, preselecting the signing key,
because one key registered with GitHub for both uses is common. Sandboxes
[without a folder](advanced.md#sandboxes-without-a-folder) have no agent and
always use `"gh"`.

## Commit signing

Give an identity in `config.toml` (or in `msbctl setup` → "Git identities") a
`signing_key`, the public half of an SSH key:

```toml title="~/.config/msb/config.toml"
[identities.public]
name        = "yourhandle"
email       = "12345+yourhandle@users.noreply.github.com"
signing_key = "ssh-ed25519 AAAA..."
```

A sandbox using that identity sets `gpg.format=ssh`, `user.signingkey` and
commit and tag signing in the guest's `--system` git config, and signs through
the filtered agent. An allowed-signers file is written too, so
`git log --show-signature` verifies its own commits.

Signing is on only while the sandbox is allowed that key. Drop it in
`msbctl keys` and signing turns off, with a warning, rather than leaving you
with a sandbox where every commit fails.
