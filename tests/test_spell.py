"""Spelling in the editor: what is blanked before aspell reads it, and what
comes back. The blanking is tested everywhere; what aspell says only where it
is installed."""

import shutil

import pytest

from paperpen import spell

needs_aspell = pytest.mark.skipif(not shutil.which("aspell"), reason="aspell is not installed")


def test_what_is_not_prose_is_blanked_to_the_same_length():
    text = ("see \\cref{fig:dyad} and \\citep[p.~3]{corbetta2018}, 50\\% % a coment\n"
            "$\\rho_{crit}$ \\( x_{hihg} \\)\n"
            "\\begin{equation*}\n velocty\n\\end{equation*} walks")
    out = spell.prose(text)
    assert len(out) == len(text) and out.count("\n") == text.count("\n")
    for gone in ("dyad", "corbetta", "coment", "crit", "hihg", "velocty"):
        assert gone not in out
    for kept in ("see", "and", "50\\%", "walks"):
        assert kept in out


def test_the_language_follows_babel(paper):
    assert spell.language(paper) == "en_US"
    main = paper.repo / "main.tex"
    main.write_text(main.read_text().replace(
        "\\begin{document}", "\\usepackage[british]{babel}\n\\begin{document}"))
    assert spell.language(paper) == "en_GB"


@needs_aspell
def test_misspelt_words_come_back_where_they_are(paper):
    text = "The pair walks abrest.\nSee \\cite{corbetta2018} and $\\rho_{crit}$, teh end."
    found = spell.check("dyads", text)
    assert found["available"] and found["lang"] == "en_US"
    lines = text.split("\n")
    got = [(w["line"], lines[w["line"] - 1][w["from"]:w["to"]]) for w in found["words"]]
    assert got == [(1, "abrest"), (2, "teh")]
    assert "abreast" in found["words"][0]["suggest"]


@needs_aspell
def test_an_accepted_word_is_kept_in_the_repository_and_not_marked_again(paper):
    assert [w["word"] for w in spell.check("dyads", "dyads walk")["words"]] == ["dyads"]
    spell.accept("dyads", "dyads")
    spell.accept("dyads", "dyads")
    assert (paper.repo / spell.WORDS).read_text() == "dyads\n"
    assert spell.check("dyads", "dyads walk")["words"] == []


def test_accept_takes_one_word(paper):
    from paperpen import bind

    with pytest.raises(bind.Refused):
        spell.accept("dyads", "two words")


def test_the_routes(paper):
    from paperpen.web.app import create_app

    client = create_app(lan=False).test_client()
    r = client.post(f"/paper/{paper.pid}/spell", json={"text": "walks abrest"})
    assert r.status_code == 200, r.get_json()
    r = client.post(f"/paper/{paper.pid}/spell/accept", json={"word": "abrest"})
    assert r.get_json()["word"] == "abrest"
    assert (paper.repo / spell.WORDS).is_file()
