"""serve = "proxy": `kandev tls install`, lease tokens, `health.tls` and the
TLS proxy itself, over real TLS on loopback. The certificates are made by
`openssl` at test time (a name-constrained root and its leaves), so no key is
ever committed."""

import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from unittest import mock, skipUnless

from tests.test_kandev import KandevTest, PLANTED_NPM

HAVE_OPENSSL = shutil.which("openssl") is not None
# What Kandev sends as Authorization on every request, for agentctl itself.
AGENTCTL_TOKEN = "planted-agentctl-token"


def _openssl(*argv, cwd):
    subprocess.run(["openssl", *argv], cwd=cwd, check=True, capture_output=True)


def make_pki(where):
    """{name: path}: a root, a leaf for localhost/127.0.0.1 and one for
    another name, both under the root, and a key that matches neither."""
    ec = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes"]
    _openssl("req", "-x509", *ec, "-keyout", "ca.key", "-out", "ca.pem", "-days", "30",
             "-subj", "/CN=Test Kandev Root",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign",
             "-addext", "nameConstraints=critical,permitted;DNS:localhost,permitted;DNS:other.example,"
             "permitted;IP:127.0.0.0/255.0.0.0", cwd=where)
    for leaf, san in (("leaf", "DNS:localhost,IP:127.0.0.1"), ("other", "DNS:other.example")):
        with open(os.path.join(where, f"{leaf}.ext"), "w", encoding="utf-8") as fh:
            fh.write(f"subjectAltName={san}\nextendedKeyUsage=serverAuth\n")
        _openssl("req", "-new", *ec, "-keyout", f"{leaf}.key", "-out", f"{leaf}.csr",
                 "-subj", f"/CN={leaf}", cwd=where)
        _openssl("x509", "-req", "-in", f"{leaf}.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                 "-set_serial", "2" if leaf == "leaf" else "3", "-days", "10",
                 "-extfile", f"{leaf}.ext", "-out", f"{leaf}.pem", cwd=where)
    _openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
             "-out", "stray.key", cwd=where)
    return {n: os.path.join(where, n) for n in os.listdir(where)}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@skipUnless(HAVE_OPENSSL, "needs the openssl command to make test certificates")
class TlsTest(KandevTest):

    @classmethod
    def setUpClass(cls):
        cls.pki_dir = tempfile.mkdtemp(prefix="msbctl-pki-")
        cls.pki = make_pki(cls.pki_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.pki_dir, ignore_errors=True)

    def configure(self, **over):
        values = {"serve": '"proxy"', "proxy_listen": '"127.0.0.1"', "base_url": '"https://localhost"'}
        values.update(over)
        super().configure(**values)

    def pair(self, leaf="leaf", key=None, chain=True):
        cert = read(self.pki[f"{leaf}.pem"]) + (read(self.pki["ca.pem"]) if chain else "")
        return json.dumps({"cert_pem": cert, "key_pem": read(self.pki[key or f"{leaf}.key"])}) + "\n"

    def install(self, **pair):
        return self.ok("tls", "install", stdin=self.pair(**pair))["tls"]

    def ca_sha256(self):
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(read(self.pki["ca.pem"]))).hexdigest()

    def later(self, days):
        moved = self.m.utc_now() + dt.timedelta(days=days)
        return mock.patch.object(self.m, "utc_now", lambda: moved)


