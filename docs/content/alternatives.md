---
title: Compared with alternatives
section: Guides
order: 15
description: How msb-manager differs from other coding-agent sandboxes such as jailoc, by which part of the agent threat each one closes.
---

Several tools put a coding agent in a box. They differ less in features than in
**which threat they set out to stop**, so this page compares them on that first.
Each entry was written from the other project's own code and documentation at
the version named. If one has moved on, tell us and the page will follow.

## The frame: the lethal trifecta

Simon Willison's [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)
is the clearest way to compare these tools. An agent becomes exploitable once it
has all three of:

1. **private data**: your code, your tokens, your keys;
2. **untrusted content**: issues, web pages, package READMEs, any of which can
   carry injected instructions;
3. **a way out**: any network request that can carry data somewhere.

No sandbox removes leg 2, because reading untrusted content is the agent's job.
A sandbox can only shrink leg 1, what the agent can read, and leg 3, where it can
send it. Every tool below does some of leg 1. What separates them is whether
they close leg 3 and whether the credentials count as leg 1.

msb-manager's answer, in brief (the whole of it is in
[How it works](how-it-works.md#the-security-model-in-one-table)):

- **Leg 3 is closed by default.** Egress is an allowlist per host and per port.
  A host no rule group names is unreachable, and that includes public ones.
- **Credentials are taken out of leg 1.** Tokens and SSH keys never enter the
  VM. The guest holds a placeholder, and the real value is used on the host.
- **The policy can't be widened from inside.** The firewall is msb's, on the
  host, and the project's policy is pinned and approved there.

What remains is anything the agent can reach *through* a host you allowed, and
the project folder itself. Choose rule groups with that in mind.

## jailoc

[jailoc](https://github.com/seznam/jailoc) (Seznam, compared at v1.19.0) is the
closest project in shape: a per-workspace CLI that runs a headless
[OpenCode](https://opencode.ai/) agent in Docker Compose, with its own Docker
daemon beside it. It's a single Go binary and runs anywhere Docker does,
including macOS.

Its goal is narrower, and its docs say so: it protects your **internal
network** and your **host filesystem**. The public internet is deliberately
left open, and exfiltration to a public server is listed as out of scope.

### Security model

| | jailoc | msb-manager |
| --- | --- | --- |
| Isolation boundary | a Docker container on the host kernel: UID 1000, all capabilities dropped, `no_new_privs`, a PID limit | a microVM with its own kernel |
| Egress default | **allow**; private ranges (RFC 1918, link-local, CGNAT) are dropped | **deny**; only hosts in the project's rule groups, per port |
| Allowing an internal host | `allowed_hosts` / `allowed_networks`, resolved to addresses once at start | a rule in a [rule group](egress.md), matched by name |
| Who enforces it | iptables written by the container's own entrypoint, as root with `NET_ADMIN`, before it drops privileges | msb, on the host; nothing in the guest can change it |
| Docker for the agent | a privileged Docker-in-Docker sidecar running a rootless daemon, on by default | podman inside the VM, as a feature |
| Tokens | the real value, as an environment variable or a file under `/run/secrets` | a placeholder; the value is substituted on the host, into headers, for named hosts only ([Credentials & SSH](credentials.md)) |
| Agent's own API keys | readable by the agent, in its mounted config | the Claude credential is a placeholder; a pi endpoint's key stays on the host ([Your own models](models.md)) |
| SSH | the host's whole agent socket, plus `known_hosts` read-only | a per-sandbox filter that lists and signs with the keys you picked |
| Host git config | `~/.gitconfig` mounted read-only by default | not mounted; the identity is set inside the guest |
| Where policy lives | the user's own config only | committed in the project, then [pinned and approved](egress.md#the-policy-pin) on the host |

### Features

| | jailoc | msb-manager |
| --- | --- | --- |
| Host platforms | Linux and macOS (Docker Desktop, OrbStack, Rancher), amd64 and arm64 | Linux with `/dev/kvm` |
| Install | one Go binary, `go install`, a Nix flake | Python 3.11 standard library and `msb`; [install](install.md) |
| Coding agents | OpenCode | Claude Code, and [pi](models.md) for your own models or any provider |
| Agent session | `opencode serve` stays up in the container, and you attach from the host; a dropped terminal loses nothing | the agent runs in your `msbctl shell` session |
| Image | a Dockerfile cascade: a preset image, a Dockerfile by path or URL, a per-workspace overlay, an embedded fallback | an OCI image, then a bootstrap driven by the features you pick |
| Project folders | several per workspace, each at its host path | one project at `/work` or its host path, plus extra [mounts](commands.md#msbctl-mount) |
| Corporate TLS proxies | forwards the host's CA bundle | per model endpoint only (`ca_cert`) |
| Filtering internal DNS names | an optional CoreDNS sidecar | not needed for egress, which is an allowlist; DNS rebind protection is on unless a rule group needs private addresses |
| Finding a missing rule | edit the config and restart | [`msbctl observe`](commands.md#msbctl-observe) logs instead of blocking, then [`msbctl allow`](commands.md#msbctl-allow) |
| Other machines | none | [remote hosts](remote-hosts.md) and [Kandev](kandev.md) |

### Choosing between them

**Pick jailoc** if you're on macOS, if OpenCode is your agent, or if you trust
the public internet with your code and only need to keep the agent away from
your internal network and your home folder. It's also less work to start with,
because nothing has to be allowlisted.

**Pick msb-manager** if leaking your code or tokens to a public host is part of
the threat. That covers most prompt-injection payloads, which send data to an
attacker's server rather than to your LAN. It also fits if you want a VM rather
than a container as the boundary, or the policy to travel with the repo and be
approved on the host.

Things jailoc does that msb-manager doesn't yet are tracked as issues: agent
sessions that survive a disconnect
([#113](https://github.com/runoverlabs/sandbox-manager/issues/113)), and
forwarding a host CA bundle
([#112](https://github.com/runoverlabs/sandbox-manager/issues/112)).
