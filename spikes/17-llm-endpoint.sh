#!/usr/bin/env bash
#
# 17-llm-endpoint.sh — a model server on your LAN, with its key kept host-side.
#
# pi talks to `[llm.<name>]` endpoints, and the one that matters most is a
# server of your own: vLLM or llama.cpp on a LAN box, on a port that is not
# 443, with a certificate from your own CA, under a name that resolves to a
# private address. msbctl binds its key as `LLM_KEY_<NAME>@HOST`, so the guest
# holds a placeholder and msb substitutes the real value into the header on the
# way out. That rests on four things, each checked here:
#
#   1. Substitution works on a port other than 443 once it is intercepted
#      (`--tls-intercept-port`), against an upstream signed by a private CA
#      (`--tls-upstream-ca-cert-for HOST=PEM`), for a name that resolves
#      privately (`--no-dns-rebind-protection`).
#   2. `--tls-intercept-port` REPLACES msb's default of 443 rather than adding
#      to it, and may be repeated. msbctl therefore always restates 443: given
#      only 8443, every other HTTPS rule (GitHub, npm) silently stops working.
#   3. Another secret's placeholder in a request BODY to the endpoint is
#      blocked — the agent's transcript, resent every turn — unless the
#      endpoint is in that binding's passthrough list, which is why msbctl adds
#      every endpoint to AGENT_TRANSCRIPT_HOSTS for the sandbox.
#   4. The key never reaches a host it is not bound to.
#
# Self-contained: it makes a throwaway CA and server certificate, and runs a
# fake OpenAI-style endpoint and a one-name DNS server on this host. The
# endpoint records whether the Authorization header held the real key, a
# placeholder or nothing, and never logs the key.
#
# Needs openssl and python3 on the host, and an image with busybox wget (alpine
# loads fine: `podman save --format oci-archive` then `msb load -i`).
# ADDR is an address of THIS host that the guest can reach (the LAN or
# bridge address, not 127.0.0.1). Required, with no default on purpose.
#
# PASS: (1) the endpoint sees the real key while the guest holds a placeholder,
#       (2) 443 still works only when restated, (3) a foreign placeholder in a
#       body is blocked without passthrough and delivered with it, (4) the key
#       sent to another host does not arrive as the key.

set -uo pipefail

IMAGE="${IMAGE:-docker.io/library/alpine:3}"
ADDR="${ADDR:?set ADDR to an address of this host the guest can reach}"
PORT="${PORT:-8443}"
NAME=llm.spike.test
CONTROL="${CONTROL:-github.com}"       # an HTTPS host the guest may reach on 443

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail=0
check() {   # check <label> <want> <got>
	if [ "$2" = "$3" ]; then note "$1  OK"
	else note "$1  FAIL (wanted $2, got ${3:-nothing})"; fail=1; fi
}

say "Preflight"
[ -e /dev/kvm ] || { echo "no /dev/kvm — run on the host" >&2; exit 1; }
for c in msb openssl python3; do
	command -v "$c" >/dev/null || { echo "$c not on PATH" >&2; exit 1; }
done

work="$(mktemp -d)"
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null; rm -rf "$work"; }
trap cleanup EXIT
cd "$work" || exit 1

openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.pem -days 1 \
	-subj "/CN=spike 17 CA" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -keyout srv.key -out srv.csr -subj "/CN=$NAME" 2>/dev/null
printf 'subjectAltName=DNS:%s\n' "$NAME" > ext
openssl x509 -req -in srv.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out srv.pem \
	-days 1 -extfile ext 2>/dev/null

LLM_KEY_SPIKE="sk-spike-$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')"
OTHER_TOKEN="other-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
export LLM_KEY_SPIKE OTHER_TOKEN

cat > server.py <<'EOF'
import json, os, ssl, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
cert, key, port, log = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
real = os.environ["LLM_KEY_SPIKE"]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "replace")
        tok = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        auth = "real" if tok == real else "placeholder" if "MSB_" in tok else "none" if not tok else "other"
        with open(log, "a") as fh:
            fh.write(json.dumps({"tag": self.path.strip("/"), "auth": auth}) + "\n")
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers()
        self.wfile.write(b"{}")
