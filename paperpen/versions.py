"""The same paper as it was, and what changed since.

A manuscript is read against its own history. What did this paragraph say
before the co-author touched it, and what exactly moved? The reader shows one
build of one tree, which is the tree that happens to be checked out; this
shows three at once (a commit, what is here now, and the two of them run
through latexdiff) beside the log they were picked from.

Nothing is written into the paper's repository, not even the administrative
file a `git worktree` leaves behind. A version is taken with `git archive`,
which only reads, and unpacked into paperpen's cache; so this works on a
repository that is dirty, mid-rebase, or somebody else's, and a paper being
compared is a paper nothing is happening to.

What comes out is built by upstream's own `cmd_build`, into a cache directory
of its own. The old PDF is therefore made the same way as the PDF you read,
which is the only way the two are worth putting side by side.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from . import bind, config

WORKING = "work"          # the tree as it is on disk, dirt and all
PAIR = ".."               # old..new, as git spells it
KEY = 12                  # how much of a sha names a cache directory
LATEXDIFF = os.environ.get("PAPERPEN_LATEXDIFF", "").strip() or "latexdiff --flatten"
DIFF_TIMEOUT = 600

# What a source diff is about. A build directory full of .aux and .bbl is not
# a change to the paper even when git is tracking it.
SOURCE = ("*.tex", "*.bib", "*.sty", "*.cls")
LONGEST_DIFF = 400_000    # characters of patch handed to a browser

# A ref is passed to git, never to a shell, so the charset is only here to
# keep a path out of the cache key and a surprise out of the log.
REF_OK = re.compile(r"^[A-Za-z0-9._/~^@{}-]{1,100}$")

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(key: str) -> threading.Lock:
    """One build of one version at a time.

    Two tablets on the same shelf, or one browser reloaded while latexmk is
    running, would otherwise start a second latexmk on the same -outdir. The
    second caller waits and then finds the build already there, which is what
    it wanted.
    """
    with _locks_lock:
        return _locks.setdefault(key, threading.Lock())


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise bind.Refused(f"git {args[0]}: "
                           + (done.stderr.strip() or f"exit {done.returncode}"))
    return done.stdout


def _maybe(repo: Path, *args: str) -> str:
    try:
        return _git(repo, *args).strip()
    except (bind.Refused, OSError, subprocess.SubprocessError):
        return ""


def is_git(paper) -> bool:
    return bool(paper.repo.is_dir() and _maybe(paper.repo, "rev-parse", "--git-dir"))


def need_repo(paper) -> None:
    if not paper.repo.is_dir():
        raise bind.Refused(f"no such repo: {paper.repo}")
    if not is_git(paper):
        raise bind.Refused(f"{paper.repo} is not a git repository, so there is "
                           f"no history to read this against")


# --- the log ---------------------------------------------------------------

RECORD = "\x1e"
FIELD = "\x1f"


def commits(paper, limit: int = 60) -> list[dict]:
    """The log, newest first, with what each commit is likely to mean here.

    `source` says the commit touched the text rather than a figure or the
    build; `round` says it was one of ours, a reading written back into the
    paper. Merges are kept: a manuscript that takes Overleaf back in gets its
    changes in exactly one commit, and that is the one worth comparing to.
    """
    need_repo(paper)
    out = _maybe(paper.repo, "log", f"-n{limit}", "--date=short",
                 f"--format=%H{FIELD}%h{FIELD}%ad{FIELD}%an{FIELD}%s{RECORD}")
    touched = set(_maybe(paper.repo, "log", f"-n{limit}", "--format=%H",
                         "--", *SOURCE).split())
    ours = set(_maybe(paper.repo, "log", f"-n{limit}", "--format=%H",
                      "--", "review").split())
    built = bind.paper.build_info(paper).get("commit", "")
    rows = []
    for record in out.split(RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, short, when, who, subject = record.split(FIELD)
        rows.append({"sha": sha, "short": short, "date": when, "who": who,
                     "subject": subject, "source": sha in touched,
                     "round": sha in ours, "built": bool(built) and short.startswith(built)})
    return rows


def working(paper) -> dict:
    """The row above the log: the tree as it is, and whether it is dirty."""
    dirty = bool(_maybe(paper.repo, "status", "--porcelain")) if is_git(paper) else False
    head = _maybe(paper.repo, "rev-parse", "--short", "HEAD") if is_git(paper) else ""
    return {"ref": WORKING, "dirty": dirty, "head": head,
            "built": paper.pdf.is_file()}


# --- naming one ------------------------------------------------------------

@dataclass(frozen=True)
class Version:
    ref: str          # what was asked for
    kind: str         # work | commit | diff
    key: str          # the cache directory it builds into
    title: str        # one line for a pane heading
    old: str = ""     # full shas; "" on the right of a diff means the working tree
    new: str = ""


def _rev(paper, ref: str) -> str:
    if not REF_OK.match(ref or ""):
        raise bind.Refused(f"not a ref: {ref!r}")
    sha = _maybe(paper.repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if not sha:
        raise bind.Refused(f"{paper.repo.name} has no commit {ref}")
    return sha


def resolve(paper, ref: str) -> Version:
    """A ref as the URL spells it, turned into a place in the cache.

    Three shapes: `work`, a commit, and `old..new` where either side may be a
    commit and the right may be `work`. The key is shortened shas rather than
    the ref as typed, so `HEAD~1` and the sha it names are one build and not
    two, and so that tomorrow's `HEAD~1` does not find yesterday's answer.
    """
    ref = (ref or "").strip()
    if ref in ("", WORKING):
        return Version(WORKING, WORKING, WORKING, "the working tree")
    if PAIR in ref:
        left, _, right = ref.partition(PAIR)
        need_repo(paper)
        old = _rev(paper, left or "HEAD~1")
        new = "" if right in ("", WORKING) else _rev(paper, right)
        key = f"{old[:KEY]}..{new[:KEY] or WORKING}"
        return Version(ref, "diff", key,
                       f"{old[:7]} → {new[:7] or 'the working tree'}", old, new)
    need_repo(paper)
    sha = _rev(paper, ref)
    return Version(ref, "commit", sha[:KEY], sha[:7], sha, sha)


def _root(paper, version: Version) -> Path:
    return config.cache_root() / "versions" / paper.pid / version.key


def _as_paper(paper, version: Version, custom: bool):
    """The same paper, pointed at an extracted tree and its own cache.

    `pid` is the cache directory, because upstream derives the cache from it;
    it never reaches the registry. The custom build command is dropped unless
    the caller says it may run, which is the same rule the server applies to
    the ordinary rebuild button: paperpen does not run a line out of
    papers.json because a browser asked it to.
    """
    if version.kind == WORKING:
        return paper
    root = _root(paper, version)
    return replace(paper, pid=f"versions/{paper.pid}/{version.key}",
                   repo=root / "src", build=paper.build if custom else "")


# --- making one ------------------------------------------------------------

def _extract(paper, sha: str, into: Path) -> None:
    """The tree at `sha`, unpacked. Read-only on the repository, which is the
    point: `git worktree` would write into .git and take a lock on a repo
    somebody may be in the middle of using."""
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="paperpen-tree-") as tmp:
        tar = Path(tmp) / "tree.tar"
        _git(paper.repo, "archive", "--format=tar", "-o", str(tar), sha, timeout=600)
        with tarfile.open(tar) as archive:
            try:
                archive.extractall(into, filter="data")
            except TypeError:       # python without the extraction filters
                archive.extractall(into)


def _copy_working(paper, into: Path) -> None:
    if into.exists():
        shutil.rmtree(into)
    shutil.copytree(paper.repo, into,
                    ignore=shutil.ignore_patterns(".git", "*.pdf", "*.synctex.gz"),
                    symlinks=True)


def _latexdiff(old_main: Path, new_main: Path, out: Path) -> None:
    """latexdiff's marked-up source, flattened so \\input is followed.

    Flattening is what makes this work across two directories: each side's
    \\input is resolved against its own tree, and what comes out is one file
    that no longer refers to either. PAPERPEN_LATEXDIFF replaces the command
    for a paper that needs its own flags (--math-markup and friends), which
    differ per manuscript and are not something to guess at.
    """
    command = LATEXDIFF.split() + [str(old_main), str(new_main)]
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=DIFF_TIMEOUT)
    except FileNotFoundError:
        raise bind.Refused(f"{command[0]} is not installed; it is what marks up "
                           f"the changes. On Debian: apt install latexdiff") from None
    if done.returncode != 0 or not done.stdout.strip():
        raise bind.Refused("latexdiff could not mark up the change:\n"
                           + (done.stderr.strip()[-1200:] or "it said nothing"))
    out.write_text(done.stdout, encoding="utf-8")


def _assemble(paper, version: Version, root: Path) -> None:
    """Put the tree that is going to be built into <root>/src."""
    src = root / "src"
    if version.kind == "commit":
        _extract(paper, version.new, src)
        if not (src / paper.main).is_file():
            raise bind.Refused(f"{paper.main} is not in {version.new[:7]}; the "
                               f"paper was called something else then")
        return

    if paper.is_pdf:
        raise bind.Refused("this paper is a PDF, so there is no source to mark "
                           "up. Put the two builds side by side instead.")
    was = root / "was"
    _extract(paper, version.old, was)
    if version.new:
        _extract(paper, version.new, src)
    else:
        _copy_working(paper, src)
    for side, tree in (("old", was), ("new", src)):
        if not (tree / paper.main).is_file():
            raise bind.Refused(f"{paper.main} is not in the {side} tree")
    try:
        _latexdiff(was / paper.main, src / paper.main, src / paper.main)
    finally:
        shutil.rmtree(was, ignore_errors=True)


def _newest_source(repo: Path) -> float:
    """When the paper was last touched, by the clock on the files."""
    newest = 0.0
    for kind in SOURCE:
        for found in repo.rglob(kind):
            if ".git/" in str(found):
                continue
            try:
                newest = max(newest, found.stat().st_mtime)
            except OSError:
                pass
    return newest


def _stale(paper, version: Version, target) -> bool:
    """Whether a build has been overtaken by the paper being edited.

    A commit cannot change, and neither can a diff between two of them: once
    built they are right forever. Anything with the working tree on one side
    is a different matter: it is the side that moves, and a diff against
    yesterday's edit, drawn without a word, is worse than no diff at all.
    """
    if not target.pdf.is_file():
        return False
    if version.kind == "commit" or (version.kind == "diff" and version.new):
        return False
    if version.kind == WORKING:
        return bool(bind.paper.source_moved(paper))
    return _newest_source(paper.repo) > target.pdf.stat().st_mtime


def state(paper, ref: str) -> dict:
    """What there is of this version, built or not. Nothing is compiled here."""
    version = resolve(paper, ref)
    target = _as_paper(paper, version, custom=False)
    info = bind.paper.build_info(target) if target.pdf.is_file() else {}
    answer = {"ref": version.ref, "kind": version.kind, "key": version.key,
              "title": version.title, "built": bool(info),
              "pages": info.get("pages", 0), "sizes": info.get("sizes", []),
              "at": info.get("at", ""), "old": version.old[:7], "new": version.new[:7],
              "stale": _stale(paper, version, target)}
    if version.kind == "commit":
        answer.update(_about(paper, version.new))
    elif version.kind == WORKING:
        answer.update(working(paper))
    return answer


def _about(paper, sha: str) -> dict:
    line = _maybe(paper.repo, "show", "-s", "--date=short",
                  f"--format=%h{FIELD}%ad{FIELD}%an{FIELD}%s", sha)
    if line.count(FIELD) != 3:
        return {}
    short, when, who, subject = line.split(FIELD)
    return {"short": short, "date": when, "who": who, "subject": subject}


def build(paper, ref: str, force: bool = False, custom: bool = False) -> dict:
    """Compile this version if it is not already there, and say what it is."""
    version = resolve(paper, ref)
    target = _as_paper(paper, version, custom)
    if paper.build and not custom:
        raise bind.Refused(
            "this paper has its own build command in papers.json; the server "
            "does not run those. Build the version from a terminal: "
            f"paperpen versions {paper.pid} --build {version.ref}")
    with _lock(f"{paper.pid}\x00{version.key}"):
        if force or not target.pdf.is_file():
            if version.kind != WORKING:
                root = _root(paper, version)
                root.mkdir(parents=True, exist_ok=True)
                _assemble(paper, version, root)
            bind.paper.cmd_build(target, prerender=False)
    return state(paper, ref)


def pdf_of(paper, ref: str) -> Path:
    """Where this version's PDF is, built or not."""
    return _as_paper(paper, resolve(paper, ref), custom=False).pdf


