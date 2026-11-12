"""Where things live when there is no dashboard repository to live in.

Three separate places, because they have three different lifetimes. The
registry is configuration and is worth backing up. The cache is derived from
the papers and can be deleted at any time. The rounds are the record of what
was read and sent, and are the one thing here that cannot be made again.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "paperpen"


def _env(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def home() -> Path:
    """The directory holding the registry.

    A `.paperpen/` beside the papers wins, so a directory of drafts can carry
    its own shelf and be moved or shared whole. Otherwise PAPERPEN_HOME, which
    is how the dashboard points this at its own papers.json. Otherwise the
    usual place.
    """
    local = Path.cwd() / f".{APP}"
    if (local / "papers.json").is_file():
        return local
    return _env("PAPERPEN_HOME") or (_env("XDG_CONFIG_HOME") or Path.home() / ".config") / APP


def registry_file() -> Path:
    return home() / "papers.json"


def cache_root() -> Path:
    """Built PDFs and rendered pages. Deletable; `build` makes them again."""
    return _env("PAPERPEN_CACHE") or (_env("XDG_CACHE_HOME") or Path.home() / ".cache") / APP


def data_root() -> Path:
    """The rounds: what was read, what was said, and where it went."""
    return _env("PAPERPEN_DATA") or (_env("XDG_DATA_HOME") or Path.home() / ".local/share") / APP


def paper_data(pid: str) -> Path:
    return data_root() / pid
