"""An agent that answers a delivered round, started by Finish or by hand.

It runs headless in the paper's own checkout with a prompt that says what the
round is and how to answer it, and it answers with paperpen's own commands.
Two runners can do it, chosen per paper, for all papers, or for one run:

    claude      Claude Code, `claude -p`, the default. It is given a short list
                of what it may do, paperpen's commands for answering and reading
                files, and cannot edit a file any other way, run git, or reach
                anything else.
    codex       OpenAI Codex, `codex exec`. Codex has no such list: it is fenced
                by its sandbox instead, which may write the paper's checkout and
                paperpen's own data and cache and nothing else. Git is not
                forbidden to it the way it is to claude; the prompt says not to
                commit, and nothing is committed unless you do it.

    implement   what leaves no choice is applied at once, `propose --apply`, and
                the rest is proposed or asked about: a correction written by
                hand has been decided already
    propose     everything is proposed, and chosen in the notes
    off         nothing is started

and one job that starts from nothing of yours:

    review      it reads the paper on its own and writes notes of its own, each
                with the fix it would make, for you to approve or reject; it is
                asked for, `paperpen review` or the reader's Review button, and
                never started by Finish (see proposals.py)

Every change it makes is a fix on its note, with its diff, so what it did is
read and undone one note at a time, and nothing is committed unless the paper
says so: with `agent_branch`, a round it finished is committed on a branch of
its own, paperpen/<round>, to be taken or dropped.

The command is never hidden. `paperpen agent <paper> --print` prints it, a line
to paste into a terminal, and `paperpen agent <paper>` runs it there, in front
of you. Finish runs the same line in the background, once per round, with its
output in the round's folder beside a status the reader shows.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from . import bind, config, proposals, registry, review, rounds

MODES = ("implement", "propose", "off")
REVIEW = "review"
DEFAULT_FOR = {"mine": "implement", "coauthor": "propose", "student": "off", "referee": "off"}
RUNNERS = proposals.AGENTS            # claude, codex: the name is the executable
MODEL = "opus"                        # claude's model; codex runs what its own config names
MODELS = {"claude": MODEL, "codex": ""}
TIMEOUT = 20 * 60
READING = ["Read", "Glob", "Grep"]
ANSWERING = ["Bash(paperpen feedback:*)", "Bash(paperpen notes:*)",
             "Bash(paperpen propose:*)", "Bash(paperpen reply:*)"]
CHECKING = ["Bash(paperpen build:*)"]
SUGGESTING = ["Bash(paperpen suggest:*)", "Bash(paperpen notes:*)"]


def mode(paper) -> str:
    """The paper's setting, or its kind's default; PAPERPEN_AGENT=off turns every
    one off, which is what a test or a demo wants."""
    if os.environ.get("PAPERPEN_AGENT", "").strip().lower() == "off":
        return "off"
    said = str(registry.entry(paper.pid).get("agent", "") or "").lower()
    if said in MODES:
        return said
    return DEFAULT_FOR.get(registry.extras(paper.pid)["kind"], "off")


def runner(paper=None, asked: str = "") -> str:
    """Who runs: --runner for this run, else the paper's own setting, else
    PAPERPEN_RUNNER for every paper, else claude."""
    said_by = [asked, registry.entry(paper.pid).get("runner", "") if paper is not None else "",
               os.environ.get("PAPERPEN_RUNNER", "")]
    for said in said_by:
        said = str(said or "").strip().lower()
        if said in RUNNERS:
            return said
        if said:
            raise bind.Refused(f"the runner is one of {', '.join(RUNNERS)}, not {said!r}")
    return RUNNERS[0]


def on_branch(paper) -> bool:
    return bool(registry.entry(paper.pid).get("agent_branch", False))


def latest_round(paper) -> str:
    """The newest delivered round with a note still open, which is the one to answer."""
    open_by = {}
    for note in rounds.delivered_notes(paper):
        # an agent's own proposals wait for you, not for another pass of an agent
        if proposals.is_review(note.get("session", "")):
            continue
        if note.get("status", "open") == "open":
            open_by.setdefault(note.get("session", ""), 0)
            open_by[note.get("session", "")] += 1
    live = sorted(s for s in open_by if s)
    if not live:
        raise bind.Refused(f"{paper.pid} has no delivered round with a note still open")
    return live[-1]


# --- what it is told, and what it may do --------------------------------------

def review_prompt(paper, session: str, focus: str = "", most: int = proposals.MOST,
                  who: str = proposals.BY) -> str:
    """What the reviewing run is told: read the paper, find what you would
    change, and write each as a note of your own with its fix."""
    pid = paper.pid
    brief = registry.extras(pid).get("brief", "").strip()
    focus = focus.strip() or ("clarity, consistency of notation, symbols used before they are "
                              "defined, grammar, missing or wrong references, overlong sentences")
    asked = []
    for note in rounds.delivered_notes(paper):
        if proposals.is_agent(note.get("by")) and note.get("status") == "rejected":
            asked.append(f"  - {note.get('anchor', '')[:90]!r}: {note.get('response', '')}")
    purpose = f"What this read is for, in the author's words: {brief}\n" if brief else ""
    rejected = ("\nThese were proposed before and rejected; do not propose them again:\n"
                + "\n".join(asked[-30:]) + "\n") if asked else ""
    return f"""You are reviewing the paper in this repository before its author reads it again.
