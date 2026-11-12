#!/usr/bin/env python3
# The paper reader's engine: build a LaTeX paper together with its SyncTeX map,
# render its pages, anchor a note to the source line it actually belongs to,
# and write a reading session back into the paper's own repo as feedback for
# the next pass.
#
#   scripts/paper.py list
#   scripts/paper.py add <repo> [--main x.tex] [--name ...] [--task ...]
#   scripts/paper.py check <repo>                      # is it postable?
#   scripts/paper.py howto                             # print PAPERS.md
#   scripts/paper.py build <paper> [--force]
#   scripts/paper.py meta <paper>                      # JSON for the board
#   scripts/paper.py render <paper> <page> [--scale 2]
#   scripts/paper.py layout <paper> <page>             # its sentences, words, figures
#   scripts/paper.py anchor <paper> <page> <x0> <y0> <x1> <y1>
#   scripts/paper.py note <paper> --json '{...}'       # add or replace one
#   scripts/paper.py drop <paper> <note-id>
#   scripts/paper.py notes <paper> [--json]
#   scripts/paper.py export <paper> [--no-commit]
#   scripts/paper.py classify <paper> <note-id> <SCIENCE|LANGUAGE|QUESTION|TODO>
#   scripts/paper.py resolve <paper> <note-id> <done|rejected|open> ["what was done"]
#
# <paper> is an entry of papers.json at the repo root, by its slug or any
# unique substring of it.
#
# The anchor is the point of all this. SyncTeX maps a place on the page back to
# the exact file and line of LaTeX that produced it, so a note made with a pen
# on a tablet arrives at the next pass as "sec_intro.tex:53, about this
# sentence, do that", which is what a revision actually needs. The text under
# the note is quoted alongside, because a line number drifts as the source is
# edited and the sentence does not.
#
# Nothing here leaves the machine: the build is local TeX, the rendering is
# local PyMuPDF, and the output is a commit in the paper's own repository.

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

try:
    import pymupdf
except ImportError:  # the package was called fitz before 1.24
    import fitz as pymupdf

ROOT = Path(__file__).resolve().parent.parent
PAPERS_FILE = ROOT / "papers.json"
# What a paper's own repository needs to know, kept here and read from here:
# this repo never writes instructions into somebody else's checkout.
HOWTO = ROOT / "PAPERS.md"


def howto_path() -> Path:
    """Where to tell somebody else to read it: the main checkout, because a
    worktree is temporary and a path in someone's notes should not be."""
    return board_home() / "PAPERS.md"
# AUTO is the default and means the owner did not say: the pass that reads the
# notes decides the class and records it with `paper.py classify`. Making him
# choose one at the moment of writing is the wrong moment to ask.
TAGS = ("AUTO", "SCIENCE", "LANGUAGE", "QUESTION", "TODO")
STATUSES = ("open", "done", "rejected")
DEFAULT_SCALE = 2.0
INK_PAD = 18.0  # points of page kept around a handwritten note in its crop


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def slugify(text: str) -> str:
    """A short id that reads as words: it is typed into commands by hand."""
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")
    if len(slug) > 40:
        slug = slug[:40].rsplit("-", 1)[0]  # never cut a word in half
    return slug.strip("-")


def board_home() -> Path:
    """The main checkout of this repo, which is the path to put in another
    repository's instructions: a worktree is temporary and its path is not."""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):])
    return ROOT


def git(*args: str, cwd: Path | None = None) -> str:
    """A git command whose failure is not fatal here."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd or ROOT), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def cache_root() -> Path:
    """Built PDFs and rendered pages, in the shared git directory: one path
    from every worktree, and nothing that could ever be committed."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return (Path(common) if common else ROOT / ".git") / "papers"


@dataclass
class Paper:
    pid: str
    name: str
    repo: Path
    main: str
    build: str = ""
    task: str = ""
    notes: str = ""      # a Claude-written note set to show alongside, optional

    @property
    def cache(self) -> Path:
        return cache_root() / self.pid

    @property
    def is_pdf(self) -> bool:
        """A paper we were handed as a PDF, with no LaTeX source to point at."""
        return Path(self.main).suffix.lower() == ".pdf"

    @property
    def pdf(self) -> Path:
        return self.cache / (Path(self.main).stem + ".pdf")

    @property
    def synctex(self) -> Path:
        return self.cache / (Path(self.main).stem + ".synctex.gz")

    @property
    def session(self) -> Path:
        return self.cache / "session.json"

    @property
    def review(self) -> Path:
        return self.repo / "review"


def load_papers() -> list[Paper]:
    if not PAPERS_FILE.is_file():
        return []
    try:
        raw = json.loads(PAPERS_FILE.read_text(encoding="utf-8"))
    except ValueError as e:
        die(f"papers.json is not valid JSON: {e}")
    out = []
    for entry in raw.get("papers", []):
        name = str(entry.get("name", "")).strip()
        repo = str(entry.get("repo", "")).strip()
        main = str(entry.get("main", "")).strip()
        if not (name and repo and main):
            continue  # a half-written entry is skipped, not fatal
        out.append(
            Paper(
                pid=str(entry.get("id") or slugify(name)),
                name=name,
                repo=Path(repo).expanduser(),
                main=main,
                build=str(entry.get("build", "")).strip(),
                task=str(entry.get("task", "")).strip(),
                notes=str(entry.get("notes", "")).strip(),
            )
        )
    return out


def resolve_paper(query: str) -> Paper:
    papers = load_papers()
    if not papers:
        die("no papers registered; add one to papers.json")
    hits = [p for p in papers if p.pid == query]
    if not hits:
        hits = [p for p in papers if query.lower() in p.pid or query.lower() in p.name.lower()]
    if len(hits) != 1:
        names = "\n".join(f"  {p.pid}  {p.name}" for p in papers)
        die(f"'{query}' matches {len(hits)} papers:\n{names}")
    return hits[0]


# --- building --------------------------------------------------------------

