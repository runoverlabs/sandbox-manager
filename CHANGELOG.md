# Changelog

All notable changes, one line each, newest first. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow `VERSION`.
Add entries under **Unreleased**; the release process turns that heading into
the version being cut, and the release workflow publishes that section as the
release notes.

## [Unreleased]

### Changed
- `msbctl port` and `msbctl edit` → Published ports no longer need a rebuild: they change an existing sandbox with `msb modify`, which keeps its state. A stopped sandbox has the new ports when it next starts, and a running one on its next start, or at once with `msbctl port --restart` (asked on a terminal), which is msbctl's own stop and start. `--rebuild` still rebuilds, for when other create-time changes are pending too. A new guest port for a host port already published replaces that mapping, and a port msbctl didn't publish (an `msb_conf` one) is never removed.

## [0.10.0] - 2026-10-30

### Added
- `msbctl managed` (protocol 2) lets another orchestrator own sandboxes on a Kandev host beside Kandev's: `host authorize KEY --client NAME` writes a key whose forced command is `host serve --client NAME`, which runs that client's `managed` verbs and `ls`, `show`, `stop`, `purge` and `doctor --json` over its own sandboxes only. Its sandboxes have their own name prefix, msb label, limits, egress, guest ports, agentctl variable prefix and an optional callback, which its `allow_extra` must admit: by an address, CIDR or address:port entry covering the address it resolves to on the host, or by a hostname pattern only when that address is public or the name is in its `private_names`, as for the same name in `egress_allow` (a name nothing could admit is refused without being looked up); `*` admits any address given as one, private included, and for a name counts as a pattern. A client that is never called back sends none, so no egress rule names it and nothing is pinned in the guest's `/etc/hosts`, where a pinned name would get no secret substituted. Kandev's `msbctl kandev` (protocol 1) is unchanged, and the Kandev key may run `managed` too.
- `msbctl kandev health` lists the `managed_namespace` feature on a host that speaks protocol 2.
- `[managed]` (the host-wide proxy, address, pool keys and optional totals over every client) and `[clients.NAME]` (one client's table, including `body_secret_hosts`: the hosts a secret's placeholder may reach in a request body, such as its model endpoints) in `config.toml`, set by `msbctl host managed configure [--client NAME]`; `msbctl doctor` reports a table that doesn't check out, and a client prefix that an existing sandbox of yours already starts with. A problem in a client's table, or two clients sharing a prefix, stops only the clients concerned; Kandev and the others go on. Nothing to do for Kandev hosts: `[kandev]` keeps working. Its client keys may move to `[clients.kandev]` and its host keys to `[managed]`; a host key in any `[clients.*]` table is refused.
- `msbctl kandev health` reports, under `serve`, the public ports the Kandev proxy has open (`ports`, `[]` when no sandbox is live) and how many ports in `proxy_port_pool` your own sandboxes publish (`pool_overlap`), advertised as the `serve_ports` feature; `host kandev configure` warns, naming them, when your sandboxes publish ports inside `port_pool` or `proxy_port_pool`. The proxy picks this up on its next restart (`kandev restart-proxy`).
- `msbctl add` lets a repo on another forge through egress: a rule group that already allows its host and port is preselected, and when none does, the wizard writes a machine-local `forge-<host>` group into `config.toml` (`:443`, plus the SSH port for an ssh URL), listed under `private_dns_groups` when the name resolves to a LAN address, and gives it to the sandbox. It never goes into the project's `sandbox.toml`. A shipped `codeberg` group covers Codeberg.
- `[defaults] agents` (`["claude"]` by default; `msbctl setup` → Coding agents) decides which coding agents a new sandbox gets ticked, `[]` for none; pi is still ticked too when `[defaults] llm` names an endpoint. The first-run setup skips the Claude login when no new sandbox gets Claude, and the model endpoints when none gets pi.

