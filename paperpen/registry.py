"""The shelf's registry: the dashboard's papers.json, with three fields added.

Each of the three earns its place by changing what the app does, which is the
test for putting anything in here at all. `kind` picks the delivery default,
`brief` is what Claude is told and what the notes are headed with, `delivery`
is where a finished round goes. A file written by the dashboard has none of
them and behaves exactly as it did.
"""

from __future__ import annotations

import json

from . import config

KINDS = ("mine", "coauthor", "student", "referee")
DELIVERIES = ("repo", "pdf", "folder")

# Where the paper's record is kept, which is a different question from where a
# finished round is delivered. `repo` writes `review/` into the paper's own
# repository, so the paper carries its own history and any machine with a
# clone can rebuild the shelf from it. `local` keeps it only under the app's
# data directory. A round delivered as a commit is already writing there, so
# it records there; a draft you hand back as a PDF does not touch the other
# person's tree unless you say so.
RECORDS = ("repo", "local")
RECORD_FOR = {"repo": "repo", "pdf": "local", "folder": "local"}

# What you hand somebody depends on who they are. Your own manuscript commits
# its notes into its own repository; a student gets a file, because a commit in
# a repository they do not have is not a thing you can send.
DELIVERY_FOR = {"mine": "repo", "coauthor": "repo", "student": "pdf", "referee": "pdf"}


def read() -> dict:
    path = config.registry_file()
    if not path.is_file():
        return {"papers": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    raw.setdefault("papers", [])
    return raw


def write(raw: dict) -> None:
    path = config.registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def entry(pid: str) -> dict:
    for e in read()["papers"]:
        if e.get("id") == pid:
            return e
    return {}


def extras(pid: str) -> dict:
    """The three fields, defaulted, for a paper that may predate them."""
    e = entry(pid)
    kind = str(e.get("kind", "") or "mine").lower()
    if kind not in KINDS:
        kind = "mine"
    delivery = str(e.get("delivery", "") or DELIVERY_FOR[kind]).lower()
    if delivery not in DELIVERIES:
        delivery = DELIVERY_FOR[kind]
    record = str(e.get("record", "") or RECORD_FOR[delivery]).lower()
    if record not in RECORDS:
        record = RECORD_FOR[delivery]
    return {
        "kind": kind,
        "delivery": delivery,
        "record": record,
        "brief": str(e.get("brief", "") or "").strip(),
        "archived": bool(e.get("archived", False)),
    }


def remove(pid: str) -> dict:
    """Take a paper off the shelf. Only its entry: its repository, its rounds
    and its cache stay where they are, so putting it back with `add` or
    `adopt` finds its history again."""
    raw = read()
    kept = [e for e in raw["papers"] if e.get("id") != pid]
    if len(kept) == len(raw["papers"]):
        raise ValueError(f"no paper {pid} in {config.registry_file()}")
    gone = next(e for e in raw["papers"] if e.get("id") == pid)
    raw["papers"] = kept
    write(raw)
    return gone


def update(pid: str, **fields) -> dict:
    raw = read()
    for e in raw["papers"]:
        if e.get("id") == pid:
            for key, value in fields.items():
                if value is None or value == "":
                    e.pop(key, None)
                else:
                    e[key] = value
            write(raw)
            return e
    raise ValueError(f"no paper {pid} in {config.registry_file()}")
