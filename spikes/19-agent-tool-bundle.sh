#!/usr/bin/env bash
#
# 19-agent-tool-bundle.sh — does a tool bundle actually reach an agent?
#
# msbctl derives the rules, the environment and the adapter installation from a
# bundle folder (docs/content/agent-tools.md). Two things that derivation cannot
# prove in a unit test:
#
#   1  pi loads the adapter as written, through its OWN extension loader — the
#      jiti transform plus the aliased imports — with no `npm install` anywhere,
#      and both tools work. This runs on the host against the bundle's pi.ts:
#      what msbctl copies is this file byte for byte, so if it loads here it
#      loads in the guest, where the same loader finds it in ~/.pi/agent.
#   2  A live sandbox actually has the env, both adapter files, and a route to
#      the endpoints: the search called from INSIDE the guest, which is the only
#      place the emitted egress rules apply.
#
# PASS (step 1) is: loads, registers the expected tools, a real search returns
# results, a real read returns text, and the two failure halves say why (no
# endpoint named in the message; an unreadable page reported rather than thrown).
#
# Step 2 needs a sandbox with the bundle attached: SPIKE_SANDBOX=<name>. It
# changes nothing — it only looks around — but it does call the endpoints for
# real, twice. SPIKE_LIVE=1 calls them once each from the HOST in step 1, which
# is the only check of the adapter's own logic rather than its registration.
#
# Observed 2026-10-24 on pi 0.73.1, node v22, host against
# ~/.config/msb/tools/web: step 1 PASS, with SPIKE_LIVE=1 too (a real search and
# a real read from the host, 772 + 698 chars of prompt for the two tools). Step 2
# has not been run yet: it needs /dev/kvm, msb and a sandbox created with the
# bundle enabled — run it there before trusting the derivation end to end.
#
# Needs: node and pi for step 1 (pi's loader is found via npm root -g).

set -uo pipefail

BUNDLE="${BUNDLE:-$HOME/.config/msb/tools/web}"
TOOLS="${TOOLS:-websearch webread}"
QUERY="${QUERY:-microsandbox microVM}"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0

[ -f "$BUNDLE/bundle.toml" ] || { echo "no bundle at $BUNDLE (BUNDLE=...)"; exit 1; }
[ -f "$BUNDLE/pi.ts" ] || { echo "no pi adapter at $BUNDLE/pi.ts"; exit 1; }

# ---------------------------------------------------------------- step 1: pi
say "1  the adapter under pi's own loader"

