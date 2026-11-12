"""The contract for a paper's own repository is paperpen's, in paperpen's commands.

It is printed by `paperpen howto` and its path is written into every NOTES.md
that goes out, so it must be a file that exists and say nothing of anybody's
machine.
"""

from paperpen import bind, cli


def test_howto_prints_paperpens_own_contract(board, capsys):
    assert cli.main(["howto"]) == 0
    said = capsys.readouterr().out
    assert said.startswith("# Putting a paper on the shelf")
    assert "paperpen resolve" in said
    for foreign in ("scripts/paper.py", "~/workspace", "dashboard"):
        assert foreign not in said


def test_the_path_a_notes_file_points_at_is_there():
    assert bind.paper.howto_path() == bind.HOWTO
    assert bind.HOWTO.is_file()
