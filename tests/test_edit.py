"""Writing the paper, and the map between the source and the page."""

import json
import shutil

import pytest

DOC = r"""\documentclass{article}
\begin{document}
The pair walks side by side at low density.

\input{sec/results}
\end{document}
"""

RESULTS = r"""At high density the pair walks one behind the other.
The transition is gradual and depends on the crowd.
"""

latex = pytest.mark.skipif(not (shutil.which("latexmk") and shutil.which("synctex")),
                           reason="no latexmk or synctex on this machine")


@pytest.fixture
def written(tmp_path, monkeypatch):
    for name, sub in (("PAPERPEN_HOME", "config"), ("PAPERPEN_CACHE", "cache"),
                      ("PAPERPEN_DATA", "data")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(name, str(tmp_path / sub))
    repo = tmp_path / "corridor"
    (repo / "sec").mkdir(parents=True)
    (repo / "main.tex").write_text(DOC, encoding="utf-8")
    (repo / "sec" / "results.tex").write_text(RESULTS, encoding="utf-8")
    (repo / "figure.png").write_bytes(b"\x89PNG not really")
    (tmp_path / "config" / "papers.json").write_text(json.dumps({"papers": [{
        "id": "corridor", "name": "Dyads in a corridor",
        "repo": str(repo), "main": "main.tex"}]}), encoding="utf-8")
    return repo


@pytest.fixture
def paper(written):
    from paperpen import bind
    return bind.resolve_paper("corridor")


def test_what_there_is_to_open_is_the_source_and_the_main_file_first(paper):
    from paperpen import edit

    listed = [f["path"] for f in edit.files(paper)]
    assert listed[0] == "main.tex"
    assert "sec/results.tex" in listed
    assert "figure.png" not in listed          # not a kind of file this edits


def test_nothing_outside_the_paper_can_be_named(paper, tmp_path):
    from paperpen import bind, edit

    secret = tmp_path / "secret.tex"
    secret.write_text("not the paper", encoding="utf-8")
    (paper.repo / "pointer.tex").symlink_to(secret)

    for name in ("../secret.tex", "/etc/passwd", "sec/../../secret.tex",
                 "pointer.tex", "main.pdf"):
        with pytest.raises(bind.Refused):
            edit.read(paper, name)


def test_a_file_is_written_only_when_it_has_not_moved(paper):
    from paperpen import bind, edit

    had = edit.read(paper, "sec/results.tex")
    done = edit.write(paper, "sec/results.tex", RESULTS + "One sentence more.\n",
                      had["stamp"])
    assert done["written"] and done["kept"]
    assert (paper.repo / "sec" / "results.tex").read_text().endswith("more.\n")
    # what it said before is kept, because git has not seen this yet
    assert open(done["kept"]).read() == RESULTS

    # writing the same text again is not a write at all
    now = edit.read(paper, "sec/results.tex")
    assert edit.write(paper, "sec/results.tex", now["text"], now["stamp"])["written"] is False

    # and a file that moved underneath is refused, with nothing written
    with pytest.raises(bind.Refused) as refused:
        edit.write(paper, "sec/results.tex", "wiped", had["stamp"])
    assert "changed on disk" in str(refused.value)
    assert (paper.repo / "sec" / "results.tex").read_text() == now["text"]

    # unless no one claims to know when it was read
    assert edit.write(paper, "sec/results.tex", "wiped")["written"] is True


@latex
def test_the_two_directions_of_synctex_agree(paper):
    from paperpen import bind, edit

    bind.paper.cmd_build(paper, prerender=False)
    # the line is in an \input file, which is the case that a flat map gets wrong
    found = edit.forward(paper, "sec/results.tex", 2)
    assert found["page"] == 1 and len(found["rect"]) == 4

    middle_x = (found["rect"][0] + found["rect"][2]) / 2
    middle_y = (found["rect"][1] + found["rect"][3]) / 2
    back = edit.inverse(paper, found["page"], middle_x, middle_y)
    assert back["file"] == "sec/results.tex"
    assert abs(back["line"] - 2) <= 1


@latex
def test_a_file_that_is_not_the_paper_is_refused_by_the_forward_search_too(paper):
    from paperpen import bind, edit

    bind.paper.cmd_build(paper, prerender=False)
    with pytest.raises(bind.Refused):
        edit.forward(paper, "../secret.tex", 1)
    with pytest.raises(bind.Refused):
        edit.forward(paper, "sec/nothing-here.tex", 1)


def test_the_page_opens_and_a_save_goes_through_it(paper, written):
    from paperpen.web import create_app

    client = create_app().test_client()
    assert client.get("/paper/corridor/edit").status_code == 200

    listing = client.get("/paper/corridor/files").get_json()
    assert listing["ok"] and listing["files"][0]["main"] is True

    had = client.get("/paper/corridor/source?path=main.tex").get_json()
    assert had["text"] == DOC

    saved = client.post("/paper/corridor/source", json={
        "path": "main.tex", "text": DOC + "% a comment\n", "was": had["stamp"]})
    assert saved.get_json()["written"] is True
    assert (written / "main.tex").read_text().endswith("% a comment\n")

    stale = client.post("/paper/corridor/source", json={
        "path": "main.tex", "text": "wiped", "was": had["stamp"]})
    assert stale.status_code == 400 and stale.get_json()["ok"] is False
    assert (written / "main.tex").read_text().endswith("% a comment\n")

    assert client.get("/paper/corridor/source?path=../../secret").status_code == 400


def test_a_pdf_paper_has_nothing_to_edit(board):
    from paperpen.web import create_app

    client = create_app().test_client()
    assert client.get("/paper/dyads-in-a-corridor/edit").status_code == 404
    assert client.get("/paper/dyads-in-a-corridor/files").status_code == 400
