"""Fixes proposed for a delivered note, chosen and applied, or answered.

The round is written into the paper's repository as a delivery leaves it, and
the source is a small LaTeX file: what is tested is what happens to the file
and to the note, not the build.
"""

import json

import pytest

from paperpen import bind, cli, feedback, rounds

from conftest import NOTE, SESSION, TEX  # noqa: F401  (shared with the other tests)


def two_fixes():
    feedback.propose("dyads", NOTE, "the local density", [
        {"file": "main.tex", "old": "the density of the crowd",
         "new": "the local density of the crowd around the pair"}],
        why="the note asks which density", by="claude")
    feedback.propose("dyads", NOTE, "the density of the whole crowd", [
        {"file": "main.tex", "old": "the density of the crowd",
         "new": "the global density of the crowd"}], by="claude")


def status_of(paper) -> str:
    return next(n for n in rounds.delivered_notes(paper) if n["id"] == NOTE)["status"]


def test_a_proposal_is_written_beside_the_round_it_answers(paper):
    two_fixes()
    written = json.loads((paper.review / SESSION / "feedback.json").read_text())
    assert written["format"] == feedback.FORMAT
    fixes = written["notes"][NOTE]["fixes"]
    assert [f["id"] for f in fixes] == ["1", "2"]
    assert all(f["state"] == feedback.PROPOSED for f in fixes)

    [item] = feedback.items("dyads")
    assert item["anchor"].startswith("The arrangement") and item["source"] == "main.tex:3"
    assert feedback.count(paper) == 1


@pytest.mark.parametrize("old, why", [
    ("the density of the pair", "no longer has"),
    ("density", "2 times"),
])
def test_a_fix_that_could_never_apply_is_refused_when_it_is_proposed(paper, old, why):
    with pytest.raises(bind.Refused, match=why):
        feedback.propose("dyads", NOTE, "x", [{"file": "main.tex", "old": old, "new": "y"}])


def test_a_fix_cannot_reach_outside_the_paper(paper):
    with pytest.raises(bind.Refused):
        feedback.propose("dyads", NOTE, "x", [{"file": "../../etc/passwd.tex",
                                               "old": "a", "new": "b"}])


def test_the_chosen_fix_goes_in_and_the_note_is_closed_with_it(paper):
    two_fixes()
    done = feedback.apply("dyads", NOTE, ["1"])
    assert done["applied"] == ["1"] and done["closed"]

    text = (paper.repo / "main.tex").read_text()
    assert "the local density of the crowd around the pair" in text
    assert "global" not in text

    assert status_of(paper) == "done"
    response = next(n for n in rounds.delivered_notes(paper) if n["id"] == NOTE)["response"]
    assert "the local density" in response and "fix 1" in response

    fixes = {f["id"]: f for f in feedback.items("dyads")[0]["fixes"]}
    assert fixes["1"]["state"] == feedback.APPLIED
    assert fixes["2"]["state"] == feedback.PROPOSED, "the other one is left for later"


def test_a_fix_whose_text_has_moved_is_reported_and_writes_nothing(paper):
    two_fixes()
    (paper.repo / "main.tex").write_text(TEX.replace("the density of the crowd",
                                                     "the crowd's density"))
    before = (paper.repo / "main.tex").read_text()
    done = feedback.apply("dyads", NOTE, ["1"])
    assert done["applied"] == [] and "1" in done["failed"] and not done["closed"]
    assert (paper.repo / "main.tex").read_text() == before
    assert status_of(paper) == "open"
    assert feedback.items("dyads")[0]["fixes"][0]["state"] == feedback.FAILED


def test_a_fix_of_several_edits_goes_in_whole_or_not_at_all(paper):
    feedback.propose("dyads", NOTE, "both sentences", [
        {"file": "main.tex", "old": "the density of the crowd", "new": "the local density"},
        {"file": "main.tex", "old": "side by side", "new": "abreast"}])
    # the second edit's text goes away before the fix is chosen
    (paper.repo / "main.tex").write_text(TEX.replace("side by side", "next to each other"))
    before = (paper.repo / "main.tex").read_text()
    done = feedback.apply("dyads", NOTE, ["1"])
    assert done["failed"] and (paper.repo / "main.tex").read_text() == before


def test_a_reply_goes_in_the_thread_and_the_note_stays_open(paper):
    two_fixes()
    feedback.reply("dyads", NOTE, "neither: the density measured in the corridor")
    [item] = feedback.items("dyads")
    assert item["thread"][-1]["by"] == "you"
    assert "corridor" in item["thread"][-1]["text"]
    assert status_of(paper) == "open"