Its main file is {paper.main}; the typeset PDF is {paper.pdf}.
{purpose}
Look for: {focus}.

Read the source. For each thing you would change, write one note, with its fix:

    paperpen suggest {pid} --by {who} --tag LANGUAGE --note "what is wrong, and why it matters" \\
        --summary "what the fix does" --why "why this fix" --edits - <<'EOF'
    [{{"file": "{paper.main}", "old": "the exact text there now", "new": "what replaces it"}}]
    EOF

--tag is SCIENCE, LANGUAGE, QUESTION or TODO. A note is placed on the page from
the text its fix replaces, so `old` has to be the exact source, long enough to be
found once. A change needed in several places is one note whose fix has several
edits. Where there is no single right rewording (a question, a point about the
science), write the note without a fix, saying where it is:

    paperpen suggest {pid} --by {who} --tag QUESTION --note "..." --file {paper.main} --at "the exact text"

Write at most {most} notes, the ones that matter most first; paperpen stops you
there. Do not note what is a matter of taste. If paperpen refuses a note, correct it
and try again; do not work around it. Never edit a file any other way, and do not
commit: the author approves or rejects each note.
{rejected}
End with one line: how many notes you wrote, and of what kind.
"""


def prompt(paper, session: str, how: str, focus: str = "", most: int = proposals.MOST,
           who: str = proposals.BY) -> str:
    """What the run is told. `who` is the runner's name, which is what its
    proposals and replies are signed with."""
    if how == REVIEW:
        return review_prompt(paper, session, focus, most, who)
    pid = paper.pid
    edit = ("paperpen propose {pid} <note-id> {apply}--by " + who + " --summary \"...\" --why \"...\" "
            "--edits - <<'EOF'\n      [{{\"file\": \"main.tex\", \"old\": \"the exact text there now\", "
            "\"new\": \"what replaces it\"}}]\n      EOF")
    if how == "implement":
        first = (f"- Carry out a correction that leaves no choice: a word struck and replaced, a typo,\n"
                 f"  a sentence to cut, \"say so\", a reference to add. Apply it at once:\n"
                 f"      {edit.format(pid=pid, apply='--apply ')}\n"
                 f"- Where there is a real choice, or the note is a scientific point, propose the\n"
                 f"  same way without --apply: two fixes when there are two good answers.\n")
    else:
        first = (f"- Change nothing: propose every fix, and the author chooses among them.\n"
                 f"      {edit.format(pid=pid, apply='')}\n"
                 f"  Two fixes when there are two good answers.\n")
    return f"""You are answering a round of review notes on the paper in this repository.

