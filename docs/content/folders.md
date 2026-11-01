---
title: Folders & ports
section: Guides
order: 42
description: Where the project appears inside a sandbox, extra host folders, and reaching a server running in it.
---

Read this when the agent needs a folder other than the project, absolute
paths that match the host, or when you want to open something the sandbox
serves.

## Where the project appears in the sandbox

By default the project is mounted at `/work`. `msbctl add` asks where it
should appear, and `msbctl edit` → "Name & folder" changes it:

- **the same path as on the host.** Absolute paths in compiler errors, stack
  traces and an agent's output are then valid on both sides, so your editor (or
  an ACP client) can open them as they are. A `msbctl move` takes the mount
  along with it.
- **`/work`.** This keeps your folder layout and username out of the guest.
- **any other absolute path.** Not inside a system folder (`/usr`, `/etc`, …)
  and not over a whole one like `/home` or `/tmp`.

It's stored as `guest_path` in the registry entry (`"host"`, `"/work"` or the
path), never in `.msb/sandbox.toml`, because a host path is one person's
machine. Set the default for new sandboxes in `msbctl setup` → "Defaults for
new sandboxes". A change needs a rebuild, and Claude Code keeps its sessions
and memory per path, so the ones from the old path stay behind.

## Extra folders

```console
$ msbctl mount . ~/reference                      # read-only at /mnt/reference
$ msbctl mount . ~/datasets:/data --rw --rebuild  # read-write, at /data, now
```

Extra host folders are read-only unless you ask, and read-write ones show your
own ownership, like `/work`. Host paths are machine-local, so they're stored in
the registry entry, never in the project. Like every mount, they're fixed at
create time.

## Reaching a server in the sandbox

```console
$ msbctl port . 8080 --restart        # http://localhost:8080 reaches :8080 inside
$ msbctl port . 3000:5173             # host 3000 to a dev server on 5173
$ msbctl port .                       # list them; --rm 8080 removes one
```

`msbctl port` (with no arguments) and `msbctl show` make each tcp port's host
side a clickable hyperlink to `http://127.0.0.1:<host>/` on a terminal, and
`show --json` adds a `port_urls` map of each port to its URL.

Inside, the server has to listen on `0.0.0.0` — `python3 -m http.server 8080
--bind 0.0.0.0`, `vite --host 0.0.0.0` — because msb connects to the guest's
own address and a server bound to `localhost` is never reached. On the host the
port binds to `127.0.0.1` only; `0.0.0.0:8080:8080` opens it to your network,
and `msbctl` says so. The connection comes in rather than going out, so the
egress rules don't apply. Ports are stored in the registry entry, not the
project, since a host port is one machine's to hand out; `msbctl` warns when
another sandbox already publishes the same one. A change needs no rebuild: the
sandbox keeps its state and has the new ports from its next start, or at once
with `--restart`. `msbctl edit` → "Published ports" changes them too.