class TlsInstall(TlsTest):

    def test_install_writes_the_pair_and_reports_it(self):
        doc = self.install()
        self.assertEqual(doc["subject"], "localhost")
        self.assertEqual(doc["issuer_sha256"], self.ca_sha256())
        self.assertTrue(doc["installed"])
        self.assertEqual(os.stat(self.m.KANDEV_TLS_KEY).st_mode & 0o777, 0o600)
        self.assertEqual(read(self.m.KANDEV_TLS_KEY), read(self.pki["leaf.key"]))
        self.assertEqual(self.ok("health")["tls"], doc)

    def test_bad_pairs_change_nothing(self):
        self.install()
        before = (read(self.m.KANDEV_TLS_CERT), read(self.m.KANDEV_TLS_KEY))
        key_body = read(self.pki["stray.key"]).splitlines()[1]
        for label, stdin in (("mismatched", self.pair(key="stray.key")),
                             ("wrong name", self.pair(leaf="other")),
                             ("no issuer", self.pair(chain=False)),
                             ("not json", "{\n")):
            with self.subTest(label):
                code, doc = self.kandev("tls", "install", stdin=stdin)
                self.assertEqual((code, doc["error"]["code"]), (3, "invalid_config"), doc)
                self.assertNotIn(key_body, json.dumps(doc))
        with self.later(30):
            self.error("invalid_config", "tls", "install", stdin=self.pair())
        self.assertEqual((read(self.m.KANDEV_TLS_CERT), read(self.m.KANDEV_TLS_KEY)), before)
        self.assertEqual(sorted(os.listdir(self.m.KANDEV_TLS_DIR)), ["cert.pem", "key.pem"])

    def test_the_key_is_never_printed(self):
        code, out, err = self.run_main("kandev", "tls", "install", stdin=self.pair().encode())
        self.assertEqual(code, 0, err)
        body = read(self.pki["leaf.key"]).splitlines()[1]
        self.assertNotIn(body, out + err)

    def test_needs_base_url_and_the_install_action(self):
        self.configure(base_url='""')
        self.error("invalid_config", "tls", "install", stdin=self.pair())
        self.configure()
        self.error("invalid_config", "tls", "remove", stdin=self.pair())


class Health(TlsTest):

    def serve_doc(self):
        return self.ok("health")["serve"]

    def test_no_certificate(self):
        doc = self.ok("health")
        self.assertEqual(doc["tls"], {"installed": False})
        self.assertFalse(doc["serve"]["ok"])
        self.assertIn("certificate", doc["serve"]["reason"])
        self.assertEqual((doc["serve"]["mode"], doc["serve"]["listen"]), ("proxy", "127.0.0.1"))

    def test_expired_certificate(self):
        self.install()
        with self.lock_held():
            self.assertTrue(self.serve_doc()["ok"])
            with self.later(30):
                doc = self.ok("health")
        self.assertTrue(doc["tls"]["installed"])
        self.assertFalse(doc["serve"]["ok"])
        self.assertIn("not now", doc["serve"]["reason"])

    def test_proxy_not_running(self):
        self.install()
        doc = self.serve_doc()
        self.assertEqual((doc["ok"], doc["running"]), (False, False))
        self.assertIn("not running", doc["reason"])
        with self.lock_held():
            # A lock with nothing in it: a proxy from before it said its release.
            self.assertEqual(self.serve_doc(), {"ok": True, "mode": "proxy", "listen": "127.0.0.1",
                                                "running": True, "version": ""})

    def test_proxy_listen_unset(self):
        self.install()
        self.configure(proxy_listen='""')
        with self.lock_held():
            doc = self.serve_doc()
        self.assertFalse(doc["ok"])
        self.assertIn("proxy_listen", doc["reason"])

    def test_tailscale_without_certificates(self):
        self.configure(serve='"tailscale"')
        self.assertTrue(self.serve_doc()["ok"])
        os.environ["FAKE_TAILSCALE_NO_CERTS"] = "1"
        doc = self.serve_doc()
        self.assertFalse(doc["ok"])
        self.assertIn("CertDomains", doc["reason"])

    def test_config(self):
        self.configure(serve=None)
        self.assertEqual(self.serve_doc()["mode"], "proxy")        # the default
        for key, value in (("proxy_listen", '"sbx-01"'), ("proxy_port_pool", '"25000-35000"'),
                           ("serve", '"caddy"')):
            with self.subTest(key=key):
                self.configure(**{key: value})
                self.assertIn(key, self.error("invalid_config", "health")["message"])

    def lock_held(self):
        """Hold the proxy's lock as a running proxy does."""
        import fcntl

        @contextlib.contextmanager
        def held():
            os.makedirs(os.path.dirname(self.m.KANDEV_PROXY_LOCK), exist_ok=True)
            with open(self.m.KANDEV_PROXY_LOCK, "a", encoding="utf-8") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                yield
        return held()


