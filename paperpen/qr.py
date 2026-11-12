"""A QR code for the address, because the alternative is reading an IP aloud.

Connecting a tablet to this means typing `https://198.51.100.24:8770/` on a
glass keyboard, and getting it wrong once. A QR code on the terminal is
pointed at with the camera and the tablet opens the reader.

Drawn with half-block characters, two rows of modules per line of text, so a
version-3 code fits in a normal terminal. The quiet zone is not decoration:
scanners want four modules of margin and will sit there failing without it.

`segno` is a pure-Python encoder with no dependencies of its own. QR is a real
specification with Reed-Solomon and mask selection in it, and a hand-rolled
encoder that is subtly wrong produces a picture that simply does not scan,
which is the worst kind of wrong to debug on a tablet.
"""

from __future__ import annotations

QUIET = 4

# Two vertical modules per character cell. Dark is drawn light-on-dark or the
# other way about depending on the terminal, so both are offered and the
# default is the one that works on the dark terminals most people have.
FULL, UPPER, LOWER, BLANK = "█", "▀", "▄", " "


def matrix(text: str, error: str = "m") -> list[list[int]]:
    """The modules, 1 for dark, with the quiet zone already around them."""
    import segno

    code = segno.make(text, error=error)
    rows = [[1 if m else 0 for m in row] for row in code.matrix]
    width = len(rows[0]) + 2 * QUIET
    pad = [[0] * width for _ in range(QUIET)]
    return pad + [[0] * QUIET + r + [0] * QUIET for r in rows] + pad


def to_text(text: str, error: str = "m", invert: bool = False) -> str:
    """The code as lines of text, two module-rows per line.

    `invert` swaps dark and light, for a terminal with a light background:
    a QR scanner wants dark modules on a light field, and on a dark terminal
    the blocks *are* the light field, which is why the default draws it the
    way it does.
    """
    rows = matrix(text, error)
    if len(rows) % 2:
        rows.append([0] * len(rows[0]))
    dark, light = (BLANK, FULL) if invert else (FULL, BLANK)
    out = []
    for top, bottom in zip(rows[::2], rows[1::2]):
        line = []
        for a, b in zip(top, bottom):
            if a and b:
                line.append(dark)
            elif a:
                line.append(UPPER if not invert else LOWER)
            elif b:
                line.append(LOWER if not invert else UPPER)
            else:
                line.append(light)
        out.append("".join(line))
    return "\n".join(out)


def to_svg(text: str, error: str = "m", size: int = 8) -> str:
    """The same code as an SVG, for a page rather than a terminal."""
    rows = matrix(text, error)
    side = len(rows[0]) * size
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" '
             f'height="{side}" viewBox="0 0 {len(rows[0])} {len(rows)}" '
             f'shape-rendering="crispEdges">',
             f'<rect width="{len(rows[0])}" height="{len(rows)}" fill="#fff"/>']
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if not row[x]:
                x += 1
                continue
            run = x
            while run < len(row) and row[run]:
                run += 1
            parts.append(f'<rect x="{x}" y="{y}" width="{run - x}" height="1"/>')
            x = run
    parts.append("</svg>")
    return "".join(parts)


def available() -> bool:
    try:
        import segno  # noqa: F401
        return True
    except ImportError:
        return False


def show(text: str, invert: bool = False) -> str:
    """The code, or a plain sentence when the encoder is not installed."""
    if not available():
        return (f"    {text}\n"
                f"    (`pip install segno` and this becomes a QR code to point "
                f"a camera at)")
    return to_text(text, invert=invert)
