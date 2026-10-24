# Security policy

msb-manager exists to keep two things true: a sandbox can only reach the hosts
it was allowed, and a credential never enters the VM. A way around either is a
vulnerability, and so is a way for a sandbox to reach the host beyond what its
mounts and agent filter grant.

## Reporting

**Do not open a public issue.** Use GitHub's private report form:
<https://github.com/runoverlabs/sandbox-manager/security/advisories/new>

Include what you did, what you expected to be refused, and what happened
instead. A reproduction against a throwaway sandbox is ideal.

## In scope

- Egress reaching a host or port the sandbox's rules do not allow.
- A real token, key or secret readable inside the guest, or written to a log.
- The SSH agent filter forwarding a key it should have withheld or a request it
  should have refused.
- The installer or `self-update` installing something that failed its checksum.

## Out of scope

- Vulnerabilities in `msb` / microsandbox itself: report those to that project.
  If msb-manager's use of it is what makes the problem reachable, report it here.
- Anything that needs the attacker to already control the host account.

## Reviews

Whole-project reviews, so the next one can start from the diff since the last
baseline (`git diff <commit>..main`) instead of from scratch. What they found
and fixed is in `CHANGELOG.md`; anything still open is tracked privately until
it is fixed.

| Date | Baseline commit | Scope | How |
|---|---|---|---|
| 2026-10-24 | `3756a66` | `msbctl`, `msb-picker`, `bootstrap.sh`, installers, workflows | Split by attack surface: guest and untrusted repo → host, egress and secrets, remotes and Kandev, supply chain, command execution. Every finding was then challenged by an independent reviewer, and the high-severity ones were reproduced against msb 0.7.7. |

## Supported versions

Only the latest release is supported. Release assets carry a build-provenance
attestation: `gh attestation verify <file> --repo runoverlabs/sandbox-manager`.
