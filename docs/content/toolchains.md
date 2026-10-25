---
title: Toolchains & project setup
section: Guides
order: 44
description: Extra packages, a setup script and environment variables for a project, package caches, and podman inside a sandbox.
---

Read this when a project needs more than the features the wizard offers: its
own packages or setup step, faster installs, or containers.

## Project setup and environment

```toml title=".msb/sandbox.toml"
[bootstrap]
packages = ["postgresql-client"]       # extra apt packages
script   = "scripts/sandbox-setup.sh"  # run last, inside the guest, from the project folder

[env]
SOME_PROJECT_FLAG = "1"                # merged over the machine-wide [env]
```

The setup script runs once, at create time, after everything else, for things
like `npm ci`. A failure is reported, not fatal. Environment variables are
create-time, like mounts.

## Package caches

Each package manager can get its own disk for its download cache: `npm`,
`bun`, `python` (pip), `rust` (cargo registry) and `go` (module cache).

```toml title=".msb/sandbox.toml"
[caches]
npm = "5G"
```

Each is a named disk volume, `<sandbox>-cache-<key>`. It's as fast as the root
disk, capped at its size, **kept** across rebuilds and deleted by `purge`.

```console
$ msbctl cache .                # usage per cache
$ msbctl cache . clear npm      # empty one (all of them without a key)
```

A volume's size is fixed when it's first created. Change it in the config later
and msbctl keeps the existing size and warns you; `msbctl cache . clear` then
recreates it at the new size.

> **Note:** The caches mount at `/mnt/cache/<key>`, and the bootstrap symlinks
> the tool's usual directory (such as `/root/.npm`) to it. That detour is
> deliberate: msb refuses a named-volume mount whose guest path contains a dot.

## Containers inside a sandbox (podman)

The `podman` feature installs podman and opens the `containers` egress group.
podman then needs somewhere to keep images. The root filesystem is an overlay
that podman's overlay driver can't sit on, so pick one of:

- **a container disk** (`containers_disk = "20G"`): a named volume at
  `/var/lib/containers`. Fast, and pulled images survive rebuilds. This is the
  recommended option.
- **fuse-overlayfs** (`containers_storage = "fuse-overlayfs"` under
  `[bootstrap]`, plus the package): no extra disk, slower.

With neither, podman falls back to `vfs`: slow, and about three times the disk.
The wizard asks.
