#!/usr/bin/env bash
#
# 12-conf-interpolation.sh — what a project's dev.yaml could do if msbctl still
# passed it to `msb --conf`, and the premise of not doing so.
#
# msb's config loader fills `${NAME}` into every string of the file from msb's
# OWN process environment, and msbctl runs `msb create` with the bound secrets
# in that environment. It also accepts `mounts` with paths relative to the
# file. So a dev.yaml written from inside a sandbox (the project folder is
# read-write) would hand the next rebuild the real token and the host's files.
# msbctl now reads `image:` and passes nothing else; this spike documents the
# hole and checks the one thing the fix relies on.
#
#   1  --conf with env: {LEAK: "${SPIKE_VAL}"}       expected: the guest sees the VALUE (the hole)
#   2  --env 'LEAK=${SPIKE_VAL}', no conf             MUST: the guest sees the literal text,
#                                                     because [env] from sandbox.toml reaches
#                                                     msb this way
#   3  --conf with host mounts, relative to the file  expected: the host directory appears in
#      and as "${SPIKE_DIR}/outside"                  the guest (the hole), in one spelling at least
#   4  a positional image of /tmp/<dir> and ./<dir>   RECORDED: does msb boot a host directory?
#                                                     msbctl refuses both shapes either way
#
# PASS means 1 and 2 behaved as documented: the hole is real and the flag path
# the fix uses is inert. 3 and 4 are reported, not judged.
#
# Observed 2026-10-16 on msb 0.7.6 and 0.7.8: PASS. 3 — the relative mount
# fails to start (EINVAL), the `${SPIKE_DIR}` one mounts the host directory.
# 4 — msb BOOTS a host directory given as the image, absolute and relative.
#
# Needs: /dev/kvm, msb, a pullable IMAGE (default alpine:3). Step 4 also needs
# podman, to unpack a rootfs into a directory; without it 4 is skipped.

set -uo pipefail

IMAGE="${IMAGE:-alpine:3}"
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
# Every sandbox is named with this prefix and removed by it: run_one runs inside
# $(...), a subshell, so a list it appended to would be lost.
PREFIX="spike12-$$-"
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
SPIKE_VAL="spike12-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
export SPIKE_VAL
note "planted value: ${#SPIKE_VAL} chars (not printed)"

# One sandbox per step, run to completion; its output on stdout. CRLF from the
# guest TTY is stripped so the comparisons below see clean lines.
run_one() {
	local name="$PREFIX$1"; shift
	msb run --name "$name" "$@" 2>&1 | tr -d '\r'
}

say "1  \${VAR} in a --conf file"
mkdir -p "$WORK/proj/.msb"
cat > "$WORK/proj/.msb/dev.yaml" <<'EOF'
env:
  LEAK: "${SPIKE_VAL}"
EOF
out="$(run_one conf --conf "$WORK/proj/.msb/dev.yaml" "$IMAGE" -- sh -c 'printf "LEAK=%s\n" "$LEAK"')"
got="$(printf '%s\n' "$out" | sed -n 's/^LEAK=//p' | head -1)"
if [ "$got" = "$SPIKE_VAL" ]; then
	note "the guest received the host value                     AS EXPECTED (the hole)"
elif [ -n "$got" ]; then
	note "the guest received something else ('${got:0:20}')      CHANGED"
	note "  msb no longer interpolates the conf from its environment — re-read the design"
	fail=1
else
	note "LEAK did not reach the guest                          INVESTIGATE"
	printf '%s\n' "$out" | tail -5 | sed 's/^/     /'
	fail=1
fi

say "2  \${VAR} in --env (the path [env] takes)"
# shellcheck disable=SC2016  # the literal ${SPIKE_VAL} is the point
out="$(run_one env --env 'LEAK=${SPIKE_VAL}' "$IMAGE" -- sh -c 'printf "LEAK=%s\n" "$LEAK"')"
got="$(printf '%s\n' "$out" | sed -n 's/^LEAK=//p' | head -1)"
# shellcheck disable=SC2016
if [ "$got" = '${SPIKE_VAL}' ]; then
	note "the guest received the literal text                   OK"
elif [ "$got" = "$SPIKE_VAL" ]; then
	note "the guest received the HOST VALUE                     FAIL"
	note "  --env interpolates too: [env] from a project is as dangerous as the conf"
	fail=1
else
	note "unexpected: '${got:0:40}'                              FAIL"
	fail=1
fi

say "3  host mounts in a --conf file"
# Two spellings: relative to the file, which is what msb documents, and an
# absolute path built from `${VAR}`, which needs no knowledge of the host's
# layout — ${HOME} is in msb's environment like everything else.
mkdir -p "$WORK/outside"
echo "host-side-marker" > "$WORK/outside/marker"
SPIKE_DIR="$WORK"
export SPIKE_DIR
printf 'mounts:\n  - "../../outside:/mnt/o"\n' > "$WORK/proj/.msb/rel.yaml"
# shellcheck disable=SC2016  # the literal ${SPIKE_DIR} is the point
printf 'mounts:\n  - "${SPIKE_DIR}/outside:/mnt/o"\n' > "$WORK/proj/.msb/abs.yaml"
for kind in rel abs; do
	out="$(run_one "mount-$kind" --conf "$WORK/proj/.msb/$kind.yaml" "$IMAGE" \
		-- sh -c 'cat /mnt/o/marker 2>&1 || echo NO_MOUNT')"
	if printf '%s\n' "$out" | grep -qx "host-side-marker"; then
		note "$kind: /mnt/o is the host directory                  AS EXPECTED (the hole)"
	else
		note "$kind: the mount did not appear                      RECORDED"
		printf '%s\n' "$out" | grep -v 'for full diagnostics' | tail -2 | sed 's/^/     /'
	fi
done

say "4  a host directory as the positional image"
if command -v podman >/dev/null 2>&1; then
	rootfs="$WORK/rootfs"
	mkdir -p "$rootfs"
	if cid="$(podman create -q "docker.io/library/$IMAGE" 2>/dev/null)" \
		&& podman export "$cid" | tar -x -C "$rootfs" 2>/dev/null; then
		podman rm -f "$cid" >/dev/null 2>&1
		echo "booted-from-host-dir" > "$rootfs/SPIKE12_MARKER"
		out="$(run_one abs "$rootfs" -- cat /SPIKE12_MARKER)"
		if printf '%s\n' "$out" | grep -qx "booted-from-host-dir"; then
			note "absolute path $rootfs: msb BOOTS the host directory"
		else
			note "absolute path: msb did not boot it: $(printf '%s' "$out" | tail -1 | cut -c1-100)"
		fi
		out="$(cd "$WORK" && run_one rel ./rootfs -- cat /SPIKE12_MARKER)"
		if printf '%s\n' "$out" | grep -qx "booted-from-host-dir"; then
			note "relative ./rootfs: msb BOOTS the host directory"
		else
			note "relative ./rootfs: msb did not boot it: $(printf '%s' "$out" | tail -1 | cut -c1-100)"
		fi
		note "either way msbctl refuses a path-shaped image (image_problem())"
	else
		note "could not unpack $IMAGE with podman — skipped"
	fi
else
	note "podman not installed — skipped"
fi

say "Result"
if [ "$fail" -eq 0 ]; then
	echo "   PASS — a --conf file interpolates msb's environment, and --env does not:"
	echo "   never passing a project's dev.yaml to msb closes the hole."
else
	echo "   FAIL — see above."
fi
exit "$fail"