PI_ROOT="$(npm root -g 2>/dev/null)/@earendil-works/pi-coding-agent"
LOADER="$PI_ROOT/dist/core/extensions/loader.js"
[ -f "$LOADER" ] || { echo "   pi's extension loader not found at $LOADER"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat >"$WORK/load.mjs" <<'EOF'
// Load one adapter file the way pi does, then call its tools. Endpoints come
// from the bundle's [env] as they would from the sandbox's environment.
import { pathToFileURL } from "node:url"
import { readFile } from "node:fs/promises"

const [loader, file, ...want] = process.argv.slice(2)
const dir = file.slice(0, file.lastIndexOf("/"))
if (!process.env.SPIKE_MISSING) {
  for (const [, key, value] of (await readFile(`${dir}/bundle.toml`, "utf8"))
    .matchAll(/^([A-Z][A-Z0-9_]*)\s*=\s*"([^"]*)"/gm)) process.env[key] ??= value
}

const { loadExtensions } = await import(pathToFileURL(loader).href)
const { extensions, errors } = await loadExtensions([file], process.cwd())
if (errors.length) {
  console.log(`   FAIL  did not load: ${errors.map((e) => e.error?.message ?? e.error).join("; ")}`)
  process.exit(1)
}
const tools = [...extensions[0].tools.values()].map((t) => t.definition)
console.log(`   ok    loaded, registering ${tools.map((t) => t.name).join(", ")}`)
const call = (name, params) => tools.find((t) => t.name === name)
  .execute("spike", params, undefined, () => {}, { cwd: process.cwd() })
  .then((out) => out.content.map((c) => c.text).join("\n"))
let rc = 0
for (const name of want) {
  const tool = tools.find((t) => t.name === name)
  if (!tool) { console.log(`   FAIL  ${name} is not registered`); rc = 1; continue }
  // What the model pays for on every request. An MCP server's 27 definitions
  // cost ~28k characters; this is the number that made the extension the answer.
  console.log(`   ok    ${name}: ${JSON.stringify(tool.description).length
    + JSON.stringify(tool.parameters).length} chars of prompt`)
  if (!tool.promptSnippet) console.log(`   note  ${name} has no promptSnippet`)
}
if (rc === 0 && process.env.SPIKE_LIVE && !process.env.SPIKE_MISSING && want.length > 1) {
  // The endpoints, once each, from the host: the adapter's own logic, not just
  // its registration. Step 2 does the same from inside a sandbox, where the
  // egress rules apply as well.
  const search = await call(want[0], { query: process.env.QUERY || "microsandbox microVM", maxResults: 3 })
  const url = /https?:\/\/\S+/.exec(search)?.[0]
  const page = url ? await call(want[1], { url, maxChars: 1200 }) : ""
  const good = search.length > 40 && url && page.length > 100
  console.log(`   ${good ? "ok" : "FAIL"}    ${want[0]}: ${(search.split("\n")[0] || "").slice(0, 70)}`)
  console.log(`   ${good ? "ok" : "FAIL"}    ${want[1]} read ${url || "(no url in the output)"}: ${page.length} chars`)
  rc = good ? 0 : 1
}
if (rc === 0 && process.env.SPIKE_MISSING) {
  // The failure half, which is the half an agent cannot work out for itself:
  // inside a sandbox a bare error reads as a network problem.
  let msg = ""
  try { await call(want[0], { query: "x" }) } catch (error) { msg = String(error.message) }
  const named = msg.includes(process.env.SPIKE_MISSING)
  console.log(named ? `   ok    with no endpoint, ${want[0]} names ${process.env.SPIKE_MISSING}`
                    : `   FAIL  with no endpoint, ${want[0]} said: ${msg || "nothing — it did not fail"}`)
  rc = named ? 0 : 1
}
process.exit(rc)
EOF

if command -v node >/dev/null && node "$WORK/load.mjs" "$LOADER" "$BUNDLE/pi.ts" $TOOLS; then
  step1=0
else
  step1=1
fi
if [ "$step1" -ne 0 ]; then
  note "step 1 FAILED"
  fail=1
fi

# The same calls with the endpoints unset must name the variable, not just fail:
# inside a sandbox "connection refused" sends you looking for a network problem.
# The tools must read their endpoints at call time, so this loads fine and then
# fails by naming the variable rather than by refusing to connect.
say "   the failure half: no endpoint"
env -u WEB_SEARCH_URL -u WEB_FETCH_URL SPIKE_LIVE= SPIKE_MISSING=WEB_SEARCH_URL \
  node "$WORK/load.mjs" "$LOADER" "$BUNDLE/pi.ts" $TOOLS || fail=1

# ---------------------------------------------------------------- step 2: live
if [ -z "${SPIKE_SANDBOX:-}" ]; then
  say "2  SKIPPED: SPIKE_SANDBOX=<name> of a sandbox with this bundle attached"
  note "checks the rules msbctl emitted, both adapter files in the guest, and a"
  note "search called from inside it, where only the emitted egress rules apply"
else
  say "2  the live sandbox $SPIKE_SANDBOX"
  hosts="$(sed -n 's/^hosts = \[\(.*\)\]$/\1/p' "$BUNDLE/bundle.toml" | tr -d '[:space:]\"' | tr ',' ' ')"
  show="$(msbctl show "$SPIKE_SANDBOX" 2>&1)"
  for h in $hosts; do
    host="${h%%:*}"; port="${h##*:}"; [ "$port" = "$host" ] && port=443
    if grep -q "allow@$host:tcp:$port" <<<"$show"; then
      note "ok    show lists allow@$host:tcp:$port"
    else
      note "FAIL  show does not list allow@$host:tcp:$port — was the sandbox rebuilt?"
      fail=1
    fi
  done
  guest() { msb exec "$SPIKE_SANDBOX" --no-tty -- sh -c "$1" 2>&1; }
  name="$(basename "$BUNDLE")"
  for f in "/root/.pi/agent/extensions/msb-$name.ts" "/root/.claude/skills/msb-$name/SKILL.md"; do
    if [ "$(guest "[ -f $f ] && echo yes")" = "yes" ]; then
      note "ok    $f"
    else
      note "FAIL  $f is not in the guest"
      fail=1
    fi
  done
  note "env: $(guest 'env | grep -c "^WEB_"') WEB_* variables set"
  code="$(guest 'curl -sS -o /dev/null -w "%{http_code}" -G "$WEB_SEARCH_URL" \
                   --data-urlencode "q=spike" --data-urlencode "format=json"')"
  if [ "$code" = "200" ]; then
    note "ok    the guest reaches the search endpoint (HTTP 200)"
  else
    note "FAIL  the guest got HTTP ${code:-nothing} — an egress rule is missing, and"
    note "      from inside the guest that is indistinguishable from an outage"
    fail=1
  fi
fi

echo
[ "$fail" -eq 0 ] && echo "PASS" || echo "FAILED"
exit "$fail"
