#!/usr/bin/env python3
"""The manual: one shell, six pages, written here and committed as HTML.

    scripts/manual.py            write manual/*.html
    scripts/manual.py --check    say whether what is committed is what this
                                 file produces, and change nothing

GitHub Pages publishes `manual/` as it stands, so the CI job copies a directory
and does not build anything. That is the point: a manual whose publication
depends on a toolchain in a runner is a manual that stops being published on
the day the toolchain moves, and this one has to survive being ignored for a
year. The pictures come from `scripts/manual-shots.py`, out of the demo shelf,
which is invented: no paper of anybody's and no path of anybody's is in them.

Nothing in here may name the house: no home directories, no internal
hostnames, no private repository names, no campus addresses. `tests/test_manual.py`
is the check, and the addresses used in examples are the ranges the RFCs set
aside for documentation.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "manual"

PAGES = [
    ("index.html", "What it is"),
    ("reading.html", "Reading a paper"),
    ("writing.html", "Writing it back"),
    ("network.html", "The tablet, over the network"),
    ("agents.html", "Working the queue"),
    ("commands.html", "Every command"),
]

CSS = """/* Written by scripts/manual.py. One file, no fonts fetched, no scripts. */
:root {
  color-scheme: light dark;
  --bg: #f6f7f9; --paper: #fff; --ink: #1c2330; --muted: #5e6c84;
  --line: #d8dde5; --accent: #0b6ab8; --mark: #fff3cd; --code: #f0f2f5;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171d; --paper: #1d222b; --ink: #e7eaf0; --muted: #9aa3b2;
          --line: #2c333f; --accent: #6cb6ff; --mark: #3a3212; --code: #232935; }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink); line-height: 1.6;
  font-family: -apple-system, "Segoe UI", Roboto, system-ui, sans-serif;
  font-size: 16px;
}
a { color: var(--accent); }
header.top {
  display: flex; align-items: baseline; gap: 1.2rem; flex-wrap: wrap;
  padding: .9rem 1.4rem; background: var(--paper); border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 5;
}
header.top .mark { font-weight: 700; text-decoration: none; color: var(--ink); }
header.top nav { display: flex; gap: 1rem; flex-wrap: wrap; font-size: .87rem; }
header.top nav a { text-decoration: none; color: var(--muted); }
header.top nav a:hover, header.top nav a.here { color: var(--accent); }
main { max-width: 52rem; margin: 0 auto; padding: 1.6rem 1.4rem 4rem; }
h1 { font-size: 1.6rem; line-height: 1.25; margin: .6rem 0 .3rem; }
h2 { font-size: 1.1rem; margin: 2.2rem 0 .4rem; }
h3 { font-size: .95rem; margin: 1.4rem 0 .3rem; }
p, li { font-size: .95rem; }
.lede { font-size: 1.05rem; color: var(--muted); margin-top: 0; }
code, pre { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
code { background: var(--code); padding: .08em .3em; border-radius: 4px; font-size: .88em; }
pre {
  background: var(--code); padding: .8rem 1rem; border-radius: 8px; overflow-x: auto;
  font-size: .84rem; line-height: 1.5; border: 1px solid var(--line);
}
pre code { background: none; padding: 0; font-size: 1em; }
figure { margin: 1.4rem 0; }
figure img {
  width: 100%; display: block; border: 1px solid var(--line); border-radius: 8px;
  background: var(--paper);
}
figcaption { font-size: .82rem; color: var(--muted); margin-top: .45rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: .8rem; text-transform: uppercase;
     letter-spacing: .04em; }
td code { white-space: nowrap; }
.note {
  border-left: 3px solid var(--accent); background: var(--paper); padding: .7rem 1rem;
  margin: 1.2rem 0; border-radius: 0 8px 8px 0; font-size: .92rem;
}
.note b { color: var(--accent); }
.warn { border-left-color: #c2701a; }
.warn b { color: #c2701a; }
footer {
  border-top: 1px solid var(--line); margin-top: 3rem; padding: 1.2rem 1.4rem 3rem;
  color: var(--muted); font-size: .82rem; text-align: center;
}
footer a { color: var(--muted); }
.next { display: flex; justify-content: space-between; gap: 1rem; margin-top: 2.5rem;
        font-size: .9rem; }
"""

SHELL = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{title} · paperpen</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{blurb}">
<link rel="stylesheet" href="manual.css">
<header class="top">
  <a class="mark" href="index.html">paperpen</a>
  <nav>{nav}</nav>
</header>
<main>
{body}
{next}
</main>
<footer>
  Read a paper on a tablet, mark it up with a pen, get the marks back where the
  paper is written. · <a href="index.html">the manual</a> ·
  by <a href="https://github.com/acorbe">acorbe</a>
</footer>
</html>
"""


def nav(current: str) -> str:
    # No backslash inside the expression: an f-string cannot hold one before
    # Python 3.12, and this package says it runs on 3.10.
    out = []
    for name, title in PAGES:
        mark = ' class="here"' if name == current else ""
        out.append(f'<a href="{name}"{mark}>{title}</a>')
    return "\n    ".join(out)


def onward(current: str) -> str:
    names = [p[0] for p in PAGES]
    at = names.index(current)
    back = f'<a href="{PAGES[at-1][0]}">&larr; {PAGES[at-1][1]}</a>' if at else "<span></span>"
    on = (f'<a href="{PAGES[at+1][0]}">{PAGES[at+1][1]} &rarr;</a>'
          if at + 1 < len(PAGES) else "<span></span>")
    return f'<div class="next">{back}{on}</div>'


# --- the pages -------------------------------------------------------------

INDEX = """
<h1>Read a paper with a pen, and get the marks back</h1>
<p class="lede">paperpen puts a paper on a tablet, takes pen marks on it, and
returns each one anchored to the line of LaTeX that made the sentence, or as a
PDF with the notes in the margin, for whoever wrote the paper.</p>

<p>It exists because the round trip is where the work is lost. A draft is read
away from the desk, the marks are made on glass, and then somebody sits down
and retypes them into the source from memory. paperpen keeps the anchor: a note
made on a sentence comes back as <code>sec_results.tex:41</code> and the
sentence it sat on, so the note can be acted on rather than reconstructed.</p>

<figure>
  <img src="shots/shelf.png" alt="The shelf: four papers grouped by who is waiting">
  <figcaption>The shelf groups papers by who is waiting on whom: a reading in
  progress, a round sent and unanswered, and the ones with nothing
  outstanding.</figcaption>
</figure>

<h2>The loop</h2>
<ol>
  <li><b>Add a paper.</b> A LaTeX repository, a folder, or a PDF somebody sent
  you.</li>
  <li><b>Read it</b> in a browser, on a tablet, with a stylus. Notes are typed
  or handwritten, and both are kept.</li>
  <li><b>Finish the round.</b> The notes are delivered the way that paper is
  delivered: committed into its repository, written to a folder, or turned into
  a marked-up PDF to send.</li>
  <li><b>Act on them</b> in the source, and mark each note done or rejected
  with what was decided. paperpen starts an agent in the paper's checkout to
  do it, or you run a session there by hand (see
  <a href="reading.html#after-finish-and-send">After Finish and send</a>). The
  next reading shows what happened to the last one.</li>
</ol>

<h2>Starting it</h2>
<p>Python 3.10 or newer, and <code>latexmk</code> for a paper with LaTeX
behind it. With <a href="https://docs.astral.sh/uv/">uv</a>:</p>
<pre><code>git clone https://github.com/acorbe/paperpen.git
cd paperpen
uv run paperpen add ~/papers/my-manuscript      # or a .pdf
uv run paperpen serve</code></pre>
<p>It prints where it is, and that is the address to open:</p>
<pre><code>registry ~/.config/paperpen/papers.json
cache    ~/.cache/paperpen
shelf    http://127.0.0.1:8770/
reader   http://127.0.0.1:8770/paper/&lt;id&gt;   ·   queue http://127.0.0.1:8770/queue</code></pre>
<p>Without uv, a virtual environment and <code>pip install -e .</code> gives
the same <code>paperpen</code> command. Either way nothing is installed
system-wide and nothing runs as a service.</p>

<div class="note"><b>Loopback by default.</b> The server listens on
<code>127.0.0.1</code> and is reachable only from the machine it runs on.
Putting it where the tablet can see it is a deliberate second step, and it is
closed with a login unless you choose otherwise: see <a href="network.html">the network page</a>.</div>

<h2>Where things are kept</h2>
<table>
  <tr><th>What</th><th>Where</th><th>Lifetime</th></tr>
  <tr><td>The registry</td><td><code>~/.config/paperpen/papers.json</code></td>
      <td>Configuration. Small, hand-editable, worth backing up.</td></tr>
  <tr><td>The cache</td><td><code>~/.cache/paperpen/&lt;paper&gt;/</code></td>
      <td>Built PDFs, rendered pages, version builds. Delete it freely; it is
      made again.</td></tr>
  <tr><td>The rounds</td><td><code>~/.local/share/paperpen/&lt;paper&gt;/</code></td>
      <td>What was read and said, and where it went. This cannot be made
      again.</td></tr>
  <tr><td>The paper</td><td>its own repository</td>
      <td>Output, not state: a delivered round is committed there as
      <code>review/&lt;date&gt;/</code>.</td></tr>
</table>
<p><code>paperpen where</code> prints the four, which is the quickest way to
find out what a machine is actually using. Each takes an environment override
(<code>PAPERPEN_HOME</code>, <code>PAPERPEN_CACHE</code>,
<code>PAPERPEN_DATA</code>), and a <code>.paperpen/papers.json</code> in the
current directory wins over all of them, so a folder of drafts can carry its
own shelf and be moved whole.</p>
"""

READING = """
<h1>Reading a paper</h1>
<p class="lede">The shelf, the reader, and what a round is.</p>

<h2>Adding one</h2>
<pre><code>paperpen add ~/papers/my-manuscript     # finds the main .tex, builds it once
paperpen add ~/inbox/referee-draft.pdf   # a PDF with no source behind it
paperpen list</code></pre>
<p><code>add</code> looks for the <code>.tex</code> holding
<code>\\documentclass</code>, takes the paper's name from its
<code>\\title</code>, compiles it once to check, and registers it. A paper that
does not compile is not registered. <code>--main</code>, <code>--name</code>
and <code>--task</code> override what it worked out.</p>

<div class="note"><b>SyncTeX is what makes a note worth having.</b> Build with
<code>latexmk -pdf -synctex=1</code>, which is what paperpen does for you. A
paper without it can still be read and marked up; its notes carry a page and a
quoted sentence, and no source line.</div>

<h2>What a paper is, on the shelf</h2>
<p>Two fields decide how a paper behaves, and both can be set from the card or
from <code>paperpen about</code>:</p>
<table>
  <tr><th>Field</th><th>Values</th><th>What it changes</th></tr>
  <tr><td>kind</td><td>mine, coauthor, student, referee</td>
      <td>Who the reading is for, and the default delivery.</td></tr>
  <tr><td>delivery</td><td>repo, folder, pdf</td>
      <td>Where a finished round goes.</td></tr>
</table>
<pre><code>paperpen about my-manuscript --kind mine --delivery repo
paperpen about referee-draft --brief "Is the claim in Sec. 4 supported?"</code></pre>
<p>The brief is shown on the card and in the reader: what this reading is
for, in one line, written before it starts.</p>

<h2>The reader</h2>
<figure>
  <img src="shots/reader.png" alt="A page of a paper with a note being written">
  <figcaption>A note is made on a sentence, a word, a figure or a region. The
  selection is the anchor, so a note is never vague about what it is
  about.</figcaption>
</figure>
<p>Three tools: <b>Read</b> moves the paper, <b>Note</b> types one, <b>Pen</b>
writes on it. A finger scrolls and only a stylus draws, so the paper can be
moved with a hand resting on the glass.</p>
<ul>
  <li><b>Sentence or word.</b> The text layer is cut into sentences, each
  keeping the boxes it occupies, so tapping a line means the sentence and not
  the line.</li>
  <li><b>Handwriting is kept as ink</b>, cropped to the page around it. There
  is no OCR: the picture is the note, and whoever picks it up reads it.</li>
  <li><b>Rebuild</b> compiles again when the source has moved past the PDF on
  show. The reader says when that has happened.</li>
</ul>

<h2>Rounds</h2>
<p>A round is a reading, not a note. It opens with the first note and stays
open until it is finished, which is when it is delivered:</p>
<pre><code>paperpen rounds my-manuscript             # every round, and how each stands
paperpen finish my-manuscript             # deliver it the way this paper is delivered
paperpen finish referee-draft --as pdf    # or override, once</code></pre>
<p>Delivery is one of three:</p>
<table>
  <tr><th>repo</th><td>Commits <code>review/&lt;date&gt;/</code> into the
  paper's own repository: <code>NOTES.md</code> to act on,
  <code>notes.json</code> as the record, <code>ink/&lt;id&gt;.png</code> for
  each handwritten note.</td></tr>
  <tr><th>folder</th><td>The same directory, written beside the paper and not
  committed.</td></tr>
  <tr><th>pdf</th><td><code>&lt;main&gt;-notes-&lt;date&gt;.pdf</code>: the
  paper with every note in the margin, for somebody who does not have the
  repository.</td></tr>
</table>
<p>Whatever the delivery, the round is also recorded locally. That is
deliberate: a draft sent back as a PDF leaves no trace anywhere else, and a
repository can be on a machine that is not this one.</p>

<h2 id="after-finish-and-send">After Finish and send</h2>
<p>Finish and send closes the round and commits
<code>review/&lt;date&gt;/</code> into the paper's repository. Answering the
notes happens in the paper's checkout, by an agent. paperpen starts one there
itself, headless, the moment the round is delivered, and that is the usual way
(<a href="agents.html">An agent above the papers</a>). The other way is a
session you start by hand, pointed at the round: any LLM that can run a shell
command will do, and Claude Opus is what we have used.</p>
<p>The agent paperpen starts is Claude Code by default, and OpenAI Codex with
<code>--runner codex</code>: for one run on <code>paperpen agent</code> or
<code>paperpen review</code>, for a paper with <code>paperpen about &lt;paper&gt;
--runner codex</code>, or for every paper with <code>PAPERPEN_RUNNER=codex</code>.
Claude Code is given a list of what it may do, paperpen's own commands and
reading files. Codex has no such list and is fenced by its
<code>workspace-write</code> sandbox instead: it may write the paper's checkout
and paperpen's data and cache, and is told not to commit. <code>paperpen
onboard --check</code> says which of the two is installed and which is in
force.</p>
<p>Each note
carries the file and line of LaTeX it is about, its class, and the sentence it
sits on, and a handwritten note is a picture, <code>ink/&lt;id&gt;.png</code>,
which the model reads directly. A session therefore needs the round and little
else:</p>
<pre><code>Work through review/&lt;date&gt;/NOTES.md in this repository. For each note, change
the LaTeX it points at, or say why not; for a handwritten note, read its
ink/&lt;id&gt;.png. Rebuild the paper, close each note with
  paperpen resolve &lt;paper&gt; &lt;note-id&gt; done|rejected "what was done"
and commit.</code></pre>
<p>Whether a round's corrections go in, and when, is a decision about the
paper: nothing is committed until you say so, in the reader or with
<code>paperpen commit</code>. The commit that comes back is what the
next reading is read against, and <code>paperpen versions &lt;paper&gt;</code>
shows it beside the draft the notes were written on. This applies to a paper
delivered into a repository; a draft sent back as a PDF is corrected by
whoever wrote it.</p>

<h2>The queue</h2>
<figure>
  <img src="shots/queue.png" alt="Every open note from every paper, in one list">
  <figcaption>Every open note, from every paper, oldest first, because the
  work is rarely "read a paper" and usually "nine notes are still
  open".</figcaption>
</figure>
<p>A note carries a class (SCIENCE, LANGUAGE, QUESTION, TODO) or is left on
AUTO for whoever picks it up to decide. Closing one says what was done:</p>
<pre><code>paperpen classify my-manuscript 2026-04-02-07 SCIENCE
paperpen resolve  my-manuscript 2026-04-02-07 done "rewrote the paragraph"
paperpen resolve  my-manuscript 2026-04-02-08 rejected "the figure is right as it is"</code></pre>
<p>Both work from any directory, and both write wherever that round is kept:
the copy in the paper's repository, so the <code>NOTES.md</code> a co-author
reads is regenerated, and the local record.</p>
"""

WRITING = """
<h1>Writing it back</h1>
<p class="lede">The source with the build beside it, and the paper beside its
own past.</p>

<h2>The editor</h2>
<p><b>Edit</b>, in the reader's header or on a shelf card, opens the paper's
source on the left and the build on the right.</p>
<figure>
  <img src="shots/editor.png" alt="LaTeX source on the left, the compiled page on the right">
  <figcaption>Double click a line and the place it made lights up on the page.
  Double click the page and the line that made it takes the caret, in the
  right file, which for an <code>\\input</code> is not the one that was
  compiled.</figcaption>
</figure>
<p>Both directions are the same SyncTeX map the reader uses to hang a note on a
sentence, read forwards as well as backwards.</p>

<h3>The window breaks</h3>
<p><code>C-x 3</code> puts a second window beside the first and
<code>C-x 2</code> below it; each takes its own file, or another part of the
same one, and the divider drags. The buttons in the header do the same for a
keymap without chords.</p>

<h3>Two keymaps</h3>
<table>
  <tr><th></th><th>standard</th><th>emacs</th></tr>
  <tr><td>save</td><td><code>Ctrl-S</code></td><td><code>C-x C-s</code></td></tr>
  <tr><td>build</td><td><code>Ctrl-Enter</code>, <code>F5</code></td><td><code>C-c C-c</code></td></tr>
  <tr><td>show this line in the build</td><td><code>F8</code></td><td><code>C-c C-v</code></td></tr>
  <tr><td>find, again</td><td><code>Ctrl-F</code>, <code>F3</code></td><td><code>C-s</code></td></tr>
  <tr><td>split beside, below</td><td><code>Alt-3</code>, <code>Alt-2</code></td><td><code>C-x 3</code>, <code>C-x 2</code></td></tr>
  <tr><td>close, only, next window</td><td><code>Alt-0</code>, <code>Alt-1</code>, <code>F6</code></td><td><code>C-x 0</code>, <code>C-x 1</code>, <code>C-x o</code></td></tr>
  <tr><td>moving about</td><td>arrows, Home, End</td><td><code>C-a C-e C-f C-b C-n C-p</code>, <code>M-f M-b</code>, <code>M-&lt;</code>, <code>M-&gt;</code></td></tr>
  <tr><td>kill, yank, region</td><td>the usual clipboard</td><td><code>C-k</code> (a run collects), <code>C-y</code>, <code>C-Space</code> then <code>C-w</code> or <code>M-w</code></td></tr>
</table>
<p>Arrow keys, shift-selection and the browser's own undo work in both. The
<code>?</code> button lists whichever map is on, and the choice is
remembered.</p>
<div class="note warn"><b>Four keys are the browser's.</b> <code>C-w</code>,
<code>C-n</code>, <code>C-t</code> and <code>C-q</code> never reach a page:
<code>C-w</code> closes the tab. They are bound anyway for a browser that lets
them through, and the region can always be killed with <code>C-Space</code>
then <code>C-k</code>.</div>

<h3>What it writes, and when</h3>
<p>Nothing until you ask. There is no autosave, because a background write that
lands while a sentence is half rewritten is a change to a paper that nobody
made. <b>build on save</b> compiles after a save, for anyone who wants that
rhythm.</p>
<p>Saving writes the file in the paper's own working tree, with no copy and no lock,
so <code>git status</code>, <code>git diff</code> and every other habit go on
meaning what they meant. Two guards sit around it:</p>
<ul>
  <li><b>A file that moved underneath is not overwritten.</b> A pull, a sync
  from elsewhere, or another window is allowed to win. The save is refused and
  both answers are offered: keep yours and write it anyway, or take the file as
  it is now, which puts what you had in the kill ring, so <code>C-y</code>
  brings it back into the new text.</li>
  <li><b>The previous contents are kept first</b>, in
  <code>~/.cache/paperpen/&lt;paper&gt;/edits/</code>, the last twenty saves of
  each file. A short net for the ten minutes before a commit; git is the long
  one.</li>
</ul>
<p>It is an editor for writing sentences in a paper and nothing else: no
completion, no linting, no live collaboration. The merge tool is git, which is
already there.</p>

<h2>The paper beside its own past</h2>
<p><b>Versions</b> opens four panes: the log, a build at a past commit, the
build as it is now, and latexdiff between the two.</p>
<figure>
  <img src="shots/versions.png" alt="The log, an old build, the current build, and the diff">
  <figcaption>One page number drives all three, and with <code>locked</code> on
  they scroll together. <code>source</code> in the diff pane swaps the
  marked-up PDF for <code>git diff</code> over the <code>.tex</code>, which is
  what shows a macro or a figure path.</figcaption>
</figure>
<pre><code>paperpen versions my-manuscript                 # the log, and which of it is built
paperpen versions my-manuscript --build 901c97a # that commit, compiled
paperpen versions my-manuscript --diff 901c97a  # latexdiff against the working tree
paperpen versions my-manuscript --source 901c97a
paperpen versions my-manuscript --forget        # throw the version builds away</code></pre>
<div class="note"><b>Nothing is written into the paper's repository.</b> A
version is taken with <code>git archive</code>, which only reads, and unpacked
into the cache, so this works on a repository that is dirty or mid-rebase, and
no worktree administration is left behind to prune.</div>
<p>A commit cannot change, so once built it is served from the cache forever. A
build with the working tree on one side can, so it is marked <i>the paper has
been edited since</i> rather than quietly redrawn, with a
<code>rebuild</code> button in the pane.</p>
<p>latexdiff does the markup and has to be installed. A manuscript that needs
its own flags sets the whole command:</p>
<pre><code>PAPERPEN_LATEXDIFF="latexdiff --flatten --math-markup=whole" paperpen serve</code></pre>
"""

NETWORK = """
<h1>The tablet, over the network</h1>
<p class="lede">The reader is worth having on the tablet, which means the
server has to leave the machine it runs on. That is one flag, and it is closed
behind a login unless you choose otherwise.</p>

<pre><code>paperpen onboard             # the login, the certificate and a first paper, once
paperpen lan                 # choose the login again
paperpen tls                 # a certificate for this machine
paperpen serve --lan         # every interface, over https, behind the login</code></pre>

<p><code>serve --lan</code> prints what the tablet needs:</p>
<pre><code>shelf    https://127.0.0.1:8770/
network  https://192.0.2.17:8770/   password and six digits to get in
tls      ~/.config/paperpen/tls/cert.pem
         AD:B0:30:1C:3D:8D:E0:B3:03:1A:D7:6B:2A:AF:8E:66:…

    █▀▀▀▀▀█ ▀▄ ▀▀█▄▀▀▄▀▀█ █▀▀▀▀▀█
    █ ███ █ █▀▀ ▀▄ ▄ ▀ █▄ █ ███ █
    █ ▀▀▀ █ ▄█▀ ▄█  ▀██▄▀ █ ▀▀▀ █
    …
    https://192.0.2.17:8770/</code></pre>
<p>The QR code is there because an address like that is otherwise typed on
glass. <code>paperpen qr</code> shows it again on its own.</p>

<h2>The login</h2>
<p>Onboarding and <code>paperpen lan</code> ask how the reader on the network
lets people in:</p>
<ol>
  <li><b>A password and six digits from an authenticator app.</b> Recommended,
  and the default.</li>
  <li><b>A password only.</b></li>
  <li><b>No login.</b> Anyone who can reach the address can read your papers
  and notes, change their sources and download all of it. Fair at home, on a
  network that is yours; wrong on conference or campus wifi. It is confirmed
  by typing <code>no login</code>, and <code>serve --lan</code> warns about it
  every time it starts. <code>paperpen lan --no-login</code> chooses it
  directly, and <code>paperpen lan</code> turns a login back on.</li>
</ol>
<p>Nothing is ever served to the network unlocked by default: until one of the
three is chosen, <code>serve --lan</code> asks.</p>
<ul>
  <li>The password is hashed with scrypt and kept in
  <code>~/.config/paperpen/auth.json</code>, mode 600, and deliberately not
  <code>papers.json</code>, which is the file meant to be handed around.</li>
  <li><code>paperpen lan</code> offers a second factor: a standard TOTP secret
  any authenticator app will take, shown as a QR code to scan.</li>
  <li>A wrong password and a wrong code give the same answer, and a failure
  costs a second.</li>
  <li>Whatever the login, the server refuses a write sent by another site's
  page, and on loopback answers only to its own name, because any page open in
  your browser can send requests to this machine.</li>
</ul>

<h2>The certificate</h2>
<p><code>paperpen tls</code> makes a self-signed certificate for this machine
and prints its fingerprint and both honest ways to use it:</p>
<ul>
  <li><b>Install it on the tablet</b> (the file is
  <code>~/.config/paperpen/tls/cert.pem</code>) and the browser stops
  complaining. On iOS that is Settings → General → VPN &amp; Device Management,
  then Certificate Trust Settings.</li>
  <li><b>Or accept the warning once</b>, after checking the fingerprint against
  what the terminal printed. That is a real check, not a formality: it is what
  the warning is asking you to do.</li>
</ul>
<div class="note warn"><b>The address is in the certificate, as an address.</b>
A certificate naming only a hostname has not been accepted by a browser since
2017, so the LAN address goes in as an IP subject alternative name. If the
machine's address changes, <code>serve --lan</code> says so and
<code>paperpen tls --renew</code> makes a new one. The certificate is good for
397 days, because Apple refuses anything longer.</div>

<h2>Taking the state with you</h2>
<p>The rounds are the one thing here that cannot be made again, and the tablet
has no terminal. <b>take the state</b> in the shelf header is the whole of it
as one file:</p>
<pre><code>paperpen bundle                  # everything: the registry and every round
paperpen bundle my-manuscript    # one paper, with its manifest
paperpen bundle --ink            # include the rendered handwriting</code></pre>
<p>The same two are <code>/state.tar.gz</code> and
<code>/paper/&lt;id&gt;/state.tar.gz</code> in a browser. The rendered ink is
left out by default: it comes back from the strokes and is most of the
bytes.</p>

<h2>A paper that carries its own history</h2>
<p>With <code>record: repo</code>, a finished round leaves a manifest beside
itself in the paper's repository:</p>
<pre><code>&lt;paper&gt;/review/
  paperpen.json          which paper this is, how it is read, which rounds exist
  2026-04-02/            NOTES.md, notes.json, ink/</code></pre>
<p>That is enough to rebuild the shelf entry from a clone, which is what
<code>adopt</code> does, so a paper can move between machines, or be picked up
by whoever has the repository:</p>
<pre><code>paperpen adopt git@example.org:group/manuscript.git
paperpen adopt ~/papers/manuscript
paperpen sync                    # pull every paper's repo, re-read the rounds</code></pre>
"""

AGENTS = """
<h1>Working the queue</h1>
<p class="lede">Deciding which paper to work on is not repository work. The
registry, the shelf and the queue already stand above every repository, and
these are the commands that read them.</p>

<pre><code>paperpen queue                   # every open note, every paper, oldest first
paperpen queue --json            # the same, on stdout, with nothing else on it
paperpen queue --unclassified    # the ones left on AUTO, which is the triage
paperpen queue --paper X --older-than 14
paperpen next                    # what to do first, and the command that does it
paperpen next --all --json       # the whole list, in order</code></pre>

<h2>What <code>next</code> answers</h2>
<p>Four kinds, never a fifth:</p>
<table>
  <tr><th>classify</th><td>Delivered notes have no class. The class decides who
  acts on a note, so this is the cheapest thing that unblocks the
  rest.</td></tr>
  <tr><th>work</th><td>A round is still open. The answer names the round's
  <code>NOTES.md</code> and how old it is.</td></tr>
  <tr><th>build</th><td>The source has moved past the build the reader is
  showing.</td></tr>
  <tr><th>finish</th><td>A reading is open and unsent. Reported, not urged:
  whether a round is finished is a judgment about a paper, not arithmetic about
  notes.</td></tr>
</table>
<p>Neither command writes anything, which is what makes them safe to give to
something that has no business editing a manuscript.</p>

<h2>Acting on one note</h2>
<p>Every row carries what is needed without opening the paper first: the source
line, the sentence the note sits on, its age, and for a handwritten note the
path to its picture.</p>
<pre><code>{
  "id": "2026-04-02-07",
  "paper": "my-manuscript",
  "tag": "AUTO",
  "source": "sec_results.tex:41",
  "anchor": "Above the knee the 48 cells agree closely; below it they scatter.",
  "ink": "~/papers/manuscript/review/2026-04-02/ink/2026-04-02-07.png",
  "age": 6,
  "handwritten": true
}</code></pre>
<p>There is no OCR anywhere in this, so a handwritten note is read by whoever
picks it up, which may be something with no browser, hence the path.</p>

<h2>Two scopes, not two processes</h2>
<p>The useful split is not how many things are running, it is what each of them
can reach.</p>
<ul>
  <li><b>Above the repositories</b>: the queue, the triage, the ordering, and
  closing a note. These go through the registry and work from any directory.
  Nothing here needs a paper's source.</li>
  <li><b>Inside one repository</b>: reading <code>review/&lt;date&gt;/NOTES.md</code>,
  changing the LaTeX, rebuilding, committing. One build, one history, one set
  of co-authors; a mistake reaches one paper.</li>
</ul>
<div class="note warn"><b>Check which shelf is in force.</b> A
<code>.paperpen/papers.json</code> in the current directory wins over the
global registry. Anything running in such a directory is looking at a different
shelf, silently. <code>paperpen where</code> says which.</div>

<h2>What a paper's repository should say</h2>
<p>Whoever works in the paper's own repository, a person or otherwise, needs
to know three things, and they belong in that repository rather than in
somebody's head:</p>
<ol>
  <li><code>review/&lt;date&gt;/NOTES.md</code> is what to act on. Line numbers
  are from the build the note was made on and drift as the source is edited;
  <b>the quoted sentence is what to search for</b>.</li>
  <li><code>notes.json</code> is the record; <code>NOTES.md</code> is
  generated from it, so it is never hand-edited.</li>
  <li>A note is closed with <code>paperpen resolve</code>, with what was done,
  so the next reading shows what happened to the last one.</li>
</ol>
"""

COMMANDS = """
<h1>Every command</h1>
<p class="lede"><code>paperpen --help</code> prints this list;
<code>paperpen &lt;command&gt; --help</code> prints one.</p>

<h2>The shelf</h2>
<table>
  <tr><td><code>paperpen add &lt;repo-or-pdf&gt;</code></td><td>Register a paper: find the main file, build it once.</td></tr>
  <tr><td><code>paperpen list</code></td><td>What is registered.</td></tr>
  <tr><td><code>paperpen shelf</code></td><td>The shelf in the terminal, and where the browser one is.</td></tr>
  <tr><td><code>paperpen about &lt;paper&gt;</code></td><td>Kind, brief, delivery, archived, the agent and its runner. <code>--agent</code>, <code>--runner claude|codex</code>.</td></tr>
  <tr><td><code>paperpen where</code></td><td>Which registry and caches are in force.</td></tr>
  <tr><td><code>paperpen check &lt;repo&gt;</code></td><td>Whether a repository is ready to be added.</td></tr>
</table>

<h2>Reading and rounds</h2>
<table>
  <tr><td><code>paperpen serve</code></td><td>The shelf, the reader, the editor. <code>--port</code>, <code>--host</code>, <code>--lan</code>, <code>--no-tls</code>, <code>--qr</code>, <code>--light</code>, <code>--debug</code> (loopback only).</td></tr>
  <tr><td><code>paperpen build &lt;paper&gt;</code></td><td>latexmk with SyncTeX, into the cache.</td></tr>
  <tr><td><code>paperpen rounds &lt;paper&gt;</code></td><td>Every round, and how each one stands.</td></tr>
  <tr><td><code>paperpen finish &lt;paper&gt;</code></td><td>Close the open round and deliver it. <code>--as repo|pdf|folder</code>, <code>--no-commit</code>.</td></tr>
  <tr><td><code>paperpen notes &lt;paper&gt;</code></td><td>Every note, and whether it is closed.</td></tr>
</table>

<h2>The queue</h2>
<table>
  <tr><td><code>paperpen queue</code></td><td>Every open note. <code>--json</code>, <code>--paper</code>, <code>--tag</code>, <code>--unclassified</code>, <code>--older-than</code>, <code>--limit</code>.</td></tr>
  <tr><td><code>paperpen next</code></td><td>What to do first. <code>--json</code>, <code>--all</code>, <code>--fast</code>.</td></tr>
  <tr><td><code>paperpen classify &lt;paper&gt; &lt;id&gt; &lt;TAG&gt;</code></td><td>SCIENCE, LANGUAGE, QUESTION or TODO.</td></tr>
  <tr><td><code>paperpen resolve &lt;paper&gt; &lt;id&gt; &lt;done|rejected|open&gt; ["what was done"]</code></td><td>Close a note, with what was decided.</td></tr>
</table>

<h2>The agent reading first</h2>
<table>
  <tr><td><code>paperpen agent &lt;paper&gt;</code></td><td>The agent answers the newest round, Claude Code unless <code>--runner codex</code>. <code>--print</code>, <code>--background</code>, <code>--status</code>, <code>--stop</code>.</td></tr>
  <tr><td><code>paperpen review &lt;paper&gt;</code></td><td>The agent reads the paper and writes notes of its own, each with its fix, into <code>review/&lt;date&gt;-claude/</code>, or <code>-codex/</code>. <code>--focus</code>, <code>--max</code>, <code>--runner</code>, <code>--background</code>, <code>--print</code>.</td></tr>
  <tr><td><code>paperpen suggest &lt;paper&gt; --tag T --note "..."</code></td><td>One such note, placed from the text it fixes: <code>--file</code>, <code>--old</code>, <code>--new</code> (or <code>--edits</code> JSON), or <code>--at</code> for a remark with no fix.</td></tr>
  <tr><td><code>paperpen approve &lt;paper&gt; &lt;id&gt; [&lt;fix&gt;]</code></td><td>Put its fix in the working tree and close it done.</td></tr>
  <tr><td><code>paperpen reject &lt;paper&gt; &lt;id&gt;...</code></td><td>Close them as rejected. <code>--why</code>, which the next run reads.</td></tr>
</table>

<h2>Versions</h2>
<table>
  <tr><td><code>paperpen versions &lt;paper&gt;</code></td><td>The log, and which of it is built. <code>-n</code>.</td></tr>
  <tr><td><code>paperpen versions &lt;paper&gt; --build &lt;ref&gt;</code></td><td>The paper as it was at that commit.</td></tr>
  <tr><td><code>paperpen versions &lt;paper&gt; --diff &lt;ref&gt;</code></td><td>latexdiff, compiled.</td></tr>
  <tr><td><code>paperpen versions &lt;paper&gt; --source &lt;ref&gt;</code></td><td>What git diff says about the .tex.</td></tr>
  <tr><td><code>paperpen versions &lt;paper&gt; --forget</code></td><td>Throw the version builds away.</td></tr>
</table>

<h2>The network, and the state</h2>
<table>
  <tr><td><code>paperpen lan</code></td><td>Choose how the reader on the network lets people in: password and app code, password, or no login. <code>--no-login</code>, <code>--clear</code>.</td></tr>
  <tr><td><code>paperpen tls</code></td><td>A self-signed certificate, and how to trust it. <code>--renew</code>.</td></tr>
  <tr><td><code>paperpen qr</code></td><td>The address as a QR code. <code>--url</code>, <code>--light</code>.</td></tr>
  <tr><td><code>paperpen bundle</code></td><td>The state as one .tar.gz. <code>--ink</code>, <code>-o</code>.</td></tr>
  <tr><td><code>paperpen record &lt;paper&gt;</code></td><td>Refresh <code>review/paperpen.json</code> in the paper's repository.</td></tr>
  <tr><td><code>paperpen adopt &lt;repo-or-url&gt;</code></td><td>Put a paper back on the shelf from the record its repository carries.</td></tr>
  <tr><td><code>paperpen sync</code></td><td>Pull the papers' repositories, re-read the rounds.</td></tr>
</table>

<h2>Environment</h2>
<table>
  <tr><td><code>PAPERPEN_HOME</code></td><td>Where the registry lives.</td></tr>
  <tr><td><code>PAPERPEN_CACHE</code></td><td>Builds and rendered pages.</td></tr>
  <tr><td><code>PAPERPEN_DATA</code></td><td>The rounds.</td></tr>
  <tr><td><code>PAPERPEN_LATEXDIFF</code></td><td>The latexdiff command, for a manuscript that needs its own flags.</td></tr>
</table>
"""

BODIES = {"index.html": INDEX, "reading.html": READING, "writing.html": WRITING,
          "network.html": NETWORK, "agents.html": AGENTS, "commands.html": COMMANDS}

BLURBS = {
    "index.html": "Read a paper on a tablet, mark it up with a pen, and get the "
                  "marks back anchored to the source.",
    "reading.html": "Adding a paper, reading it with a pen, and what a round is.",
    "writing.html": "The source with the build beside it, SyncTeX both ways, and "
                    "the paper beside its own past.",
    "network.html": "Serving the reader to a tablet: the login, "
                    "certificate, QR code.",
    "agents.html": "The queue across every paper, and what to do first.",
    "commands.html": "Every paperpen command, in one page.",
}


def pages() -> dict[str, str]:
    made = {"manual.css": CSS}
    for name, title in PAGES:
        made[name] = SHELL.format(title=title, blurb=BLURBS[name], nav=nav(name),
                                  body=BODIES[name].strip(), next=onward(name))
    return made


def main(argv: list[str]) -> int:
    check = "--check" in argv
    made = pages()
    OUT.mkdir(parents=True, exist_ok=True)
    differ = []
    for name, text in made.items():
        here = OUT / name
        if not here.is_file() or here.read_text(encoding="utf-8") != text:
            differ.append(name)
            if not check:
                here.write_text(text, encoding="utf-8")
    if check:
        for name in differ:
            print(f"out of step: manual/{name}")
        print(f"{len(made) - len(differ)} of {len(made)} files in step")
        return 1 if differ else 0
    shots = len(list((OUT / "shots").glob("*.png"))) if (OUT / "shots").is_dir() else 0
    print(f"{len(made)} files in {OUT}, {shots} pictures")
    if not shots:
        print("  no pictures yet: scripts/manual-shots.py takes them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
