"""Which file is the paper, and which papers are on the shelf.

A repository can hold more than one .tex that builds on its own, and the one
that is built has to be chosen. Papers are put on the shelf and taken off it
from the shelf page as well as from the command line.
"""

import json
import shutil

import pymupdf
import pytest

from paperpen import bind, edit, registry, rounds
from paperpen.web import create_app

latex = pytest.mark.skipif(not shutil.which("latexmk"), reason="needs latexmk")


def tex_paper(board):
    """The fixture's paper as a LaTeX repository with two documents and a chapter."""
    repo = board / "paper"
    (repo / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nA.\n"
                                   "\\input{chapter}\n\\end{document}\n", encoding="utf-8")
    (repo / "reply.tex").write_text("% the reply to the referees\n\\documentclass{letter}\n"
                                    "\\begin{document}\nB.\n\\end{document}\n", encoding="utf-8")
    (repo / "chapter.tex").write_text("\\section{C}\nC.\n", encoding="utf-8")
    reg = board / "config" / "papers.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    data["papers"][0].update(main="main.tex")
    reg.write_text(json.dumps(data), encoding="utf-8")
    return bind.resolve_paper("dyads")


def test_the_files_say_which_could_be_the_main_one(board):
    paper = tex_paper(board)
    found = {f["path"]: f for f in edit.files(paper)}
    assert found["main.tex"]["main"] and found["main.tex"]["candidate"]
    assert found["reply.tex"]["candidate"] and not found["reply.tex"]["main"]
    assert not found["chapter.tex"]["candidate"]


def test_another_document_can_be_made_the_main_one(board):
    paper = tex_paper(board)
    done = edit.set_main(paper, "reply.tex")
    assert done == {"id": paper.pid, "main": "reply.tex", "was": "main.tex"}
    assert bind.resolve_paper(paper.pid).main == "reply.tex"


@pytest.mark.parametrize("rel, why", [
    ("chapter.tex", "no \\\\documentclass"),
    ("draft.pdf", "not a kind of file"),
    ("nothing.tex", "no such file"),
    ("../elsewhere.tex", "not in this paper"),
])
def test_only_a_document_can_be_the_main_one(board, rel, why):
    paper = tex_paper(board)
    with pytest.raises(bind.Refused, match=why):
        edit.set_main(paper, rel)
    assert bind.resolve_paper(paper.pid).main == "main.tex"


def test_the_main_file_is_chosen_at_the_command_line_too(board, capsys):
    from paperpen import cli

    paper = tex_paper(board)
    assert cli.main(["about", paper.pid, "--main", "reply.tex"]) == 0
    assert "main      reply.tex" in capsys.readouterr().out


def a_pdf(where, text="A referee's draft."):
    where.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text(pymupdf.Point(72, 96), text, fontsize=11)
    doc.save(where / "draft.pdf")
    doc.close()
    return where / "draft.pdf"


def test_a_pdf_is_put_on_the_shelf_from_its_path(board):
    got = bind.add(str(a_pdf(board / "referee")))
    assert got["pages"] == 1
    entry = registry.entry(got["id"])
    assert entry["main"] == "draft.pdf"
    assert len(registry.read()["papers"]) == 2


def test_a_paper_that_will_not_build_leaves_the_shelf_as_it_was(board):
    if not shutil.which("latexmk"):
        pytest.skip("no latexmk to fail with")
    broken = board / "broken"
    broken.mkdir()
    (broken / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\n"
                                     "\\undefinedcommand\n", encoding="utf-8")
    before = (board / "config" / "papers.json").read_text(encoding="utf-8")
    with pytest.raises(bind.Refused):
        bind.add(str(broken))
    assert (board / "config" / "papers.json").read_text(encoding="utf-8") == before


def _titled(where, title):
    where.mkdir(parents=True, exist_ok=True)
    (where / "main.tex").write_text(
        "\\documentclass{article}\n\\title{" + title + "}\n"
        "\\begin{document}\\maketitle\\end{document}\n", encoding="utf-8")
    return where


@latex
def test_two_papers_cannot_share_an_id(board):
    """A second folder whose title slugifies the same is refused.

    The id is in the URL, the cache path and every note already sent, so two
    entries carrying one id make `resolve_paper` answer for whichever comes
    first. A variant of a manuscript on a branch or in a worktree is the way
    this happens in practice: same title, different folder.
    """
    title = "A paper with a title of its own"
    first = bind.add(str(_titled(board / "one", title)))
    before = (board / "config" / "papers.json").read_text(encoding="utf-8")
    with pytest.raises(bind.Refused) as refusal:
        bind.add(str(_titled(board / "two", title)))
    assert first["id"] in str(refusal.value)
    assert "--name" in str(refusal.value)
    assert (board / "config" / "papers.json").read_text(encoding="utf-8") == before


@latex
def test_a_name_of_its_own_gets_a_twin_onto_the_shelf(board):
    title = "A paper with a title of its own"
    first = bind.add(str(_titled(board / "one", title)))
    second = bind.add(str(_titled(board / "two", title)),
                      name="The same paper, folded differently")
    assert second["id"] != first["id"]
    ids = [e["id"] for e in registry.read()["papers"]]
    assert len(ids) == len(set(ids))


@latex
def test_forget_takes_a_paper_off_the_shelf(board):
    """The command line reaches registry.remove, which only the shelf page could."""
    from paperpen import cli
    got = bind.add(str(_titled(board / "throwaway", "A throwaway")))
    assert cli.cmd_forget([got["id"]]) == 0
    assert registry.entry(got["id"]) == {}


@latex
def test_forget_refuses_a_paper_with_open_notes_unless_told(board):
    """Open notes stay in the repository, but they leave the queue and the
    shelf, so forgetting is not silent while any are outstanding."""
    from paperpen import cli
    got = bind.add(str(_titled(board / "noted", "A paper somebody read")))
    paper = bind.resolve_paper(got["id"])
    bind.paper.cmd_note(paper, {"page": 1, "rect": [50, 50, 200, 70],
                                "note": "something to come back to"})
    with pytest.raises(bind.Refused) as refusal:
        cli.cmd_forget([paper.pid])
    assert "still open" in str(refusal.value) and "--yes" in str(refusal.value)
    assert registry.entry(paper.pid) != {}
    assert cli.cmd_forget([paper.pid, "--yes"]) == 0
    assert registry.entry(paper.pid) == {}


def test_taking_a_paper_off_the_shelf_keeps_its_rounds(board):
    paper = bind.resolve_paper("dyads")
    kept = rounds.rounds_dir(paper)
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "marker").write_text("a round was here", encoding="utf-8")
    registry.remove(paper.pid)
    assert registry.read()["papers"] == []
    assert (kept / "marker").is_file() and (board / "paper" / "draft.pdf").is_file()


def test_the_shelf_page_adds_and_removes(board):
    client = create_app().test_client()
    got = client.post("/papers/add", json={"where": str(a_pdf(board / "referee")),
                                           "kind": "referee"}).get_json()
    assert got["ok"], got
    assert registry.extras(got["id"])["kind"] == "referee"
    refused = client.post("/papers/add", json={"where": str(board / "nowhere")}).get_json()
    assert not refused["ok"] and "no such folder" in refused["error"]

    gone = client.post(f"/paper/{got['id']}/remove").get_json()
    assert gone["ok"] and registry.entry(got["id"]) == {}
    page = client.get("/").get_data(as_text=True)
    assert "A referee" not in page
