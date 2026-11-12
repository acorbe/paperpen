"""Every request, in every mode, comes under this server's own name, and a
write comes from one of its own pages; and the login is on unless turned off."""

import pytest

from paperpen import auth, cli
from paperpen.web import create_app
from paperpen.web.login import safe_next

GOOD = "correct horse battery staple"


def test_a_write_from_another_site_is_refused(board):
    client = create_app(lan=False).test_client()
    got = client.post("/papers/add", json={"path": "/tmp/x"},
                      headers={"Origin": "https://evil.example"})
    assert got.status_code == 403
    got = client.post("/papers/add", data="{}", content_type="text/plain",
                      headers={"Referer": "https://evil.example/page"})
    assert got.status_code == 403
    got = client.post("/papers/add", data="{}", headers={"Origin": "null"})
    assert got.status_code == 403


def test_a_write_from_its_own_page_or_from_no_page_goes_through(board):
    client = create_app(lan=False).test_client()
    own = client.post("/papers/add", json={}, headers={"Origin": "http://localhost"})
    bare = client.post("/papers/add", json={})
    assert own.status_code != 403 and bare.status_code != 403


def test_loopback_answers_only_to_its_own_name(board):
    """A page that points its own name at 127.0.0.1 (DNS rebinding) is refused,
    reads included: that is how it would take /state.tar.gz."""
    client = create_app(lan=False).test_client()
    for name in ("127.0.0.1:8770", "localhost:8770", "[::1]:8770"):
        assert client.get("/", headers={"Host": name}).status_code == 200, name
    assert client.get("/state.tar.gz", headers={"Host": "evil.example:8770"}).status_code == 421


def test_after_signing_in_it_goes_only_somewhere_on_this_server():
    assert safe_next("/paper/x?y=1") == "/paper/x?y=1"
    for bad in (None, "", "https://evil.example", "//evil.example", "/\\evil.example",
                "javascript:alert(1)"):
        assert safe_next(bad) == "/", bad


def test_the_login_is_on_unless_turned_off(board):
    auth.set_password(GOOD)
    assert not auth.login_off()
    assert create_app(lan=True).test_client().get("/").status_code == 302
    auth.set_login(False)
    assert auth.login_off()
    assert create_app(lan=True).test_client().get("/").status_code == 200
    auth.set_login(True)
    assert create_app(lan=True).test_client().get("/").status_code == 302
    assert auth.has_password(), "turning it off and on again keeps the password"


def _answers(monkeypatch, *said):
    it = iter(said)
    monkeypatch.setattr("builtins.input", lambda question="": next(it))
    monkeypatch.setattr(cli, "ask_password", lambda: GOOD)


def test_the_menu_recommends_a_login_and_enter_takes_it(board, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "offer_second_factor",
                        lambda light=False, ask=True: seen.setdefault("ask", ask) or True)
    _answers(monkeypatch, "")
    assert cli.choose_login() is True
    assert auth.has_password() and not auth.login_off()
    assert seen["ask"] is False, "option 1 enrols the second factor without asking again"


def test_password_only(board, monkeypatch):
    _answers(monkeypatch, "2")
    assert cli.choose_login() is True
    assert auth.has_password() and not auth.has_totp()


def test_no_login_has_to_be_said_in_so_many_words(board, monkeypatch, capsys):
    _answers(monkeypatch, "3", "y", "3", "no login")
    assert cli.choose_login() is False
    assert auth.login_off() and not auth.has_password()
    assert "only on a network you trust" in capsys.readouterr().out.lower()


def test_lan_no_login_and_back(board, monkeypatch, capsys):
    assert cli.cmd_lan(["--no-login"]) == 0
    assert auth.login_off()
    cli.cmd_lan(["--clear"])
    assert not auth.login_off(), "cleared means back to the default, a login"


def test_debug_is_refused_off_loopback(board, capsys):
    auth.set_login(False)
    assert cli.cmd_serve(["--lan", "--debug"]) == 1
    assert "loopback only" in capsys.readouterr().out
