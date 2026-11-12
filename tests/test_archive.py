"""The record a paper carries in its own repository, and what it rebuilds.

The local record under the data directory answers "what have I read". The copy
in the paper's own repository answers "what was said about this paper", to
anybody holding the paper, which is the question that outlives this machine.
Only the second one can put a shelf back, and only if it says which paper it
is: `review/<date>/notes.json` has recorded the paper's *name* since the
dashboard, and a name is rewritten whenever a title is fixed.
"""

import json
import subprocess
import tarfile
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest

from paperpen import archive, bind, config, deliver, registry, rounds

TODAY = date.today().isoformat()


def a_note(text: str = "say at which densities") -> dict:
    paper = bind.resolve_paper("dyads")
    hit = next(s for s in bind.paper.layout_cached(paper, 1)["sentences"]
               if "arrangement depends" in s["text"])
    return bind.paper.cmd_note(paper, {"page": 1, "kind": "sentence",
                                       "rect": hit["rects"][0], "rects": hit["rects"],
                                       "note": text, "tag": "SCIENCE"})


def a_git_repo(path: Path) -> None:
    for args in (["init", "-q", "-b", "main"],
                 ["config", "user.email", "a@b.c"], ["config", "user.name", "A"]):
        subprocess.run(["git", "-C", str(path), *args], check=True,
                       capture_output=True)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "the draft"],
                   check=True, capture_output=True)


def test_a_paper_carries_its_own_history_when_it_is_asked_to(board):
    """`record: repo` puts the round and the manifest in the paper's tree, and
    commits both. A round committed without the manifest is a clone that has
    the notes and no way to tell whose they are."""
    paper = bind.resolve_paper("dyads")
    a_git_repo(paper.repo)
    registry.update(paper.pid, record="repo")   # a student's draft: not the default
    a_note()

    done = deliver.finish("dyads")
    assert done["delivery"] == "pdf"            # unchanged: the delivery is the file
    kept = done["record"]
    assert kept["wrote_round"] and kept["committed"]

    said = archive.read_manifest(paper.review)
    assert said["id"] == "dyads-in-a-corridor"  # the id, not the name
    assert said["kind"] == "student" and said["paperpen"] == archive.VERSION
    assert [r["date"] for r in said["rounds"]] == [TODAY]
    assert (paper.review / TODAY / "notes.json").is_file()

    tracked = subprocess.run(["git", "-C", str(paper.repo), "ls-files", "review"],
                             capture_output=True, text=True).stdout
    assert "review/paperpen.json" in tracked and f"review/{TODAY}/notes.json" in tracked


def test_a_clone_of_the_paper_puts_it_back_on_the_shelf(board, tmp_path):
    """The whole point. Everything this machine knows is thrown away, and the
    paper comes back from its repository alone: its id, its kind, its brief,
    and the round that was read."""
    paper = bind.resolve_paper("dyads")
    a_git_repo(paper.repo)
    registry.update(paper.pid, record="repo")
    a_note("the 28 incomplete sessions need saying")
    deliver.finish("dyads")

    elsewhere = tmp_path / "somewhere-else"
    subprocess.run(["git", "clone", "-q", str(paper.repo), str(elsewhere)],
                   check=True, capture_output=True)

    registry.write({"papers": []})                       # the shelf is empty
    import shutil
    shutil.rmtree(config.data_root(), ignore_errors=True)  # and so is the record
    assert bind.load_papers() == []

    got = archive.adopt(str(elsewhere))
    assert got["id"] == "dyads-in-a-corridor"
    assert got["rounds"] == [TODAY]

    back = bind.resolve_paper("dyads-in-a-corridor")
    assert registry.extras(back.pid)["kind"] == "student"
    assert "A first draft" in registry.extras(back.pid)["brief"]
    kept = rounds.delivered(back)[TODAY]
    assert any("28 incomplete" in (n.get("note") or "") for n in kept)


def test_a_repository_that_says_nothing_is_refused_rather_than_guessed(board, tmp_path):
    """Without a manifest the rounds do not say which paper they are. Slugging
    the name again is what would quietly make a second paper."""
    bare = tmp_path / "no-record"
    (bare / "review" / "2026-01-01").mkdir(parents=True)
    with pytest.raises(bind.Refused, match="Register it with"):
        archive.adopt(str(bare))

    (bare / "review" / "2026-01-01" / "notes.json").write_text(
        json.dumps({"paper": "Some paper", "notes": []}), encoding="utf-8")
    with pytest.raises(bind.Refused, match="does not say which paper"):
        archive.adopt(str(bare))


def test_a_manifest_from_a_later_paperpen_is_refused(board, tmp_path):
    review = tmp_path / "newer" / "review"
    review.mkdir(parents=True)
    (review / archive.MANIFEST).write_text(
        json.dumps({"paperpen": archive.VERSION + 1, "id": "x"}), encoding="utf-8")
    with pytest.raises(bind.Refused, match="upgrade rather than guess"):
        archive.read_manifest(review)


def test_the_bundle_leaves_out_what_it_can_make_again(board):
    """The rendered ink is eight times the size of everything else in a round
    and comes back from the strokes, so it is not in the bundle by default."""
    paper = bind.resolve_paper("dyads")
    note = a_note()
    note["hand"] = [[[2.0, 2.0], [40.0, 24.0], [70.0, 4.0]]]
    note["pad"] = {"w": 300, "h": 120}
    bind.paper.cmd_note(paper, note)
    deliver.finish("dyads")

    def names(raw: bytes) -> list[str]:
        with tarfile.open(fileobj=BytesIO(raw)) as tar:
            return tar.getnames()

    lean = names(archive.bundle())
    assert "paperpen/papers.json" in lean
    assert any(n.endswith(f"rounds/{TODAY}/notes.json") for n in lean)
    assert not any("/ink/" in n for n in lean)

    fat = names(archive.bundle(ink=True))
    assert any("/ink/" in n for n in fat), "the rendered ink when it is asked for"

    one = names(archive.bundle(["dyads-in-a-corridor"]))
    assert "paperpen/papers.json" not in one          # one paper travels alone
    assert any(n.endswith(archive.MANIFEST) for n in one)


def test_the_state_can_be_taken_from_the_browser(board):
    """The tablet is where the reading happens and it has no terminal."""
    from paperpen.web import create_app

    a_note()
    deliver.finish("dyads")
    client = create_app().test_client()

    whole = client.get("/state.tar.gz")
    assert whole.status_code == 200
    assert whole.headers["Content-Type"] == "application/gzip"
    assert "paperpen-" in whole.headers["Content-Disposition"]
    with tarfile.open(fileobj=BytesIO(whole.data)) as tar:
        assert "paperpen/papers.json" in tar.getnames()

    one = client.get("/paper/dyads-in-a-corridor/state.tar.gz")
    assert one.status_code == 200
    with tarfile.open(fileobj=BytesIO(one.data)) as tar:
        assert any(n.endswith(archive.MANIFEST) for n in tar.getnames())

    assert client.get("/paper/nope/state.tar.gz").status_code == 404

    # the shelf offers it, because a terminal is what the tablet has not got
    assert 'href="/state.tar.gz"' in client.get("/").get_data(as_text=True)
