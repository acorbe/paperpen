"""Claude reading the paper first: notes it writes itself, each with a fix, for
you to approve or reject.

Everywhere else in paperpen the flow starts with you. You mark the paper up,
the round is delivered, and whoever answers it proposes fixes for your notes.
This is the same thing the other way round: Claude reads the paper on its own
initiative and writes the notes, each one already carrying the fix it would
make, and all that is left to you is the decision.

So a proposal is an ordinary delivered note, and nothing downstream has to
learn a new kind of thing. It sits in a round of its own,

    review/<date>-claude/notes.json      the notes, each with "by": "claude"
    review/<date>-claude/feedback.json   their fixes, in the usual format

so it never mixes with a reading of yours and the agent that answers your
rounds never mistakes it for one. The note is anchored to the sentence the fix
is about, worked out from the fix itself: the line its `old` text starts on,
through SyncTeX to the page, and the sentence there that carries it. Its fix
is a fix like any other, so **Approve** is `apply`, which writes the working
tree and closes the note as done, and **Reject** closes it as rejected, with a
word why if you have one. Nothing is committed: the review's own Commit is the
way an approved fix becomes history, exactly as for an answered round.

A proposal without a fix is allowed, for a question or a remark that has no
one right rewording; it can only be rejected or closed by hand. A run is capped
(25 notes by default), because a long paper read for "clarity" would otherwise
come back with three hundred of them, and nobody decides three hundred.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from . import bind, edit, feedback, queue, rounds

# Who writes notes of their own: the runners of agent.py. A review round is
# named after the one that wrote it, <date>-claude or <date>-codex, and each
# of its notes carries that name in "by".
AGENTS = rounds.AGENTS
BY = AGENTS[0]
MOST = 25
TAGS = ("SCIENCE", "LANGUAGE", "QUESTION", "TODO")


def is_agent(by) -> bool:
    return str(by or "") in AGENTS


def session_of(day: str = "", by: str = BY) -> str:
    """The round a review of that day goes into; a second run joins it."""
    if by not in AGENTS:
        raise bind.Refused(f"a review is written by one of {', '.join(AGENTS)}, not {by!r}")
    return (day or date.today().isoformat()) + "-" + by


def is_review(session: str) -> bool:
    return any(str(session).endswith("-" + a) for a in AGENTS)


def by_of(session: str) -> str:
    """Which agent's round it is; claude for anything that is not one."""
    for a in AGENTS:
        if str(session).endswith("-" + a):
            return a
    return BY


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- where on the page a piece of source came out --------------------------

COMMENT = re.compile(r"(?<!\\)%.*")
MATH = re.compile(r"\$[^$]*\$")
COMMAND = re.compile(r"\\[A-Za-z@]+\*?(\[[^\]]*\])?")


def plain(tex: str) -> str:
    """LaTeX as it will read in the PDF, near enough to search for: commands
    dropped and their arguments kept, maths out, ties as spaces."""
    text = "\n".join(COMMENT.sub("", line) for line in tex.splitlines())
    text = MATH.sub(" ", text)
    text = COMMAND.sub(" ", text)
    text = re.sub(r"[{}~]", " ", text).replace("\\\\", " ").replace("``", '"').replace("''", '"')
    return " ".join(text.split())


