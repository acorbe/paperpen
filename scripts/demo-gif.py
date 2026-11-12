#!/usr/bin/env python3
"""Frames plus their captions, as one looping GIF.

The generic half of the demo: it does not know what it is filming. It takes a
directory holding PNGs and a `frames.json` saying what each one is and how long
to hold it, fits every frame into one canvas, sets the caption in a strip
underneath, and writes the GIF.

    scripts/demo-gif.py <frames-dir> <out.gif> [--width 1100] [--colors 192]

A caption is a sentence somebody could say out loud. Two lines is the most that
can be read in the time a frame is held, so a longer one is an error rather
than something to shrink the type for.

A frame may also say where the pointer was, and what was holding it:

    {"png": "04.png", "caption": "...", "hold": 0.06,
     "pointer": {"at": [820, 410], "kind": "mouse"}}

which is drawn on top. It is a picture of a position the driver really
dispatched events to, not an invention: a film of a program being used should
show the thing doing the using. Several frames may name the same PNG, which is
what a pointer crossing a page that is not changing costs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PAGE_BG = (238, 241, 245)
STRIP_BG = (23, 43, 77)
STRIP_FG = (255, 255, 255)
STRIP_PAD = 16
CAPTION_SIZE = 21
CAPTION_LINES = 2


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_B if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def wrap(text: str, face, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = word if not line else f"{line} {word}"
        if face.getlength(trial) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit(image: Image.Image, box: tuple[int, int]):
    """Every frame on the same canvas, whatever shape it arrived in: a browser
    window and a PDF page are not the same proportions and a GIF has one size.

    Hands back how the frame was placed as well, so that a point in the frame's
    own coordinates can be found again on the canvas.
    """
    canvas = Image.new("RGB", box, PAGE_BG)
    scale = min(box[0] / image.width, box[1] / image.height)
    small = image.resize((max(1, round(image.width * scale)),
                          max(1, round(image.height * scale))), Image.LANCZOS)
    offset = ((box[0] - small.width) // 2, (box[1] - small.height) // 2)
    canvas.paste(small, offset)
    return canvas, scale, offset


# A pointer drawn twice: a pale outline under a dark body, so that it is found
# on a white page and on a dark one without being told which it is on.
ARROW = [(0, 0), (0, 17), (4.2, 12.9), (7.1, 19), (9.6, 17.9), (6.8, 12),
         (11.6, 11.6)]
# A pen is held with its tip on the paper and its body up and to the right,
# so that is where the body goes: the point is the position, not the middle.
NIB = [(0, 0), (5.0, -8.4), (8.4, -5.0)]
NIB_SHAFT = [(6.2, -6.2), (19, -19)]


def draw_pointer(frame: Image.Image, at: tuple[float, float], kind: str) -> None:
    draw = ImageDraw.Draw(frame)
    x, y = at
    if kind == "pen":
        body = [(x + dx, y + dy) for dx, dy in NIB]
        shaft = [(x + dx, y + dy) for dx, dy in NIB_SHAFT]
        draw.line(shaft, fill=(255, 255, 255), width=7, joint="curve")
        draw.line(shaft, fill=(120, 26, 22), width=4, joint="curve")
        draw.polygon(body, fill=(217, 48, 37), outline=(255, 255, 255))
        return
    body = [(x + dx, y + dy) for dx, dy in ARROW]
    draw.polygon(body, fill=(255, 255, 255))
    draw.line([*body, body[0]], fill=(255, 255, 255), width=5, joint="curve")
    draw.polygon(body, fill=(28, 33, 43))


def one_palette(frames: list[Image.Image], colors: int) -> Image.Image:
    """One palette for the whole film, taken from a little of every frame.

    Quantising each frame on its own gives each its own colours, and then no
    two frames are comparable and every one of them has to be written out
    whole. Sharing a palette is what lets a frame where only the pointer moved
    cost a few hundred bytes instead of forty thousand.
    """
    # Subsampled, not smoothed. Two pixels of red ink on white average out to
    # pink under any resampling worth the name, and a palette chosen from that
    # has no red in it: the handwriting came out grey. NEAREST keeps the
    # colours that are actually on the screen, which is the only thing the
    # palette is being asked about.
    thumbs = [f.resize((f.width // 2, f.height // 2), Image.NEAREST) for f in frames]
    sheet = Image.new("RGB", (thumbs[0].width, sum(t.height for t in thumbs)))
    y = 0
    for t in thumbs:
        sheet.paste(t, (0, y))
        y += t.height
    return sheet.quantize(colors=colors, method=Image.MEDIANCUT)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=1100)
    # 192, not 128: at 128 the median cut spends its colours on the greys of
    # a page of type and the red ink comes back brick brown, and the ink is
    # the thing the film is about.
    ap.add_argument("--colors", type=int, default=192)
    args = ap.parse_args(argv)

    where = Path(args.frames)
    spec = json.loads((where / "frames.json").read_text(encoding="utf-8"))
    if not spec:
        print("no frames", file=sys.stderr)
        return 1

    # several frames may name the same PNG, and a film that moves names it a
    # lot: it is opened once
    seen: dict[str, Image.Image] = {}
    for f in spec:
        seen.setdefault(f["png"], Image.open(where / f["png"]).convert("RGB"))
    images = [seen[f["png"]] for f in spec]
    # The shape most of the frames share sets the canvas, so those fill it
    # exactly and the odd one out sits inside with a margin. Taking the widest
    # or the tallest instead lets a single frame of another shape shrink all
    # the rest, which is what happens when one frame is a PDF page.
    shapes = Counter(round(i.width / i.height, 3) for i in images)
    shape = shapes.most_common(1)[0][0]
    box = (args.width, round(args.width / shape))

    face = font(CAPTION_SIZE)
    captions = [wrap(f["caption"], face, box[0] - 2 * STRIP_PAD) for f in spec]
    too_long = [c for c, f in zip(captions, spec) if len(c) > CAPTION_LINES]
    if too_long:
        print(f"a caption runs to {max(len(c) for c in too_long)} lines; "
              f"say it in {CAPTION_LINES}:\n  " + " ".join(too_long[0]), file=sys.stderr)
        return 1
    line_h = CAPTION_SIZE + 7
    strip = 2 * STRIP_PAD + CAPTION_LINES * line_h

    out = []
    for image, lines, f in zip(images, captions, spec):
        frame = Image.new("RGB", (box[0], box[1] + strip), STRIP_BG)
        placed, scale, offset = fit(image, box)
        frame.paste(placed, (0, 0))
        pointer = f.get("pointer")
        if pointer:
            draw_pointer(frame, (offset[0] + pointer["at"][0] * scale,
                                 offset[1] + pointer["at"][1] * scale),
                         pointer.get("kind", "mouse"))
        draw = ImageDraw.Draw(frame)
        y = box[1] + STRIP_PAD + (CAPTION_LINES - len(lines)) * line_h // 2
        for line in lines:
            draw.text(((box[0] - face.getlength(line)) / 2, y), line,
                      font=face, fill=STRIP_FG)
            y += line_h
        out.append(frame)

    palette = one_palette(out, args.colors)
    out = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in out]

    # disposal 1 leaves the last frame standing and lets the encoder write only
    # what changed, which is the whole reason the palette is shared
    out[0].save(args.out, save_all=True, append_images=out[1:],
                duration=[int(f["hold"] * 1000) for f in spec],
                loop=0, optimize=True, disposal=1)
    size = Path(args.out).stat().st_size
    print(f"{len(out)} frames, {sum(f['hold'] for f in spec):.1f}s, "
          f"{box[0]}x{box[1] + strip} -> {args.out} ({size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
