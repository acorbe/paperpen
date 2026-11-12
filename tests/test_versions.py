"""A paper with a history, and the three builds that make a comparison."""

import json
import shutil
import subprocess

import pytest

MAIN = r"""\documentclass{article}
\title{Dyads in a corridor}
\begin{document}
\maketitle
The pair walks side by side at low density.
\input{sec/results}
\end{document}
"""

FIRST = r"""\section{Results}
At high density the pair walks one behind the other.
"""

SECOND = r"""\section{Results}
At high density the pair walks in file, one behind the other.
The transition is gradual.
"""

latex = pytest.mark.skipif(not shutil.which("latexmk"),
                           reason="no latexmk on this machine")
diffable = pytest.mark.skipif(not (shutil.which("latexmk") and shutil.which("latexdiff")),
                              reason="no latexdiff on this machine")


def run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def written(tmp_path, monkeypatch):
    """One paper in a git repository, with two commits and an uncommitted edit."""
    for name, sub in (("PAPERPEN_HOME", "config"), ("PAPERPEN_CACHE", "cache"),
                      ("PAPERPEN_DATA", "data")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(name, str(tmp_path / sub))

    repo = tmp_path / "corridor"
    (repo / "sec").mkdir(parents=True)
    (repo / "main.tex").write_text(MAIN, encoding="utf-8")
    (repo / "sec" / "results.tex").write_text(FIRST, encoding="utf-8")
    run(repo.parent, "init", "-q", str(repo))
    run(repo, "config", "user.email", "nobody@example.org")
    run(repo, "config", "user.name", "Nobody")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "the first draft")
    (repo / "sec" / "results.tex").write_text(SECOND, encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "say what happens in between")
    (repo / "README.md").write_text("not the paper\n", encoding="utf-8")

    (tmp_path / "config" / "papers.json").write_text(json.dumps({"papers": [{
        "id": "corridor", "name": "Dyads in a corridor",
        "repo": str(repo), "main": "main.tex"}]}), encoding="utf-8")
    return repo


@pytest.fixture
def paper(written):
    from paperpen import bind
    return bind.resolve_paper("corridor")


def test_the_log_is_newest_first_and_says_what_touched_the_paper(paper, written):
    from paperpen import versions

    log = versions.commits(paper)
    assert [row["subject"] for row in log] == ["say what happens in between",
                                               "the first draft"]
    assert all(row["source"] for row in log)
    assert not any(row["round"] for row in log)
    assert versions.working(paper)["dirty"] is True   # the untracked README


def test_a_ref_is_resolved_to_a_place_in_the_cache(paper):
    from paperpen import bind, versions

    work = versions.resolve(paper, "work")
    assert (work.kind, work.key) == ("work", "work")

    one = versions.resolve(paper, "HEAD~1")
    assert one.kind == "commit" and len(one.key) == versions.KEY

    pair = versions.resolve(paper, "HEAD~1..work")
    assert pair.kind == "diff" and pair.key.endswith("..work")
    assert pair.old.startswith(one.key) and pair.new == ""

    # the same commit named twice is one build, not two
    assert versions.resolve(paper, one.new).key == one.key
    with pytest.raises(bind.Refused):
        versions.resolve(paper, "no-such-commit")


def test_a_version_is_built_without_touching_the_repository(paper, written):
    from paperpen import versions

    before = run(written, "status", "--porcelain")
    sha = versions.commits(paper)[1]["sha"]
    versions._assemble(paper, versions.resolve(paper, sha), versions._root(
        paper, versions.resolve(paper, sha)))
    tree = versions._root(paper, versions.resolve(paper, sha)) / "src"
    assert (tree / "sec" / "results.tex").read_text() == FIRST
    assert not (written / ".git" / "worktrees").exists()
    assert run(written, "status", "--porcelain") == before


@latex
def test_an_old_commit_compiles_into_its_own_cache(paper):
    from paperpen import versions

    sha = versions.commits(paper)[1]["sha"]
    built = versions.build(paper, sha)
    assert built["built"] and built["pages"] == 1
    assert versions.pdf_of(paper, sha).is_file()
    # and the paper's own build is untouched by it
    assert not paper.pdf.is_file()
    assert versions.page(paper, sha, 1, 1.0).is_file()