def test_the_command_line_proposes_replies_and_applies(paper, capsys):
    assert cli.main(["propose", "dyads", NOTE, "--summary", "the local density",
                     "--file", "main.tex", "--old", "the density of the crowd",
                     "--new", "the local density of the crowd", "--by", "claude"]) == 0
    assert cli.main(["reply", "dyads", NOTE, "or say so in the caption",
                     "--by", "claude"]) == 0
    capsys.readouterr()
    assert cli.main(["feedback", "dyads", "--json"]) == 0
    [item] = json.loads(capsys.readouterr().out)["items"]
    assert item["fixes"][0]["by"] == "claude" and item["thread"][0]["by"] == "claude"
    assert cli.main(["apply", "dyads", NOTE, "1"]) == 0
    assert "the local density of the crowd" in (paper.repo / "main.tex").read_text()


def test_a_draft_delivered_as_a_pdf_has_nothing_to_fix(board):
    with pytest.raises(bind.Refused, match="PDF"):
        feedback.reply("dyads", NOTE, "hello")


def test_the_reader_is_given_each_notes_fixes_with_the_paper(paper):
    """The reader offers a note's fixes in the note itself, so /meta, which it
    reads on every load, carries them by note id."""
    from paperpen.web import create_app

    two_fixes()
    got = create_app().test_client().get(f"/paper/{paper.pid}/meta").get_json()
    fixes = got["feedback"][NOTE]["fixes"]
    assert [f["summary"] for f in fixes] == ["the local density", "the density of the whole crowd"]
    assert feedback.by_note(bind.resolve_paper("dyads"))[NOTE]["thread"] == []


def test_a_rebuild_keeps_each_notes_fixes(paper, monkeypatch):
    """The reader takes the reply to Rebuild as its whole META, as it does the
    reply to /meta; without `feedback` in it every fix disappeared from the
    reader, and with `with fixes` on every note, until the page was reloaded."""
    from paperpen.web import create_app

    two_fixes()
    monkeypatch.setattr(bind.paper, "cmd_build", lambda p: None)
    got = create_app().test_client().post(f"/paper/{paper.pid}/build").get_json()
    assert got["ok"]
    assert [f["summary"] for f in got["feedback"][NOTE]["fixes"]] == [
        "the local density", "the density of the whole crowd"]


def test_a_correction_that_leaves_no_choice_is_applied_at_once(paper):
    done = feedback.propose("dyads", NOTE, "the local density", [
        {"file": "main.tex", "old": "the density of the crowd",
         "new": "the local density of the crowd"}], by="claude", now=True)
    assert done["applied"]["closed"]
    assert "the local density of the crowd" in (paper.repo / "main.tex").read_text()
    assert status_of(paper) == "done"
    assert feedback.items("dyads")[0]["fixes"][0]["state"] == feedback.APPLIED


def test_an_applied_fix_is_undone_and_the_note_opens_again(paper):
    feedback.propose("dyads", NOTE, "the local density", [
        {"file": "main.tex", "old": "the density of the crowd",
         "new": "the local density of the crowd"},
        {"file": "main.tex", "old": "side by side", "new": "abreast"}], now=True)
    feedback.undo("dyads", NOTE, "1")
    assert (paper.repo / "main.tex").read_text() == TEX
    assert status_of(paper) == "open"
    assert feedback.items("dyads")[0]["fixes"][0]["state"] == feedback.UNDONE
    with pytest.raises(bind.Refused, match="not applied"):
        feedback.undo("dyads", NOTE, "1")


def test_an_undo_after_the_text_was_changed_again_is_refused(paper):
    feedback.propose("dyads", NOTE, "abreast", [
        {"file": "main.tex", "old": "side by side", "new": "abreast"}], now=True)
    (paper.repo / "main.tex").write_text(TEX.replace("side by side", "shoulder to shoulder"))
    with pytest.raises(bind.Refused, match="changed since"):
        feedback.undo("dyads", NOTE, "1")


def test_an_open_note_nobody_has_answered_is_listed_too(paper):
    """What whoever answers next has to see first is the notes still open."""
    [item] = feedback.items("dyads")
    assert item["id"] == NOTE and item["fixes"] == [] and item["thread"] == []
    assert feedback.count(paper) == 0, "no fix waiting to be chosen"
