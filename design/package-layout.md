# msbctl as a package: the decision, and what goes where

Decided 2026-10-26. Status: **accepted, not yet started**. Step 0 (below) comes
first, inside the single file.

## Why

`msbctl` is one 15,400-line file, with ~575 functions and ~210 module
constants. That was the right shape at 1,900 lines. Now it shows two
symptoms, both seen when the first non-GitHub repo went through `msbctl add`
(see `non-github-forges-and-agents.md`):

- **A concept has no home, so every caller re-derives it.** "The repo" is a
  bare string. About 30 sites ask `bool(box.repo)` and assume that means
  GitHub. `cmd_add` builds a new sandbox out of local variables and makes its
  own decisions instead of asking `Sandbox`, so the wizard and a running
  sandbox can disagree.
- **Nothing marks a boundary.** Any function can reach any global, so a new
  case gets bolted on at each call site rather than added in one place.

A package does not fix the first by itself. The rules below do. But one file
gives those rules nowhere to live and nothing to enforce them.

## What was decided

**A package with a tiny launcher. No build step, and nothing assembled into
one file.**

```
msbctl               the launcher: ~10 lines, puts its own folder on sys.path,
                     calls msb_manager.cli.main(). Still the command, still
                     what install.sh links and what authorized_keys names.
msb_manager/         the code
```

The alternatives, and why each lost:

| Option | Why not |
|---|---|
| `zipapp` (stdlib) into one file | It builds a binary zip that you cannot read or grep on a host. A `--dev` checkout would need a build after every `git pull`. `__file__` points inside the zip, so finding `defaults.toml`/`templates/` breaks. And it buys nothing: see below |
| A homemade amalgamator (concatenate modules, SQLite-style) | The committed `msbctl` becomes generated, giving two sources of truth. Traceback line numbers would not match the sources, and cross-module `from x import y` would have to be banned |
| Stay one file, with stricter section banners | That is the status quo. Nothing enforces a banner |

**"Single file" was never what shipped.** The payload (`scripts/package.sh`,
`install.sh`) is a tree already: `msbctl msb-picker bootstrap.sh defaults.toml
templates profile spikes …`, and `msbctl` finds its siblings through `HERE`. A
package directory is one more `PAYLOAD` entry. The hard constraint is **no
dependencies** (stdlib + `msb`), and that is unchanged.

## The rules: what goes where

1. **One concept, one home, one parser.** Every value read from a file or
   typed by a person gets exactly one module that parses it into an object.
   Every other module asks that object and never re-parses the string. Examples:
   the repo (`forge.RepoRef`), an image reference, an egress rule, a mount
   spec, a port spec, a size.
   *Smell:* a regex or `.startswith()` on a registry value outside its home
   module. Move it.
2. **Import modules, not names.** `from msb_manager import ui`, then
   `ui.ask(...)`. Never `from msb_manager.ui import ask`. A caller that looks
   the name up on the module at call time is what lets a test patch one
   attribute and have every caller see it. It also keeps call sites
   self-describing.
3. **Layers point down.** A module imports only from its own layer or lower.
   `tests/test_layout.py` checks this with `ast`, so it is enforced rather
   than remembered. Layers, lowest first:

   | Layer | Modules |
   |---|---|
   | 0 base | `paths`, `ui`, `tomlio`, `shell` |
   | 1 stores | `config`, `secretstore`, `keyring` |
   | 2 domain | `forge`, `egress`, `images`, `mounts`, `sshkeys`, `llm`, `bundles` |
   | 3 model | `sandbox` (the `Sandbox` class: resolution and `msb` flags) |
   | 4 mechanisms | `guest` (per-boot `ensure_*`), `profile`, `pi`, `policy`, `agentfilter`, `lifecycle`, `observe` |
   | 5 verbs | `wizard`, `edit`, `setup`, `display`, `versions`, `doctor`, `hostserve`, `remotes`, `kandev/`, `menu`, `completion` |
   | 6 entry | `cli` (argparse, `main()`, `preflight`) |

4. **A verb lives with its domain.** `cmd_allow` goes in `egress`, `cmd_keys`
   in `sshkeys`. `cli.py` only wires argparse to them.
5. **The wizard and `edit` ask `Sandbox`, never decide on their own.** `add`
   builds a draft entry and puts the same questions to the same properties
   (`wants_github`, `wants_component("claude")`, `repo.kind`) that a start
   does.
6. **Machine paths live in `paths` and are read as `paths.X`.** They are
   computed from `HOME`/`MSB_CONFIG_DIR`/`MSB_STATE_DIR` when the module is
   imported. Tests get a fresh copy by dropping every `msb_manager*` entry
   from `sys.modules` and importing again, which is the package form of
   today's `load_msbctl()`. `paths.ROOT` (the checkout or install) and
   `paths.MSBCTL` (the launcher) replace every `os.path.realpath(__file__)`.
   Those re-exec sites, `host serve`, the agent filter daemon and the
   `authorized_keys` line, must name the launcher, never a module file.
