"""The gate in front of the reader, and the guard behind every request.

Loopback has no login. A password prompt on `http://127.0.0.1` protects
nothing that the filesystem does not already protect, and a lock that asks
every day for no reason is one people route around.

Off loopback everything is gated, including `/state.tar.gz`, which is the
whole reading history in one file and is the thing you would least like to
hand to whoever else is on the wifi. Unless the login was turned off on
purpose (`paperpen lan --no-login`), for a network its owner trusts.

What no login can stand in for is the browser itself: any web page you have
open can send requests to `127.0.0.1`. So every request, in every mode, must
come to this server under its own name, and a write must come from one of
its own pages. A page elsewhere that posts here is refused, and so is one
that has pointed its own name at this machine (DNS rebinding).
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from flask import redirect, render_template, request, session, url_for

from .. import auth

# A failed attempt costs this long. It is not a lockout: a lockout on a
# single-user reader is a way to be locked out of your own papers by somebody
# else on the network. It makes guessing slow and leaves the door working.
PENALTY = 1.0

# What is reachable without signing in. The favicon, because a login page with
# a broken icon looks like the wrong site, and the login page itself.
OPEN = ("/login", "/favicon.svg")


def wants_json(path: str) -> bool:
    """A fetch() from the reader, rather than a page the person asked for.

    The reader is one page that then talks to these on its own. Redirecting
    those to HTML gives it a login form where it expected JSON and it fails in
    a way nobody can read, so they get a 401 and the page reloads itself.
    """
    return any(path.endswith(s) for s in (".json", "/meta", "/note", "/drop",
                                          "/export", "/build", "/classify",
                                          "/resolve", "/finish")) \
        or "/layout/" in path or request.method == "POST"


# The names this machine answers to on loopback. A request on loopback under
# any other name was sent by a page that has pointed that name here.
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Methods that change something, which must come from one of our own pages.
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def same_site(origin: str, host: str) -> bool:
    """Whether an Origin (or Referer) names this server as it was asked for."""
    return bool(origin) and urlsplit(origin).netloc.lower() == host.lower()


def safe_next(target: str | None) -> str:
    """Where to go after signing in: a path on this server, never elsewhere."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    return target


def install(app, lan: bool) -> None:
    """Put the guard in always, and the gate when reachable from elsewhere."""
    app.secret_key = auth.session_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

    @app.before_request
    def guard():
        host = request.host or ""
        if not lan and (urlsplit("//" + host).hostname or "") not in LOOPBACK:
            return {"ok": False, "error": "this server answers only to its own name"}, 421
        if request.method in WRITES:
            # Browsers send Origin on every cross-site write; Referer is the
            # fallback for the few that do not. A client that sends neither is
            # not a web page (curl, a script of yours) and is let through.
            said = request.headers.get("Origin") or request.headers.get("Referer")
            if said is not None and not same_site(said, host):
                return {"ok": False, "error": "refused: a request from another site"}, 403
        return None

    if not lan or auth.login_off():
        return

    @app.before_request
    def gate():
        if session.get("in") or request.path in OPEN:
            return None
        if wants_json(request.path):
            return {"ok": False, "error": "not signed in"}, 401
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        wrong = ""
        if request.method == "POST":
            password = request.form.get("password", "")
            code = request.form.get("code", "")
            if not auth.check_password(password):
                wrong = "That is not the password."
            elif auth.has_totp() and not auth.check_totp(code):
                # Said the same way as a wrong password on purpose: which of
                # the two was wrong is not something a guesser should learn,
                # and a code already used reads as wrong here too.
                wrong = "That is not the password."
            else:
                session["in"] = True
                session.permanent = True
                return redirect(safe_next(request.args.get("next")))
            time.sleep(PENALTY)
        return render_template("login.html", wrong=wrong,
                               totp=auth.has_totp(),
                               tls=request.is_secure), (200 if not wrong else 401)

    @app.route("/logout", methods=["POST", "GET"])
    def logout():
        session.clear()
        return redirect("/login")
