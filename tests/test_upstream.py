"""upstream/ is the dashboard's files, plus whatever upstream/patches/ says.

Two things can go wrong there and both are silent. The reader is converted when
it is taken out of the `PAPER_PAGE` format string, and a conversion over 1700
lines of CSS and JavaScript can corrupt something nobody looks at. And the
patches can quietly stop describing what is in upstream/, at which point the
next sync changes behaviour without anybody deciding to.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream"
FIELDS = {"pid": "wake-transitions-cylinder", "name": "Wake transitions & <cylinder>",
          "board_name": "a board", "task": "2026-09-14-a-task", "custom_build": "1"}


def load_sync():
    spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts" / "sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync"] = module
    spec.loader.exec_module(module)
    return module


def board() -> Path:
    """The dashboard checkout, from $PAPERPEN_BOARD as scripts/sync.py takes it;
    unset, the tests that need it are skipped."""
    return Path(os.environ.get("PAPERPEN_BOARD") or "/nonexistent").expanduser()


needs_board = pytest.mark.skipif(
    not (board() / "dashboard.py").is_file(),
    reason="the dashboard checkout is not on this machine")


def render(template: str) -> str:
    """How paperpen fills the reader: `{word}` is a placeholder and nothing else
    is touched, which is what the braces in the CSS depend on."""
    return re.sub(r"\{([a-z_]+)\}", lambda m: FIELDS.get(m.group(1), m.group(0)), template)


@needs_board
def test_the_reader_survives_leaving_the_format_string():
    with tempfile.TemporaryDirectory() as tmp:
        load_sync().extract(board(), Path(tmp))
        taken = (Path(tmp) / "reader.html").read_text(encoding="utf-8")

    source = (board() / "dashboard.py").read_text(encoding="utf-8")
    start = source.index('PAPER_PAGE = """') + len('PAPER_PAGE = """')
    original = source[start:source.index('\n"""', start) + 1]

    assert render(taken) == original.format(**FIELDS)


@needs_board
def test_the_copies_are_the_dashboard_before_the_patches_are_replayed():
    """Verbatim, except for the dashboard's own path, which `scrub` takes out."""
    sync = load_sync()
    names = sync.board_names(board())
    with tempfile.TemporaryDirectory() as tmp:
        files = sync.extract(board(), Path(tmp))
        for name, info in files.items():
            if ":" in info["from"]:
                continue  # cut out of dashboard.py, covered above
            source = (board() / info["from"]).read_text(encoding="utf-8")
            assert (Path(tmp) / name).read_text(encoding="utf-8") == sync.scrub(source, names), name
            assert sync.sha(source) == info["sha256"], name


@needs_board
def test_upstream_is_in_step_with_the_dashboard():
    """What `scripts/sync.py --check` says, which is what CI runs: extracting
    again and replaying the patches reproduces upstream/ exactly."""
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync.py"), "--check"],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_patch_is_still_needed():
    """A patch that no longer applies is the sync telling you the dashboard has
    moved under it. It must fail loudly rather than be skipped."""
    patches = sorted((UPSTREAM / "patches").glob("*.patch"))
    recorded = json.loads((UPSTREAM / "UPSTREAM.json").read_text())["patches"]
    assert [p.name for p in patches] == recorded


def test_no_placeholder_was_left_undoubled():
    """A `{word}` meant as CSS or JavaScript would now be a hole in the page."""
    page = (UPSTREAM / "reader.html").read_text(encoding="utf-8")
    assert set(re.findall(r"\{([a-z_]+)\}", page)) == {"pid", "name", "custom_build"}


def test_the_contract_path_points_at_a_file_that_is_here():
    """It is written into the NOTES.md that goes to the co-author.

    Upstream derives it from `board_home()`, which in the dashboard is the
    checkout PAPERS.md sits at the top of. Vendored, the same sum named a file
    that does not exist, in a document sent to somebody else. And the one in
    upstream/ is the dashboard's contract, in the dashboard's commands, so the
    path is paperpen's own.
    """
    from paperpen import bind

    assert bind.paper.howto_path() == bind.HOWTO
    assert bind.paper.howto_path().is_file()


def test_a_title_is_not_cut_in_the_middle_of_a_word(tmp_path):
    """Upstream cuts at 70 for a pill the shelf does not have, and the id is
    slugified from the name and then never allowed to move."""
    from paperpen import bind

    long = ("Towards modeling abreast to in-file transitions in small "
            "pedestrian groups at high density")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\title{" + long + "}\n", encoding="utf-8")
    assert bind.paper.title_of(tmp_path, "main.tex") == long

    longer = " ".join(["Supercalifragilistic"] * 12)
    (tmp_path / "big.tex").write_text(
        "\\documentclass{article}\n\\title{" + longer + "}\n", encoding="utf-8")
    got = bind.paper.title_of(tmp_path, "big.tex")
    assert len(got) <= bind.LONGEST_TITLE and not got.endswith("Supercalifragilisti")


def test_scrub_takes_the_dashboards_own_path_out():
    """The dashboard's files say where they run from; vendored, that is a
    private name. Made-up name here, since the real one is written nowhere."""
    sync = load_sync()
    text = ("Everything below is run from this repo, which lives at\n"
            "`~/workspace/my-board` (the main checkout, not a worktree).\n"
            "~/workspace/my-board/scripts/paper.py howto\n"
            "/home/someone/workspace/my-board/scripts/paper.py add <repo>\n"
            "see my-board for more; my-boardwalk is something else\n")
    got = sync.scrub(text, {"my-board"})
    assert "my-board" not in got.replace("my-boardwalk", "")
    assert "`$PAPERPEN_BOARD` (the main checkout" in got
    assert got.count("scripts/paper.py") == 2 and "~/" not in got and "/home/" not in got
    assert "see the dashboard for more" in got and "my-boardwalk" in got


@needs_board
def test_nothing_tracked_names_the_dashboard():
    """What goes to GitHub is what git tracks, so none of it may carry the
    dashboard's name, the patches included: a patch carries the lines it removes."""
    sync = load_sync()
    names = sync.board_names(board())
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             text=True).stdout.split("\0")
    for rel in filter(None, tracked):
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name in names:
            assert name not in text, f"{rel} names the dashboard"
