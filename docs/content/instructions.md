---
title: The agent's instructions
section: Guides
order: 38
description: The central CLAUDE.md every sandbox gets, your additions to it, and the per-sandbox section msbctl writes.
---

Read this when you want every agent to know something, or need to see what a
sandbox's agent has been told.

## Your CLAUDE.md additions

`~/.config/msb/CLAUDE.local.md` is appended to msb-manager's shipped
instructions, and the result is copied into every sandbox's `~/.claude` on each
start. Edit it from the main menu ("edit your CLAUDE.md additions") or directly.
Editing the copy *inside* a sandbox does nothing: it's overwritten on the next
start.

## The "This sandbox" section

Each sandbox's copy also ends with a short "This sandbox" section, written by
msbctl: one line per feature it has (podman, python, …), with the npm feature
a note that npm 12 runs no package's install scripts unless allowed (so a
missing native binary isn't taken for a refused download), how git reaches
GitHub, and where the project is mounted — including its `.agents/skills/`
folder, because this file lives in the agent's home and a project that splits
its instructions across skill files has to be pointed at them by absolute path.
It's built from the current config on every start, so after an edit that still
needs a rebuild it describes the sandbox you'll get, not yet the one that's
running. `msbctl edit <name>` → "View the CLAUDE.md it gets" shows the whole
file as that sandbox will receive it.
