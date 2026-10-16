#!/usr/bin/env bash
#
# 14-ssh-passthrough.sh — does `ssh host msbctl …` behave like msbctl here?
#
# `host:name` on the laptop is nothing but ssh to the host's `msbctl host
# serve`, with stdio passed through. Everything rests on ssh and the forced
# command keeping stdio, exit codes and the tty intact, so this checks:
#
#   0  `msbctl ls` exits 0: the forced command finds msb under sshd's own PATH
#   1  `exec NAME -- sh -c "exit 7"` over -T exits 7
#   2  1 MiB of random bytes through `exec NAME -- cat` comes back identical
#   3  `exec NAME -- tty` prints /dev/pts/* over -t, and "not a tty" over -T
#   4  an idle `exec NAME -- sleep N` over a ControlMaster connection stays up
#      (SPIKE_IDLE seconds, default 600)
#   5  denied half: `cat ~/.config/msb/secrets/global.env` and
#      `msbctl allow NAME evil.example` are refused with exit 126
#
# Observed 2026-10-16, laptop role in a sandbox, host on Fedora 44 with msb
# 0.7.8 under a dedicated user: PASS on all six, the idle session at 600s.
#
# Needs: SPIKE_SSH_DEST (user@host whose authorized_keys line was written by
# `msbctl host authorize`, with msb in ~/.local/bin as get.sh leaves it) and
# SPIKE_NAME (a sandbox there, created). No defaults on purpose. Runs on the
# laptop: no msb or KVM needed here.

set -uo pipefail

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
DEST="${SPIKE_SSH_DEST:-}"
NAME="${SPIKE_NAME:-}"
IDLE="${SPIKE_IDLE:-600}"
[ -n "$DEST" ] && [ -n "$NAME" ] || { echo "set SPIKE_SSH_DEST and SPIKE_NAME" >&2; exit 1; }
WORK="$(mktemp -d)"
CTL="$WORK/cm-%C"
trap 'ssh -o ControlPath="$CTL" -O exit "$DEST" >/dev/null 2>&1; rm -rf "$WORK"' EXIT
SSH=(ssh -o ControlMaster=auto -o ControlPath="$CTL" -o ControlPersist=600 -o ServerAliveInterval=30)

say "0  msbctl ls under the forced command"
if "${SSH[@]}" -T "$DEST" -- 'msbctl ls' >/dev/null 2>"$WORK/err"; then
	note "exit 0                                                OK"
else
	note "failed: $(tail -1 "$WORK/err")                        FAIL"; fail=1
fi

say "1  exit status"
"${SSH[@]}" -T "$DEST" -- "msbctl exec $NAME -- sh -c 'exit 7'" </dev/null >/dev/null 2>&1
rc=$?
[ "$rc" -eq 7 ] && note "exit 7 came back                                      OK" \
	|| { note "exit $rc, not 7                                       FAIL"; fail=1; }

say "2  a binary stream through cat"
head -c 1048576 /dev/urandom > "$WORK/in"
"${SSH[@]}" -T "$DEST" -- "msbctl exec $NAME -- cat" < "$WORK/in" > "$WORK/out" 2>/dev/null
if [ "$(sha256sum < "$WORK/in")" = "$(sha256sum < "$WORK/out")" ]; then
	note "1 MiB identical                                       OK"
else
	note "differs: $(wc -c < "$WORK/out") bytes came back                FAIL"; fail=1
fi

say "3  the tty"
with="$("${SSH[@]}" -tt "$DEST" -- "msbctl exec $NAME -- tty" 2>/dev/null | tr -d '\r' | tail -1)"
without="$("${SSH[@]}" -T "$DEST" -- "msbctl exec $NAME -- tty" </dev/null 2>/dev/null | tail -1)"
case "$with" in /dev/pts/*) note "-t: $with                                    OK" ;;
	*) note "-t: '$with'                                         FAIL"; fail=1 ;; esac
[ "$without" = "not a tty" ] && note "-T: not a tty                                         OK" \
	|| { note "-T: '$without'                                      FAIL"; fail=1; }

say "4  idle for ${IDLE}s over the shared connection"
start=$(date +%s)
"${SSH[@]}" -T "$DEST" -- "msbctl exec $NAME -- sleep $IDLE" </dev/null >/dev/null 2>&1
rc=$?
took=$(( $(date +%s) - start ))
if [ "$rc" -eq 0 ] && [ "$took" -ge "$IDLE" ]; then
	note "stayed up ${took}s                                     OK"
else
	note "ended after ${took}s with exit $rc                     FAIL"; fail=1
fi

say "5  what the key must not do"
for cmd in 'cat ~/.config/msb/secrets/global.env' "msbctl allow $NAME evil.example" "msbctl observe $NAME on -y"; do
	"${SSH[@]}" -T "$DEST" -- "$cmd" </dev/null >/dev/null 2>"$WORK/err"
	rc=$?
	if [ "$rc" -eq 126 ]; then
		note "refused (126): $cmd"
	else
		note "NOT refused ($rc): $cmd                           FAIL"; fail=1
	fi
done

say "Result"
if [ "$fail" -eq 0 ]; then
	echo "   PASS — host:name over ssh keeps exit codes, bytes and the tty, holds an"
	echo "   idle session, and the forced command refuses what it must."
else
	echo "   FAIL — see above."
fi
exit "$fail"
