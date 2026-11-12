"""Finishing a round: what is recorded here, and what is delivered where."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from paperpen import bind, config, deliver, queue, registry, rounds, shelf

TODAY = date.today().isoformat()


def sentence(paper, phrase: str = "arrangement depends", page: int = 1) -> dict:
    return next(s for s in bind.paper.layout_cached(paper, page)["sentences"]
                if phrase in s["text"])


def a_note(text: str = "say at which densities", tag: str = "SCIENCE") -> dict:
    paper = bind.resolve_paper("dyads")
    hit = sentence(paper)
    return bind.paper.cmd_note(paper, {"page": 1, "kind": "sentence",
                                       "rect": hit["rects"][0], "rects": hit["rects"],
                                       "note": text, "tag": tag})


def test_a_draft_leaves_as_a_pdf_and_is_recorded_here(board):
    a_note()
    done = deliver.finish("dyads")               # kind student, so delivery pdf

    assert done["delivery"] == "pdf"
    marked = Path(done["where"])
    assert marked.is_file() and marked.name == f"draft-notes-{TODAY}.pdf"

    kept = Path(done["record"])
    assert (kept / "notes.json").is_file() and (kept / "NOTES.md").is_file()
    assert kept.is_relative_to(config.data_root())

    assert rounds.open_round(bind.resolve_paper("dyads")) == []  # the round is closed
    assert shelf.shelf()[0]["papers"][0]["state"] == rounds.WAITING


def test_the_record_outlives_the_paper_it_was_about(board, tmp_path):
    """The point of keeping it here: a draft delivered as a PDF has no
    repository, and one that has a repository may have it on another machine."""
    a_note()
    deliver.finish("dyads")
    shutil.rmtree(tmp_path / "paper")

    past = rounds.sent(bind.resolve_paper("dyads"))
    assert [(r["date"], r["notes"], r["delivery"]) for r in past] == [(TODAY, 1, "pdf")]
    assert queue.tally(queue.rows())["total"] == 1


def test_the_repository_wins_over_the_mirror(board):
    """A pass working in the paper's own checkout closes notes there. If this
    side kept its own opinion of their status the two would disagree."""
    registry.update("dyads-in-a-corridor", kind="mine", delivery="")
    note = a_note()
    done = deliver.finish("dyads")
    assert done["delivery"] == "repo"

    mirrored = rounds.round_dir(bind.resolve_paper("dyads"), TODAY) / "notes.json"
    assert json.loads(mirrored.read_text())["notes"][0]["status"] == "open"

    bind.paper.cmd_resolve(bind.resolve_paper("dyads"), note["id"], "done", "reworded")

    assert rounds.sent(bind.resolve_paper("dyads"))[0]["answered"] is True
    assert shelf.shelf()[0]["papers"][0]["state"] == rounds.IDLE
    assert queue.rows() == []
    # and the mirror is untouched, still saying what it said when it was sent
    assert json.loads(mirrored.read_text())["notes"][0]["status"] == "open"


def test_a_second_round_on_one_day_joins_the_first(board):
    a_note("first")
    deliver.finish("dyads")
    a_note("second")
    done = deliver.finish("dyads")
    assert done["notes"] == 1
    assert rounds.sent(bind.resolve_paper("dyads"))[0]["notes"] == 2


def test_an_empty_round_is_refused(board):
    with pytest.raises(bind.Refused):
        deliver.finish("dyads")


def test_the_markup_anchors_on_the_sentence_and_not_on_its_heading():
    """A heading and the sentence after it share a text block in a PDF."""
    assert deliver.anchor_of({"anchor": "2. Method Pairs were identified by hand"}) \
        == "Pairs were identified by hand"
    assert deliver.anchor_of({"anchor": "Below 1.9 steps per second"}) \
        == "Below 1.9 steps per second"


def test_a_handwritten_note_still_reaches_the_pdf(board):
    """Until the strokes are transcribed the note says so, rather than going
    into the margin as an empty comment."""
    paper = bind.resolve_paper("dyads")
    hit = sentence(paper)
    bind.paper.cmd_note(paper, {"page": 1, "kind": "sentence", "rect": hit["rects"][0],
                                "rects": hit["rects"], "note": "",
                                "hand": [[[0, 0], [8, 9]]], "pad": [200, 90]})
    said = deliver.triples(rounds.open_round(paper))
    assert said and "not transcribed" in said[0][2]


def rebuilt_as_one_page(board) -> None:
    """The paper edited and built again: its text is somewhere else now, and
    the page the first delivery's note sat on is gone."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(pymupdf.Point(72, 300), "Revised.\nThe pair walks side by side "
                     "at low density and in file at high density.", fontsize=11)
    doc.save(board / "paper" / "draft.pdf")
    doc.close()
    bind.paper.cmd_build(bind.resolve_paper("dyads"), prerender=False)
    assert bind.paper.build_info(bind.resolve_paper("dyads"))["pages"] == 1


def test_a_later_delivery_of_the_day_keeps_the_earlier_handwriting(board):
    """A second delivery on one day joins the first. The first one's
    handwriting was cropped from the build it was written on, and cropping it
    again from today's later build would show the wrong lines, or a page that
    is not there any more. Both copies keep it: the record here and the
    review/ written into the paper's directory."""
    paper = bind.resolve_paper("dyads")
    hit = sentence(paper, "high density", page=2)
    first = bind.paper.cmd_note(paper, {
        "page": 2, "kind": "sentence", "rect": hit["rects"][0], "rects": hit["rects"],
        "note": "", "ink": [[[72, 110], [180, 112]]],
        "hand": [[[0, 0], [30, 12], [60, 0]]], "pad": [200, 90]})
    done = deliver.finish("dyads", delivery=deliver.FOLDER)
    picture = f"ink/{first['id']}.png"
    kept, review = Path(done["record"]), Path(done["where"])
    was = {where: (where / picture).read_bytes() for where in (kept, review)}

    rebuilt_as_one_page(board)
    paper = bind.resolve_paper("dyads")
    second = bind.paper.cmd_note(paper, {
        "page": 1, "kind": "region", "rect": [70, 285, 200, 305],
        "note": "", "ink": [[[72, 300], [150, 302]]]})
    again = deliver.finish("dyads", delivery=deliver.FOLDER)
    assert Path(again["record"]) == kept and Path(again["where"]) == review

    for where in (kept, review):
        assert (where / picture).read_bytes() == was[where], \
            f"{where}: the first delivery's handwriting was cropped again"
        assert (where / f"ink/{second['id']}.png").is_file(), \
            f"{where}: the second delivery's own note has no picture"
        ids = [n["id"] for n in json.loads((where / "notes.json").read_text())["notes"]]
        assert sorted(ids) == sorted([first["id"], second["id"]])


def test_a_note_delivered_again_is_cropped_again(board):
    """What is kept is the picture of a note from an earlier delivery. A note
    in this delivery is cropped from this build, even if a picture of that
    name is already there."""
    paper = bind.resolve_paper("dyads")
    hit = sentence(paper)
    note = bind.paper.cmd_note(paper, {
        "page": 1, "kind": "sentence", "rect": hit["rects"][0], "rects": hit["rects"],
        "note": "", "ink": [[[72, 100], [160, 101]]]})
    done = deliver.finish("dyads", delivery=deliver.FOLDER)
    kept = Path(done["record"])
    stale = kept / f"ink/{note['id']}.png"
    stale.write_bytes(b"not a picture")

    rounds.write_record(paper, [note], TODAY, bind.paper.build_info(paper))
    assert stale.read_bytes().startswith(b"\x89PNG"), "this delivery's note was not cropped"
