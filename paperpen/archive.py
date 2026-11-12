"""The record a paper carries in its own repository, and the bundle you can
download.

A reading is kept in two places and they answer different questions. The local
record under `~/.local/share/paperpen` answers "what have I read", across every
paper, including the ones that were handed over as a PDF and have no repository
at all. The copy in the paper's own repository answers "what was said about
this paper", to anyone who has the paper, which is the question that outlives
the machine paperpen happened to be running on.

The second copy is the one that makes a shelf reconstructable. `review/<date>/`
has been written there since the dashboard, but it records the paper's *name*
and not its id, and nothing at all about what kind of read it was. A name is
not an identity: it is rewritten when a title is fixed, and the id is
deliberately not allowed to move with it. So a manifest sits beside the rounds
and says which paper this is, how it is read, and which rounds exist.

    <paper repo>/review/
      paperpen.json         this manifest
      2026-09-17/notes.json, NOTES.md, ink/*.png
      2026-09-22/...

`paperpen adopt <repo-or-git-url>` reads that back: it registers the paper and
rebuilds the local record from the rounds it finds, so a new machine with a
clone of the paper has the shelf the old one had.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from . import bind, config, registry, rounds

MANIFEST = "paperpen.json"

# The manifest's own shape. A reader that does not know a version refuses it
# rather than guessing at fields it has never seen: the record is the thing
# that has to survive, so it says plainly when it is from a future it does not
# understand.
VERSION = 1

# Rendered from the strokes in notes.json against the built page, so they come
# back with `paperpen ink`. They are also 7 MB of a 916 KB round, which is the
# difference between a repository that can hold a year of readings and one
# that cannot.
DERIVED = "ink"


def round_index(paper) -> list[dict]:
    """Every round this paper has, as the manifest lists them."""
    out = []
    for r in rounds.sent(paper):
        out.append({k: r[k] for k in ("date", "notes", "open", "done", "rejected",
                                      "answered", "delivery", "where") if k in r})
    return out


def manifest(paper) -> dict:
    """What a repository has to carry for the shelf to be rebuilt from it."""
    extra = registry.extras(paper.pid)
    return {
        "paperpen": VERSION,
        "id": paper.pid,
        "name": paper.name,
        "main": paper.main,
        "kind": extra["kind"],
        "brief": extra["brief"],
        "delivery": extra["delivery"],
        "written": datetime.now().isoformat(timespec="seconds"),
        "rounds": round_index(paper),
    }


def write_manifest(paper) -> Path:
    """Refresh the manifest in the paper's own repository."""
    paper.review.mkdir(parents=True, exist_ok=True)
    out = paper.review / MANIFEST
    out.write_text(json.dumps(manifest(paper), indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def read_manifest(review: Path) -> dict:
    """The manifest out of a `review/` directory, or {} if there is none."""
    try:
        got = json.loads((review / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict):
        return {}
    if got.get("paperpen", 0) > VERSION:
        raise bind.Refused(
            f"{review / MANIFEST} is version {got['paperpen']} and this "
            f"paperpen reads {VERSION}; upgrade rather than guess at it")
    return got


def rounds_in(review: Path) -> list[str]:
    """The round directories present, whatever the manifest claims.

    The directories are the record and the manifest is an index of it. When
    they disagree the directories win: a round can be committed by one machine
    and the manifest refreshed by another, and losing a reading because an
    index was stale is not a trade worth making.
    """
    return sorted(d.name for d in review.glob("*/") if (d / "notes.json").is_file())


def add_to_tar(tar: tarfile.TarFile, path: Path, arcname: str, ink: bool) -> None:
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(path)
        if not ink and DERIVED in rel.parts:
            continue
        tar.add(item, arcname=f"{arcname}/{rel}")


def bundle(pids: list[str] | None = None, ink: bool = False) -> bytes:
    """The state, as one .tar.gz, in memory.

    The registry goes in as it stands and the rounds go in per paper. The
    rendered ink stays out unless it is asked for: it is derived, and it is
    eight times the size of everything else put together.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        reg = config.registry_file()
        if reg.is_file() and pids is None:
            tar.add(reg, arcname="paperpen/papers.json")
        for paper in bind.load_papers():
            if pids is not None and paper.pid not in pids:
                continue
            here = config.paper_data(paper.pid)
            if here.is_dir():
                add_to_tar(tar, here, f"paperpen/{paper.pid}", ink)
            # One paper on its own travels without the registry, so it carries
            # its manifest instead: enough to put it back on a shelf.
            if pids is not None:
                raw = (json.dumps(manifest(paper), indent=2,
                                  ensure_ascii=False) + "\n").encode()
                info = tarfile.TarInfo(f"paperpen/{paper.pid}/{MANIFEST}")
                info.size = len(raw)
                info.mtime = int(datetime.now().timestamp())
                tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def clone_to(url: str, into: Path) -> Path:
    """A shallow clone of the paper's repository, to read its record out of."""
    into.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "clone", "-q", "--depth", "50", url, str(into)],
                          capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        raise bind.Refused(f"could not clone {url}:\n{proc.stderr.strip()[-400:]}")
    return into


def looks_like_git(source: str) -> bool:
    """A git address rather than a directory on this machine."""
    return (source.endswith(".git") or "://" in source
            or (":" in source and not Path(source).expanduser().exists()))


def restore_rounds(paper, review: Path) -> list[str]:
    """Copy the repository's rounds into the local record.

    The repository's copy wins wherever both exist, which is the same rule the
    shelf already reads by: a note closed in the paper's own checkout is closed
    where the person editing the paper can see it, and this side does not keep
    a second opinion.
    """
    brought = []
    for session in rounds_in(review):
        src, dst = review / session, rounds.round_dir(paper, session)
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.rglob("*")):
            if not item.is_file():
                continue
            out = dst / item.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out)
        brought.append(session)
    return brought


