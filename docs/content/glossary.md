---
title: Glossary
section: Reference
order: 30
description: The words these pages use with a specific meaning, from agent filter to workspace volume, each with where to read more.
---

The words these pages use with a specific meaning. Each one links to where it's
covered in full.

| Term | Means |
| --- | --- |
| **agent filter** | the per-sandbox process on the host that stands in front of your SSH agent. It lists and signs only with the keys you picked, and nothing reaches the guest but its answers. [Credentials & SSH](credentials.md#ssh-the-filtered-agent) |
| **`base`** | the rule group every sandbox gets, always first: DNS, the Ubuntu mirrors over HTTPS, and a deny of plain HTTP. [Rule groups](egress.md#rule-groups) |
| **bootstrap** | `bootstrap.sh`, run once inside a new sandbox to install its packages, node, the agents and what its features ask for. It reports every failure at the end rather than stopping at the first. [The bootstrap](how-it-works.md#the-bootstrap) |
| **create time** | when the VM is made, by the first `start` or a `rebuild`. Egress rules, mounts, the image and environment variables are fixed then, so changing one needs a rebuild. [Create time vs. restart](how-it-works.md#create-time-vs-restart) |
| **egress** | connections from the sandbox out. Deny-by-default: only what a rule allows gets out. [Network & egress](egress.md) |
| **feature** | what the wizard offers instead of raw rules: `python`, `podman` and so on. Each brings its packages *and* the rule groups it needs. [Get started](quickstart.md#2-register-a-project) |
| **guest** | the inside of the VM. The **host** is the machine running it, where msbctl, your config and your tokens live. |
| **guest path** | where the project folder appears inside the guest: `/work`, the host's own path, or one you choose. [Folders & ports](folders.md#where-the-project-appears-in-the-sandbox) |
| **identity** | a git name and email, and optionally keys to sign or push with, from `[identities]` in your config. It's applied inside the guest at the lowest level, so a repo's own identity wins. [Configuration](configuration.md#identitiesname) |
| **machine-local group** | a rule group only your `config.toml` defines. It goes in the registry entry (`extra_rule_groups`), never in the project, because nobody who clones the project has it. [Hosts on your network](egress.md#hosts-on-your-network) |
| **model endpoint** | an `[llm.<name>]` entry: a server or provider pi talks to, whose key stays on the host. [Your own models](models.md) |
| **observe mode** | a sandbox with blocking switched off and every host it reaches recorded, to learn what it needs. Set on this machine only. [Finding out what a sandbox needs](egress.md#finding-out-what-a-sandbox-needs) |
| **placeholder** | what a secret looks like inside the guest: `$GH_TOKEN` holds a stand-in, and msb swaps the real value in on the host, in headers, for the hosts it's bound to. The agent can use it but never read it. [Credentials & SSH](credentials.md#secrets-usable-never-visible) |
| **policy** | the part of `.msb/sandbox.toml` that decides what leaves the sandbox or what it takes from the host: rule groups, rules, secret bindings, resources. [The policy pin](configuration.md#the-policy-pin) |
| **policy pin** | the record of the policy you last approved. A create or rebuild that finds the policy changed shows the difference and asks first, so the sandbox can't widen its own egress. [The policy pin](egress.md#the-policy-pin) |
| **profile** | the central `CLAUDE.md` every sandbox's agent gets: msb-manager's text, your additions, and a "This sandbox" section. [The agent's instructions](instructions.md) |
| **project** | the folder a sandbox is for, shared into it read-write. Its `.msb/` holds the portable, committed settings. |
| **registry entry** | `~/.config/msb/sandboxes/<name>.toml`: one per sandbox, machine-local, never committed. It holds host paths, keys, identity and anything that overrides the project. [The registry entry](configuration.md#the-registry-entry) |
| **remote** | another machine running sandboxes for this one, addressed as `host:name`. [Remote hosts](remote-hosts.md) |
| **repo sandbox** | a sandbox without a folder: it clones its GitHub repo into a disk volume, and its policy is the repo's `.msb/` at a pinned commit. [Sandboxes without a folder](repo-sandboxes.md) |
| **rule** | one egress line, `allow@github.com:tcp:443`. First match wins. [The rule grammar](egress.md#the-rule-grammar) |
| **rule group** | a named list of rules (`github`, `npm`, your own) that a project picks from. [Rule groups](egress.md#rule-groups) |
| **secret binding** | a variable bound to the hosts its real value may be sent to, `ENV@HOST`. [More secrets](credentials.md#more-secrets) |
| **tool bundle** | a capability (web search, page reading) your own endpoints provide, given to agents from `~/.config/msb/tools/`. [Agent tools](agent-tools.md) |
| **workspace volume** | a repo sandbox's disk, where its clone lives. It survives a rebuild; `purge` deletes it. [Sandboxes without a folder](repo-sandboxes.md#where-the-clone-lives) |
