import base64
import socket
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from fareflare import webhook_http
from fareflare.webhook_http import (
    WebhookHTTPTransport,
    new_signing_secret,
    normalize_webhook_url,
    sign_webhook,
    verify_webhook,
)

SECRET = "whsec_" + base64.b64encode(bytes(range(32))).decode()  # Synthetic test vector.
BODY = b'{"type":"price.drop","price":12345}'


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://HOOKS.Example.com:443", "https://hooks.example.com/"),
        (
            "https://hooks.example.com./prices?team=a&token=b",
            "https://hooks.example.com/prices?team=a&token=b",
        ),
        ("https://bücher.example/安", "https://xn--bcher-kva.example/%E5%AE%89"),
        ("https://8.8.8.8/", "https://8.8.8.8/"),
        ("https://[2606:4700:4700::1111]/", "https://[2606:4700:4700::1111]/"),
    ],
)
def test_url_normalization_preserves_endpoint_and_restricts_authority(url, expected):
    assert normalize_webhook_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com",
        "file:///tmp/secret",
        "https://user:pass@hooks.example.com",
        "https://user@hooks.example.com",
        "https://hooks.example.com#",
        "https://hooks.example.com/#part",
        "https://hooks.example.com:8443",
        "https://hooks.example.com:",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.1.2.3",
        "https://172.16.1.1",
        "https://192.168.1.1",
        "https://169.254.169.254/latest/meta-data",
        "https://100.64.0.1",
        "https://224.0.0.1",
        "https://0.0.0.0",
        "https://192.0.0.9",
        "https://192.88.99.1",
        "https://198.18.0.1",
        "https://192.0.2.1",
        "https://[::1]",
        "https://[fc00::1]",
        "https://[fe80::1%eth0]",
        "https://[::ffff:8.8.8.8]",
        "https://[64:ff9b::808:808]",
        "https://[2002:808:808::1]",
        "https://[2001::1]",
        "https://[ff00::1]",
        "https://[2001:db8::1]",
        "https://127.1",
        "https://2130706433",
        "https://0x7f000001",
        "https://0177.0.0.1",
        "https://127%2e0%2e0%2e1",
        "https://example.com\\@127.0.0.1",
        "https://hooks.example.com/\r\nHost:evil",
        " https://hooks.example.com",
        "https://ho\toks.example.com",
        "https://-bad.example",
        "https://bad_.example",
        "https://hooks.example.com/" + "a" * 2048,
    ],
)
def test_url_validation_rejects_unsafe_or_ambiguous_destinations(url):
    with pytest.raises(ValueError, match="public HTTPS URL") as error:
        normalize_webhook_url(url)
    assert url not in str(error.value)


def test_standard_webhooks_known_signature_and_header_case():
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert headers == {
        "webhook-id": "evt_abc",
        "webhook-timestamp": "1700000000",
        "webhook-signature": "v1,NUIcffr29GXGRAkRObKn27f4GU7a4xqL5b+eepLqjno=",
    }
    assert verify_webhook(
        SECRET, BODY, {key.upper(): value for key, value in headers.items()}, now=1700000000
    )
    assert not verify_webhook(SECRET, BODY + b" ", headers, now=1700000000)
    assert not verify_webhook(new_signing_secret(), BODY, headers, now=1700000000)
    assert not verify_webhook(SECRET, BODY, {**headers, "webhook-id": "evt_other"}, now=1700000000)
    assert not verify_webhook(
        SECRET, BODY, {**headers, "webhook-timestamp": "1700000001"}, now=1700000000
    )


