"""What a machine needs before the reader is worth opening, and whether it has it.

Each of these was already a command of its own (`lan`, `tls`, `add`), and
each of them is found by reading the README in the right order, which is the
order nobody reads a README in. `paperpen onboard` walks them once, and this is
the half of it that only looks: every step says whether it is done, and if not,
the command that does it. Nothing here asks or writes, so `onboard --check` can
be run by a script, and run again, and say the same thing.

A step is *needed* or it is not. The tools that build a paper and the password
are needed; the second factor and a certificate are the right answer on most
networks and a choice on some, so they are reported and not insisted on.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from . import auth, bind, config, tls


@dataclass
class Step:
    key: str
    title: str
    done: bool
    said: str           # how it stands, in a few words
    fix: str = ""       # the command that does it, when it is not done
    needed: bool = True


def _tools() -> Step:
    # latexmk and synctex build a paper and anchor a mark to its line; without
    # them a PDF can still be read and marked, but not a repository. git is
    # how a round is committed back. openssl is for the certificate, and the
    # `cryptography` package does the same job on a machine without it.
    missing = [t for t in ("latexmk", "synctex", "git") if not shutil.which(t)]
    if not shutil.which("openssl"):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            missing.append("openssl")
    if not missing:
        return Step("tools", "tools", True, "latexmk, synctex, git and openssl are here")
    return Step("tools", "tools", False, "missing: " + ", ".join(missing),
                "install them with the system's package manager")


def _places() -> Step:
    where = [config.home(), config.cache_root(), config.data_root()]
    absent = [str(p) for p in where if not p.is_dir()]
    if not absent:
        return Step("places", "places", True, str(config.home()))
    return Step("places", "places", False, "not made yet: " + ", ".join(absent),
                "paperpen onboard")


def _password() -> Step:
    if auth.login_off():
        return Step("password", "login", True,
                    "OFF on the network, by choice: anyone there can read and change "
                    "your papers", "paperpen lan")
    if auth.has_password():
        return Step("password", "login", True, f"a password, in {auth.auth_file()}")
    return Step("password", "login", False,
                "not decided, so `serve --lan` will ask first", "paperpen lan")


def _second_factor() -> Step:
    if auth.login_off():
        return Step("totp", "second factor", False, "off, with the login",
                    "paperpen lan", needed=False)
    if auth.has_totp():
        return Step("totp", "second factor", True, "on", needed=False)
    return Step("totp", "second factor", False,
                "off: a password alone on the network", "paperpen lan", needed=False)


def _certificate() -> Step:
    if not tls.exists():
        return Step("tls", "certificate", False,
                    "none: the LAN reader would be in the clear",
                    "paperpen tls", needed=False)
    here = tls.lan_ip()
    if here and not tls.covers(here):
        return Step("tls", "certificate", False,
                    f"does not name {here}, so the tablet will refuse it",
                    "paperpen tls --renew", needed=False)
    return Step("tls", "certificate", True,
                f"good until {tls.not_after() or 'unknown'}", needed=False)


def _papers() -> Step:
    # Not loaded when there is no registry: loading one makes its directory,
    # and this half of onboarding is the half that does not write.
    try:
        count = len(bind.load_papers()) if config.registry_file().is_file() else 0
    except (bind.Refused, OSError, ValueError):
        count = 0
    if count:
        return Step("papers", "shelf", True,
                    f"{count} paper{'' if count == 1 else 's'}", needed=False)
    return Step("papers", "shelf", False, "empty",
                "paperpen add <repo-or-pdf>", needed=False)


def _runners() -> list[Step]:
    # The agent that answers a finished round is Claude Code or Codex, run
    # headless, so the one in force needs to be on this machine and signed in.
    # Everything else works without either, so it is said and not insisted on.
    from . import agent

    try:
        chosen = agent.runner()
    except bind.Refused:
        chosen = ""
    where = {"claude": "install Claude Code and sign in: https://claude.com/claude-code",
             "codex": "install Codex and sign in: https://developers.openai.com/codex/cli"}
    out = []
    for who in agent.RUNNERS:
        in_force = "the runner in force" if who == chosen else "`--runner " + who + "` chooses it"
        if shutil.which(who):
            out.append(Step(who, who, True, f"installed, for the agent that answers rounds; {in_force}",
                            needed=False))
        else:
            out.append(Step(who, who, False,
                            f"not installed: no agent will answer a round" if who == chosen
                            else f"not installed; {in_force}", where[who], needed=False))
    return out


def _aspell() -> Step:
    # the editor underlines misspelt words with aspell, on this machine
    if shutil.which("aspell"):
        return Step("aspell", "aspell", True, "installed, for spelling in the editor", needed=False)
    return Step("aspell", "aspell", False, "not installed: the editor will not check spelling",
                "install aspell and an English dictionary (aspell-en)", needed=False)


def status() -> list[Step]:
    """Every step, in the order onboarding takes them."""
    return [_tools(), _places(), _password(), _second_factor(),
            _certificate(), _papers(), *_runners(), _aspell()]


def ready(steps: list[Step] | None = None) -> bool:
    """Whether everything that is needed is done."""
    return all(s.done for s in (steps if steps is not None else status()) if s.needed)


def report(steps: list[Step]) -> str:
    rows = []
    for s in steps:
        mark = "ok" if s.done else ("--" if s.needed else " .")
        line = f"  {mark}  {s.title:<14} {s.said}"
        if not s.done and s.fix:
            line += f"\n      {'':<14} {s.fix}"
        rows.append(line)
    return "\n".join(rows)
