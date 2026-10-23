---
name: msb-wizard
description: "The msbctl add feature wizard: FEATURES mapping each feature to the egress groups, apt packages and bootstrap switches it needs, the separate AGENTS list for coding agents, detect_features() preselecting from GitHub linguist languages at 5% of bytes, pick_caches() and pick_disks(), machine_only_groups() and private_dns_groups, and the toggle_list() termios menu versus numbered-input paths that tests rely on. Use when adding or changing a feature, a coding agent, a wizard step or a prompt."
---

# Wizard

Detail carved out of `AGENTS.md`, which keeps only what has to hold in
every session. Repo-specific throughout; the facts here are verified against
msb 0.7.6 and re-checked on 0.7.7.

`msbctl add` asks for *features*, not raw egress groups. `FEATURES` in `msbctl` maps each one to the egress groups, apt packages and bootstrap switches it needs (e.g. `bun` → `bun` group + `bun = true`; `gitleaks` is opt-in, never preselected; `podman` → `containers` group + packages + a storage follow-up). A feature's `languages` are GitHub linguist names; `detect_features()` reads the repo's languages from the GitHub API and preselects features at ≥5% of bytes. Add a new feature there rather than teaching users to tick a group and a package separately. Coding agents are a separate `AGENTS` list (`claude`, preselected, and `pi`, opt-in); an agent is installed only if ticked, so add new ones there plus an installer step in `bootstrap.sh` and a `GUEST_PROBES`/`UPDATERS` row. Groups neither list owns still get their own toggle. Package caches (`pick_caches()`) are named disk volumes, kept across rebuilds and deleted by `purge`. After features, `pick_disks()` asks for the root disk size (small/medium/large/custom around the usual 16G) and, if podman is in, a container disk — or none, which means `fuse-overlayfs` on the rootfs. Single-choice prompts use `choose_one()`; all multi-choice prompts go through `toggle_list()`: a stdlib `termios` menu (arrows/jk, space, enter) on a terminal, numbered input otherwise — keep both paths working, since tests pipe stdin.