@diffable
def test_the_diff_is_latexdiff_compiled(paper):
    from paperpen import versions

    sha = versions.commits(paper)[1]["sha"]
    built = versions.build(paper, f"{sha}..work")
    assert built["kind"] == "diff" and built["pages"] >= 1
    marked = (versions._root(paper, versions.resolve(paper, f"{sha}..work"))
              / "src" / "main.tex").read_text(encoding="utf-8")
    assert "\\DIFadd" in marked and "The transition is gradual" in marked
    # the old tree is not kept: it was only ever an argument to latexdiff
    assert not (versions._root(paper, versions.resolve(paper, f"{sha}..work"))
                / "was").exists()


def test_a_pdf_paper_has_no_source_to_mark_up(board):
    from paperpen import bind, versions

    paper = bind.resolve_paper("dyads")
    assert not versions.is_git(paper)
    with pytest.raises(bind.Refused):
        versions.commits(paper)


def test_the_source_diff_says_what_was_typed(paper):
    from paperpen import versions

    sha = versions.commits(paper)[1]["sha"]
    said = versions.source_diff(paper, sha, "work")
    assert not said["empty"] and "results.tex" in said["stat"]
    assert "+The transition is gradual." in said["patch"]
    assert "README" not in said["patch"]          # not the paper
    assert versions.source_diff(paper, "HEAD", "work")["empty"]


def test_the_page_offers_the_four_panes(paper, written):
    from paperpen.web import create_app

    client = create_app().test_client()
    page = client.get("/paper/corridor/versions")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    for pane in ("pane-old", "pane-new", "pane-diff", "log"):
        assert pane in body

    log = client.get("/paper/corridor/history").get_json()
    assert log["ok"] and len(log["commits"]) == 2
    assert log["working"]["dirty"] is True

    state = client.get("/paper/corridor/version/work").get_json()
    assert state["kind"] == "work" and state["built"] is False
    assert client.get("/paper/corridor/version/nope").status_code == 400
    assert client.get("/paper/nope/versions").status_code == 404


def test_the_server_will_not_run_a_paper_s_own_build_command(written, tmp_path):
    from paperpen import bind, versions

    registry = tmp_path / "config" / "papers.json"
    papers = json.loads(registry.read_text())
    papers["papers"][0]["build"] = "make paper"
    registry.write_text(json.dumps(papers), encoding="utf-8")

    paper = bind.resolve_paper("corridor")
    with pytest.raises(bind.Refused) as refused:
        versions.build(paper, "HEAD")
    assert "from a terminal" in str(refused.value)


def test_a_build_with_the_working_tree_on_one_side_goes_stale(paper):
    """A commit is fixed; the tree you are editing is not, and a diff drawn
    against yesterday's edit without saying so is worse than none."""
    from paperpen import versions

    sha = versions.commits(paper)[1]["sha"]
    for ref in (f"{sha}..work", "work"):
        target = versions._as_paper(paper, versions.resolve(paper, ref), custom=False)
        target.cache.mkdir(parents=True, exist_ok=True)
        target.pdf.write_bytes(b"%PDF-1.4\n")
        (target.cache / "build.json").write_text(json.dumps(
            {"pages": 3, "at": "2026-01-01T00:00:00",
             "commit": run(paper.repo, "rev-parse", "--short", "HEAD")}),
            encoding="utf-8")
        assert versions.state(paper, ref)["stale"] is False

    edited = paper.repo / "sec" / "results.tex"
    edited.write_text(edited.read_text() + "\nAnd a sentence more.\n", encoding="utf-8")

    assert versions.state(paper, f"{sha}..work")["stale"] is True
    assert versions.state(paper, "work")["stale"] is True
    # what is built out of two commits cannot be overtaken by an edit
    pair = f"{sha}..{versions.commits(paper)[0]['sha']}"
    target = versions._as_paper(paper, versions.resolve(paper, pair), custom=False)
    target.cache.mkdir(parents=True, exist_ok=True)
    target.pdf.write_bytes(b"%PDF-1.4\n")
    (target.cache / "build.json").write_text(json.dumps({"pages": 3}), encoding="utf-8")
    assert versions.state(paper, pair)["stale"] is False
