"""A self-signed certificate, so the LAN reader is not in the clear.

The reader is served to a tablet over the network, and until now that meant
the password and every paper crossing it in plain HTTP. This closes that. It
does not pretend to be a public certificate authority: what it makes is one
self-signed certificate for this machine, which the tablet is told once to
trust, and which is then as private as a real one between those two ends.

What it does not give you is the padlock a browser shows without being asked.
A self-signed certificate is trusted by nobody until somebody says so, and a
browser is right to interrupt. There are two honest ways through that and both
are here:

- **Install it on the tablet**, once, and it is trusted afterwards with no
  warning. `paperpen tls` says where the file is and what its fingerprint is.
- **Accept the warning**, which works and has to be done again periodically,
  and which is only safe if you check the fingerprint against the one printed
  here. An unchecked "proceed anyway" on a network you do not control is how
  this gets read by somebody else.

The names matter more than they look. A browser checks the address it was
given against the certificate's subjectAltName, and an IP address typed into a
tablet has to be in there *as an IP*, not as a common name: a certificate
carrying only a CN has not been accepted by Chrome since 2017. So the LAN
address is put in the SANs, and the certificate has to be made again when that
address changes, which `serve` checks and says.

Validity is 397 days because Apple refuses a TLS certificate valid for more
than 398, self-signed included, and an iPad is exactly the reader this exists
for.
"""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config

DAYS = 397


def tls_dir() -> Path:
    return config.home() / "tls"


def cert_file() -> Path:
    return tls_dir() / "cert.pem"


def key_file() -> Path:
    return tls_dir() / "key.pem"


def exists() -> bool:
    return cert_file().is_file() and key_file().is_file()


def lan_ip() -> str:
    """The address this machine is reached at from the network it is on.

    Asked of the routing table rather than of the hostname, which on a laptop
    resolves to 127.0.1.1 and would put the wrong name in the certificate.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))     # documentation range; nothing is sent
            return s.getsockname()[0]
    except OSError:
        return ""


def names() -> tuple[list[str], list[str]]:
    """(dns, ip) for the subjectAltName. Whatever the tablet might type."""
    dns = ["localhost"]
    host = socket.gethostname()
    if host and host not in dns:
        dns.append(host)
        dns.append(f"{host}.local")         # what mDNS answers on a home network
    ips = ["127.0.0.1"]
    here = lan_ip()
    if here and here not in ips:
        ips.append(here)
    return dns, ips


def san_string() -> str:
    dns, ips = names()
    return ",".join([f"DNS:{d}" for d in dns] + [f"IP:{i}" for i in ips])


def der() -> bytes:
    """The certificate's bytes, out of the PEM, without a parser."""
    text = cert_file().read_text(encoding="utf-8")
    body = re.search(r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
                     text, re.S)
    if not body:
        raise ValueError(f"{cert_file()} does not hold a certificate")
    return base64.b64decode(re.sub(r"\s+", "", body.group(1)))


def fingerprint() -> str:
    """SHA-256, grouped in pairs, which is how every browser shows it.

    This is the whole of the security of "accept the warning": the fingerprint
    on the tablet's screen and the one here are the same, or somebody else is
    answering.
    """
    raw = hashlib.sha256(der()).hexdigest().upper()
    return ":".join(raw[i:i + 2] for i in range(0, len(raw), 2))


def _openssl(days: int) -> bool:
    """Make it with the openssl on this machine, which is nearly every machine."""
    if not shutil.which("openssl"):
        return False
    tls_dir().mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key_file()), "-out", str(cert_file()),
         "-days", str(days), "-subj", "/CN=paperpen",
         "-addext", f"subjectAltName={san_string()}",
         "-addext", "basicConstraints=critical,CA:FALSE",
         "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
         "-addext", "extendedKeyUsage=serverAuth"],
        capture_output=True, text=True, timeout=300)
    return done.returncode == 0 and cert_file().is_file()


def _cryptography(days: int) -> bool:
    """The same thing without openssl, for a machine that has not got it."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        return False
    import ipaddress
    from datetime import timedelta

    dns, ips = names()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "paperpen")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(who).issuer_name(who)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(
            [x509.DNSName(d) for d in dns]
            + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]), False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_encipherment=True, content_commitment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                       False)
        .sign(key, hashes.SHA256()))

    tls_dir().mkdir(parents=True, exist_ok=True)
    key_file().write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert_file().write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return True


def make(days: int = DAYS) -> dict:
    """A fresh certificate and key for this machine, replacing any there."""
    if not (_openssl(days) or _cryptography(days)):
        raise RuntimeError(
            "no openssl on this machine and the `cryptography` package is not "
            "installed, so there is nothing here to make a certificate with. "
            "Install either, or serve without --tls and know what that means.")
    key_file().chmod(0o600)
    cert_file().chmod(0o644)    # the certificate is public; only the key is not
    dns, ips = names()
    return {"cert": str(cert_file()), "key": str(key_file()),
            "dns": dns, "ip": ips, "fingerprint": fingerprint(),
            "until": not_after()}


def not_after() -> str:
    """When it stops being accepted, read out of the certificate itself."""
    if not shutil.which("openssl"):
        return ""
    done = subprocess.run(["openssl", "x509", "-in", str(cert_file()),
                           "-noout", "-enddate"],
                          capture_output=True, text=True, timeout=60)
    got = done.stdout.strip()
    return got.split("=", 1)[1] if "=" in got else got


def covers(address: str) -> bool:
    """Whether the certificate names the address the tablet will be typing.

    A laptop gets a new address from DHCP and the certificate quietly stops
    matching; the browser then refuses it for a reason that reads like a
    mistake. Worth saying before the reader is handed over rather than after.
    """
    if not exists() or not address:
        return True
    if not shutil.which("openssl"):
        return True
    done = subprocess.run(["openssl", "x509", "-in", str(cert_file()),
                           "-noout", "-text"], capture_output=True, text=True,
                          timeout=60)
    return f"IP Address:{address}" in done.stdout or f"DNS:{address}" in done.stdout
