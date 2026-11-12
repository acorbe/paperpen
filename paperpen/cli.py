"""The command line.

Everything the dashboard's script already does is passed straight through to
it, unchanged, so there is one implementation of `build`, `note`, `export` and
the rest and no second opinion about what they mean. What is added here is the
server, and `shelf`, which is the same view the home page shows.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from . import (agenda, agent, archive, auth, bind, config, deliver, feedback, onboard,
               proposals, queue as queue_mod, review,
               registry, rounds, qr, serving, shelf as shelf_mod, tls, versions)

# The subcommands upstream owns. Anything in here is its argv, not ours.
# `export` is not passed through: finishing a round records it here first and
# then delivers it the way the paper is delivered, which upstream's export,
# written when every paper had a repository, does not do.
PASSTHROUGH = {"list", "add", "check", "howto", "build", "meta", "render", "layout",
               "anchor", "note", "drop", "notes", "classify", "resolve"}

USAGE = """paperpen: read a paper, mark it up, send the notes back

  paperpen onboard [--check]             everything a new machine needs, in
                                         order: the password, the certificate,
                                         a first paper; --check only says
  paperpen serve [--port N] [--host H] [--lan]
                                         the shelf and the reader
  paperpen shelf                         the same, in the terminal
  paperpen queue [--json] [--paper P] [--tag T] [--unclassified] [--older-than N]
                                         every open note, from every paper
  paperpen next [--json] [--all]         what to do first, and the command
  paperpen rounds <paper>                every round, and how each one stands
  paperpen finish <paper> [--as repo|pdf|folder] [--no-commit]
                                         close the open round and deliver it
  paperpen forget <paper> [--yes]        take a paper off the shelf; its
                                         repository, rounds and cache stay
  paperpen about <paper> [--kind K] [--delivery D] [--brief "..."]
                                         what a paper is, and who is waiting
  paperpen record <paper>                refresh review/paperpen.json in its repo
  paperpen feedback <paper> [--json]     the fixes proposed for its notes, and
                                         the replies; chosen at /paper/<id>/feedback
  paperpen propose <paper> <note> --summary S --file F --old O --new N [--why W]
                                         propose a fix: exact text, and what
                                         replaces it (or --edits JSON)
  paperpen reply <paper> <note> "..."    a word in the note's thread
  paperpen apply <paper> <note> <fix>... put the chosen fixes in the source
  paperpen undo <paper> <note> <fix>     take an applied fix back out
  paperpen commit <paper> [--branch]     commit what the fixes changed, nothing else
  paperpen agent <paper> [--runner claude|codex] [--print] [--background] [--status] [--stop]
                                         the agent answering the newest round:
                                         here, as a command to run, or behind;
                                         Claude Code unless the runner is codex
  paperpen branch <paper> take|drop      merge a review branch back, or throw it away
  paperpen review <paper> [--focus "clarity, notation"] [--max N] [--runner R] [--background|--print]
                                         the agent reads the paper first and writes
                                         notes of its own, each with its fix
  paperpen suggest <paper> --tag T --note "..." --summary S --file F --old O --new N
                                         what that run writes: one note, placed
                                         from the text it fixes (or --edits JSON,
                                         or --at TEXT for a remark with no fix)
  paperpen approve <paper> <note> [<fix>]
                                         put a proposal's fix in, close it done
  paperpen reject <paper> <note>... [--why "..."]
                                         close proposals as rejected
  paperpen adopt <repo-or-git-url> [--into D]
                                         put a paper back on the shelf from the
                                         record its own repository carries
  paperpen sync [<paper>]                pull the papers' repos, re-read rounds
  paperpen bundle [<paper>] [-o F] [--ink]
                                         the state as one .tar.gz
  paperpen versions <paper> [-n N] [--build REF] [--diff OLD[..NEW]] [--forget]
                                         the paper's own history: build it as
                                         it was, or latexdiff between two
  paperpen where                         which registry and caches are in use
  paperpen lan [--clear]                 set the password the LAN reader asks
                                         for, and optionally a second factor
  paperpen tls [--renew]                 a self-signed certificate for this
                                         machine, and how to trust it
  paperpen qr [--url U] [--light]        the address as a QR code to point
                                         a tablet's camera at

and, straight from the reader's own tooling:

  paperpen add <repo>        register a paper (finds the main .tex, builds it)
  paperpen list              what is on the shelf
  paperpen build <paper>     latexmk -synctex, into the cache
  paperpen notes <paper>     every note, and whether it is closed
  paperpen resolve <paper> <note-id> <done|rejected|open> ["what was done"]
  paperpen howto             what a paper's own repository needs to know
"""


def ask_password() -> str:
    """Twice, hidden, and the same both times."""
    import getpass

    while True:
        first = getpass.getpass("  a password for the LAN reader: ")
        if len(first) < 8:
            print("  at least 8 characters, please.")
            continue
        if first != getpass.getpass("  again: "):
            print("  those did not match.")
            continue
        return first


def offer_second_factor(light: bool = False, ask: bool = True) -> bool:
    """Enrol a TOTP secret, and prove a code from it before it is kept.

    Checked before saving on purpose. A second factor you cannot produce is a
    lock with no key, and finding that out at the door with the tablet in your
    hand is the wrong moment.

    The secret is offered as a QR code, which is what an authenticator app
    expects to be pointed at: typing thirty-two characters of base32 into a
    phone is where pairing failed. Drawn in the terminal, and also written as
    a picture readable only by you, for a terminal whose font breaks the
    drawing; the picture is the secret, so it is deleted when this is over.
    """
    if ask and input("  add a second factor, six digits from an authenticator app? "
                     "(recommended) [Y/n] ").strip().lower() in ("n", "no"):
        return False

    import socket

    secret = auth.new_totp_secret()
    uri = auth.totp_uri(secret, label=f"paperpen:{socket.gethostname() or 'paperpen'}")
    print("\n  Scan this with your authenticator app:\n")
    print(qr.show(uri, invert=light))
    picture = config.home() / "second-factor.svg"
    try:
        if qr.available():
            picture.parent.mkdir(parents=True, exist_ok=True)
            picture.touch(mode=0o600)
            picture.chmod(0o600)
            picture.write_text(qr.to_svg(uri), encoding="utf-8")
            print(f"\n  If it will not scan: open {picture}, the same code as a picture")
            if not light:
                print("  (or run again with --light, for a terminal with a light background)")
        print(f"  or type the key in by hand: {secret}\n")
        return _prove_second_factor(secret)
    finally:
        picture.unlink(missing_ok=True)


def _prove_second_factor(secret: str) -> bool:
    for left in range(3, 0, -1):
        code = input(f"  now the six digits it shows ({left} tries): ").strip()
        # Checked against this secret, not against the stored one: nothing is
        # stored until a code proves the app and this machine agree.
        if any(auth.totp(secret, time.time() + drift * auth.STEP) == code.replace(" ", "")
               for drift in (-1, 0, 1)):
            auth.enable_totp(secret)
            print("  the app and this machine agree. The second factor is on.")
            return True
        print("  that is not the code it is showing.")
    print("  leaving the second factor off; `paperpen lan` again to try it.")
    return False


def cmd_qr(argv: list[str]) -> int:
    """The address, as something to point a camera at.

    Typing `https://198.51.100.24:8770/` on a glass keyboard is the step
    where connecting a tablet actually fails.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen qr")
    ap.add_argument("--url", default="", help="anything; the LAN address by default")
    ap.add_argument("--light", action="store_true",
                    help="for a terminal with a light background")
    args = ap.parse_args(argv)

    where = args.url
    if not where:
        up = serving.running()
        if up and up["host"] not in ("127.0.0.1", "localhost"):
            where = up["url"]
        else:
            addresses = lan_addresses(up["port"] if up else serving.DEFAULT_PORT,
                                      "https" if tls.exists() else "http")
            if not addresses:
                raise bind.Refused(
                    "this machine has no network address to offer; pass --url")
            where = addresses[0]
            if not up:
                print("(nothing is serving yet; this is where it would be)\n")

    print(qr.show(where, invert=args.light))
    print(f"    {where}")
    return 0