srv = ThreadingHTTPServer(("0.0.0.0", port), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert, key)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
EOF
cat > dns.py <<'EOF'
import socket, struct, sys
name, addr, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
up = [l.split()[1] for l in open("/etc/resolv.conf") if l.startswith("nameserver")][0]
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", port))
while True:
    data, peer = s.recvfrom(512)
    off, labels = 12, []
    while data[off]:
        labels.append(data[off + 1:off + 1 + data[off]].decode()); off += data[off] + 1
    if ".".join(labels).lower() != name:
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(3)
        try:
            u.sendto(data, (up, 53)); s.sendto(u.recv(4096), peer)
        except OSError:
            pass
        continue
    qtype = struct.unpack("!H", data[off + 1:off + 3])[0]
    n = 1 if qtype == 1 else 0
    out = data[:2] + struct.pack("!HHHHH", 0x8180, 1, n, 0, 0) + data[12:off + 5]
    if n:
        out += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton(addr)
    s.sendto(out, peer)
EOF
# Its stderr is msb resetting the refused requests, which is the point.
python3 -I server.py srv.pem srv.key "$PORT" "$work/req.log" 2>/dev/null & pids+=($!)
python3 -I dns.py "$NAME" "$ADDR" 5354 & pids+=($!)
sleep 1
note "endpoint https://$NAME:$PORT -> $ADDR, CA in $work/ca.pem"

# The guest: each line is a labelled request. The endpoint logs the label.
cat > guest.sh <<EOF
url=https://$NAME:$PORT
wget -q -O /dev/null --header "Authorization: Bearer \$LLM_KEY_SPIKE" --post-data '{}' \$url/key >/dev/null 2>&1; echo "R_KEY=\$?"
wget -q -O /dev/null --header "Authorization: Bearer \$LLM_KEY_SPIKE" --post-data "{\"t\":\"\$OTHER_TOKEN\"}" \$url/foreign >/dev/null 2>&1; echo "R_FOREIGN=\$?"
wget -q -O /dev/null https://$CONTROL/ >/dev/null 2>&1; echo "R_443=\$?"
wget -q -O /dev/null --header "Authorization: Bearer \$LLM_KEY_SPIKE" https://$CONTROL/ >/dev/null 2>&1; echo "R_LEAK=\$?"
case "\$LLM_KEY_SPIKE" in *MSB_*) echo GUEST=placeholder ;; *) echo GUEST=other ;; esac
EOF

run() {   # run <passthrough options for OTHER_TOKEN> <intercept-port flags...>
	local other="$1"; shift
	rm -f "$work/req.log"
	msb run --pull never --memory 512M -v "$work:/spike:ro" \
		--dns-nameserver 127.0.0.1:5354 \
		--net-default-egress deny \
		--net-rule "allow@dns" \
		--net-rule "allow@$NAME:tcp:$PORT" \
		--net-rule "allow@$CONTROL:tcp:443" \
		--no-dns-rebind-protection \
		--tls-intercept "$@" \
		--tls-upstream-ca-cert-for "$NAME=$work/ca.pem" \
		--secret "LLM_KEY_SPIKE@$NAME" \
		--secret "OTHER_TOKEN${other}@$CONTROL" \
		--secret-violation-action block-and-log \
		"$IMAGE" -- sh /spike/guest.sh 2>&1 | tr -d '\r'
}
val()  { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }
seen() { [ -f "$work/req.log" ] && sed -n "s/.*\"tag\": \"$1\", \"auth\": \"\([a-z]*\)\".*/\1/p" "$work/req.log" | head -1; }

say "A: $PORT intercepted alone, no passthrough"
out="$(run "" --tls-intercept-port "$PORT")"
check "guest holds a placeholder              " placeholder "$(val "$out" GUEST)"
check "(1) the endpoint gets the REAL key     " real "$(seen key)"
check "(3) foreign placeholder in a body: refused" "" "$(seen foreign)"
check "(2) $CONTROL:443 breaks, 443 replaced  " 1 "$(val "$out" R_443)"

say "B: 443 restated, endpoint in passthrough"
out="$(run ":passthrough=[$NAME]" --tls-intercept-port 443 --tls-intercept-port "$PORT")"
check "(1) the endpoint still gets the key    " real "$(seen key)"
check "(3) foreign placeholder: delivered     " real "$(seen foreign)"
check "(2) $CONTROL:443 works again           " 0 "$(val "$out" R_443)"
# The key in a header to a host it is not bound to: msb refuses the request
# (block-and-log) rather than sending either the placeholder or the value.
check "(4) the key toward $CONTROL: refused   " 1 "$(val "$out" R_LEAK)"

say "Result"
if [ "$fail" -eq 0 ]; then
	note "PASS — a LAN model server on any port, with its own CA, keeps its key host-side."
else
	note "FAIL — read the lines above; msbctl's [llm] support relies on every one."
fi
exit "$fail"