def cmd_build(paper: Paper, force: bool = False, prerender: bool = True) -> dict:
    """Compile with -synctex=1 into the cache, leaving the paper repo clean.

    latexmk by default: it settles the passes and the bibliography itself, and
    it takes -synctex, which a repo's own Makefile generally does not. `build`
    in papers.json overrides it for a paper that needs its own recipe.
    """
    if not paper.repo.is_dir():
        die(f"no such repo: {paper.repo}")
    src = paper.repo / paper.main
    if not src.is_file():
        die(f"no such main file: {src}")
    paper.cache.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".pdf":
        # a paper with no source here: a draft from a co-author, or one of this
        # repo's own annotated PDFs. No build, no source lines, everything else
        # the same, so it can still be read and marked up on the tablet.
        shutil.copy2(src, paper.pdf)
        if paper.synctex.exists():
            paper.synctex.unlink()
    elif paper.build:
        proc = subprocess.run(paper.build, shell=True, cwd=paper.repo,
                              capture_output=True, text=True, timeout=900)
        built = paper.repo / (Path(paper.main).stem + ".pdf")
        if not built.is_file():
            die(f"'{paper.build}' left no {built.name}:\n{proc.stdout[-1500:]}")
        shutil.copy2(built, paper.pdf)
        made = paper.repo / (Path(paper.main).stem + ".synctex.gz")
        if made.is_file():
            shutil.copy2(made, paper.synctex)
        elif paper.synctex.exists():
            paper.synctex.unlink()
    else:
        proc = subprocess.run(
            ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode",
             "-halt-on-error" if force else "-f", f"-outdir={paper.cache}", paper.main],
            cwd=paper.repo, capture_output=True, text=True, timeout=900,
        )
        if not paper.pdf.is_file():
            die(f"latexmk produced no PDF:\n{proc.stdout[-2000:]}")

    # the rendered pages belong to the build that made them
    for stale in ("pages", "text"):
        if (paper.cache / stale).is_dir():
            shutil.rmtree(paper.cache / stale)

    doc = pymupdf.open(paper.pdf)
    info = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "commit": git("rev-parse", "--short", "HEAD", cwd=paper.repo),
        "dirty": bool(git("status", "--porcelain", cwd=paper.repo)),
        "main": paper.main,
        "pages": doc.page_count,
        "sizes": [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in doc],
        "synctex": paper.synctex.is_file(),
    }
    doc.close()
    (paper.cache / "build.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    if prerender:
        # a quarter of a second a page here, against the same wait on the
        # tablet for every page as it is first swiped to
        for n in range(1, info["pages"] + 1):
            page_png(paper, n)
    return info


def build_info(paper: Paper) -> dict:
    try:
        return json.loads((paper.cache / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def source_moved(paper: Paper) -> bool:
    """Whether the sources have changed since the PDF on show was built."""
    info = build_info(paper)
    if not info:
        return True
    if paper.is_pdf:
        built = paper.pdf.stat().st_mtime if paper.pdf.is_file() else 0
        src = paper.repo / paper.main
        return src.is_file() and src.stat().st_mtime > built
    now = git("rev-parse", "--short", "HEAD", cwd=paper.repo)
    if info.get("commit") and now and info["commit"] != now:
        return True
    built = paper.pdf.stat().st_mtime if paper.pdf.is_file() else 0
    for tex in list(paper.repo.rglob("*.tex")) + list(paper.repo.rglob("*.bib")):
        if "/.git/" in str(tex):
            continue
        try:
            if tex.stat().st_mtime > built:
                return True
        except OSError:
            pass
    return False


# --- rendering -------------------------------------------------------------

def page_png(paper: Paper, page_no: int, scale: float = DEFAULT_SCALE) -> Path:
    """One page as a PNG, rendered once and kept. The tablet sees the PDF
    itself rendered, not a conversion of it, which is the whole point."""
    out = paper.cache / "pages" / f"{page_no:03d}@{scale:g}.png"
    if out.is_file():
        return out
    if not paper.pdf.is_file():
        die("nothing built yet; run: scripts/paper.py build <paper>")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(paper.pdf)
    if not 1 <= page_no <= doc.page_count:
        die(f"page {page_no} is outside 1..{doc.page_count}")
    pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    pix.save(out)
    doc.close()
    return out


# --- sentences: what a note is actually about ------------------------------
# A note anchored to "the line you tapped" is not what anyone means. The unit
# is the sentence, so the text layer is cut into sentences, each keeping the
# boxes it occupies (one per line it runs over, and a sentence in a two-column
# paper can run over several), and the reader hangs its notes on those.

# A full stop that does not end a sentence. Initials and single letters are
# caught separately: "A." is not the end of anything.
ABBREVIATIONS = {
    "fig", "figs", "eq", "eqs", "sec", "secs", "ref", "refs", "tab", "tabs",
    "al", "et", "e.g", "i.e", "cf", "vs", "resp", "approx", "ca", "no", "nos",
    "dr", "prof", "mr", "mrs", "ms", "st", "vol", "pp", "ch", "app",
}
SENTENCE_END = ".!?"


def ends_sentence(word: str, nxt: str | None) -> bool:
    """Whether this word closes a sentence, given what follows it."""
    stripped = word.rstrip(")]}\"'”’")
    if not stripped or stripped[-1] not in SENTENCE_END:
        return False
    if stripped[-1] == ".":
        stem = stripped[:-1].lower().lstrip("([{\"'“‘")
        if stem in ABBREVIATIONS:
            return False
        if len(stem) <= 1:
            return False  # an initial, or an enumerator like "1."
        if stem.replace(".", "").isdigit():
            return False  # a section number, "2.3."
    # a sentence does not end in the middle of a lower-case run
    if nxt and nxt[:1].islower():
        return False
    return True


def line_boxes(words: list) -> list[list[float]]:
    """One box per line the words run over, in reading order."""
    boxes: dict[tuple, list[float]] = {}
    order: list[tuple] = []
    for w in words:
        key = (w[5], w[6])
        if key not in boxes:
            boxes[key] = [w[0], w[1], w[2], w[3]]
            order.append(key)
        else:
            b = boxes[key]
            b[0], b[1] = min(b[0], w[0]), min(b[1], w[1])
            b[2], b[3] = max(b[2], w[2]), max(b[3], w[3])
    return [[round(v, 2) for v in boxes[k]] for k in order]


def page_sentences(paper: Paper, page_no: int) -> list[dict]:
    """The page's text as sentences, each with the boxes it occupies."""
    doc = pymupdf.open(paper.pdf)
    pages = doc.page_count
    if not 1 <= page_no <= pages:
        doc.close()
        die(f"page {page_no} is outside 1..{pages}")
    words = doc[page_no - 1].get_text("words")
    doc.close()
    words.sort(key=lambda w: (w[5], w[6], w[7]))

    out: list[dict] = []
    current: list = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        # a block is a paragraph, a heading, a caption: never run across one
        block_ends = nxt is None or nxt[5] != w[5]
        if block_ends or ends_sentence(w[4], nxt[4] if nxt else None):
            text = " ".join(x[4] for x in current).strip()
            text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)  # the PDF's line breaks
            if text:
                out.append({
                    "i": len(out),
                    "text": text,
                    "rects": line_boxes(current),
                })
            current = []
    return out


# --- figures, and the words themselves -------------------------------------
# A note can be about a whole sentence, a single word in it, or a figure. Each
# needs a different thing written down for the note to be traceable back to
# what was meant: a word is meaningless without the sentence around it, and a
# figure is known by its number, not by where it sits on the page.

# "Figure 3:" and "Table 1:" start a caption. "Table 2 reports the..." does
# not, which is why the separator is required.
CAPTION_RE = re.compile(r"^\s*(Figure|Fig\.?|Table)\s*([0-9]+[a-z]?)\s*[:.]", re.I)
PAGE_MARGIN = 36.0  # how far into the page a figure band may reach


def page_figures(paper: Paper, page_no: int) -> list[dict]:
    """The figures and tables on a page, each as a region that can be tapped.

    Found by their captions: most figures in a LaTeX paper are vector drawings
    with no image to ask about, but every one is captioned, and the caption is
    also the only name the figure has in the source.

    The band that can be tapped is the caption plus the artwork beside it, the
    images and vector drawings between this caption and the one before it. The
    extent comes from the artwork rather than from the surrounding text because
    a plot's own axis labels and arrows are text blocks too, and a band bounded
    by those stops at the caption and leaves the figure untappable. A band that
    reaches a little too far costs nothing: the reader tries sentences first,
    so a tap on a paragraph is still that paragraph's sentence.
    """
    doc = pymupdf.open(paper.pdf)
    page = doc[page_no - 1]
    blocks = [b for b in page.get_text("blocks") if (b[4] or "").strip()]
    art = []
    for info in page.get_images(full=True):
        art.extend([list(r) for r in page.get_image_rects(info[0])])
    try:
        art.extend([list(d["rect"]) for d in page.get_drawings()])
    except Exception:  # noqa: BLE001  a page whose vectors will not parse still works
        pass
    height = page.rect.height
    doc.close()

    def overlaps_x(a, b) -> bool:
        return min(a[2], b[2]) - max(a[0], b[0]) > 10

    caps = [(b, CAPTION_RE.match(b[4] or "")) for b in blocks]
    caps = [(b, m) for b, m in caps if m]
    out = []
    for cap, m in caps:
        is_table = m.group(1).lower().startswith("tab")
        label = f"{'Table' if is_table else 'Figure'} {m.group(2)}"
        # never reach past a neighbouring caption: two stacked figures are two
        others = [c for c, _ in caps if c is not cap and overlaps_x(c, cap)]
        if is_table:
            edge = min((c[1] for c in others if c[1] > cap[3]), default=height - PAGE_MARGIN)
            lo, hi = cap[3], edge
        else:
            edge = max((c[3] for c in others if c[3] < cap[1]), default=PAGE_MARGIN)
            lo, hi = edge, cap[1]
        band = [cap[0], cap[1], cap[2], cap[3]]
        for r in art:
            if (overlaps_x(r, cap) and r[1] >= lo - 2 and r[3] <= hi + 2
                    and r[2] - r[0] > 8 and r[3] - r[1] > 8):
                band = [min(band[0], r[0]), min(band[1], r[1]),
                        max(band[2], r[2]), max(band[3], r[3])]
        caption = re.sub(r"\s+", " ", (cap[4] or "").strip())
        out.append({
            "i": len(out),
            "label": label,
            "caption": caption,
            "rect": [round(v, 2) for v in band],
            "caption_rect": [round(v, 2) for v in (cap[0], cap[1], cap[2], cap[3])],
        })
    return out


def page_layout(paper: Paper, page_no: int) -> dict:
    """Everything the reader needs to know about a page to put a note on it:
    its sentences, its words, and its figures."""
    sentences = page_sentences(paper, page_no)
    doc = pymupdf.open(paper.pdf)
    words = doc[page_no - 1].get_text("words")
    doc.close()
    # which sentence each word belongs to, so a word note can quote the
    # sentence around it without asking the board again
    owner: dict[tuple, int] = {}
    for s in sentences:
        for r in s["rects"]:
            owner[(round(r[1], 1), round(r[3], 1), round(r[0], 1))] = s["i"]

    def sentence_of(w) -> int:
        best, gap = -1, 1e9
        for s in sentences:
            for r in s["rects"]:
                if (w[0] >= r[0] - 1 and w[2] <= r[2] + 1
                        and w[1] >= r[1] - 1 and w[3] <= r[3] + 1):
                    return s["i"]
                d = abs((w[1] + w[3]) / 2 - (r[1] + r[3]) / 2) + 0.2 * abs(w[0] - r[0])
                if d < gap:
                    best, gap = s["i"], d
        return best if gap < 8 else -1

    return {
        "sentences": sentences,
        "figures": page_figures(paper, page_no),
        "words": [
            {"t": w[4], "r": [round(w[0], 2), round(w[1], 2), round(w[2], 2), round(w[3], 2)],
             "s": sentence_of(w)}
            for w in words
        ],
    }


def layout_cached(paper: Paper, page_no: int) -> dict:
    """Worked out once per build and kept beside the rendered pages."""
    path = paper.cache / "text" / f"{page_no:03d}.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "words" in data:
                return data
        except ValueError:
            pass
    out = page_layout(paper, page_no)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# --- anchoring: where on the page, and where in the source -----------------

def synctex_edit(paper: Paper, page_no: int, x: float, y: float) -> dict:
    """The LaTeX file and line that produced this spot on the page.

    Coordinates are points from the page's top-left, which is what PyMuPDF
    reports and what SyncTeX expects: verified against this repo's own papers.
    """
    if not paper.synctex.is_file():
        return {}
    proc = subprocess.run(
        ["synctex", "edit", "-o", f"{page_no}:{x:.2f}:{y:.2f}:{paper.pdf.name}"],
        cwd=paper.cache, capture_output=True, text=True, timeout=30,
    )
    found: dict = {}
    for line in proc.stdout.splitlines():
        if line.startswith("Input:"):
            raw = Path(line[len("Input:"):].strip())
            try:
                found["file"] = str(raw.resolve().relative_to(paper.repo.resolve()))
            except ValueError:
                found["file"] = str(raw)
        elif line.startswith("Line:"):
            try:
                found["line"] = int(line[len("Line:"):].strip())
            except ValueError:
                pass
    return found if found.get("file") else {}


MAX_QUOTE = 45  # words: a quote is there to find the place again, not to copy it


def text_in_rects(paper: Paper, page_no: int, rects: list[list[float]]) -> str:
    """The exact words inside the boxes a selected sentence occupies.

    Read back from the PDF rather than trusted from the browser: the quote
    that goes into the notes is what the paper says, whatever was posted.
    """
    doc = pymupdf.open(paper.pdf)
    words = doc[page_no - 1].get_text("words")
    doc.close()
    boxes = [pymupdf.Rect(*r) for r in rects]
    picked = [w for w in words
              if any(pymupdf.Rect(w[:4]).intersects(b) for b in boxes)]
    picked.sort(key=lambda w: (w[5], w[6], w[7]))
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", " ".join(w[4] for w in picked).strip())


def text_under(paper: Paper, page_no: int, rect: list[float]) -> str:
    """The text a note sits on, quoted from the PDF's own text layer.

    Whole lines, in the reading order PyMuPDF's blocks give, because a paper in
    two columns interleaves nonsense if the words are sorted by position. A
    line number drifts as the source is edited; the sentence does not, so this
    quote is what makes a note findable after the paper has moved on.
    """
    doc = pymupdf.open(paper.pdf)
    page = doc[page_no - 1]
    words = page.get_text("words")
    box = pymupdf.Rect(*rect)
    if box.is_empty:
        box = pymupdf.Rect(box.x0 - 4, box.y0 - 4, box.x1 + 4, box.y1 + 4)
    touched = {(w[5], w[6]) for w in words if pymupdf.Rect(w[:4]).intersects(box)}
    if not touched:
        # nothing under it, so a note written in the margin still says what it
        # is about: the nearest line, weighted towards its own column
        centre = ((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        best, gap = None, 1e9
        for w in words:
            d = (abs((w[1] + w[3]) / 2 - centre[1])
                 + 0.35 * abs((w[0] + w[2]) / 2 - centre[0]))
            if d < gap:
                best, gap = w, d
        if best is not None:
            touched = {(best[5], best[6])}
    doc.close()
    out: list[str] = []
    for key in sorted(touched):
        line = sorted((w for w in words if (w[5], w[6]) == key), key=lambda w: w[7])
        out.extend(w[4] for w in line)
        if len(out) >= MAX_QUOTE:
            break
    quote = " ".join(out[:MAX_QUOTE]).strip()
    # the PDF breaks words across lines; the source does not, so a quote that
    # is going to be searched for in the .tex should not carry the break
    return re.sub(r"(\w)-\s+(\w)", r"\1\2", quote)


def bbox(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects)]


KINDS = ("sentence", "word", "figure", "region")


def word_context(paper: Paper, page_no: int, rects: list[list[float]]) -> tuple[str, str]:
    """The sentence a selected word sits in, and that sentence with the word
    marked in it. A note on one word says nothing on its own: what the next
    pass needs is which word, in which sentence."""
    boxes = [pymupdf.Rect(*r) for r in rects]
    for sent in page_sentences(paper, page_no):
        if not any(pymupdf.Rect(*sr).intersects(b) for sr in sent["rects"] for b in boxes):
            continue
        doc = pymupdf.open(paper.pdf)
        words = doc[page_no - 1].get_text("words")
        doc.close()
        inside = [w for w in words
                  if any(pymupdf.Rect(w[:4]).intersects(pymupdf.Rect(*sr))
                         for sr in sent["rects"])]
        inside.sort(key=lambda w: (w[5], w[6], w[7]))
        marked = []
        for w in inside:
            hit = any(pymupdf.Rect(w[:4]).intersects(b) for b in boxes)
            marked.append(f"**{w[4]}**" if hit else w[4])
        text = re.sub(r"(\w)-\s+(\w)", r"\1\2", " ".join(marked).strip())
        return sent["text"], text
    return "", ""


def figure_at(paper: Paper, page_no: int, rect: list[float]) -> dict:
    """The figure or table whose region a note was put in."""
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    for fig in page_figures(paper, page_no):
        r = fig["rect"]
        if r[0] - 2 <= cx <= r[2] + 2 and r[1] - 2 <= cy <= r[3] + 2:
            return fig
    return {}


def cmd_anchor(paper: Paper, page_no: int, rect: list[float],
               rects: list[list[float]] | None = None) -> dict:
    """Where a note sits: the words it is on, and the source line that made
    them. `rects` are the boxes of a selected sentence, one per line it runs
    over; without them the note is a point or a stroke and the text under it
    has to be guessed at."""
    if rects:
        rect = bbox(rects)
        anchor = text_in_rects(paper, page_no, rects)
    else:
        anchor = text_under(paper, page_no, rect)
    # the source line comes from the start of the selection, which is where the
    # sentence begins, rather than from the middle of a block of lines
    x = rect[0] + 2 if rects else (rect[0] + rect[2]) / 2
    y = (rects[0][1] + rects[0][3]) / 2 if rects else (rect[1] + rect[3]) / 2
    return {
        "page": page_no,
        "rect": [round(v, 2) for v in rect],
        "rects": [[round(v, 2) for v in r] for r in (rects or [])],
        "anchor": anchor,
        "source": synctex_edit(paper, page_no, x, y),
    }


def anchor_for(paper: Paper, page_no: int, kind: str, rect: list[float],
               rects: list[list[float]]) -> dict:
    """Everything that says what a note is about, worked out from the boxes it
    covers rather than taken from the browser, so the record is the paper's."""
    out = cmd_anchor(paper, page_no, rect, rects)
    out["kind"] = kind if kind in KINDS else "region"
    out["word"] = ""
    out["context"] = ""
    out["figure"] = ""
    if out["kind"] == "word" and rects:
        out["word"] = out["anchor"]
        sentence, marked = word_context(paper, page_no, rects)
        out["context"] = marked or sentence
    elif out["kind"] == "figure":
        fig = figure_at(paper, page_no, out["rect"])
        if fig:
            out["figure"] = fig["label"]
            out["anchor"] = fig["caption"]
            # the source line of a figure is the line of its caption, which is
            # inside the float in the LaTeX and is where its \label lives
            c = fig["caption_rect"]
            found = synctex_edit(paper, page_no, c[0] + 2, (c[1] + c[3]) / 2)
            if found:
                out["source"] = found
    return out


# --- notes -----------------------------------------------------------------

def read_session(paper: Paper) -> list[dict]:
    try:
        return json.loads(paper.session.read_text(encoding="utf-8")).get("notes", [])
    except (OSError, ValueError):
        return []


def write_session(paper: Paper, notes: list[dict]) -> None:
    paper.cache.mkdir(parents=True, exist_ok=True)
    tmp = paper.session.with_suffix(".tmp")
    tmp.write_text(json.dumps({"notes": notes}, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(paper.session)


def past_sessions(paper: Paper) -> list[dict]:
    """Every note from sessions already exported into the paper's repo."""
    out = []
    if not paper.review.is_dir():
        return out
    for nj in sorted(paper.review.glob("*/notes.json")):
        try:
            data = json.loads(nj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for note in data.get("notes", []):
            note["session"] = nj.parent.name
            out.append(note)
    return out


def next_id(paper: Paper) -> str:
    today = date.today().isoformat()
    taken = {n.get("id", "") for n in read_session(paper) + past_sessions(paper)}
    n = 1
    while f"{today}-{n:02d}" in taken:
        n += 1
    return f"{today}-{n:02d}"


def cmd_note(paper: Paper, data: dict) -> dict:
    """Add a note, or replace one that is still in the open session."""
    notes = read_session(paper)
    page_no = int(data.get("page", 1))
    rect = [float(v) for v in data.get("rect", [0, 0, 0, 0])]
    rects = [[float(v) for v in r] for r in (data.get("rects") or [])]
    note = {
        "id": str(data.get("id") or next_id(paper)),
        "page": page_no,
        "rect": [round(v, 2) for v in rect],
        "rects": [[round(v, 2) for v in r] for r in rects],
        "tag": (str(data.get("tag", "")).upper() or "AUTO"),
        "note": str(data.get("note", "")).strip(),
        # `ink` is drawn on the page itself, in page points: circles, strikes,
        # arrows. `hand` is written in the pad beside the sentence, in the
        # pad's own pixels, which is why `pad` records how big it was.
        "ink": data.get("ink") or [],
        "hand": data.get("hand") or [],
        "pad": data.get("pad") or [],
        "at": datetime.now().isoformat(timespec="seconds"),
        "status": "open",
        "response": "",
    }
    if note["tag"] not in TAGS:
        note["tag"] = "AUTO"
    if not note["note"] and not note["ink"] and not note["hand"]:
        die("a note needs words, or ink, or something written in the pad")
    if note["ink"] and (rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0):
        # ink with no rectangle anchors itself to where it was drawn
        xs = [float(p[0]) for st in note["ink"] for p in st if len(p) >= 2]
        ys = [float(p[1]) for st in note["ink"] for p in st if len(p) >= 2]
        if xs and ys:
            rect = [min(xs), min(ys), max(xs), max(ys)]
            note["rect"] = [round(v, 2) for v in rect]
    anchored = anchor_for(paper, page_no, str(data.get("kind", "")), rect, rects)
    for field in ("rect", "rects", "anchor", "source", "kind", "word", "context", "figure"):
        note[field] = anchored[field]
    notes = [n for n in notes if n.get("id") != note["id"]]
    notes.append(note)
    notes.sort(key=lambda n: (n.get("page", 0), n.get("rect", [0, 0])[1]))
    write_session(paper, notes)
    return note


def cmd_drop(paper: Paper, note_id: str) -> dict:
    notes = read_session(paper)
    kept = [n for n in notes if n.get("id") != note_id]
    if len(kept) == len(notes):
        die(f"no open note {note_id}")
    write_session(paper, kept)
    return {"dropped": note_id}


# --- export: the session, as feedback, in the paper's own repo -------------

HAND_SCALE = 0.62   # pad pixels to points, so a written note reads at page size


def hand_block(note: dict) -> tuple[list[list[list[float]]], float, float]:
    """The pad's strokes, moved to their own origin, and the size they need."""
    strokes = note.get("hand") or []
    pts = [p for st in strokes for p in st if len(p) >= 2]
    if not pts:
        return [], 0.0, 0.0
    x0 = min(p[0] for p in pts)
    y0 = min(p[1] for p in pts)
    x1 = max(p[0] for p in pts)
    y1 = max(p[1] for p in pts)
    moved = [[[(p[0] - x0) * HAND_SCALE, (p[1] - y0) * HAND_SCALE] for p in st]
             for st in strokes]
    return moved, (x1 - x0) * HAND_SCALE, (y1 - y0) * HAND_SCALE


def ink_crop(paper: Paper, note: dict, out: Path) -> bool:
    """One image holding the handwriting and what it is about.

    The page where the note was made goes on top, with any marks drawn on the
    page itself; what was written in the pad goes underneath, at the size it
    was written. A pass reads this and transcribes it, which is deliberately a
    reading job rather than an OCR service, because nothing here leaves the
    machine.
    """
    if not note.get("ink") and not note.get("hand"):
        return False
    doc = pymupdf.open(paper.pdf)
    page = doc[note["page"] - 1]
    box = list(note["rect"])
    for stroke in note["ink"]:
        pts = [pymupdf.Point(float(p[0]), float(p[1])) for p in stroke if len(p) >= 2]
        if len(pts) == 1:
            page.draw_circle(pts[0], 1.2, color=(0.85, 0.1, 0.1), fill=(0.85, 0.1, 0.1))
        elif pts:
            page.draw_polyline(pts, color=(0.85, 0.1, 0.1), width=1.6)
        # by hand, because a rect of zero area is empty and unions away to
        # nothing: the crop has to hold the ink and whatever it is about, which
        # are often at opposite ends of the page
        for pt in pts:
            box = [min(box[0], pt.x), min(box[1], pt.y),
                   max(box[2], pt.x), max(box[3], pt.y)]
    box = pymupdf.Rect(*box)
    clip = pymupdf.Rect(box.x0 - INK_PAD, box.y0 - INK_PAD,
                        box.x1 + INK_PAD, box.y1 + INK_PAD) & page.rect
    out.parent.mkdir(parents=True, exist_ok=True)
    strip = page.get_pixmap(matrix=pymupdf.Matrix(2.6, 2.6), clip=clip)
    doc.close()

    hand, hw, hh = hand_block(note)
    if not hand:
        strip.save(out)
        return True

    # the page strip above, the handwriting below it, in one image
    gap, margin = 14.0, 10.0
    sw, sh = strip.width / 2.6, strip.height / 2.6
    width = max(sw, hw + 2 * margin)
    sheet = pymupdf.open()
    board = sheet.new_page(width=width, height=sh + gap + hh + 2 * margin)
    board.draw_rect(board.rect, color=None, fill=(1, 1, 1))
    board.insert_image(pymupdf.Rect(0, 0, sw, sh), pixmap=strip)
    board.draw_line(pymupdf.Point(margin, sh + gap / 2),
                    pymupdf.Point(width - margin, sh + gap / 2),
                    color=(0.75, 0.78, 0.83), width=0.8)
    top = sh + gap + margin
    for st in hand:
        pts = [pymupdf.Point(margin + p[0], top + p[1]) for p in st]
        if len(pts) == 1:
            board.draw_circle(pts[0], 1.1, color=(0.85, 0.1, 0.1), fill=(0.85, 0.1, 0.1))
        elif pts:
            board.draw_polyline(pts, color=(0.85, 0.1, 0.1), width=1.7)
    board.get_pixmap(matrix=pymupdf.Matrix(2.2, 2.2)).save(out)
    sheet.close()
    return True


def notes_md(paper: Paper, notes: list[dict], info: dict, session: str) -> str:
    counts: dict[str, int] = {}
    for n in notes:
        counts[n["tag"]] = counts.get(n["tag"], 0) + 1
    tally = ", ".join(
        f"{v} {'unclassified' if k == 'AUTO' else k.lower()}"
        for k, v in sorted(counts.items()))
    built = info.get("commit") or "an unrecorded commit"
    lines = [
        f"# Notes on {Path(paper.main).stem}, {session}",
        "",
        f"Read on the tablet from the build of {built} ({info.get('at', '?')}).",
        f"{len(notes)} note{'s' if len(notes) != 1 else ''}"
        + (f": {tally}." if tally else "."),
        "",
        "Each note gives the source line it is anchored to, what it is about,",
        "and what to do. A note on a word names the word and shows it in bold",
        "inside its own sentence; a note on a figure names the figure and",
        "quotes its caption; a note on a sentence quotes the sentence. The line",
        "number is from the build above and drifts as the source is edited, so",
        "the quoted text is what to search for.",
        "",
        "A note marked **unclassified** is one the owner did not put a class on,",
        "which is the default: decide whether it is SCIENCE, LANGUAGE, QUESTION",
        "or TODO from what it says, and record that with `paper.py classify`.",
        "",
        "Generated from `notes.json`, which is the record: edit that and run",
        "`paper.py classify` and `paper.py resolve` rather than hand-editing",
        "this file.",
        "",
        "What to do with these notes, and how this paper came to be read at all,",
        f"is written in `{howto_path()}`",
        f"(`{board_home()}/scripts/paper.py howto` prints it).",
        "",
    ]
    for i, n in enumerate(notes, start=1):
        where = n.get("source") or {}
        head = f"{where['file']}:{where['line']}" if where.get("file") else f"page {n['page']}"
        kind = n.get("kind") or "sentence"
        # What the note is about, said plainly enough that it can be found
        # again: a word is named and then shown inside its own sentence, a
        # figure is named by its number, a sentence is simply quoted.
        if kind == "word" and n.get("word"):
            about = f'the word "{n["word"]}"'
        elif kind == "figure" and n.get("figure"):
            about = n["figure"]
        else:
            about = ""
        lines.append("---")
        lines.append("")
        tag = "unclassified" if n["tag"] == "AUTO" else n["tag"]
        lines.append(f"## {i}. {head}  (page {n['page']})  {tag}"
                     + (f"  ·  {about}" if about else ""))
        lines.append("")
        if kind == "word" and n.get("context"):
            lines.append(f'The word **{n.get("word", "")}**, in this sentence:')
            lines.append("")
            lines.append(f"> {n['context']}")
            lines.append("")
        elif kind == "figure" and n.get("figure"):
            lines.append(f"**{n['figure']}**, whose caption reads:")
            lines.append("")
            lines.append(f"> {n['anchor']}")
            lines.append("")
        elif n.get("anchor"):
            lines.append(f"> {n['anchor']}")
            lines.append("")
        if n.get("note"):
            lines.append(n["note"])
            lines.append("")
        if n.get("ink") or n.get("hand"):
            if n.get("anchor"):
                lines.append(
                    f"Handwritten, about the text above: `ink/{n['id']}.png` shows the"
                    " strokes on the page with it. Read the image and write what it"
                    " says into this note before acting on it.")
            else:
                lines.append(
                    f"Handwritten: `ink/{n['id']}.png`. Read the image and write what"
                    " it says into this note before acting on it.")
            lines.append("")
        if n.get("status") and n["status"] != "open":
            lines.append(f"**{n['status'].capitalize()}**"
                         + (f": {n['response']}" if n.get("response") else ""))
            lines.append("")
        lines.append(f"<!-- id: {n['id']} -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_review(paper: Paper, notes: list[dict], session: str, info: dict,
                 fresh: set | None = None) -> Path:
    out = paper.review / session
    out.mkdir(parents=True, exist_ok=True)
    for n in notes:
        # with `fresh` given, a note from an earlier delivery of the day keeps
        # the image it was cropped with: it was made on another build, whose
        # page may have moved or be gone from the current one
        if fresh is not None and n["id"] not in fresh \
                and (out / "ink" / f"{n['id']}.png").exists():
            continue
        if n.get("ink") or n.get("hand"):
            ink_crop(paper, n, out / "ink" / f"{n['id']}.png")
    (out / "notes.json").write_text(
        json.dumps({"paper": paper.name, "main": paper.main, "session": session,
                    "build": info, "notes": notes}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "NOTES.md").write_text(notes_md(paper, notes, info, session), encoding="utf-8")
    return out


def cmd_export(paper: Paper, commit: bool = True) -> dict:
    notes = read_session(paper)
    if not notes:
        die("the open session has no notes")
    if not paper.repo.is_dir():
        die(f"no such repo: {paper.repo}")
    session = date.today().isoformat()
    fresh = {n["id"] for n in notes}
    # a second session on one day joins the first rather than overwriting it
    existing = paper.review / session / "notes.json"
    if existing.is_file():
        try:
            was = json.loads(existing.read_text(encoding="utf-8")).get("notes", [])
        except ValueError:
            was = []
        seen = {n["id"] for n in notes}
        notes = [n for n in was if n["id"] not in seen] + notes
        notes.sort(key=lambda n: (n.get("page", 0), n.get("rect", [0, 0])[1]))
    out = write_review(paper, notes, session, build_info(paper), fresh=fresh)
    result = {"written": str(out), "notes": len(notes), "committed": False}
    if commit and (paper.repo / ".git").exists():
        rel = str(out.relative_to(paper.repo))
        git("add", "--", rel, cwd=paper.repo)
        proc = subprocess.run(
            ["git", "-C", str(paper.repo), "commit", "-m",
             f"review {session}: {len(notes)} notes from the tablet", "--", rel],
            capture_output=True, text=True,
        )
        result["committed"] = proc.returncode == 0
        result["git"] = (proc.stdout + proc.stderr).strip()[-400:]
    write_session(paper, [])
    return result


def cmd_classify(paper: Paper, note_id: str, tag: str) -> dict:
    """Record the class a pass decided for a note the owner left on AUTO."""
    tag = tag.upper()
    if tag not in TAGS:
        die(f"tag must be one of {', '.join(TAGS)}")
    for nj in sorted(paper.review.glob("*/notes.json"), reverse=True):
        try:
            data = json.loads(nj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for n in data.get("notes", []):
            if n.get("id") == note_id:
                n["tag"] = tag
                nj.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                              encoding="utf-8")
                (nj.parent / "NOTES.md").write_text(
                    notes_md(paper, data["notes"], data.get("build", {}), nj.parent.name),
                    encoding="utf-8")
                return {"id": note_id, "tag": tag, "session": nj.parent.name}
    die(f"no note {note_id} in {paper.review}")


def cmd_resolve(paper: Paper, note_id: str, status: str, response: str) -> dict:
    """Say what the revision did with a note, and regenerate NOTES.md."""
    if status not in STATUSES:
        die(f"status must be one of {', '.join(STATUSES)}")
    for nj in sorted(paper.review.glob("*/notes.json"), reverse=True):
        try:
            data = json.loads(nj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for n in data.get("notes", []):
            if n.get("id") == note_id:
                n["status"] = status
                n["response"] = response
                nj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                session = nj.parent.name
                (nj.parent / "NOTES.md").write_text(
                    notes_md(paper, data["notes"], data.get("build", {}), session),
                    encoding="utf-8",
                )
                return {"id": note_id, "status": status, "session": session}
    die(f"no note {note_id} in {paper.review}")


# --- the board asks for all of it at once ---------------------------------

def cmd_meta(paper: Paper) -> dict:
    info = build_info(paper)
    return {
        "id": paper.pid,
        "name": paper.name,
        "repo": str(paper.repo),
        "main": paper.main,
        "task": paper.task,
        "build": info,
        "built": paper.pdf.is_file(),
        "stale": source_moved(paper),
        "open": read_session(paper),
        "past": past_sessions(paper),
        "claude_notes": claude_notes(paper),
    }


def claude_notes(paper: Paper) -> list[dict]:
    """A note set written by a pass (the annotate-paper.py format: page hint,
    anchor phrase, comment), placed on the page by searching for its anchor so
    the owner reacts to Claude's markup and adds his own in the same reading."""
    if not paper.notes:
        return []
    path = (paper.repo / paper.notes) if not Path(paper.notes).is_absolute() else Path(paper.notes)
    path = path.expanduser()
    if not path.is_file() or not paper.pdf.is_file():
        return []
    raw: list = []
    if path.suffix == ".json":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return []
    else:
        scope: dict = {}
        try:
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), scope)
        except Exception:  # noqa: BLE001  a note file is data, but it is python
            return []
        raw = scope.get("NOTES", [])
    doc = pymupdf.open(paper.pdf)
    out = []
    for i, entry in enumerate(raw):
        try:
            page_hint, anchor, comment = entry[0], entry[1], entry[2]
        except (TypeError, IndexError):
            continue
        hit, page_no = None, None
        order = [int(page_hint)] + [p for p in range(1, doc.page_count + 1) if p != int(page_hint)]
        for p in order:
            if not 1 <= p <= doc.page_count:
                continue
            found = doc[p - 1].search_for(anchor[:80])
            if found:
                hit, page_no = found[0], p
                break
        if hit is None:
            continue
        out.append({
            "id": f"claude-{i:03d}",
            "page": page_no,
            "rect": [round(hit.x0, 2), round(hit.y0, 2), round(hit.x1, 2), round(hit.y1, 2)],
            "anchor": anchor,
            "note": comment,
            "tag": comment.split(":", 1)[0].upper() if ":" in comment[:12] else "TODO",
        })
    doc.close()
    return out


# --- posting a paper: what the other repository has to know ---------------

def find_main(repo: Path) -> str:
    """The .tex with \\documentclass in it, preferring the shallowest."""
    found = []
    for tex in repo.rglob("*.tex"):
        if any(part in (".git", "attic", "auto") for part in tex.parts):
            continue
        try:
            head = tex.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if re.search(r"^\s*\\documentclass", head, re.M):
            found.append(tex)
    if not found:
        return ""
    found.sort(key=lambda p: (len(p.relative_to(repo).parts), len(p.name)))
    return str(found[0].relative_to(repo))


def title_of(repo: Path, main: str) -> str:
    """The paper's own \\title, for a name worth reading on a pill."""
    try:
        text = (repo / main).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"\\title\s*\{(.+?)\}\s*(?:\n|$)", text, re.S)
    if not m:
        return ""
    title = re.sub(r"\\[a-zA-Z]+\s*", " ", m.group(1))
    title = re.sub(r"[{}$\\]", "", title)
    return re.sub(r"\s+", " ", title).strip()[:70]


def cmd_add(repo_arg: str, main: str, name: str, task: str) -> dict:
    repo = Path(repo_arg).expanduser().resolve()
    if not repo.is_dir():
        die(f"no such directory: {repo}")
    main = main or find_main(repo)
    if not main:
        die(f"no .tex with \\documentclass under {repo}; pass --main")
    if not (repo / main).is_file():
        die(f"no such file: {repo / main}")
    name = name or title_of(repo, main) or repo.name
    try:
        raw = json.loads(PAPERS_FILE.read_text(encoding="utf-8")) if PAPERS_FILE.is_file() else {}
    except ValueError as e:
        die(f"papers.json is not valid JSON: {e}")
    papers = raw.get("papers", [])
    home = str(repo)
    for entry in papers:
        if Path(str(entry.get("repo", ""))).expanduser().resolve() == repo:
            die(f"already registered as '{entry.get('name')}'; edit papers.json to change it")
    # keep the ~ so papers.json reads as the owner's own paths do
    try:
        home = "~/" + str(repo.relative_to(Path.home()))
    except ValueError:
        pass
    # The id is written down rather than derived again on every read: it is in
    # URLs, in cache paths and in the notes already sent, and it must not move
    # because somebody improved the paper's name.
    entry = {"id": slugify(name), "name": name, "repo": home, "main": main}
    if task:
        entry["task"] = task
    papers.append(entry)
    raw["papers"] = papers
    PAPERS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    paper = resolve_paper(slugify(name))
    try:
        info = cmd_build(paper)
    except SystemExit:
        # a paper that will not compile is not registered: papers.json goes
        # back as it was rather than keeping an entry that cannot be read
        raw["papers"] = [e for e in papers if e is not entry]
        PAPERS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        raise
    return {"id": paper.pid, "name": name, "main": main, "pages": info["pages"],
            "synctex": info["synctex"]}


def cmd_check(repo_arg: str) -> dict:
    """Whether a repository is ready to be posted, without registering it."""
    repo = Path(repo_arg).expanduser().resolve()
    main = find_main(repo) if repo.is_dir() else ""
    return {
        "repo": str(repo),
        "exists": repo.is_dir(),
        "main": main,
        "title": title_of(repo, main) if main else "",
        "latexmk": bool(shutil.which("latexmk")),
        "synctex": bool(shutil.which("synctex")),
        "git": (repo / ".git").exists(),
    }


# --- the CLI ---------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list"); ls.add_argument("--json", action="store_true")
    ad = sub.add_parser("add"); ad.add_argument("repo")
    ad.add_argument("--main", default=""); ad.add_argument("--name", default="")
    ad.add_argument("--task", default="")
    ck = sub.add_parser("check"); ck.add_argument("repo")
    sub.add_parser("howto")
    b = sub.add_parser("build"); b.add_argument("paper"); b.add_argument("--force", action="store_true")
    b.add_argument("--no-prerender", action="store_true")
    m = sub.add_parser("meta"); m.add_argument("paper")
    r = sub.add_parser("render"); r.add_argument("paper"); r.add_argument("page", type=int)
    r.add_argument("--scale", type=float, default=DEFAULT_SCALE)
    se = sub.add_parser("layout"); se.add_argument("paper"); se.add_argument("page", type=int)
    a = sub.add_parser("anchor"); a.add_argument("paper"); a.add_argument("page", type=int)
    a.add_argument("rect", type=float, nargs=4)
    a.add_argument("--rects", default="")
    n = sub.add_parser("note"); n.add_argument("paper"); n.add_argument("--json", required=True,
        help="the note as JSON, or - to read it from stdin (handwriting is far "
             "too big for a command-line argument: the kernel caps one at 128 KB)")
    d = sub.add_parser("drop"); d.add_argument("paper"); d.add_argument("note_id")
    ns = sub.add_parser("notes"); ns.add_argument("paper"); ns.add_argument("--json", action="store_true")
    e = sub.add_parser("export"); e.add_argument("paper"); e.add_argument("--no-commit", action="store_true")
    cl = sub.add_parser("classify"); cl.add_argument("paper"); cl.add_argument("note_id")
    cl.add_argument("tag")
    rs = sub.add_parser("resolve"); rs.add_argument("paper"); rs.add_argument("note_id")
    rs.add_argument("status"); rs.add_argument("response", nargs="?", default="")
    args = ap.parse_args(argv)

    if args.cmd == "howto":
        # the contract lives in this repo and is read from here; nothing of it
        # is ever planted in a paper's own repository
        try:
            print(HOWTO.read_text(encoding="utf-8"), end="")
        except OSError:
            die(f"{HOWTO} is missing")
        return 0

    if args.cmd == "add":
        out = cmd_add(args.repo, args.main, args.name, args.task)
        print(f"{out['id']}: {out['name']}")
        print(f"  main    {out['main']}, {out['pages']} pages"
              + ("" if out["synctex"] else "  (no synctex: notes will carry no source line)"))
        print(f"  read it at /paper/{out['id']} on the board")
        print(f"  what to do with the notes it sends back: {howto_path()}")
        return 0

    if args.cmd == "check":
        out = cmd_check(args.repo)
        ok = out["exists"] and out["main"] and out["latexmk"] and out["synctex"]
        for k in ("repo", "exists", "main", "title", "latexmk", "synctex", "git"):
            print(f"  {k:<9} {out[k]}")
        print("ready to post" if ok else "not ready: see above")
        return 0 if ok else 1

    if args.cmd == "list":
        papers = load_papers()
        if args.json:
            # what the board needs to draw its pills. Deliberately cheap: no
            # source_moved(), which walks a repo for .tex timestamps.
            print(json.dumps([
                {"id": p.pid, "name": p.name, "repo": str(p.repo), "main": p.main,
                 "task": p.task, "custom_build": bool(p.build),
                 "built": p.pdf.is_file(), "open": len(read_session(p))}
                for p in papers], ensure_ascii=False))
            return 0
        if not papers:
            print("no papers registered; add one to papers.json")
            return 0
        for p in papers:
            info = build_info(p)
            state = "not built" if not p.pdf.is_file() else (
                f"{info.get('pages', '?')}p, {info.get('commit', '?')}"
                + (", sources moved on" if source_moved(p) else ""))
            open_n = len(read_session(p))
            print(f"{p.pid:<28} {state:<34} {open_n} open note(s)  {p.name}")
        return 0

    paper = resolve_paper(args.paper)
    if args.cmd == "build":
        info = cmd_build(paper, args.force, not args.no_prerender)
        print(f"{paper.pid}: {info['pages']} pages from {info.get('commit') or 'an untracked tree'}"
              + ("" if info["synctex"] else "  (no synctex: notes will carry no source line)"))
    elif args.cmd == "meta":
        print(json.dumps(cmd_meta(paper), ensure_ascii=False))
    elif args.cmd == "render":
        print(page_png(paper, args.page, args.scale))
    elif args.cmd == "layout":
        print(json.dumps(layout_cached(paper, args.page), ensure_ascii=False))
    elif args.cmd == "anchor":
        rects = json.loads(args.rects) if args.rects else None
        print(json.dumps(cmd_anchor(paper, args.page, list(args.rect), rects),
                         ensure_ascii=False))
    elif args.cmd == "note":
        raw = sys.stdin.read() if args.json == "-" else args.json
        try:
            data = json.loads(raw)
        except ValueError as ex:
            die(f"the note is not valid JSON: {ex}")
        print(json.dumps(cmd_note(paper, data), ensure_ascii=False))
    elif args.cmd == "drop":
        print(json.dumps(cmd_drop(paper, args.note_id), ensure_ascii=False))
    elif args.cmd == "notes":
        notes = read_session(paper) + past_sessions(paper)
        if args.json:
            print(json.dumps(notes, ensure_ascii=False))
        elif not notes:
            print("no notes yet")
        else:
            for n in notes:
                where = n.get("source") or {}
                head = f"{where['file']}:{where['line']}" if where.get("file") else f"p{n['page']}"
                mark = {"open": " ", "done": "x", "rejected": "-"}.get(n.get("status", "open"), " ")
                body = n.get("note") or ("(handwritten)" if n.get("ink") else "")
                print(f"[{mark}] {n['id']}  {head:<28} {n['tag']:<8} {body[:60]}")
    elif args.cmd == "export":
        print(json.dumps(cmd_export(paper, not args.no_commit), ensure_ascii=False))
    elif args.cmd == "classify":
        print(json.dumps(cmd_classify(paper, args.note_id, args.tag), ensure_ascii=False))
    elif args.cmd == "resolve":
        print(json.dumps(cmd_resolve(paper, args.note_id, args.status, args.response),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