def test_signatures_expire_in_both_directions_and_support_rotation():
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert verify_webhook(SECRET, BODY, headers, now=1700000300)
    assert not verify_webhook(SECRET, BODY, headers, now=1700000301)
    assert not verify_webhook(SECRET, BODY, headers, now=1699999699)
    alternate = sign_webhook(new_signing_secret(), "evt_abc", 1700000000, BODY)
    headers["webhook-signature"] = (
        alternate["webhook-signature"] + " " + headers["webhook-signature"]
    )
    assert verify_webhook(SECRET, BODY, headers, now=1700000000)
    assert not verify_webhook(
        SECRET, BODY, {**headers, "webhook-timestamp": "01700000000"}, now=1700000000
    )
    assert not verify_webhook(
        SECRET, BODY, {**headers, "webhook-signature": "v1,安"}, now=1700000000
    )
    assert not verify_webhook(SECRET, BODY, {}, now=1700000000)
    assert not verify_webhook(SECRET, BODY, headers, now=1700000000, tolerance=-1)


def test_generated_secrets_have_256_bits_and_invalid_inputs_do_not_leak():
    first, second = new_signing_secret(), new_signing_secret()
    assert first != second
    assert len(base64.b64decode(first[6:], validate=True)) == 32
    for invalid in ("secret-value", "whsec_!!!!", "whsec_YQ=="):
        with pytest.raises(ValueError, match="Invalid webhook signing secret") as error:
            sign_webhook(invalid, "evt_abc", 1700000000, BODY)
        assert invalid not in str(error.value)
    for event_id, timestamp, payload in (
        ("bad\r\nheader", 1, BODY),
        ("event", True, BODY),
        ("event", -1, BODY),
        ("event", 1, b"x" * 65537),
    ):
        with pytest.raises(ValueError, match="signing input"):
            sign_webhook(SECRET, event_id, timestamp, payload)


def dns_record(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443)


@pytest.mark.parametrize(
    "addresses",
    [
        ["8.8.8.8", "127.0.0.1"],
        ["8.8.8.8", "10.0.0.1"],
        ["8.8.8.8", "::1"],
        ["8.8.8.8", "::ffff:169.254.169.254"],
        ["8.8.8.8", "2002:7f00:1::"],
    ],
)
def test_every_dns_answer_is_validated_including_ipv6(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [dns_record(ip) for ip in addresses])
    with pytest.raises(ValueError, match="public internet"):
        webhook_http._resolve_addresses("hooks.example.com", 1)


