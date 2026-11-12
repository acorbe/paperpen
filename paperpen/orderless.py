"""Orderless matching, as emacs's `orderless` does it, for every search here.

A query is split on spaces into pieces, and a text matches when every piece is
in it, in any order: `density crowd` finds "the crowd's density". A piece that
starts with `!` must not be in it: `density !crowd`. A piece with a capital
letter in it is matched as written; one without ignores case, which is emacs's
smart case. Each piece is literal text, never a regular expression, so a query
typed on a tablet cannot be an error.

The same rules are in `web/orderless.js`, for the pages, so a search in the
browser and one on the server mean the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Piece:
    text: str
    negated: bool
    exact_case: bool

    def found(self, text: str) -> bool:
        return (self.text in text) if self.exact_case else (self.text.lower() in text.lower())


def parse(query: str) -> list[Piece]:
    out = []
    for raw in (query or "").split():
        negated = raw.startswith("!") and len(raw) > 1
        text = raw[1:] if negated else raw
        out.append(Piece(text, negated, text != text.lower()))
    return out


def matches(pieces: list[Piece], text: str) -> bool:
    """Every piece that must be there is, and none that must not be."""
    if not pieces:
        return False
    return all(p.found(text) != p.negated for p in pieces)


def spans(pieces: list[Piece], text: str) -> list[tuple[int, int]]:
    """Where the pieces that must be there are, merged and in order, for a
    highlight. Every occurrence, so a word found twice is marked twice."""
    found = []
    folded = text.lower()
    for p in pieces:
        if p.negated or not p.text:
            continue
        hay, needle = (text, p.text) if p.exact_case else (folded, p.text.lower())
        at = hay.find(needle)
        while at >= 0:
            found.append((at, at + len(needle)))
            at = hay.find(needle, at + len(needle))
    found.sort()
    merged: list[tuple[int, int]] = []
    for a, b in found:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged
