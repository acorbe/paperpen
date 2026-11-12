"""Answers to delivered notes: fixes proposed for them, and a thread about them.

A round of notes goes into the paper's repository as `review/<date>/`, and what
comes back is worked on there, by a person or by an LLM session. What comes
back is not always a finished change. More often it is a proposal, or two, and
a question: *this sentence could become either of these; or did you mean the
density of the whole crowd?* That is what this file holds, beside the round it
answers:

    review/<date>/feedback.json

    {
      "format": "paperpen-feedback/1",
      "notes": {
        "<note id>": {
          "fixes": [
            {"id": "1", "by": "claude", "at": "2026-09-24T10:12:00",
             "summary": "define the density at its first use",
             "why": "the note asks which density; the text never says",
             "edits": [{"file": "main.tex",
                        "old": "depends on the density of the crowd",
                        "new": "depends on the local density of the crowd"}],
             "state": "proposed"}
          ],
          "thread": [{"by": "you", "at": "...", "text": "..."}]
        }
      }
    }

A fix is one or more edits, each an exact piece of text in a file of the
paper's repository and what replaces it. Exact text rather than a line number,
because a line number is out of date the moment anything above it moves, and
exact text either is still there or says plainly that it is not. A fix is
applied whole or not at all: every `old` has to be found, once, before any
file is written.

Applying writes into the working tree through the same safe write the editor
uses, and closes the note with what was applied. Nothing is committed: the
versions view shows the working tree against the last commit, which is how
what was applied gets looked at before it becomes history.

The file is written by whoever answers, by hand or with `paperpen propose` and
`paperpen reply`, and read by the page at /paper/<id>/feedback. It lives in the
repository because the answer is about the paper, and whoever works on the
paper next should find it there.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import bind, edit, queue, rounds

FORMAT = "paperpen-feedback/1"
NAME = "feedback.json"
PROPOSED, APPLIED, FAILED, UNDONE = "proposed", "applied", "failed", "undone"
YOU = "you"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def path(paper, session: str) -> Path:
    return paper.review / session / NAME


def read(paper, session: str) -> dict:
    data = rounds.read_json(path(paper, session), {})
    if not isinstance(data, dict) or not isinstance(data.get("notes"), dict):
        return {"format": FORMAT, "notes": {}}
    return data


def write(paper, session: str, data: dict) -> Path:
    """Atomically, so a page reading it never sees half a file."""
    out = path(paper, session)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": FORMAT, "notes": data.get("notes", {})}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out


def _need_repo(paper) -> None:
    if paper.is_pdf or not paper.repo.is_dir():
        raise bind.Refused(f"{paper.pid} has no source to fix: a round delivered as "
                           "a PDF is corrected by whoever wrote the paper")


def _note(paper, note_id: str) -> dict:
    """The delivered note, with the round it was delivered in."""
    for note in rounds.delivered_notes(paper):
        if note.get("id") == note_id:
            return note
    raise bind.Refused(f"no delivered note {note_id} in {paper.pid}")


def _entry(data: dict, note_id: str) -> dict:
    entry = data["notes"].setdefault(note_id, {})
    entry.setdefault("fixes", [])
    entry.setdefault("thread", [])
    return entry


# --- writing an answer -------------------------------------------------------

def propose(pid: str, note_id: str, summary: str, edits: list[dict],
            why: str = "", by: str = "claude", now: bool = False) -> dict:
    """Add a fix to a note. Checked now, so a fix that could never apply is
    refused while whoever wrote it is still there to write it again.

    With `now`, the fix is applied as soon as it is written down: the way a
    correction that leaves no choice is carried out, a word struck out and
    another written in. It is still a fix on the note, with its diff, so what
    was done is there to be read and undone one note at a time."""
    paper = bind.resolve_paper(pid)
    _need_repo(paper)
    note = _note(paper, note_id)
    if not summary.strip():
        raise bind.Refused("a fix needs a summary: one line, what it changes")
    if not edits:
        raise bind.Refused("a fix needs at least one edit")
    clean = []
    for e in edits:
        rel, old, new = str(e.get("file", "")), str(e.get("old", "")), str(e.get("new", ""))
        if not old:
            raise bind.Refused("an edit names the exact text it replaces; `old` is empty")
        if old == new:
            raise bind.Refused(f"an edit to {rel} changes nothing")
        edit.inside(paper, rel)
        clean.append({"file": rel, "old": old, "new": new})
    problems = _check(paper, clean)
    if problems:
        raise bind.Refused("; ".join(problems))
    data = read(paper, note["session"])
    entry = _entry(data, note_id)
    fix = {"id": str(1 + max((int(f["id"]) for f in entry["fixes"]
                              if str(f.get("id", "")).isdigit()), default=0)),
           "by": by or "claude", "at": _now(), "summary": summary.strip(),
           "why": why.strip(), "edits": clean, "state": PROPOSED}
    entry["fixes"].append(fix)
    write(paper, note["session"], data)
    out = {"paper": paper.pid, "note": note_id, "session": note["session"], "fix": fix}
    if now:
        out["applied"] = apply(pid, note_id, [fix["id"]], by=by)
    return out


def reply(pid: str, note_id: str, text: str, by: str = YOU) -> dict:
    """A word in the note's thread. The note stays open: a reply is a question
    or an instruction for whoever answers next, not a decision."""
    paper = bind.resolve_paper(pid)
    _need_repo(paper)
    note = _note(paper, note_id)
    if not text.strip():
        raise bind.Refused("nothing to say")
    data = read(paper, note["session"])
    said = {"by": by or YOU, "at": _now(), "text": text.strip()}
    _entry(data, note_id)["thread"].append(said)
    write(paper, note["session"], data)
    return {"paper": paper.pid, "note": note_id, "said": said}


# --- applying ----------------------------------------------------------------

def _check(paper, edits: list[dict]) -> list[str]:
    """What stands in the way of these edits, read against the files as they
    are now and in order, so two edits to one file see each other."""
    problems, texts = [], {}
    for e in edits:
        rel = e["file"]
        if rel not in texts:
            full = edit.inside(paper, rel)
            if not full.is_file():
                problems.append(f"{rel} is not there")
                texts[rel] = None
                continue
            texts[rel] = full.read_text(encoding="utf-8", errors="replace")
        text = texts[rel]
        if text is None:
            continue
        n = text.count(e["old"])
        if n == 0:
            problems.append(f"{rel} no longer has the text this edit replaces: "
                            f"{_short(e['old'])}")
        elif n > 1:
            problems.append(f"{rel} has the text this edit replaces {n} times, so "
                            f"which one is meant is not clear: {_short(e['old'])}")
        else:
            texts[rel] = text.replace(e["old"], e["new"], 1)
    return problems


def _short(text: str, wide: int = 60) -> str:
    text = " ".join(text.split())
    return repr(text if len(text) <= wide else text[:wide - 1] + "…")


def _apply_one(paper, fix: dict) -> list[str]:
    """Every edit of the fix, or none of them."""
    problems = _check(paper, fix["edits"])
    if problems:
        return problems
    by_file: dict[str, list[dict]] = {}
    for e in fix["edits"]:
        by_file.setdefault(e["file"], []).append(e)
    for rel, some in by_file.items():
        now = edit.read(paper, rel)
        text = now["text"]
        for e in some:
            text = text.replace(e["old"], e["new"], 1)
        edit.write(paper, rel, text, was=now["stamp"])
    return []


def apply(pid: str, note_id: str, fix_ids: list[str], by: str = YOU) -> dict:
    """Apply the chosen fixes to the working tree, in the order they were
    proposed, and close the note with what went in.

    A fix that no longer applies is reported and left as it was; the others
    still go in. The note is closed only when every chosen fix did: half of
    what was asked for is not the note answered.
    """
    paper = bind.resolve_paper(pid)
    _need_repo(paper)
    note = _note(paper, note_id)
    data = read(paper, note["session"])
    entry = _entry(data, note_id)
    wanted = [str(f) for f in fix_ids]
    chosen = [f for f in entry["fixes"] if str(f.get("id")) in wanted]
    missing = sorted(set(wanted) - {str(f.get("id")) for f in chosen})
    if missing:
        raise bind.Refused(f"note {note_id} has no fix {', '.join(missing)}")
    if not chosen:
        raise bind.Refused("choose at least one fix")

    done, failed = [], {}
    for fix in chosen:
        if fix.get("state") == APPLIED:
            done.append(fix)
            continue
        problems = _apply_one(paper, fix)
        if problems:
            fix["state"], fix["problem"] = FAILED, "; ".join(problems)
            failed[fix["id"]] = fix["problem"]
        else:
            fix["state"], fix["applied"] = APPLIED, {"by": by, "at": _now()}
            fix.pop("problem", None)
            done.append(fix)
    write(paper, note["session"], data)

    closed = False
    if done and not failed:
        said = "; ".join(f"{f['summary']} (fix {f['id']}, by {f['by']})" for f in done)
        queue.resolve(paper.pid, note_id, "done", f"applied: {said}")
        closed = True
    return {"paper": paper.pid, "note": note_id, "applied": [f["id"] for f in done],
            "failed": failed, "closed": closed}


def undo(pid: str, note_id: str, fix_id: str, by: str = YOU) -> dict:
    """Take an applied fix back out: every edit read the other way, the new
    text found once and the old put back, all of it or none. The note opens
    again, since what answered it is gone."""
    paper = bind.resolve_paper(pid)
    _need_repo(paper)
    note = _note(paper, note_id)
    data = read(paper, note["session"])
    fix = next((f for f in _entry(data, note_id)["fixes"] if str(f.get("id")) == str(fix_id)), None)
    if fix is None:
        raise bind.Refused(f"note {note_id} has no fix {fix_id}")
    if fix.get("state") != APPLIED:
        raise bind.Refused(f"fix {fix_id} of {note_id} is not applied, so there is nothing to undo")
    back = {"edits": [{"file": e["file"], "old": e["new"], "new": e["old"]}
                      for e in reversed(fix["edits"])]}
    problems = _apply_one(paper, back)
    if problems:
        raise bind.Refused("it cannot be undone as it stands: " + "; ".join(problems)
                           + ". The text it put in has been changed since.")
    fix["state"], fix["undone"] = UNDONE, {"by": by, "at": _now()}
    write(paper, note["session"], data)
    queue.resolve(paper.pid, note_id, "open", "")
    return {"paper": paper.pid, "note": note_id, "undone": fix["id"]}


def applied_since(paper, stamp: str) -> list[dict]:
    """The fixes applied after `stamp`, an ISO time, with their note: what a
    commit of the review takes in."""
    out = []
    for fj in sorted(paper.review.glob(f"*/{NAME}")):
        for note_id, entry in read(paper, fj.parent.name)["notes"].items():
            for fix in entry.get("fixes", []):
                if fix.get("state") == APPLIED and (fix.get("applied") or {}).get("at", "") > stamp:
                    out.append({"note": note_id, "session": fj.parent.name, **fix})
    return out


# --- reading it back ---------------------------------------------------------

def items(pid: str) -> list[dict]:
    """Every delivered note of the paper that has an answer, with the note
    itself, so the page needs nothing else. Open ones first, then by round."""
    paper = bind.resolve_paper(pid)
    if paper.is_pdf or not paper.repo.is_dir():
        return []
    notes = {n.get("id"): n for n in rounds.delivered_notes(paper)}
    out = []
    for fj in sorted(paper.review.glob(f"*/{NAME}")):
        session = fj.parent.name
        for note_id, entry in read(paper, session)["notes"].items():
            note = notes.get(note_id, {})
            source = note.get("source") or {}
            out.append({
                "id": note_id, "session": session, "by": note.get("by", ""),
                "status": note.get("status", "open"),
                "response": note.get("response", ""),
                "tag": (note.get("tag") or "AUTO").upper(),
                "text": rounds.say(note) if note else "(this note is not in the round)",
                "anchor": (note.get("anchor") or "").strip(),
                "source": f"{source['file']}:{source['line']}" if source.get("file") else "",
                "page": note.get("page", 0),
                "handwritten": bool(note.get("hand") or note.get("ink")),
                "fixes": entry.get("fixes", []),
                "thread": entry.get("thread", []),
            })
    # and every delivered note still open that nobody has answered yet: it is
    # what whoever answers next has to see first, with an empty thread
    listed = {i["id"] for i in out}
    for note in notes.values():
        if note.get("id") in listed or note.get("status", "open") != "open":
            continue
        source = note.get("source") or {}
        out.append({
            "id": note["id"], "session": note.get("session", ""), "by": note.get("by", ""),
            "status": "open",
            "response": "", "tag": (note.get("tag") or "AUTO").upper(),
            "text": rounds.say(note), "anchor": (note.get("anchor") or "").strip(),
            "source": f"{source['file']}:{source['line']}" if source.get("file") else "",
            "page": note.get("page", 0),
            "handwritten": bool(note.get("hand") or note.get("ink")),
            "fixes": [], "thread": []})
    out.sort(key=lambda i: (i["status"] != "open", i["session"], i["page"]))
    return out


def by_note(paper) -> dict:
    """What the reader needs to show a note's answers in the note itself: for
    each note id, its fixes and its thread. Empty for a paper with nothing to
    fix, and never a refusal, because the reader asks for it on every load."""
    try:
        if paper.is_pdf or not paper.repo.is_dir():
            return {}
        out = {}
        for fj in sorted(paper.review.glob(f"*/{NAME}")):
            for note_id, entry in read(paper, fj.parent.name)["notes"].items():
                out[note_id] = {"fixes": entry.get("fixes", []),
                                "thread": entry.get("thread", [])}
        return out
    except (OSError, ValueError):
        return {}


def count(paper) -> int:
    """Open notes with a fix still waiting to be chosen, for the shelf to show."""
    try:
        return sum(1 for i in items(paper.pid) if i["status"] == "open"
                   and any(f.get("state") == PROPOSED for f in i["fixes"]))
    except (bind.Refused, OSError, ValueError):
        return 0
