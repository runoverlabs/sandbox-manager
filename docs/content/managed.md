---
title: Managed clients
section: Guides
order: 58
description: Let a second orchestrator own sandboxes on a host Kandev already uses, with its own key, names, limits and egress, and no view of anyone else's.
---

A [Kandev host](kandev.md) runs sandboxes for one orchestrator, Kandev, through
its own ssh key. When a second orchestrator (a CI runner, say) wants
sandboxes on the same host, it gets the same machinery under its own name: a
`[clients.NAME]` table in `config.toml`, a key authorized with `--client NAME`,
and the `msbctl managed` verbs, protocol 2. Kandev keeps protocol 1
(`msbctl kandev`) exactly as it was. Nothing changes on a host that runs
Kandev alone.

Each client's sandboxes are a world of their own:

- A client's key lists, shows, stops and purges its own sandboxes and nothing
  else. Another client's sandbox, or one of yours, is `not_found` to `show` and
  `stop`, and `absent` to `purge`, as a name with nothing under it would be, so
  a purge is no way to learn what exists.
- Its sandboxes are named with its own prefix (`c-` for `ci`, by default), carry
  its own msb label (`msbctl.owner=ci`), count against its own limits, and get
  the egress its own table allows. New sandbox names of yours can't start with
  any configured prefix.
- Which client a key is comes from the forced command in `authorized_keys`
  alone. A `--client` in the command it sends may only repeat that; one that
  names another client is refused with exit 126.

