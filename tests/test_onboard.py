"""Onboarding: the steps a new machine needs, said in order, and walked once.

The half that only looks is tested for saying the truth and for writing
nothing; the half that asks is tested for asking nothing on a machine that is
already set up, which is what running it a second time has to be.
"""

import pytest

from paperpen import auth, cli, onboard


def keyed(steps):
    return {s.key: s for s in steps}


def test_a_new_machine_is_not_ready_and_says_what_to_run(tmp_path, monkeypatch):
    for name in ("PAPERPEN_HOME", "PAPERPEN_CACHE", "PAPERPEN_DATA"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    steps = keyed(onboard.status())

    assert not steps["password"].done and steps["password"].fix == "paperpen lan"
    assert not steps["places"].done
    assert not steps["papers"].done
    assert not onboard.ready(list(steps.values()))
    assert not any(tmp_path.iterdir()), "looking writes nothing"


def test_the_second_factor_and_the_certificate_are_not_insisted_on(board):
    auth.set_password("a-long-enough-one")
    steps = keyed(onboard.status())
    assert not steps["totp"].done and not steps["totp"].needed
    assert steps["papers"].done and steps["papers"].said == "1 paper"
    if steps["tools"].done:
        assert onboard.ready(list(steps.values()))


def test_check_exits_one_until_the_password_is_set(board, capsys):
    if not keyed(onboard.status())["tools"].done:
        pytest.skip("the build tools are not on this machine")
    assert cli.main(["onboard", "--check"]) == 1
    assert "paperpen lan" in capsys.readouterr().out
    auth.set_password("a-long-enough-one")
    assert cli.main(["onboard", "--check"]) == 0


def test_a_set_up_machine_is_asked_only_about_what_is_optional(board, monkeypatch, capsys):
    auth.set_password("a-long-enough-one")
    asked = []

    def answer(question=""):
        asked.append(question)
        return "n"

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr("getpass.getpass", lambda *_: pytest.fail("asked for a password"))
    cli.main(["onboard"])

    assert not any("path" in q for q in asked), "the shelf has a paper; none is asked for"
    assert all("second factor" in q or "certificate" in q or "make one" in q
               for q in asked), asked
    assert auth.check_password("a-long-enough-one"), "the password was left alone"
