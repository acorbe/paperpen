"""Committing what a round's fixes changed, on the branch you are on or on one of
its own.

Applying a fix writes the working tree and commits nothing, so what went in can
be read before it becomes history. Reading it is easiest as a commit: the
versions view shows a commit against the one before it, as the source's diff
or as latexdiff. So committing is one step, and it takes in only what the
review did: the files the applied fixes touched and the round's own record,
never whatever else happens to be edited in the working tree.

A round can also go on a branch of its own, `paperpen/<round>`, made from where
you are. Git carries the uncommitted fixes along to it, so nothing is copied
and no second checkout is made. Then it is taken, merged back into the branch
it came from, or dropped, which goes back there and deletes it. Only branches
paperpen made are ever deleted, and nothing is ever pushed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import bind, feedback

PREFIX = "paperpen/"
BASE_KEY = "paperpen-base"      # git config branch.<name>.paperpen-base: where it came from


def _git(repo: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=120)
    if check and done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise bind.Refused(f"git {args[0]}: {said[-1] if said else 'failed'}")
    return done.stdout.strip()


def _need_git(paper) -> Path:
    if paper.is_pdf or not (paper.repo / ".git").exists():
        raise bind.Refused(f"{paper.pid} is not a git repository, so there is nothing to commit")
    return paper.repo


def branch(paper) -> str:
    return _git(paper.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)


def _committed_text(repo: Path, rel: str) -> str:
    """The file as the last commit has it, empty when it is new."""
    done = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                          capture_output=True, text=True, timeout=60)
    return done.stdout if done.returncode == 0 else ""


def pending(paper) -> dict:
    """What a commit would take in now: the applied fixes whose change is in
    the working tree and not yet in the last commit, and their files.

    Told apart by the text, not by the clock: a fix is waiting while what it
    put in occurs more often in the file than in the committed file.
    """
    repo = paper.repo
    head, work, fixes = {}, {}, []
    for fix in feedback.applied_since(paper, ""):
        waiting = False
        for e in fix["edits"]:
            rel = e["file"]
            if rel not in head:
                head[rel] = _committed_text(repo, rel)
                full = repo / rel
                work[rel] = full.read_text(encoding="utf-8", errors="replace") if full.is_file() else ""
            if work[rel].count(e["new"]) > head[rel].count(e["new"]):
                waiting = True
        if waiting:
            fixes.append(fix)
    files = sorted({e["file"] for f in fixes for e in f["edits"]})
    records = sorted({f"review/{f['session']}/{name}" for f in fixes
                      for name in ("feedback.json", "notes.json", "NOTES.md")
                      if (repo / "review" / f["session"] / name).is_file()})
    return {"fixes": fixes, "files": files, "records": records,
            "notes": sorted({f["note"] for f in fixes})}


def state(paper) -> dict:
    """For the reader's header: which branch, and what is waiting to be committed."""
    try:
        if paper.is_pdf or not (paper.repo / ".git").exists():
            return {}
        on = branch(paper)
        return {"branch": on, "review_branch": on.startswith(PREFIX),
                "base": _git(paper.repo, "config", f"branch.{on}.{BASE_KEY}", check=False),
                "to_commit": len(pending(paper)["notes"])}
    except (OSError, bind.Refused, subprocess.SubprocessError):
        return {}


def _message(fixes: list[dict]) -> str:
    notes = sorted({f["note"] for f in fixes})
    sessions = sorted({f["session"] for f in fixes})
    by = {}
    for f in fixes:
        by[f.get("by", "?")] = by.get(f.get("by", "?"), 0) + 1
    who = ", ".join(f"{n} by {w}" for w, n in sorted(by.items()))
    head = (f"review {', '.join(sessions)}: {len(notes)} note{'' if len(notes) == 1 else 's'} "
            f"applied, {who}")
    lines = [f"- {f['note']}: {f['summary']} ({f.get('by', '?')})" for f in fixes]
    return head + "\n\n" + "\n".join(lines) + "\n"


def commit(pid: str, on_branch: bool = False) -> dict:
    """Commit what the round's fixes changed, and nothing else."""
    paper = bind.resolve_paper(pid)
    repo = _need_git(paper)
    now = pending(paper)
    if not now["fixes"]:
        raise bind.Refused("no applied fix is waiting to be committed")
    made = ""
    if on_branch:
        base = branch(paper)
        if base.startswith(PREFIX):
            raise bind.Refused(f"already on {base}, a review branch: commit there, or take it first")
        made = PREFIX + max(f["session"] for f in now["fixes"])
        if _git(repo, "branch", "--list", made, check=False):
            raise bind.Refused(f"{made} is there already: take it or drop it first")
        _git(repo, "switch", "-c", made)
        _git(repo, "config", f"branch.{made}.{BASE_KEY}", base)
    paths = now["files"] + now["records"]
    _git(repo, "add", "--", *paths)
    _git(repo, "commit", "-m", _message(now["fixes"]), "--", *paths)
    return {"paper": paper.pid, "commit": _git(repo, "rev-parse", "--short", "HEAD"),
            "branch": branch(paper), "made": made, "notes": now["notes"], "files": paths}


def _review_branch(paper) -> tuple[str, str]:
    on = branch(paper)
    if not on.startswith(PREFIX):
        raise bind.Refused(f"on {on}, which is not a review branch")
    base = _git(paper.repo, "config", f"branch.{on}.{BASE_KEY}", check=False)
    if not base:
        raise bind.Refused(f"{on} does not say which branch it came from")
    return on, base


def take(pid: str) -> dict:
    """Merge the review branch into the one it came from, and delete it."""
    paper = bind.resolve_paper(pid)
    repo = _need_git(paper)
    on, base = _review_branch(paper)
    _git(repo, "switch", base)
    try:
        _git(repo, "merge", "--ff-only", on)
        how = "fast-forward"
    except bind.Refused:
        _git(repo, "merge", "--no-edit", on)
        how = "merge"
    _git(repo, "branch", "-d", on)
    return {"paper": paper.pid, "branch": base, "took": on, "how": how,
            "commit": _git(repo, "rev-parse", "--short", "HEAD")}


def drop(pid: str) -> dict:
    """Go back to where the review branch came from, and delete it."""
    paper = bind.resolve_paper(pid)
    repo = _need_git(paper)
    on, base = _review_branch(paper)
    if _git(repo, "status", "--porcelain", "--untracked-files=no", check=False):
        raise bind.Refused(f"{on} has changes not committed; commit them or put them "
                           "away before dropping it, so nothing is lost by accident")
    _git(repo, "switch", base)
    _git(repo, "branch", "-D", on)
    return {"paper": paper.pid, "branch": base, "dropped": on}
