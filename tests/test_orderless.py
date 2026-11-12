"""Orderless search: every piece, in any order; ! for without; smart case."""

import pytest

from paperpen import orderless as o

TEXT = "At high density the pair walks one behind the other."


@pytest.mark.parametrize("query, hit", [
    ("density pair", True),
    ("pair density", True),             # in any order
    ("dens behind", True),              # pieces, not words
    ("density !behind", False),
    ("density !abreast", True),
    ("Density", False),                 # a capital: as written
    ("DENSITY", False),
    ("density crowd", False),           # every piece has to be there
    ("", False),
    ("!", False),                       # a bare ! is the letter, and it is not there
])
def test_orderless(query, hit):
    assert o.matches(o.parse(query), TEXT) is hit


def test_the_highlight_marks_every_piece_found_merged():
    got = o.spans(o.parse("the he !other"), TEXT)
    assert [TEXT[a:b] for a, b in got] == ["the", "the", "the"]
    assert o.spans(o.parse("walk walks"), "she walks") == [(4, 9)]


def test_the_paper_is_searched_sentence_by_sentence(board):
    from paperpen import bind, search

    got = search.sentences(bind.resolve_paper("dyads").pid, "density pair")
    texts = [m["text"] for m in got["matches"]]
    assert texts and all("density" in t and "pair" in t for t in texts)
    assert {m["page"] for m in got["matches"]} == {2}
    assert all(m["rects"] for m in got["matches"])
    assert search.sentences("dyads", "")["matches"] == []


def test_the_source_is_searched_line_by_line(paper):
    from paperpen import search

    got = search.lines(paper.pid, "side pair")
    assert [(m["file"], m["line"]) for m in got["matches"]] == [("main.tex", 4)]
    assert got["matches"][0]["text"][slice(*got["matches"][0]["spans"][0])] == "pair"
    assert search.lines(paper.pid, "side !pair")["matches"] == []


def test_the_pages_share_the_matching(board):
    from paperpen.web import create_app

    got = create_app().test_client().get("/orderless.js")
    assert got.status_code == 200 and b"Orderless" in got.data
