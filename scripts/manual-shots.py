#!/usr/bin/env python3
"""The manual's pictures, taken out of the running program.

    scripts/manual-shots.py [<dir>]      default /tmp/paperpen-manual

Same rule as the demo film: nothing here is screen-grabbed, and nothing here is
anybody's. The shelf is `demo/fixture.py` (four invented papers, invented
authors, example.org), so a picture in the manual can be published without
anybody reading it in a diff first, and so a change to a view either still
takes its picture or fails loudly.

The pictures go to manual/shots/ and are committed, because GitHub Pages serves
the manual from the repository and a CI job that had to install LaTeX and drive
a browser to rebuild them would be a worse thing to keep working than a PNG.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "demo"))
sys.path.insert(0, str(ROOT))

import fixture  # noqa: E402
import scenario  # noqa: E402
from chrome import Chrome  # noqa: E402

SHOTS = ROOT / "manual" / "shots"
MINE = "second-life-cells"
STUDENT = "sleep-draft"

# A second commit, so the versions view has two of them to put side by side.
# The co-author's edit is the one the film's paper is about: a sentence that
# says more than the measurement does.
BEFORE = ("Above the knee the 48 cells agree closely; below\n"
          "it they scatter, and the scatter grows with every hundred cycles.")
AFTER = ("Above the knee the 48 cells agree to within a per cent; below it they\n"
         "scatter, and the scatter grows with every hundred cycles, which is the\n"
         "behaviour a pack has to be sized against.")


def wait(chrome: Chrome, what: str, seconds: float = 30.0) -> None:
    chrome.until(what, seconds)


def size(chrome: Chrome, width: int, height: int) -> None:
    """A picture is cropped by the window it is taken in, so each view gets the
    window it fills rather than a field of grey under it."""
    chrome.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                deviceScaleFactor=1, mobile=False)
    chrome.settle(0.3)


def shoot(chrome: Chrome, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / f"{name}.png").write_bytes(chrome.shot())
    print(f"  {name}.png")


def a_second_commit(root: Path) -> None:
    repo = root / "secondlife"
    results = repo / "sec_results.tex"
    text = results.read_text(encoding="utf-8")
    if BEFORE not in text:
        raise SystemExit(f"the fixture no longer says {BEFORE!r}; the manual's "
                         f"diff picture has nothing to show")
    results.write_text(text.replace(BEFORE, AFTER), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=R. Okonkwo",
                    "-c", "user.email=r@example.org", "commit", "-qm",
                    "results: say what the rested cells do"],
                   check=True, capture_output=True)


def dbl(chrome: Chrome, x: float, y: float) -> None:
    chrome.move(x, y)
    for count in (1, 2):
        chrome.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y,
                    button="left", buttons=1, clickCount=count)
        chrome.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y,
                    button="left", buttons=0, clickCount=count)


def main(argv: list[str]) -> int:
    root = Path(argv[0]).expanduser() if argv else Path("/tmp/paperpen-manual")
    print(f"building the fixture in {root}")
    fixture.build(root, fresh=True)
    scenario.seed(root)
    a_second_commit(root)
    proc, base = scenario.serve(root)
    print(f"serving {base}")
    try:
        with Chrome(width=1180, height=880) as c:
            c.goto(base + "/", ready="document.querySelectorAll('.card').length >= 3")
            size(c, 1180, 650)
            c.settle(0.8)
            shoot(c, "shelf")

            c.goto(base + "/queue", ready="document.querySelectorAll('main .row').length > 0")
            size(c, 1180, 700)
            c.settle(0.5)
            shoot(c, "queue")

            c.goto(base + f"/paper/{STUDENT}", ready=scenario.READER_IN)
            size(c, 1180, 880)
            c.settle(1.2)
            shoot(c, "reader")

        with Chrome(width=1560, height=940) as c:
            c.goto(base + f"/paper/{MINE}/edit",
                   ready="typeof here === 'function'")
            wait(c, "panes.size === 1 && here() && here().ta.value.length > 100")
            c.settle(1.0)
            # the sentence is in an \\input file, which is the case worth
            # showing: SyncTeX puts the caret in the file that made the line,
            # not in the one that was compiled
            c.js("showIn(here(), 'sec_results.tex')")
            wait(c, "here().ta.value.indexOf('to within a per cent') > 0")
            c.settle(0.6)
            # found in the text rather than counted, so the picture survives an
            # edit above it
            spot = c.js("""(() => {
              const pane = here();
              const at = pane.ta.value.indexOf('to within a per cent');
              if (at < 0) return null;
              const line = pane.ta.value.slice(0, at).split('\\n').length;
              pane.ta.scrollTop = Math.max(0, pane.hl.children[line - 1].offsetTop - 140);
              const box = pane.hl.children[line - 1].getBoundingClientRect();
              return [Math.round(box.left + 70), Math.round(box.top + 6)];
            })()""")
            if not spot:
                raise SystemExit("the fixture's results section no longer has the "
                                 "sentence the editor picture points at")
            c.settle(0.4)
            dbl(c, spot[0], spot[1])
            wait(c, "document.getElementById('hit').classList.contains('show')")
            c.settle(0.8)
            shoot(c, "editor")

            c.goto(base + f"/paper/{MINE}/versions",
                   ready="document.querySelectorAll('#log .row').length > 1")
            c.settle(0.8)
            # the oldest commit on the left, the working tree on the right,
            # and each pane compiled the way a reader would: by pressing the
            # button the pane offers when it has nothing built yet
            size(c, 1560, 780)
            c.js("choose('old', view.rows[view.rows.length - 1].ref)")
            for pane in ("old", "diff"):
                wait(c, f"view.pages.{pane} > 0"
                        f" || document.querySelector('#pane-{pane} .empty button')", 40)
                c.js(f"(() => {{ const b = document.querySelector('#pane-{pane} .empty button');"
                     f" if (b) b.click(); }})()")
                wait(c, f"view.pages.{pane} > 0", 240)
            c.settle(1.0)
            shoot(c, "versions")
    finally:
        proc.terminate()
    print(f"{len(list(SHOTS.glob('*.png')))} pictures in {SHOTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
