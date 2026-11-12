"""The cross-paper view: every open note, and what to do about them first."""

import json

import pytest

from paperpen import agenda, bind, cli, deliver, queue, rounds


def a_note(text: str, tag: str = "AUTO") -> dict:
    paper = bind.resolve_paper("dyads")
    hit = next(s for s in bind.paper.layout_cached(paper, 1)["sentences"]
               if "arrangement depends" in s["text"])
    return bind.paper.cmd_note(paper, {"page": 1, "kind": "sentence",
                                       "rect": hit["rects"][0], "rects": hit["rects"],
                                       "note": text, "tag": tag})


def test_the_queue_is_every_open_note_across_the_papers(board):
    a_note("say at which densities", "SCIENCE")
    a_note("this word again")
    rows = queue.rows()

    assert len(rows) == 2
    assert {r["paper"] for r in rows} == {"dyads-in-a-corridor"}
    assert [r["where"] for r in rows] == ["this reading", "this reading"]
    assert queue.tally(rows)["tags"]["AUTO"] == 1
    assert all("ink" in r for r in rows)          # nothing handwritten here, so ""
    assert all(r["ink"] == "" for r in rows)


def test_a_delivered_note_stays_in_the_queue_until_it_is_answered(board):
    a_note("say at which densities", "SCIENCE")
    deliver.finish("dyads")

    rows = queue.rows()
    assert len(rows) == 1 and rows[0]["where"] != "this reading"
    queue.resolve("dyads-in-a-corridor", rows[0]["id"], "done", "said so")
    assert queue.rows() == []


def test_what_to_do_first_is_triage_then_the_oldest_round(board):
    a_note("this one has no class")
    a_note("say at which densities", "SCIENCE")
    deliver.finish("dyads")

    doing = agenda.actions(slow=False)
    assert [a["do"] for a in doing] == ["classify", "work"]
    assert doing[0]["count"] == 1                 # only the unclassified one
    assert doing[1]["count"] == 2
    assert "2 notes still open" in doing[1]["why"]
    assert doing[0]["run"].startswith("paperpen queue --paper dyads-in-a-corridor")

    # classified, the triage falls away and the work stands
    queue.classify("dyads-in-a-corridor", queue.rows(unclassified=True)[0]["id"], "TODO")
    assert [a["do"] for a in agenda.actions(slow=False)] == ["work"]
    assert agenda.next_one(slow=False)["do"] == "work"


def test_an_open_reading_is_reported_and_not_urged(board):
    a_note("still reading", "TODO")
    doing = agenda.actions(slow=False)

    assert [a["do"] for a in doing] == ["finish"]
    assert "your call" in doing[0]["why"]


def test_an_empty_shelf_says_so_rather_than_inventing_work(board):
    assert agenda.actions(slow=False) == []
    nothing = agenda.next_one(slow=False)
    assert nothing["do"] == "nothing" and nothing["run"] == ""


def test_the_commands_answer_in_json_for_something_that_is_not_a_person(board, capsys):
    a_note("this one has no class")
    a_note("say at which densities", "SCIENCE")
    deliver.finish("dyads")

    capsys.readouterr()                           # finish() said where it went
    assert cli.main(["queue", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["ok"] and said["tally"]["total"] == 2
    assert {r["id"] for r in said["rows"]} == {r["id"] for r in queue.rows()}
    assert said["rows"][0]["source"] == ""        # a PDF paper has no source lines

    assert cli.main(["next", "--json", "--fast"]) == 0
    first = json.loads(capsys.readouterr().out)["next"]
    assert first["do"] == "classify" and first["paper"] == "dyads-in-a-corridor"

    assert cli.main(["queue", "--unclassified", "--json"]) == 0
    only = json.loads(capsys.readouterr().out)
    assert only["tally"]["total"] == 1

    assert cli.main(["queue", "--paper", "dyads", "--older-than", "9000", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == []


def test_the_queue_reads_in_the_terminal_too(board, capsys):
    a_note("say at which densities", "SCIENCE")
    assert cli.main(["queue"]) == 0
    printed = capsys.readouterr().out
    assert "1 open note" in printed and "SCIENCE" in printed
    assert "say at which densities" in printed

    assert cli.main(["next"]) == 0
    assert "finish" in capsys.readouterr().out


def test_a_round_that_was_never_answered_names_the_notes_file(board):
    a_note("say at which densities", "SCIENCE")
    deliver.finish("dyads")
    work = [a for a in agenda.actions(slow=False) if a["do"] == "work"][0]

    # the PDF paper's repo has no review/, so the path is the round we hold
    assert work["where"]
    assert rounds.sent(bind.resolve_paper("dyads"))[0]["answered"] is False


def test_a_note_is_closed_even_when_no_repository_holds_the_round(board):
    """The draft that left as a marked-up PDF.

    Upstream closes a note by walking `review/` in the paper's repository,
    because every paper the dashboard read had one. This one does not, so the
    local record is the only copy of the round, and a note nobody can close
    is a queue that never empties.
    """
    a_note("this one has no class")
    deliver.finish("dyads")
    paper = bind.resolve_paper("dyads")
    assert not (paper.review).exists()            # nothing was delivered there

    row = queue.rows()[0]
    said = queue.classify("dyads-in-a-corridor", row["id"], "LANGUAGE")
    assert said["in_repo"] is False and said["recorded"] is True
    assert queue.rows()[0]["tag"] == "LANGUAGE"

    closed = queue.resolve("dyads-in-a-corridor", row["id"], "done", "reworded it")
    assert closed["recorded"] is True and queue.rows() == []

    kept = rounds.round_dir(paper, closed["session"])
    assert "reworded it" in (kept / "NOTES.md").read_text(encoding="utf-8")

    with pytest.raises(bind.Refused):
        queue.resolve("dyads-in-a-corridor", "no-such-note", "done")
