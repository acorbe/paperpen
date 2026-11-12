"""Where the browser view is, for the commands that are not it.

`paperpen shelf` is the same shelf as the home page, in a terminal, and it used
to end without saying so. The terminal is where you are when you have just
built something; the browser is where you read. The one should say where the
other is, and say whether it is actually up rather than printing a URL that
may go nowhere.

What is known is recorded by `serve` while it runs, under the cache, because it
is a fact about this moment and not about the papers: it is true until the
process exits and is worth nothing afterwards. The port is then probed before
anything is claimed, so a record left behind by a server that was killed says
"not serving" like any other stale file.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from . import config

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8770


def record_file() -> Path:
    return config.cache_root() / "serving.json"


def url(host: str, port: int, scheme: str = "http") -> str:
    """The address to type. A server bound to every interface is still reached
    from here at the loopback one, and `0.0.0.0` is not a place to browse."""
    where = DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host
    return f"{scheme}://{where}:{port}/"


def remember(host: str, port: int, scheme: str = "http") -> None:
    try:
        record_file().parent.mkdir(parents=True, exist_ok=True)
        record_file().write_text(
            json.dumps({"host": host, "port": port, "pid": os.getpid(),
                        "scheme": scheme}),
            encoding="utf-8")
    except OSError:
        pass  # saying where the server is is not worth failing to start it


def forget() -> None:
    try:
        record_file().unlink()
    except OSError:
        pass


def answers(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection(
                (DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host, port),
                timeout=timeout):
            return True
    except OSError:
        return False


def running() -> dict | None:
    """The server this machine has, if the port it recorded still answers."""
    try:
        said = json.loads(record_file().read_text(encoding="utf-8"))
        host, port = str(said["host"]), int(said["port"])
        scheme = str(said.get("scheme", "http"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not answers(host, port):
        return None
    return {"host": host, "port": port, "scheme": scheme,
            "url": url(host, port, scheme)}


def where_to_look() -> str:
    """One line for a terminal command to end on.

    Three cases and they are different advice. A server of ours is up, so open
    it. Nothing is up, so here is what to type. Or the port is taken by
    something that left no record, which is worth saying plainly rather than
    printing a URL and letting it be somebody else's page.
    """
    up = running()
    if up:
        return f"in a browser: {up['url']}"
    if answers(DEFAULT_HOST, DEFAULT_PORT):
        return (f"in a browser: {url(DEFAULT_HOST, DEFAULT_PORT)} "
                f"(something is already on {DEFAULT_PORT}; this paperpen did not "
                f"start it)")
    return (f"not serving. `paperpen serve` puts this shelf, and the reader, at "
            f"{url(DEFAULT_HOST, DEFAULT_PORT)}")
