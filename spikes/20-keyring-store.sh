#!/usr/bin/env bash
#
# 20-keyring-store.sh — does `[secrets] store = "keyring"` work against a real
# Secret Service, and does a locked one ask to unlock, without hanging when
# nobody can answer?
#
# The unit tests run against tests/fake/secret-tool and tests/fake/busctl,
# which are only as right as what they assume. This checks the assumptions on a
# real gnome-keyring, on a private session bus (dbus-run-session), in a
# throwaway HOME and MSB_CONFIG_DIR, so your own keyring is never touched:
#
#   1  busctl reads the default collection's Locked property (what
#      keyring_status() asks), and `secret-tool lookup` prints the value
#      with no trailing newline when stdout is not a terminal.
#   2  `msbctl secret migrate --to keyring` moves a plaintext value into the
#      keyring, leaves `VAR=@keyring` in the file, and prints no value.
#   3  The keyring locked: `host check` says so, as information (a locked
#      keyring asks on first use). `migrate --to file` DOES call secret-tool,
#      which starts the unlock prompt (gcr-prompter; on a desktop, the dialog
#      you answer). Here there is no display, so the prompt fails at once, and
#      migrate must stop cleanly: the file and [secrets] store unchanged, and
#      within seconds rather than at a timeout.
#   2b Unlocked, a marker whose item was deleted behind msbctl's back:
#      keyring_why() says "missing", which needs the bus to say unlocked
#      after the failed lookup.
#   4  Still locked, two values read twice each: secret-tool is called ONCE
#      (the refused prompt latches for the run, after the bus still says
#      Locked), and keyring_why() says "refused".
#
# PASS is all of it. Needs: dbus-run-session, gnome-keyring-daemon,
# secret-tool, busctl (Debian/Ubuntu: dbus-daemon gnome-keyring libsecret-tools).
#
# Observed 2026-10-24 on Ubuntu (gnome-keyring 48, libsecret 0.21, systemd
# busctl), in the dev sandbox: PASS. A locked lookup there starts
# org.gnome.keyring.SystemPrompter, which fails for want of a display in ~0.1 s.
# Not checked here: answering the dialog on a real desktop.

set -uo pipefail

if [ "${SPIKE_INNER:-}" != 1 ]; then
	for bin in dbus-run-session gnome-keyring-daemon secret-tool busctl; do
		command -v "$bin" >/dev/null || { echo "SKIP: $bin not installed"; exit 2; }
	done
	work=$(mktemp -d)
	trap 'rm -rf "$work"' EXIT
	mkdir -p "$work/home" "$work/run" && chmod 700 "$work/run"
	HOME="$work/home" XDG_RUNTIME_DIR="$work/run" SPIKE_INNER=1 \
		MSB_CONFIG_DIR="$work/home/.config/msb" MSB_STATE_DIR="$work/home/.local/state/msb" \
		MSBCTL="$(cd "$(dirname "$0")/.." && pwd)/msbctl" \
		timeout 120 dbus-run-session -- bash "$0"
	exit $?
fi

fail=0
pass() { echo "PASS  $*"; }
bad() { echo "FAIL  $*"; fail=1; }
VALUE="spike-keyring-value-$$"

printf 'spike-password' | gnome-keyring-daemon --unlock --components=secrets >/dev/null 2>&1
sleep 1

# 1 -------------------------------------------------------------- the probe
locked=$(busctl --user --timeout=5 get-property org.freedesktop.secrets \
	/org/freedesktop/secrets/aliases/default org.freedesktop.Secret.Collection Locked)
[ "$locked" = "b false" ] && pass "busctl: unlocked reads as '$locked'" || bad "busctl said '$locked'"
printf 'x' | secret-tool store --label=spike service spike-probe
[ "$(secret-tool lookup service spike-probe | od -An -c | tr -d ' \n')" = "x" ] \
	&& pass "lookup: no trailing newline" || bad "lookup output is not exactly the value"
secret-tool clear service spike-probe

# 2 -------------------------------------------------------- migrate --to keyring
mkdir -p "$MSB_CONFIG_DIR/secrets" && chmod 700 "$MSB_CONFIG_DIR/secrets"
env_file="$MSB_CONFIG_DIR/secrets/global.env"
(umask 077 && printf 'GH_TOKEN=%s\n' "$VALUE" >"$env_file")
out=$("$MSBCTL" secret migrate --to keyring --json 2>&1)
grep -q '^GH_TOKEN=@keyring$' "$env_file" && pass "migrate: the file holds the marker" \
	|| bad "migrate: the file says $(sed 's/=.*/=…/' "$env_file")"