def test_dns_results_are_deduplicated_and_name_is_absolute(monkeypatch):
    lookups = []

    def resolve(*args):
        lookups.append(args)
        return [dns_record("8.8.8.8"), dns_record("8.8.8.8"), dns_record("2606:4700:4700::1111")]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert webhook_http._resolve_addresses("hooks.example.com", 1) == (
        "8.8.8.8",
        "2606:4700:4700::1111",
    )
    assert lookups == [
        ("hooks.example.com.", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    ]


def test_dns_timeout_returns_promptly_and_lookup_slots_are_bounded(monkeypatch):
    release = threading.Event()
    completed = threading.Event()
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(webhook_http, "_DNS_SLOTS", slots)

    def resolve(*args):
        try:
            release.wait(1)
            return [dns_record("8.8.8.8")]
        finally:
            completed.set()

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            webhook_http._resolve_addresses("hooks.example.com", 0.02)
        assert time.monotonic() - start < 0.5
        with pytest.raises(TimeoutError, match="unavailable"):
            webhook_http._resolve_addresses("hooks.example.com", 1)
    finally:
        release.set()
        assert completed.wait(1)


@pytest.fixture
def network(monkeypatch):
    captured = {
        "connect": [],
        "closed": 0,
        "tls": [],
        "requests": [],
        "status": 204,
        "shutdown": threading.Event(),
        "dns": [],
    }

    class FakeSocket:
        def settimeout(self, timeout):
            assert 0 < timeout <= 10

        def connect(self, address):
            captured["connect"].append(address)

        def do_handshake(self):
            if captured.get("tls_error"):
                raise ssl.SSLCertVerificationError("private certificate diagnostic")

        def shutdown(self, how):
            captured["shutdown"].set()

        def close(self):
            captured["closed"] += 1

    class FakeContext:
        def wrap_socket(self, raw, **kwargs):
            captured["tls"].append(kwargs)
            return raw

    class FakeResponse:
        @property
        def status(self):
            return captured["status"]

        def close(self):
            captured["response_closed"] = True

        def read(self, *args):
            pytest.fail("Webhook transport must never read response bodies")

    class FakeConnection:
        def __init__(self, host, port, timeout, context):
            captured["http_host"] = (host, port)
            self.sock = None

        def request(self, method, path, body, headers):
            assert self.sock is not None
            captured["requests"].append((method, path, body, headers))

        def getresponse(self):
            if captured.get("slow"):
                assert captured["shutdown"].wait(0.5)
                raise OSError("read interrupted by deadline")
            return FakeResponse()

        def close(self):
            captured["connection_closed"] = True

    def resolve(*args):
        captured["dns"].append(args)
        return [dns_record(captured.get("dns_ip", "8.8.8.8"))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(webhook_http.ssl, "create_default_context", FakeContext)
    monkeypatch.setattr(webhook_http.http.client, "HTTPSConnection", FakeConnection)
    return captured


def test_transport_pins_ip_keeps_original_tls_hostname_and_sends_exact_bytes(network, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://127.0.0.1:9999")
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert WebhookHTTPTransport().send("https://hooks.example.com/alerts?x=1", BODY, headers)
    assert network["connect"] == [("8.8.8.8", 443)]
    assert network["http_host"] == ("hooks.example.com", 443)
    assert network["tls"] == [
        {"server_hostname": "hooks.example.com", "do_handshake_on_connect": False}
    ]
    method, path, body, actual_headers = network["requests"][0]
    assert (method, path, body) == ("POST", "/alerts?x=1", BODY)
    assert verify_webhook(SECRET, body, actual_headers, now=1700000000)
    assert actual_headers["Connection"] == "close"
    assert len(network["dns"]) == 1
    assert network["response_closed"] and network["closed"]


def test_dns_rebinding_cannot_reach_private_addresses_on_later_attempts(network):
    transport = WebhookHTTPTransport()
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert transport.send("https://hooks.example.com/", BODY, headers)
    network["dns_ip"] = "127.0.0.1"
    assert not transport.send("https://hooks.example.com/", BODY, headers)
    assert len(network["dns"]) == 2
    assert network["connect"] == [("8.8.8.8", 443)]


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299, 300, 301, 302, 307, 400, 429, 500])
def test_only_2xx_succeeds_and_redirects_are_not_followed(network, status):
    network["status"] = status
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert WebhookHTTPTransport().send("https://hooks.example.com/", BODY, headers) is (
        200 <= status < 300
    )
    assert len(network["requests"]) == 1
    assert network["closed"] and network["connection_closed"]


def test_tls_validation_failure_is_sanitized_and_closes_socket(network):
    network["tls_error"] = True
    assert not WebhookHTTPTransport().send(
        "https://hooks.example.com/", BODY, sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    )
    assert network["requests"] == []
    assert network["closed"]


def test_total_deadline_interrupts_a_slow_response(network):
    network["slow"] = True
    start = time.monotonic()
    assert not WebhookHTTPTransport(timeout=0.02).send(
        "https://hooks.example.com/", BODY, sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    )
    assert time.monotonic() - start < 0.5
    assert network["shutdown"].is_set()
    assert network["closed"]


def test_transport_rejects_header_overrides_injection_and_oversized_body_before_io(network):
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    transport = WebhookHTTPTransport()
    assert not transport.send(
        "https://hooks.example.com/", BODY, {**headers, "Host": "internal.example"}
    )
    assert not transport.send(
        "https://hooks.example.com/", BODY, {**headers, "webhook-id": "id\r\ninjected: true"}
    )
    assert not transport.send("https://hooks.example.com/", b"x" * 65537, headers)
    assert network["dns"] == [] and network["connect"] == []


@pytest.mark.parametrize("timeout", [0, -1, 16, float("inf"), float("nan")])
def test_transport_requires_a_bounded_timeout(timeout):
    with pytest.raises(ValueError):
        WebhookHTTPTransport(timeout)


@pytest.fixture
def local_tls(monkeypatch, tmp_path):
    """Exercise real TLS and HTTP while directing only the test socket to localhost."""
    hostname = "hooks.example.com"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    captured = {"connect": [], "sni": [], "slow": False, "body": None, "headers": None}
    server_context.set_servername_callback(lambda sock, name, ctx: captured["sni"].append(name))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(1)
    destination = listener.getsockname()
    stop = threading.Event()
    finished = threading.Event()
    real_socket = socket.socket

    class LocalSocket(real_socket):
        def connect(self, address):
            captured["connect"].append(address)
            assert address == ("8.8.8.8", 443)
            # The actual transport has already validated and pinned this public
            # address. Only this test socket redirects it to an isolated listener.
            return super().connect(destination)

    def serve():
        try:
            raw, _ = listener.accept()
            raw.settimeout(1)
            with server_context.wrap_socket(raw, server_side=True) as stream:
                data = b""
                while b"\r\n\r\n" not in data and len(data) < 65536:
                    part = stream.recv(4096)
                    if not part:
                        return
                    data += part
                header_bytes, body = data.split(b"\r\n\r\n", 1)
                lines = header_bytes.decode("ascii").split("\r\n")
                captured["request_line"] = lines[0]
                captured["headers"] = dict(line.split(": ", 1) for line in lines[1:])
                length = int(captured["headers"]["Content-Length"])
                while len(body) < length:
                    part = stream.recv(length - len(body))
                    if not part:
                        return
                    body += part
                captured["body"] = body
                if captured["slow"]:
                    stream.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    while not stop.wait(0.005):
                        stream.sendall(b"a")
                else:
                    # A huge body that never arrives must not delay acceptance.
                    stream.sendall(b"HTTP/1.1 202 Accepted\r\nContent-Length: 999999999\r\n\r\n")
                    stop.wait(1)
        except (OSError, ValueError):
            pass  # Certificate rejection and deadline closure are exercised below.
        finally:
            finished.set()

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [dns_record("8.8.8.8")])
    monkeypatch.setattr(socket, "socket", LocalSocket)
    thread = threading.Thread(target=serve, name="webhook-local-tls-test", daemon=True)
    thread.start()
    transport = WebhookHTTPTransport(timeout=0.5)
    transport._context = ssl.create_default_context(cafile=str(cert_path))
    try:
        yield transport, captured
    finally:
        stop.set()
        listener.close()
        assert finished.wait(2)


