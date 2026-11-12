# Reference only: the dashboard's own /paper routes, so that a change
# to them shows up in a sync diff. paperpen does not import this.

# --- papers: reading and marking one up on the tablet ---------------------
# The board is only the surface here. scripts/paper.py owns the building, the
# rendering, the anchoring and the export, so a pass can do every one of those
# from a terminal and the tablet and the CLI cannot drift apart.

PAPER_PY = REPO / "scripts" / "paper.py"
PAPERS_FILE = REPO / "papers.json"


def paper_py(*args: str, timeout: int = 900, stdin: str | None = None) -> dict:
    """Run scripts/paper.py and read its JSON back. Raises on a refusal.

    Anything big goes in through `stdin`, never as an argument: the kernel caps
    a single argument at 128 KB and a page of handwriting is comfortably past
    that, which showed up as "argument list too long" on a long note.
    """
    proc = subprocess.run(
        [sys.executable, str(PAPER_PY), *args],
        capture_output=True, text=True, cwd=REPO, timeout=timeout, env=board_env(),
        input=stdin,
    )
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout).strip()[-600:] or "paper.py failed")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError:
        return {"out": out}


_PAPERS_CACHE: dict = {"at": 0.0, "stamp": None, "papers": []}
PAPERS_TTL = 20


def load_papers() -> list[dict]:
    """The registry, from scripts/paper.py itself.

    The board used to work an id out from the name on its own, which is how it
    came to link to one that paper.py no longer answered to. There is one place
    that decides what a paper's id is, and this is not it.
    """
    try:
        stamp = PAPERS_FILE.stat().st_mtime
    except OSError:
        return []
    now = time.time()
    if _PAPERS_CACHE["stamp"] == stamp and now - _PAPERS_CACHE["at"] < PAPERS_TTL:
        return _PAPERS_CACHE["papers"]
    try:
        papers = paper_py("list", "--json", timeout=60)
    except Exception:  # noqa: BLE001  a broken registry must not break the board
        papers = []
    if not isinstance(papers, list):
        papers = []
    _PAPERS_CACHE.update(at=now, stamp=stamp, papers=papers)
    return papers


def find_paper(pid: str) -> dict:
    for p in load_papers():
        if p["id"] == pid:
            return p
    raise ValueError("no such paper")


def paper_cache(pid: str) -> Path:
    return git_common() / "papers" / pid


@app.route("/paper/<pid>")
def paper_reader(pid):
    try:
        paper = find_paper(pid)
    except ValueError:
        return "no such paper", 404
    return PAPER_PAGE.format(
        pid=escape(pid),
        name=escape(paper["name"]),
        board_name=escape(BOARD_NAME),
        task=escape(paper["task"]),
        custom_build="1" if paper["custom_build"] else "",
    )


@app.route("/paper/<pid>/meta")
def paper_meta(pid):
    try:
        find_paper(pid)
        return jsonify(ok=True, **paper_py("meta", pid, timeout=120))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400


@app.route("/paper/<pid>/page/<int:n>.png")
def paper_page(pid, n):
    try:
        find_paper(pid)
        scale = request.args.get("scale", "2")
        float(scale)  # it goes into a filename, so it has to be a number
        png = paper_cache(pid) / "pages" / f"{n:03d}@{float(scale):g}.png"
        if not png.is_file():
            paper_py("render", pid, str(n), "--scale", scale, timeout=120)
        if not png.is_file():
            return "not rendered", 404
        return send_from_directory(png.parent, png.name, max_age=86400)
    except Exception:  # noqa: BLE001
        return "not found", 404


@app.route("/paper/<pid>/layout/<int:n>")
def paper_layout(pid, n):
    """A page's sentences, its words and its figures, so a note can be put on
    one of them rather than on whatever a finger happened to land on."""
    try:
        find_paper(pid)
        cached = paper_cache(pid) / "text" / f"{n:03d}.json"
        if cached.is_file():
            return app.response_class(cached.read_text(encoding="utf-8"),
                                      mimetype="application/json")
        return jsonify(paper_py("layout", pid, str(n), timeout=120))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400


@app.route("/paper/<pid>/note", methods=["POST"])
def paper_note(pid):
    data = request.get_json(force=True, silent=True) or {}
    try:
        paper = find_paper(pid)
        note = paper_py("note", pid, "--json", "-", stdin=json.dumps(data), timeout=120)
        if paper["task"]:
            record(f"task:{paper['task']}", "note",
                   f"{note.get('tag', 'TODO')} on {Path(paper['main']).stem}: "
                   f"{(note.get('note') or 'handwritten')[:70]}")
        return jsonify(ok=True, note=note)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400


@app.route("/paper/<pid>/drop", methods=["POST"])
def paper_drop(pid):
    data = request.get_json(force=True, silent=True) or {}
    try:
        find_paper(pid)
        return jsonify(ok=True, **paper_py("drop", pid, str(data.get("id", "")), timeout=60))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400


@app.route("/paper/<pid>/export", methods=["POST"])
def paper_export(pid):
    try:
        paper = find_paper(pid)
        out = paper_py("export", pid, timeout=300)
        if paper["task"]:
            record(f"task:{paper['task']}", "note",
                   f"{out.get('notes', 0)} notes sent to {Path(paper['repo']).name}")
        return jsonify(ok=True, **out)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400


@app.route("/paper/<pid>/build", methods=["POST"])
def paper_build(pid):
    """Rebuild, for the round trip: a pass revises the source and the tablet
    wants the new PDF without anyone reaching a terminal.

    Only a paper that builds with plain latexmk. A `build` command in
    papers.json is displayed and never run by the board, the same rule
    `dashboards.json` follows for `start`: a config file is not a place from
    which the board should be executing shell, least of all while it is served
    to the VPN. The arguments here come from the registry, never from the
    request.
    """
    try:
        paper = find_paper(pid)
        if paper["custom_build"]:
            raise ValueError("this paper has its own build command in papers.json; "
                             "the board does not run those. Build it from a terminal.")
        paper_py("build", pid, timeout=900)
        return jsonify(ok=True, **paper_py("meta", pid, timeout=120))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 400
