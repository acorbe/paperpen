"""A password, and optionally a second factor, for serving on the LAN.

The reader is meant for a tablet, and a tablet reaches this machine over the
network rather than through loopback. That is the whole reason to serve on the
LAN and it is also the reason to put a lock on it: what is behind this server
is every paper you are reading, every note you have written about somebody
else's draft, and a one-URL download of all of it.

So `--lan` will not start without a password. Not a warning, not a flag to
override: the difference between a private reader and a public one is one
argument on a command line, and a warning printed at start-up is read once and
then scrolled past every day afterwards.

What this is not:

**There is no TLS yet.** The password crosses the network in the clear, and so
does everything you read. On a home or lab network that is a reasonable trade
against having the reader work at all; on conference wifi it is not, and this
says so every time it starts. TLS is the next thing here, and until it is done
`--lan` is for networks you would already trust with a printer.

The second factor is TOTP, the six digits an authenticator app shows, and it
is optional because it is the right answer for a laptop carried to a
conference and overkill for a desktop on a wired lab network. Enrolling checks
a code before it saves, because a second factor you cannot produce is a lock
with no key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from pathlib import Path

from . import config

VERSION = 1

# scrypt's cost, at roughly 16 MB and a few tens of milliseconds per attempt.
# A login here is typed by a person on a tablet, so nothing is waiting on it,
# and the cost is what makes a stolen file worth less than the password.
SCRYPT = {"n": 1 << 14, "r": 8, "p": 1}
MAXMEM = 64 * 1024 * 1024
DKLEN = 32

STEP = 30          # seconds per TOTP code, which is what every app assumes
DIGITS = 6
SKEW = 1           # one step either side, for a tablet whose clock has drifted


def auth_file() -> Path:
    """Beside the registry, because it is configuration for this machine.

    Deliberately *not* in `papers.json`: that file is in every bundle and can
    be downloaded from the shelf, and a password hash has no business
    travelling with the papers.
    """
    return config.home() / "auth.json"


def read() -> dict:
    try:
        got = json.loads(auth_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def write(data: dict) -> None:
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)          # before the rename, so it is never briefly readable
    tmp.replace(path)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode())


# --- the password ----------------------------------------------------------


def derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=DKLEN,
                          maxmem=MAXMEM, **SCRYPT)


def set_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("a password of at least 8 characters, please")
    salt = secrets.token_bytes(16)
    data = read()
    data["paperpen"] = VERSION
    data["password"] = {"algorithm": "scrypt", "salt": b64(salt),
                        "hash": b64(derive(password, salt)), **SCRYPT}
    data.setdefault("session_key", b64(secrets.token_bytes(32)))
    write(data)


def check_password(password: str) -> bool:
    said = read().get("password") or {}
    try:
        salt, want = unb64(said["salt"]), unb64(said["hash"])
    except (KeyError, ValueError, TypeError):
        return False
    if said.get("algorithm") != "scrypt":
        return False
    got = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=len(want),
                         maxmem=MAXMEM, n=said.get("n", SCRYPT["n"]),
                         r=said.get("r", SCRYPT["r"]), p=said.get("p", SCRYPT["p"]))
    return hmac.compare_digest(got, want)


def has_password() -> bool:
    return bool((read().get("password") or {}).get("hash"))


def login_off() -> bool:
    """Whether the network reader was told to let anyone in.

    Off is a choice somebody made (`paperpen lan --no-login`, or onboarding),
    for a network they trust, at home say; it is never what happens by default.
    Nothing set means the login is on."""
    return read().get("login") == "off"


def set_login(on: bool) -> None:
    """Turn the network login on or off. The password and the second factor
    are kept either way, so turning it back on asks for nothing new."""
    data = read()
    if on:
        data.pop("login", None)
    else:
        data["login"] = "off"
    write(data)


def clear() -> None:
    """Forget the password and the second factor, and say nothing was there
    if nothing was."""
    try:
        auth_file().unlink()
    except OSError:
        pass


# --- the second factor ------------------------------------------------------


def new_totp_secret() -> str:
    """Twenty random bytes in base32, which is what authenticator apps read."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, when: float | None = None, step: int = STEP) -> str:
    """The six digits for a moment. RFC 6238, which is HOTP over the clock."""
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded.upper())
    counter = int((time.time() if when is None else when) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFF_FFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def check_totp(code: str, when: float | None = None) -> bool:
    """A code, against the steps either side of now.

    A code already used is refused even while it is still valid. Within its
    thirty seconds it would otherwise be replayable by anyone who watched it
    go past in the clear, which on a network with no TLS is the whole point of
    saying so.
    """
    said = read().get("totp") or {}
    secret = said.get("secret")
    if not secret:
        return False
    code = str(code).strip().replace(" ", "")
    now = time.time() if when is None else when
    for drift in range(-SKEW, SKEW + 1):
        at = now + drift * STEP
        if hmac.compare_digest(totp(secret, at), code):
            counter = int(at // STEP)
            if counter <= int(said.get("last", -1)):
                return False
            data = read()
            data["totp"] = {**said, "last": counter}
            write(data)
            return True
    return False


def enable_totp(secret: str) -> None:
    data = read()
    data["totp"] = {"secret": secret, "last": -1}
    write(data)


def disable_totp() -> None:
    data = read()
    data.pop("totp", None)
    write(data)


def has_totp() -> bool:
    return bool((read().get("totp") or {}).get("secret"))


def totp_uri(secret: str, label: str = "paperpen") -> str:
    """What a QR code would encode, and what an app accepts pasted. The label
    is the entry's name in the app, `issuer:account`, and is quoted: a space
    in it is the end of the link to a scanner."""
    from urllib.parse import quote

    return (f"otpauth://totp/{quote(label, safe=':@')}?secret={secret}"
            f"&issuer=paperpen&digits={DIGITS}&period={STEP}")


# --- the session ------------------------------------------------------------


def session_key() -> bytes:
    """Kept, rather than made fresh, so restarting the server does not sign
    the tablet out in the middle of a reading."""
    data = read()
    if not data.get("session_key"):
        data["session_key"] = b64(secrets.token_bytes(32))
        data.setdefault("paperpen", VERSION)
        write(data)
    return unb64(data["session_key"])