The notes are in review/{session}/NOTES.md, and the record is review/{session}/notes.json.
A handwritten note says what it says in its picture, review/{session}/ink/<note-id>.png:
read the picture. Before anything else, run `paperpen feedback {pid}` and read each
note's thread: a reply there from "you" is the author's instruction, and it wins.

Answer only the notes that are still open, one at a time.

{first}- Where you cannot read the handwriting, or need a fact you do not have, ask, with
  your best reading:
      paperpen reply {pid} <note-id> --by {who} "..."
- If a note needs no change, reply saying why.

An edit replaces an exact piece of the source as it is now: take `old` from the
file, long enough to be found once and no longer than what changes and a few words
around it. A change needed in several places at once is one fix with several edits.
If paperpen refuses an edit, correct `old` and try again; do not work around it.
Never edit a file any other way, and do not commit: the author reads the result.

When you are done, run `paperpen feedback {pid}` again and check that every open
note has a fix or a reply. End with one line: how many notes you applied, proposed,
and asked about.
"""


def tools(how: str) -> list[str]:
    if how == REVIEW:
        return READING + SUGGESTING
    return READING + ANSWERING + (CHECKING if how == "implement" else [])


def executable(who: str) -> str:
    return shutil.which(who) or who


def claude() -> str:
    return executable("claude")


def argv_for(who: str, how: str, repo: Path, prompt_text) -> list:
    """The runner's command line, with the prompt where it goes.

    claude: `-p` with the prompt, its model, and the allowlist of what it may
    do. --strict-mcp-config with no config: none of the MCP servers of whoever
    runs it, which the round has no use for and which only slow it and fail.

    codex: `exec` in the paper's checkout, the prompt as the argument, in the
    workspace-write sandbox. There is no allowlist to give it, so the sandbox
    is the fence: the checkout, and paperpen's data and cache, where `propose`
    and `build` write, are the only places it may write, besides the temporary
    directory the sandbox always allows. Its own config is read as it stands:
    the model, unless MODELS names one, and any MCP servers and hooks there,
    which codex has no flag to leave out short of --ignore-user-config.
    """
    if who == "codex":
        return [executable("codex"), "exec", "--sandbox", "workspace-write",
                "-C", str(repo), "--skip-git-repo-check", "--color", "never",
                "--add-dir", str(config.data_root()), "--add-dir", str(config.cache_root()),
                *(["-m", MODELS["codex"]] if MODELS["codex"] else []),
                prompt_text]
    return [executable("claude"), "-p", prompt_text, "--model", MODEL,
            "--strict-mcp-config", "--allowedTools", *tools(how)]


def prompt_file(paper, session: str) -> Path:
    return rounds.round_dir(paper, session) / "agent-prompt.md"


def command(paper, session: str, how: str, focus: str = "",
            most: int = proposals.MOST, who: str = "") -> list[str]:
    """The argv, with the prompt written to the round's folder and read from there."""
    who = runner(paper, who)
    where = prompt_file(paper, session)
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(prompt(paper, session, how, focus, most, who), encoding="utf-8")
    return argv_for(who, how, paper.repo, where.read_text(encoding="utf-8"))


_PROMPT = object()      # where the prompt goes in a line to paste


