"""Claude reading the paper first: notes of its own, each with a fix, approved
or rejected one at a time or as a selection.

The real claude is never run. Its notes are written with the same calls the
reviewing run makes, `paperpen suggest`, against the fixture's LaTeX and its
two-page PDF, which has no SyncTeX: so the note is placed by searching the
page for the words of the fix, the fallback a build without SyncTeX gets.
"""

import json
import shutil

import pytest
from conftest import NOTE, SESSION

from paperpen import agent, bind, cli, feedback, proposals, rounds

SIDE = [{"file": "main.tex", "old": "At low density the pair walks side by side.",
         "new": "At low density the pair walks abreast."}]


@pytest.fixture(autouse=True)
def printed(request):
    """The fixture's PDF under the name the LaTeX paper's build would have,
    so a proposal has a page to be placed on, as it does after a build."""
    if "paper" in request.fixturenames:
        paper = request.getfixturevalue("paper")
        shutil.copy(paper.cache / "draft.pdf", paper.pdf)


def suggest_side(**kw):
    return proposals.suggest("dyads", "\"side by side\" is two words for one: abreast",
                             "LANGUAGE", SIDE, summary="abreast", why="shorter", **kw)


def note_of(paper, note_id):
    return next(n for n in rounds.delivered_notes(paper) if n["id"] == note_id)


def test_a_proposal_is_a_note_of_claudes_in_a_round_of_its_own(paper):
    done = suggest_side()
    session = proposals.session_of()
    note = done["note"]
    assert done["session"] == session and note["id"] == f"{session}-01"
    assert note["by"] == "claude" and note["tag"] == "LANGUAGE" and note["status"] == "open"
    # placed on the sentence the fix is about, on the page it is printed on
    assert done["placed"] and note["page"] == 2 and note["kind"] == "sentence"
    assert "side by side" in note["anchor"]
    assert note["source"] == {"file": "main.tex", "line": 4}
    # in the paper's repository and in the local record, and nothing else moved
    kept = json.loads((paper.review / session / "notes.json").read_text())["notes"]
    assert [n["id"] for n in kept] == [note["id"]]
    assert (rounds.round_dir(paper, session) / "notes.json").is_file()
    assert done["fix"]["state"] == feedback.PROPOSED and done["fix"]["by"] == "claude"
    assert "side by side" in (paper.repo / "main.tex").read_text()
    assert feedback.count(paper) == 1          # the shelf says a fix is waiting


def test_approving_puts_the_fix_in_and_closes_the_note_done(paper):
    note = suggest_side()["note"]
    went = proposals.approve("dyads", note["id"])
    assert went["closed"] and went["applied"] == ["1"]
    assert "walks abreast." in (paper.repo / "main.tex").read_text()
    assert note_of(paper, note["id"])["status"] == "done"
    with pytest.raises(bind.Refused, match="already done"):
        proposals.approve("dyads", note["id"])


def test_rejecting_closes_it_with_its_fix_and_keeps_the_reason(paper):
    note = suggest_side()["note"]
    proposals.reject("dyads", note["id"], "side by side is the term in the field")
    assert note_of(paper, note["id"])["status"] == "rejected"
    entry = feedback.read(paper, proposals.session_of())["notes"][note["id"]]
    assert entry["fixes"][0]["state"] == "rejected"
    assert entry["thread"][-1]["text"] == "side by side is the term in the field"
    assert "side by side" in (paper.repo / "main.tex").read_text()
    # and the next run is told, so it does not propose the same thing again
    told = agent.review_prompt(paper, proposals.session_of())
    assert "rejected" in told and "the term in the field" in told


def test_a_remark_with_no_fix_says_where_it_is_and_can_only_be_rejected(paper):
    done = proposals.suggest("dyads", "Which density: the crowd's or the pair's?", "question",
                             file="main.tex", at="the density of the crowd")
    assert "fix" not in done and done["note"]["source"]["line"] == 3
    with pytest.raises(bind.Refused, match="no fix to approve"):
        proposals.approve("dyads", done["note"]["id"])
    proposals.reject("dyads", done["note"]["id"])
    assert note_of(paper, done["note"]["id"])["status"] == "rejected"


@pytest.mark.parametrize("edits, said", [
    ([{"file": "main.tex", "old": "walks in a line", "new": "x"}], "no longer has"),
    ([{"file": "main.tex", "old": "density", "new": "x"}], "2 times"),
    ([{"file": "../outside.tex", "old": "a", "new": "b"}], None),
])
def test_a_proposal_that_could_never_apply_writes_nothing(paper, edits, said):
    with pytest.raises(bind.Refused, match=said):
        proposals.suggest("dyads", "x", "LANGUAGE", edits, summary="x")
    assert not (paper.review / proposals.session_of()).exists()


