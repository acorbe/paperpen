#!/usr/bin/env python3
# Mark up a paper: put every comment in a widened right-hand strip, level with
# the line it is about, joined to it by a leader that never runs diagonally.
# This is the house format for annotating a manuscript; see "Annotating a paper"
# in CLAUDE.md.
#
#   scripts/annotate-paper.py <paper.pdf> <notes> <out.pdf> [--sticky]
#
# <notes> is either a .json file holding a list of [page, anchor, comment], or a
# .py file defining a list called NOTES of (page, anchor, comment) tuples.
#   page    1-based page the anchor is expected on; the whole document is
#           searched as a fallback, so an approximate hint is fine
#   anchor  a phrase copied verbatim out of the PDF's own text layer, 5 to 12
#           words, unique enough not to match in three places
#   comment starts with "SCIENCE: " or "LANGUAGE: " (amber and blue), or any
#           other "WORD: " prefix, which is drawn in grey
#
# --sticky writes the other form instead: the page at its original size with
# clickable sticky notes, for marking up further in a PDF reader.

import os
import sys

import pymupdf

MARGIN = 336.0        # width of the strip added on the right, in points
GUTTER = 22.0         # the leaders live in this band, between page and strip
PAD = 8.0
SIZE = 7.0
LEAD = 8.6
GAP = 9.0             # least vertical space between two notes
TOP = 22.0

# 27 of the notes carry Greek or maths characters. The base-14 fonts are
# Latin-1 only and would silently turn tau and Delta into dots.
FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_FILE_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
HAVE_DEJAVU = os.path.exists(FONT_FILE) and os.path.exists(FONT_FILE_B)
FONT = "note" if HAVE_DEJAVU else "helv"
FONT_B = "noteb" if HAVE_DEJAVU else "hebo"

SCIENCE = (0.86, 0.52, 0.02)
LANGUAGE = (0.11, 0.40, 0.72)
HL_SCIENCE = (1.0, 0.88, 0.55)
HL_LANGUAGE = (0.72, 0.86, 0.99)
LEADER = 0.45         # line width

_METRICS = [None]


def metrics():
    if _METRICS[0] is None:
        _METRICS[0] = pymupdf.Font(fontfile=FONT_FILE) if HAVE_DEJAVU else pymupdf.Font("helv")
    return _METRICS[0]


OTHER = (0.35, 0.35, 0.35)
HL_OTHER = (0.88, 0.88, 0.86)


def load_notes(path):
    """A .json list of [page, anchor, comment], or a .py defining NOTES."""
    if path.endswith(".json"):
        import json
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        ns = {}
        with open(path, encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), ns)
        if "NOTES" not in ns:
            raise SystemExit("%s defines no NOTES list" % path)
        raw = ns["NOTES"]
    notes = []
    for i, entry in enumerate(raw):
        if len(entry) != 3:
            raise SystemExit("note %d has %d fields, expected 3" % (i + 1, len(entry)))
        page, anchor, comment = entry
        notes.append((int(page), str(anchor), str(comment)))
    return notes


def kind_of(text):
    head = text.split(":", 1)[0]
    return head if head.isupper() and head.isalpha() and len(head) <= 12 else "NOTE"


def color_of(kind):
    return {"SCIENCE": SCIENCE, "LANGUAGE": LANGUAGE}.get(kind, OTHER)


def highlight_of(kind):
    return {"SCIENCE": HL_SCIENCE, "LANGUAGE": HL_LANGUAGE}.get(kind, HL_OTHER)


def strip_prefix(text):
    kind = kind_of(text)
    return text.split(":", 1)[1].strip() if kind != "NOTE" or text.startswith("NOTE:") else text


def wrap(text, width, size=SIZE):
    font = metrics()
    lines = []
    for para in text.split("\n"):
        line = ""
        for w in para.split():
            trial = w if not line else line + " " + w
            if font.text_length(trial, fontsize=size) <= width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = w
        lines.append(line)
    return lines