def shell_line(paper, session: str, how: str, focus: str = "",
               most: int = proposals.MOST, who: str = "") -> str:
    """The same command, as a line to paste into a terminal.

    It carries what the agent needs to find: this paperpen on the PATH, for a
    paperpen run with `uv run` from its checkout is on nobody's PATH and every
    `paperpen propose` the agent tried would be `command not found`; and the
    registry, cache and rounds this one is using, when they are not the usual
    ones. Pasted anywhere, it answers the same round of the same shelf.
    """
    who = runner(paper, who)
    command(paper, session, how, focus, most, who)     # writes the prompt file
    where = prompt_file(paper, session)
    argv = argv_for(who, how, paper.repo, _PROMPT)
    words = [who] + [f'"$(cat {shlex.quote(str(where))})"' if a is _PROMPT else shlex.quote(str(a))
                     for a in argv[1:]]
    env = []
    here = Path(sys.executable).parent
    # always, when this paperpen is a script beside its python: under `uv run`
    # it is on the PATH here and on nobody's in the terminal the line is pasted in
    if (here / "paperpen").exists():
        env.append(f"PATH={shlex.quote(str(here))}:\"$PATH\"")
    for name in ("PAPERPEN_HOME", "PAPERPEN_CACHE", "PAPERPEN_DATA"):
        if os.environ.get(name):
            env.append(f"{name}={shlex.quote(os.environ[name])}")
    return (f"cd {shlex.quote(str(paper.repo))} && "
            + (" ".join(env) + " " if env else "") + " ".join(words))


def _env() -> dict:
    """paperpen as the one the server runs, on the PATH of whatever the runner starts,
    and the same registry, cache and rounds."""
    env = dict(os.environ)
    here = Path(sys.executable).parent
    if (here / "paperpen").exists():
        env["PATH"] = f"{here}{os.pathsep}{env.get('PATH', '')}"
    return env


# --- running it -----------------------------------------------------------------

def status_file(paper, session: str) -> Path:
    return rounds.round_dir(paper, session) / "agent.json"


def _write_status(paper, session: str, **what) -> dict:
    out = status_file(paper, session)
    out.parent.mkdir(parents=True, exist_ok=True)
    was = rounds.read_json(out, {})
    now = {**was, **what, "round": session}
    out.write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
    return now


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def status(paper) -> dict:
    """The agent of the newest round that has had one, as the reader shows it."""
    try:
        # the newest run, whichever round it was for: a review of today and the
        # answer to yesterday's round are both runs on this paper
        runs = [rounds.read_json(f, {}) for f in rounds.rounds_dir(paper).glob("*/agent.json")]
        for said in sorted(runs, key=lambda r: (r.get("started", ""), r.get("round", "")),
                           reverse=True):
            if said.get("state") == "running" and not _alive(said.get("pid", 0)):
                said["state"] = "stopped"
            return said
    except OSError:
        pass
    return {}


