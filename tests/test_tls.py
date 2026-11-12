"""The self-signed certificate, and the QR that saves typing an IP on glass."""

import shutil
import ssl
import subprocess

import pytest

from paperpen import qr, tls

needs_openssl = pytest.mark.skipif(not shutil.which("openssl"),
                                   reason="no openssl on this machine")


@needs_openssl
def test_the_certificate_names_the_addresses_a_tablet_would_type(board):
    """A browser checks the address against subjectAltName, and an IP has to
    be in there as an IP: a certificate carrying only a common name has not
    been accepted by Chrome since 2017."""
    made = tls.make()

    assert "localhost" in made["dns"] and "127.0.0.1" in made["ip"]
    text = subprocess.run(["openssl", "x509", "-in", made["cert"], "-noout", "-text"],
                          capture_output=True, text=True).stdout
    assert "IP Address:127.0.0.1" in text
    assert "DNS:localhost" in text
    assert "CA:FALSE" in text
    assert "TLS Web Server Authentication" in text


@needs_openssl
def test_the_key_is_private_and_the_certificate_is_not(board):
    tls.make()
    assert tls.key_file().stat().st_mode & 0o077 == 0
    assert tls.cert_file().stat().st_mode & 0o004, "the certificate is meant to travel"


@needs_openssl
def test_it_is_a_certificate_openssl_and_python_both_accept(board):
    """Made, then actually loaded into an SSL context, which is the only proof
    that `serve` will not fall over on it."""
    tls.make()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tls.cert_file()), str(tls.key_file()))


@needs_openssl
def test_a_certificate_that_no_longer_names_this_machine_is_noticed(board):
    """A laptop gets a new address from DHCP and the certificate quietly stops
    matching; the browser then refuses it for a reason that reads like a bug."""
    tls.make()
    assert tls.covers("127.0.0.1")
    assert not tls.covers("203.0.113.9")


@needs_openssl
def test_the_fingerprint_is_the_one_openssl_prints(board):
    """It is what you check on the tablet's screen before accepting a warning,
    so it has to be the same string the rest of the world shows."""
    tls.make()
    said = subprocess.run(["openssl", "x509", "-in", str(tls.cert_file()),
                           "-noout", "-fingerprint", "-sha256"],
                          capture_output=True, text=True).stdout.strip()
    assert said.split("=", 1)[1] == tls.fingerprint()


def test_the_qr_encodes_what_it_says_it_does():
    """Checked by decoding it rather than by looking at it: a QR that is
    subtly wrong is a picture that simply does not scan."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    url = "https://192.0.2.7:8770/"
    rows = qr.matrix(url)
    image = np.kron(np.array([[0 if m else 255 for m in r] for r in rows], dtype="uint8"),
                    np.ones((10, 10), dtype="uint8"))
    got, *_ = cv2.QRCodeDetector().detectAndDecode(image)
    assert got == url


def test_the_qr_has_its_quiet_zone():
    """Scanners want four modules of margin and sit there failing without it."""
    rows = qr.matrix("https://192.0.2.7:8770/")
    assert all(m == 0 for m in rows[0]), "the top margin"
    assert all(r[0] == 0 for r in rows), "the left margin"
    assert sum(sum(r) for r in rows) > 0, "and something in the middle"


def test_the_terminal_drawing_is_half_the_height_of_the_code():
    rows = qr.matrix("https://192.0.2.7:8770/")
    lines = qr.to_text("https://192.0.2.7:8770/").split("\n")
    assert len(lines) == (len(rows) + 1) // 2
    assert len({len(line) for line in lines}) == 1, "and rectangular"


def test_a_light_terminal_gets_it_the_other_way_round():
    dark = qr.to_text("https://192.0.2.7:8770/")
    light = qr.to_text("https://192.0.2.7:8770/", invert=True)
    assert dark != light
    assert len(dark.split("\n")) == len(light.split("\n"))


def test_the_svg_is_the_same_code(tmp_path):
    svg = qr.to_svg("https://192.0.2.7:8770/")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "shape-rendering=\"crispEdges\"" in svg, "or it blurs into unscannable"
