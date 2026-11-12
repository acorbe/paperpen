"""The server: the shelf, and the reader the dashboard already has.

The reader's page is upstream's, filled in here rather than by `str.format`,
and its endpoints are served by calling upstream's functions directly. The
dashboard shells out to `scripts/paper.py` for each of them, which is right
there (it keeps the tablet and a terminal from drifting) and is a subprocess
per page turn here, where the same code is already imported.
"""

from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from .. import (agent, archive, bind, deliver, edit, feedback, proposals, queue, registry,
                 review, rounds, search, shelf, spell, versions)
from . import login

READER = Path(__file__).resolve().parent.parent.parent / "upstream" / "reader.html"
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
TITLE = re.compile(r"<title>.*?</title>", re.S)

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="12" y="6" width="34" height="52" rx="3" fill="#fff" stroke="#5e6c84" stroke-width="3"/>
<path d="M20 20h18M20 28h18M20 36h11" stroke="#9aa3b2" stroke-width="3" stroke-linecap="round"/>
<path d="M48 12 L56 20 L34 42 L26 44 L28 36 Z" fill="#d93025" stroke="#8c1d16" stroke-width="2"
      stroke-linejoin="round"/></svg>"""


def fill(template: str, **fields: str) -> str:
    """Upstream's page is a format string whose braces were undoubled when it
    was taken out of dashboard.py. Filling it by substitution rather than by
    `str.format` is what lets the CSS keep its braces."""
    return PLACEHOLDER.sub(lambda m: fields.get(m.group(1), m.group(0)), template)


def said_of(done: dict) -> str:
    """One sentence for the tablet: what happened and where it went."""
    n = done["notes"]
    many = f"{n} note{'' if n == 1 else 's'}"
    if done["delivery"] == deliver.PDF:
        return f"{many} marked up in {Path(done['where']).name}"
    if done.get("committed"):
        return f"Committed {many} in {Path(done['where']).parent.parent.name}"
    return f"{many} written to {done['where']}, not committed"


def create_app(lan: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # a page of handwriting

    # Nothing is gated on loopback; everything is off it, including the state
    # download. `lan` is passed rather than sniffed from the request, because
    # what matters is what the server was told to bind, not what an individual
    # request claims about itself.
    login.install(app, lan)

    def _limit() -> int:
        try:
            return max(1, min(400, int(request.args.get("n", 60))))
        except ValueError:
            return 60

    def paper_or_400(pid: str):
        for p in bind.load_papers():
            if p.pid == pid:
                return p
        raise bind.Refused("no such paper")

    @app.errorhandler(bind.Refused)
    def refused(e):
        # A route that hands over a file answers like one. The JSON refusal is
        # for the endpoints the page calls with fetch(), where the message is
        # read and shown; a browser following a download link wants a 404.
        page = request.method == "GET" and (
            request.path.endswith(("/versions", "/edit"))
            or "/paper/" in request.path and request.path.count("/") == 2)
        if page or request.path.endswith((".png", ".svg", ".tar.gz")):
            return str(e), 404
        return jsonify(ok=False, error=str(e)), 400

    # --- the shelf ---------------------------------------------------------

    def page_of(groups: list[dict], **extra):
        total = sum(len(g["papers"]) for g in groups)
        return render_template("shelf.html", groups=groups, total=total,
                               kinds=registry.KINDS, **extra)

    @app.route("/")
    def home():
        put_away = sum(len(g["papers"]) for g in shelf.shelf(archived=True))
        return page_of(shelf.shelf(), archived=put_away)

    @app.route("/queue")
    def the_queue():
        want = {"tag": request.args.get("tag", ""),
                "paper": request.args.get("paper", ""),
                "who": request.args.get("who", ""),
                "unclassified": request.args.get("unclassified") == "1"}
        return render_template("queue.html", rows=queue.rows(**want),
                               tally=queue.tally(queue.rows()), want=want,
                               papers=[(p.pid, p.name) for p in bind.load_papers()],
                               tags=queue.TAGS)

    @app.route("/queue/classify", methods=["POST"])
    def classify():
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **queue.classify(str(d.get("paper", "")),
                                                 str(d.get("id", "")),
                                                 str(d.get("tag", ""))))

    @app.route("/queue/resolve", methods=["POST"])
    def resolve():
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **queue.resolve(str(d.get("paper", "")),
                                                str(d.get("id", "")),
                                                str(d.get("status", "done")),
                                                str(d.get("response", ""))))

    # --- what came back for a paper's notes --------------------------------
    #
    # Fixes proposed for delivered notes, by whoever answered them, chosen here
    # and written into the working tree; or a reply, which keeps the note open.

    @app.route("/paper/<pid>/feedback")
    def feedback_page(pid):
        paper = paper_or_400(pid)
        return render_template("feedback.html", pid=paper.pid, name=paper.name,
                               is_pdf=paper.is_pdf, agents=list(proposals.AGENTS))

    @app.route("/paper/<pid>/feedback.json")
    def feedback_items(pid):
        return jsonify(ok=True, items=feedback.items(paper_or_400(pid).pid))

    @app.route("/paper/<pid>/feedback/apply", methods=["POST"])
    def feedback_apply(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **feedback.apply(paper_or_400(pid).pid, str(d.get("note", "")),
                                                 [str(f) for f in d.get("fixes") or []]))

    @app.route("/paper/<pid>/agent", methods=["POST"])
    def run_agent(pid):
        """Ask the agent to answer the newest round, or stop it."""
        d = request.get_json(force=True, silent=True) or {}
        paper = paper_or_400(pid)
        if d.get("what") == "stop":
            return jsonify(ok=True, **agent.stop(paper.pid))
        return jsonify(ok=True, **agent.start(paper.pid, again=bool(d.get("again")),
                                              how=str(d.get("mode", "") or "")))

    @app.route("/paper/<pid>/review", methods=["POST"])
    def start_review(pid):
        """Ask the agent to read the paper first and write notes of its own."""
        d = request.get_json(force=True, silent=True) or {}
        try:
            most = int(d.get("max") or proposals.MOST)
        except (TypeError, ValueError):
            raise bind.Refused("max is a number")
        return jsonify(ok=True, **agent.start(paper_or_400(pid).pid, how=agent.REVIEW,
                                              focus=str(d.get("focus", "") or ""),
                                              most=max(1, min(most, 200))))

    @app.route("/paper/<pid>/proposals/decide", methods=["POST"])
    def decide_proposals(pid):
        """Approve or reject the agent's notes, one or a selection."""
        d = request.get_json(force=True, silent=True) or {}
        notes = [str(n) for n in d.get("notes") or []]
        if not notes:
            raise bind.Refused("choose at least one note")
        return jsonify(ok=True, **proposals.decide(paper_or_400(pid).pid, notes,
                                                   str(d.get("what", "")),
                                                   str(d.get("why", "") or "")))

    @app.route("/paper/<pid>/commit", methods=["POST"])
    def commit_review(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **review.commit(paper_or_400(pid).pid,
                                                on_branch=bool(d.get("branch"))))

    @app.route("/paper/<pid>/branch", methods=["POST"])
    def review_branch(pid):
        d = request.get_json(force=True, silent=True) or {}
        what = str(d.get("what", ""))
        if what not in ("take", "drop"):
            raise bind.Refused("take or drop")
        paper = paper_or_400(pid)
        return jsonify(ok=True, **(review.take(paper.pid) if what == "take"
                                   else review.drop(paper.pid)))

    @app.route("/paper/<pid>/feedback/undo", methods=["POST"])
    def feedback_undo(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **feedback.undo(paper_or_400(pid).pid, str(d.get("note", "")),
                                                str(d.get("fix", ""))))

    @app.route("/paper/<pid>/feedback/reply", methods=["POST"])
    def feedback_reply(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **feedback.reply(paper_or_400(pid).pid, str(d.get("note", "")),
                                                 str(d.get("text", ""))))

    @app.route("/paper/<pid>/feedback/propose", methods=["POST"])
    def feedback_propose(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **feedback.propose(
            paper_or_400(pid).pid, str(d.get("note", "")), str(d.get("summary", "")),
            list(d.get("edits") or []), why=str(d.get("why", "")),
            by=str(d.get("by", "") or feedback.YOU)))

    @app.route("/paper/<pid>/ink/<session>/<note>.png")
    def ink_png(pid, session, note):
        """The picture of a handwritten note, from the paper's repository or
        the local record, whichever has it."""
        paper = paper_or_400(pid)
        if not (re.fullmatch(r"[0-9A-Za-z._-]+", session)
                and re.fullmatch(r"[0-9A-Za-z._-]+", note)):
            raise bind.Refused("no such picture")
        for where in (paper.review / session / "ink", rounds.round_dir(paper, session) / "ink"):
            if (where / f"{note}.png").is_file():
                return send_from_directory(where, f"{note}.png", max_age=300)
        raise bind.Refused("no such picture")

    @app.route("/archived")
    def archived():
        return page_of(shelf.shelf(archived=True), archived=0, title="Archived")

    # --- the state, as a file you can keep --------------------------------
    #
    # The rounds are the one thing here that cannot be made again, so there is
    # a way to take them without a terminal: the tablet you read on can hand
    # the reading back to the machine that keeps it. The rendered ink is left
    # out unless `?ink=1` asks for it, because it comes back from the strokes
    # and is most of the bytes.

    def as_tgz(raw: bytes, name: str):
        answer = app.response_class(raw, mimetype="application/gzip")
        answer.headers["Content-Disposition"] = f'attachment; filename="{name}"'
        answer.headers["Content-Length"] = str(len(raw))
        return answer

    @app.route("/state.tar.gz")
    def whole_state():
        ink = request.args.get("ink") == "1"
        return as_tgz(archive.bundle(ink=ink),
                      f"paperpen-{date.today().isoformat()}.tar.gz")

    @app.route("/paper/<pid>/state.tar.gz")
    def paper_state(pid):
        paper = paper_or_400(pid)
        ink = request.args.get("ink") == "1"
        return as_tgz(archive.bundle([paper.pid], ink=ink),
                      f"{paper.pid}-{date.today().isoformat()}.tar.gz")

    @app.route("/paper/<pid>/thumb.png")
    def thumb(pid):
        png = shelf.thumbnail(paper_or_400(pid))
        if png is None:
            return "not built", 404
        return send_from_directory(png.parent, png.name, max_age=3600)

    @app.route("/paper/<pid>/kind", methods=["POST"])
    def set_kind(pid):
        data = request.get_json(force=True, silent=True) or {}
        fields = {k: data[k] for k in ("kind", "brief", "delivery", "archived")
                  if k in data}
        registry.update(pid, **fields)
        return jsonify(ok=True, **registry.extras(pid))

    # --- the reader, which is upstream's ------------------------------------

    @app.route("/paper/<pid>")
    def reader(pid):
        paper = paper_or_400(pid)
        page = fill(READER.read_text(encoding="utf-8"),
                    pid=html.escape(paper.pid), name=html.escape(paper.name),
                    custom_build="1" if paper.build else "")
        # Every tab says paperpen, so the open ones can be found by searching
        # for it. The reader's own title is only the paper's name, and it is
        # set here rather than patched, because it is the one line that says so.
        return TITLE.sub(f"<title>{html.escape(paper.name)} · paperpen</title>", page, count=1)

    # --- writing it, with the build beside it -------------------------------
    #
    # The text is read from and written to the paper's own working tree. There
    # is no copy and no lock: git is still what knows what changed, and a save
    # is refused rather than merged when the file moved underneath.

    @app.route("/paper/<pid>/edit")
    def edit_page(pid):
        paper = paper_or_400(pid)
        if not edit.editable(paper):
            raise bind.Refused("this paper is a PDF; there is no source to edit")
        info = bind.paper.build_info(paper)
        return render_template("editor.html", pid=paper.pid, name=paper.name,
                               main=paper.main, pages=info.get("pages", 0),
                               synctex=bool(info.get("synctex")),
                               scale=bind.paper.DEFAULT_SCALE,
                               custom_build=bool(paper.build))

    @app.route("/paper/<pid>/main", methods=["POST"])
    def set_main(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **edit.set_main(paper_or_400(pid), str(d.get("main", ""))))

    # --- putting a paper on the shelf, and taking one off ------------------

    @app.route("/papers/add", methods=["POST"])
    def add_paper():
        """A folder or a PDF on this machine, built once before it is kept."""
        d = request.get_json(force=True, silent=True) or {}
        got = bind.add(str(d.get("where", "")).strip(), main=str(d.get("main", "")).strip())
        kind = str(d.get("kind", "")).strip()
        if kind:
            if kind not in registry.KINDS:
                raise bind.Refused(f"kind is one of {', '.join(registry.KINDS)}")
            registry.update(got["id"], kind=kind)
        return jsonify(ok=True, **got)

    @app.route("/paper/<pid>/remove", methods=["POST"])
    def remove_paper(pid):
        paper = paper_or_400(pid)
        registry.remove(paper.pid)
        return jsonify(ok=True, id=paper.pid, name=paper.name,
                       kept=[str(paper.repo), str(rounds.rounds_dir(paper))])

    @app.route("/paper/<pid>/files")
    def source_files(pid):
        return jsonify(ok=True, files=edit.files(paper_or_400(pid)))

    @app.route("/paper/<pid>/source")
    def source_of(pid):
        return jsonify(ok=True, **edit.read(paper_or_400(pid),
                                            request.args.get("path", "")))

    @app.route("/paper/<pid>/source", methods=["POST"])
    def save_source(pid):
        data = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **edit.write(paper_or_400(pid),
                                             str(data.get("path", "")),
                                             str(data.get("text", "")),
                                             str(data.get("was", ""))))

    @app.route("/paper/<pid>/forward")
    def forward(pid):
        """Source line to place on the page."""
        return jsonify(ok=True, **edit.forward(
            paper_or_400(pid), request.args.get("path", ""),
            int(request.args.get("line", 1)), int(request.args.get("col", 1))))

    @app.route("/paper/<pid>/inverse")
    def inverse(pid):
        """Place on the page to source line, which is upstream's own answer."""
        return jsonify(ok=True, **edit.inverse(
            paper_or_400(pid), int(request.args.get("page", 1)),
            float(request.args.get("x", 0)), float(request.args.get("y", 0))))

    # --- the same paper, as it was ------------------------------------------
    #
    # The reader shows the tree that happens to be checked out. Off the reader
    # there is a second view of the same paper: a past build, this one, and
    # latexdiff between them, beside the log they were picked from. A version
    # is named in the URL the way git names it (`work`, a commit, or
    # `old..new`), and everything about it is built into the cache.

    @app.route("/paper/<pid>/versions")
    def version_page(pid):
        paper = paper_or_400(pid)
        return render_template("versions.html", pid=paper.pid, name=paper.name,
                               is_pdf=paper.is_pdf,
                               git=versions.is_git(paper), repo=str(paper.repo))

    @app.route("/paper/<pid>/history")
    def history(pid):
        paper = paper_or_400(pid)
        return jsonify(ok=True, working=versions.working(paper),
                       commits=versions.commits(paper, _limit()))

    @app.route("/paper/<pid>/version/<ref>")
    def version_state(pid, ref):
        return jsonify(ok=True, **versions.state(paper_or_400(pid), ref))

    @app.route("/paper/<pid>/version/<ref>", methods=["POST"])
    def version_build(pid, ref):
        """Compile it. Slow on purpose: the answer is the finished build."""
        paper = paper_or_400(pid)
        force = (request.get_json(force=True, silent=True) or {}).get("force") is True
        return jsonify(ok=True, **versions.build(paper, ref, force=force))

    @app.route("/paper/<pid>/version/<ref>/page/<int:n>.png")
    def version_page_png(pid, ref, n):
        paper = paper_or_400(pid)
        scale = float(request.args.get("scale", bind.paper.DEFAULT_SCALE))
        png = versions.page(paper, ref, n, scale)
        return send_from_directory(png.parent, png.name, max_age=86400)

    @app.route("/paper/<pid>/version/<ref>/layout/<int:n>")
    def version_layout(pid, ref, n):
        return jsonify(ok=True, **versions.layout(paper_or_400(pid), ref, n))

    @app.route("/paper/<pid>/match", methods=["POST"])
    def match(pid):
        """A sentence picked on the diff, found in the reader's build."""
        data = request.get_json(force=True, silent=True) or {}
        words = [str(w) for w in (data.get("words") or [])][:64]
        return jsonify(ok=True, **versions.match(paper_or_400(pid), words,
                                                 int(data.get("center") or 0),
                                                 int(data.get("page") or 0)))

    @app.route("/paper/<pid>/source-diff")
    def source_diff(pid):
        paper = paper_or_400(pid)
        return jsonify(ok=True, **versions.source_diff(
            paper, request.args.get("old", ""),
            request.args.get("new", versions.WORKING)))

    def paper_meta(paper):
        # with the answers to its notes, so the reader can offer a note's fixes
        # in the note itself rather than on a page the reader has to find. Every
        # route that hands the reader its META goes through here: the reader
        # replaces the whole of it, so one without `feedback` loses every fix
        # until the page is loaded again
        return jsonify(ok=True, **bind.paper.cmd_meta(paper),
                       feedback=feedback.by_note(paper),
                       agent={**agent.status(paper), "mode": agent.mode(paper),
                              "runner": agent.runner(paper)},
                       agents=list(proposals.AGENTS),
                       review=review.state(paper))

    @app.route("/paper/<pid>/meta")
    def meta(pid):
        return paper_meta(paper_or_400(pid))

    @app.route("/paper/<pid>/page/<int:n>.png")
    def page(pid, n):
        paper = paper_or_400(pid)
        scale = float(request.args.get("scale", bind.paper.DEFAULT_SCALE))
        png = bind.paper.page_png(paper, n, scale)
        return send_from_directory(png.parent, png.name, max_age=86400)

    @app.route("/paper/<pid>/layout/<int:n>")
    def layout(pid, n):
        return jsonify(bind.paper.layout_cached(paper_or_400(pid), n))

    @app.route("/paper/<pid>/note", methods=["POST"])
    def note(pid):
        data = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, note=bind.paper.cmd_note(paper_or_400(pid), data))

    @app.route("/paper/<pid>/drop", methods=["POST"])
    def drop(pid):
        data = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **bind.paper.cmd_drop(paper_or_400(pid),
                                                      str(data.get("id", ""))))

    @app.route("/paper/<pid>/export", methods=["POST"])
    def export(pid):
        """Finish the open round and deliver it the way this paper is delivered."""
        data = request.get_json(force=True, silent=True) or {}
        done = deliver.finish(pid, str(data.get("delivery", "")))
        return jsonify(ok=True, said=said_of(done), **done)

    @app.route("/paper/<pid>/build", methods=["POST"])
    def build(pid):
        paper = paper_or_400(pid)
        if paper.build:
            raise bind.Refused(
                "this paper has its own build command in papers.json; the "
                "server does not run those. Build it from a terminal.")
        bind.paper.cmd_build(paper)
        return paper_meta(paper)

    # --- search, orderless, over the paper as it reads and as it is written --

    @app.route("/orderless.js")
    def orderless_js():
        """The matching every page shares, so a search means the same thing
        wherever it is typed."""
        body = (Path(__file__).resolve().parent / "orderless.js").read_text(encoding="utf-8")
        return app.response_class(body, mimetype="text/javascript",
                                  headers={"Cache-Control": "max-age=300"})

    @app.route("/paper/<pid>/search")
    def search_text(pid):
        return jsonify(ok=True, **search.sentences(paper_or_400(pid).pid,
                                                   request.args.get("q", "")))

    @app.route("/paper/<pid>/grep")
    def search_source(pid):
        return jsonify(ok=True, **search.lines(paper_or_400(pid).pid, request.args.get("q", ""),
                                               only=request.args.get("file", "")))

    @app.route("/paper/<pid>/spell", methods=["POST"])
    def spell_check(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **spell.check(paper_or_400(pid).pid, str(d.get("text", ""))))

    @app.route("/paper/<pid>/spell/accept", methods=["POST"])
    def spell_accept(pid):
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(ok=True, **spell.accept(paper_or_400(pid).pid, str(d.get("word", ""))))

    @app.route("/favicon.svg")
    def favicon():
        return app.response_class(FAVICON, mimetype="image/svg+xml")

    return app
