"""The three demo films: each GIF is committed beside the frames it was made
from, the README shows it, and it stays short and small enough to be read on a
project page. The films themselves are made by driving the app in headless
Chrome (see docs/development.md, "The demo"), which a test run does not do."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"

FILMS = [("paperpen.gif", "frames"),
         ("review.gif", "frames-review"),
         ("editor.gif", "frames-editor")]


@pytest.mark.parametrize("gif,frames", FILMS)
def test_each_film_is_its_frames_short_and_small(gif, frames):
    folder = DEMO / frames
    listed = json.loads((folder / "frames.json").read_text(encoding="utf-8"))
    used = {f["png"] for f in listed}
    there = {p.name for p in folder.glob("*.png")}
    assert used <= there, f"{frames} names images it does not have: {used - there}"
    assert there <= used, f"{frames} holds images no frame uses: {there - used}"
    assert all(f["caption"] for f in listed), f"{frames} has a frame with no caption"
    seconds = sum(f["hold"] for f in listed)
    assert 15 <= seconds <= 25, f"{gif} runs {seconds:.1f}s"
    assert (DEMO / gif).stat().st_size < 1_000_000, f"{gif} is a megabyte or more"


def test_the_readme_shows_every_film():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for gif, _ in FILMS:
        assert f"(demo/{gif})" in readme, f"README does not show demo/{gif}"
