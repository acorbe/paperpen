#!/usr/bin/env python3
"""Handwriting for the demo, as strokes a pen could have made.

The film has to show the pen, because the pen is the whole point of the
program, and a demo that only ever types is a demo of a text box. What it must
not do is paste a picture of handwriting into the frame: the note in the film
is a note the reader really took, so what is needed here is not an image but a
list of strokes, which is exactly what a stylus gives the page.

So the letters come from a single-stroke font. Hershey Script is one pen's
path per glyph (it was drawn for plotters, which have a pen and no fill), and
laid out on a line with a little drift it reads as handwriting rather than as
type. `strokes()` hands back polylines in the pad's own pixels, and
`scenario.py` walks them with pen pointer events, so the reader receives the
same events a stylus sends and keeps what it works out from them.

    demo/handwriting.py                 draw a sample to /tmp/handwriting.svg
    demo/handwriting.py --take          take the glyphs from Inkscape again

The glyph data is Dr. A. V. Hershey's, by way of Inkscape's SVG fonts, and
`hershey-script.json` beside this file carries the acknowledgements its licence
asks for. `--take` writes that file again and is how it got there; nothing
here is edited by hand.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_FILE = HERE / "hershey-script.json"

# Where Inkscape keeps the SVG fonts its Hershey Text extension draws with.
INKSCAPE_FONTS = [
    Path("/usr/share/inkscape/extensions/svg_fonts/HersheyScriptMed.svg"),
    Path("/usr/local/share/inkscape/extensions/svg_fonts/HersheyScriptMed.svg"),
    Path.home() / ".config/inkscape/extensions/svg_fonts/HersheyScriptMed.svg",
]

ACKNOWLEDGEMENT = [
    "The Hershey Fonts were originally created by Dr. A. V. Hershey while "
    "working at the U. S. National Bureau of Standards.",
    "The format of the Font data in this distribution was originally created "
    "by James Hurt, Cognition, Inc., 900 Technology Park Drive, Billerica, "
    "MA 01821.",
    "Converted to SVG fonts in 2019 by Windell H. Oskay, "
    "www.evilmadscientist.com, and shipped with Inkscape.",
]

X_HEIGHT = 300.0   # font units, from the font's own font-face element


def _load() -> dict:
    data = json.loads(FONT_FILE.read_text(encoding="utf-8"))
    return {c: (g["adv"], g["strokes"]) for c, g in data["glyphs"].items()}


def _resample(points: list[list[float]], step: float) -> list[list[float]]:
    """A pen reports while it moves, not only where it turns.

    A glyph arrives as its corners, and replaying only those gives the page
    four events for a letter. The reader thins what it is sent anyway, so this
    walks each segment at roughly the spacing a stylus would have reported at.
    """
    out = [points[0]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        span = math.hypot(x1 - x0, y1 - y0)
        for i in range(1, max(1, int(span / step)) + 1):
            t = min(1.0, i * step / span) if span else 1.0
            out.append([x0 + (x1 - x0) * t, y0 + (y1 - y0) * t])
        out[-1] = [x1, y1]
    return out


def wrap(text: str, width: float, scale: float, glyphs: dict, tracking: float) -> list[str]:
    def run(s: str) -> float:
        return sum(glyphs.get(c, glyphs[" "])[0] for c in s) * scale * tracking

    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = word if not line else f"{line} {word}"
        if run(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def strokes(text: str, *, width: float, x_height: float = 12.0,
            line_height: float = 38.0, baseline: float = 36.0,
            left: float = 16.0, tracking: float = 0.92,
            seed: int = 7) -> list[list[list[float]]]:
    """`text` as polylines in pad pixels, y downwards, ready to be written.

    The drift is the reason this is not a font: every glyph sits a little off
    the line and a little off its neighbour's size, and the baseline wanders
    the way a hand wanders on unruled paper. It is small, under a pixel, and
    it is what stops six words from looking stamped.
    """
    glyphs = _load()
    rng = random.Random(seed)
    scale = x_height / X_HEIGHT
    out: list[list[list[float]]] = []

    for row, line in enumerate(wrap(text, width - left * 2, scale, glyphs, tracking)):
        x = left
        y0 = baseline + row * line_height
        for char in line:
            adv, paths = glyphs.get(char, glyphs[" "])
            dx = rng.uniform(-0.5, 0.5)
            dy = rng.uniform(-0.7, 0.7)
            size = scale * rng.uniform(0.96, 1.04)
            for path in paths:
                pen = [[x + dx + px * size,
                        y0 + dy - py * size + math.sin((x + px * size) / 46.0) * 0.9]
                       for px, py in path]
                if len(pen) == 1:
                    pen.append([pen[0][0] + 0.4, pen[0][1] + 0.4])
                out.append(_resample(pen, 2.0))
            x += adv * scale * tracking
    return out


# --- taking the glyphs again ------------------------------------------------

def take() -> Path:
    """Write `hershey-script.json` from Inkscape's copy of the font.

    Only the printable ASCII glyphs, only their points: the file that results
    is the font reduced to what a pen does with it, which is all this needs.
    """
    src = next((p for p in INKSCAPE_FONTS if p.is_file()), None)
    if src is None:
        raise SystemExit("no Inkscape SVG fonts here; looked in:\n  "
                         + "\n  ".join(str(p) for p in INKSCAPE_FONTS))
    import xml.etree.ElementTree as ET

    glyphs: dict[str, dict] = {}
    for g in ET.parse(src).iter("{http://www.w3.org/2000/svg}glyph"):
        char = g.get("unicode") or ""
        if len(char) != 1 or not 32 <= ord(char) < 127:
            continue
        paths = []
        for part in g.get("d", "").split("M"):
            nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", part.replace("L", " "))]
            pts = [[nums[i], nums[i + 1]] for i in range(0, len(nums) - 1, 2)]
            if pts:
                paths.append(pts)
        glyphs[char] = {"adv": float(g.get("horiz-adv-x", 378)), "strokes": paths}

    if " " not in glyphs:
        glyphs[" "] = {"adv": 378.0, "strokes": []}
    FONT_FILE.write_text(json.dumps(
        {"font": "Hershey Script medium", "source": str(src),
         "acknowledgements": ACKNOWLEDGEMENT, "units_per_em": 1000,
         "x_height": X_HEIGHT, "glyphs": glyphs},
        separators=(",", ":")) + "\n", encoding="utf-8")
    return FONT_FILE


def _sample(out: Path, text: str) -> None:
    """A page of it, to look at without running the whole film."""
    lines = strokes(text, width=418)
    paths = " ".join(
        "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in st) for st in lines)
    out.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="418" height="190">'
        f'<rect width="418" height="190" fill="#fff"/>'
        f'<path d="{paths}" fill="none" stroke="#d93025" stroke-width="2.2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>',
        encoding="utf-8")


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--take":
        print(f"{take()} written from Inkscape's font")
        return 0
    text = " ".join(argv) or "one model, not a fleet. say so."
    where = Path("/tmp/handwriting.svg")
    _sample(where, text)
    print(f"{where}: {len(strokes(text, width=418))} strokes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