### Changed
- New sandbox names may not start with any configured client's `name_prefix`, as they already could not start with Kandev's `k-`, which no client may take. The Kandev proxy serves every enabled client's sandboxes, and the reaper reaps every client's, each by its own label. Before downgrading to an msbctl without protocol 2, purge every managed client's sandboxes: an older `msbctl ls` fails on their `source = "managed"` entries.
- The Kandev proxy logs how many ports it serves whenever that changes, 0 included (`serving 0 ports: no Kandev sandbox is published through the proxy`), and each port it opens or closes with the sandbox and guest port behind it; before, an idle proxy logged just "serving", which looked like a failed bind. The Kandev page now says that in proxy mode nothing listens on `base_url`'s port and there is no `/health` URL: check a host with `msbctl kandev health` over ssh and a real lease.
- `msbctl add` asks for the coding agents right after the repo, and the steps after follow the answer: no Claude token step without Claude Code, and the guest-path note no longer assumes Claude. `msbctl edit` → Claude token says it is not used in a sandbox without Claude.

### Fixed
- On a Kandev host, a value of the wrong type in `[kandev]` (`rule_groups = [["base"]]`, an inline table) or a `base_url` that does not parse as a URL now answers `invalid_config` naming the table, like any other bad value, instead of `unavailable` ("internal error"), and no longer stops the Kandev proxy. A key in `[kandev]` (or any client's table) that does not check out no longer stops the reaper either: sandboxes past their expiry are still destroyed, and only a problem in the host's keys stops it.
- A sandbox without Claude Code (pi only, or no agent) no longer has the stored Claude token bound at start, and no longer reads it: before, it got the `CLAUDE_CODE_OAUTH_TOKEN` placeholder whenever a token was stored, and a locked keyring could prompt, or hold up its autostart, for a token nothing in it used.
- `msbctl add` handles a repo that isn't on GitHub: give it the clone URL (`https://`, `ssh://user@host:port/path` or `user@host:path`) and it is cloned as given, stored in `repo` as given, and the GitHub steps (PAT, `[secrets] github`, the gh/ssh push question, language detection, the pre-ticked `github` feature) are skipped. Before, any such URL was turned into `git@github.com:<url>.git` and treated as a GitHub repo. The agent's CLAUDE.md names the forge, and `add --repo` refuses one, which it cannot clone.

## [0.9.1] - 2026-10-26

### Changed
- New sandboxes get node 24 (the active LTS) instead of 22, which is in maintenance until April 2027; a sandbox whose own `[versions]` pins `node` keeps it, and an existing one changes on its next rebuild.
- Sandboxes get npm 12.2.1 instead of the npm that node ships (11 on node 24): a new `npm` pin in `[versions]` (`""` keeps node's own), shown by `ls --refresh` and updated in place with `msbctl update . -c npm`; existing sandboxes need a rebuild or that update.

## [0.9.0] - 2026-10-26

### Added
- `msbctl doctor [--json]` checks that this machine can run sandboxes and prints the fix for each problem: KVM access, msb and its version (and `msb doctor`'s verdict), disk space, config and secret file modes, registry entries whose folder is gone or that msb doesn't know about, the SSH agent, and `host check`'s hygiene heuristics. It never prompts and exits 1 only when something failed. `remote test` and `remote setup` now run it on the host, falling back to `host check` on an older one. Under the Kandev plugin's key it reports the host and Kandev's own sandboxes, and names none of the operator's.
- Tab completion for bash, zsh and fish: `msbctl completion bash|zsh|fish` prints a script to source, completing verbs, flags and sandbox names (`HOST:name` from what `ls` last cached) and handing `exec`'s command to the shell's own completion, without starting `msb` or ssh on a Tab.
- `msbctl allow . --from-observe` allows every host the observation log shows reached and no rule covers, in one write and one approval (names seen only in DNS with `--with-dns`), and `msbctl observe . --json` prints the report as one JSON document, so the observe → allow → rebuild loop runs from a script.
- `git_checkstat` turns on or off the `core.checkStat = minimal` that msbctl puts in a mounted project's repos so a host editor's git does not rewrite `.git/index` under the sandbox: `[defaults] git_checkstat` (`msbctl setup` → Defaults for new sandboxes) for the machine, the registry entry (`msbctl edit` → Host editor) for one sandbox; on by default, `show` and `show --json` report it (`null` for a sandbox without a folder), and the agent's CLAUDE.md says which, so it neither unsets the value nor chases files that only looked deleted. Turning it off does not remove the value from repos that already have it.
- Published tcp ports are clickable in `msbctl port` and `show` (an OSC 8 hyperlink to `http://127.0.0.1:<host>/` on a terminal), and `show --json` adds a `port_urls` map of each port to its URL.
- Secret values can live in your desktop keyring instead of 0600 files: `msbctl secret migrate --to keyring` moves them (and `--to file` back), and `[secrets] store = "file" | "keyring" | "auto"` in `config.toml` decides where new ones go. A locked keyring asks to unlock with its own prompt, a machine without one keeps the files, a boot-time `start --autostart` skips (and names) the sandboxes whose secrets are in a still-locked keyring, and `msbctl host check` reports which store is in use. Over ssh into a machine whose desktop keyring is locked, msbctl says the unlock prompt is on that desktop's screen; see the docs' "Credentials & SSH" page. Nothing changes until you opt in.

### Changed
- The `github` egress group allows `*.blob.core.windows.net`, where `gh run view --log` fetches Actions logs from (it replaces the single `tmaproduction` account `gh attestation verify` needed); existing sandboxes need a rebuild.
- The `go` egress group allows `storage.googleapis.com`, where proxy.golang.org redirects module and toolchain downloads; existing sandboxes need a rebuild.
- `core.checkStat = minimal` is now set on each checkout up to two levels under the project folder (`repo/`, `group/repo/`; `node_modules` and hidden folders skipped) as well as the project folder itself, symlinked checkouts included, and in every read-write extra mount, so a workspace holding several repos no longer loses `.git/index` for ~5 s whenever a host editor diffs one of them; before, a project folder that was not itself a repo got nothing. The git calls run only when this boot has not yet seen exactly these repos (or `git_checkstat` changed), so a repo cloned since is covered by the next `shell`/`exec`; a guest without git yet is retried instead of remembered, and a repo whose `.git/config` the guest cannot write is skipped.
- The same walk adds every repo it finds to git's global `safe.directory` in the guest, by name, so git there (the agent's as much as msbctl's) no longer refuses a repo two levels down, cloned since create, or in an extra mount as "dubious ownership"; before, only bootstrap's create-time list of the project and the repos directly in it was trusted. It runs whether or not `git_checkstat` is on.
- `msbctl allow` on a terminal now asks whether to rebuild when `--rebuild` is not given; off a terminal it never asks and does not rebuild, as before, and `--no-rebuild` skips the question.
- `msbctl observe`'s report no longer counts a udp or `:ingress` rule for a host as covering a TLS connection to it.
- A secret value that a line in its 0600 file cannot hold as it is (a line break, or a space or quote at either end) is refused when you store it, instead of being written and read back trimmed.

## [0.8.0] - 2026-10-24

### Added
- Agent tools: a capability your own endpoints back (web search, page reading, anything else), attached to sandboxes from one folder — `~/.config/msb/tools/<name>/` with a `bundle.toml`, a pi extension and a Claude Code skill. Its egress rules and environment are emitted from the bundle, the adapters are installed at every start and removed when it goes, and `msbctl setup` → Agent tools turns them on for new sandboxes (`msbctl edit` for one). Nothing belongs in the project; see the docs site's "Agent tools" page.
- A tool bundle can give pi a published pi package (`pi_package = "name"` or `"name@1.2.3"` in `bundle.toml`), such as `billion-context-pi`: msbctl declares it in pi's settings and pi installs it inside the sandbox on the next start, onto the mount that survives a rebuild; `msbctl update <name> -c pi` now also updates pi's packages (a pinned one stays).
- Each sandbox now tells its agent where its project is mounted and where the project's own `.agents/skills/` folder is, so those files are reachable from outside it; nothing to do, it lands on the next start.
- pi, a second coding agent for your own model server or any provider: add a source with `msbctl setup` → Model endpoints (a URL and a key; HTTPS only, the key stays on the host), pick its model from the list it serves, then tick `pi` under Coding agents and rebuild. The model list is asked again on every start, and "choose a model" changes the model without a rebuild.

### Fixed
- `msbctl secret add` no longer writes `secret_binds` into the middle of a multi-line `extra_rules` list, which left the file unreadable; the same fix covers `allow` after a multi-line `rule_groups` and `mount add`. A list holding an IPv6 rule (`allow@[fd00::1]:tcp:22`) is no longer cut short at its `]`, and msbctl now refuses to write a file it would leave invalid.
- A policy change can no longer hide in the approval prompt: text from `.msb/sandbox.toml` that would move the cursor or recolour the terminal is shown escaped, so an `\u001b` sequence can't erase the added rule or secret binding from the screen you are approving.
- `msbctl edit`, `allow` and `secret` no longer approve a change the sandbox wrote to `.msb/sandbox.toml` while they waited on you: only what msbctl itself wrote is approved unasked, and anything else (including your own edit in "Edit the files") is shown and asked about as you leave.
- The `containers` rule group now allows `*.data.mcr.microsoft.com`, where Microsoft's registry actually serves image layers from, so pulling an `mcr.microsoft.com` image inside a sandbox no longer fails at the first layer; rebuild a sandbox with `containers` to pick it up.
- pi no longer stops at a startup question nobody is there to answer. The sandbox's project folder (and `/tmp`) are trusted on every start, which also fixes the project's own `.agents/skills/` loading nothing when pi is started without a terminal (`msbctl exec . -- pi …`), where pi answered its own trust prompt with "no"; and the "What's New" block pi prints after it updates is switched off — `/changelog` still shows it. Both are pi's own settings under `~/.pi/agent/`, rewritten on every start, so nothing needs a rebuild.

### Changed
- pi installs from `@earendil-works/pi-coding-agent`: the `@mariozechner` package pi used to live in is deprecated on npm and stops at 0.73.1, so rebuild a sandbox that already has pi: its key stops working until then, because `models.json` now uses the key spelling only the new pi understands.

## [0.7.0] - 2026-10-22

### Added
- `[kandev] private_names` (`host kandev configure --private-name`) lets a Kandev profile name a host that resolves to a LAN address, such as a forge with a bound token; that sandbox runs with DNS rebind protection off and msbctl denies every other private destination in its place.

## [0.6.1] - 2026-10-19

### Added
- `msbctl kandev restart-proxy` restarts the Kandev proxy if it runs an older release, and `kandev health` reports the proxy's release as `serve.version`: run it once after updating a 0.6.0 host.

### Changed
- `self-update` restarts the Kandev proxy's service after an update if it runs an older release, so the proxy no longer keeps the old code until someone restarts it; this cuts its open connections.

### Fixed
- `self-update --version` and `get.sh --version` accept `0.6.1` as well as `v0.6.1`.

## [0.6.0] - 2026-10-19

### Added
- `kandev health` reports `host`: the machine's OS, kernel, CPUs, memory, load, free disk and uptime.
- `msbctl host kandev configure` sets `[kandev]` keys (`--enabled`, `--serve`, `--proxy-listen`, `--base-url`, `--allow-extra`) in `config.toml`, keeping the rest of the file, and refuses a bad value without writing.
- The Kandev plugin's key may run `self-update --json`, which answers `{"msbctl_version", "updated"}`; under either restricted key `--version` may now name any release not older than the running one.

## [0.5.1] - 2026-10-19

### Added
- `[kandev] allow_extra` admits addresses (`192.168.2.6`), `address:port` (`192.168.2.6:8788`) and CIDRs (`192.168.2.0/24`, no wider than /8), so one LAN host can be allowed without `"*"`; `kandev health` reports the list as `egress.allow_extra`.

## [0.5.0] - 2026-10-19

### Added
- Kandev sandboxes get their own disk at `/workspace` (`workspace_gib` in `kandev provision`, now required), deleted with the sandbox; `kandev health` lists `features`, starting with `workspace_disk`.

## [0.4.0] - 2026-10-19

### Added
- Kandev sandbox hosts: `msbctl kandev …` lets the Kandev plugin run one microVM per session here over ssh, listing, inspecting, stopping and removing them with `ls`, `show`, `stop` and `purge` and `--json` (`host authorize --kandev`, `host kandev install|reap|proxy`); off until `[kandev] enabled = true`, see the "Kandev hosts" page.
- Kandev hosts serve sandboxes through their own TLS proxy (`[kandev] serve = "proxy"`, the new default; set `proxy_listen`): the plugin installs a certificate with `kandev tls install`, leases carry a short-lived token in `X-Msb-Lease` that survives a stop and start (`host kandev rotate-lease-key` replaces its key), and `health` reports `tls`. Re-run `msbctl host kandev install` to get the proxy's service, or set `serve = "tailscale"` to keep `tailscale serve`.
- `msbctl stop --json` and `msbctl purge -y --json` print one JSON document, as `ls --json` and `show --json` do.
- Kandev `health` reports `serve.ok = false` in `tailscale` mode when the tailnet issues no certificates (headscale).
- The `go` egress group allows `vuln.go.dev`, for `govulncheck`; existing sandboxes need a rebuild.
- Remote hosts from the menu: bare `msbctl` → **remote hosts** adds, sets up, tests and removes them, and `msbctl remote setup NAME` installs what a host is missing (msb and msbctl at this machine's versions, autostart) and restricts your key there, asking before each step.
- With remotes configured, `msbctl add` asks where the new sandbox should run, and the menu's sidebar lists every remote's sandboxes too.
- `msbctl host authorize --replace` rewrites a key's existing line, so a key that already has a shell can be restricted.
- Git push mode per sandbox (`git_push`, `msbctl edit` → Git push): `gh` (the new default) fetches and pushes over https with the GitHub token through gh's credential helper, even for an SSH origin; `ssh` pushes through the agent with the identity's new `push_key` only. Takes effect on the next start; set `git_push = "ssh"` in a sandbox's registry entry to keep pushing over SSH.
- `msbctl remote setup` offers to copy your git identities and Claude tokens to the host; `msbctl setup --identity KEY --git-name … --git-email …` and `--default` set them without the menu.

### Changed
- In the picker, Enter now edits the sandbox (`msbctl edit`).
- `msbctl purge` of a name with nothing registered under it says "nothing found" and succeeds, so purging twice is fine.
- With `--json`, a failing `ls`, `show`, `stop` or `purge` prints `{"error": {"code", "message"}}` on stdout and exits 3 (`not_found` for an unknown name) instead of a message on stderr and exit 1.
- `msbctl stop` exits non-zero when msb fails to stop a running sandbox.

### Removed
- `msbctl code` and `MSB_EDITOR`: open the project folder in your editor yourself.

### Fixed
- Bare `msbctl` → "register a new project" crashed with `AttributeError: 'Namespace' object has no attribute 'repo'`, and "refresh version info" likewise.

## [0.3.0] - 2026-10-16

### Added
- `msbctl remote add` registers another machine; `host:name` addresses a sandbox there, and `ls` and the picker show every host.
- `msbctl host serve|authorize|check`: run a machine as a remote sandbox host whose SSH key for everyday use cannot read secrets or change policy.
- `msbctl start --autostart` and `msbctl host autostart install` start the autostart set after a reboot, with no picker or login.
- `ls --json`, `show --json`, `msbctl secret set … --stdin` and `msbctl setup --claude-token NAME --stdin` for scripts; no secret value is ever printed.
- `msbctl add --repo owner/name` creates a sandbox with no host folder: the repo is cloned into a disk volume that survives rebuilds, and its policy is read from the repo's `.msb/` at a recorded commit (`msbctl policy <name> update` moves it).
- Changes to a project's egress rules, secret bindings or resources must be approved on the host (`msbctl policy`) before a create or rebuild applies them, and `.msb/` is read-only inside the sandbox; the first rebuild after upgrading asks once.

### Changed
- The `containers` egress group also allows `mcr.microsoft.com`, so podman in a sandbox can pull the devcontainers images. Needs a rebuild.
- An egress group you defined yourself is written to the sandbox's registry entry (`extra_rule_groups`, added to the project's groups) instead of the committed `.msb/sandbox.toml`, where it broke every other clone; `msbctl edit` → Features & agents moves one that is already there. Needs a rebuild.
- Sandboxes with Claude Code get `IS_SANDBOX=1` (so bypass-permissions mode is offered, including through `claude-agent-acp` in Zed), `DISABLE_BUG_COMMAND` and `DISABLE_AUTOUPDATER` on top of the telemetry and feedback opt-outs. Those now come from a new `[agent_env.claude]` table and are no longer set in sandboxes without Claude. Needs a rebuild.

### Fixed
- A project's `sandbox.toml` can no longer bind `GH_TOKEN` or a Claude token, read values from `secrets/global.env`, or switch on observe mode; store a project binding's value per sandbox with `msbctl secret add`.
- A project's `.msb/dev.yaml` is no longer passed to msb, which let a repo mount host paths or read the bound secrets; only its `image` is read, and create refuses a file that sets more (move `env:` to `sandbox.toml`, or use the new registry-only `msb_conf`).

## [0.2.4] - 2026-10-09

### Added
- Each release carries its build-provenance attestation as `msb-manager-X.Y.Z.intoto.jsonl`, so `gh attestation verify --bundle` can check a download against it.

### Changed
- `msbctl rebuild` and `start` (and a rename that recreates the sandbox) end with a red warning and exit non-zero when the bootstrap fails, instead of reporting the sandbox as running; the half-set-up sandbox is kept so you can look inside.

### Fixed
- The bootstrap's apt step retries a dropped download and reports FAILED when the install fails, instead of saying "ok" with podman and the base tools missing; a sandbox that hit this needs a rebuild.
- A secret binding with its own options (`KEY:query@host`) no longer fails at create with "invalid secret option": msbctl now joins its `passthrough=` to them with a comma, as msb expects; run the failed rebuild again.
- podman works again after a sandbox restart instead of failing every command with "boot ID differs": each start clears its runtime state left over from the previous boot (images and containers are kept); no rebuild needed.
- Image update checks only fetch a registry's pull token over https; a registry that names a plain-http (or other) token service is skipped instead.

## [0.2.3] - 2026-10-09

### Added
- Each sandbox's `CLAUDE.md` ends with a short "This sandbox" section listing its features, so the agent knows podman is there; refreshed on every start, and `msbctl edit` → "View the CLAUDE.md it gets" shows the result.
- A `browsers` feature in `msbctl add` and `edit` (the new `playwright` egress group) lets `playwright install` download its browsers from `cdn.playwright.dev`; an existing sandbox needs it ticked, then a rebuild.
- The `containers` egress group (the podman feature) allows `codeberg.org`, so images pull from Codeberg's registry; existing sandboxes need a rebuild.
- Every start sets `core.checkStat=minimal` in the project's git repo (unless it sets `core.checkStat` already), so `.git/index` no longer vanishes for ~5 s after a git command while a host editor such as zed watches the repo; no rebuild needed.
- Several Claude tokens, one per account: `msbctl setup` → Claude login stores them by name and picks the default, `msbctl edit` → Claude token picks one per sandbox (a restart, no rebuild); an existing token becomes `main` and nothing changes until you add another.

## [0.2.2] - 2026-10-08

### Added
- `msbctl port <name> 8080` publishes a host port to a server inside the sandbox, so `http://localhost:8080` reaches it (also under `msbctl edit` → Published ports); stored in the registry entry, bound to 127.0.0.1, needs a rebuild, and the server inside must listen on 0.0.0.0.

### Fixed
- `msbctl allow`, `edit` and `setup` accept `host:tcp:port` (and `host:udp:port`) instead of turning it into a rule msb refuses at create (`…:tcp:2222:tcp:443`); a rule already saved that way now fails before create, naming the file to fix it in.

## [0.2.1] - 2026-10-08

### Added
- `msbctl shell` and `msbctl exec` pass any flag after the name to `msb exec` as is (`-u root`, `--timeout 5m`, `-e KEY=value`, …; `msb exec --help` lists them); for `exec`, end them with `--`.
- The project can appear inside the sandbox at its host path (or any path) instead of `/work`, so paths in errors and agent output open on the host as they are: `msbctl add` asks, `msbctl edit` → Name & folder changes it (needs a rebuild), and `setup` sets the default.
- Choosing Claude Code also installs its ACP adapter, `claude-agent-acp`, so an editor can drive Claude in the sandbox over stdio (`msbctl exec . -- claude-agent-acp`); `msbctl update <name> -c claude` updates both, and existing sandboxes get it on a rebuild or that update.
- Claude Code in a sandbox trusts `/tmp` as well as the project, so an agent or ACP session started in scratch space is not stopped by the trust prompt; takes effect on the next start.

### Changed
- The project moved to https://github.com/runoverlabs/sandbox-manager and its documentation to https://sandbox-manager.runoverlabs.dev/; old GitHub links and existing installs keep working through GitHub's redirects, but the old github.io docs address does not.
- Naming the sandbox by the current folder (`.` or leaving the name out) no longer prints the sandbox it resolved to before running the command.

### Fixed
- Input piped into `msbctl exec` (`echo hi | msbctl exec . -- cat`) reaches the command instead of being swallowed, and starting a stopped sandbox no longer writes to its stdout, so it can carry a stream such as ACP.
- After a sandbox is stopped and started again, its SSH agent works again (signing, `git push`) instead of refusing every connection; no rebuild needed.

## [0.2.0] - 2026-10-07

### Added
- Documentation site at https://naerymdan.github.io/sandbox-manager/: install, getting started, guides, command and configuration reference, with search and light/dark themes; agents can read it through `llms.txt`, `llms-full.txt` or the Markdown copy beside each page.
- Sandboxes get `EDITOR=nano` (and nano itself), so Claude Code's `/memory`, `git commit` and friends open an editor instead of silently doing nothing; override it under `[env]`. Existing sandboxes need a rebuild.
- Inside a project folder msbctl knows which sandbox you mean: leave the name out where it is the only argument (`msbctl shell`, `msbctl stop`), use `.` where more follows (`msbctl exec . make`, `msbctl allow . example.com`), or `msbctl exec -- cmd`; `shell` and `exec` start in the matching subfolder of `/work`.
- `msbctl rename <name> <new>` and `msbctl move <name> <dir>` (also `edit` → Name & folder) rename a sandbox or point it at another project folder; a rename recreates the VM and keeps settings, secrets, Claude state, caches and container images, a move needs a rebuild.
- A git identity can name an ssh key to sign commits with (`setup` → Git identities); sandboxes using it sign through the filtered agent (and can verify their own signatures) while the key stays ticked in `msbctl keys`, which flags it and warns before you drop it. Existing sandboxes need a rebuild for `openssh-client` if `ssh-keygen` is missing.

## [0.1.1] - 2026-10-06

First release. msb-manager runs coding agents against real repositories in
[microsandbox](https://github.com/microsandbox/microsandbox) microVMs, without
giving them your network or your tokens.

### Isolation
- **Deny-by-default egress**, per host and per port. Named rule groups (`github`, `npm`, `python`, `go`, `claude`, `bun`, …) compose per project, and plain HTTP is refused outright.
- **Tokens never enter the VM.** `--secret` bindings put an opaque placeholder in the guest and substitute the real value host-side, into request headers only, for the hosts you name. `GH_TOKEN` and Claude's own credential work this way, and `msbctl secret` adds more.
- **A filtered SSH agent** per sandbox, forwarded over vsock: only identity-list and sign requests, limited to the keys you pick (`msbctl keys`). The private key never crosses.
- **A central `CLAUDE.md`** (shipped text plus your own additions) copied into every sandbox on each start from a read-only mount; each sandbox gets its own `~/.claude`.

### Managing sandboxes
- **One CLI and an fzf picker** (with a desktop entry) to register, start, stop, rebuild, purge, resize, shell into and run commands in sandboxes: `msbctl add`, `start`, `stop`, `rebuild`, `purge`, `shell`, `exec`, `resize`, `reclaim`, `ls`, `status`, `show`.
- **A setup wizard** that asks for features (bun, python, podman, gitleaks, …) rather than raw rule groups, preselects them from your repo's languages, and sizes the disks and package caches; `msbctl edit` and `msbctl setup` revisit any section later, and a first-run walk-through covers a new machine.
- **Per-project config that travels with the repo** (`.msb/sandbox.toml`, egress groups, packages, limits), with machine-local paths and tokens kept in `~/.config/msb/` and never committed. `msbctl config` shows the merged result and where each value came from.
- **Extra folders, package-cache disks and secrets** added after the fact (`msbctl mount`, `cache`, `secret`), and `msbctl allow` for one more egress rule.
- **Egress observe mode** (`msbctl observe <name> on`): when an allowlist is too tight to work in, stop blocking, record every host reached, then read it back with the exact `msbctl allow` lines for the hosts no rule covers. It leaves that sandbox's egress unrestricted until you switch it off.
- **Secret placeholders pass through to agent hosts**, so a coding agent that has read `$MSB_GH_TOKEN` no longer breaks its own API calls.
- **In-place updates** of claude, gh, gitleaks, bun and apt (`msbctl update`), with the versions recorded so a rebuild reproduces them, and a version display in the picker.

### Install and supply chain
- **`curl | sh` installer** (`get.sh`) and `msbctl self-update`, with sha256 verification of the release tarball.
- **Signed build-provenance attestations** on every release tarball and `get.sh`, verified by `get.sh` and `self-update` when an authenticated `gh` is installed (`MSB_MANAGER_SKIP_ATTEST=1` skips it; otherwise only the checksum is checked). See the README's "Verifying a release".
- **Verified toolchain installs inside the guest**: bun and gh are pinned release assets checked against their published checksums, and node comes from NodeSource's apt repository with a pinned signing-key fingerprint, instead of `curl | bash`.
- **CI, CodeQL, zizmor and OpenSSF Scorecard**, a tag-driven release workflow, Dependabot, issue forms, a security policy and a contributing guide.

### Upgrading from a checkout
- Rule groups changed: the Claude hosts now come only from the `claude` group, `bun` allows `github.com` instead of `bun.sh`, and `github` allows the Actions log host, Sigstore's trust root and GitHub's attestation storage (so `gh attestation verify` works from a sandbox). Existing sandboxes pick these up, along with the secret pass-through and the new installers, at their next `msbctl rebuild`.
