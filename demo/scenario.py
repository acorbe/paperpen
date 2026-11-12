#!/usr/bin/env python3
"""The demo, driven out of the running program.

Eight beats, each one a sentence somebody could say out loud, which is the
caption. The shelf and the reader are the real pages.

It moves, because a film of a program being used should show the thing doing
the using. The pointer is real: `chrome.glide` dispatches the moves and
`chrome.click` the clicks, so the page hovers and opens what a hand would open
it by, and each frame records where the pointer was for `demo-gif.py` to draw
it. The note in the middle is written with a stylus, a few strokes at a time
with the shutter open between them, so the handwriting appears the way
handwriting appears. Only the two taps that open the pad are called rather than
clicked: in pen mode the page canvas is the pen's, and a mouse pressed on it
draws instead of picking. It is called at the coordinates the pointer really
travelled to, which is `pickHere`, the same function the tablet's two taps call.

The other half of the film is the round. A reading is not finished when the
notes are made; it is finished when somebody has answered them. So the paper is
read and sent, and then answered the way it is answered now: an agent working
in the paper's repository proposes a fix for each note, with `paperpen
propose`, and the fixes come back into the notes themselves, where one tap
puts one into the LaTeX and the next note opens. The fixes are proposed by the
same code the command runs, against the fixture paper's real source, so the
diff on screen is one that applies.

    demo/scenario.py [<frames-dir>]      default demo/frames
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fixture  # noqa: E402  (demo/fixture.py, beside this file)
import handwriting  # noqa: E402
from chrome import Chrome, free_port  # noqa: E402

W, H = 1100, 840

MINE = "second-life-cells"
STUDENT = "sleep-draft"
REFEREE = "wake-draft"


def seed(root: Path) -> None:
    """The state the film opens on: a student's draft read and sent, a referee
    job being read now, and your own paper not opened since it was built."""
    os.environ.update({k: v for k, v in fixture.env(root).items()
                       if k.startswith("PAPERPEN_")})
    from paperpen import bind  # after the environment, so it aims at the fixture

    for paper in bind.load_papers():
        bind.paper.cmd_build(paper, prerender=False)

    def note_on(pid: str, page: int, phrase: str, text: str, tag: str) -> None:
        """A sentence is found by a phrase in it, not by its opening: a heading
        and the sentence after it share a text block, so the first sentence of a
        section begins `2. Method Participants recorded...`."""
        paper = bind.resolve_paper(pid)
        layout = bind.paper.layout_cached(paper, page)
        hit = next(s for s in layout["sentences"] if phrase in s["text"])
        bind.paper.cmd_note(paper, {"page": page, "kind": "sentence",
                                    "rect": hit["rects"][0], "rects": hit["rects"],
                                    "note": text, "tag": tag})

    note_on(STUDENT, 1, "Going to bed late is the commonest",
            "'commonest' and 'commonly' in one sentence. Pick another word for "
            "one of them.", "LANGUAGE")
    note_on(STUDENT, 1, "A session was counted when",
            "91 students, 63 of them complete: say what the other 28 contribute, "
            "and whether they differ.", "SCIENCE")
    bind.paper.cmd_export(bind.resolve_paper(STUDENT))

    # a second note on your own paper, so that using one fix has a next to go to
    note_on(MINE, 1, "Taking a cell to 20",
            "Three times? Table 1 says about twice: 0.74 against 0.38.", "SCIENCE")

    note_on(REFEREE, 1, "This is surprising",
            "The shift is the same at all four heating rates, which is what the "
            "viscosity argument says it should not be. This needs answering.",
            "SCIENCE")
    note_on(REFEREE, 1, "Each point in the figure",
            "200 cycles each: after how long a transient?", "AUTO")


def serve(root: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "paperpen.cli", "serve", "--port", str(port)],
        cwd=HERE.parent, env=fixture.env(root),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/", timeout=1).read()
            return proc, base
        except Exception:  # noqa: BLE001  it is simply not up yet
            time.sleep(0.25)
    proc.terminate()
    raise SystemExit("the server never came up")


IMAGES_IN = "Array.from(document.images).every(i => i.complete)"
READER_IN = ("META && META.built && document.querySelectorAll('.page img').length > 0"
             f" && {IMAGES_IN} && LAYOUT[1] && LAYOUT[1].sentences.length > 0")

# The sentence the note in the film is about: the one the paper's own argument
# turns on, so the note reads like a note and not like a demo.
ABOUT = "Every cell in the sample came out of the same vehicle model"
# What is written on it, by hand, in the pad. Short, because a margin note is
# short, and because handwriting is read at the size it was written.
BY_HAND = "one model, not a fleet. say so."

# Scroll first and measure afterwards: scrollIntoView moves the page under the
# rectangle, and coordinates taken before it lands the pointer somewhere else.
SPOT = """
(() => {
  const el = document.querySelector('.page[data-page="1"]');
  const s = LAYOUT[1].sentences.find(s => s.text.includes(%s));
  if (!s) return null;
  el.scrollIntoView({block: 'center'});
  const r = s.rects[0], k = scaleOf(el);   // points per CSS pixel, so divide
  const box = el.getBoundingClientRect();
  return [box.left + ((r[0] + r[2]) / 2) / k, box.top + ((r[1] + r[3]) / 2) / k];
})()
"""

# Where the pointer already is, which is where it travelled to. In pen mode the
# page canvas belongs to the pen, so a mouse pressed on it draws a line instead
# of picking a sentence; this is the function the two taps call, at the point
# the two taps would have been.
TAP = """
(() => {
  pickHere(document.querySelector('.page[data-page="1"]'), %f, %f);
  return !document.getElementById('pad').hidden;
})()
"""

# The pad's writing area, in the page's own coordinates, so the strokes are
# laid out to the size it actually came up at rather than to a size assumed
# here: it shrinks itself when there is no room below the sentence.
PAD_BOX = """
(() => {
  const b = document.getElementById('pad-canvas').getBoundingClientRect();
  return [b.left, b.top, b.width, b.height];
})()
"""

CLASS_IT = """
(() => {
  const s = document.getElementById('pad-tag');
  s.value = %s;
  s.dispatchEvent(new Event('change', {bubbles: true}));
  return s.value;
})()
"""


def steady_pad(c: Chrome, tries: int = 20) -> list[float]:
    """Where the pad has come to rest.

    It is placed relative to the sentence it is about, and the page under it is
    still settling when it opens: measured too early the rectangle is off by
    the width of a scrollbar and everything written lands that far out. So it
    is read until it reads the same twice, which is the only reliable way to
    know a layout has finished.
    """
    was = None
    for _ in range(tries):
        now = c.js(PAD_BOX)
        if now == was:
            return now
        was = now
        c.settle(0.15)
    raise SystemExit("the pad never stopped moving")


SAYS = {
    "shelf": "Four papers open at once, grouped by what each one is waiting for.",
    "pen": "Pen mode: two taps on a sentence, and a pad opens beside it.",
    "write": "You write on it by hand, and the ink is what the note keeps.",
    "kept": "Kept as ink, with the file and line of LaTeX that made the sentence.",
    "sent": "Finish the round and it goes, committed into the paper's own repository.",
    "fixes": "An agent answers the round: each note comes back with a fix to choose.",
    "used": "One tap puts it into the LaTeX, and the next note opens.",
    "pdf": "A draft that arrived as a PDF goes back as one, every note in the margin.",
}

# What the agent proposes, as `paperpen propose` would: exact text of the
# fixture's LaTeX and what replaces it, one for each note of the round.
FIXES = [
    ("same vehicle model",
     "the claim is one model's",
     "the note says one model is not a fleet",
     [("sec_cells.tex",
       "and we\nreport the fade rates as representative of second-life packs in general.",
       "and the\nfade rates reported here are for that model alone.")]),
    ("Taking a cell to 20",
     "about twice, as Table 1 has it",
     "the note checks the ratio against the table: 0.74 against 0.38",
     [("sec_results.tex",
       "costs roughly three times the capacity per cycle that\ntaking it to 40\\% costs,",
       "costs about twice the capacity per cycle that\ntaking it to 40\\% costs "
       "(0.74 against 0.38 per hundred cycles, Table~\\ref{tab:fade}),")]),
]


class Reel:
    """The frames, in order, and what the pointer was doing in each.

    Two frames of a pointer crossing a page that is not changing are the same
    picture, so they are the same file: the reel keeps one copy of each image
    it is given and names it again. A film that moves would otherwise be mostly
    duplicate PNGs, and they are committed.
    """

    def __init__(self, out: Path, says: dict | None = None):
        self.out = out
        self.says = SAYS if says is None else says   # the captions, by beat
        self.frames: list[dict] = []
        self.seen: dict[str, str] = {}
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.png"):
            old.unlink()

    def keep(self, png: bytes, caption: str, hold: float,
             at: tuple[float, float] | None = None, kind: str = "mouse") -> None:
        digest = hashlib.sha256(png).hexdigest()
        name = self.seen.get(digest)
        if name is None:
            name = f"{len(self.seen):02d}.png"
            (self.out / name).write_bytes(png)
            self.seen[digest] = name
        frame = {"png": name, "caption": caption, "hold": hold}
        if at is not None:
            frame["pointer"] = {"at": [round(at[0], 1), round(at[1], 1)], "kind": kind}
        self.frames.append(frame)

    def beat(self, c: Chrome, says: str, hold: float) -> None:
        self.keep(c.shot(), self.says[says], hold, c.at)

    def travel(self, c: Chrome, to: tuple[float, float], says: str,
               steps: int = 6, hold: float = 0.055) -> None:
        """The pointer crossing the page, filmed while it crosses."""
        for at in c.glide(to, steps):
            self.keep(c.shot(), self.says[says], hold, at)


def write_by_hand(c: Chrome, reel: Reel, text: str) -> None:
    """Write in the pad with a stylus, with the shutter open while it writes.

    A few strokes between frames rather than one frame at the end: the words
    appear in the order they were written, which is the only way a still film
    of handwriting reads as handwriting.
    """
    left, top, width, _ = steady_pad(c)
    strokes = handwriting.strokes(text, width=width)
    start = (left + strokes[0][0][0], top + strokes[0][0][1])
    reel.travel(c, start, "write", steps=5)

    written, tip, step = 0, start, max(1, len(strokes) // 12)
    for i in range(0, len(strokes), step):
        part = strokes[i:i + step]
        written += c.pen(part, at=(left, top))
        tip = (left + part[-1][-1][0], top + part[-1][-1][1])
        reel.keep(c.shot(), SAYS["write"], 0.085, tip, kind="pen")
    if written < 100:
        raise SystemExit("the pen wrote almost nothing; check the font data")
    reel.keep(c.shot(), SAYS["write"], 1.2, tip, kind="pen")


def propose_fixes(pid: str) -> None:
    """What the far end of the round does now: an agent in the paper's
    repository reads NOTES.md and proposes a fix for each note, which is
    `paperpen propose`. Each fix is found by the sentence its note is on."""
    from paperpen import bind, feedback

    sent = bind.paper.past_sessions(bind.resolve_paper(pid))
    if len(sent) < len(FIXES):
        raise SystemExit(f"{pid} delivered {len(sent)} notes; the round did not go")
    for phrase, summary, why, edits in FIXES:
        note = next((n for n in sent if phrase in (n.get("anchor") or "")), None)
        if note is None:
            raise SystemExit(f"no delivered note is on the sentence with {phrase!r}")
        feedback.propose(pid, note["id"], summary,
                         [{"file": f, "old": o, "new": n} for f, o, n in edits],
                         why=why, by="claude")


def film(base: str, out: Path) -> Reel:
    reel = Reel(out)
    with Chrome(W, H) as c:
        # --- the shelf, and the paper opened off it ----------------------
        c.goto(base + "/", IMAGES_IN)
        c.move(W * 0.72, H - 70)
        c.settle(0.5)
        reel.beat(c, "shelf", 2.0)

        reel.travel(c, c.where(f'a.card[href="/paper/{MINE}"]'), "shelf", steps=7)
        c.click()
        c.until(READER_IN, 40)
        c.settle(0.5)

        # --- a note, written by hand -------------------------------------
        reel.travel(c, c.where('.tool[data-tool="pen"]'), "pen")
        c.click()
        c.settle(0.35)

        spot = c.js(SPOT % json.dumps(ABOUT))
        if not spot:
            raise SystemExit("the sentence the note is about is not on page 1 any more")
        reel.travel(c, (spot[0], spot[1]), "pen", steps=7)
        if not c.js(TAP % (spot[0], spot[1])):
            raise SystemExit("the tap opened no pad; the sentence moved")
        c.settle(0.45)
        reel.beat(c, "pen", 1.5)

        c.js(CLASS_IT % json.dumps("SCIENCE"))
        write_by_hand(c, reel, BY_HAND)

        # The source line is worked out when the note is saved, so it is the
        # note reopened that shows it, exactly as it would be on the tablet.
        reel.travel(c, c.where("#pad-save"), "write", steps=5)
        c.click()
        c.until("document.querySelectorAll('.pin').length > 0")
        c.settle(0.45)
        reel.travel(c, c.where(".pin"), "kept", steps=5)
        c.click()
        c.until("!document.getElementById('sheet').hidden && "
                "!document.getElementById('sheet-hand').hidden && "
                "document.getElementById('sheet-where').textContent.includes('.tex:')")
        c.settle(0.4)
        reel.beat(c, "kept", 2.2)

        # --- the round: sent ---------------------------------------------
        c.js("closeSheet()")
        c.settle(0.2)
        reel.travel(c, c.where("#finish"), "sent", steps=7)
        c.click()                                   # its confirm is accepted
        c.until("(META.open || []).length === 0 && (META.past || []).length > 0", 30)
        c.goto(base + "/", IMAGES_IN)
        c.settle(0.5)
        reel.beat(c, "sent", 2.0)

        # --- and answered: a fix for each note, chosen in the note -------
        propose_fixes(MINE)
        c.goto(f"{base}/paper/{MINE}", READER_IN + " && document.querySelector('.pin.has-fix')")
        c.js("document.querySelector('.pin.has-fix').scrollIntoView({block: 'center'})")
        c.settle(0.5)
        reel.travel(c, c.where(".pin.has-fix"), "fixes", steps=7)
        c.click()
        c.until("!document.getElementById('sheet').hidden && "
                "document.querySelector('#sheet-fixes .fx-use')")
        c.settle(0.4)
        reel.beat(c, "fixes", 2.6)

        first = c.js("EDIT && EDIT.id")
        reel.travel(c, c.where("#sheet-fixes .fx-use"), "used", steps=5)
        c.click()
        c.until(f"EDIT && EDIT.id && EDIT.id !== {json.dumps(first)} && "
                "document.querySelector('#sheet-fixes .fx-use')", 20)
        c.settle(0.5)
        reel.beat(c, "used", 2.8)
    return reel


def anchor_of(note: dict) -> str:
    """A phrase out of the note's own sentence that the markup can find again.

    A section heading and the sentence after it share a text block, so a
    sentence often arrives as `2. Method Participants recorded...`, and an
    anchor starting there matches the heading rather than the sentence. The
    heading is dropped and the phrase taken from the sentence proper, and cut
    at a space: a phrase cut mid-word underlines half a word in the margin.
    """
    text = re.sub(r"^\d+\.\s+[A-Z][a-z]+\s+", "", (note.get("anchor") or "").strip())
    return text if len(text) <= 60 else text[:60].rsplit(" ", 1)[0]


def marked_up_pdf(root: Path, reel: Reel) -> None:
    """The last beat: the file you send a student, made by the real markup."""
    import pymupdf

    from paperpen import bind

    paper = bind.resolve_paper(STUDENT)
    notes = [[n["page"], anchor_of(n), f"{n['tag']}: {n['note']}"]
             for n in bind.paper.past_sessions(paper) if n.get("anchor")]
    marked = root / "cache" / "draft-marked.pdf"
    bind.markup.main(str(paper.pdf), str(marked), notes)

    doc = pymupdf.open(marked)
    page = doc[0]
    # the page as it was used: an A4 with notes down two thirds of it is mostly
    # white below, and white is not worth a quarter of the frame
    used = pymupdf.Rect(page.rect.x1, page.rect.y1, page.rect.x0, page.rect.y0)
    for block in page.get_text("blocks"):
        used |= pymupdf.Rect(block[:4])
    clip = (used + (-24, -24, 24, 24)) & page.rect
    scale = min(W / clip.width, H / clip.height)
    png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip).tobytes("png")
    doc.close()
    reel.keep(png, SAYS["pdf"], 2.4)


def main(argv: list[str]) -> int:
    out = Path(argv[0]).expanduser() if argv else HERE / "frames"
    root = fixture.build()
    seed(root)
    server, base = serve(root)
    try:
        reel = film(base, out)
    finally:
        server.terminate()
    marked_up_pdf(root, reel)
    (out / "frames.json").write_text(
        json.dumps(reel.frames, indent=2) + "\n", encoding="utf-8")
    seconds = sum(f["hold"] for f in reel.frames)
    print(f"{len(reel.frames)} frames ({len(reel.seen)} images) in {out}, "
          f"{seconds:.1f}s in all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
