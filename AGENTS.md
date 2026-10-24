# AGENTS.md

This file provides guidance to coding agents (Claude Code, Codex, and anything else that reads `AGENTS.md`) when working with code in this repository. `CLAUDE.md` only imports it; edit this file.

## What this is

`msb-manager` manages [microsandbox](https://github.com/microsandbox/microsandbox) microVMs as per-project agent sandboxes: deny-by-default egress, credentials substituted host-side (never inside the VM), one CLI/picker to start, stop, rebuild and update them. Developed against `msb` 0.7.6, host now on 0.7.7 (behaviour re-checked on both); `msb --help` is more reliable than its published docs.

`msbctl` runs on the **host** and needs `/dev/kvm` plus the `msb` binary. The dev sandbox has nested KVM and can reach GitHub, so `msb` (the host's version) can be installed here from its GitHub release (`install.sh` from the release assets, checksum-verified) and `msbctl` run for real against throwaway sandboxes. Docker Hub answers from here while the sandbox has the `containers` group (`index.docker.io/v2/` gives the usual 401 auth challenge); where it is refused, load an image instead: `podman save --format oci-archive` then `msb load -i`, and create with `--pull never`. Use a throwaway `MSB_CONFIG_DIR`/`MSB_STATE_DIR`, and always `msb rm -f` what you create. Otherwise syntax-check with `python3 -m py_compile msbctl` and `bash -n`.

## Hard constraints

- **No dependencies.** Python 3.11+ stdlib (`tomllib`) and the `msb` binary only. No pip, no TOML writer. Registry entries are rendered whole from `templates/` and only read back via `tomllib`; the single exception is the `[versions]` table that `update` rewrites (`write_version_override()`).
- `.gitignore` blocks `*.env` and `secrets/`. Nothing machine-local or generated belongs in the repo.
- Comments in config/templates are the documentation (failure modes are non-obvious and cost debugging sessions). Preserve and extend them when changing behaviour; `msbctl --help` and `defaults.toml` are the user-facing docs.

- **Every behaviour change gets a one-line entry in `CHANGELOG.md`** under
  `## [Unreleased]`, and a matching page in `docs/content/` in the same PR if it is
  user-visible. `msb-release-ci` and `msb-docs` for the rest of that flow.

## Read the skill before the section you are changing

The detail lives in `.agents/skills/<name>/SKILL.md` — the harness-neutral skills
format, which pi discovers natively and resolves from any subdirectory up to the
repo root. pi puts every description in the system prompt and reads the file
itself when a task matches; other harnesses must
`read` the file named here. What stays in this file is only what has to hold in
every session — if a symptom below rings a bell, the fix is one file away.

| Skill | Read it when |
|---|---|
| `msb-egress` | any egress rule, `--net-rule` / `--tls-intercept`, `--secret`, `egress_mode`, the policy pin, or a connection out of a sandbox was refused |
| `msb-repo-layout` | you cannot find the code behind a behaviour, or you are adding a file, template or command |
| `msb-packaging` | the payload, `install.sh` / `get.sh` / `scripts/package.sh`, `dist/`, `self-update` |
| `msb-release-ci` | making any user-visible change, cutting a release, or CI / a mode / a payload check complains |
| `msb-docs` | a docs page, `--check` failing a link, anchor or `msbctl` subcommand section, or a screenshot |
| `msb-testing` | writing or debugging tests, or needing a live check of a mechanism |
| `msb-profile` | what an agent inside a sandbox is told, or why its context lacks something |
| `msb-repo-sandboxes` | `source = "repo"`: `add --repo`, policy fetch and pin, the workspace volume |
| `msb-wizard` | features, coding agents, `FEATURES`, `detect_features()`, a prompt or picker |
| `msb-edit` | `msbctl edit` sections, `rename` / `move`, secret storage, the `--json` interfaces |
| `msb-remotes` | remote hosts: `host serve` refusals, `host:name`, `ls` fan-out, `remote setup` |
| `msb-kandev` | any Kandev verb, its provisioning, its API pinning, `kandev reap` |
| `msb-setup` | machine-level settings, first run, named Claude tokens |
| `msb-pi-llm` | pi install or config, `[llm.<name>]`, how an endpoint's key reaches it |
| `msb-git-agent` | how a sandbox pushes, which key, what the SSH agent filter forwards |
| `msb-tool-bundles` | agent tool bundles: `~/.config/msb/tools/`, `[defaults] tools`, their rules/env/adapters, or a tool an agent is missing |

## Layout

Orientation only; the *why* of each area is in the skill named on its row.

| Path | What it is |
|---|---|
| `msbctl` | single-file Python CLI (~12,600 lines): `Sandbox` (config resolution, `msb` flag emission), `cmd_*` handlers, `main()` argparse at the bottom, fzf menu with numbered-prompt fallback |
| `msb-picker` | fzf picker used by the desktop entry (`msb-manager.desktop`) |
| `bootstrap.sh` | runs once **inside the guest** at create, piped over stdin so manager code stays out of the VM; deliberately not `set -e`; parameterized by `MSB_*` env vars |
| `defaults.toml` | what msb-manager ships: egress rule groups, version pins, baseline defaults. Read from the checkout, never copied |
| `templates/` | the `.in` skeletons install.sh seeds once: `config`, `sandbox`, `dev.yaml`, `registry`, `registry-repo` (no folder), `registry-kandev` |
| `.msb/` | this repo's own sandbox policy (`sandbox.toml`, `dev.yaml`) |
| `profile/` | the SHIPPED central CLAUDE.md → `msb-profile` |
| `install.sh`, `get.sh`, `scripts/package.sh`, `VERSION` | install, the curl-piped entry point, `dist/` build, release version → `msb-packaging` |
| `docs/`, `assets/`, `scripts/screenshots/` | the documentation site, the logo, the README's pictures → `msb-docs` |
| `tests/`, `spikes/` | stdlib unittest suite with fake `msb`/`tailscale`, and re-runnable mechanism spikes → `msb-testing` |

## The current folder names a sandbox

`sandbox_here()` resolves an omitted name (or `.`) to the registered sandbox whose `project` contains the cwd, deepest wins; the registry decides, never a `.msb/` alone, and two entries on one folder are an error. `main()` applies `resolve_here()` to `args.name`/`args.names` for every verb but `_agent-filter`, and rewrites `exec --` to `exec . --`. A name is optional (`nargs="?"`/`"*"`) ONLY where it is the sole positional; where another positional follows it stays required and `.` is the shorthand, so nothing is ever ambiguous (`observe on` must not mean the sandbox "on"). `guest_workdir()` maps the cwd to the same subfolder of the guest project path for `shell`/`exec`.

## Where the project is mounted

`Sandbox.guest_project` is the registry entry's `guest_path` (`"host"` = the host path, `"/work"`, or an absolute path; default from `[defaults]`, else `/work`), validated by `guest_path_problem()`. Registry-only — a host path must never reach the committed `sandbox.toml`. Everything that names the guest project goes through it: the mount, `--workdir` at create (overrides the committed `dev.yaml`), `guest_workdir()`, Claude's folder trust in `ensure_profile()` and pi's in `ensure_pi()`, bootstrap's `MSB_PROJECT_DIR`, and the extra-mount overlap check (`parse_mount_spec(spec, project_dest)`). Never hard-code `/work`; use `GUEST_PROJECT` only as the default.

## Configuration model

Four TOML files, later wins:

1. `<repo>/defaults.toml` — shipped: egress rule groups, pins, baselines (updates with `git pull`)
2. `~/.config/msb/config.toml` — the operator's overrides only, merged over (1): tables merge key by key, anything else (incl. a rule group) is replaced whole. `msbctl config` shows the result and each value's origin
3. `<project>/.msb/sandbox.toml` — committed, portable, no host paths or tokens
4. `~/.config/msb/sandboxes/<name>.toml` — machine-local paths and overrides

Put new defaults and rule groups in `defaults.toml`, never in the template skeleton. A group only the operator's `config.toml` defines (`machine_only_groups()`) is machine-local: `add` and `edit` → Features write it to the registry's `extra_rule_groups` (`split_groups()`), which ADDS to `rule_groups`, is not pinned, and brings `allow_private_dns` when listed in `private_dns_groups`; never into a project's `sandbox.toml`, where every other clone would die on "unknown rule group".

A project's `dev.yaml` is **never passed to msb**: msbctl reads its `image:` line (validated as an OCI reference by `image_problem()`, because msb boots a host directory given as the image — spike 12) and nothing else, and create/rebuild refuse a file with any other top-level key than `CONF_KEYS_READ` or any nested line (`conf_problems()`). msb's `--conf` is code, not data: it mounts host paths, copies host files in and interpolates `${VAR}` from msb's own environment, which holds the bound secrets, and the project folder is writable from the guest. Everything is emitted as flags instead (egress as verified `--net-rule` flags from the `sandbox.toml` group list). `conf` must stay inside the project. The operator's escape hatch is `msb_conf` in the registry entry (registry-only, absolute path, no `${`). Env overrides: `MSB_CONFIG_DIR`, `MSB_STATE_DIR`.
