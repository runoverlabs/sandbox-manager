#!/usr/bin/env bash
#
# 13-workspace-volume.sh — the mechanics of a sandbox with no host folder.
#
# `msbctl add --repo` sandboxes keep their code in a named disk volume at the
# guest project path, cloned by bootstrap.sh's do_clone with the GH_TOKEN
# PLACEHOLDER handed to git by an inline credential helper. This proves:
#
#   1  a fresh --mount-named V:/work:kind=disk volume: does /work hold
#      lost+found? (recorded: do_clone keeps it out of git status either way)
#   2  do_clone's steps (init, remote, fetch, checkout) succeed against
#      SPIKE_REPO with --secret GH_TOKEN@github.com, and the guest's $GH_TOKEN
#      is the placeholder, not the token (sha256 prefixes, as spike 08 does)
#   3  after `msb rm -f` and a new sandbox on the SAME volume, /work/.git and a
#      file committed in step 2 are still there — what makes a rebuild keep
#      unpushed work
#   4  denied half: WITHOUT the binding, the fetch of SPIKE_REPO fails. Only
#      meaningful for a private repo; a public one is reported INCONCLUSIVE
#
# Observed 2026-10-16 on msb 0.7.6, nested in a sandbox with a public repo: 1 no
# lost+found; 2 the clone works; 3 PASS. Then the same day on a real host with
# a private repo: PASS throughout — 1 no lost+found; 2 the guest's GH_TOKEN is
# the placeholder and the clone works; 3 PASS; 4 the fetch fails without the
# binding. (Nested, the placeholder half of 2 is INCONCLUSIVE: there the host's
# GH_TOKEN is itself a placeholder.)
#
# Needs: /dev/kvm, msb, GH_TOKEN (a token that can read SPIKE_REPO), SPIKE_REPO
# (owner/name, ideally PRIVATE). No defaults on purpose. IMAGE defaults to
# ubuntu:24.04, which the script installs git into.

set -uo pipefail

IMAGE="${IMAGE:-ubuntu:24.04}"
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
PREFIX="spike13-$$-"
VOL="spike13-$$-work"
cleanup() {
	for n in $(msb ls 2>/dev/null | awk -v p="$PREFIX" 'NR > 1 && index($1, p) == 1 {print $1}'); do
		msb rm -f "$n" >/dev/null 2>&1
	done
	msb volume rm "$VOL" >/dev/null 2>&1
}
trap cleanup EXIT

say "Preflight"
[ -e /dev/kvm ] || { echo "no /dev/kvm — run on the host" >&2; exit 1; }
command -v msb >/dev/null || { echo "msb not on PATH" >&2; exit 1; }
[ -n "${GH_TOKEN:-}" ] || { echo "GH_TOKEN is not set" >&2; exit 1; }
[ -n "${SPIKE_REPO:-}" ] || { echo "SPIKE_REPO is not set (owner/name)" >&2; exit 1; }
msb --version
host_sha="$(printf '%s' "$GH_TOKEN" | sha256sum | cut -c1-12)"
private="$(curl -fsS -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/$SPIKE_REPO" \
	| sed -n 's/^  "private": \(true\|false\),*$/\1/p' | head -1)"
note "repo $SPIKE_REPO, private: ${private:-unknown}; host token sha256 ${host_sha}…"

RULES=(--net-default-egress deny --net-rule "allow@dns" --net-rule "deny@public:tcp:80,deny@private:tcp:80"
	--net-rule "allow@*.ubuntu.com:tcp:443" --net-rule "allow@github.com:tcp:443"
	--net-rule "allow@api.github.com:tcp:443" --tls-intercept)

# The do_clone steps, as bootstrap.sh runs them, then a commit to look for later.
# shellcheck disable=SC2016  # runs in the guest
CLONE='
	set -u
	sed -i "s|http://\([a-z0-9.-]*ubuntu\.com\)|https://\1|g" /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null
	command -v git >/dev/null || { apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq git ca-certificates >/dev/null 2>&1; }
	v="${GH_TOKEN:-}"
	[ -n "$v" ] && printf "GUEST_SHA=%s\n" "$(printf "%s" "$v" | sha256sum | cut -c1-12)"
	if [ -d /work/lost+found ]; then echo LOST_FOUND=yes; else echo LOST_FOUND=no; fi
	git config --system credential.https://github.com.helper \
		"!f() { test \"\$1\" = get || exit 0; echo username=x-access-token; echo \"password=\${GH_TOKEN:-}\"; }; f"
	git -C /work init -q && git -C /work remote add origin "https://github.com/$1.git" \
		&& git -C /work fetch -q origin 2>/tmp/fetch.err && echo FETCH=ok || { echo FETCH=failed; head -c 200 /tmp/fetch.err; exit 0; }
	echo lost+found >> /work/.git/info/exclude
	branch="$(git -C /work remote show origin | sed -n "s/.*HEAD branch: //p")"
	git -C /work checkout -q "$branch" && echo CHECKOUT=ok || echo CHECKOUT=failed
	echo marker > /work/spike13-marker
	git -C /work -c user.name=spike -c user.email=spike@example.invalid add spike13-marker
	git -C /work -c user.name=spike -c user.email=spike@example.invalid commit -qm spike13 && echo COMMIT=ok
	printf "STATUS=%s\n" "$(git -C /work status --porcelain | tr "\n" " ")"
