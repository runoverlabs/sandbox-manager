#!/usr/bin/env bash
#
# 15-nested-ro-mount.sh — can the project's .msb/ be read-only inside the guest
# while the project around it stays read-write?
#
# msbctl mounts the project read-write, and .msb/sandbox.toml inside it is the
# policy the host reads at the next rebuild. The policy pin is what actually
# protects it (a change has to be approved on the host); a read-only .msb/ in
# the guest only turns a silent edit into an immediate EROFS. This spike decides
# whether msbctl can emit that second mount:
#
#   --mount-dir P:/work  --mount-dir P/.msb:/work/.msb:ro
#
#   1  that order: /work/x is writable and lands on the host; /work/.msb/y fails
#      (EROFS, or any error) and nothing appears on the host; /work/.msb/sandbox.toml
#      is still readable
#   2  the reverse flag order: recorded, so msbctl emits the order that passed
#   +  whether root in the guest can simply umount the read-only one: recorded
#
# PASS: order 1 behaves as described. Both halves are asserted: the write that
# must work and the write that must not.
#
# Observed 2026-10-16 on msb 0.7.6 and 0.7.8: PASS, both orders behave the
# same, and root in the guest CAN umount the read-only .msb and write beneath.
#
# Needs: /dev/kvm, msb, a pullable IMAGE (default alpine:3).

set -uo pipefail

IMAGE="${IMAGE:-alpine:3}"
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
PREFIX="spike15-$$-"
WORK="$(mktemp -d)"
cleanup() {
	for n in $(msb ls 2>/dev/null | awk -v p="$PREFIX" 'NR > 1 && index($1, p) == 1 {print $1}'); do
		msb rm -f "$n" >/dev/null 2>&1
	done
	rm -rf "$WORK"
}
trap cleanup EXIT

say "Preflight"
[ -e /dev/kvm ] || { echo "no /dev/kvm — run on the host" >&2; exit 1; }
command -v msb >/dev/null || { echo "msb not on PATH" >&2; exit 1; }
msb --version

# The guest script: one KEY=value line per probe.
# shellcheck disable=SC2016  # expanded in the guest
probe='
	echo w > /work/x 2>/dev/null && echo OUTER=ok || echo OUTER=denied
	if (echo y > /work/.msb/y) 2>/tmp/err; then echo INNER=ok; else echo "INNER=denied:$(head -c 60 /tmp/err)"; fi
	echo "READ=$(cat /work/.msb/sandbox.toml 2>&1 | head -1)"
	# Root in the guest can take the read-only mount away; recorded, not judged.
	if umount /work/.msb 2>/dev/null && (echo z > /work/.msb/z) 2>/dev/null; then echo UNMOUNT=writable; else echo UNMOUNT=held; fi
'

run_order() {
	local tag="$1"; shift
	local proj="$WORK/$tag"
	mkdir -p "$proj/.msb"
	echo 'rule_groups = ["github"]' > "$proj/.msb/sandbox.toml"
	local inner=("--mount-dir" "$proj/.msb:/work/.msb:ro")
	local outer=("--mount-dir" "$proj:/work:uid=$(id -u),gid=$(id -g)")
	local flags
	if [ "$1" = outer-first ]; then flags=("${outer[@]}" "${inner[@]}"); else flags=("${inner[@]}" "${outer[@]}"); fi
	msb run --name "$PREFIX$tag" "${flags[@]}" "$IMAGE" -- sh -c "$probe" 2>&1 | tr -d '\r' > "$WORK/$tag.out"
	field() { sed -n "s/^$1=//p" "$WORK/$tag.out" | head -1; }
	OUTER="$(field OUTER)"; INNER="$(field INNER)"; READ="$(field READ)"
	HOST_X=no; [ -f "$proj/x" ] && HOST_X=yes
	HOST_Y=no; [ -f "$proj/.msb/y" ] && HOST_Y=yes
	UNMOUNT="$(field UNMOUNT)"
	if [ -z "$OUTER" ]; then
		note "did not run:"; tail -3 "$WORK/$tag.out" | sed 's/^/     /'
	fi
}

say "1  project first, then .msb read-only"
run_order a outer-first
r1=pass
[ "$OUTER" = ok ] && [ "$HOST_X" = yes ] \
	&& note "/work/x written and on the host                       OK" \
	|| { note "/work/x: guest=$OUTER host=$HOST_X                  FAIL"; r1=fail; }
case "$INNER" in
	denied*) [ "$HOST_Y" = no ] \
		&& note "/work/.msb/y refused (${INNER#denied:})   OK" \
		|| { note "/work/.msb/y refused but it is on the host        FAIL"; r1=fail; } ;;
	*) note "/work/.msb/y: guest=$INNER host=$HOST_Y              FAIL (writable)"; r1=fail ;;
esac
[ "$READ" = 'rule_groups = ["github"]' ] \
	&& note "/work/.msb/sandbox.toml readable                      OK" \
	|| { note "/work/.msb/sandbox.toml: '$READ'                   FAIL"; r1=fail; }
[ "$r1" = pass ] || fail=1
if [ "$UNMOUNT" = writable ]; then
	note "root in the guest can umount it and write underneath  RECORDED"
	note "  so this is a tripwire, not a control: the policy pin is the control"
else
	note "umount by root in the guest: $UNMOUNT                 RECORDED"
fi

say "2  .msb read-only first, then the project (recorded)"
run_order b inner-first
note "outer write: guest=$OUTER host=$HOST_X; inner write: guest=${INNER%%:*} host=$HOST_Y; read: ${READ:-none}"

say "Result"
if [ "$fail" -eq 0 ]; then
	echo "   PASS — project first, then its .msb read-only, is the order msbctl emits."
else
	echo "   FAIL — msbctl must not emit the read-only .msb mount; the pin is the control."
fi
exit "$fail"