class Leases(TlsTest):

    def test_proxy_lease_and_token(self):
        self.install()
        rec = self.provision()
        entry = self.m.read_toml(self.entry_path("k-6f1c2b9e"))
        self.assertEqual(entry["serve"], "proxy")
        public = self.m.kandev_proxy_ports(entry)
        self.assertEqual(sorted(public), [8765, 41001, 41002, 41003])
        self.assertTrue(all(30000 <= p <= 39999 for p in public.values()))
        lease = self.ok("lease", "6f1c2b9e", "8765")["lease"]
        self.assertEqual(lease["base_url"], f"https://localhost:{public[8765]}")
        self.assertEqual(lease["generation"], "1")
        # Never Authorization: Kandev refuses a lease that sets it.
        self.assertEqual(list(lease["headers"]), ["X-Msb-Lease"])
        token = lease["headers"]["X-Msb-Lease"]
        self.assertEqual(os.stat(self.m.KANDEV_LEASE_KEY).st_mode & 0o777, 0o600)
        keys = self.m.kandev_lease_keys()
        me = self.m.kandev_incarnation(entry)
        ok = self.m.kandev_token_ok
        self.assertTrue(ok(keys, token, rec["name"], 8765, me))
        self.assertFalse(ok(keys, token, "k-other", 8765, me))
        self.assertFalse(ok(keys, token, rec["name"], 41001, me))
        self.assertFalse(ok(keys, token, rec["name"], 8765, me + "x"))     # another incarnation
        self.assertFalse(ok([os.urandom(32)], token, rec["name"], 8765, me))
        self.assertFalse(ok(keys, token[:-1] + ("A" if token[-1] != "A" else "B"), rec["name"], 8765, me))
        # Reported to expire in 10 minutes, accepted for 15 (plus the skew).
        expires = self.m.parse_iso(lease["expires_at"]).timestamp()
        valid_until = int(token.split(".")[1])
        self.assertEqual(valid_until - expires, 300)
        self.assertTrue(ok(keys, token, rec["name"], 8765, me, now=valid_until + 29))
        self.assertFalse(ok(keys, token, rec["name"], 8765, me, now=valid_until + 31))

    def test_a_rotated_key_is_accepted_for_15_minutes(self):
        self.install()
        self.provision()
        token = self.ok("lease", "6f1c2b9e", "8765")["lease"]["headers"]["X-Msb-Lease"]
        me = self.m.kandev_incarnation(self.m.read_toml(self.entry_path("k-6f1c2b9e")))
        code, _, err = self.run_main("host", "kandev", "rotate-lease-key")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.m.KANDEV_LEASE_KEY_PREV))
        self.assertTrue(self.m.kandev_token_ok(self.m.kandev_lease_keys(), token, "k-6f1c2b9e", 8765, me))
        fresh = self.ok("lease", "6f1c2b9e", "8765")["lease"]["headers"]["X-Msb-Lease"]
        self.assertNotEqual(fresh, token)
        past = time.time() - self.m.KANDEV_LEASE_VALID - 1
        os.utime(self.m.KANDEV_LEASE_KEY_PREV, (past, past))
        self.assertFalse(self.m.kandev_token_ok(self.m.kandev_lease_keys(), token, "k-6f1c2b9e", 8765, me))
        self.assertTrue(self.m.kandev_token_ok(self.m.kandev_lease_keys(), fresh, "k-6f1c2b9e", 8765, me))

    def test_two_sandboxes_never_share_a_public_port(self):
        self.provision("e1", operation_id="op-1")
        self.provision("e2", operation_id="op-2")
        ports = [set(self.m.kandev_proxy_ports(self.m.read_toml(self.entry_path(n))).values())
                 for n in ("k-e1", "k-e2")]
        self.assertFalse(ports[0] & ports[1])

    def test_lease_needs_a_certificate(self):
        self.provision()
        self.error("unavailable", "lease", "6f1c2b9e", "8765")

    def test_destroy_undoes_the_mode_it_was_made_with(self):
        self.configure(serve='"tailscale"')
        self.provision()
        self.configure()                                # serve = "proxy" now
        self.purge("k-6f1c2b9e")
        self.assertEqual(len([c for c in self.tailscale_calls() if c[-1:] == ["off"]]), 4)

    def test_an_entry_from_before_serve_was_recorded(self):
        self.configure(serve='"tailscale"')
        self.provision()
        path = self.entry_path("k-6f1c2b9e")
        with open(path, encoding="utf-8") as fh:
            text = fh.read().replace('serve        = "tailscale"\n', "")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        # Best effort: a tailscale that fails no longer blocks the destroy.
        os.environ["FAKE_TAILSCALE_FAIL"] = "serve"
        self.assertEqual(self.purge("k-6f1c2b9e")["purged"], ["k-6f1c2b9e"])


