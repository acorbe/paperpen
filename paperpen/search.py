"""Search, orderless, over what a paper is made of.

`sentences` is the paper as it reads: every sentence of every page of the build,
with the boxes it occupies, so the reader can list them and draw them where
they are. `lines` is the paper as it is written: every line of every source
file in its repository, with its number, for the editor. Both are an occur
view waiting to be drawn: every match, in order, with where it is.

A paper is a few hundred sentences and its repository a few thousand lines,
and the page layouts are kept after the first reading, so neither needs an
index.
"""

from __future__ import annotations

from . import bind, edit, orderless

MOST = 500          # matches returned; a query that finds more wants another piece


def sentences(pid: str, query: str) -> dict:
    paper = bind.resolve_paper(pid)
    pieces = orderless.parse(query)
    if not pieces:
        return {"query": query, "matches": [], "more": False}
    pages = bind.paper.build_info(paper).get("pages", 0)
    found, more = [], False
    for page in range(1, pages + 1):
        for s in bind.paper.layout_cached(paper, page).get("sentences", []):
            if orderless.matches(pieces, s["text"]):
                if len(found) >= MOST:
                    more = True
                    break
                found.append({"page": page, "i": s["i"], "text": s["text"], "rects": s["rects"],
                              "spans": orderless.spans(pieces, s["text"])})
        if more:
            break
    return {"query": query, "matches": found, "more": more}


def lines(pid: str, query: str, only: str = "") -> dict:
    """Every line of the paper's source files that matches, or of one file."""
    paper = bind.resolve_paper(pid)
    pieces = orderless.parse(query)
    if not pieces:
        return {"query": query, "matches": [], "more": False}
    files = [only] if only else [f["path"] for f in edit.files(paper)]
    found, more = [], False
    for rel in files:
        try:
            text = edit.read(paper, rel)["text"]
        except bind.Refused:
            continue
        for n, line in enumerate(text.split("\n"), start=1):
            if orderless.matches(pieces, line):
                if len(found) >= MOST:
                    more = True
                    break
                found.append({"file": rel, "line": n, "text": line,
                              "spans": orderless.spans(pieces, line)})
        if more:
            break
    return {"query": query, "matches": found, "more": more}
