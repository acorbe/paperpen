"""Claude answering a delivered round: the command, its limits, and its runs.

The real claude is never run here. A stand-in on the PATH records how it was
called and, for the full run, does what the agent would: it applies a fix with
`paperpen propose --apply` from inside the paper's checkout.
"""

import json
import os
import stat
import time

import pytest

from paperpen import agent, bind, cli, deliver, registry, review, rounds

import test_feedback as tf


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A `claude` that writes down its arguments and where it ran, then runs a
    script of our choosing, which is what the agent would have done."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "claude-was-called.json"
    script = bin_dir / "claude"

    def install(body: str = "", exit_code: int = 0):
        script.write_text(
            "#!/bin/sh\n"
            f"python3 -c 'import json, os, sys; json.dump({{\"argv\": sys.argv[1:], \"cwd\": os.getcwd()}}, "
            f"open(\"{seen}\", \"w\"))' \"$@\"\n"
            f"{body}\n"
            f"exit {exit_code}\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    install()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    return install, seen


def test_it_is_on_for_your_own_papers_and_off_for_a_students(paper, monkeypatch):
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    assert agent.mode(paper) == "implement"            # kind mine
    registry.update(paper.pid, kind="coauthor")
    assert agent.mode(bind.resolve_paper(paper.pid)) == "propose"
    registry.update(paper.pid, kind="student")
    assert agent.mode(bind.resolve_paper(paper.pid)) == "off"
    monkeypatch.setenv("PAPERPEN_AGENT", "off")
    registry.update(paper.pid, kind="mine")
    assert agent.mode(bind.resolve_paper(paper.pid)) == "off"


def test_the_setting_is_said_at_the_command_line(paper, capsys, monkeypatch):
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    assert cli.main(["about", paper.pid, "--agent", "propose", "--branch"]) == 0
    out = capsys.readouterr().out
    assert "agent     propose" in out and "own branch" in out
    assert agent.on_branch(bind.resolve_paper(paper.pid))


def test_the_command_can_be_printed_and_run_by_hand(paper, capsys, monkeypatch):
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    assert cli.main(["agent", paper.pid, "--print"]) == 0
    line = capsys.readouterr().out.strip()
    where = agent.prompt_file(paper, tf.SESSION)
    assert line.startswith(f"cd {paper.repo} && ")
    assert f'claude -p "$(cat {where})" --model opus --strict-mcp-config' in line
    # the shelf the test runs on, so that pasted anywhere it answers this round
    assert f"PAPERPEN_HOME={os.environ['PAPERPEN_HOME']}" in line
    assert "'Bash(paperpen propose:*)'" in line and "'Bash(paperpen build:*)'" in line
    said = where.read_text()
    assert f"review/{tf.SESSION}/NOTES.md" in said and "--apply" in said
    assert "do not commit" in said


def test_proposing_only_is_told_so_and_may_not_build(paper):
    said = agent.prompt(paper, tf.SESSION, "propose")
    assert "--apply" not in said and "Change nothing" in said
    assert "Bash(paperpen build:*)" not in agent.tools("propose")
    assert not any(t.startswith(("Edit", "Write", "Bash(git")) for t in agent.tools("implement"))


def test_a_run_is_claude_in_the_papers_checkout_with_only_those_tools(paper, fake_claude):
    install, seen = fake_claude
    done = agent.run(paper.pid)
    assert done["state"] == "done" and done["round"] == tf.SESSION
    called = json.loads(seen.read_text())
    assert called["cwd"] == str(paper.repo)
    tools_given = called["argv"][called["argv"].index("--allowedTools") + 1:]
    assert tools_given == agent.tools("implement")


def test_a_failed_run_says_so(paper, fake_claude):
    install, _ = fake_claude
    install(exit_code=3)
    done = agent.run(paper.pid)
    assert done["state"] == "failed" and "exited with 3" in done["said"]


def test_what_it_applies_goes_on_its_own_branch_when_asked(repo, paper, fake_claude):
    install, _ = fake_claude
    # the fixture applied a fix and closed the note; open it again for the agent
    from paperpen import feedback
    feedback.undo(paper.pid, tf.NOTE, "1")
    install(body=f"paperpen propose {paper.pid} {tf.NOTE} --apply --by claude "
                 "--summary abreast --file main.tex --old 'side by side' --new abreast")
    registry.update(paper.pid, agent_branch=True)
    done = agent.run(paper.pid)
    assert done["state"] == "done", done
    assert done["branch"] == "paperpen/" + tf.SESSION
    assert review.state(paper)["review_branch"]
    assert "abreast" in (repo / "main.tex").read_text()
    review.take(paper.pid)
    assert review.state(paper)["branch"] == "main"


def test_finish_hands_a_round_delivered_into_a_repository_on(board, monkeypatch):
    """Finish calls it for a round delivered into the paper's repository, and
    the paper decides; a PDF paper has nothing for it to work in."""
    import subprocess

    import test_rounds

    registry.update("dyads-in-a-corridor", kind="mine", delivery="repo")
    subprocess.run(["git", "-C", str(board / "paper"), "init", "-q"], check=True)
    for k, v in (("user.name", "t"), ("user.email", "t@example.org")):
        subprocess.run(["git", "-C", str(board / "paper"), "config", k, v], check=True)
    handed = []
    real = agent.after_finish
    # only this function is replaced, and only it is put back: undoing every
    # patch would also put back the registry the test is kept away from
    monkeypatch.setattr(agent, "after_finish", lambda p, s: handed.append(s) or "started")
    test_rounds.a_note()
    done = deliver.finish("dyads")
    assert handed == [done["session"]] and done["agent"] == "started"
    monkeypatch.setattr(agent, "after_finish", real)
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    assert agent.after_finish(bind.resolve_paper("dyads"), done["session"]) == ""


def test_started_behind_it_runs_once_and_says_how_it_went(repo, paper, fake_claude):
    from paperpen import feedback
    feedback.undo(paper.pid, tf.NOTE, "1")                # an open note to answer
    said = agent.start(paper.pid)
    assert said["state"] == "running"
    for _ in range(150):
        if agent.status(paper).get("state") in ("done", "failed"):
            break
        time.sleep(0.1)
    assert agent.status(paper)["state"] == "done", agent.status(paper)
    assert (rounds.round_dir(paper, tf.SESSION) / "agent.log").is_file()
    with pytest.raises(bind.Refused, match="answered once"):
        agent.start(paper.pid)



def test_pasted_anywhere_the_line_finds_this_paperpen(paper, monkeypatch):
    """paperpen run from its checkout is on nobody's PATH, and the agent calls
    it by name: the printed line puts it there."""
    import sys
    from pathlib import Path

    line = agent.shell_line(paper, tf.SESSION, "implement")
    if (Path(sys.executable).parent / "paperpen").exists():
        assert f"PATH={Path(sys.executable).parent}:" in line


# --- the runner: claude unless said, codex when said ---------------------------

def test_the_runner_is_claude_unless_the_paper_or_the_machine_says_codex(paper, monkeypatch):
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    assert agent.runner(paper) == "claude"
    monkeypatch.setenv("PAPERPEN_RUNNER", "codex")
    assert agent.runner(paper) == "codex"
    registry.update(paper.pid, runner="claude")           # the paper wins over the machine
    assert agent.runner(bind.resolve_paper(paper.pid)) == "claude"
    assert agent.runner(bind.resolve_paper(paper.pid), "codex") == "codex"   # and --runner over both
    monkeypatch.setenv("PAPERPEN_RUNNER", "gemini")
    registry.update(paper.pid, runner="")
    with pytest.raises(bind.Refused):
        agent.runner(bind.resolve_paper(paper.pid))


def test_the_runner_is_set_and_said_at_the_command_line(paper, capsys, monkeypatch):
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    assert cli.main(["about", paper.pid, "--runner", "codex"]) == 0
    assert "runner    codex" in capsys.readouterr().out
    assert registry.entry(paper.pid)["runner"] == "codex"
    assert cli.main(["about", paper.pid, "--runner", "default"]) == 0
    assert "runner    claude   (the default" in capsys.readouterr().out
    assert "runner" not in registry.entry(paper.pid)


def test_codexs_command_is_exec_in_the_checkout_fenced_by_its_sandbox(paper, capsys, monkeypatch):
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    assert cli.main(["agent", paper.pid, "--print", "--runner", "codex"]) == 0
    line = capsys.readouterr().out.strip()
    where = agent.prompt_file(paper, tf.SESSION)
    assert line.startswith(f"cd {paper.repo} && ")
    assert f"codex exec --sandbox workspace-write -C {paper.repo} --skip-git-repo-check" in line
    assert f'--add-dir {os.environ["PAPERPEN_DATA"]}' in line
    assert line.endswith(f'"$(cat {where})"')
    assert "--allowedTools" not in line and "claude -p" not in line
    said = where.read_text()
    assert "--by codex" in said and "--by claude" not in said
    assert f"review/{tf.SESSION}/NOTES.md" in said and "do not commit" in said


def test_a_codex_run_is_codex_in_the_papers_checkout(paper, fake_claude, tmp_path, monkeypatch):
    """The stand-in is the same script under the other name: what matters is
    which one is called, where, and how it is told."""
    install, seen = fake_claude
    import shutil
    shutil.copy(tmp_path / "bin" / "claude", tmp_path / "bin" / "codex")
    monkeypatch.setenv("PAPERPEN_RUNNER", "codex")
    done = agent.run(paper.pid)
    assert done["state"] == "done" and done["runner"] == "codex"
    called = json.loads(seen.read_text())
    assert called["cwd"] == str(paper.repo)
    assert called["argv"][:3] == ["exec", "--sandbox", "workspace-write"]
    assert "--by codex" in called["argv"][-1]
    assert agent.status(paper)["runner"] == "codex"


def test_a_missing_or_failing_runner_is_named(paper, fake_claude, monkeypatch):
    install, _ = fake_claude
    monkeypatch.setenv("PAPERPEN_RUNNER", "codex")      # not on the fake PATH
    monkeypatch.setenv("PATH", str(fake_claude[1].parent / "bin"))
    done = agent.run(paper.pid)
    assert done["state"] == "failed" and done["said"] == "codex is not installed on this machine"


def test_a_review_by_codex_is_a_round_of_its_own(paper, capsys, monkeypatch):
    monkeypatch.delenv("PAPERPEN_AGENT", raising=False)
    from paperpen import proposals
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    assert cli.main(["review", paper.pid, "--print", "--runner", "codex"]) == 0
    line = capsys.readouterr().out.strip()
    session = proposals.session_of(by="codex")
    assert session.endswith("-codex") and proposals.is_review(session)
    assert "codex exec" in line and str(agent.prompt_file(paper, session)) in line
    said = agent.prompt_file(paper, session).read_text()
    assert "paperpen suggest" in said and "--by codex" in said


def test_onboard_says_which_runners_are_there_and_which_runs(monkeypatch):
    from paperpen import onboard
    real = onboard.shutil.which
    monkeypatch.setattr(onboard.shutil, "which",
                        lambda name, *a, **k: f"/usr/bin/{name}" if name in agent.RUNNERS
                        else real(name, *a, **k))
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    steps = {s.key: s for s in onboard.status()}
    assert "claude" in steps and "codex" in steps
    assert "the runner in force" in steps["claude"].said
    assert "--runner codex" in steps["codex"].said
    monkeypatch.setenv("PAPERPEN_RUNNER", "codex")
    steps = {s.key: s for s in onboard.status()}
    assert "the runner in force" in steps["codex"].said


def test_onboard_says_when_the_runner_in_force_is_missing(monkeypatch):
    from paperpen import onboard
    real = onboard.shutil.which
    monkeypatch.setattr(onboard.shutil, "which",
                        lambda name, *a, **k: None if name in agent.RUNNERS
                        else real(name, *a, **k))
    monkeypatch.delenv("PAPERPEN_RUNNER", raising=False)
    steps = {s.key: s for s in onboard.status()}
    assert "no agent will answer a round" in steps["claude"].said
    assert "--runner codex" in steps["codex"].said