def _words(text: str) -> list[str]:
    """Words to compare a source with a page by: ligatures undone, case and
    punctuation gone, so curly quotes and straight ones are the same."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w\s]", " ", text).split()


def _find(paper, text: str, first: int = 0):
    """The sentence on the page that carries the text, and its page.

    Matched against the reader's own sentences rather than searched for in the
    PDF, because those have the line-end hyphens taken out: "arrange-ment"
    broken over two lines is not found by a search, and is in a sentence. The
    longest run of the text's words wins, from eight down to three, since the
    source and the typeset page differ in whatever a macro expands to and a few
    words found is enough. The page SyncTeX names is tried first."""
    want = _words(plain(text))
    if not want or not paper.pdf.is_file():
        return None
    import pymupdf

    with pymupdf.open(paper.pdf) as doc:
        pages = list(range(1, doc.page_count + 1))
    if first in pages:
        pages.remove(first)
        pages.insert(0, first)
    said = {}
    for size in (8, 6, 5, 4, 3, len(want)):
        if size > len(want) or (size < 3 and len(want) >= 3):
            continue
        runs = [" " + " ".join(want[i:i + size]) + " " for i in range(len(want) - size + 1)]
        for page in pages:
            if page not in said:
                said[page] = [(" " + " ".join(_words(x["text"])) + " ", x["rects"])
                              for x in bind.paper.page_sentences(paper, page)]
            for text_of, rects in said[page]:
                if any(run in text_of for run in runs):
                    return page, rects
    return None


def _sentence_at(paper, page: int, rect: list[float]) -> list[list[float]]:
    """The boxes of the sentence the rectangle falls in, so the note is on a
    sentence the way one made with a finger is."""
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    best, gap = [], None
    for s in bind.paper.page_sentences(paper, page):
        for r in s["rects"]:
            if r[0] - 1 <= cx <= r[2] + 1 and r[1] - 1 <= cy <= r[3] + 1:
                return s["rects"]
            d = abs((r[1] + r[3]) / 2 - cy) + max(0.0, r[0] - cx, cx - r[2]) / 4
            if gap is None or d < gap:
                best, gap = s["rects"], d
    return best


def place(paper, rel: str, text: str, anchor: str = "") -> dict:
    """Where a note about this piece of the source goes on the page.

    `anchor`, a phrase copied from the PDF, wins when it is given. Otherwise
    the source text is followed: its line through SyncTeX gives the page, and
    the words themselves, looked for there first, give the sentence; failing
    that, the sentence where SyncTeX put the line. A build without SyncTeX
    goes by the words alone, and a text that cannot be found leaves the note on
    its source line with no place on the page, which is said rather than
    guessed at.
    """
    full = edit.inside(paper, rel)
    source_text = full.read_text(encoding="utf-8", errors="replace") if full.is_file() else ""
    at = source_text.find(text) if text else -1
    line = source_text.count("\n", 0, at) + 1 if at >= 0 else 0
    source = {"file": rel, "line": line} if line else {}

    page, hit = 0, None
    if line:
        try:
            fwd = edit.forward(paper, rel, line)
            page, hit = fwd["page"], fwd["rect"]
        except bind.Refused:
            pass
    found = _find(paper, anchor, page) if anchor else None
    found = found or (_find(paper, text, page) if text else None)
    if found:
        page, rects = found
    elif page and hit:
        rects = _sentence_at(paper, page, hit) or [hit]
    else:
        return {"page": 1, "rect": [0, 0, 0, 0], "rects": [], "kind": "region",
                "anchor": anchor or plain(text)[:300], "source": source,
                "word": "", "context": "", "figure": "", "placed": False}
    out = bind.paper.anchor_for(paper, page, "sentence", bind.paper.bbox(rects), rects)
    if source:
        out["source"] = source       # the line we know, not the one SyncTeX guesses
    out["placed"] = True
    return out


# --- writing a proposal ------------------------------------------------------

def _round_notes(paper, session: str) -> list[dict]:
    return rounds.read_json(paper.review / session / "notes.json", {}).get("notes", [])


def _next_id(paper, session: str) -> str:
    taken = {n.get("id") for n in rounds.delivered_notes(paper)}
    n = 1
    while f"{session}-{n:02d}" in taken:
        n += 1
    return f"{session}-{n:02d}"


def _keep(paper, session: str, note: dict) -> None:
    """Into the paper's repository, where a pass and the reader find it, and
    into the local record, the way a delivered round is kept: both written
    with upstream's own NOTES.md, so the two say the same thing."""
    notes = [n for n in _round_notes(paper, session) if n.get("id") != note["id"]] + [note]
    notes.sort(key=lambda n: (n.get("page", 0), n.get("rect", [0, 0])[1]))
    info = bind.paper.build_info(paper)
    bind.paper.write_review(paper, notes, session, info, fresh={note["id"]})
    rounds.write_record(paper, [note], session, info)
    rounds.write_sent(paper, session, notes=len(notes), delivery=by_of(session),
                      where=str(paper.review / session), committed=False)


def _cap(paper, session: str) -> int:
    """How many more this run may write: the run's own cap, counted from when
    it started. A proposal written by hand, with no run behind it, has none."""
    from . import agent

    said = rounds.read_json(agent.status_file(paper, session), {})
    if said.get("state") != "running" or not said.get("max"):
        return -1
    made = sum(1 for n in _round_notes(paper, session)
               if is_agent(n.get("by")) and n.get("at", "") >= said.get("started", ""))
    return int(said["max"]) - made


