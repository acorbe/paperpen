#!/usr/bin/env python3
"""Take the paper reader out of the dashboard again, as it is now.

    scripts/sync.py [<dashboard-checkout>] [--ref HEAD] [--check]

The dashboard is a private repository of the author's, where this code is
exercised every day, so it keeps changing. Its checkout is given as the
argument or as $PAPERPEN_BOARD; without either there is nothing to sync from. Everything under upstream/ is a
verbatim copy of it, taken by this script, and nothing in this repository edits
those files by hand. What paperpen needs differently is done by rebinding at
import (paperpen/bind.py) or, where that cannot reach, by a patch in
upstream/patches/, which this script replays after every extraction. That way
the list of things we had to change is a directory you can read, rather than a
merge conflict in 1700 lines of pen handling.

`--check` extracts to a temporary directory and reports whether upstream/ is
still what the dashboard says it should be. It changes nothing and exits
non-zero when they differ, which is what CI runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream"
PATCHES = UPSTREAM / "patches"
DEFAULT_BOARD = os.environ.get("PAPERPEN_BOARD", "")

# Copied as they are, source -> what it is called here. annotate-paper.py is
# renamed because a hyphen cannot be imported.
COPIES = {
    "scripts/paper.py": "paper.py",
    "scripts/annotate-paper.py": "annotate_paper.py",
    "PAPERS.md": "PAPERS.md",
}

# Lifted out of dashboard.py: the reader's page, and the routes that serve it.
# The page is used; the routes are kept only so that a change to them shows up
# in this diff, because paperpen serves the same endpoints from its own web
# layer and a new one there is a thing we have to notice.
TEMPLATE = "PAPER_PAGE"
ROUTES_FROM = "# --- papers: reading and marking one up on the tablet"
ROUTES_TO = "def safe_note("


def die(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def git(board: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(board), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def cut_template(source: str, name: str) -> tuple[str, list[int]]:
    """A `NAME = \"\"\"...\"\"\"` block, with str.format's doubled braces undone.

    The template is a format string, so every literal brace in 1700 lines of
    CSS and JavaScript is written twice. Undoing that is the whole conversion:
    `{{` is a brace, `}}` is a brace, and a single `{word}` is a placeholder
    that stays. There are no triple braces in it, which is what makes the
    substitution safe to do with a replace rather than a parser.
    """
    lines = source.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f'{name} = """')), -1)
    if start < 0:
        raise ValueError(f"no `{name} = \"\"\"` in dashboard.py")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip() == '"""'), -1)
    if end < 0:
        raise ValueError(f"{name} is never closed")
    body = lines[start][len(f'{name} = """'):] + "\n" + "\n".join(lines[start + 1:end]) + "\n"
    if "{{{" in body:
        raise ValueError(f"{name} has a triple brace; the substitution is no longer safe")
    return body.replace("{{", "{").replace("}}", "}"), [start + 1, end + 1]


def cut_block(source: str, first: str, last: str) -> tuple[str, list[int]]:
    """Everything from the line starting `first` up to the line starting `last`."""
    lines = source.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(first)), -1)
    if start < 0:
        raise ValueError(f"no line starting {first!r} in dashboard.py")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(last)), len(lines))
    return "\n".join(lines[start:end]).rstrip() + "\n", [start + 1, end]


