"""What should happen next, across every paper on the shelf.

The shelf says which papers want attention and the queue says which notes are
open. Neither says what to do first, and that is the question somebody (or
something) standing above all the repositories actually has: there are four
papers, nine open notes and two stale builds, and the next half hour goes to
one of them.

This is that list, in order, with the command for each. It is deliberately a
small set of kinds rather than a score: triage what has no class, work through
what has been waiting longest, rebuild what has been edited past its build,
and say so when a reading is open and unsent. The last one is your call
and is reported rather than urged, because whether a round is finished is a
judgment about a paper, not an arithmetic about notes.

Nothing here writes anything. It reads the state and says what it sees, which
is what makes it safe to hand to an agent that has not been given a paper's
repository.
"""

from __future__ import annotations

from . import bind, queue, rounds

# The order the kinds come in, and what each is worth when two are the same
# age. A number rather than a position so that `--all` can be read as a list
# and the reason for the order is visible in the answer itself.
WEIGHT = {"classify": 80, "work": 70, "build": 40, "finish": 30, "nothing": 0}


def _for(paper, rows: list[dict], slow: bool) -> list[dict]:
    """Everything worth doing about one paper."""
    mine = [r for r in rows if r["paper"] == paper.pid]
    delivered = [r for r in mine if r["where"] != "this reading"]
    reading = [r for r in mine if r["where"] == "this reading"]
    out = []

    loose = [r for r in delivered if r["tag"] == "AUTO"]
    if loose:
        out.append({
            "do": "classify", "paper": paper.pid, "paper_name": paper.name,
            "count": len(loose), "age": max(r["age"] for r in loose),
            "why": f"{len(loose)} delivered note{'' if len(loose) == 1 else 's'} "
                   f"with no class; the class is what decides who acts on it",
            "run": f"paperpen queue --paper {paper.pid} --unclassified --json",
            "then": "paperpen classify <paper> <id> SCIENCE|LANGUAGE|QUESTION|TODO",
            "where": "",
        })

    if delivered:
        rounds_open = [r for r in rounds.sent(paper) if not r["answered"]]
        oldest = rounds_open[-1]["date"] if rounds_open else ""
        out.append({
            "do": "work", "paper": paper.pid, "paper_name": paper.name,
            "count": len(delivered), "age": max(r["age"] for r in delivered),
            "why": f"{len(delivered)} note{'' if len(delivered) == 1 else 's'} "
                   f"still open from {oldest or 'an earlier round'}",
            "run": f"paperpen rounds {paper.pid}",
            "then": "paperpen resolve <paper> <id> done \"what was changed\"",
            "where": str(paper.review / oldest / "NOTES.md") if oldest else str(paper.repo),
        })

    if slow and paper.repo.is_dir() and paper.pdf.is_file():
        try:
            moved = bind.paper.source_moved(paper)
        except (bind.Refused, OSError, ValueError):
            moved = False
        if moved:
            out.append({
                "do": "build", "paper": paper.pid, "paper_name": paper.name,
                "count": 0, "age": 0,
                "why": "the source has moved past the build, so the reader is "
                       "showing an older paper than the one on disk",
                "run": f"paperpen build {paper.pid}",
                "then": "", "where": str(paper.repo),
            })

    if reading:
        out.append({
            "do": "finish", "paper": paper.pid, "paper_name": paper.name,
            "count": len(reading), "age": max(r["age"] for r in reading),
            "why": f"a reading is open with {len(reading)} "
                   f"note{'' if len(reading) == 1 else 's'} in it, not sent. "
                   f"Whether it is finished is your call",
            "run": f"paperpen finish {paper.pid}",
            "then": "", "where": "",
        })
    return out


def actions(slow: bool = True) -> list[dict]:
    """Everything there is to do, most pressing first.

    `slow` is whether to ask each paper's repository if it has moved since the
    build. That walks the tree for timestamps, which is why the shelf does not
    do it; here it is a command somebody typed, so it is affordable and worth
    knowing.
    """
    rows = queue.rows()
    out = []
    for paper in bind.load_papers():
        out.extend(_for(paper, rows, slow))
    for item in out:
        item["weight"] = WEIGHT.get(item["do"], 0)
    out.sort(key=lambda a: (a["weight"], a["age"], a["count"]), reverse=True)
    return out


def next_one(slow: bool = True) -> dict:
    """The one thing, or an honest nothing."""
    all_of_it = actions(slow)
    if all_of_it:
        return all_of_it[0]
    return {"do": "nothing", "paper": "", "paper_name": "", "count": 0, "age": 0,
            "weight": 0, "why": "nothing open, nothing outstanding, nothing stale",
            "run": "", "then": "", "where": ""}