def run(pid: str, session: str = "", how: str = "", focus: str = "",
        most: int = proposals.MOST, who: str = "") -> dict:
    """Run it here, now, and wait: in a terminal its output is the terminal's."""
    paper = bind.resolve_paper(pid)
    how = how or mode(paper)
    who = runner(paper, who)
    if how == "off":
        raise bind.Refused(f"the agent is off for {paper.pid}: "
                           f"`paperpen about {paper.pid} --agent implement` turns it on")
    if not paper.repo.is_dir() or paper.is_pdf:
        raise bind.Refused(f"{paper.pid} has no repository for an agent to work in")
    if how == REVIEW:
        session = session or proposals.session_of(by=who)
    session = session or latest_round(paper)
    argv = command(paper, session, how, focus, most, who)
    _write_status(paper, session, state="running", mode=how, runner=who, pid=os.getpid(),
                  started=datetime.now().isoformat(timespec="seconds"), ended="", said="",
                  **({"max": most, "focus": focus} if how == REVIEW else {}))
    try:
        # its output goes wherever this process's does: the terminal, or the
        # round's agent.log when Finish started it
        # stdin closed: codex appends whatever stdin carries to its prompt, and
        # waits on a terminal for it
        done = subprocess.run(argv, cwd=paper.repo, env=_env(), timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
        state = "done" if done.returncode == 0 else "failed"
        said = "" if state == "done" else f"{who} exited with {done.returncode}"
    except subprocess.TimeoutExpired:
        state, said = "failed", f"stopped after {TIMEOUT // 60} minutes"
    except FileNotFoundError:
        state, said = "failed", f"{who} is not installed on this machine"
    committed = ""
    if how == REVIEW:
        made = sum(1 for n in rounds.delivered_notes(paper) if n.get("session") == session
                   and n.get("by") == who)
        return _write_status(paper, session, state=state, said=said, notes=made,
                             ended=datetime.now().isoformat(timespec="seconds"))
    if state == "done" and how == "implement" and on_branch(paper):
        try:
            if review.pending(paper)["fixes"]:
                committed = review.commit(paper.pid, on_branch=True)["made"]
        except bind.Refused as e:
            said = f"not committed: {e}"
    return _write_status(paper, session, state=state, said=said, branch=committed,
                         ended=datetime.now().isoformat(timespec="seconds"))


def start(pid: str, session: str = "", how: str = "", again: bool = False,
          focus: str = "", most: int = proposals.MOST, who: str = "") -> dict:
    """Run it in the background, detached, so a page or a terminal can return.
    Once per round unless asked again; never two at once. A review is asked
    for each time, so asking is enough to run it again."""
    paper = bind.resolve_paper(pid)
    how = how or mode(paper)
    if how == "off":
        raise bind.Refused(f"the agent is off for {paper.pid}")
    if paper.is_pdf or not (paper.repo / ".git").exists():
        raise bind.Refused(f"{paper.pid} has no repository for an agent to work in")
    who = runner(paper, who)
    if status(paper).get("state") == "running":
        raise bind.Refused(f"an agent is already at work on {paper.pid}")
    if how == REVIEW:
        session, again = session or proposals.session_of(by=who), True
    session = session or latest_round(paper)
    was = rounds.read_json(status_file(paper, session), {})
    if was.get("state") == "running" and _alive(was.get("pid", 0)):
        raise bind.Refused(f"{was.get('runner', 'an agent')} is already answering the round of {session}")
    if was and not again:
        raise bind.Refused(f"the round of {session} has been answered once; ask again to rerun")
    log = rounds.round_dir(paper, session) / "agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as out:
        worker = subprocess.Popen(
            [sys.executable, "-m", "paperpen.cli", "agent", paper.pid, "--round", session,
             "--mode", how, "--worker", "--focus", focus, "--max", str(most), "--runner", who],
            stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parent.parent, env=_env(), start_new_session=True)
    # Waited for, behind: a long-running server that never waits for the
    # workers it starts keeps each of them as a zombie, which still answers a
    # signal and so reads as running for ever.
    threading.Thread(target=worker.wait, daemon=True).start()
    return _write_status(paper, session, state="running", mode=how, runner=who, pid=worker.pid,
                         started=datetime.now().isoformat(timespec="seconds"),
                         ended="", said="", log=str(log), notes=0,
                         **({"max": most, "focus": focus} if how == REVIEW else {}))


def stop(pid: str) -> dict:
    paper = bind.resolve_paper(pid)
    said = status(paper)
    if said.get("state") != "running":
        raise bind.Refused("no agent is running for this paper")
    try:
        os.killpg(os.getpgid(said["pid"]), signal.SIGTERM)
    except (OSError, KeyError):
        pass
    return _write_status(paper, said["round"], state="stopped",
                         ended=datetime.now().isoformat(timespec="seconds"), said="stopped by hand")


def after_finish(paper, session: str) -> str:
    """What Finish does once a round is delivered: start the agent if the paper
    wants one. Never a reason for the delivery to fail."""
    try:
        if mode(paper) == "off" or paper.is_pdf or not (paper.repo / ".git").exists():
            return ""
        start(paper.pid, session)
        return "started"
    except (bind.Refused, OSError) as e:
        return f"not started: {e}"
