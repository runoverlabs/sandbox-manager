# Non-GitHub forges, and following through on the agent choice

Plan written from a first `msbctl add` against a self-hosted Forgejo
(`ssh://git@git.vild.party:2222/vincent/cell.git`) with only pi as agent.
Line numbers are from `msbctl` at bcdad82.

## What went wrong, and why

The root cause is a single variable. `repo` in `cmd_add` (and in the registry
entry) means "GitHub owner/name", and every later step keys off it being truthy.
A URL that `parse_github_url()` (9389) does not recognise passes through
unchanged (`parse_github_url(repo) or repo`, 10164), so everything downstream
treats the Forgejo URL as a GitHub slug:

| Symptom in the transcript | Where |
|---|---|
| `git clone git@github.com:ssh://git@git.vild.party:2222/vincent/cell.git.git` | `url = f"git@github.com:{repo}.git"` (10178) |
| clone target `cell/cell.git` | `repo.split("/")[-1]` keeps `.git` (10168) |
| "could not read languages from GitHub" | `detect_features()` → `api.github.com/repos/<url>/languages` |
| `github` feature ticked | `[defaults] rule_groups = ["github", "claude"]` preselects it no matter the remote |
| "Git push: gh / ssh" asked, both GitHub-only | `pick_git_push()`; `ensure_git_push()` only rewrites `github.com` |
| GitHub PAT step, "Only select repositories -> ssh://…" | `want_github = bool(repo)` (10276) |
| `secrets.github = true` written to sandbox.toml | `SECRET_GITHUB=want_github` → GH_TOKEN bound for a repo with no GitHub |
| profile tells the agent "git reaches GitHub over gh" | `sandbox_profile_section()`, plus the GH_TOKEN paragraphs in `profile/CLAUDE.md` |

The agent choice has the same problem in a different form. It is made inside
`pick_features()`, after the identity, push and key steps. Of the steps that
depend on it, only "Models for pi" checks it:

| Symptom | Where |
|---|---|
| "Claude token" asked for a pi-only sandbox | gated on `len(tokens) > 1` only (10267) |
| start reads (and can keyring-prompt for) the Claude token of a pi-only sandbox | `global_secret_vars()` adds it whenever `claude_auth == "secret"` (2481). `secret_env()` already checks `wants_component("claude")` |
| "Claude Code keeps its sessions per path" in the guest-path step | `pick_guest_path()` wording |
| claude preselected, pi only if `[defaults] llm` | `AGENTS` `opt_in` hard-coded; no operator default for agents |
| `~/.claude` seeded in a sandbox without Claude | `ensure_profile()` is unconditional (4076) |

Not GitHub-related, but seen in the same run:
- **Image digest:** `available_digest()` gives up on a registry that refuses
  anonymous pulls, which a private Forgejo registry does, and then says only
  "could not resolve a digest". It should say why: "registry refused anonymous
  access (private?)". There is also an open question to settle with a live
  check: can msb pull a private image at all, and with which credentials?