def cmd_tls(argv: list[str]) -> int:
    """Make the certificate, and say how to get the tablet to accept it."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen tls")
    ap.add_argument("--renew", action="store_true",
                    help="make a new one, for instance after this machine "
                         "changed address")
    args = ap.parse_args(argv)

    if tls.exists() and not args.renew:
        print(f"a certificate is already here: {tls.cert_file()}")
        print(f"  good until   {tls.not_after() or 'unknown'}")
        print(f"  names        {tls.san_string()}")
        print(f"  fingerprint  {tls.fingerprint()}")
        here = tls.lan_ip()
        if here and not tls.covers(here):
            print(f"\n  this machine is now at {here}, which this certificate "
                  f"does not name.\n  `paperpen tls --renew` makes one that does.")
        print("\n`paperpen tls --renew` replaces it.")
        return 0

    try:
        made = tls.make()
    except RuntimeError as e:
        raise bind.Refused(str(e)) from e

    print(f"certificate  {made['cert']}")
    print(f"key          {made['key']}  (yours alone)")
    print(f"names        {', '.join(made['dns'] + made['ip'])}")
    print(f"good until   {made['until'] or 'about a year'}")
    print(f"fingerprint  {made['fingerprint']}")
    print()
    print("This is signed by nobody, so the tablet has to be told once to trust")
    print("it. Either way works and they are not equally good:")
    print()
    print("  Install it, and there is no warning afterwards. Copy")
    print(f"    {made['cert']}")
    print("  to the tablet (mail it to yourself, AirDrop it, or put it on a")
    print("  stick) and open it. iOS: Settings, then Profile Downloaded, then")
    print("  General > About > Certificate Trust Settings and switch it on.")
    print("  Android: Settings > Security > Encryption > Install a certificate.")
    print()
    print("  Or accept the browser's warning, which comes back every so often.")
    print("  Only do that after checking the fingerprint on the tablet's screen")
    print("  against the one above. An unchecked `proceed anyway` on a network")
    print("  you do not control is how somebody else ends up reading this.")
    print()
    print("Then:  paperpen serve --lan")
    return 0


NO_LOGIN_WARNING = (
    "no login: anyone who can reach this address can read your papers and notes,\n"
    "change their sources and download all of it. Only on a network you trust.")


def choose_login(light: bool = False) -> bool:
    """Ask how the reader on the network lets people in, and set it up.

    A login is what is recommended, and the first answer is the default. No
    login is there because it is a fair choice at home, on a network that is
    yours; it is asked for in so many words and said every time it serves.
    Returns whether a login is now on.
    """
    print("How should the reader on the network let people in?\n")
    print("  1  a password and six digits from an authenticator app   (recommended)")
    print("  2  a password only")
    print("  3  no login: anyone on the network can read and change your papers;")
    print("     only for a network you trust, at home say\n")
    while True:
        said = input("  choose [1]: ").strip() or "1"
        if said in ("1", "2", "3"):
            break
        print("  1, 2 or 3, please.")
    if said == "3":
        if input("  serve with no login? type 'no login' to confirm: ").strip().lower() \
                != "no login":
            print("  not confirmed; asking again.\n")
            return choose_login(light)
        auth.set_login(False)
        print(f"\n  {NO_LOGIN_WARNING}")
        print("  `paperpen lan` turns a login on whenever you want one.")
        return False
    auth.set_login(True)
    auth.set_password(ask_password())
    if said == "1":
        if not offer_second_factor(light=light, ask=False):
            print("  no second factor kept; `paperpen lan` to try again.")
    else:
        auth.disable_totp()
    print(f"  kept in {auth.auth_file()}, readable only by you.")
    return True


def cmd_lan(argv: list[str]) -> int:
    """Set up what the LAN reader asks for.

    This is the whole of it. There is no account, because there is one person
    and it is you; what is being kept out is everyone else on the network.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen lan")
    ap.add_argument("--clear", action="store_true",
                    help="forget the password and the second factor")
    ap.add_argument("--no-login", dest="no_login", action="store_true",
                    help="serve the network with no login, for a network you trust")
    ap.add_argument("--light", action="store_true",
                    help="draw the QR code for a terminal with a light background")
    args = ap.parse_args(argv)

    if args.clear:
        had = auth.has_password()
        auth.clear()
        print("cleared." if had else "there was nothing set.")
        print("`paperpen serve --lan` will ask for a login again.")
        return 0

    if args.no_login:
        auth.set_login(False)
        print(NO_LOGIN_WARNING)
        print("`paperpen lan` turns a login on again.")
        return 0

    if auth.login_off():
        print("the network reader has no login now.")
    elif auth.has_password():
        print(f"a password is already set ({auth.auth_file()})"
              + (", with a second factor." if auth.has_totp() else "."))
        if input("  replace it? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  left as it was.")
            return 0

    if not choose_login(light=args.light):
        return 0

    print(f"\nkept in {auth.auth_file()}, readable only by you.")
    if tls.exists():
        print("\nA certificate is already here, so this will be served over "
              "https.\nServe it to the tablet with:\n")
        print("    paperpen serve --lan")
    else:
        print("\nNext, a certificate, or the password and everything you read")
        print("cross the network in the clear:\n")
        print("    paperpen tls          # once")
        print("    paperpen serve --lan  # prints a QR the tablet can scan")
    return 0


