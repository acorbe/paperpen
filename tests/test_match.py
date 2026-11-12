"""A note picked on a diff lands on the sentence of the build it belongs to.

A latexdiff build is the new text with the deleted text put back, so what is
picked on it is found in the reader's build by its words: the word under the
finger counts most, and a place that is all deletion is refused.
"""

import pytest

from paperpen import bind, versions


def test_the_words_around_the_finger_find_their_sentence(board):
    paper = bind.resolve_paper("dyads")
    words = "walks side by side. At high density it walks".split()
    got = versions.match(paper, words, center=words.index("high"), near=2)
    assert got["page"] == 2
    assert got["text"].startswith("At high density")


def test_deleted_words_around_it_do_not_move_it(board):
    paper = bind.resolve_paper("dyads")
    # what latexdiff shows: the old words struck through, beside the new ones
    words = "we once counted every passer-by The arrangement depends on density".split()
    got = versions.match(paper, words, center=words.index("depends"))
    assert got["page"] == 1 and "arrangement depends on density" in got["text"]


def test_a_place_that_is_all_deletion_is_refused(board):
    paper = bind.resolve_paper("dyads")
    words = "the calibration of the overhead sensor was repeated twice".split()
    with pytest.raises(bind.Refused, match="not in the new version"):
        versions.match(paper, words, center=4)
