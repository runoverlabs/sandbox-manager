#!/usr/bin/env bash
#
# 16-kandev-host.sh — the msb mechanisms `msbctl kandev` relies on.
#
#   1  (S1) a process started with `setsid … &` from `msb exec` keeps running
#      after that exec returns, and answers on a published 127.0.0.1 port
#   2  (S3) `--label` on create is what `msb ls --label` filters on; a sandbox
#      without the label is not listed (the denied half)
#   3  (S4) the Kandev API pinned by address: an IP rule plus a guest
#      /etc/hosts line reaches SPIKE_PIN_HOST over HTTPS with DNS rebind
#      protection on, SPIKE_DENY_HOST is refused, and the /etc/hosts line is
#      gone after a restart (which is why `kandev start` writes it again)
#   4  registry credentials through MSB_CONFIG_PATH: a wrong password named by
#      `password_env` makes `msb pull` fail "Not authorized" where the same
#      pull without it works, and the password is nowhere under MSB_HOME
#   5  (S2, only with SPIKE_TS=1) `tailscale serve --set-path` to a published
#      port: whether the prefix is stripped before proxying. WebSocket
#      upgrades and many mappings per node still need checking by hand.
#   6  (S5, only with SPIKE_SSH_DEST) cold and warm `ssh DEST msbctl kandev
#      health` round trips, against Kandev's 15 s / 30 s budgets
#
# Observed 2026-10-17 on msb 0.7.7, nested inside an msb sandbox (so with
# --trust-host-cas, since the outer sandbox intercepts TLS): 1, 2 and 4 PASS;
# 3 PASS for the pinned address and the refused host, and the /etc/hosts line
# did NOT survive a restart. A hostname rule failed TLS in that nested setup
# while the IP rule worked, which is why 3 needs a run on a real host. 5 and 6
# not run (no tailscale, no remote).
#
# Needs: msb and /dev/kvm here, and SPIKE_IMAGE (a small image with sh and
# busybox nc, e.g. an alpine on a registry you can reach), SPIKE_PIN_HOST and
# SPIKE_DENY_HOST (two HTTPS hosts this machine can reach), SPIKE_PRIVATE_REG
# (a registry host that rejects bad credentials, e.g. ghcr.io) with
# SPIKE_REG_IMAGE (a public image there, not cached yet). No defaults on
# purpose. Optional: SPIKE_TS=1, SPIKE_SSH_DEST, SPIKE_TRUST_HOST_CAS=1 when
# nested. Everything created is removed.

set -uo pipefail

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
for v in SPIKE_IMAGE SPIKE_PIN_HOST SPIKE_DENY_HOST SPIKE_PRIVATE_REG SPIKE_REG_IMAGE; do
	[ -n "${!v:-}" ] || { echo "set $v (see the header)" >&2; exit 1; }
done
command -v msb >/dev/null || { echo "msb is not on PATH" >&2; exit 1; }
[ -r /dev/kvm ] && [ -w /dev/kvm ] || { echo "no usable /dev/kvm" >&2; exit 1; }
CA=(); [ "${SPIKE_TRUST_HOST_CAS:-}" = 1 ] && CA=(--trust-host-cas)
WORK="$(mktemp -d)"
NAMES=(spike16-a spike16-b spike16-c)
cleanup() {
	msb rm -f "${NAMES[@]}" >/dev/null 2>&1
	[ "${SPIKE_TS:-}" = 1 ] && tailscale serve --https=443 --set-path=/spike16 off >/dev/null 2>&1
	rm -rf "$WORK"
}
trap cleanup EXIT
SERVER='while :; do printf "HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok" | nc -l -p 8765 > /tmp/req 2>/dev/null; done'

say "1  a setsid process outlives its exec"
msb create --name spike16-a "${CA[@]}" --port 127.0.0.1:28765:8765 --label msbctl.owner=kandev \
	"$SPIKE_IMAGE" >/dev/null 2>&1 || { note "create failed                                 FAIL"; exit 1; }
msb exec spike16-a --no-tty -- sh -c "setsid sh -c '$SERVER' </dev/null >/dev/null 2>&1 &"
sleep 2
if [ "$(curl -s -m 5 http://127.0.0.1:28765/)" = ok ]; then
	note "answers on the published port after the exec    OK"
else
	note "no answer on 127.0.0.1:28765                     FAIL"; fail=1
fi

