"""A reading, and what became of it.

A round opens at the first note, is *sent* when it is finished and delivered,
and is *answered* once every note in it has been resolved or rejected. That is
the state a person acts on; a count of notes is not.

Every round is recorded here, under the app's own data directory, whatever the
delivery was. That is the whole reason this module exists. The dashboard could
read a paper's history out of the paper's repository because every paper it
read had one and it was on the same machine. Neither holds in general: a draft
handed over as a PDF has no repository to write into, and a repository can be
on a laptop that is not this one. Without a record here the shelf would simply
forget those.

Where there is a repository, its copy stays authoritative and this one is a
mirror. A pass working in the paper's own checkout runs `paperpen resolve`
there and closes notes in `review/<date>/notes.json`; if this side kept its own
opinion of their status the two would disagree within a day, and the one in the
repository is the one the person editing the paper can see.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import bind, config

# Who writes notes and fixes of their own, besides you: the agent's runners.
# The name is what their notes are signed with ("by") and what their review
# rounds are called after, <date>-claude or <date>-codex. The one list: the
# proposals, the queue, the agent and the pages all take it from here.
AGENTS = ("claude", "codex")

OPEN, WAITING, IDLE = "reading", "waiting", "idle"


def rounds_dir(paper) -> Path:
    return config.paper_data(paper.pid) / "rounds"


def round_dir(paper, session: str) -> Path:
    return rounds_dir(paper) / session


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def say(note: dict) -> str:
    """What a note says, in one string.

    A note is words, or ink, or both. Once the strokes are transcribed the
    transcription stands in for the words; until then there is nothing to show
    and the note says so, rather than appearing empty and being skipped over.
    """
    written = (note.get("note") or "").strip()
    if written:
        return written
    if note.get("hand_text"):
        return note["hand_text"].strip()
    if note.get("hand") or note.get("ink"):
        return "(handwritten, not transcribed)"
    return ""


def open_round(paper) -> list[dict]:
    """The notes of the reading in progress, which upstream keeps in the cache."""
    return bind.paper.read_session(paper)


def write_record(paper, notes: list[dict], session: str, info: dict) -> Path:
    """The local copy of a delivered round: the notes, the handwriting, and
    what it was read from. Written with upstream's own `notes_md` and
    `ink_crop`, so this copy and the one in a repository say the same thing.

    A second round on one day joins the first, the way upstream's export does,
    rather than replacing it."""
    out = round_dir(paper, session)
    out.mkdir(parents=True, exist_ok=True)
    was = read_json(out / "notes.json", {}).get("notes", [])
    fresh = {n["id"] for n in notes}
    if was:
        notes = [n for n in was if n["id"] not in fresh] + notes
        notes.sort(key=lambda n: (n.get("page", 0), n.get("rect", [0, 0])[1]))
    for note in notes:
        # Only this delivery's notes are cropped: an earlier one was cropped
        # from the build it was written on, and the current build may have
        # moved its text or lost its page altogether.
        if note["id"] not in fresh and (out / "ink" / f"{note['id']}.png").exists():
            continue
        if note.get("ink") or note.get("hand"):
            bind.paper.ink_crop(paper, note, out / "ink" / f"{note['id']}.png")
    (out / "notes.json").write_text(
        json.dumps({"paper": paper.name, "main": paper.main, "session": session,
                    "build": info, "notes": notes}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out / "NOTES.md").write_text(
        bind.paper.notes_md(paper, notes, info, session), encoding="utf-8")
    return out


def write_sent(paper, session: str, **what) -> None:
    """Where the round went, so the shelf can say so without guessing."""
    (round_dir(paper, session) / "sent.json").write_text(
        json.dumps({"session": session,
                    "at": datetime.now().isoformat(timespec="seconds"), **what},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mark(paper, note_id: str, **fields) -> str:
    """Put fields on a delivered note in the local record, and say which round.

    The record here is the copy that always exists. A round delivered into a
    paper's repository has a second copy there, which upstream maintains; a
    round that left as a marked-up PDF, or whose repository is on another
    machine, has only this one. Both are written with upstream's own
    `notes_md`, so the two never say different things about the same note.
    """
    for notes_json in sorted(rounds_dir(paper).glob("*/notes.json"), reverse=True):
        data = read_json(notes_json, {})
        for note in data.get("notes", []):
            if note.get("id") != note_id:
                continue
            note.update(fields)
            session = notes_json.parent.name
            notes_json.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
            (notes_json.parent / "NOTES.md").write_text(
                bind.paper.notes_md(paper, data["notes"], data.get("build", {}), session),
                encoding="utf-8")
            return session
    return ""


def delivered(paper) -> dict[str, list[dict]]:
    """Every delivered round, by date, the repository's copy winning.

    Local first, then the repository over the top of it: a note closed in the
    paper's own checkout has to show as closed here, and the mirror is never
    allowed to argue with it.
    """
    by_session: dict[str, list[dict]] = {}
    for notes_json in sorted(rounds_dir(paper).glob("*/notes.json")):
        by_session[notes_json.parent.name] = read_json(notes_json, {}).get("notes", [])
    if paper.repo.is_dir():
        from_repo: dict[str, list[dict]] = {}
        for note in bind.repo_sessions(paper):
            from_repo.setdefault(note.get("session", "?"), []).append(note)
        by_session.update(from_repo)
    return by_session


def delivered_notes(paper) -> list[dict]:
    out = []
    for session, notes in delivered(paper).items():
        for note in notes:
            out.append({**note, "session": session})
    return out


def sent(paper) -> list[dict]:
    """One entry per delivered round, newest first, with how it stands."""
    out = []
    for session, notes in delivered(paper).items():
        counts = {"open": 0, "done": 0, "rejected": 0}
        for note in notes:
            status = note.get("status", "open")
            counts[status if status in counts else "open"] += 1
        went = read_json(round_dir(paper, session) / "sent.json", {})
        out.append({"date": session, "notes": len(notes), **counts,
                    "answered": counts["open"] == 0,
                    "delivery": went.get("delivery", ""),
                    "where": went.get("where", "")})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def state(paper) -> str:
    if open_round(paper):
        return OPEN
    if any(not r["answered"] for r in sent(paper)):
        return WAITING
    return IDLE