def test_one_note_per_place_and_the_tag_is_decided(paper):
    suggest_side()
    with pytest.raises(bind.Refused, match="already about that text"):
        suggest_side()
    with pytest.raises(bind.Refused, match="--tag"):
        proposals.suggest("dyads", "x", "AUTO", file="main.tex", at="side by side")


def test_a_run_stops_at_its_cap(paper):
    session = proposals.session_of()
    agent._write_status(paper, session, state="running", mode=agent.REVIEW, pid=agent.os.getpid(),
                        started="2000-01-01T00:00:00", max=1)
    suggest_side()
    with pytest.raises(bind.Refused, match="as many notes as it may"):
        proposals.suggest("dyads", "x", "QUESTION", file="main.tex", at="the density of the crowd")


def test_the_agent_that_answers_your_rounds_leaves_claudes_alone(paper):
    suggest_side()
    assert agent.latest_round(paper) == SESSION
    proposals.reject("dyads", f"{proposals.session_of()}-01")
    feedback.propose("dyads", NOTE, "x", [{"file": "main.tex", "old": "the density of the crowd",
                                           "new": "the local density"}], now=True)
    proposals.suggest("dyads", "y", "QUESTION", file="main.tex", at="side by side")
    with pytest.raises(bind.Refused, match="no delivered round"):
        agent.latest_round(paper)


def test_a_selection_is_decided_each_on_its_own(paper):
    first = suggest_side()["note"]["id"]
    second = proposals.suggest("dyads", "say which density", "SCIENCE",
                               [{"file": "main.tex", "old": "the density of the crowd",
                                 "new": "the local density of the crowd"}],
                               summary="local")["note"]["id"]
    remark = proposals.suggest("dyads", "a figure would help", "TODO",
                               file="main.tex", at="\\begin{document}")["note"]["id"]
    done = proposals.decide("dyads", [first, second, remark], "approve")
    assert done["done"] == [first, second] and "no fix" in done["failed"][remark]
    text = (paper.repo / "main.tex").read_text()
    assert "abreast" in text and "local density" in text
    done = proposals.decide("dyads", [remark], "reject", "not now")
    assert done["done"] == [remark]


def test_the_command_line_suggests_approves_and_rejects(paper, capsys):
    assert cli.main(["suggest", "dyads", "--tag", "language", "--note", "two words for one",
                     "--summary", "abreast", "--file", "main.tex",
                     "--old", SIDE[0]["old"], "--new", SIDE[0]["new"]]) == 0
    out = capsys.readouterr().out
    first = out.split()[0]
    assert "main.tex:4" in out and "page 2" in out
    assert cli.main(["suggest", "dyads", "--tag", "QUESTION", "--note", "which?",
                     "--file", "main.tex", "--at", "the density of the crowd"]) == 0
    second = capsys.readouterr().out.split()[0]
    assert cli.main(["approve", "dyads", first]) == 0
    assert "abreast" in (paper.repo / "main.tex").read_text()
    assert cli.main(["reject", "dyads", second, "--why", "clear enough"]) == 0
    assert note_of(paper, second)["status"] == "rejected"


def test_the_review_run_may_only_read_and_suggest(paper, capsys):
    assert agent.tools(agent.REVIEW) == agent.READING + agent.SUGGESTING
    assert cli.main(["review", "dyads", "--focus", "notation", "--max", "7", "--print"]) == 0
    line = capsys.readouterr().out
    assert "paperpen suggest:*" in line and "paperpen propose" not in line
    told = (rounds.round_dir(paper, proposals.session_of()) / "agent-prompt.md").read_text()
    assert "Look for: notation." in told and "at most 7 notes" in told
    assert "A first draft." in told                 # the paper's brief, as written


