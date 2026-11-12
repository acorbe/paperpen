"""A shelf of one paper, made from scratch, so the tests need nothing installed
on the machine and nothing of yours on it either."""

import json

import pymupdf
import pytest


@pytest.fixture
def board(tmp_path, monkeypatch):
    """A registry, a cache, a rounds directory and one built paper."""
    for name, sub in (("PAPERPEN_HOME", "config"), ("PAPERPEN_CACHE", "cache"),
                      ("PAPERPEN_DATA", "data")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(name, str(tmp_path / sub))
    # no test starts claude: an agent is started by Finish on a paper of your own
    monkeypatch.setenv("PAPERPEN_AGENT", "off")

    repo = tmp_path / "paper"
    repo.mkdir()
    doc = pymupdf.open()
    for n, body in enumerate((
        "Pedestrian dyads in a corridor.\nWe measure how two people walking "
        "together arrange themselves. The arrangement depends on density.",
        "Results.\nAt low density the pair walks side by side. At high density "
        "it walks one behind the other.")):
        page = doc.new_page()
        page.insert_text(pymupdf.Point(72, 96), body, fontsize=11)
    doc.save(repo / "draft.pdf")
    doc.close()

    (tmp_path / "config" / "papers.json").write_text(json.dumps({"papers": [{
        "id": "dyads-in-a-corridor", "name": "Pedestrian dyads in a corridor",
        "repo": str(repo), "main": "draft.pdf", "kind": "student",
        "brief": "A first draft. Language, and whether the claim in Sec. 2 holds.",
    }]}), encoding="utf-8")

    from paperpen import bind
    bind.paper.cmd_build(bind.resolve_paper("dyads"), prerender=False)
    return tmp_path


# --- a LaTeX paper with a delivered round, and the same under git -----------

SESSION = "2026-09-20"
NOTE = "2026-09-20-01"
TEX = ("\\documentclass{article}\n\\begin{document}\n"
       "The arrangement depends on the density of the crowd.\n"
       "At low density the pair walks side by side.\n"
       "\\end{document}\n")


@pytest.fixture
def paper(board):
    """The fixture's paper, as a LaTeX repository with one round delivered."""
    from paperpen import bind

    repo = board / "paper"
    (repo / "main.tex").write_text(TEX, encoding="utf-8")
    reg = board / "config" / "papers.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["papers"][0].update(main="main.tex", kind="mine")
    reg.write_text(json.dumps(data), encoding="utf-8")
    review = repo / "review" / SESSION
    review.mkdir(parents=True)
    (review / "notes.json").write_text(json.dumps({"notes": [{
        "id": NOTE, "page": 1, "tag": "SCIENCE", "status": "open", "response": "",
        "note": "which density: the pair's, or the crowd's?",
        "anchor": "The arrangement depends on the density of the crowd.",
        "source": {"file": "main.tex", "line": 3}, "rect": [0, 0, 0, 0], "rects": [],
    }]}), encoding="utf-8")
    return bind.resolve_paper("dyads")


def git(repo, *args):
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(paper):
    """The feedback fixture's paper, under git, with one fix applied and one
    unrelated edit in the working tree that is not the review's."""
    from paperpen import feedback

    r = paper.repo
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.name=t", "-c", "user.email=t@example.org", "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "draft")
    for key, value in (("user.name", "t"), ("user.email", "t@example.org")):
        git(r, "config", key, value)
    (r / "notes-to-self.txt").write_text("not the review's\n")
    feedback.propose("dyads", NOTE, "the local density", [
        {"file": "main.tex", "old": "the density of the crowd",
         "new": "the local density of the crowd"}], by="claude", now=True)
    return r