def locate(doc, page_hint, phrase):
    hinted = doc[min(max(page_hint, 1), doc.page_count) - 1]
    quads = hinted.search_for(phrase)
    if quads:
        return hinted.number, quads[0]
    for page in doc:
        quads = page.search_for(phrase)
        if quads:
            return page.number, quads[0]
    return hinted.number, None


def text_right_edge(page, cap):
    """Right edge of the body text, so a leader never crosses a word."""
    right = 0.0
    for block in page.get_text("blocks"):
        if len(block) > 6 and block[6] == 0:      # 0 is a text block
            right = max(right, block[2])
    return min(max(right, cap - 90.0), cap)


def place(desired, heights, top, bottom, gap=GAP):
    """Put each note as near its own line as it can go, order preserved.

    Forward sweep pushes overlaps down; if that runs off the bottom, a backward
    sweep pulls the tail up, then a second forward sweep repairs the head. The
    result is the smallest-displacement stacking that keeps the sequence.
    """
    n = len(desired)
    y = [0.0] * n
    cur = top
    for i in range(n):
        y[i] = max(desired[i], cur)
        cur = y[i] + heights[i] + gap
    if n and y[-1] + heights[-1] > bottom:
        cur = bottom
        for i in range(n - 1, -1, -1):
            y[i] = min(y[i], cur - heights[i])
            cur = y[i] - gap
        cur = top
        for i in range(n):
            y[i] = max(y[i], cur)
            cur = y[i] + heights[i] + gap
    return y


def register(page):
    if HAVE_DEJAVU:
        page.insert_font(fontname=FONT, fontfile=FONT_FILE)
        page.insert_font(fontname=FONT_B, fontfile=FONT_FILE_B)


def sticky(src, dst, NOTES):
    """The other form: original page size, clickable sticky notes."""
    doc = pymupdf.open(src)
    missing = 0
    for hint, phrase, text in NOTES:
        pno, rect = locate(doc, hint, phrase)
        page = doc[pno]
        kind = kind_of(text)
        if rect is not None:
            hl = page.add_highlight_annot(rect)
            hl.set_colors(stroke=highlight_of(kind))
            hl.update()
            point = pymupdf.Point(page.rect.width - 40, max(rect.y0 - 4, 24))
        else:
            missing += 1
            point = pymupdf.Point(page.rect.width - 40, 40)
        note = page.add_text_annot(point, text, icon="Comment")
        note.set_info(title="Notes")
        note.update()
    doc.save(dst, garbage=3, deflate=True)
    print("%d sticky notes -> %s" % (len(NOTES), dst))
    if missing:
        print("  %d anchor(s) not found, placed in the top margin" % missing)