def adopt(source: str, main: str = "", keep: Path | None = None) -> dict:
    """Put a paper back on the shelf from the record in its own repository.

    `source` is a directory or a git address. What comes back is whatever the
    manifest says the paper was: its id above all, because the id is in the
    URLs, the cache paths and every note already sent, and re-deriving it from
    a name that has since been corrected would quietly make a second paper.
    """
    if looks_like_git(source):
        if keep is None:
            raise bind.Refused("a git address needs somewhere to clone into; "
                               "pass --into <dir>")
        repo = clone_to(source, keep)
    else:
        repo = Path(source).expanduser().resolve()
    if not repo.is_dir():
        raise bind.Refused(f"no such directory: {repo}")

    review = repo / "review"
    said = read_manifest(review)
    sessions = rounds_in(review) if review.is_dir() else []
    if not said and not sessions:
        raise bind.Refused(
            f"{repo} carries no paperpen record: no review/{MANIFEST} and no "
            f"round beneath review/. Register it with `paperpen add` instead.")

    pid = said.get("id", "")
    if not pid:
        # An older repository, written before the manifest: the rounds are
        # there and the identity is not, so it is said out loud rather than
        # guessed, because a guessed id makes a duplicate paper silently.
        raise bind.Refused(
            f"{review / MANIFEST} is missing, so this record does not say which "
            f"paper it is. The rounds are there ({', '.join(sessions)}); run "
            f"`paperpen add` and then `paperpen record <paper>` to write the "
            f"manifest for next time.")

    entry = {"id": pid, "name": said.get("name") or repo.name,
             "repo": str(repo), "main": main or said.get("main", "")}
    for field in ("kind", "brief", "delivery"):
        if said.get(field):
            entry[field] = said[field]
    raw = registry.read()
    raw["papers"] = [e for e in raw["papers"] if e.get("id") != pid] + [entry]
    registry.write(raw)

    paper = bind.resolve_paper(pid)
    brought = restore_rounds(paper, review)
    return {"id": pid, "name": entry["name"], "repo": str(repo),
            "main": entry["main"], "rounds": brought}


def keep_in_repo(paper, notes: list[dict], session: str, info: dict,
                 commit: bool = True) -> dict:
    """Leave the round, and the manifest indexing it, in the paper's repository.

    For a round delivered as a commit this mostly finds the work already done:
    upstream's export has written `review/<session>/` and committed it. What is
    added is the manifest, which has to be committed too or a clone carries the
    rounds and no way to tell which paper they belong to.

    For a round delivered as a PDF it writes the round as well. That is what
    `record: repo` asks for on a paper whose notes leave as a file: the file is
    what the author reads, and the repository is where the history lives. It
    is not the default for somebody else's draft, because writing into another
    person's tree is their business and not ours.
    """
    review = paper.review
    where = review / session
    wrote_round = False
    if not (where / "notes.json").is_file():
        bind.paper.write_review(paper, notes, session, info)
        wrote_round = True
    said = write_manifest(paper)

    out = {"review": str(where), "manifest": str(said),
           "wrote_round": wrote_round, "committed": False}
    if not (commit and (paper.repo / ".git").is_dir()):
        return out

    rel = [str(said.relative_to(paper.repo))]
    if wrote_round:
        rel.append(str(where.relative_to(paper.repo)))
    subprocess.run(["git", "-C", str(paper.repo), "add", "--", *rel],
                   capture_output=True, text=True, timeout=120)
    done = subprocess.run(
        ["git", "-C", str(paper.repo), "commit", "-m",
         f"paperpen: the record of {session}", "--", *rel],
        capture_output=True, text=True, timeout=120)
    # Nothing to commit is the ordinary case when the export has just
    # committed the round and the manifest has not moved, so it is not an
    # error; anything else is reported with what git said.
    out["committed"] = done.returncode == 0
    if done.returncode != 0:
        out["git"] = (done.stdout + done.stderr).strip()[-300:]
    return out