def suggest(pid: str, note: str, tag: str, edits: list[dict] | None = None,
            summary: str = "", why: str = "", file: str = "", at: str = "",
            anchor: str = "", session: str = "", by: str = "") -> dict:
    """A note the agent writes itself, anchored to the source it is about, with
    the fix it proposes. Checked before anything is written: a fix that could
    never apply is refused while whoever wrote it can still try again.

    `by` is the agent writing it, claude unless said, and it picks the round:
    codex's notes go in <date>-codex, never among claude's."""
    paper = bind.resolve_paper(pid)
    if paper.is_pdf or not paper.repo.is_dir():
        raise bind.Refused(f"{paper.pid} has no source for a proposal to fix")
    session = session or session_of(by=by or BY)
    if not is_review(session):
        raise bind.Refused(f"a proposal goes in a round of its own, <date>-claude or <date>-codex")
    by = by or by_of(session)
    if by != by_of(session):
        raise bind.Refused(f"{session} is {by_of(session)}'s round, not {by}'s")
    if not note.strip():
        raise bind.Refused("say what is wrong: --note, one or two sentences")
    tag = tag.upper()
    if tag not in TAGS:
        raise bind.Refused(f"--tag is one of {', '.join(TAGS)}")
    clean = []
    for e in edits or []:
        rel, old, new = str(e.get("file", "")), str(e.get("old", "")), str(e.get("new", ""))
        if not old:
            raise bind.Refused("an edit names the exact text it replaces; `old` is empty")
        if old == new:
            raise bind.Refused(f"an edit to {rel} changes nothing")
        edit.inside(paper, rel)
        clean.append({"file": rel, "old": old, "new": new})
    if clean and not summary.strip():
        raise bind.Refused("a fix needs a summary: one line, what it changes")
    if clean:
        problems = feedback._check(paper, clean)
        if problems:
            raise bind.Refused("; ".join(problems))
        file, at = clean[0]["file"], clean[0]["old"]
    elif not (file and at):
        raise bind.Refused("a remark without a fix still says where it is: "
                           "--file and --at, the exact text it is about")
    else:
        full = edit.inside(paper, file)
        if not full.is_file() or at not in full.read_text(encoding="utf-8", errors="replace"):
            raise bind.Refused(f"{file} does not have the text --at names: {feedback._short(at)}")

    for was in _round_notes(paper, session):
        if was.get("status", "open") == "open" and is_agent(was.get("by")) \
                and was.get("about") == {"file": file, "text": at}:
            raise bind.Refused(f"{was['id']} is already about that text; one note per place")
    left = _cap(paper, session)
    if left == 0:
        raise bind.Refused("this run has written as many notes as it may; stop here")

    where = place(paper, file, at, anchor)
    placed = where.pop("placed")
    new = {"id": _next_id(paper, session), "by": by, "tag": tag, "note": note.strip(),
           "at": _now(), "status": "open", "response": "",
           "ink": [], "hand": [], "pad": [], "about": {"file": file, "text": at},
           **where}
    _keep(paper, session, new)
    out = {"paper": paper.pid, "session": session, "note": new, "placed": placed}
    if clean:
        out["fix"] = feedback.propose(paper.pid, new["id"], summary, clean, why=why, by=by)["fix"]
    return out


# --- deciding ---------------------------------------------------------------

def _waiting(paper, note_id: str) -> tuple[dict, list[dict]]:
    note = feedback._note(paper, note_id)
    data = feedback.read(paper, note["session"])
    fixes = [f for f in data["notes"].get(note_id, {}).get("fixes", [])
             if f.get("state") == feedback.PROPOSED]
    return note, fixes


def approve(pid: str, note_id: str, fix_id: str = "", by: str = feedback.YOU) -> dict:
    """Put the note's fix into the working tree and close the note as done.
    A note with two fixes waiting needs to be told which."""
    paper = bind.resolve_paper(pid)
    note, fixes = _waiting(paper, note_id)
    if note.get("status", "open") != "open":
        raise bind.Refused(f"{note_id} is already {note.get('status')}")
    if fix_id:
        chosen = [str(fix_id)]
    elif len(fixes) == 1:
        chosen = [fixes[0]["id"]]
    elif not fixes:
        raise bind.Refused(f"{note_id} has no fix to approve: reject it, or close it by hand")
    else:
        raise bind.Refused(f"{note_id} has {len(fixes)} fixes; say which one")
    return feedback.apply(paper.pid, note_id, chosen, by=by)


def reject(pid: str, note_id: str, why: str = "", by: str = feedback.YOU) -> dict:
    """Close the note as rejected, its fixes with it, and keep the reason in
    its thread, where a later run reads it."""
    paper = bind.resolve_paper(pid)
    note = feedback._note(paper, note_id)
    if note.get("status", "open") != "open":
        raise bind.Refused(f"{note_id} is already {note.get('status')}")
    session = note["session"]
    if not paper.is_pdf and paper.repo.is_dir():
        data = feedback.read(paper, session)
        entry = feedback._entry(data, note_id)
        for fix in entry["fixes"]:
            if fix.get("state") == feedback.PROPOSED:
                fix["state"], fix["rejected"] = "rejected", {"by": by, "at": _now()}
        if why.strip():
            entry["thread"].append({"by": by or feedback.YOU, "at": _now(), "text": why.strip()})
        feedback.write(paper, session, data)
    queue.resolve(paper.pid, note_id, "rejected", f"rejected: {why.strip()}" if why.strip()
                  else "rejected")
    return {"paper": paper.pid, "note": note_id, "rejected": True}


def decide(pid: str, note_ids: list[str], what: str, why: str = "") -> dict:
    """The same decision for several notes, each on its own: one that cannot be
    approved (two fixes, or text that has moved) is reported and the rest go."""
    if what not in ("approve", "reject"):
        raise bind.Refused("approve or reject")
    done, failed = [], {}
    for note_id in note_ids:
        try:
            if what == "approve":
                went = approve(pid, note_id)
                if went["failed"]:
                    failed[note_id] = "; ".join(went["failed"].values())
                    continue
            else:
                reject(pid, note_id, why)
            done.append(note_id)
        except bind.Refused as e:
            failed[note_id] = str(e)
    return {"what": what, "done": done, "failed": failed}


def waiting(paper) -> list[dict]:
    """The agent's notes still to be decided, oldest round first."""
    return [n for n in rounds.delivered_notes(paper)
            if is_agent(n.get("by")) and n.get("status", "open") == "open"]
