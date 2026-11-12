"""The shelf, the reader, and the thumbnail that makes a shelf recognisable."""

from paperpen import registry, rounds, shelf
from paperpen.web import create_app


def test_a_paper_with_no_rounds_is_idle(board):
    groups = shelf.shelf()
    assert [g["state"] for g in groups] == [rounds.IDLE]
    card = groups[0]["papers"][0]
    assert card["pages"] == 2
    assert card["kind"] == "student"
    # a student's draft is handed over as a file, not as a commit
    assert card["delivery"] == "pdf"
    assert card["thumb"] is True
    assert card["synctex"] is False  # a PDF with no source behind it


def test_a_note_opens_a_round(board):
    from paperpen import bind

    paper = bind.resolve_paper("dyads")
    bind.paper.cmd_note(paper, {"page": 1, "rect": [70, 88, 300, 100],
                                "note": "say which density"})
    card = shelf.shelf()[0]["papers"][0]
    assert card["state"] == rounds.OPEN
    assert (card["open"], card["unclassified"]) == (1, 1)


def test_the_kind_picks_the_delivery_and_can_be_overridden(board):
    assert registry.extras("dyads-in-a-corridor")["delivery"] == "pdf"
    registry.update("dyads-in-a-corridor", delivery="folder")
    assert registry.extras("dyads-in-a-corridor")["delivery"] == "folder"
    registry.update("dyads-in-a-corridor", kind="mine", delivery="")
    assert registry.extras("dyads-in-a-corridor")["delivery"] == "repo"


def test_the_pages_the_server_serves(board):
    client = create_app().test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert "Pedestrian dyads in a corridor" in page.get_data(as_text=True)
    assert "A first draft" in page.get_data(as_text=True)  # the brief is on the card

    thumb = client.get("/paper/dyads-in-a-corridor/thumb.png")
    assert thumb.status_code == 200 and thumb.data[:4] == b"\x89PNG"

    reader = client.get("/paper/dyads-in-a-corridor")
    assert reader.status_code == 200
    body = reader.get_data(as_text=True)
    assert 'const PID = "dyads-in-a-corridor";' in body
    assert "{pid}" not in body and "{{" not in body

    assert client.get("/paper/dyads-in-a-corridor/meta").get_json()["build"]["pages"] == 2
    assert client.get("/paper/dyads-in-a-corridor/layout/1").get_json()["sentences"]
    assert client.get("/paper/nope").status_code == 404


def test_a_refusal_is_a_response_and_not_the_end_of_the_process(board):
    """Upstream's `die` raises SystemExit, which a web framework does not catch."""
    client = create_app().test_client()
    answer = client.get("/paper/dyads-in-a-corridor/layout/99")
    assert answer.status_code == 400
    assert "outside 1..2" in answer.get_json()["error"]


def test_the_passthrough_and_the_shelf_mean_the_same_registry(board, capsys):
    """`paperpen add` and `paperpen shelf` are two views of one file.

    Upstream reads `PAPERS_FILE`, a module global whose default is the checkout
    it lives in. Anything that reaches upstream without going through `bind`
    keeps that default, and then `add` writes where `shelf` does not read: the
    paper you have just registered is not on the shelf, and `where` names a
    file nobody wrote to.
    """
    from paperpen import bind, cli, config

    assert cli.main(["list"]) == 0
    assert "Pedestrian dyads" in capsys.readouterr().out
    assert bind.paper.PAPERS_FILE == config.registry_file()
    assert not (bind.UPSTREAM.parent / "papers.json").exists()


def test_the_registry_is_made_on_a_machine_that_has_never_run_this(board, tmp_path,
                                                                   monkeypatch):
    """Upstream writes papers.json in place and assumes its parent exists.

    In the dashboard it is a file at the top of the checkout, so it always
    does. Here it is under `~/.config`, so the very first `paperpen add` on a
    new machine came back as a FileNotFoundError out of pathlib.
    """
    from paperpen import bind, config

    fresh = tmp_path / "never-used" / "paperpen"
    monkeypatch.setenv("PAPERPEN_HOME", str(fresh))
    assert not fresh.exists()
    bind.load_papers()
    assert config.registry_file().parent.is_dir()


def test_what_a_paper_is_can_be_said_at_the_command_line(board, capsys):
    """The three fields paperpen adds were reachable only from a POST the
    shelf never makes, so every paper added at the command line arrived as
    `mine`, delivering into a repository: wrong for a draft that came over as
    a PDF, and wrong in the direction that writes into somebody else's tree."""
    from paperpen import cli, registry

    assert cli.main(["about", "dyads", "--kind", "referee",
                     "--brief", "For PRE. Sec. 3 and the statistics in Fig. 4."]) == 0
    out = capsys.readouterr().out
    assert "referee" in out and "For PRE" in out

    now = registry.extras("dyads-in-a-corridor")
    assert (now["kind"], now["delivery"]) == ("referee", "pdf")

    # an explicit delivery overrides the kind's own, and an empty one gives it back
    assert cli.main(["about", "dyads", "--delivery", "folder"]) == 0
    assert registry.extras("dyads-in-a-corridor")["delivery"] == "folder"
    assert cli.main(["about", "dyads", "--delivery", ""]) == 0
    assert registry.extras("dyads-in-a-corridor")["delivery"] == "pdf"


def test_every_page_says_paperpen_in_its_title(board):
    """So the open tabs can be found by searching for paperpen."""
    import re

    from paperpen import bind

    client = create_app().test_client()
    pid = bind.resolve_paper("dyads").pid
    for url in ("/", "/queue", "/archived", f"/paper/{pid}", f"/paper/{pid}/versions",
                f"/paper/{pid}/feedback"):
        page = client.get(url).get_data(as_text=True)
        title = re.search(r"<title>(.*?)</title>", page, re.S).group(1)
        assert title.endswith("· paperpen"), f"{url}: {title!r}"
    reader = client.get(f"/paper/{pid}").get_data(as_text=True)
    assert "<title>Pedestrian dyads in a corridor · paperpen</title>" in reader