- **First run (cosmetic):** the cancel was intentional (Esc). A bare `WARNING: ` was left above it, and
  the exit message lost its `msbctl: ` prefix. Probably the menu's cursor-up
  erase clearing stderr text (stderr is separate from stdout's buffer); not
  reproduced yet. Low priority.

## Model: a parsed repo reference, not a GitHub slug

Add `RepoRef.parse(text) -> RepoRef | None`, the only reader of `repo` (see
`package-layout.md`, rule 1), with these fields:

```
kind      "github" | "forgejo" | "gitlab" | "generic"
host      git.vild.party
ssh_port  2222 (None for the default)
path      vincent/cell                 (owner/name, ".git" stripped)
url       the clone URL exactly as typed, or built from github owner/name
```

- Accepts `https://`, `ssh://user@host[:port]/path`, scp-style `user@host:path`,
  and bare `owner/name` (GitHub, as today).
- Detecting the kind on the host during the wizard, never fatal:
  `github.com` → github, `codeberg.org` → forgejo; otherwise a 5 s probe of
  `https://<host>/api/v1/version` (Forgejo/Gitea) then `/api/v4/version`
  (GitLab). If neither answers, `generic`. A `[forges."<host>"] kind = "…"` table
  in config.toml can override the guess. That is one more table the operator
  writes; msbctl only reads it.
- Registry: `repo` is still the only key. It holds `owner/name` for GitHub,
  as today (so every existing entry parses unchanged), and the URL as given for
  any other forge. Every `bool(box.repo)` that means "is on GitHub" becomes
  `box.repo_ref.kind == "github"` (or `.has_github`).
- `add --repo` (`source = "repo"`: policy fetch, in-guest clone) stays
  GitHub-only for now and dies with a clear message for any other forge
  (phase 3).
- Wizard prompt: `repo (URL, or owner/name for GitHub; blank for none)`.
  `github_repo(project)` becomes `checkout_repo(project)` and offers the
  checkout's own origin, whatever forge it is on.

## Each step, by forge and by agent

Move the **agents** question up, to right after the repo, so every later step
can check it. Add `[defaults] agents = [...]` (defaults.toml: `["claude"]`) so
the preselection follows the operator. Unticking every agent stays valid: you
get a plain dev sandbox.

| Step | github | forgejo / gitlab / generic |
|---|---|---|
| Clone | `git@github.com:owner/name.git` (unchanged) | the URL as typed; target from `path`'s last segment. If `[host]:port` is missing from `~/.ssh/known_hosts`, say so before cloning, because the guest's known_hosts is a read-only copy of it |
| Guest path | "Claude Code keeps its sessions per path" | wording follows the chosen agents ("agent sessions are kept per path"), dropped when there are none |
| Git push | gh / ssh, as today | no question. Note: "git uses the remote as it is: ssh through the forwarded agent". With an identity `push_key`, write a `Host <host>` stanza (with `Port`) with `IdentitiesOnly`, i.e. `GUEST_PUSH_SSH_CONFIG` generalised to the forge host. An https remote with no token is fetch-only, so say that |
| SSH keys | unchanged | unchanged, plus a hint that the push key must be ticked |
| Features: `github` | preselected per defaults | not preselected. Only ticked by hand, for gh against other repos |
| Forge egress | `github` group | if a configured rule group already allows `host:443` / `host:ssh_port` (here, `forgejo`), preselect it under "Other egress groups". If none does, offer to write `allow@<host>:443` and `allow@<host>:<ssh_port>` into the registry's `extra_rules` (machine-local, not pinned). If the host resolves to a private address on this machine, say that `allow_private_dns` is needed too, and why (msb drops LAN answers, which reads as NXDOMAIN). Ship a `codeberg` group in defaults.toml |
| Languages | GitHub API | Forgejo/Gitea `GET /api/v1/repos/{path}/languages` has the same `{lang: bytes}` shape, so it slots straight into `suggest_features()`. GitLab `/api/v4/projects/{urlenc path}/languages` gives percentages; normalise them. Fallback for every forge, private repos included: after a clone, or with a checkout present, total `git ls-files` bytes by extension → linguist name (a small map for the languages `FEATURES` already names) |
| Models for pi | if pi ticked | same. If pi is ticked and `[llm]` is empty, say pi has nothing to talk to and point at `msbctl setup` |
| Claude token | only if `claude` ticked (and >1 token, as today) | same |
| Forge token | GitHub PAT, as today | phase 3. `SECRET_GITHUB` is false either way |
| Profile | unchanged | "This sandbox" names the forge and how push works (ssh via agent, host:port), and says plainly that there is no GitHub token here. Move the GH_TOKEN paragraphs of `profile/CLAUDE.md` into the generated section, so a sandbox with no GitHub token is not told to use one |

Outside the wizard, the same agent gating applies:
- `global_secret_vars()`: add the Claude token var only when
  `wants_component("claude")`. This fixes a keyring prompt or autostart
  refusal over a token nothing uses.
- `ensure_profile()`: skip when claude is off (pi has its own `ensure_pi()`).
- `msbctl setup` / first run: ask which agents you use. With no Claude, do not
  push Claude login as the first thing to do. It writes `[defaults] agents`.
- `msbctl edit` → Claude token / GitHub token sections: show "not used by this
  sandbox" instead of offering to set one, when the agent or forge is absent.

## Phases (one PR each, CHANGELOG line + docs page each)

1. **Stop the damage.** Small, and mostly bug fixes.
   - `RepoRef` with kind detection by hostname only (no probe yet), every
     `box.repo` reader moved onto it, and a correct clone URL and target folder.
   - For non-GitHub, skip: the GitHub token step, the git push question,
     `SECRET_GITHUB`, the `github` preselect, and the GitHub languages call.
   - Agents asked first; gate the Claude token step and `global_secret_vars()`
     on claude; add `[defaults] agents`.
   - Reword the guest-path note, and the digest-refusal message.
   - Tests (stdin-piped wizard): Forgejo ssh URL with port, pi-only, no
     agents, GitHub unchanged.
2. **Make a forge work, not just stop asking.**
   - Forge egress preselect / `extra_rules` offer + private-DNS hint.
   - Per-host push key ssh stanza.
   - Forgejo/GitLab languages + the local-checkout fallback.
   - API kind probe + `[forges]` override.
   - Profile text per forge.
   - Live check in the dev sandbox against Codeberg over ssh:22 and https.
3. **Forge API access.**
   - A Forgejo/GitLab token step that mirrors the GitHub one: what to create
     and with which scopes, bound as `FORGEJO_TOKEN@<host>` /
     `GITLAB_TOKEN@<host>` through the existing secret bindings. These are
     header-only, and Forgejo accepts `Authorization: token …`.
   - Optional `tea` / `glab` features.
   - Credential helper for https remotes on that host.
   - `add --repo` for Forgejo (raw file API for the policy fetch, https clone
     with the token).

## Open questions

(Decided: `repo` holds a full URL for a non-GitHub forge, with no new key;
see `package-layout.md`.)

- GitLab in scope, or Forgejo/Gitea (Codeberg + self-hosted) only for now?
- Should the wizard write `extra_rules` for an unknown forge host, or only
  suggest the `msbctl allow` command?
