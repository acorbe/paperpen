#!/usr/bin/env python3
"""The second film: the agent reads the paper first.

The first film starts with your notes. This one starts with none: the reader
is open on your own paper, Review is pressed in the header, and the notes
arrive written by the agent, each anchored to its sentence and carrying the
fix it would make. You open one and approve it, the next opens and you reject
it with a word why, and the Fixes page shows what is left to decide.

Nothing in a demo calls out to a model. The notes are written by the same
command the review run invokes, `paperpen suggest`, from the list below,
against the fixture paper's real LaTeX, so every diff on screen is one that
applies. The Start button is pressed for real, with the one call it makes to
the server pointed at nothing: the page then does what it does when the run
reports back, which is to draw the notes.

    demo/scenario_review.py [<frames-dir>]      default demo/frames-review
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fixture  # noqa: E402
from scenario import IMAGES_IN, MINE, READER_IN, Reel, seed, serve  # noqa: E402
from chrome import Chrome  # noqa: E402

W, H = 1100, 840

SAYS = {
    "reader": "Your own paper, open in the reader, before anyone else has read it.",
    "ask": "Review, in the header: say what to look for, or leave it to a general read.",
    "arrive": "The agent reads the paper and writes notes of its own, each with the fix it would make.",
    "approve": "Open one: what is wrong, the diff that would fix it, and Approve.",
    "next": "Approved, it goes into the LaTeX, and the next proposal opens.",
    "reject": "Not this one: a word why, and Reject. The reason is kept for the next run.",
    "fixes": "The Fixes page: every proposal in one list, to decide a few at once.",
}

FOCUS = "clarity, notation"
WHY_NOT = "keep the hedge, the data are few"

# What the agent writes, as `paperpen suggest` would: the exact text of the
# fixture's LaTeX and what replaces it. The last one has no fix, which is a
# question, and is allowed.
NOTES = [
    ("LANGUAGE",
     "'which is the point at which' says which twice in one clause.",
     "one 'which' instead of two",
     [("sec_cells.tex",
       "which is\nthe point at which the car stops being worth driving",
       "the point\nwhere the car stops being worth driving")]),
    ("LANGUAGE",
     "'linear' is said three times in two lines; the second sentence can carry it alone.",
     "'and not below', once",
     [("sec_results.tex",
       "and\nstops being linear below that.",
       "and\nnot below.")]),
    ("SCIENCE",
     "0.5C is given without saying which capacity it is relative to: as sold, or as recovered. "
     "The two differ by 20% here.",
     "say which capacity the C-rate refers to",
     [("sec_cells.tex",
       "cycled at a constant 0.5C between fixed voltage limits",
       "cycled at a constant 0.5C, rated on the capacity as sold, between fixed\nvoltage limits")]),
    ("QUESTION",
     "Is 25 degrees the room or the cell? A cell cycled at 0.5C runs warmer than its room.",
     "", [("sec_cells.tex", "25 degrees Celsius", "")]),
]

# The Start button's one call goes to the server, which would start a model.
# Here it goes nowhere: the page is told the run reported back, and draws
# what `suggest` has already written.
NO_CALL = """
(() => {
  headerCall = (url, body, done, button) => { toast(done({ok: true}), 6000); load(); };
  return true;
})()
"""


def suggest_notes(pid: str) -> None:
    from paperpen import proposals

    for tag, note, summary, edits in NOTES:
        if summary:
            proposals.suggest(pid, note, tag, summary=summary,
                              edits=[{"file": f, "old": o, "new": n} for f, o, n in edits])
        else:
            f, at, _ = edits[0]
            proposals.suggest(pid, note, tag, file=f, at=at)


def film(base: str, out: Path) -> Reel:
    reel = Reel(out, SAYS)
    with Chrome(W, H) as c:
        # --- the reader, and Review in its header --------------------------
        c.goto(f"{base}/paper/{MINE}", READER_IN)
        c.move(W * 0.55, H - 60)
        c.settle(0.5)
        reel.beat(c, "reader", 1.8)

        reel.travel(c, c.where("#ask-review"), "ask", steps=7)
        c.click()
        c.until("!document.getElementById('review-focus').hidden")
        c.settle(0.3)
        reel.beat(c, "ask", 0.8)
        for piece in (FOCUS[:8], FOCUS[8:]):
            c.type(piece)
            reel.beat(c, "ask", 0.45)
        reel.beat(c, "ask", 1.4)

        # --- the run, and the notes it writes ------------------------------
        suggest_notes(MINE)
        c.js(NO_CALL)
        # the field appearing moved the button along the header, so find it again
        reel.travel(c, c.where("#ask-review"), "ask", steps=4)
        c.click()                                    # Start the review
        c.until("document.querySelectorAll('.pin.proposal').length >= 3", 20)
        c.js("document.querySelector('.pin.proposal').scrollIntoView({block: 'center'})")
        c.settle(0.6)
        reel.beat(c, "arrive", 2.6)

        # --- one approved ---------------------------------------------------
        reel.travel(c, c.where(".pin.proposal.has-fix"), "approve", steps=7)
        c.click()
        c.until("!document.getElementById('sheet').hidden && "
                "document.querySelector('#sheet-fixes .fx-use')")
        c.settle(0.4)
        reel.beat(c, "approve", 2.6)

        first = c.js("EDIT && EDIT.id")
        reel.travel(c, c.where("#sheet-fixes .fx-use"), "next", steps=5)
        c.click()
        c.until(f"EDIT && EDIT.id && EDIT.id !== {json.dumps(first)} && "
                "document.querySelector('#sheet-fixes .fx-reject')", 20)
        c.settle(0.5)
        reel.beat(c, "next", 2.2)

        # --- the next rejected, with a reason -------------------------------
        reel.travel(c, c.where("#sheet-fixes .fx-reply input"), "reject", steps=5)
        c.click()
        for piece in (WHY_NOT[:16], WHY_NOT[16:]):
            c.type(piece)
            reel.beat(c, "reject", 0.45)
        reel.travel(c, c.where("#sheet-fixes .fx-reject"), "reject", steps=4)
        c.click()
        c.until("(META.past || []).some(n => n.by === 'claude' && n.status === 'rejected')", 20)
        c.settle(0.6)
        reel.beat(c, "reject", 2.2)

        # --- what is left, on the Fixes page --------------------------------
        c.goto(f"{base}/paper/{MINE}/feedback",
               "document.querySelectorAll('#list .note').length > 0")
        c.settle(0.4)
        reel.travel(c, c.where('.filters .chip[data-show="claude"]'), "fixes", steps=6)
        c.click()
        c.settle(0.5)
        reel.beat(c, "fixes", 2.8)
    return reel


def main(argv: list[str]) -> int:
    out = Path(argv[0]).expanduser() if argv else HERE / "frames-review"
    root = fixture.build()
    seed(root)
    server, base = serve(root)
    try:
        reel = film(base, out)
    finally:
        server.terminate()
    (out / "frames.json").write_text(
        json.dumps(reel.frames, indent=2) + "\n", encoding="utf-8")
    seconds = sum(f["hold"] for f in reel.frames)
    print(f"{len(reel.frames)} frames ({len(reel.seen)} images) in {out}, "
          f"{seconds:.1f}s in all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
