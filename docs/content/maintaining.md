---
title: Maintaining a sandbox
section: Guides
order: 46
description: Resizing without a rebuild, versions and updates, renaming or moving a sandbox, and autostart.
---

Read this when a sandbox you already have needs to change: more memory, newer
tools, a new name or folder, or to start on its own.

## Resizing without a rebuild

```console
$ msbctl resize . --cpus 8 --memory 16G     # needs a restart; asks first
$ msbctl resize . --root-disk 32G           # grows live; shrinking is refused
```

`resize` uses `msb modify`, so the sandbox keeps its state. The new values are
written to the registry entry, so a later rebuild reproduces them.

## Versions and updates

Component versions are pinned in `defaults.toml` under `[versions]` (node's
major, `gh`, `gitleaks`, `bun`), and the image is pinned by digest.

```console
$ msbctl ls --refresh                  # check upstream (cached for 6 hours)
$ msbctl update . -c claude gh apt     # in place
```

`update` records what it installed in the registry entry's `[versions]` table,
so the next rebuild reproduces it rather than silently going back. Delete an
entry there to return to the default. The **image** can't be updated in place:
change its digest in `.msb/dev.yaml`, then rebuild.

The upstream checks use the anonymous GitHub API (60 requests an hour). A
`GH_TOKEN` in `secrets/global.env` is used for them if present.

## Renaming a sandbox, or moving its project

```console
$ msbctl rename old-name new-name
$ msbctl move . ~/src/the-new-place
```

msb can rename neither a sandbox nor a volume, so a **rename** removes the VM
and creates it again under the new name, at the cost of a rebuild.
Everything msbctl keeps under the name moves with it: the registry entry, its
secrets, the Claude state and the version cache. Package caches and container
images are kept too: the entry's `volumes` key keeps pointing at the existing
disks, and that old name stays reserved until you rename back.

A **move** points the sandbox at a different folder, for example after you
moved the checkout on disk. The old folder may already be gone. If the new
folder has no `.msb/`, msbctl offers to copy it over, re-detects the GitHub
repo, and offers the rebuild the new mount needs.

Both are also in `msbctl edit` → "Name & folder".

## Autostart

Mark a sandbox to start whenever the picker opens:
`msbctl edit .` → "Identity & autostart". `msbctl start --autostart` starts
that set from anywhere; on a host with nobody at it, `msbctl host autostart
install` runs it at boot (see [Remote hosts](remote-hosts.md#setting-up-a-host)). An idle sandbox costs about 300 MB,
and a running one is the only kind whose installed versions can be checked.