case "$out" in *"$VALUE"*) bad "migrate printed the value" ;; *) pass "migrate printed no value" ;; esac
got=$(secret-tool lookup service msb-manager file global var GH_TOKEN)
[ "$got" = "$VALUE" ] && pass "the keyring holds the value" || bad "the keyring does not hold it"

printf 'spike-password' | busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
# 2b ------------------------------- an item deleted behind msbctl's back
# OTHER's marker points at no item: a failed lookup, then the bus says unlocked.
(umask 077 && printf 'GH_TOKEN=@keyring\nOTHER=@keyring\n' >"$env_file")
why=$(python3 -I - "$MSBCTL" <<'PY' 2>/dev/null
import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("msbctl", sys.argv[1])
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("msbctl", loader))
loader.exec_module(m)
print(m.keyring_status()[0], m.keyring_get(m.GLOBAL_ENV, "OTHER"), m.keyring_why(m.GLOBAL_ENV, "OTHER")[0])
PY
)
[ "$why" = "unlocked None missing" ] && pass "unlocked, item deleted: reads as missing" \
	|| bad "unlocked, item deleted: '$why'"

# 3 -------------------------------------------------------------- locked
busctl --user call org.freedesktop.secrets /org/freedesktop/secrets \
	org.freedesktop.Secret.Service Lock ao 1 /org/freedesktop/secrets/aliases/default >/dev/null
# Wrap secret-tool to count the calls: each one now is an unlock prompt.
mkdir -p "$HOME/bin"
printf '#!/bin/sh\necho called >>"%s/secret-tool.calls"\nexec %s "$@"\n' "$HOME" "$(command -v secret-tool)" >"$HOME/bin/secret-tool"
chmod +x "$HOME/bin/secret-tool"
export PATH="$HOME/bin:$PATH"
check=$("$MSBCTL" host check --json 2>/dev/null)
python3 -I -c 'import json,sys; c=[x for x in json.load(sys.stdin)["checks"] if x["check"]=="secret store"][0]; sys.exit(0 if c["ok"] is None and "locked" in c["detail"] else 1)' <<<"$check" \
	&& pass "host check: locked, reported as information" || bad "host check: $check"
start=$(date +%s)
if timeout 60 "$MSBCTL" secret migrate --to file >/dev/null 2>&1; then
	bad "migrate --to file succeeded with nobody to answer the prompt"
else
	pass "migrate --to file stopped when the prompt could not be shown"
fi
[ $(($(date +%s) - start)) -lt 30 ] && pass "and promptly" || bad "it took $(($(date +%s) - start)) s"
[ -e "$HOME/secret-tool.calls" ] && pass "the locked keyring was asked (the unlock prompt)" \
	|| bad "secret-tool was never called"
grep -q '^GH_TOKEN=@keyring$' "$env_file" && pass "the file is unchanged" || bad "the file changed"
grep -q '^store = "keyring"' "$MSB_CONFIG_DIR/config.toml" && pass "[secrets] store is unchanged" \
	|| bad "[secrets] store changed"

# 4 ------------------------------------------------- one prompt, and why
(umask 077 && printf 'GH_TOKEN=@keyring\nOTHER=@keyring\n' >"$env_file")
rm -f "$HOME/secret-tool.calls"
# The module is loaded from its path; -I keeps this folder off sys.path.
why=$(python3 -I - "$MSBCTL" <<'PY' 2>/dev/null
import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("msbctl", sys.argv[1])
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("msbctl", loader))
loader.exec_module(m)
for _ in range(2):
    m.read_env_file(m.GLOBAL_ENV)
print(m.keyring_why(m.GLOBAL_ENV, "GH_TOKEN")[0])
PY
)
calls=$(wc -l <"$HOME/secret-tool.calls" 2>/dev/null || echo 0)
[ "$calls" -eq 1 ] && pass "locked: one secret-tool call for two values read twice" \
	|| bad "locked: $calls secret-tool calls"
[ "$why" = refused ] && pass "and it reads as refused" || bad "it reads as '$why'"

[ $fail = 0 ] && echo "PASS" || echo "FAIL"
exit $fail
