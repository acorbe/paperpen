"""What the shelf knows about each paper.

The card has to answer, at a glance and without opening anything: what this
paper is, whose it is, whether what I would be reading is current, and whether
it is waiting on me or on somebody else. The thumbnail is part of that answer:
a shelf of six papers is recognised by their first pages long before it is read
by their titles.
"""

from __future__ import annotations

from pathlib import Path

from . import bind, feedback, registry, rounds

# A first page at half scale is about 300px across for A4, which is twice the
# width it is drawn at. It is rendered once and kept, like every other page.
THUMB_SCALE = 0.5

ORDER = (rounds.OPEN, rounds.WAITING, rounds.IDLE)
GROUPS = {
    rounds.OPEN: ("Reading", "a round is open"),
    rounds.WAITING: ("Sent, waiting", "delivered, and some notes are still open"),
    rounds.IDLE: ("Idle", "nothing open, nothing outstanding"),
}


def thumbnail(paper) -> Path | None:
    """The first page, small. None when the paper has not been built yet."""
    if not paper.pdf.is_file():
        return None
    try:
        return bind.paper.page_png(paper, 1, THUMB_SCALE)
    except (bind.Refused, OSError, ValueError):
        return None


def card(paper) -> dict:
    """One paper, as the shelf shows it.

    Deliberately cheap: it reads the build record and the notes and renders one
    small page, and it does not ask whether the sources have moved. That walks
    a repository for timestamps, and doing it for every paper is what would
    make opening the shelf slow. The reader says it, for the paper you opened.
    """
    info = bind.paper.build_info(paper)
    open_notes = rounds.open_round(paper)
    delivered = rounds.sent(paper)
    return {
        **registry.extras(paper.pid),
        "id": paper.pid,
        "name": paper.name,
        "repo": str(paper.repo),
        "main": paper.main,
        "task": paper.task,
        "is_pdf": paper.is_pdf,
        "built": paper.pdf.is_file(),
        "pages": info.get("pages", 0),
        "built_at": (info.get("at") or "")[:10],
        "commit": info.get("commit", ""),
        "synctex": bool(info.get("synctex")),
        "open": len(open_notes),
        "unclassified": sum(1 for n in open_notes if n.get("tag", "AUTO") == "AUTO"),
        "sent": delivered,
        "last_sent": delivered[0] if delivered else None,
        "outstanding": sum(r["open"] for r in delivered),
        "state": rounds.state(paper),
        "thumb": thumbnail(paper) is not None,
        # open notes with a proposed fix still to be chosen
        "to_choose": feedback.count(paper),
    }


def shelf(archived: bool = False) -> list[dict]:
    """The groups, in the order they want attention, each with its papers."""
    cards = [card(p) for p in bind.load_papers()]
    cards = [c for c in cards if c["archived"] == archived]
    out = []
    for state in ORDER:
        here = [c for c in cards if c["state"] == state]
        if not here:
            continue
        here.sort(key=lambda c: (c["last_sent"]["date"] if c["last_sent"] else "",
                                 c["name"]), reverse=True)
        title, blurb = GROUPS[state]
        out.append({"state": state, "title": title, "blurb": blurb, "papers": here})
    return out