say "2  labels"
msb create --name spike16-b "$SPIKE_IMAGE" >/dev/null 2>&1
listed="$(msb ls --label msbctl.owner=kandev -q 2>/dev/null)"
case "$listed" in *spike16-a*) note "labelled sandbox listed                         OK" ;;
	*) note "labelled sandbox not listed                     FAIL"; fail=1 ;; esac
case "$listed" in *spike16-b*) note "unlabelled sandbox listed too                   FAIL"; fail=1 ;;
	*) note "unlabelled sandbox not listed                   OK" ;; esac

say "3  the Kandev API pinned by address"
addr="$(getent ahostsv4 "$SPIKE_PIN_HOST" | awk 'NR==1{print $1}')"
msb create --name spike16-c "${CA[@]}" --net-default-egress deny --net-rule allow@dns \
	--net-rule "allow@${addr}:tcp:443" --tls-intercept "$SPIKE_IMAGE" >/dev/null 2>&1
msb exec spike16-c --no-tty -- sh -c "echo '$addr $SPIKE_PIN_HOST' >> /etc/hosts"
if msb exec spike16-c --no-tty -- wget -q -T 10 -O /dev/null "https://$SPIKE_PIN_HOST/" 2>/dev/null; then
	note "https://$SPIKE_PIN_HOST through the pinned address        OK"
else
	note "https://$SPIKE_PIN_HOST failed                            FAIL"; fail=1
fi
if msb exec spike16-c --no-tty -- wget -q -T 8 -O /dev/null "https://$SPIKE_DENY_HOST/" 2>/dev/null; then
	note "$SPIKE_DENY_HOST reached: the rule is too wide        FAIL"; fail=1
else
	note "$SPIKE_DENY_HOST refused                              OK"
fi
msb stop spike16-c >/dev/null 2>&1; msb start spike16-c >/dev/null 2>&1
if msb exec spike16-c --no-tty -- grep -q "$SPIKE_PIN_HOST" /etc/hosts 2>/dev/null; then
	note "/etc/hosts line survived a restart                RECORDED"
else
	note "/etc/hosts line gone after a restart              RECORDED"
fi

say "4  registry credentials by password_env"
printf '{"registries":{"hosts":{"%s":{"auth":{"username":"nobody","password_env":"SPIKE16_PW"}}}}}' \
	"$SPIKE_PRIVATE_REG" > "$WORK/config.json"
out="$(MSB_CONFIG_PATH="$WORK/config.json" SPIKE16_PW=spike16-wrong-password \
	msb pull "$SPIKE_REG_IMAGE" 2>&1)"
case "$out" in *"ot authorized"*|*nauthorized*|*denied*)
	note "the wrong password was used and refused         OK" ;;
	*) note "pull with a wrong password: $(echo "$out" | tail -1)   FAIL"; fail=1 ;; esac
if msb pull "$SPIKE_REG_IMAGE" >/dev/null 2>&1; then
	note "the same pull without it works                  OK"
else
	note "the pull fails anyway: the test proves nothing  FAIL"; fail=1
fi
home="${MSB_HOME:-$HOME/.microsandbox}"
if grep -rqs spike16-wrong-password "$home"; then
	note "the password was written under $home            FAIL"; fail=1
else
	note "the password is nowhere under msb's home        OK"
fi

if [ "${SPIKE_TS:-}" = 1 ]; then
	say "5  tailscale serve --set-path"
	tailscale serve --bg --https=443 --set-path=/spike16 http://127.0.0.1:28765 >/dev/null 2>&1
	dns="$(tailscale status --json | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1)"
	if [ "$(curl -s -m 10 "https://$dns/spike16/x/y")" = ok ]; then
		seen="$(msb exec spike16-a --no-tty -- head -1 /tmp/req | tr -d '\r')"
		note "proxied; the guest saw: $seen                    RECORDED"
	else
		note "nothing came back through https://$dns/spike16   FAIL"; fail=1
	fi
fi

if [ -n "${SPIKE_SSH_DEST:-}" ]; then
	say "6  round trips"
	for pass in cold warm; do
		start=$(date +%s%N)
		ssh -o ControlMaster=auto -o ControlPath="$WORK/cm" -o ControlPersist=60 -T \
			"$SPIKE_SSH_DEST" -- msbctl kandev health >/dev/null 2>&1
		note "$pass: $(( ($(date +%s%N) - start) / 1000000 )) ms                  RECORDED"
	done
	ssh -o ControlPath="$WORK/cm" -O exit "$SPIKE_SSH_DEST" >/dev/null 2>&1
fi

say "Result"
[ "$fail" -eq 0 ] && note "PASS" || note "FAIL"
exit "$fail"
