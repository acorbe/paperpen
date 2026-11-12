"""Finishing a round: recording it, and sending it where its reader needs it.

The delivery is a property of the paper, not a mode of the app, because it is
a property of the person on the other end. Your own manuscript takes a commit
in its own repository, which is where you will be editing it. A student's
draft takes a PDF, because what you send a student is a file they can open. A
referee job takes the same file and touches no repository at all.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import archive, bind, registry, rounds

REPO, PDF, FOLDER = "repo", "pdf", "folder"

# A section heading and the sentence after it share a text block in a PDF, so a
# sentence often arrives as `2. Method Pairs were identified...`. An anchor
# starting there matches the heading rather than the sentence, and the markup
# then draws its leader to the wrong line.
HEADING = re.compile(r"^\d+\.?\s+[A-Z][a-z]+\s+")
ANCHOR_WORDS = 60


def anchor_of(note: dict) -> str:
    """A phrase from the note's own sentence that the markup can find again."""
    return HEADING.sub("", (note.get("anchor") or "").strip())[:ANCHOR_WORDS]


def triples(notes: list[dict]) -> list[list]:
    """The notes in the form the marked-up PDF is written from."""
    out = []
    for note in notes:
        said = rounds.say(note)
        anchor = anchor_of(note)
        if not (said and anchor):
            continue  # nothing to write, or nowhere to point it
        tag = note.get("tag", "AUTO").upper()
        out.append([note.get("page", 1), anchor,
                    said if tag == "AUTO" else f"{tag}: {said}"])
    return out


def marked_pdf(paper, notes: list[dict], session: str) -> Path:
    """The file you send its author: the paper with every note in the margin."""
    stem = Path(paper.main).stem
    where = paper.repo if paper.repo.is_dir() else rounds.round_dir(paper, session)
    where.mkdir(parents=True, exist_ok=True)
    out = where / f"{stem}-notes-{session}.pdf"
    bind.markup.main(str(paper.pdf), str(out), triples(notes))
    return out


def finish(pid: str, delivery: str = "", commit: bool = True) -> dict:
    """Close the open round: record it here, then deliver it.

    The record is written first and unconditionally. A delivery can fail for
    reasons that have nothing to do with the reading (a repository that has
    moved, a disk that is full), and a reading that is lost because its
    delivery failed is the one outcome worth engineering against.
    """
    paper = bind.resolve_paper(pid)
    notes = rounds.open_round(paper)
    if not notes:
        raise bind.Refused("the open round has no notes")
    delivery = (delivery or registry.extras(paper.pid)["delivery"]).lower()
    if delivery not in (REPO, PDF, FOLDER):
        raise bind.Refused(f"{delivery} is not one of {REPO}, {PDF}, {FOLDER}")

    session = date.today().isoformat()
    info = bind.paper.build_info(paper)
    kept = rounds.write_record(paper, notes, session, info)

    result = {"paper": paper.pid, "session": session, "notes": len(notes),
              "delivery": delivery, "record": str(kept)}
    if delivery in (REPO, FOLDER):
        if not paper.repo.is_dir():
            raise bind.Refused(f"no such directory to deliver into: {paper.repo}")
        out = bind.paper.cmd_export(paper, commit=(delivery == REPO and commit))
        result.update(where=out["written"], committed=out.get("committed", False))
    else:
        out = marked_pdf(paper, notes, session)
        bind.paper.write_session(paper, [])  # the round is closed either way
        result.update(where=str(out), committed=False)

    rounds.write_sent(paper, session, notes=len(notes), delivery=delivery,
                      where=result["where"], committed=result["committed"])

    # The paper's own copy of its history, refreshed after the round is
    # recorded and after `sent.json` is written, so the index it carries is
    # complete for the round just delivered. This is what `paperpen adopt`
    # reads, and it is the only thing that makes a shelf rebuildable from a
    # clone rather than from a backup of this machine.
    #
    # It is done last and is never allowed to fail the delivery. By this point
    # the reading is recorded and the round is in the author's hands; a
    # manifest that did not get written is a `paperpen record` away, and
    # losing the delivery over it would be the wrong trade.
    if registry.extras(paper.pid)["record"] == "repo" and paper.repo.is_dir():
        try:
            result["record"] = archive.keep_in_repo(paper, notes, session, info,
                                                    commit=commit)
        except (OSError, ValueError, bind.Refused) as e:
            result["record_error"] = str(e)

    # And the round is handed to whoever answers it: claude, in the paper's
    # checkout, if the paper says so. Started behind, and never a reason for
    # the delivery to have failed.
    if delivery == REPO:
        from . import agent
        result["agent"] = agent.after_finish(paper, session)
    return result