def main(src, dst, NOTES):
    doc = pymupdf.open(src)
    if not HAVE_DEJAVU:
        print("warning: DejaVu not found, Greek and maths characters will be lost")

    # resolve every anchor, then order the notes as they are read: down the
    # page, and left to right within a line
    resolved = []
    for hint, phrase, text in NOTES:
        pno, rect = locate(doc, hint, phrase)
        resolved.append((pno, rect, text, phrase))
    resolved.sort(key=lambda r: (r[0],
                                 round(r[1].y0, 1) if r[1] is not None else 0.0,
                                 r[1].x0 if r[1] is not None else 0.0))

    per_page = {}
    for num, (pno, rect, text, phrase) in enumerate(resolved, start=1):
        per_page.setdefault(pno, []).append((num, rect, text, phrase))

    out = pymupdf.open()
    offsets = []
    for pno in range(doc.page_count):
        src_page = doc[pno]
        W, H = src_page.rect.width, src_page.rect.height
        items = per_page.get(pno, [])

        page = out.new_page(width=W + MARGIN, height=H)
        register(page)
        page.show_pdf_page(pymupdf.Rect(0, 0, W, H), doc, pno)
        page.draw_rect(pymupdf.Rect(W, 0, W + MARGIN, H), color=None, fill=(0.985, 0.985, 0.97))
        page.draw_line(pymupdf.Point(W, 0), pymupdf.Point(W, H), color=(0.82, 0.82, 0.79), width=0.5)
        if not items:
            continue

        edge = text_right_edge(src_page, W - 10.0)
        x_text = W + GUTTER + PAD                  # left edge of the note text
        width = W + MARGIN - PAD - x_text

        bodies = [wrap(strip_prefix(t), width) for _, _, t, _ in items]
        heights = [LEAD + len(b) * LEAD for b in bodies]
        # the note wants its heading level with the top of its anchor line
        desired = [(r.y0 - 1.0 if r is not None else TOP) for _, r, _, _ in items]
        desired = [min(max(d, TOP), H - TOP - h) for d, h in zip(desired, heights)]
        ys = place(desired, heights, TOP, H - TOP)

        for k, ((num, rect, text, _), body, h, y) in enumerate(zip(items, bodies, heights, ys)):
            kind = kind_of(text)
            col = color_of(kind)

            if rect is not None:
                hl = page.add_highlight_annot(rect)
                hl.set_colors(stroke=highlight_of(kind))
                hl.update()
                page.insert_text(pymupdf.Point(min(rect.x1 + 1.5, W - 9), rect.y1 - 0.5),
                                 str(num), fontname=FONT_B, fontsize=5.5, color=col)

                y_anchor = (rect.y0 + rect.y1) / 2.0
                y_note = y + LEAD * 0.55           # middle of the heading line
                lane = W + 5.0 + (k % 3) * 5.0     # three lanes, so no two
                                                   # verticals sit on top of
                                                   # each other
                page.draw_line(pymupdf.Point(edge + 3.0, y_anchor),
                               pymupdf.Point(lane, y_anchor), color=col, width=LEADER)
                offsets.append(abs(y_note - y_anchor))
                if abs(y_note - y_anchor) >= 0.5:
                    page.draw_line(pymupdf.Point(lane, y_anchor),
                                   pymupdf.Point(lane, y_note), color=col, width=LEADER)
                page.draw_line(pymupdf.Point(lane, y_note),
                               pymupdf.Point(x_text - 3.0, y_note), color=col, width=LEADER)

            page.insert_text(pymupdf.Point(x_text, y + LEAD - 2), "%d  %s" % (num, kind),
                             fontname=FONT_B, fontsize=SIZE, color=col)
            yy = y + LEAD
            for ln in body:
                yy += LEAD
                page.insert_text(pymupdf.Point(x_text, yy - 2), ln,
                                 fontname=FONT, fontsize=SIZE, color=(0.1, 0.1, 0.1))

    out.save(dst, garbage=3, deflate=True)
    import collections
    kinds = collections.Counter(kind_of(t) for _, _, t, _ in resolved)
    print("%d notes over %d pages -> %s" % (len(resolved), doc.page_count, dst))
    print("  " + ", ".join("%s %d" % (k.lower(), n) for k, n in sorted(kinds.items())))
    lost = sum(1 for _, r, _, _ in resolved if r is None)
    if lost:
        print("  %d anchor(s) not found in the pdf, shown without a leader" % lost)
    if offsets:
        offsets.sort()
        within = lambda t: sum(1 for o in offsets if o <= t)
        print("  vertical displacement from the anchor line, in points:")
        print("    median %.1f, 90th percentile %.1f, worst %.1f"
              % (offsets[len(offsets) // 2], offsets[int(len(offsets) * 0.9)], offsets[-1]))
        print("    within one line (8.6 pt): %d of %d; within three lines: %d"
              % (within(8.6), len(offsets), within(25.8)))


def cli(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}
    if len(args) != 3:
        raise SystemExit(__doc__ or
                         "usage: annotate-paper.py <paper.pdf> <notes> <out.pdf> [--sticky]")
    paper, notes_path, out = args
    notes = load_notes(notes_path)
    print("%d notes from %s" % (len(notes), notes_path))
    if "--sticky" in flags:
        sticky(paper, out, notes)
    else:
        main(paper, out, notes)


if __name__ == "__main__":
    cli(sys.argv[1:])