def test_real_tls_and_http_preserve_sni_host_body_and_skip_response_body(local_tls):
    transport, captured = local_tls
    headers = sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    assert transport.send("https://hooks.example.com/price?query=a%20b", BODY, headers)
    assert captured["connect"] == [("8.8.8.8", 443)]
    assert captured["sni"] == ["hooks.example.com"]
    assert captured["request_line"] == "POST /price?query=a%20b HTTP/1.1"
    assert captured["headers"]["Host"] == "hooks.example.com"
    assert captured["body"] == BODY
    assert verify_webhook(SECRET, captured["body"], captured["headers"], now=1700000000)


def test_real_tls_rejects_wrong_hostname_even_with_trusted_certificate(local_tls):
    transport, captured = local_tls
    assert not transport.send(
        "https://wrong.example.com/", BODY, sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    )
    assert captured["sni"] == ["wrong.example.com"]
    assert captured["body"] is None


def test_real_tls_slow_header_stream_is_interrupted_by_total_deadline(local_tls):
    transport, captured = local_tls
    transport.timeout = 0.1
    captured["slow"] = True
    start = time.monotonic()
    assert not transport.send(
        "https://hooks.example.com/", BODY, sign_webhook(SECRET, "evt_abc", 1700000000, BODY)
    )
    assert time.monotonic() - start < 0.5
    assert captured["body"] == BODY