def board_names(board: Path) -> set[str]:
    """What the dashboard is called on disk: the checkout given, and the main
    checkout behind it when that is a worktree, which is the one its files name."""
    names = {board.resolve().name}
    try:
        common = git(board, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        names.add(Path(common).parent.name)
    except Exception:
        pass
    return {n for n in names if n}


def scrub(text: str, names: set[str]) -> str:
    """Take the dashboard's own checkout out of what is vendored.

    Its files say where they are run from (`~/workspace/<dashboard>/scripts/...`),
    which is right in the dashboard and a private name in a published
    repository. A patch cannot do this without carrying the old lines itself, so
    it is done here, with the name worked out from the checkout at sync time and
    written nowhere in this repository.
    """
    for name in sorted(names, key=len, reverse=True):
        n = re.escape(name)
        text = re.sub(r"(?:~|/)[^\s`'\"()]*?/" + n + r"/scripts/", "scripts/", text)
        text = re.sub(r"(?:~|/)[^\s`'\"()]*?/" + n + r"\b", "$PAPERPEN_BOARD", text)
        text = re.sub(r"\b" + n + r"\b", "the dashboard", text)
    return text


def extract(board: Path, into: Path) -> dict:
    """Write every vendored file into `into`, and say where each came from.

    The sums are of the dashboard's files as they are; what is written is
    scrubbed of the dashboard's own path (see `scrub`)."""
    into.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    names = board_names(board)

    for src, dst in COPIES.items():
        path = board / src
        if not path.is_file():
            raise ValueError(f"the dashboard has no {src}")
        text = path.read_text(encoding="utf-8")
        (into / dst).write_text(scrub(text, names), encoding="utf-8")
        files[dst] = {"from": src, "sha256": sha(text), "lines": len(text.splitlines())}

    dashboard = (board / "dashboard.py").read_text(encoding="utf-8")
    page, at = cut_template(dashboard, TEMPLATE)
    (into / "reader.html").write_text(scrub(page, names), encoding="utf-8")
    files["reader.html"] = {"from": f"dashboard.py:{TEMPLATE}", "at": at,
                            "sha256": sha(page), "lines": len(page.splitlines())}

    routes, at = cut_block(dashboard, ROUTES_FROM, ROUTES_TO)
    (into / "routes_dashboard.py").write_text(
        "# Reference only: the dashboard's own /paper routes, so that a change\n"
        "# to them shows up in a sync diff. paperpen does not import this.\n\n"
        + scrub(routes, names), encoding="utf-8")
    files["routes_dashboard.py"] = {"from": "dashboard.py:/paper routes", "at": at,
                                    "sha256": sha(routes), "lines": len(routes.splitlines())}
    return files


def apply_patches(into: Path) -> list[str]:
    """Replay what could not be done by rebinding, in name order.

    Applied from the parent with --directory, because `git apply` run inside a
    repository resolves a patch's paths against the repository root and quietly
    ignores whatever falls outside the current directory, exiting 0 as it does
    so. That silence is worse than a failure: the sync reports the patch as
    replayed and upstream/ does not have it. So each patch also has to change
    something, and one that changes nothing is an error.
    """
    applied = []
    for patch in sorted(PATCHES.glob("*.patch")):
        before = {f: f.read_bytes() for f in sorted(into.glob("*")) if f.is_file()}
        proc = subprocess.run(["git", "apply", "-p1", "--directory", into.name, str(patch)],
                              cwd=into.parent, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError(f"{patch.name} does not apply:\n{proc.stderr.strip()}\n"
                             f"The dashboard has moved under it. Fix it there and drop\n"
                             f"the patch, or rewrite the patch against what is there now.")
        if all(f.read_bytes() == was for f, was in before.items()):
            raise ValueError(f"{patch.name} applied but changed nothing")
        applied.append(patch.name)
    return applied


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", nargs="?", default=DEFAULT_BOARD,
                    help="the dashboard checkout to take it from (default: $PAPERPEN_BOARD)")
    ap.add_argument("--ref", default="", help="check this ref out first (not yet: it uses the tree as it is)")
    ap.add_argument("--check", action="store_true",
                    help="say whether upstream/ is in step; change nothing")
    args = ap.parse_args(argv)

    if not args.board:
        return die("say which dashboard checkout to take it from, or set PAPERPEN_BOARD")
    board = Path(args.board).expanduser()
    if not (board / "dashboard.py").is_file():
        return die(f"{board} does not look like the dashboard (no dashboard.py)")
    if args.ref:
        return die("--ref is not implemented; check the dashboard out yourself first")

    where = Path(tempfile.mkdtemp(prefix="paperpen-sync-")) if args.check else UPSTREAM
    try:
        try:
            files = extract(board, where)
            patches = apply_patches(where)
        except ValueError as e:
            return die(str(e))

        if args.check:
            differ = [name for name in files
                      if not (UPSTREAM / name).is_file()
                      or (UPSTREAM / name).read_text(encoding="utf-8")
                      != (where / name).read_text(encoding="utf-8")]
            for name in differ:
                print(f"out of step: {name}")
            print(f"{len(files) - len(differ)} of {len(files)} files in step with {board}")
            return 1 if differ else 0

        commit = git(board, "rev-parse", "HEAD")
        # The commit is recorded; the checkout's path and its last commit's
        # subject are not, because this file travels and they are the author's.
        (UPSTREAM / "UPSTREAM.json").write_text(json.dumps({
            "commit": commit,
            "commit_short": commit[:9],
            "taken": datetime.now().isoformat(timespec="seconds"),
            "patches": patches,
            "files": files,
        }, indent=2) + "\n", encoding="utf-8")

        for name, info in sorted(files.items()):
            print(f"  {name:<22} {info['lines']:>5} lines  from {info['from']}")
        if patches:
            print("  patches replayed: " + ", ".join(patches))
        print(f"upstream/ is now {commit[:9] or 'an untracked tree'}"
              + (" (dirty)" if git(board, "status", "--porcelain") else ""))
        return 0
    finally:
        if args.check:
            shutil.rmtree(where, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
