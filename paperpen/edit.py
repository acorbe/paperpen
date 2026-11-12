"""Editing the paper, with the build beside it and SyncTeX between them.

The reader is for reading somebody else's draft. This is for the other half of
the same afternoon: the paper is yours, you know what the sentence should say,
and going back to an editor in another window to say it is how a reading turns
into a morning of retyping notes.

What is here is deliberately thin. The text is read from and written to the
paper's own working tree, with no copy, no database and no lock, so git is still the
thing that knows what changed, and `paperpen versions` still answers against
the same file. Two guards sit around that: a write is refused if the file
moved under the editor (the repository takes Overleaf merges, and a pull is
allowed to win), and the previous contents are kept in the cache first.

SyncTeX works in both directions here. Upstream already asks it which line
made a spot on the page, for anchoring a note; the other direction, where on
the page a line came out, is `synctex view`, which is the same map read the
other way and is what makes a double click mean "show me this bit".
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from . import bind, config, registry

# What the editor will open. A build directory full of .aux is not the paper,
# and neither is a figure: the list is what somebody types into.
KINDS = (".tex", ".bib", ".sty", ".cls", ".bst", ".cfg", ".txt", ".md")
SKIP = {".git", "node_modules", "__pycache__", ".texpadtmp", "_minted"}
MOST_FILES = 400
# what makes a .tex a document rather than a piece of one, as `add` decides it
DOCUMENT = re.compile(r"^[ \t]*\\documentclass", re.M)


def can_be_main(full: Path) -> bool:
    if full.suffix.lower() != ".tex":
        return False
    try:
        with full.open(encoding="utf-8", errors="replace") as f:
            return bool(DOCUMENT.search(f.read(64 * 1024)))
    except OSError:
        return False
BIGGEST = 4 * 1024 * 1024        # a .tex this size is a generated table, not prose
KEEP = 20                        # saves kept per file, oldest thrown away

# `synctex view` answers in blocks, one per box it found for the line.
FIELD = re.compile(r"^(Page|x|y|h|v|W|H):(.+)$")


def editable(paper) -> bool:
    return bool(not paper.is_pdf and paper.repo.is_dir())


def need(paper) -> None:
    if not paper.repo.is_dir():
        raise bind.Refused(f"no such repo: {paper.repo}")
    if paper.is_pdf:
        raise bind.Refused("this paper is a PDF; there is no source to edit")


def inside(paper, rel: str) -> Path:
    """The file `rel` names, or a refusal.

    Everything the browser asks for goes through here. The paper's repository
    is the whole of what may be touched, symlinks resolved before the question
    is asked rather than after: `../../.ssh/id_rsa` and a link pointing out of
    the tree are the same attack and get the same answer.
    """
    need(paper)
    root = paper.repo.resolve()
    try:
        full = (root / (rel or "")).resolve()
        full.relative_to(root)
    except (ValueError, OSError):
        raise bind.Refused(f"{rel} is not in this paper's repository") from None
    if full.suffix.lower() not in KINDS:
        raise bind.Refused(f"{full.suffix or rel} is not a kind of file this edits")
    return full


def files(paper) -> list[dict]:
    """What there is to open, the main file first."""
    need(paper)
    root = paper.repo.resolve()
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in KINDS:
            continue
        if SKIP & set(path.relative_to(root).parts):
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            continue
        found.append({"path": rel, "bytes": path.stat().st_size,
                      "mtime": path.stat().st_mtime, "main": rel == paper.main,
                      "candidate": can_be_main(path)})
        if len(found) >= MOST_FILES:
            break
    found.sort(key=lambda f: (not f["main"], f["path"].count("/"), f["path"]))
    return found


def set_main(paper, rel: str) -> dict:
    """Make another .tex the one that is built.

    A paper with a thesis-style layout has several files that could be the
    main one: the whole, a chapter compiled on its own, the reply to referees.
    Only a file with \\documentclass in it is accepted, which is the same test
    `add` makes, because anything else will not build. The build of the old
    main file stays in the cache, but it is not this paper's any more: the
    reader says not built until the new one is.
    """
    full = inside(paper, rel)
    if full.suffix.lower() != ".tex":
        raise bind.Refused(f"{rel} is not a .tex file")
    if not full.is_file():
        raise bind.Refused(f"no such file: {rel}")
    if not can_be_main(full):
        raise bind.Refused(f"{rel} has no \\documentclass, so it cannot be built on its own")
    rel = str(full.relative_to(paper.repo.resolve()))
    registry.update(paper.pid, main=rel)
    return {"id": paper.pid, "main": rel, "was": paper.main}


def stamp(full: Path) -> str:
    """What a file is, for the purpose of noticing that it changed.

    Nanoseconds and a length, as an opaque string. A float mtime would do the
    same job less well: it goes out to a browser and comes back through JSON,
    and it has to be compared with a tolerance, which is the difference between
    catching a write that happened in the same millisecond and not.
    """
    got = full.stat()
    return f"{got.st_mtime_ns}:{got.st_size}"


def read(paper, rel: str) -> dict:
    """The text, and what it was when it was read, which is what a save is
    checked against."""
    full = inside(paper, rel)
    if not full.is_file():
        raise bind.Refused(f"no such file: {rel}")
    if full.stat().st_size > BIGGEST:
        raise bind.Refused(f"{rel} is {full.stat().st_size // 1024} KB; too big to edit here")
    return {"path": rel, "text": full.read_text(encoding="utf-8", errors="replace"),
            "stamp": stamp(full)}


def _kept(paper, rel: str) -> Path:
    return config.cache_root() / paper.pid / "edits" / rel.replace("/", "%")


def keep(paper, rel: str, was: str) -> Path | None:
    """What the file said before this save.

    A short net, not a long one: git is the long one, and this catches the ten
    minutes before a commit: the paragraph replaced by the wrong paste, found
    out two saves later. It lives in the cache, which is deletable on purpose.
    """
    if not was:
        return None
    home = _kept(paper, rel)
    home.mkdir(parents=True, exist_ok=True)
    when = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    older = home / f"{when}.bak"
    older.write_text(was, encoding="utf-8")
    for stale in sorted(home.glob("*.bak"))[:-KEEP]:
        stale.unlink(missing_ok=True)
    return older


def write(paper, rel: str, text: str, was: str = "") -> dict:
    """Write the file, unless it has moved since it was read.

    The repository takes merges from elsewhere, so an editor that last read a
    file five minutes ago is not entitled to assume it still knows what is in
    it. When the two disagree the save is refused and the editor is told; the
    person decides which one is the paper.
    """
    full = inside(paper, rel)
    if full.exists() and not full.is_file():
        raise bind.Refused(f"{rel} is not a file")
    before = full.read_text(encoding="utf-8", errors="replace") if full.is_file() else ""
    if was and full.is_file() and stamp(full) != was:
        raise bind.Refused(
            f"{rel} has changed on disk since it was opened (a pull, an "
            f"Overleaf merge, or another window). Nothing was written. Reload "
            f"it and put your change in again.")
    if text == before:
        return {"path": rel, "stamp": stamp(full), "written": False,
                "bytes": len(text.encode("utf-8"))}
    kept = keep(paper, rel, before)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(text, encoding="utf-8")
    return {"path": rel, "stamp": stamp(full), "written": True,
            "bytes": len(text.encode("utf-8")),
            "kept": str(kept) if kept else ""}


# --- SyncTeX, both ways ----------------------------------------------------

def _synctex(paper, *args: str) -> str:
    if not paper.synctex.is_file():
        raise bind.Refused("this build has no SyncTeX; build it again with "
                           "latexmk -synctex=1 (which is what `paperpen build` does)")
    done = subprocess.run(["synctex", *args], cwd=paper.cache,
                          capture_output=True, text=True, timeout=30)
    return done.stdout


def forward(paper, rel: str, line: int, column: int = 1) -> dict:
    """Where on the page a line of source came out.

    `synctex view` answers with one block per box it can find for the line,
    each giving the box (h, v, W, H) in points from the top left of the page.
    The first block is the one to show: SyncTeX lists them in the order the
    typesetter made them, so for a line that broke across two columns or two
    pages the first is where reading it starts.
    """
    inside(paper, rel)                      # the same guard as a read
    out = _synctex(paper, "view", "-i", f"{max(1, int(line))}:{max(1, int(column))}:{rel}",
                   "-o", paper.pdf.name)
    hits, current = [], {}
    for text in out.splitlines():
        found = FIELD.match(text.strip())
        if not found:
            continue
        name, value = found.group(1), found.group(2).strip()
        if name == "Page" and current:
            hits.append(current)
            current = {}
        try:
            current[name] = float(value)
        except ValueError:
            pass
    if current:
        hits.append(current)
    boxes = [{"page": int(h["Page"]),
              # v is the baseline and H the height, so the top of the box is
              # v - H; a highlight drawn at v alone sits under the line it means
              "rect": [h.get("h", 0.0), h.get("v", 0.0) - h.get("H", 0.0),
                       h.get("h", 0.0) + h.get("W", 0.0), h.get("v", 0.0)]}
             for h in hits if "Page" in h]
    if not boxes:
        raise bind.Refused(f"SyncTeX has nothing for line {line} of {rel}; it "
                           f"may be a comment, or the build may be older than "
                           f"the line")
    return {"path": rel, "line": int(line), "page": boxes[0]["page"],
            "rect": boxes[0]["rect"], "boxes": boxes}


def inverse(paper, page: int, x: float, y: float) -> dict:
    """Which line made this spot on the page. Upstream's, unchanged."""
    found = bind.paper.synctex_edit(paper, int(page), float(x), float(y))
    if not found:
        raise bind.Refused("SyncTeX has nothing at that spot on the page")
    return found
