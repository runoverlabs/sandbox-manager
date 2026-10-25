---
title: Sandboxes without a folder
section: Guides
order: 52
description: A sandbox that clones its GitHub repo into a disk volume, whose policy is the repo's own .msb/ fetched at a pinned commit.
---

Read this when the project shouldn't live on this machine at all, as on a
[remote host](remote-hosts.md) or for [Kandev](kandev.md): the sandbox keeps
its own clone, and work leaves it with `git push`.

## Registering one

`msbctl add --repo owner/name` registers a sandbox that has no folder on this
machine. Its first start clones the repo into a disk volume
(`<name>-workspace`, at `/work`), with the sandbox's own GitHub token as a
placeholder, the same way every other token works. A rebuild finds the clone
there and leaves it alone, unpushed work included; `msbctl purge` deletes it.
Work leaves the sandbox with `git push` from inside it.

```console
$ msbctl add --repo acme/webshop --ref main -y
$ msbctl secret set webshop GH_TOKEN      # a private repo needs it to clone
$ msbctl start webshop
```

## Which `.msb/` governs

It's the copy msbctl fetched from GitHub at the pinned
commit, never the checkout inside the sandbox: editing `.msb/sandbox.toml` in
the guest changes nothing until it's pushed and `msbctl policy webshop update`
is run on the host. A rebuild stays on the pinned commit and fetches nothing,
so it can run unattended. A repo with no `.msb/` gets your defaults. A repo
can't set `conf`, and its `dev.yaml` follows the [same rules](configuration.md#msbdevyaml)
as a folder's.

## Changing one

`msbctl allow`, `secret add` and `edit` write to the registry entry, since
there's no checkout to edit, and what they add sits on top of the repo's rules
and bindings rather than replacing them. A change meant to last belongs in the
repo. `move` refuses: there is no folder. No ssh-agent is forwarded,
so `ssh_keys = []`, and git uses HTTPS with the token.

## Where the clone lives

`guest_path` can't be `"host"` (there's no host path) and can't contain a dot
(a disk volume can't be mounted there). The volume's size is `workspace_disk`
(`--workspace-disk`, default 20G), fixed when it's created.
