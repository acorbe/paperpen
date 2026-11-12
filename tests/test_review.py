"""Committing what a round's fixes changed, on the branch you are on or on its own."""

import subprocess

import pytest

from paperpen import bind, review

import test_feedback as tf


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_commit_takes_in_the_review_and_nothing_else(repo, paper):
    assert review.state(paper)["to_commit"] == 1
    done = review.commit("dyads")
    assert done["branch"] == "main" and done["notes"] == [tf.NOTE]
    shown = git(repo, "show", "--stat", "--format=%s%n%b", "HEAD")
    assert "1 note applied, 1 by claude" in shown and "the local density (claude)" in shown
    assert "main.tex" in shown and "feedback.json" in shown
    assert "notes-to-self.txt" not in shown, "an edit that is not the review's went in"
    assert review.state(paper)["to_commit"] == 0
    with pytest.raises(bind.Refused, match="waiting to be committed"):
        review.commit("dyads")


def test_a_round_on_its_own_branch_is_taken_back(repo, paper):
    done = review.commit("dyads", on_branch=True)
    assert done["made"] == "paperpen/" + tf.SESSION and done["branch"] == done["made"]
    assert review.state(paper)["review_branch"] and review.state(paper)["base"] == "main"
    took = review.take("dyads")
    assert took["branch"] == "main" and took["how"] == "fast-forward"
    assert "the local density" in (repo / "main.tex").read_text()
    assert not git(repo, "branch", "--list", "paperpen/*")


def test_a_round_on_its_own_branch_is_dropped(repo, paper):
    review.commit("dyads", on_branch=True)
    (repo / "notes-to-self.txt").unlink()
    dropped = review.drop("dyads")
    assert dropped["branch"] == "main"
    assert "the local density" not in (repo / "main.tex").read_text(), "the round is still there"
    assert not git(repo, "branch", "--list", "paperpen/*")


def test_only_a_review_branch_is_taken_or_dropped(repo):
    with pytest.raises(bind.Refused, match="not a review branch"):
        review.drop("dyads")
