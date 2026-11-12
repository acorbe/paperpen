"""Every open note, from every paper, in one list.

The shelf says which papers want attention. The queue is the other half: what
is actually outstanding, across all of them, as rows you can act on one at a
time. It exists because the work is not "read a paper", it is "there are nine
notes still open and two of them have been open since the draft before last".

A note from your hand and a note an agent wrote (Claude's set, or a proposal of
claude's or codex's) are rows of the same shape, told apart by a column, because
they are closed the same way.
"""

from __future__ import annotations

from datetime import date, datetime

from . import bind, rounds

YOU, CLAUDE = "you", "claude"
AGENTS = rounds.AGENTS     # whose notes are told apart from yours
TAGS = ("AUTO", "SCIENCE", "LANGUAGE", "QUESTION", "TODO")


def _age(stamp: str) -> int:
    """Days since the note was made. Unknown reads as today, not as very old."""
    try:
        return (date.today() - datetime.fromisoformat(stamp).date()).days
    except (TypeError, ValueError):
        return 0


def _ink(paper, note: dict, where: str) -> str:
    """The picture of a handwritten note, if there is one on this machine.

    There is no OCR anywhere in this: a handwritten note is read by whoever
    picks it up, and whoever picks it up may be a pass with no browser. So the
    row says where the image is rather than leaving it to be worked out from
    the round's date and the note's id.
    """
    if not (note.get("hand") or note.get("ink")):
        return ""
    name = f"{note.get('id', '')}.png"
    for maybe in (rounds.round_dir(paper, where) / "ink" / name,
                  paper.review / where / "ink" / name):
        try:
            if maybe.is_file():
                return str(maybe)
        except OSError:
            pass
    return ""


def _row(paper, note: dict, where: str, who: str = YOU) -> dict:
    source = note.get("source") or {}
    return {
        "ink": _ink(paper, note, where),
        "paper": paper.pid,
        "paper_name": paper.name,
        "id": note.get("id", ""),
        "page": note.get("page", 0),
        "tag": (note.get("tag") or "AUTO").upper(),
        "who": who,
        "text": rounds.say(note),
        "anchor": (note.get("anchor") or "").strip(),
        "kind": note.get("kind") or "sentence",
        "source": f"{source['file']}:{source['line']}" if source.get("file") else "",
        "where": where,
        "age": _age(note.get("at", "")),
        "handwritten": bool(note.get("hand") or note.get("ink")),
    }


def rows(tag: str = "", paper: str = "", who: str = "", unclassified: bool = False) -> list[dict]:
    """The open notes, oldest first, which is the order they should be cleared in."""
    out: list[dict] = []
    for p in bind.load_papers():
        if paper and p.pid != paper:
            continue
        for note in rounds.open_round(p):
            out.append(_row(p, note, "this reading"))
        for note in rounds.delivered_notes(p):
            if note.get("status", "open") == "open":
                by = note.get("by", "")
                out.append(_row(p, note, note.get("session", "sent"),
                                who=by if by in AGENTS else YOU))
        try:
            for note in bind.paper.claude_notes(p):
                out.append(_row(p, note, "Claude's set", who=CLAUDE))
        except (bind.Refused, OSError, ValueError):
            pass  # a note set that will not load must not empty the queue

    if tag:
        out = [r for r in out if r["tag"] == tag.upper()]
    if who:
        out = [r for r in out if r["who"] == who]
    if unclassified:
        out = [r for r in out if r["tag"] == "AUTO"]
    out.sort(key=lambda r: (-r["age"], r["paper"], r["page"]))
    return out


def tally(all_rows: list[dict]) -> dict:
    """What the filters are worth pressing: counts, so an empty one is visible
    as empty before it is pressed."""
    counts = {t: 0 for t in TAGS}
    for r in all_rows:
        counts[r["tag"]] = counts.get(r["tag"], 0) + 1
    return {
        "total": len(all_rows),
        "tags": counts,
        "papers": len({r["paper"] for r in all_rows}),
        "claude": sum(1 for r in all_rows if r["who"] == CLAUDE),
        "agents": {a: n for a in AGENTS
                   if (n := sum(1 for r in all_rows if r["who"] == a))},
        "handwritten": sum(1 for r in all_rows if r["handwritten"]),
    }


def _in_both(paper, note_id: str, through_upstream, **fields) -> dict:
    """Change a delivered note wherever that round is written down.

    A round is kept in up to two places: the paper's repository, when it was
    delivered there, and the local record, always. Upstream knows only the
    first, because every paper the dashboard read had a repository, so it
    refuses for a draft that left as a marked-up PDF, or whose repository is on
    somebody else's machine, and that refusal is not an error here. It is only
    an error when neither copy has the note.

    This is the other half of the fix bind.py makes for `past_sessions`: the
    merged view is what is read, so the merged view is what has to be written.
    """
    answer, in_repo = {}, ""
    try:
        answer = through_upstream()
        in_repo = answer.get("session", "")
    except bind.Refused:
        pass                       # no repository copy; the local one may still have it
    here = rounds.mark(paper, note_id, **fields)
    if not in_repo and not here:
        raise bind.Refused(f"no note {note_id} in any round of {paper.pid}")
    return {**answer, "id": note_id, **fields, "session": in_repo or here,
            "in_repo": bool(in_repo), "recorded": bool(here)}


def classify(pid: str, note_id: str, tag: str) -> dict:
    """Put a class on a note wherever it is.

    A note still in the open round is rewritten in place; one already delivered
    is classified in every record of the round it was delivered in.
    """
    tag = tag.upper()
    if tag not in TAGS:
        raise bind.Refused(f"{tag} is not one of {', '.join(TAGS)}")
    paper = bind.resolve_paper(pid)
    for note in rounds.open_round(paper):
        if note.get("id") == note_id:
            return bind.paper.cmd_note(paper, {**note, "tag": tag})
    return _in_both(paper, note_id,
                    lambda: bind.paper.cmd_classify(paper, note_id, tag), tag=tag)


def resolve(pid: str, note_id: str, status: str, response: str = "") -> dict:
    """Close a delivered note, with what was done about it."""
    paper = bind.resolve_paper(pid)
    if status not in ("open", "done", "rejected"):
        raise bind.Refused(f"{status} is not one of open, done, rejected")
    return _in_both(paper, note_id,
                    lambda: bind.paper.cmd_resolve(paper, note_id, status, response),
                    status=status, response=response)