def _yes(question: str, default: bool = True) -> bool:
    said = input(f"  {question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not said else said in ("y", "yes")


def cmd_onboard(argv: list[str]) -> int:
    """The basics, once, in the order they depend on each other.

    Each step is the command that already does it (`lan`, `tls`, `add`), so
    there is still one implementation of each and this is only the walk
    between them. A step that is done is said and passed over, so running it
    again on a machine that is set up asks nothing and changes nothing.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen onboard")
    ap.add_argument("--check", action="store_true",
                    help="say how each step stands, ask nothing, change nothing; "
                         "exits 1 while a needed step is not done")
    ap.add_argument("--light", action="store_true",
                    help="draw the QR code for a terminal with a light background")
    args = ap.parse_args(argv)

    steps = onboard.status()
    if args.check or not sys.stdin.isatty():
        print(onboard.report(steps))
        if not args.check:
            print("\n(not a terminal, so nothing was asked; "
                  "run `paperpen onboard` in one)")
        return 0 if onboard.ready(steps) else 1

    print("Setting up paperpen on this machine. Anything already done is "
          "passed over.\n")
    print(onboard.report(steps) + "\n")
    have = {s.key: s for s in steps}

    if not have["tools"].done:
        print(f"tools: {have['tools'].said}. A PDF can be read and marked without")
        print("  them; a LaTeX repository cannot be built. Carrying on.\n")

    if not have["places"].done:
        for place in (config.home(), config.cache_root(), config.data_root()):
            place.mkdir(parents=True, exist_ok=True)
        print(f"made      {config.home()}")
        print(f"          {config.cache_root()}")
        print(f"          {config.data_root()}\n")

    # The login first: everything after it is about serving to the tablet.
    # There is no account; what it keeps out is everybody else on the network.
    if not auth.has_password() and not auth.login_off():
        choose_login(light=args.light)
        print()
    elif auth.has_password() and not auth.has_totp() and not auth.login_off():
        offer_second_factor(light=args.light)
        print()

    cert = next(s for s in onboard.status() if s.key == "tls")
    if not cert.done:
        print(f"certificate: {cert.said}.")
        if _yes("make one now?"):
            print()
            cmd_tls(["--renew"] if tls.exists() else [])
        print()

    if not have["papers"].done:
        print("The shelf is empty. A first paper: a LaTeX repository, or a PDF.")
        where = input("  its path (Enter to leave it for later): ").strip()
        if where:
            try:
                bind.run(["add", str(Path(where).expanduser())])
            except bind.Refused as e:
                print(f"  not added: {e}\n  `paperpen add <path>` when it is sorted.")
        print()

    steps = onboard.status()
    print(onboard.report(steps) + "\n")
    if not onboard.ready(steps):
        print("Not everything needed is done; `paperpen onboard` again picks up "
              "where this left off.")
        return 1
    print("Ready. To read on the tablet:\n")
    print("    paperpen serve --lan   # prints a QR code to point its camera at")
    return 0


def lan_addresses(port: int = 0, scheme: str = "http") -> list[str]:
    """The addresses this machine is likely reachable at, for typing into a
    tablet. Best effort: it asks the routing table which source address would
    be used to reach the outside, which is the one on the network you are on."""
    import socket

    port = port or serving.DEFAULT_PORT
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # documentation range; nothing is sent
            found.append(f"{scheme}://{s.getsockname()[0]}:{port}/")
    except OSError:
        pass
    return found


def cmd_serve(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen serve")
    ap.add_argument("--port", type=int, default=serving.DEFAULT_PORT)
    ap.add_argument("--host", default=serving.DEFAULT_HOST)
    ap.add_argument("--lan", action="store_true",
                    help="serve on every interface, behind the password")
    ap.add_argument("--no-tls", dest="tls", action="store_false",
                    help="serve the LAN in the clear, which you have to mean")
    ap.add_argument("--qr", dest="qr", action="store_true", default=None,
                    help="show the address as a QR code (the default on --lan)")
    ap.add_argument("--light", action="store_true",
                    help="draw QR codes for a terminal with a light background")
    ap.add_argument("--debug", action="store_true",
                    help="Flask's debugger and reloader; loopback only")
    args = ap.parse_args(argv)

    host = "0.0.0.0" if args.lan and args.host == serving.DEFAULT_HOST else args.host
    lan = args.lan or host not in ("127.0.0.1", "localhost", "::1")

    # The debugger runs code typed into a browser, so it never leaves loopback.
    if args.debug and lan:
        print("--debug is for loopback only: its debugger runs whatever is typed "
              "into it.")
        return 1

    # The one place the decision is made. Off loopback the login is on unless
    # somebody turned it off in so many words (`paperpen lan --no-login`); a
    # server with no decision made is never served unlocked.
    if lan and auth.login_off():
        print("WARNING  " + NO_LOGIN_WARNING.replace("\n", "\n         "))
        print("         `paperpen lan` sets a login.\n")
    elif lan and not auth.has_password():
        print("Serving on the network needs a login decided first. Behind this are "
              "the\npapers you are reading, the notes you have written about other "
              "people's\ndrafts, and `/state.tar.gz`, which is all of it in one file.\n")
        if not sys.stdin.isatty():
            print("Set one with:  paperpen lan    (or `paperpen lan --no-login` on a "
                  "network you trust)")
            return 1
        choose_login(light=args.light)
        print()

    # TLS when there is a certificate, which `paperpen tls` makes. Without
    # one the LAN is in the clear and says so; `--no-tls` is for meaning it.
    context = None
    if lan and args.tls:
        if tls.exists():
            context = (str(tls.cert_file()), str(tls.key_file()))
        else:
            print("No certificate yet, so this would be served in the clear.")
            print("  `paperpen tls` makes one; `--no-tls` serves without.\n")
            if not sys.stdin.isatty():
                return 1
            if input("Make one now? [Y/n] ").strip().lower() not in ("n", "no"):
                cmd_tls([])
                context = (str(tls.cert_file()), str(tls.key_file()))
                print()

    from .web import create_app

    here = serving.url(host, args.port, scheme="https" if context else "http")
    print(f"registry {config.registry_file()}")
    print(f"cache    {config.cache_root()}")
    print(f"shelf    {here}")
    print(f"reader   {here}paper/<id>   ·   queue {here}queue")
    reachable = []
    if lan:
        scheme = "https" if context else "http"
        for address in lan_addresses(args.port, scheme):
            reachable.append(address)
            print(f"network  {address}   "
                  + ("no login" if auth.login_off() else
                     "password" + (" and six digits" if auth.has_totp() else "")
                     + " to get in"))
        if context:
            here_ip = tls.lan_ip()
            print(f"tls      {tls.cert_file()}")
            print(f"         {tls.fingerprint()}")
            if here_ip and not tls.covers(here_ip):
                print(f"         this machine is at {here_ip}, which the "
                      f"certificate does not name:\n"
                      f"         the tablet will refuse it. `paperpen tls --renew`.")
        else:
            print("         no TLS: the password and what you read cross the "
                  "network in the clear")

    # Pointed at with a camera rather than typed on glass, which is what an
    # address like this is otherwise.
    if reachable and (args.qr or (args.qr is None and lan)):
        print()
        print(qr.show(reachable[0]))
        print(f"    {reachable[0]}")

    # So `paperpen shelf` in another terminal can say where this is. It is
    # cleared on the way out, and probed rather than trusted by whoever reads
    # it, because a process does not always get to run its own cleanup.
    serving.remember(host, args.port, "https" if context else "http")
    try:
        app = create_app(lan=lan)
        # The session cookie is only ever sent back over https when there is https.
        app.config["SESSION_COOKIE_SECURE"] = bool(context)
        app.run(host=host, port=args.port, debug=args.debug,
                                threaded=True, use_reloader=args.debug,
                                ssl_context=context)
    finally:
        serving.forget()
    return 0


def cmd_shelf() -> int:
    groups = shelf_mod.shelf()
    if not groups:
        print(f"nothing on the shelf ({config.registry_file()})")
        print("  add one with `paperpen add <repo-or-pdf>`")
        print(f"  {serving.where_to_look()}")
        return 0
    for group in groups:
        print(f"\n{group['title']}: {group['blurb']}")
        for p in group["papers"]:
            state = (f"{p['open']} open" if p["open"] else
                     f"{p['outstanding']} outstanding" if p["outstanding"] else
                     (f"answered {p['last_sent']['date']}" if p["last_sent"] else "no rounds"))
            print(f"  {p['id']:<38} {p['kind']:<9} "
                  f"{(str(p['pages']) + 'p') if p['built'] else '-':<5} {state:<22} {p['name']}")
    # The terminal is where you are after building something; the browser is
    # where the paper is read. This is the same shelf, so it should say where
    # the other one is rather than leaving it to be remembered.
    print(f"\n{serving.where_to_look()}")
    return 0


def cmd_versions(argv: list[str]) -> int:
    """The log, and a build of the paper as it was at any point in it.

    The same builds the four-pane view uses, from the terminal: a version is
    compiled once and kept in the cache, so making one here is making the one
    the browser will show.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen versions")
    ap.add_argument("paper")
    ap.add_argument("-n", type=int, default=20, help="how much of the log to show")
    ap.add_argument("--build", metavar="REF", default="",
                    help="compile the paper as it was at REF (a commit, or `work`)")
    ap.add_argument("--diff", metavar="OLD[..NEW]", default="",
                    help="compile latexdiff between two of them (NEW defaults "
                         "to the working tree)")
    ap.add_argument("--source", metavar="OLD[..NEW]", default="",
                    help="what git diff says about the .tex, instead of a build")
    ap.add_argument("--force", action="store_true", help="build it again")
    ap.add_argument("--forget", action="store_true",
                    help="throw this paper's version builds away")
    args = ap.parse_args(argv)

    paper = bind.resolve_paper(args.paper)
    if args.forget:
        gone = versions.forget(paper)
        print(f"{len(gone)} version build{'' if len(gone) == 1 else 's'} thrown away")
        return 0

    if args.source:
        old, _, new = args.source.partition(versions.PAIR)
        said = versions.source_diff(paper, old, new or versions.WORKING)
        if said["empty"]:
            print(f"nothing changed in the source between {said['old']} and {said['new']}")
            return 0
        print(said["stat"])
        print()
        print(said["patch"], end="")
        if said["cut"]:
            print("\n… cut here; the whole of it is `git diff` in the repo")
        return 0

    if args.build or args.diff:
        ref = args.diff if args.diff else args.build
        if args.diff and versions.PAIR not in ref:
            ref = f"{ref}{versions.PAIR}{versions.WORKING}"
        print(f"building {ref} …", flush=True)
        # From a terminal the paper's own build command may run: the reason the
        # server will not is that a browser asked, and here nobody did.
        done = versions.build(paper, ref, force=args.force, custom=True)
        print(f"{done['title']}: {done['pages']} pages")
        print(f"  {versions.pdf_of(paper, ref)}")
        return 0

    if not versions.is_git(paper):
        print(f"{paper.repo} is not a git repository, so there is no history here")
        return 1
    now = versions.working(paper)
    print(f"work{'':<9} {'dirty' if now['dirty'] else 'clean':<7} "
          f"{'built' if now['built'] else '-':<6} the working tree"
          + (f" at {now['head']}" if now["head"] else ""))
    for row in versions.commits(paper, args.n):
        built = versions.state(paper, row["sha"])["built"]
        marks = " ".join(m for m, on in (("source", row["source"]),
                                         ("round", row["round"]),
                                         ("reading", row["built"])) if on)
        print(f"{row['short']:<13} {row['date']:<7} {'built' if built else '-':<6} "
              f"{row['subject'][:60]:<62} {marks}")
    print(f"\n  paperpen versions {paper.pid} --build <commit>     compile it as it was")
    print(f"  paperpen versions {paper.pid} --diff <commit>      latexdiff against now")
    return 0


def _cut(text: str, wide: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= wide else text[:wide - 1] + "\u2026"


def cmd_queue(argv: list[str]) -> int:
    """Every open note, from every paper, in the order they should be cleared.

    The same list the browser's queue shows. It is here because the thing that
    works through a queue is not always a person at a tablet: an agent standing
    above the papers needs one view of what is outstanding, and `--json` is
    that view, on stdout, with nothing else on it.
    """
    import argparse
    import json as json_mod

    ap = argparse.ArgumentParser(prog="paperpen queue")
    ap.add_argument("--json", action="store_true", help="the rows, for something to read")
    ap.add_argument("--paper", default="", help="one paper (a name or an id)")
    ap.add_argument("--tag", default="", help="SCIENCE, LANGUAGE, QUESTION, TODO or AUTO")
    ap.add_argument("--who", default="", choices=["", queue_mod.YOU, *queue_mod.AGENTS])
    ap.add_argument("--unclassified", action="store_true", help="only the ones left on AUTO")
    ap.add_argument("--older-than", type=int, default=0, metavar="DAYS")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    pid = bind.resolve_paper(args.paper).pid if args.paper else ""
    rows = queue_mod.rows(tag=args.tag, paper=pid, who=args.who,
                          unclassified=args.unclassified)
    if args.older_than:
        rows = [r for r in rows if r["age"] >= args.older_than]
    if args.limit:
        rows = rows[:args.limit]
    count = queue_mod.tally(rows)

    if args.json:
        print(json_mod.dumps({"ok": True, "tally": count, "rows": rows}, indent=2))
        return 0

    if not rows:
        print("nothing open" + (" that matches" if (args.tag or pid or args.unclassified) else ""))
        return 0
    said = [f"{count['total']} open note{'' if count['total'] == 1 else 's'}",
            f"{count['papers']} paper{'' if count['papers'] == 1 else 's'}"]
    if count["tags"].get("AUTO"):
        said.append(f"{count['tags']['AUTO']} unclassified")
    if count["handwritten"]:
        said.append(f"{count['handwritten']} handwritten")
    for who, n in count["agents"].items():
        said.append(f"{n} of {who}'s")
    print(" \u00b7 ".join(said) + "\n")
    print(f"{'id':<15}{'tag':<10}{'age':>4}  {'paper':<24}{'source':<22}note")
    for r in rows:
        # A handwritten note has no words until somebody reads the picture, so
        # the row shows the sentence it sits on instead of saying so twice.
        said = r["text"]
        if r["handwritten"] and said.startswith("(handwritten"):
            said = ("\u270e " + r["anchor"]) if r["anchor"] else said
        print(f"{_cut(r['id'], 14):<15}{r['tag']:<10}{str(r['age']) + 'd':>4}  "
              f"{_cut(r['paper'], 23):<24}{_cut(r['source'] or r['where'], 21):<22}"
              f"{_cut(said, 58)}")
    print("\n  paperpen queue --json                  the same, for an agent to read")
    print("  paperpen classify <paper> <id> <TAG>   put a class on one")
    return 0


def cmd_next(argv: list[str]) -> int:
    """What to do first, across every paper, and the command that does it."""
    import argparse
    import json as json_mod

    ap = argparse.ArgumentParser(prog="paperpen next")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="the whole list, in order")
    ap.add_argument("--fast", action="store_true",
                    help="do not ask each repository whether it has moved past its build")
    args = ap.parse_args(argv)
    slow = not args.fast

    if args.all:
        everything = agenda.actions(slow)
        if args.json:
            print(json_mod.dumps({"ok": True, "actions": everything}, indent=2))
            return 0
        if not everything:
            print("nothing open, nothing outstanding, nothing stale")
            return 0
        for item in everything:
            _say_action(item)
        return 0

    item = agenda.next_one(slow)
    if args.json:
        print(json_mod.dumps({"ok": True, "next": item}, indent=2))
        return 0
    _say_action(item)
    return 0


def _say_action(item: dict) -> None:
    head = item["do"] + (f" \u00b7 {item['paper']}" if item["paper"] else "")
    print(f"\n{head}")
    print(f"  {item['why']}")
    if item["where"]:
        print(f"  {item['where']}")
    if item["run"]:
        print(f"  run:  {item['run']}")
    if item["then"]:
        print(f"  then: {item['then']}")


def cmd_rounds(argv: list[str]) -> int:
    paper = bind.resolve_paper(argv[0]) if argv else None
    if paper is None:
        print("which paper? paperpen rounds <paper>")
        return 2
    open_now = rounds.open_round(paper)
    if open_now:
        unclassified = sum(1 for n in open_now if n.get("tag", "AUTO") == "AUTO")
        print(f"  open        {len(open_now)} note(s)"
              + (f", {unclassified} unclassified" if unclassified else ""))
    past = rounds.sent(paper)
    if not past and not open_now:
        print("no rounds yet")
    for r in past:
        stands = "answered" if r["answered"] else f"{r['open']} still open"
        where = f"  {r['where']}" if r["where"] else ""
        print(f"  {r['date']}  {r['notes']:>3} note(s)  {stands:<16}"
              f"{r['delivery'] or 'repo':<7}{where}")
    return 0


def cmd_finish(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen finish")
    ap.add_argument("paper")
    ap.add_argument("--as", dest="delivery", default="",
                    choices=["", deliver.REPO, deliver.PDF, deliver.FOLDER])
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args(argv)
    done = deliver.finish(args.paper, args.delivery, commit=not args.no_commit)
    print(f"{done['notes']} note(s), round {done['session']}")
    print(f"  recorded  {done['record']}")
    print(f"  delivered {done['where']}"
          + ("  (committed)" if done["committed"] else ""))
    return 0


def cmd_forget(argv: list[str]) -> int:
    """Take a paper off the shelf, without touching anything it owns.

    `registry.remove` has been here all along and the shelf page has a button
    for it; the command line had no way to reach it. So a paper added by
    mistake, or a variant of a manuscript put up for comparison and no longer
    wanted, could only be removed by editing papers.json by hand.

    Only the entry goes. The repository, the rounds committed into it and the
    build cache all stay where they are, which is what makes this safe and
    what makes `add` or `adopt` find the history again afterwards.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen forget")
    ap.add_argument("paper")
    ap.add_argument("--yes", action="store_true",
                    help="do not ask, for a paper with notes still open")
    args = ap.parse_args(argv)

    paper = bind.resolve_paper(args.paper)
    open_notes = 0
    try:
        open_notes = sum(1 for n in rounds.delivered_notes(paper) + rounds.open_round(paper)
                         if n.get("status", "open") == "open")
    except Exception:
        pass                      # a paper with no rounds yet, or none readable
    if open_notes and not args.yes:
        raise bind.Refused(
            f"{paper.pid} has {open_notes} note(s) still open. They stay in "
            f"its repository either way, but forgetting it now takes them off "
            f"the queue and the shelf. Pass --yes if that is what you want.")

    gone = registry.remove(paper.pid)
    print(f"{gone['id']}: off the shelf")
    print(f"  name    {gone.get('name', '')}")
    print(f"  repo    {gone.get('repo', '')}")
    print("  its rounds and its cache are untouched; `paperpen add` or "
          "`paperpen adopt` puts it back")
    return 0


def cmd_about(argv: list[str]) -> int:
    """What a paper is: its class, where a finished round goes, and the brief.

    These are the three fields paperpen adds to the dashboard's registry, and
    they were reachable only by a POST the shelf never makes or by editing
    papers.json by hand. So every paper added at the command line arrived as
    `mine`, delivering into a repository, which for a student's draft that
    came over as a PDF means a round aimed at a checkout that is not theirs
    and may not be a repository at all.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen about")
    ap.add_argument("paper")
    # Not argparse `choices`, because an empty value is a real answer here and
    # means "take it back to whatever the kind implies", and `choices` would
    # refuse it while the help was busy offering it.
    ap.add_argument("--kind", metavar="{" + ",".join(registry.KINDS) + "}",
                    help="it picks the delivery; empty to go back to mine")
    ap.add_argument("--delivery", metavar="{" + ",".join(registry.DELIVERIES) + "}",
                    help="where a finished round goes; empty for the kind's own")
    ap.add_argument("--brief", help="what kind of read this is; empty to drop it")
    ap.add_argument("--main", help="the .tex that is built, for a paper with more than one")
    ap.add_argument("--agent", choices=["implement", "propose", "off", "default"],
                    help="what the agent does when a round is finished; default goes back to the kind's")
    ap.add_argument("--runner", choices=[*agent.RUNNERS, "default"],
                    help="who the agent is for this paper: claude or codex; default goes back to "
                         "PAPERPEN_RUNNER or claude")
    ap.add_argument("--branch", dest="agent_branch", action="store_const", const=True,
                    help="an agent's finished round is committed on a branch of its own")
    ap.add_argument("--no-branch", dest="agent_branch", action="store_const", const=False)
    ap.add_argument("--record", metavar="{" + ",".join(registry.RECORDS) + "}",
                    help="repo: the paper carries its own history in review/")
    ap.add_argument("--archive", dest="archived", action="store_const", const=True)
    ap.add_argument("--unarchive", dest="archived", action="store_const", const=False)
    args = ap.parse_args(argv)

    for what, value, allowed in (("kind", args.kind, registry.KINDS),
                                 ("delivery", args.delivery, registry.DELIVERIES),
                                 ("record", args.record, registry.RECORDS)):
        if value not in (None, "", *allowed):
            raise bind.Refused(f"{what} is one of {', '.join(allowed)}, "
                               f"or empty; not {value!r}")

    paper = bind.resolve_paper(args.paper)
    asked = {k: v for k, v in (("kind", args.kind), ("delivery", args.delivery),
                               ("brief", args.brief), ("record", args.record))
             if v is not None}
    if args.archived is not None:
        asked["archived"] = args.archived or None   # absent rather than false
    if args.agent is not None:
        asked["agent"] = "" if args.agent == "default" else args.agent
    if args.agent_branch is not None:
        asked["agent_branch"] = args.agent_branch or None
    if args.runner is not None:
        asked["runner"] = "" if args.runner == "default" else args.runner
    if asked:
        registry.update(paper.pid, **asked)
    if args.main:
        from . import edit as edit_mod
        edit_mod.set_main(paper, args.main)
        paper = bind.resolve_paper(paper.pid)
        print(f"main is now {paper.main}; `paperpen build {paper.pid}` builds it")

    now = registry.extras(paper.pid)
    print(f"{paper.pid}  {paper.name}")
    print(f"  kind      {now['kind']}")
    print(f"  delivery  {now['delivery']}"
          + ("" if paper.repo.is_dir() or now["delivery"] != "repo"
             else "   (but there is no repository at " + str(paper.repo) + ")"))
    print(f"  record    {now['record']}"
          + ("   (review/ in the paper's own repository)" if now["record"] == "repo"
             else "   (kept only here; --record repo to let the paper carry it)"))
    print(f"  main      {paper.main}")
    print(f"  agent     {agent.mode(paper)}"
          + ("   (a finished round goes on its own branch)" if agent.on_branch(paper) else ""))
    print(f"  runner    {agent.runner(paper)}"
          + ("" if registry.entry(paper.pid).get("runner") else "   (the default; --runner to choose)"))
    print(f"  brief     {now['brief'] or '-'}")
    if now["archived"]:
        print("  archived")
    return 0


def cmd_record(argv: list[str]) -> int:
    """Write the manifest into the paper's own repository, now.

    `finish` does this after every round it records there. This is for the
    papers that were read before the manifest existed, and for repairing one
    that was hand-edited.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen record")
    ap.add_argument("paper")
    args = ap.parse_args(argv)

    paper = bind.resolve_paper(args.paper)
    if not paper.repo.is_dir():
        raise bind.Refused(f"{paper.pid} has no repository to record into: {paper.repo}")
    out = archive.write_manifest(paper)
    said = archive.manifest(paper)
    print(f"{out}")
    print(f"  {said['id']}  {said['kind']}, delivered as {said['delivery']}")
    print(f"  {len(said['rounds'])} round(s): "
          + (", ".join(r["date"] for r in said["rounds"]) or "none yet"))
    return 0


def cmd_adopt(argv: list[str]) -> int:
    """Rebuild a paper's place on the shelf from the record in its repository."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen adopt")
    ap.add_argument("source", help="a directory, or a git address to clone")
    ap.add_argument("--into", default="", help="where to clone a git address")
    ap.add_argument("--main", default="", help="override the manifest's main file")
    args = ap.parse_args(argv)

    got = archive.adopt(args.source, main=args.main,
                        keep=Path(args.into).expanduser() if args.into else None)
    print(f"{got['id']}: {got['name']}")
    print(f"  repo    {got['repo']}")
    print(f"  main    {got['main'] or '(none recorded; pass --main)'}")
    print(f"  rounds  {', '.join(got['rounds']) or 'none in the repository'}")
    print(f"  build it with: paperpen build {got['id']}")
    return 0


def cmd_sync(argv: list[str]) -> int:
    """Pull the papers' own repositories and read what came back.

    There is no central store to reconcile: each paper's history lives in that
    paper's repository, so syncing is pulling the repositories and re-reading
    them. A paper whose repo is not a checkout, or has no remote, is reported
    and skipped rather than being an error: a referee PDF has nowhere to pull
    from and that is not a fault.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen sync")
    ap.add_argument("paper", nargs="?", default="")
    ap.add_argument("--no-pull", action="store_true",
                    help="re-read what is already there; fetch nothing")
    args = ap.parse_args(argv)

    papers = ([bind.resolve_paper(args.paper)] if args.paper else bind.load_papers())
    for paper in papers:
        if not (paper.repo / ".git").is_dir():
            print(f"  {paper.pid:<38} no repository to pull from")
            continue
        if not args.no_pull:
            done = subprocess.run(["git", "-C", str(paper.repo), "pull", "--ff-only"],
                                  capture_output=True, text=True, timeout=600)
            if done.returncode != 0:
                print(f"  {paper.pid:<38} pull refused: "
                      f"{done.stderr.strip().splitlines()[-1][:60] if done.stderr.strip() else '?'}")
                continue
        review = paper.repo / "review"
        brought = archive.restore_rounds(paper, review) if review.is_dir() else []
        print(f"  {paper.pid:<38} {len(brought)} round(s): "
              + (", ".join(brought) or "none"))
    return 0


def cmd_bundle(argv: list[str]) -> int:
    """The state as one file, for keeping or for carrying to another machine."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen bundle")
    ap.add_argument("paper", nargs="?", default="")
    ap.add_argument("-o", "--out", default="", help="default: paperpen-<date>.tar.gz")
    ap.add_argument("--ink", action="store_true",
                    help="include the rendered ink, which is derived and large")
    args = ap.parse_args(argv)

    pids = [bind.resolve_paper(args.paper).pid] if args.paper else None
    raw = archive.bundle(pids, ink=args.ink)
    out = Path(args.out).expanduser() if args.out else Path(
        f"paperpen-{date.today().isoformat()}.tar.gz")
    out.write_bytes(raw)
    print(f"{out}  {len(raw) / 1e6:.2f} MB"
          + ("" if args.ink else "  (without the rendered ink; --ink to include it)"))
    return 0


def cmd_feedback(argv: list[str]) -> int:
    """What came back for a paper's notes: the fixes proposed, and the thread."""
    import argparse
    import json as json_mod

    ap = argparse.ArgumentParser(prog="paperpen feedback")
    ap.add_argument("paper")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    got = feedback.items(bind.resolve_paper(args.paper).pid)
    if args.json:
        print(json_mod.dumps({"ok": True, "items": got}, indent=2, ensure_ascii=False))
        return 0
    if not got:
        print("no feedback yet: `paperpen propose` writes some")
        return 0
    for item in got:
        print(f"\n{item['id']}  {item['status']:<8} {item['tag']:<9} "
              f"{item['source'] or 'page ' + str(item['page'])}")
        print(f"  {_cut(item['text'], 76)}")
        for fix in item["fixes"]:
            print(f"  [{fix['id']}] {fix['state']:<9} {fix['summary']}  ({fix['by']})")
        for said in item["thread"]:
            print(f"      {said['by']}: {_cut(said['text'], 66)}")
    return 0


def cmd_propose(argv: list[str]) -> int:
    """A fix for a delivered note, checked against the source before it is kept."""
    import argparse
    import json as json_mod

    ap = argparse.ArgumentParser(prog="paperpen propose")
    ap.add_argument("paper")
    ap.add_argument("note")
    ap.add_argument("--summary", required=True, help="one line: what the fix changes")
    ap.add_argument("--why", default="", help="what in the note it answers")
    ap.add_argument("--by", default="claude", help="who proposes it")
    ap.add_argument("--file", action="append", default=[], help="with --old and --new, once per edit")
    ap.add_argument("--old", action="append", default=[], help="the exact text there now")
    ap.add_argument("--new", action="append", default=[], help="what replaces it")
    ap.add_argument("--edits", default="",
                    help='the edits as JSON, [{"file", "old", "new"}], or - to read it from stdin')
    ap.add_argument("--apply", action="store_true",
                    help="apply it at once, for a correction that leaves no choice")
    args = ap.parse_args(argv)

    edits = [{"file": f, "old": o, "new": n} for f, o, n in zip(args.file, args.old, args.new)]
    if not (len(args.file) == len(args.old) == len(args.new)):
        raise bind.Refused("each edit is a --file, an --old and a --new")
    if args.edits:
        raw = sys.stdin.read() if args.edits == "-" else args.edits
        try:
            edits += list(json_mod.loads(raw))
        except ValueError as e:
            raise bind.Refused(f"--edits is not JSON: {e}") from e
    done = feedback.propose(args.paper, args.note, args.summary, edits, why=args.why,
                            by=args.by, now=args.apply)
    print(f"fix {done['fix']['id']} for {args.note}: {done['fix']['summary']}")
    if args.apply:
        went = done["applied"]
        print("  applied, and the note is closed" if went["closed"]
              else f"  not applied: {'; '.join(went['failed'].values())}")
        if went["failed"]:
            return 1
    print(f"  in {feedback.path(bind.resolve_paper(args.paper), done['session'])}")
    return 0


def cmd_reply(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen reply")
    ap.add_argument("paper")
    ap.add_argument("note")
    ap.add_argument("text")
    ap.add_argument("--by", default=feedback.YOU)
    args = ap.parse_args(argv)
    feedback.reply(args.paper, args.note, args.text, by=args.by)
    print(f"said on {args.note}; it stays open")
    return 0


def cmd_agent(argv: list[str]) -> int:
    """The agent, Claude Code or Codex, answering a delivered round in the
    paper's checkout.

    Run here it is in front of you; --print gives the command to run yourself;
    --background is what Finish does.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen agent")
    ap.add_argument("paper")
    ap.add_argument("--round", default="", help="a round's date; the newest open one by default")
    ap.add_argument("--mode", default="", choices=["", "implement", "propose", "review"],
                    help="for this run; the paper's setting by default")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the agent's command, to run it yourself")
    ap.add_argument("--runner", default="", choices=["", *agent.RUNNERS],
                    help="claude or codex, for this run; the paper's setting by default")
    ap.add_argument("--background", action="store_true", help="start it and return")
    ap.add_argument("--again", action="store_true", help="for a round it has answered once")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--focus", default="", help=argparse.SUPPRESS)
    ap.add_argument("--max", type=int, default=proposals.MOST, dest="most", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    paper = bind.resolve_paper(args.paper)

    if args.status:
        said = agent.status(paper)
        if not said:
            print(f"no agent has run for {paper.pid}; its setting is {agent.mode(paper)}")
            return 0
        print(f"{said.get('state')}  round {said.get('round')}  {said.get('mode', '')}  "
              f"{said.get('runner', '')}  since {said.get('started', '')}"
              + (f"  {said['said']}" if said.get("said") else ""))
        if said.get("log"):
            print(f"  log  {said['log']}")
        if said.get("branch"):
            print(f"  on   {said['branch']}: `paperpen branch {paper.pid} take` or `drop`")
        return 0
    if args.stop:
        agent.stop(paper.pid)
        print("stopped")
        return 0
    if args.worker:
        # what goes wrong before the agent is even started is said in the
        # status the reader shows, not only in a log nobody opens
        try:
            done = agent.run(paper.pid, args.round, args.mode, args.focus, args.most, args.runner)
        except bind.Refused as e:
            agent._write_status(paper, args.round, state="failed", said=str(e))
            raise
        return 0 if done["state"] == "done" else 1

    how = args.mode or agent.mode(paper)
    if how == "off":
        raise bind.Refused(f"the agent is off for {paper.pid}; --mode implement for this run, "
                           f"or `paperpen about {paper.pid} --agent implement`")
    session = args.round or agent.latest_round(paper)
    who = agent.runner(paper, args.runner)
    line = agent.shell_line(paper, session, how, who=who)
    if args.show:
        print(line)
        return 0
    if args.background:
        said = agent.start(paper.pid, session, how, again=args.again, who=who)
        print(f"started, round {session} ({how}, {who}); `paperpen agent {paper.pid} --status`")
        print(f"  log  {said['log']}")
        return 0
    print(f"{who}, answering the round of {session} of {paper.pid} ({how}):\n  {line}\n",
          flush=True)
    done = agent.run(paper.pid, session, how, who=who)
    print(f"\n{done['state']}" + (f": {done['said']}" if done.get("said") else "")
          + (f"; the round is on {done['branch']}" if done.get("branch") else ""))
    return 0 if done["state"] == "done" else 1


def _edits_from(args) -> list[dict]:
    """--file/--old/--new, once per edit, and --edits as JSON or - for stdin."""
    import json as json_mod

    if not (len(args.file) == len(args.old) == len(args.new)):
        raise bind.Refused("each edit is a --file, an --old and a --new")
    edits = [{"file": f, "old": o, "new": n} for f, o, n in zip(args.file, args.old, args.new)]
    if args.edits:
        raw = sys.stdin.read() if args.edits == "-" else args.edits
        try:
            edits += list(json_mod.loads(raw))
        except ValueError as e:
            raise bind.Refused(f"--edits is not JSON: {e}") from e
    return edits


def cmd_review(argv: list[str]) -> int:
    """The agent reads the paper on its own and writes notes, each with its fix.

    Run here it is in front of you; --background is what the reader's button
    does; --print gives the command to run yourself."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen review")
    ap.add_argument("paper")
    ap.add_argument("--focus", default="",
                    help='what to look for, in words: "clarity, notation"; a general read by default')
    ap.add_argument("--max", type=int, default=proposals.MOST, dest="most",
                    help=f"at most this many notes ({proposals.MOST})")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the agent's command, to run it yourself")
    ap.add_argument("--runner", default="", choices=["", *agent.RUNNERS],
                    help="claude or codex, for this run; the paper's setting by default")
    ap.add_argument("--background", action="store_true", help="start it and return")
    args = ap.parse_args(argv)
    if args.most < 1:
        raise bind.Refused("--max is at least 1")
    paper = bind.resolve_paper(args.paper)
    who = agent.runner(paper, args.runner)
    session = proposals.session_of(by=who)
    line = agent.shell_line(paper, session, agent.REVIEW, args.focus, args.most, who)
    if args.show:
        print(line)
        return 0
    if args.background:
        said = agent.start(paper.pid, session, agent.REVIEW, focus=args.focus, most=args.most,
                           who=who)
        print(f"started, round {session}; `paperpen agent {paper.pid} --status`")
        print(f"  log  {said['log']}")
        return 0
    print(f"{who}, reviewing {paper.pid} into {session}:\n  {line}\n", flush=True)
    done = agent.run(paper.pid, session, agent.REVIEW, args.focus, args.most, who)
    print(f"\n{done['state']}" + (f": {done['said']}" if done.get("said") else "")
          + f"; {done.get('notes', 0)} note(s) to decide, in the reader or with "
          f"`paperpen approve` / `paperpen reject`")
    return 0 if done["state"] == "done" else 1


def cmd_suggest(argv: list[str]) -> int:
    """One note of the agent's own, with the fix it proposes."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen suggest")
    ap.add_argument("paper")
    ap.add_argument("--note", required=True, help="what is wrong, and why it matters")
    ap.add_argument("--tag", required=True, type=str.upper, choices=list(proposals.TAGS))
    ap.add_argument("--summary", default="", help="one line: what the fix changes")
    ap.add_argument("--why", default="", help="why this fix")
    ap.add_argument("--file", action="append", default=[], help="with --old and --new, once per edit")
    ap.add_argument("--old", action="append", default=[], help="the exact text there now")
    ap.add_argument("--new", action="append", default=[], help="what replaces it")
    ap.add_argument("--edits", default="",
                    help='the edits as JSON, [{"file", "old", "new"}], or - to read it from stdin')
    ap.add_argument("--at", default="", help="for a note with no fix: the exact text it is about")
    ap.add_argument("--anchor", default="", help="a phrase from the PDF, if the source cannot place it")
    ap.add_argument("--by", default="", choices=["", *proposals.AGENTS],
                    help="who writes it, claude unless said; it picks the round, <date>-<by>")
    args = ap.parse_args(argv)
    at_file = ""
    if args.at:
        if len(args.file) != 1 or args.old or args.new:
            raise bind.Refused("--at goes with one --file and no --old or --new")
        at_file, args.file = args.file[0], []
    done = proposals.suggest(args.paper, args.note, args.tag, _edits_from(args),
                             summary=args.summary, why=args.why, file=at_file,
                             at=args.at, anchor=args.anchor, by=args.by)
    note = done["note"]
    where = note.get("source") or {}
    print(f"{note['id']}  {note['tag'].lower()}  "
          + (f"{where.get('file')}:{where.get('line')}" if where else "")
          + (f"  page {note['page']}" if done["placed"] else "  (not found on the page)"))
    if done.get("fix"):
        print(f"  fix: {done['fix']['summary']}")
    return 0


def cmd_approve(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen approve")
    ap.add_argument("paper")
    ap.add_argument("note")
    ap.add_argument("fix", nargs="?", default="", help="which, when it has more than one")
    args = ap.parse_args(argv)
    done = proposals.approve(args.paper, args.note, args.fix)
    for fix_id, why in done["failed"].items():
        print(f"  not applied, fix {fix_id}: {why}")
    if done["closed"]:
        print(f"{args.note}: fix {', '.join(done['applied'])} put in; the note is done")
    return 0 if not done["failed"] else 1


def cmd_reject(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen reject")
    ap.add_argument("paper")
    ap.add_argument("notes", nargs="+")
    ap.add_argument("--why", default="", help="a word why, which a later run reads")
    args = ap.parse_args(argv)
    done = proposals.decide(args.paper, args.notes, "reject", args.why)
    for note_id in done["done"]:
        print(f"{note_id} rejected")
    for note_id, why in done["failed"].items():
        print(f"{note_id}: {why}")
    return 0 if not done["failed"] else 1


def cmd_commit(argv: list[str]) -> int:
    """Commit what the round's fixes changed, and nothing else."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen commit")
    ap.add_argument("paper")
    ap.add_argument("--branch", action="store_true",
                    help="on a branch of its own, paperpen/<round>, to be taken or dropped")
    args = ap.parse_args(argv)
    done = review.commit(args.paper, on_branch=args.branch)
    print(f"{done['commit']} on {done['branch']}: {len(done['notes'])} note(s)")
    for rel in done["files"]:
        print(f"  {rel}")
    if done["made"]:
        print(f"  `paperpen branch {args.paper} take` merges it, `... drop` throws it away")
    return 0


def cmd_branch(argv: list[str]) -> int:
    """Take a review branch into the branch it came from, or drop it."""
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen branch")
    ap.add_argument("paper")
    ap.add_argument("what", choices=["take", "drop"])
    args = ap.parse_args(argv)
    if args.what == "take":
        done = review.take(args.paper)
        print(f"took {done['took']} into {done['branch']} ({done['how']}), now {done['commit']}")
    else:
        done = review.drop(args.paper)
        print(f"dropped {done['dropped']}; back on {done['branch']}")
    return 0


def cmd_undo(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen undo")
    ap.add_argument("paper")
    ap.add_argument("note")
    ap.add_argument("fix")
    args = ap.parse_args(argv)
    feedback.undo(args.paper, args.note, args.fix)
    print(f"fix {args.fix} of {args.note} taken back out; the note is open again")
    return 0


def cmd_apply(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="paperpen apply")
    ap.add_argument("paper")
    ap.add_argument("note")
    ap.add_argument("fixes", nargs="+")
    args = ap.parse_args(argv)
    done = feedback.apply(args.paper, args.note, args.fixes)
    for fix_id in done["applied"]:
        print(f"  applied fix {fix_id}")
    for fix_id, why in done["failed"].items():
        print(f"  not applied, fix {fix_id}: {why}")
    print(f"{args.note} closed" if done["closed"] else f"{args.note} left open")
    return 0 if not done["failed"] else 1


def cmd_where() -> int:
    print(f"registry  {config.registry_file()}")
    print(f"cache     {config.cache_root()}")
    print(f"rounds    {config.data_root()}")
    print(f"upstream  {bind.UPSTREAM}")
    up = serving.running()
    print(f"serving   {up['url']}" if up else "serving   no")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "serve":
            return cmd_serve(rest)
        if cmd == "shelf":
            return cmd_shelf()
        if cmd == "about":
            return cmd_about(rest)
        if cmd == "forget":
            return cmd_forget(rest)
        if cmd == "onboard":
            return cmd_onboard(rest)
        if cmd == "lan":
            return cmd_lan(rest)
        if cmd == "tls":
            return cmd_tls(rest)
        if cmd == "qr":
            return cmd_qr(rest)
        if cmd == "record":
            return cmd_record(rest)
        if cmd == "adopt":
            return cmd_adopt(rest)
        if cmd == "sync":
            return cmd_sync(rest)
        if cmd == "bundle":
            return cmd_bundle(rest)
        if cmd == "where":
            return cmd_where()
        if cmd == "feedback":
            return cmd_feedback(rest)
        if cmd == "propose":
            return cmd_propose(rest)
        if cmd == "reply":
            return cmd_reply(rest)
        if cmd == "apply":
            return cmd_apply(rest)
        if cmd == "undo":
            return cmd_undo(rest)
        if cmd == "commit":
            return cmd_commit(rest)
        if cmd == "agent":
            return cmd_agent(rest)
        if cmd == "branch":
            return cmd_branch(rest)
        if cmd == "review":
            return cmd_review(rest)
        if cmd == "suggest":
            return cmd_suggest(rest)
        if cmd == "approve":
            return cmd_approve(rest)
        if cmd == "reject":
            return cmd_reject(rest)
        if cmd == "queue":
            return cmd_queue(rest)
        if cmd == "next":
            return cmd_next(rest)
        if cmd == "versions":
            return cmd_versions(rest)
        if cmd == "rounds":
            return cmd_rounds(rest)
        if cmd == "finish":
            return cmd_finish(rest)
        if cmd in PASSTHROUGH:
            return bind.run(argv)
    except bind.Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"error: no such command: {cmd}\n\n{USAGE}", file=sys.stderr, end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
