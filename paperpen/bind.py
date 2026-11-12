"""Load the dashboard's paper.py and point it at paperpen's directories.

The file in upstream/ is the dashboard's, byte for byte, and stays that way.
What it needs told is where the registry is and where the cache goes, and both
are module globals or a single function, so they are rebound here after import
rather than edited there. This is the mechanism the design prefers to a patch:
a patch has to be replayed and can fail to apply, while a rebinding either
finds the name or raises on the spot.

Anything that cannot be reached this way belongs in upstream/patches/.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

from . import config

UPSTREAM = Path(__file__).resolve().parent.parent / "upstream"

# The contract for a paper's own repository, which `paperpen howto` prints and
# every NOTES.md points at. paperpen's own, in paperpen's commands: the one in
# upstream/ is the dashboard's, and tells its reader to run the dashboard.
HOWTO = Path(__file__).resolve().parent.parent / "docs" / "papers.md"


def _load(name: str, filename: str) -> ModuleType:
    full = f"paperpen._upstream.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, UPSTREAM / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {UPSTREAM / filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


class Refused(Exception):
    """What upstream's `die` becomes here.

    In a terminal `die` prints and raises SystemExit, which is right for a CLI
    and wrong inside a request: SystemExit is a BaseException, so a web
    framework does not catch it and a refusal that should have been a 400 takes
    the worker down with it. Rebinding turns every refusal in 1354 lines into
    an ordinary exception with its message intact.
    """


# The paper's name, which upstream cuts to 70 characters because the dashboard
# draws it on a pill. Here it is the heading of a shelf card, where there is
# room for it, and the cut fell mid-word: the first real paper added came out
# as "Towards modeling abreast to in-file transitions in small pedestrian gr".
# It outlives its reason, because the id is slugified from the name and is
# deliberately never allowed to move afterwards.
#
# This is the one place paperpen restates something upstream also knows, and
# it is a restatement and not a rebinding: the limit is a literal inside the
# function, so there is no name to point elsewhere and no way to recover from
# the outside what has already been cut off. The parse is four lines and is
# kept identical on purpose; if upstream learns to read a title better, this
# is where that has to be brought over. The limit properly belongs in the
# dashboard's own view rather than in a function that returns data, and if it
# ever moves there this comes straight back out.
TITLE_RE = re.compile(r"\\title\s*\{(.+?)\}\s*(?:\n|$)", re.S)
LONGEST_TITLE = 120   # a card heading, not a pill; a word is never cut


def title_of(repo: Path, main: str) -> str:
    try:
        text = (repo / main).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = TITLE_RE.search(text)
    if not m:
        return ""
    title = re.sub(r"\\[a-zA-Z]+\s*", " ", m.group(1))
    title = re.sub(r"[{}$\\]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > LONGEST_TITLE:
        title = title[:LONGEST_TITLE].rsplit(" ", 1)[0]
    return title


def _rebind(module: ModuleType) -> ModuleType:
    for name in ("PAPERS_FILE", "HOWTO", "cache_root", "board_home",
                 "howto_path", "title_of", "die"):
        if not hasattr(module, name):
            raise ImportError(f"upstream/paper.py no longer defines {name}; "
                              f"run scripts/sync.py and check what moved")
    module.HOWTO = HOWTO
    module.cache_root = config.cache_root
    module.board_home = lambda: UPSTREAM.parent
    module.title_of = title_of

    # Where somebody else is told to read the contract. Upstream works it out
    # from `board_home()`, and in the dashboard that is right: PAPERS.md sits
    # at the top of that checkout. Vendored here the same sum came out as
    # `<repo>/PAPERS.md`, which is nothing. And that path is not printed to
    # us: it is written into the NOTES.md committed into the co-author's
    # repository, so a dead path under your home went out in a file
    # sent to somebody else.
    module.howto_path = lambda: HOWTO

    def die(msg: str) -> None:
        raise Refused(msg)

    module.die = die
    return module


paper = _rebind(_load("paper", "paper.py"))
markup = _load("annotate_paper", "annotate_paper.py")

Paper = paper.Paper


def _aim() -> None:
    """Point upstream at the registry that is current *now*.

    `PAPERS_FILE` is a module global upstream reads on every call, so binding it
    once at import would freeze whichever registry happened to be in force then.
    That is wrong twice over: a `.paperpen/` beside the papers is found relative
    to the working directory, and a test that moves the registry has to be able
    to move it.

    The directory is made here too. Upstream writes the registry in place and
    takes its parent for granted, which is fair where the registry is a file at
    the top of the checkout it lives in. paperpen's is under `~/.config`, which
    nothing has created on a machine the tool has not been run on yet, so the
    first `paperpen add` anybody ever types ended in a FileNotFoundError out of
    pathlib. Aiming at a registry includes making the place it is to live.
    """
    global _core_add
    paper.PAPERS_FILE = config.registry_file()
    paper.PAPERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if paper.cmd_add is not _guarded_cmd_add:
        _core_add = paper.cmd_add
        paper.cmd_add = _guarded_cmd_add


# Upstream reads a paper's history out of `review/` in the paper's repository,
# because every paper the dashboard read had one. Here a round can be delivered
# as a PDF and leave no repository copy at all, and a note id is handed out from
# that history: with the history invisible, the ids of one day's second round
# repeat the first's and the record of the first is overwritten by the second.
# So upstream is given the merged view, and the repository-only one is kept
# under a name of its own for the code that has to build the merge.
repo_sessions = paper.past_sessions


def _all_sessions(p) -> list:
    from . import rounds  # here, not at import: rounds is built on this module

    return rounds.delivered_notes(p)


paper.past_sessions = _all_sessions


def load_papers() -> list:
    _aim()
    return paper.load_papers()


def resolve_paper(query: str):
    _aim()
    return paper.resolve_paper(query)


_core_add = None


def _refuse_duplicate_id(path: Path, main: str, name: str) -> None:
    """Refuse a second paper with an id that is already taken.

    The core guards the repository path, so the same folder cannot be added
    twice, but it derives the id from the paper's \\title and appends without
    looking. Two different folders holding the same title, a branch or a
    worktree carrying a variant of a manuscript, therefore register two entries
    with one id. Nothing complains: `resolve_paper` then answers with whichever
    comes first, so the build check after the add can validate the wrong
    document, and the cache path, the URL and every note already sent point at
    both papers at once.

    `adopt` already refuses rather than guess an id for this reason. This is
    the same refusal on the way in, and it names the flag that gets past it.
    """
    if not paper.PAPERS_FILE.is_file():
        return
    try:
        raw = json.loads(paper.PAPERS_FILE.read_text(encoding="utf-8"))
    except ValueError:
        return                                  # the core reports this itself
    wanted = name or paper.title_of(path, main or paper.find_main(path)) or path.name
    pid = paper.slugify(wanted)
    for entry in raw.get("papers", []):
        if entry.get("id") != pid:
            continue
        raise Refused(
            f"id '{pid}' is already on the shelf as '{entry.get('name')}' "
            f"({entry.get('repo')}). Two papers cannot share an id: it is in "
            f"the URL, the cache path and every note already sent. Give this "
            f"one a name of its own with --name, or rename the other."
        )


def _guarded_cmd_add(repo_arg, main="", name="", task=""):
    """Upstream's cmd_add with the id collision refused first.

    Wrapping the core rather than `add()` is deliberate: `paperpen add` reaches
    upstream through `run()` and `paper.main`, not through `add()`, so a guard
    on the wrapper alone sits on a path the command line never takes.
    """
    _refuse_duplicate_id(Path(repo_arg).expanduser().resolve(), main, name)
    return _core_add(repo_arg, main, name, task)


def add(where: str, main: str = "", name: str = "") -> dict:
    """Put a paper on the shelf: a LaTeX repository, a folder, or a PDF.

    A PDF is its folder with the file as the main one, which is how the core
    registers one. The core takes its entry back out when the first build
    fails, but only for the SystemExit its own command line raises, and here
    `die` raises Refused: so the entry is taken back out here as well, rather
    than leaving a paper on the shelf that cannot be read.
    """
    _aim()
    path = Path(where).expanduser()
    if path.is_file():
        if path.suffix.lower() != ".pdf":
            raise Refused(f"{path.name} is neither a folder nor a PDF")
        path, main = path.parent, main or path.name
    if not path.is_dir():
        raise Refused(f"no such folder or PDF: {where}")
    before = paper.PAPERS_FILE.read_text(encoding="utf-8") if paper.PAPERS_FILE.is_file() else None
    try:
        return paper.cmd_add(str(path), main, name, "")
    except Refused:
        now = paper.PAPERS_FILE.read_text(encoding="utf-8") if paper.PAPERS_FILE.is_file() else None
        if now != before:
            if before is None:
                paper.PAPERS_FILE.unlink(missing_ok=True)
            else:
                paper.PAPERS_FILE.write_text(before, encoding="utf-8")
        raise


def run(argv: list[str]) -> int:
    """Upstream's own command line, aimed at paperpen's registry first.

    Every way into upstream goes through this module, and aiming is the first
    thing each of them does. Handing `argv` straight to `paper.main` was the
    one door left open: it left `PAPERS_FILE` at upstream's own default, so
    `paperpen add` wrote its entry into the checkout next to paper.py while
    `paperpen shelf` went on reading the registry `paperpen where` names. The
    paper you had just added was not on the shelf, and neither command was
    wrong about anything except which file the other one meant.
    """
    _aim()
    return paper.main(argv)