def test_a_review_run_writes_its_notes_and_says_how_many(paper, monkeypatch, tmp_path):
    import os
    import stat

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text("#!/bin/sh\n"
                    "paperpen suggest dyads --tag LANGUAGE --note 'two words for one' "
                    "--summary abreast --file main.tex "
                    "--old 'side by side.' --new 'abreast.'\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    done = agent.run("dyads", how=agent.REVIEW, focus="language", most=5)
    assert done["state"] == "done" and done["notes"] == 1, done
    assert done["mode"] == "review" and done["max"] == 5
    assert agent.status(paper)["round"] == proposals.session_of()
    [waiting] = proposals.waiting(paper)
    assert waiting["note"] == "two words for one"


def test_the_reader_is_given_the_author_and_the_page_decides(paper):
    from paperpen.web import create_app

    note = suggest_side()["note"]
    client = create_app().test_client()
    meta = client.get("/paper/dyads-in-a-corridor/meta").get_json()
    mine = [n for n in meta["past"] if n["id"] == note["id"]]
    assert mine and mine[0]["by"] == "claude"
    assert meta["feedback"][note["id"]]["fixes"][0]["state"] == "proposed"
    items = client.get("/paper/dyads-in-a-corridor/feedback.json").get_json()["items"]
    assert {i["by"] for i in items} == {"", "claude"}
    got = client.post("/paper/dyads-in-a-corridor/proposals/decide",
                      json={"notes": [note["id"]], "what": "reject", "why": "no"}).get_json()
    assert got["ok"] and got["done"] == [note["id"]]
    assert note_of(paper, note["id"])["status"] == "rejected"


def test_a_pdf_has_nothing_to_review(board):
    with pytest.raises(bind.Refused):
        proposals.suggest("dyads", "x", "LANGUAGE", file="draft.pdf", at="x")
    with pytest.raises(bind.Refused):
        agent.start("dyads", how=agent.REVIEW)


def test_plain_text_is_what_the_pdf_will_say():
    assert proposals.plain("the \\emph{local} density~$\\rho$ % note\n") == "the local density"


@pytest.mark.skipif(not (shutil.which("latexmk") and shutil.which("synctex")),
                    reason="no latexmk or synctex on this machine")
def test_in_a_real_build_synctex_finds_the_page_and_the_sentence(tmp_path, monkeypatch):
    """Two pages of real LaTeX: the sentence the fix is about is on the second,
    in a paragraph of several, and that is where the note lands."""
    for name, sub in (("PAPERPEN_HOME", "config"), ("PAPERPEN_CACHE", "cache"),
                      ("PAPERPEN_DATA", "data")):
        (tmp_path / sub).mkdir()
        monkeypatch.setenv(name, str(tmp_path / sub))
    repo = tmp_path / "corridor"
    repo.mkdir()
    filler = " ".join(["Pedestrians walk in a corridor and are observed from above."] * 60)
    (repo / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + filler + "\n\n\\newpage\n"
        "The pairs are tracked for a minute. At low density the pair walks side by side.\n"
        "At high density it walks one behind the other.\n\\end{document}\n", encoding="utf-8")
    (tmp_path / "config" / "papers.json").write_text(json.dumps({"papers": [{
        "id": "corridor", "name": "Dyads", "repo": str(repo), "main": "main.tex"}]}))
    paper = bind.resolve_paper("corridor")
    bind.paper.cmd_build(paper, prerender=False)
    done = proposals.suggest("corridor", "two words for one", "LANGUAGE",
                             [{"file": "main.tex", "old": "walks side by side",
                               "new": "walks abreast"}], summary="abreast")
    note = done["note"]
    import pymupdf

    with pymupdf.open(paper.pdf) as doc:
        printed_on = next(i + 1 for i, page in enumerate(doc)
                          if "side by side" in " ".join(page.get_text().split()))
    assert printed_on >= 2
    assert done["placed"] and note["page"] == printed_on and note["source"]["line"] == 6
    assert note["anchor"].startswith("At low density the pair walks side by side")


def test_codex_writes_its_notes_in_a_round_named_after_it(paper):
    """A note said to be codex's goes into <date>-codex, is an agent's note
    like claude's, and is refused in claude's round."""
    from datetime import date
    done = proposals.suggest(paper.pid, "the sentence is a question", "QUESTION",
                             file="main.tex", at="side by side", by="codex")
    assert done["session"] == date.today().isoformat() + "-codex"
    assert done["note"]["by"] == "codex" and proposals.is_agent("codex")
    assert proposals.by_of(done["session"]) == "codex"
    assert done["note"]["id"] in {n["id"] for n in proposals.waiting(bind.resolve_paper(paper.pid))}
    with pytest.raises(bind.Refused):
        proposals.suggest(paper.pid, "wrong round", "TODO", file="main.tex", at="side by side",
                          by="codex", session=proposals.session_of())
    with pytest.raises(bind.Refused):
        proposals.session_of(by="gemini")
    assert not proposals.is_agent("you") and not proposals.is_review("2026-01-01")


def test_the_queue_names_the_agent_that_wrote_a_note(paper):
    """A proposal waiting in the queue says whose it is, claude's or codex's,
    and the tally counts each; one set of names serves all of them."""
    from paperpen import queue, rounds
    assert proposals.AGENTS is rounds.AGENTS and queue.AGENTS is rounds.AGENTS
    proposals.suggest(paper.pid, "the sentence is a question", "QUESTION",
                      file="main.tex", at="side by side", by="codex")
    rows = [r for r in queue.rows() if r["paper"] == paper.pid]
    assert sorted(r["who"] for r in rows if r["who"] != queue.YOU) == ["codex"]
    assert queue.tally(rows)["agents"] == {"codex": 1}
    assert queue.rows(who="codex") and not queue.rows(who="claude")