def page(paper, ref: str, number: int, scale: float) -> Path:
    version = resolve(paper, ref)
    return bind.paper.page_png(_as_paper(paper, version, custom=False), number, scale)


def layout(paper, ref: str, number: int) -> dict:
    """A version's page as the reader reads one: its sentences and their boxes."""
    version = resolve(paper, ref)
    target = _as_paper(paper, version, custom=False)
    if not target.pdf.is_file():
        raise bind.Refused(f"{version.title} has not been compiled")
    return bind.paper.layout_cached(target, number)


# --- from a diff back to the paper -----------------------------------------
#
# A latexdiff build is the new text with the old text put back into it, struck
# through, so its pages are not the reader's pages and a spot on one is not the
# same spot on the other. What they share is the words. So a sentence picked
# on the diff is found in the reader's build by those words, and the note is
# anchored there, where a note taken in the reader itself would have been.
# This is the one place a diff's page is read for more than its picture.

WORD = re.compile(r"[\w'-]+", re.UNICODE)
MATCH_AT_LEAST = 0.5   # below this the sentence is not in the new text at all


def _words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text or "")]


def match(paper, words: list[str], center: int, near: int = 0) -> dict:
    """The sentence of the reader's build that the picked words are in.

    `words` are the diff's words around the finger, in reading order, and
    `center` is the one under it. Not the diff's own sentence: latexdiff's
    markup muddles where its sentences end, and a deletion and the words
    added after it come out as one. So each word is weighed by how near the
    finger it is, and a sentence of the build scores what it has of them, in
    order. Words that were only deleted are in no sentence of the build, so a
    place that is all deletion scores nothing anywhere and is refused rather
    than pinned to whatever shares a few words with it.
    """
    from difflib import SequenceMatcher

    want, weight = [], []
    for i, word in enumerate(words):
        for w in _words(word):
            want.append(w)
            weight.append(1.0 / (1.0 + abs(i - center) / 3.0))
    if len(want) < 2:
        raise bind.Refused("too little text there to find it in the new version")
    total = sum(weight)
    pages = bind.paper.build_info(paper).get("pages", 0)
    if not pages:
        raise bind.Refused("the paper has not been built, so there is nothing to note on")
    best, score = None, 0.0
    for number in range(1, pages + 1):
        for sentence in bind.paper.layout_cached(paper, number).get("sentences", []):
            have = _words(sentence["text"])
            if not have:
                continue
            blocks = SequenceMatcher(None, want, have, autojunk=False).get_matching_blocks()
            got = sum(weight[b.a + k] for b in blocks for k in range(b.size)) / total
            if near and number != near:
                got *= 0.97 ** abs(number - near)     # a tie goes to the near page
            if got > score:
                best, score = (number, sentence), got
    if not best or score < MATCH_AT_LEAST:
        raise bind.Refused("that is not in the new version: it was taken out, "
                           "so there is nothing there to put a note on")
    number, sentence = best
    return {"page": number, "rects": sentence["rects"], "text": sentence["text"],
            "score": round(score, 3)}


