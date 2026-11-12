"""Saying where the browser view is, and only when there is one.

`paperpen shelf` is the same shelf as the home page. It should say where the
other one is, and a URL printed for a server that is not running is worse than
saying nothing: it is followed once, fails, and is not trusted again.
"""

import socket

import pytest

from paperpen import cli, serving


@pytest.fixture(autouse=True)
def default_port_is_free(monkeypatch):
    """Point the fallback probe at a port nothing is on.

    `where_to_look` probes the default port so that a server started by some
    other checkout is reported rather than ignored. That is right in use and
    wrong in a test: the machine running the suite may well have a paperpen
    serving on 8770, and these tests are about what the record says, not about
    what else is on this machine.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    monkeypatch.setattr(serving, "DEFAULT_PORT", free)


def a_listening_port() -> tuple[socket.socket, int]:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


def test_nothing_is_claimed_when_nothing_is_serving(board):
    assert serving.running() is None
    said = serving.where_to_look()
    assert said.startswith("not serving")
    assert "paperpen serve" in said and str(serving.DEFAULT_PORT) in said


def test_a_record_left_by_a_server_that_died_says_not_serving(board):
    """The process does not always get to run its own cleanup, so the reader
    probes the port rather than trusting the file."""
    dead, port = a_listening_port()
    dead.close()                                   # nothing is there now
    serving.remember("127.0.0.1", port)

    assert serving.record_file().is_file()         # the record is still there
    assert serving.running() is None               # and it is not believed
    assert serving.where_to_look().startswith("not serving")


def test_the_port_that_was_recorded_is_the_port_that_is_offered(board):
    """`serve --port` is not the default, and the shelf has to say the real
    one rather than the one in the documentation."""
    live, port = a_listening_port()
    try:
        serving.remember("127.0.0.1", port)
        up = serving.running()
        assert up is not None and up["port"] == port
        assert serving.where_to_look() == f"in a browser: http://127.0.0.1:{port}/"
    finally:
        live.close()


def test_a_server_on_every_interface_is_still_opened_at_the_loopback_one(board):
    """`--host 0.0.0.0` is where it listens, not an address to type."""
    assert serving.url("0.0.0.0", 8770) == "http://127.0.0.1:8770/"
    assert serving.url("192.0.2.7", 9000) == "http://192.0.2.7:9000/"


def test_the_terminal_shelf_says_where_the_browser_one_is(board, capsys):
    assert cli.main(["shelf"]) == 0
    out = capsys.readouterr().out
    assert "Pedestrian dyads" in out                       # the shelf itself
    assert "paperpen serve" in out                         # and how to open it

    live, port = a_listening_port()
    try:
        serving.remember("127.0.0.1", port)
        assert cli.main(["shelf"]) == 0
        assert f"http://127.0.0.1:{port}/" in capsys.readouterr().out
    finally:
        live.close()


def test_an_empty_shelf_still_says_both_things(board, capsys):
    from paperpen import registry

    registry.write({"papers": []})
    assert cli.main(["shelf"]) == 0
    out = capsys.readouterr().out
    assert "nothing on the shelf" in out
    assert "paperpen add" in out and "paperpen serve" in out


def test_the_record_is_not_worth_failing_to_start_over(board, monkeypatch):
    """Saying where the server is is a courtesy; it must not stop it serving."""
    def no(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(serving.Path, "write_text", no)
    serving.remember("127.0.0.1", 8770)     # does not raise
    serving.forget()                        # nor does this, with nothing there