7. **Comments move with their code.** The comments are the documentation
   (AGENTS.md). A move that drops a comment block is a regression.
8. **Size is a hint, not a rule.** A module past ~1,500 lines, or one that
   needs a "section" banner, should probably be two.

### Where each part of today's `msbctl` goes

| Today (line ~) | Goes to |
|---|---|
| paths and constants (100–260) | `paths`, plus the constants' own domain modules |
| output, toml, shell, msb state (930–1046) | `ui`, `tomlio`, `shell` |
| secrets / keyring / env files (1047–1460) | `secretstore`, `keyring` |
| dev.yaml, image refs (1460–1535), `available_digest` | `images` |
| `Sandbox` (1537–2540) | `sandbox` |
| `load_config`, `sandbox_here`, workspaces (2539–2640, 10015) | `config` |
| agent filter (2644–2870) | `agentfilter` |
| ssh keys and pickers (2874–3220) | `sshkeys` |
| profile, bundles, pi (3220–3725) | `profile`, `bundles`, `pi` |
| identity, git push, checkStat, guest repos, podman (3725–4085) | `guest` |
| lifecycle, create, bootstrap payload (4084–4880) | `lifecycle` |
| policy pin, repo policy fetch (4151–4560) | `policy` (GitHub API calls → `forge`) |
| rename / move (4882–5103) | `lifecycle` |
| TOML key editor (5217–5370) | `tomlio` |
| rules, `cmd_allow` (5371–5550) | `egress` |
| observation log (5550–5910) | `observe` |
| mounts, ports (5909–6237) | `mounts` |
| secret verbs (6238–6640) | `secretstore` (verbs) |
| setup sections, Claude tokens, identities (6637–7690) | `setup` |
| edit sections (7690–8560) | `edit` |
| ls / show / status (8581–8960, 14160–14300) | `display` |
| versions, update (9009–9356) | `versions` |
| `checkouts`, `parse_github_url`, `github_repo`, `github_languages` | `forge` |
| prompts and menus (9417–9690) | `ui` |
| sizes, disks, caches, resources (9666–9830) | `wizard` (the sizes themselves in `ui`) |
| FEATURES, AGENTS, `pick_features`, `cmd_add`, `cmd_add_repo` (9829–10575) | `wizard` |
| restricted / host serve / authorize / autostart (10574–11390) | `hostserve` |
| doctor (10839–11260) | `doctor` |
| Kandev (11390–13440) | `kandev/` (`core`, `proxy`, `tls`) |
| remotes (13443–14160) | `remotes` |
| menu, completion (14297–14876) | `menu`, `completion` |
| argparse, `main` (14877–) | `cli` |

## Order of work

0. **Inside the single file (needs no packaging):** `RepoRef` as the one
   parser of `repo`, used everywhere `box.repo` is read today, and a draft
   `Sandbox` for the wizard. This is the cleanup that matters for forges, and
   it shrinks the later moves.
1. **Skeleton.** Launcher + `msb_manager/cli.py` holding everything, moved
   verbatim. `paths.ROOT`/`paths.MSBCTL` for the `__file__` sites. Harness
   reload of the package. `PAYLOAD` (both copies), `install.sh`'s item check,
   `scripts/check.sh`, `package.sh`'s `py_compile`, the CodeQL copy step (no
   longer needed: the files are `.py`), the docs workflow's path filter.
   No logic changes.
2. **One area per PR, behaviour unchanged**, bottom layer up: `ui`, `tomlio`,
   `shell`, `paths` → stores → domain → `sandbox` → mechanisms → verbs. Each
   PR moves code, updates the tests' patch targets (54 `patch.object` sites,
   ~500 `self.m.X` reads, 131 names) to the defining module, and adds its
   modules to the layer test. Same tests, same output.
3. **Then the forge work** (`non-github-forges-and-agents.md`, phases 2–3), in
   the new layout.

When step 1 lands, update `AGENTS.md`'s layout table and the `msb-repo-layout`
skill (which still says ~1,900 lines) to point here.

## Decided along the way

- **`repo` stays the only registry key for a sandbox's repository.** It holds
  `owner/name` for GitHub, as today, and the URL as given for anything else.
  `forge.RepoRef.parse()` is its only reader. Every existing entry keeps
  parsing as GitHub, and there is no second key to keep in step.
- The package is `msb_manager`, and the command stays `msbctl`.
- The module is `secretstore`, not `secrets`, so it never shadows the stdlib's
  `secrets` for a reader.
- Within the package, "remote" keeps its existing meaning (another host
  running msbctl). A repository's server is a **forge**.
