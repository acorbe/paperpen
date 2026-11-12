"""The lock on the LAN reader, and the second factor behind it.

What is behind this server is every paper being read, every note written about
somebody else's draft, and `/state.tar.gz`, which is all of it in one file. So
`--lan` does not start without a password, and there is no flag that makes an
unlocked one.
"""

import base64
import time

import pytest

from paperpen import auth
from paperpen.web import create_app

GOOD = "a-long-enough-one"


@pytest.fixture
def locked(board):
    auth.set_password(GOOD)
    return board


def test_the_password_is_salted_hashed_and_never_kept(board):
    auth.set_password(GOOD)
    raw = auth.auth_file().read_text(encoding="utf-8")
    assert GOOD not in raw
    assert auth.read()["password"]["algorithm"] == "scrypt"

    assert auth.check_password(GOOD)
    assert not auth.check_password(GOOD + "!")
    assert not auth.check_password("")

    # two machines, one password, two different files
    first = auth.read()["password"]["hash"]
    auth.set_password(GOOD)
    assert auth.read()["password"]["hash"] != first, "the salt is fresh each time"


def test_the_file_is_readable_only_by_its_owner(board):
    auth.set_password(GOOD)
    assert auth.auth_file().stat().st_mode & 0o077 == 0, "no group, no other"


def test_a_short_password_is_refused(board):
    with pytest.raises(ValueError, match="at least 8"):
        auth.set_password("short")


def test_totp_matches_the_rfc_6238_vectors(board):
    """So that a real authenticator app and this agree, which is the only
    thing that matters about an implementation of somebody else's spec."""
    secret = base64.b32encode(b"12345678901234567890").decode()
    for when, want in ((59, "287082"), (1111111109, "081804"),
                       (1111111111, "050471"), (1234567890, "005924"),
                       (2000000000, "279037"), (20000000000, "353130")):
        assert auth.totp(secret, when=when) == want


def test_a_code_is_accepted_once_and_not_again(locked):
    """Within its thirty seconds it is otherwise replayable by anyone who
    watched it go past, which on a network with no TLS is the point."""
    secret = auth.new_totp_secret()
    auth.enable_totp(secret)
    now = time.time()
    code = auth.totp(secret, now)

    assert auth.check_totp(code, when=now)
    assert not auth.check_totp(code, when=now), "the same code twice"


def test_a_code_from_a_drifting_clock_is_still_accepted(locked):
    secret = auth.new_totp_secret()
    auth.enable_totp(secret)
    now = time.time()
    assert auth.check_totp(auth.totp(secret, now - auth.STEP), when=now)
    assert not auth.check_totp(auth.totp(secret, now - 5 * auth.STEP), when=now)


def test_loopback_is_not_gated(locked):
    """A password prompt on 127.0.0.1 protects nothing the filesystem does not,
    and a lock that asks for no reason is one people route around."""
    client = create_app(lan=False).test_client()
    assert client.get("/").status_code == 200
    assert client.get("/state.tar.gz").status_code == 200


def test_off_loopback_nothing_is_reachable_until_you_are_in(locked):
    client = create_app(lan=True).test_client()

    for path in ("/", "/queue", "/paper/dyads-in-a-corridor"):
        assert client.get(path).status_code == 302, path
    # the whole history in one file is the thing to keep behind the lock
    assert client.get("/state.tar.gz").status_code == 302
    # what the reader fetches gets a 401 rather than a login page as JSON
    assert client.get("/paper/dyads-in-a-corridor/meta").status_code == 401
    assert client.get("/login").status_code == 200


def test_the_password_opens_it_and_a_wrong_one_does_not(locked):
    client = create_app(lan=True).test_client()

    no = client.post("/login", data={"password": "not it"})
    assert no.status_code == 401 and "not the password" in no.get_data(as_text=True)
    assert client.get("/").status_code == 302, "still out"

    yes = client.post("/login", data={"password": GOOD})
    assert yes.status_code == 302
    assert client.get("/").status_code == 200
    assert client.get("/state.tar.gz").status_code == 200

    client.get("/logout")
    assert client.get("/").status_code == 302


def test_with_a_second_factor_the_password_alone_is_not_enough(locked):
    secret = auth.new_totp_secret()
    auth.enable_totp(secret)
    client = create_app(lan=True).test_client()

    assert client.post("/login", data={"password": GOOD}).status_code == 401
    assert client.get("/").status_code == 302

    page = client.get("/login").get_data(as_text=True)
    assert "authenticator" in page

    ok = client.post("/login", data={"password": GOOD, "code": auth.totp(secret)})
    assert ok.status_code == 302
    assert client.get("/").status_code == 200


def test_a_wrong_code_is_refused_in_the_same_words_as_a_wrong_password(locked):
    """Which of the two was wrong is not something a guesser should learn."""
    auth.enable_totp(auth.new_totp_secret())
    client = create_app(lan=True).test_client()

    bad_pw = client.post("/login", data={"password": "no", "code": "000000"})
    bad_code = client.post("/login", data={"password": GOOD, "code": "000000"})
    assert bad_pw.get_data(as_text=True).count("not the password") == 1
    assert "not the password" in bad_code.get_data(as_text=True)


def test_the_secret_never_travels_in_a_bundle(locked):
    """papers.json is in every bundle and downloadable from the shelf. The
    password hash lives beside it and must not go with it."""
    import tarfile
    from io import BytesIO

    from paperpen import archive

    auth.enable_totp(auth.new_totp_secret())
    with tarfile.open(fileobj=BytesIO(archive.bundle())) as tar:
        names = tar.getnames()
    assert "paperpen/papers.json" in names
    assert not any("auth" in n for n in names), names


def test_enrolling_shows_a_code_to_scan_and_keeps_no_picture(board, monkeypatch, capsys):
    """Pairing an app is scanning a QR code, not typing thirty-two characters.
    The code is drawn in the terminal and written as a picture only you can
    read, which is gone when enrolment is over: it is the secret."""
    import stat

    from paperpen import cli, config, qr

    secret = base64.b32encode(b"12345678901234567890").decode()
    monkeypatch.setattr(auth, "new_totp_secret", lambda: secret)
    picture = config.home() / "second-factor.svg"
    seen = {}
    answers = iter(["y"])

    def answer(question=""):
        if "six digits it shows" in question:
            seen["picture"] = picture.is_file() and stat.S_IMODE(picture.stat().st_mode)
            seen["svg"] = picture.read_text()[:4] if picture.is_file() else ""
            return auth.totp(secret)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    auth.set_password(GOOD)
    assert cli.offer_second_factor() is True
    out = capsys.readouterr().out

    if qr.available():
        assert "█" in out or "▀" in out, "no QR code drawn"
        assert seen["picture"] == 0o600 and seen["svg"] == "<svg"
    assert secret in out, "the key, for typing in by hand"
    assert not picture.exists(), "the picture of the secret was left behind"
    assert auth.has_totp()


def test_the_link_an_app_scans_is_a_valid_one():
    uri = auth.totp_uri("ABC", label="paperpen:my laptop")
    assert uri.startswith("otpauth://totp/paperpen:my%20laptop?secret=ABC")
    assert " " not in uri
