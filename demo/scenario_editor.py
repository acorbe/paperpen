#!/usr/bin/env python3
"""The third film: writing it back.

The editor, with the paper's files in a tree and the build beside the source.
A section is opened from the tree, a line is edited, the paper is built, and a
double click on the line shows where it landed in the build, which is SyncTeX
read forwards. Then the versions view: the last commit as old, the working
tree as new, and latexdiff between them, compiled, with what changed marked
up.

The build and the diff are the real ones, latexmk and latexdiff over the
fixture paper, so the film takes as long as they do.

    demo/scenario_editor.py [<frames-dir>]      default demo/frames-editor
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fixture  # noqa: E402
from scenario import MINE, Reel, seed, serve  # noqa: E402
from chrome import Chrome  # noqa: E402

W, H = 1100, 840

SAYS = {
    "editor": "Writing it back: the source with the build beside it, and the paper's files in a tree.",
    "open": "Open a section from the tree. Standard or emacs keys, and the spelling checked.",
    "edit": "Edit the line the note was about.",
    "build": "Build: latexmk into paperpen's cache, and the pages redraw beside you.",
    "synctex": "Double click a line and the build shows where it landed: SyncTeX, read forwards.",
    "versions": "The paper beside its own past: the last commit as old, the working tree as new.",
    "diff": "And latexdiff between them, compiled, with what changed marked up.",
}

FILE = "sec_results.tex"
WAS = "roughly three times"
NOW = "about twice"

EDITOR_IN = ("document.querySelectorAll('#edits .ta').length > 0 && "
             "document.querySelector('#edits .ta').value.length > 0 && "
             "document.querySelectorAll('#sheet .leaf img').length > 0")

# The line the words are on, so the pointer can go to it, and the words
# selected in the textarea so that what is typed replaces them.
SELECT = """
(() => {
  const p = here();
  const i = p.ta.value.indexOf(%s);
  if (i < 0) return null;
  p.ta.focus();
  p.ta.setSelectionRange(i, i + %d);
  markLine(p);
  return p.ta.value.slice(0, i).split('\\n').length;
})()
"""


ZOOM_IN = 3
# The edited sentence sits three quarters of the way down the fixture's one
# page, in Results; the diff pane is scrolled there and, locked, the other two
# follow.
DOWN_TO = """
(() => {
  const body = document.getElementById('body-diff');
  const leaf = body.querySelector('.leaf');
  if (!leaf) return false;
  body.scrollTop = leaf.offsetTop + leaf.offsetHeight * 0.75 - body.clientHeight / 2;
  body.dispatchEvent(new Event('scroll'));
  return true;
})()
"""


def wait_built(c: Chrome, which: str, timeout: float = 90) -> None:
    """A versions pane that offers to compile is compiled, and then it shows."""
    # the compile button sits in the pane's placeholder; the note pins on a
    # built page are buttons too, and a click on one opens a note
    button = f"#body-{which} .empty button"
    if c.js(f"!!document.querySelector({json.dumps(button)})"):
        c.click(*c.where(button))
    c.until(f"(() => {{ const i = document.querySelector('#body-{which} img');"
            f" return i && i.complete && i.naturalWidth > 0; }})()", timeout, every=0.4)


def film(base: str, out: Path) -> Reel:
    reel = Reel(out, SAYS)
    with Chrome(W, H) as c:
        # --- the editor, with the tree open ------------------------------
        # the tree is open on a screen this wide; on a narrow one it is put away
        c.goto(f"{base}/paper/{MINE}/edit", EDITOR_IN + " && "
               "!document.getElementById('files').hidden && "
               "document.querySelectorAll('#files .file').length > 1")
        c.move(W * 0.4, H - 60)
        c.settle(0.5)
        reel.beat(c, "editor", 2.2)

        reel.travel(c, c.where(f'#files .file[data-path="{FILE}"]'), "open", steps=6)
        c.click()
        c.until(f"here() && here().path === {json.dumps(FILE)} && here().ta.value.length > 0")
        c.settle(0.4)
        reel.beat(c, "open", 1.8)

        # --- a line edited -------------------------------------------------
        line = c.js(SELECT % (json.dumps(WAS), len(WAS)))
        if not line:
            raise SystemExit(f"{WAS!r} is not in {FILE} any more")
        reel.travel(c, c.where(f'#edits .ln[data-n="{line}"]'), "edit", steps=6)
        c.js(SELECT % (json.dumps(WAS), len(WAS)))   # the travel moved the focus
        for piece in (NOW[:5], NOW[5:]):
            c.type(piece)
            reel.beat(c, "edit", 0.5)
        reel.beat(c, "edit", 1.4)

        # --- built, and the line found in the build ----------------------
        reel.travel(c, c.where("#build"), "build", steps=6)
        c.click()
        c.until("document.getElementById('say').textContent.startsWith('built')", 90, every=0.4)
        c.settle(0.5)
        reel.beat(c, "build", 2.2)

        # closer in, so the box SyncTeX draws can be read as a line of the paper
        reel.travel(c, c.where("#in"), "synctex", steps=5)
        for _ in range(2):
            c.click()
            c.settle(0.3)
        reel.travel(c, c.where(f'#edits .ln[data-n="{line}"]'), "synctex", steps=6)
        c.dblclick()
        c.until("HIT.classList.contains('show')", 15)
        c.settle(0.5)
        reel.beat(c, "synctex", 2.6)

        # --- the paper beside its own past ---------------------------------
        c.goto(f"{base}/paper/{MINE}/versions",
               "document.querySelectorAll('#log .row').length > 1")
        c.settle(0.3)
        wait_built(c, "old")
        wait_built(c, "new")
        c.move(W * 0.3, H - 60)
        c.settle(0.5)
        reel.beat(c, "versions", 2.4)

        reel.travel(c, c.where("#body-diff .empty button"), "diff", steps=7)
        c.click()
        wait_built(c, "diff")
        c.settle(0.6)
        reel.beat(c, "diff", 1.2)
        # closer in, the three panes together, down to the sentence that moved
        reel.travel(c, c.where("#in"), "diff", steps=5)
        for _ in range(ZOOM_IN):
            c.click()
            c.settle(0.4)
        c.js(DOWN_TO)
        c.settle(0.6)
        reel.beat(c, "diff", 3.2)
    return reel


def main(argv: list[str]) -> int:
    out = Path(argv[0]).expanduser() if argv else HERE / "frames-editor"
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