'
field() { printf '%s\n' "$1" | tr -d '\r' | sed -n "s/^$2=//p" | head -1; }

say "1+2  fresh volume, clone with the placeholder"
out="$(msb run --name "${PREFIX}a" "${RULES[@]}" --secret "GH_TOKEN@github.com,api.github.com" \
	--mount-named "$VOL:/work:kind=disk,size=1G" "$IMAGE" -- bash -c "$CLONE" _ "$SPIKE_REPO" 2>&1)"
note "lost+found in a fresh volume: $(field "$out" LOST_FOUND)                RECORDED"
guest_sha="$(field "$out" GUEST_SHA)"
if [ -z "$guest_sha" ]; then
	note "GH_TOKEN did not reach the guest                      FAIL"; fail=1
elif [ "${GH_TOKEN#\$MSB_}" != "$GH_TOKEN" ]; then
	# msb's placeholder is the literal $MSB_<VAR>, so inside a sandbox the
	# "host" token is already one and the nested guest's is the same text.
	note "this host's GH_TOKEN is itself a placeholder     INCONCLUSIVE"
	note "  (nested msb): run on a real host for this half"
elif [ "$guest_sha" = "$host_sha" ]; then
	note "the guest holds the REAL token                        FAIL"; fail=1
else
	note "guest GH_TOKEN is a placeholder                       OK"
fi
if [ "$(field "$out" FETCH)" = ok ] && [ "$(field "$out" CHECKOUT)" = ok ] && [ "$(field "$out" COMMIT)" = ok ]; then
	note "init, fetch, checkout, commit                         OK"
else
	note "the clone failed                                      FAIL"
	printf '%s\n' "$out" | tail -4 | sed 's/^/     /'
	fail=1
fi
status="$(field "$out" STATUS)"
[ -z "${status// /}" ] && note "git status clean (lost+found excluded)                OK" \
	|| { note "git status not clean: '$status'                     FAIL"; fail=1; }

say "3  a new sandbox on the same volume"
msb rm -f "${PREFIX}a" >/dev/null 2>&1
out="$(msb run --name "${PREFIX}b" "${RULES[@]}" --mount-named "$VOL:/work:kind=disk,size=1G" "$IMAGE" \
	-- sh -c 'test -d /work/.git && echo GIT=yes; cat /work/spike13-marker 2>/dev/null | sed "s/^/MARKER=/"' 2>&1)"
if [ "$(field "$out" GIT)" = yes ] && [ "$(field "$out" MARKER)" = marker ]; then
	note "/work/.git and the committed file survived            OK"
else
	note "the clone did not survive                             FAIL"; fail=1
fi
msb rm -f "${PREFIX}b" >/dev/null 2>&1
msb volume rm "$VOL" >/dev/null 2>&1

say "4  without the binding"
out="$(msb run --name "${PREFIX}c" "${RULES[@]}" --mount-named "$VOL:/work:kind=disk,size=1G" "$IMAGE" \
	-- bash -c "$CLONE" _ "$SPIKE_REPO" 2>&1)"
fetch="$(field "$out" FETCH)"
if [ "$private" != true ]; then
	note "$SPIKE_REPO is not private: fetch=$fetch                INCONCLUSIVE"
	note "  run with a private SPIKE_REPO for the denied half"
elif [ "$fetch" = failed ]; then
	note "the private fetch failed without the binding          OK"
else
	note "the private fetch WORKED without the binding          FAIL"; fail=1
fi

say "Result"
if [ "$fail" -eq 0 ]; then
	echo "   PASS — a placeholder-authenticated clone lands in a named volume that"
	echo "   outlives its sandbox."
else
	echo "   FAIL — see above."
fi
exit "$fail"