Everything else is shared, and described on the [Kandev hosts](kandev.md)
page: the [TLS proxy](kandev.md#the-tls-proxy), its certificate and lease key,
the [reaper](kandev.md#the-reaper), the [workspace disk](kandev.md#the-workspace-disk),
[names on your LAN](kandev.md#names-on-your-lan) and
[private images](kandev.md#private-images). As there, in proxy mode nothing
listens on `base_url`'s own port and there is no `/health` URL:
[check a host](kandev.md#checking-a-host) with `msbctl managed health` over ssh
and a real lease.

## Who decides what

Three parties, and a line between each. The operator (you, on this host) sets
the ceilings and owns what is shared or held here. The client sets up its own
sandboxes inside them. What runs in a guest is trusted with nothing: every
rule below is enforced by msb, outside it, whoever chose it. The client is
trusted, but its key lives on another machine, so each limit is what a stolen
key could not get past.

| What | Operator (host) | Client (its key) | Guest |
| --- | --- | --- | --- |
| Capacity | `max_sandboxes`, `max_cpus`, `max_memory`; `[managed]` totals | sizes each sandbox within them | – |
| Egress | the ceiling: `rule_groups`, `allow_extra`, `private_names` (`["*"]` hands over all of it) | `egress_allow`, `private_names`, `callback`, within the ceiling | only what the sandbox allows |
| The client's own secrets | – | values, hosts, and the only `headers` they go in; a new value live | holds a placeholder; the value goes into headers to those hosts alone |
| Placeholders in bodies | `body_secret_hosts` | – | sent only there, never anywhere else |
| Model endpoints | `[llm.<name>]`: host, port, CA, private name and key, all stored here; `llms` grants them | picks granted ones (`llms`) | reaches them; never sees the key |
| Trusting a CA | `allow_upstream_ca` (on); never for an endpoint whose key it holds | sends one for its own hosts (`upstream_ca`) | – |
| `/dev/kvm` | `allow_nested_virt` | asks for it (`nested_virt`) | gets it only then |
| Image, env, ports, lease | – | its choice (`guest_ports` default from its table) | – |
| The proxy's certificate | gives it to one client (`tls`) | that client installs it (`tls install`) | – |
| The proxy, msbctl itself | `restart-proxy`, `self-update` (and Kandev's key) | – | – |
| Host paths, host credentials, other sandboxes | never handed out | never reachable | never reachable |

## Setting a client up

1. Set the host up for Kandev as on the [Kandev hosts](kandev.md#setting-a-host-up)
   page, as far as its host-wide keys: `serve`, `proxy_listen`, `base_url` and
   the port pools, and `msbctl host kandev install` for the proxy and the
   reaper. Kandev itself may stay off (`[kandev] enabled = false`).
2. Give the client a table:

   ```toml title="~/.config/msb/config.toml"
   [clients.ci]
   enabled       = true
   max_sandboxes = 4
   allow_extra   = ["pypi.org", "llm.example.org"]
   env_prefix    = "CI_"
   guest_ports   = [8765]
   ```

   Or, from a script, `msbctl host managed configure --client ci --enabled
   --allow-extra pypi.org --allow-extra llm.example.org --env-prefix CI_
   --guest-port 8765`, which edits only the keys it is given and refuses a
   result that doesn't check out, leaving the file as it was.
3. Authorize the client's key:

   ```sh
   msbctl host authorize "ssh-ed25519 AAAA… ci@example" --client ci
   ```

   That writes `restrict,command="…/msbctl host serve --client ci" <key>`.
   It warns when `[clients.ci]` is missing, does not check out or is not
   enabled, since the key would be refused every verb but `managed health`,
   and writes the line all the same.
4. From the client, `ssh host msbctl managed health` answers
   `{"protocol": 2, "client": "ci", "enabled": true, …}`.

## The `[clients.NAME]` table

A client's name is a-z first, then a-z, 0-9 and `-`, at most 16 characters;
`folder`, `repo` and `managed` are taken. Every key starts from the shipped
`[kandev]` value, so a new client gets Kandev's default limits and egress
groups, and is off until `enabled = true`.

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | the client may create sandboxes only when true. Otherwise every verb but `health` answers `denied`, and the proxy serves none of its sandboxes. While its table does not check out (`enabled = "false"`, say), new leases stop, and the proxy keeps the ports its sandboxes have open but opens no new ones: a client you disabled stays closed, and after the proxy restarts it has none until the table is fixed. Leases already issued stay valid until they expire. This is what a broken `[kandev]` has always done; `msbctl doctor` says so |
| `max_sandboxes`, `max_cpus`, `max_memory` | `12`, `32`, `"96G"` | its own limits, summed over its own sandboxes; another client's never count |
| `rule_groups` | `["github", "npm", "python", "claude"]` | egress each of its sandboxes gets, after `base` |
| `allow_extra` | `[]` | what a request's `egress_allow` may add, as for [Kandev](kandev.md#the-kandev-section), and where its `callback` may point |
| `private_names` | `[]` | hostnames a request may have resolved to a private address, as for [Kandev](kandev.md#names-on-your-lan) |
| `name_prefix` | its first letter and `-` (for a name starting with `k`, its first two letters or digits: `kube` gets `ku-`) | its sandboxes' name prefix: a-z, up to 6 more of a-z 0-9, then `-`. `k-` is always Kandev's, on every host, and refused here. No two clients may share one, so two clients with the same first letter must set it (and `k` alone must). `host managed configure` refuses a new one while the client still has sandboxes under the old: purge them first |
| `env_prefix` | `"AGENTCTL_"` | the prefix of agentctl's environment variables, and of its nonce (`<prefix>BOOTSTRAP_NONCE`). A request's own env and secrets may not use it. Never `MSB_`, `MSBCTL_`, `LD_`, `SSH_`, `XDG_` or `LC_` |
| `guest_ports` | `[8765, 41001, 41002, 41003]` | the guest ports a provision publishes when it names none: 1 to 4 ports, 1024-65535 |
| `require_callback` | `false` | whether a provision must name a callback; leave it off for a client that is never called back, so nothing is pinned in its guests' `/etc/hosts`. A callback is egress to one address and port, so `allow_extra` must admit it either way, and a name admitted only by a hostname pattern (or `*`) must resolve to a public address unless it is in `private_names`, while `*` admits any address given as one, private included ([below](#protocol-2)) |
| `body_secret_hosts` | `[]` | hosts a secret's placeholder may travel to in a request body; see [below](#secrets-in-request-bodies) |
| `allow_nested_virt` | `false` | whether its provisions may ask for `/dev/kvm` (`"nested_virt": true`), as for [Kandev](kandev.md#kvm-in-a-sandbox). Never from this host's `[defaults]` |
| `tls` | `false` | whether its key may install the proxy's certificate; see [below](#the-proxys-certificate). One client at most, and never set in Kandev's table |
| `llms` | `[]` | `[llm.<name>]` endpoints of this host its provisions may pick; see [below](#model-endpoints) |
| `allow_upstream_ca` | `true` | whether its provisions may send a CA to trust for one of their own hosts; see [below](#a-servers-own-ca) |

Kandev's own table is `[kandev]`, or `[clients.kandev]`, but not both. Its
`name_prefix`, `env_prefix`, `guest_ports`, `require_callback` and
`body_secret_hosts` are fixed at what protocol 1 has always been (`k-`,
`AGENTCTL_`, its four ports, a required `kandev_api`, Anthropic's hosts), and
another value is refused.

A client's table holds only the keys above. The host's keys (`serve`,
`proxy_listen`, `base_url`, `port_pool`, `proxy_port_pool`) are shared by every
client, so one in any `[clients.NAME]`, `[clients.kandev]` included, is refused
rather than read: they go in [`[managed]`](#the-managed-table).

A problem in `[clients]` is the problem of the clients it concerns: their
verbs answer `invalid_config`, and Kandev and every other client go on. That
holds for a table that does not check out (a value of the wrong type
included, such as `rule_groups = [["base"]]`), for a table whose name is not a
client name, for an entry under `[clients]` that is not a table (`[clients]
foo = 1`), and for two clients that share a prefix, such as `ci` and `cd`
with the default `c-`, which stops both of them until one sets its own.
Asking for `k-` stops that client and never Kandev. A table that does not
check out still holds the prefix it asks for, so no other client, and no
sandbox of yours, takes it meanwhile. Only a problem in the host's keys
(`[managed]`, or those `[kandev]` holds) stops every client.
A `[clients]` that is not a table at all (`clients = 1` before any table)
names no client: Kandev goes on with its `[kandev]`, and no other client is
configured until it is fixed.

`msbctl doctor` reports all of these under `clients`. Under a client's key,
its own problems are reported, and a clash only as one, without naming the
other client. At the host, doctor also warns under `client-prefixes` when a
client's prefix is already the start of a sandbox of yours, which can happen
when a table is written by hand: `host managed configure` refuses to set
such a prefix. The client's provision of that environment answers `conflict`,
which says the name is taken but not what it is. Rename the sandbox, or give
the client another prefix.

## The `[managed]` table

The keys that exist once per host, whichever clients use it.

| Key | Meaning |
| --- | --- |
| `serve`, `proxy_listen`, `base_url`, `port_pool`, `proxy_port_pool` | as on the [Kandev hosts](kandev.md#the-kandev-section) page. A host set up before `[managed]` keeps them in `[kandev]`, which still works; one key in both tables is refused |
| `max_sandboxes`, `max_cpus`, `max_memory` | optional totals over every client's sandboxes, Kandev's included. Unset, there is none. A provision must fit its client's limits and these, or it answers `rate_limited` |

`msbctl host managed configure` without `--client` sets these. A client's
`health` reports the totals' use in `host_capacity`: how many sandboxes, CPUs
and how much memory every client's sandboxes hold together, never whose.

## Secrets in request bodies

msb blocks every outbound request that carries a secret's placeholder
(`$MSB_<VAR>`) to a host the secret is not bound to, and only ever puts a
real value into headers. An agent that once prints its environment has the
placeholder in its transcript, and an LLM client sends the whole transcript
with every request, so from then on every request to its model endpoint is
blocked. Kandev's sandboxes let the placeholder through to Anthropic's hosts.

`body_secret_hosts` names the hosts a client's sandboxes may send it to in a
body: its model endpoints, say. Each must be an exact, lowercase hostname
the client can reach: one its `allow_extra` admits (a pattern like
`*.example.org` covers it, and an `address:port` entry admits that address),
one an `allow@` rule in its `rule_groups` (or `base`) names or covers, or one
of its `private_names`. The trade-off: those hosts see the
placeholder's text, never the real value, which still goes only into headers
for the secret's own hosts. Empty, the default, lets it go nowhere.

## The proxy's certificate

There is one certificate, so one client's key installs it: Kandev's, until
another client's table sets `tls = true`
(`msbctl host managed configure --client NAME --tls`). From then on that
client renews it with `msbctl managed tls install`, as Kandev's
[`tls install`](kandev.md#the-tls-proxy) does, and the Kandev key's is
`denied`. It needs no Kandev key and no `[kandev] enabled`, and it brings none
of the host's other verbs (`restart-proxy`, `self-update`): a new pair is
picked up by the running proxy. Two tables that set it are both
`invalid_config`, and while they do no client's key installs it; the operator
always may, at the host.

## Secrets in headers

Each secret in a request may name the only headers msb fills it in:
`{"name": "LLM_KEY", "value": "…", "hosts": ["llm.example.org"], "headers":
["x-api-key"]}`. Without `headers`, msb fills it into every header sent to its
hosts, so an allowed host that echoes a header the guest chose back would
hand the guest the real value. Names are letters, digits and `-`, up to 16,
compared without case. The scope is fixed at provision: `start` sends the
values only. `health` lists the `secret_headers` feature on a host that takes
it.

## Model endpoints

An agent like pi needs a model endpoint, and its key. Rather than each client
carrying one, the operator defines it once, as for their own sandboxes: an
[`[llm.<name>]` table](models.md) with its URL, port, `ca_cert`, `private_dns`
and the key stored here (`LLM_KEY_<NAME>` in `global.env`). `llms = ["qwen"]`
grants it to a client (`msbctl host managed configure --client NAME --llm qwen`),
and a provision that names it (`"llms": ["qwen"]`) gets everything it takes:

- the egress rule to its host and port, and TLS interception on that port
- its `ca_cert` trusted for that host alone, and its name allowed to resolve
  privately with `private_dns`
- its key bound to that host alone, read from this host at provision and at
  every `start`, so it never travels through the client. A start of a running
  sandbox with its secrets sends the key as stored now, so a key you replace
  reaches it live
- the endpoint as a passthrough host of every binding: it receives the agent's
  whole transcript, placeholders and all

`health` lists each granted endpoint under `client_settings.llms`: its name,
`base_url`, models and the like, and `key`, the placeholder to put in pi's
`models.json` (`$LLM_KEY_QWEN`; empty when no key is stored). Never the key or
a path. Naming one that is not granted is `denied`; once a grant is revoked, a
sandbox that uses it is refused `start`.

## A server's own CA

Every sandbox's HTTPS goes through msb's interceptor, which checks the server's
certificate against the public roots. A server with a private certificate
fails that. A provision may send the CA to trust for one of its own hosts:
`"upstream_ca": [{"host": "git.example.org", "ca_pem": "-----BEGIN CERTIFICATE-----…"}]`,
up to 8, each trusted for that host alone, and kept on this host until the
sandbox is removed. The host must be one its `egress_allow` (or `callback`)
names, and never an endpoint whose key the operator holds here: a CA there
could take that key. `allow_upstream_ca = false` refuses all of them.

A secret allowed on a port besides 443 (`"egress_allow": ["llm.example.org:8443"]`
for a secret bound to `llm.example.org`) has that port intercepted too, or the
secret would never be substituted there. Interception is per port, not per
host: any other host reached on that port is intercepted as well, and one with
a private certificate then needs its CA here.

## Protocol 2

`msbctl managed <verb>` is protocol 1's [verbs](kandev.md#the-verbs) with these
differences:

- `health` adds `protocols` (`[2]`, or `[1, 2]` for the Kandev key), `client`,
  `client_settings` (its `name_prefix`, `env_prefix`, `guest_ports`,
  `require_callback`, `body_secret_hosts`, `allow_nested_virt`, `tls`: whether
  this key installs the certificate, `allow_upstream_ca`, and `llms`, the
  [model endpoints](#model-endpoints) granted), the features `secret_headers`,
  `live_secrets`, `llms`, `upstream_ca` and `secret_ports`, and `host_capacity` when
  `[managed]` sets totals. Its capacity, egress and proxy ports are the
  client's own. A client with no table answers `enabled: false`.
- `provision` takes an optional `callback` `{host, port}` (`kandev_api` is the
  same key under its protocol-1 name; giving both is refused), checked as
  `kandev_api` is when given. Its rule lets the guest reach that address and
  port, so the client's `allow_extra` must admit it. An address is admitted by
  an address or CIDR entry (any port), an address:port entry (that port
  only), or `*`: for an address given as one, `*` admits any, private and
  reserved included, as it trusts the client with everything. A name is
  resolved on the host, and admitted when an address, CIDR or address:port
  entry covers the address it resolves to (the operator's explicit choice).
  Otherwise it needs a hostname pattern that matches it (any port), and for a
  name `*` counts as a pattern: then that address must be public, or the name
  in the client's `private_names`. That is what the same name in
  `egress_allow` would reach: the rule pins the address, so msb's DNS rebind
  protection never sees it. Loopback, link-local, RFC 1918, CGNAT
  (`100.64.0.0/10`, which a MagicDNS name resolves to), ULA and the other
  reserved ranges are not public. A name that no entry could admit (no
  pattern or `*` matches it, and no IPv4 address, CIDR or address:port entry
  at its port could hold its answer: a name resolves to IPv4 only) is
  refused without being looked up. Otherwise the provision is `invalid_config`
  naming `callback`, before anything is created. Kandev's `kandev_api` is its
  trusted API and is not checked against `allow_extra`, as in protocol 1.
  With none there is no pinned rule and no
  `/etc/hosts` line, at provision or at start. A client that is never called
  back (an orchestrator that only drives its sandboxes) should send none: a
  pinned name gets a connection through but not a secret, since msb
  substitutes only on an address it resolved itself (see
  [names on your LAN](kandev.md#names-on-your-lan)). Kandev's `kandev_api`
  stays required, in either protocol.
  `guest_ports` may name 1 to 4 guest ports; as many host ports and proxy ports
  are allocated. Kandev's stay its four, so under the Kandev key any others
  are refused. Every record carries `client`.
- `agentctl` takes env keys `<env_prefix>…` only, passes the nonce only as
  `<env_prefix>BOOTSTRAP_NONCE`, writes the binary to `/opt/NAME/agentctl`,
  and its `runtime_port` defaults to the first published guest port.
- `ls --json` and `show --json` give a row `source` `managed`, `client`,
  `location` `NAME:ENV`, and the record under `record`. Kandev's rows keep
  `kandev`, byte for byte.
- `start` of a sandbox that is already running, with its secrets (exactly the
  ones it binds, as for any start), hands msb the new values live, nothing
  restarted: a rotated token reaches it now, not at its next start. Each
  binding keeps its hosts and header scope. A refusal is `unavailable`, and
  the sandbox keeps the old values; with no secrets, `start` answers as before.
  Protocol 1's `start` still answers a running sandbox without touching it.
- `tls install` is only the key's of the client [given it](#the-proxys-certificate).
  `restart-proxy` and `self-update` are not here: they act for the whole host,
  and one client must not disturb another. They stay with the Kandev key and
  the operator.

Exit 126 from `managed health` means a host that predates protocol 2, or a
key not authorized with `--client`. `kandev health` lists the
`managed_namespace` feature on a host that speaks it.

## Before you remove a client or downgrade

- The reaper removes a client's orphaned VMs only while its table exists and
  checks out. Purge a client's sandboxes before removing its table.
- An msbctl from before protocol 2 does not know `source = "managed"` entries,
  and `msbctl ls` there fails on them. Purge every managed client's sandboxes
  before a downgrade. (A client's key can't downgrade: `self-update` is not
  among its verbs.)