def forget(paper, ref: str = "") -> list[str]:
    """Throw builds away. They are cache, and a stale one is only bytes."""
    root = config.cache_root() / "versions" / paper.pid
    if ref:
        root = _root(paper, resolve(paper, ref))
    gone = [p.name for p in sorted(root.glob("*"))] if root.is_dir() else []
    shutil.rmtree(root, ignore_errors=True)
    return gone


# --- what changed, in the source -------------------------------------------

def source_diff(paper, old: str, new: str = WORKING) -> dict:
    """`git diff` over the text, for when the marked-up PDF is not the answer.

    latexdiff shows what a reader would see. This shows what was typed, which
    is what a macro, a figure path or a comment change looks like, and it is
    there when latexdiff is not installed or cannot cope with the file.
    """
    need_repo(paper)
    left = _rev(paper, old)
    right = "" if new in ("", WORKING) else _rev(paper, new)
    ends = [left] + ([right] if right else [])
    stat = _maybe(paper.repo, "diff", "--stat", *ends, "--", *SOURCE)
    patch = _maybe(paper.repo, "diff", "--no-color", "-U3", *ends, "--", *SOURCE)
    cut = len(patch) > LONGEST_DIFF
    return {"old": left[:7], "new": right[:7] or WORKING, "stat": stat.strip(),
            "patch": patch[:LONGEST_DIFF], "cut": cut,
            "empty": not patch.strip()}