class EchoBackend:
    """A guest port stand-in on 127.0.0.1: greets with its tag, then echoes."""

    def __init__(self, port, tag):
        self.sock = socket.create_server(("127.0.0.1", port))
        self.tag = tag
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.echo, args=(conn,), daemon=True).start()

    def echo(self, conn):
        with conn:
            conn.sendall(self.tag.encode() + b"\n")
            while data := conn.recv(65536):
                conn.sendall(data)

    def close(self):
        self.sock.close()


class Proxy(TlsTest):

    def setUp(self):
        super().setUp()
        self.install()
        self.logs = []
        self.backends = []
        self.e1 = self.provision("e1", operation_id="op-1")
        self.e2 = self.provision("e2", operation_id="op-2")
        for rec in (self.e1, self.e2):
            for guest, host in rec["ports"].items():
                self.backends.append(EchoBackend(host, f"{rec['name']}:{guest}"))
        self.client_ctx = ssl.create_default_context(cafile=self.pki["ca.pem"])
        self.halt = threading.Event()
        patches = [mock.patch.object(self.m, "KANDEV_PROXY_SCAN", 0.2),
                   mock.patch.object(self.m, "kandev_proxy_log", self.logs.append)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.thread = threading.Thread(target=self.m.kandev_proxy, args=(self.halt,), daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        for rec in (self.e1, self.e2):
            for port in self.public(rec["name"]).values():
                self.wait_for(port, listening=True)

    def shutdown(self):
        self.halt.set()
        self.thread.join(5)
        for backend in self.backends:
            backend.close()

    def public(self, name):
        return self.m.kandev_proxy_ports(self.m.read_toml(self.entry_path(name)))

    def wait_for(self, port, listening):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                if listening:
                    return
            except ConnectionRefusedError:
                if not listening:
                    return
            time.sleep(0.05)
        self.fail(f"port {port} still {'refuses' if listening else 'accepts'} after 5 s")

    def lease(self, env, guest):
        """(public port, the lease token)."""
        lease = self.ok("lease", env, str(guest))["lease"]
        return int(lease["base_url"].rsplit(":", 1)[1]), lease["headers"]["X-Msb-Lease"]

    def request(self, port, lease=None, extra=""):
        """(the client's TLS socket, the first line it reads back). As Kandev
        sends it: the lease headers, and its own Authorization for agentctl."""
        raw = socket.create_connection(("127.0.0.1", port), timeout=5)
        tls = self.client_ctx.wrap_socket(raw, server_hostname="localhost")
        head = f"GET / HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {AGENTCTL_TOKEN}\r\n"
        if lease:
            head += f"X-Msb-Lease: {lease}\r\n"
        tls.sendall((head + extra + "\r\n").encode())
        line = b""
        while not line.endswith(b"\n"):
            chunk = tls.recv(1)
            if not chunk:
                break
            line += chunk
        return tls, line.decode()

    def assert_refused(self, port, lease=None, extra=""):
        tls, line = self.request(port, lease, extra)
        tls.close()
        self.assertTrue(line.startswith("HTTP/1.1 401"), line)

    def test_health_reports_which_release_the_proxy_is(self):
        serve = self.ok("health")["serve"]
        self.assertTrue(serve["running"])
        self.assertEqual(serve["version"], self.m.version_string())
        self.assertEqual(self.m.kandev_restart_proxy(self.m.version_string())["state"], "current")

    def test_a_lease_reaches_its_port_and_splices_both_ways(self):
        port, token = self.lease("e1", 8765)
        tls, line = self.request(port, token)
        with tls:
            self.assertEqual(line, "k-e1:8765\n")
            echoed = b""
            while not echoed.endswith(b"\r\n\r\n"):
                echoed += tls.recv(4096)
            self.assertTrue(echoed.startswith(b"GET / HTTP/1.1\r\n"))
            # agentctl's own Authorization reaches the guest untouched.
            self.assertIn(f"Authorization: Bearer {AGENTCTL_TOKEN}\r\n".encode(), echoed)
            time.sleep(0.5)                 # idle, then more traffic, as a WebSocket would
            tls.sendall(b"ping")
            self.assertEqual(tls.recv(4), b"ping")

    def test_refusals(self):
        port, token = self.lease("e1", 8765)
        self.assert_refused(port)
        self.assert_refused(port, "v1.1.x")
        _, other_sandbox = self.lease("e2", 8765)
        self.assert_refused(port, other_sandbox)
        _, other_port = self.lease("e1", 41001)
        self.assert_refused(port, other_port)
        key = self.m.kandev_lease_key(create=False)
        me = self.m.kandev_incarnation(self.m.read_toml(self.entry_path("k-e1")))
        old = self.m.kandev_token(key, "k-e1", 8765, me, int(time.time()) - 60)
        self.assert_refused(port, old)
        self.assert_refused(port, token, extra=f"X-Msb-Lease: {token}\r\n")        # two
        # A valid token anywhere but X-Msb-Lease is nothing.
        self.assert_refused(port, None, extra=f"Authorization: Bearer {token}\r\n")

    def test_ports_never_cross(self):
        for rec in (self.e1, self.e2):
            for guest, public in self.public(rec["name"]).items():
                port, token = self.lease(rec["env"], guest)
                self.assertEqual(port, public)
                tls, line = self.request(port, token)
                tls.close()
                self.assertEqual(line, f"{rec['name']}:{guest}\n")

    def test_a_token_survives_stop_and_start_but_not_reprovision(self):
        port, token = self.lease("e1", 8765)
        self.stop("k-e1")
        start = json.dumps({"secrets": [{"name": "NPM_TOKEN", "value": PLANTED_NPM}]}) + "\n"
        self.assertEqual(self.ok("start", "e1", stdin=start)["record"]["generation"], 2)
        # Kandev keeps the lease it holds until it refreshes it.
        tls, line = self.request(port, token)
        tls.close()
        self.assertEqual(line, "k-e1:8765\n")
        # Destroyed and provisioned again, within the same second even: a new
        # incarnation, which the old token is not for.
        self.purge("k-e1")
        again = self.provision("e1", operation_id="op-3")
        self.backends.append(EchoBackend(again["ports"]["8765"], "k-e1:8765"))
        port = self.public("k-e1")[8765]
        self.wait_for(port, listening=True)
        self.assert_refused(port, token)
        port, token = self.lease("e1", 8765)
        tls, line = self.request(port, token)
        tls.close()
        self.assertEqual(line, "k-e1:8765\n")

    def test_a_destroyed_sandboxs_port_refuses(self):
        ports = self.public("k-e2")
        port, token = self.lease("e2", 8765)
        tls, line = self.request(port, token)            # open across the destroy
        self.assertEqual(line, "k-e2:8765\n")
        self.purge("k-e2")
        for public in ports.values():
            self.wait_for(public, listening=False)
        # And its connection is cut: EOF, with or without a close_notify. A
        # connection left open fails the test with the socket's 5 s timeout.
        with contextlib.suppress(ssl.SSLEOFError, ConnectionResetError):
            while tls.recv(4096):
                continue
        tls.close()
        # e1 is untouched.
        port, token = self.lease("e1", 8765)
        tls, line = self.request(port, token)
        tls.close()
        self.assertEqual(line, "k-e1:8765\n")

    def test_logs_hold_no_token(self):
        port, token = self.lease("e1", 8765)
        tls, _ = self.request(port, token)
        tls.close()
        self.assert_refused(port, token + "x")
        deadline = time.monotonic() + 5
        while not {"forwarded", "unauthorized"} <= {m.rsplit(" ", 1)[-1] for m in self.logs} \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        # (wait_for()'s bare connects add "tls handshake failed" lines.)
        outcomes = [m.rsplit(" ", 1)[-1] for m in self.logs if "k-e1 8765" in m]
        self.assertIn("forwarded", outcomes)
        self.assertIn("unauthorized", outcomes)
        for message in self.logs:
            self.assertNotIn(token, message)
            self.assertNotIn(AGENTCTL_TOKEN, message)
            self.assertNotIn("X-Msb-Lease", message)

    def test_one_proxy_per_host(self):
        code, _, err = self.run_main("host", "kandev", "proxy")
        self.assertNotEqual(code, 0)
        self.assertIn("already running", err)
        self.assertTrue(self.ok("health")["serve"]["running"])

