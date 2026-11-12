# paperpen: the design

Read a paper on a tablet, mark it up with a pen, and get the marks back as
something you can act on: a note set anchored to file and line, or a marked-up
PDF to send to whoever wrote the paper. Two things write the notes: your hand,
and an agent (Claude Code or Codex) that reads the paper and writes its own.

This file says what the app is for, why it is built the way it is, and what is
not built yet. The commands and screens are in the [README](README.md), the
[docs](docs/) and the [manual](https://acorbe.github.io/paperpen/).

The reader comes from a personal dashboard of the author's, where it is in
daily use. It is taken as it is, not rewritten, for the reason in "Staying in
step with upstream" below.

## Several papers at once

The dashboard never had to solve this. There, a paper sat among cards that
already knew about deadlines and tasks. On its own the app has to answer:
which papers am I reading, what is open on each, what have I sent, and what
came back.

### A paper carries more than a path

The registry is `papers.json`: per paper a name, a repository, a main file.
paperpen adds three fields, and each earns its place by changing what the app
does:

- **`kind`**: `mine`, `coauthor`, `student` or `referee`. It decides the
  defaults, which is the only reason to have it. Your own manuscript and a
  co-author's commit their notes into the paper's repository. A student's
  draft and a referee job get a marked-up PDF, because what you hand a student
  is a file, not a commit.
- **`brief`**: two or three lines saying what kind of read this is. *"Referee
  for PRE. The claims in Sec. 3 and the statistics in Fig. 4 are what matters.
  Language only where it obscures the physics."* It is shown on the shelf,
  given to the agent as the purpose of the read when it reviews the paper, and
  kept in the record the paper carries.
- **`delivery`**: where the notes go when a round is finished. `repo` commits
  `review/<date>/` into the paper's own repository; `pdf` writes the paper
  with every note in the margin; `folder` writes the files and stops.
  Defaulted from `kind`, set per paper with `paperpen about`, and changeable
  for one round with `paperpen finish --as`.

A few more settings ride along per paper, all through `paperpen about`: where
the paper's record is kept (`record`), whether an agent answers its rounds and
how (`agent`), which agent (`runner`), whether its work goes on a branch of its
own (`agent_branch`), and whether the paper is archived. A registry with none
of these fields behaves exactly as it did upstream.

### Rounds, which is what a reading actually is

A **round** is one reading: it opens when you make the first note, it is
*sent* when you finish it, and it is *answered* when every note in it has been
resolved or rejected. That gives each paper a state a person can act on,
instead of a count of open notes.

Every round is recorded under the app's own data directory, whatever its
delivery was:

```
~/.local/share/paperpen/<paper>/rounds/<date>/
  notes.json   the record
  NOTES.md     generated from it
  ink/*.png    each handwritten note, the page region with the ink on it
  sent.json    where it went: the commit, the PDF, or the folder
```

The round being written now stays in the cache, where upstream keeps it.

The local copy matters. A round that goes into somebody else's repository
would otherwise be knowable only by looking in that repository, and a paper
handed over as a PDF would leave no trace at all. Keeping the record here is
what lets the shelf tell the truth about a paper whose repository is on
another machine, or has moved, or never existed.

Where there *is* a repository, its copy stays authoritative. A pass working in
the paper's checkout runs `paperpen resolve` there, and this side re-reads
`review/*/notes.json` rather than keeping a second opinion. Two writers on one
file is how the counts start disagreeing.

Keeping a second history has one consequence worth writing down. A note's id
is handed out from the history, so with the history split the two halves have
to be shown to whatever hands ids out, or the second round of a day reissues
the first round's ids and overwrites it. Upstream is given the merged view for
exactly that reason, in one place (`bind.py`), and the repository-only view is
kept under a name of its own for the code that builds the merge.

The paper can also carry its own history: `review/paperpen.json` in its
repository records its id, kind, brief, delivery and an index of its rounds,
and `paperpen adopt` puts a paper back on a shelf from that, on any machine
with a clone. [docs/data.md](docs/data.md) has the details.

### The shelf

The home page, and the thing a person opens the app to see. One card per
paper, grouped by what it wants from you:

- **Reading**: a round is open.
- **Sent, waiting**: a round went out and some of its notes are still open.
  This is the group that stops a draft going quiet for three weeks.
- **Idle**: nothing open, nothing outstanding.

Archived papers are folded away on a page of their own. The shelf has to stop
growing or it becomes the thing you avoid.

Each card carries **the paper's first page as a thumbnail**. A shelf of six is
recognised by its first pages long before it is read by its titles. The page
is rendered at half scale by the same code that renders every other page, and
kept like every other page; a paper that has not been built keeps the same
footprint with the frame empty, so building one does not reflow the shelf.

Beside it the card says what the paper is (kind, delivery, brief), how its
rounds stand, and whether fixes are waiting to be chosen. From the card you
open the reader, the fixes, the editor or the versions view, or take the
paper off the shelf.

The card deliberately does not say whether the sources have moved past the
PDF. That walks the paper's repository for timestamps, and doing it for every
paper is what would make opening the shelf slow. The reader says it, for the
paper you opened.

### The queue

The cross-paper view: every open note from every paper, one row each, with
the paper, the page, the class, the first line of what the note says and how
old it is. It filters by paper, by class, by age, and to the unclassified
ones, which is the filter that is actually a chore: `AUTO` is the default
class and classifying is the tax you pay later.

A note you wrote and a note an agent wrote are rows of the same shape, and
both are classified and closed the same way.

## Above the repositories

The cross-paper layer is a tool, not an agent: the registry knows every paper,
the queue knows every open note, and `agenda.py` (`paperpen next`) says which
of them matters first. That is deliberate. Something standing above four
manuscripts needs to read all four and write to none of them. The editing is
repository work, with one build, one git history and one set of co-authors,
and it wants an agent that was given that repository and nothing else.

So the split is not a process count, it is a scope. Above: the queue, the
triage, the ordering, and the commands that close a note, which go through the
registry and work from any directory. Inside: the LaTeX.

`paperpen next` answers with one of four kinds and a weight rather than a
score, because a score is unreadable the moment it disagrees with you. The
order is an opinion worth stating plainly: triage first, because a class
decides who acts on a note; then the round that has waited longest; then a
build older than its source; and last a reading that is open and unsent,
which is reported, never urged.

### Closing a note is a merged write

Upstream closes a note by walking `review/` in the paper's repository, because
every paper the dashboard read had one. Here a round can be delivered as a
marked-up PDF and leave no repository copy at all, so without care the note
would sit in the queue and nothing could close it. The repository copy goes
through upstream, so the `NOTES.md` a co-author reads is regenerated by the
code that wrote it; the local record is written here with the same generator;
and upstream refusing is only an error when the local record has not got the
note either (`queue._in_both`).

## Answering a round

A round delivered into a repository is answered there, in the paper's own
checkout, by an agent or by a person. What comes back is not always a finished
change. More often it is a proposal, or two, and a question. So the answer has
a shape of its own, `review/<date>/feedback.json` beside the round: per note,
**fixes** (each one or more exact edits, an old piece of text and what
replaces it) and a **thread**.

A fix is shown in the note it answers, with its diff. One tap on **Use this**
puts it into the working tree and opens the next note that has one; **Undo**
takes it back out. Nothing is committed until you commit it, from the reader's
header or with `paperpen commit`, optionally on a branch of its own that is
then taken or dropped. The exact-text form is deliberate: an edit that no
longer finds its `old` text is refused rather than guessed at, so a fix made
against yesterday's source cannot land in the wrong place.

### The agent

paperpen can start the agent itself. It runs headless in the paper's checkout,
with a prompt that says what the round is and how to answer it through
paperpen's own commands (`feedback`, `notes`, `propose`, `reply`). Two runners
can do it, chosen with `--runner`, per paper, or for every paper with
`PAPERPEN_RUNNER`:

- **Claude Code** (`claude -p`), the default, started with `--allowedTools`
  and a short list: reading files, and those paperpen commands, with
  `paperpen build` added when it implements. It has no other way to edit a
  file and no git.
- **Codex** (`codex exec`), which takes no such list. It is fenced by
  `--sandbox workspace-write` instead: it may write the paper's checkout and
  paperpen's data and cache, and nothing else.

Each signs what it writes with its own name. How much it does is a per-paper
setting: `implement` (what leaves no choice is applied at once, the rest is
proposed or asked about; the default for your own papers), `propose`
(everything is proposed; the default for a co-author's), or `off`. Finish
starts it in the background once per round; `paperpen agent` runs it in front
of you, and `--print` gives the line to run it anywhere. The command is never
hidden.

The fences are what limit it, not the prompt: a manuscript is text the agent
reads, and text can try to steer it. [docs/agents.md](docs/agents.md) says
exactly what each runner may do and what that does not cover.

### The agent reading first

The reverse job: `paperpen review`, or **Review** in the reader, has the agent
read the paper on its own and write notes, each anchored to its sentence and
carrying the fix it would make. They land in a round of their own,
`review/<date>-claude/` or `review/<date>-codex/`, drawn in the agent's colour,
and you approve or reject each one. A note is placed from its fix: the line
its `old` text starts on goes through SyncTeX to the page, and the sentence
there that carries those words is what it is anchored to. A run is capped (25
notes unless told otherwise), a rejection's reason is kept and handed to the
next run, and nothing is committed.

## Writing, and the two directions of SyncTeX

The reading and the writing are the same afternoon. A note anchored to a line
is worth having because the line is about to change, and going to another
window to change it is where a morning goes. So the source is editable here,
with the build beside it.

The editor is a `<textarea>` with a highlighted copy of the same text under
it, one block per line, and the caret is the browser's. Nothing is vendored
for it. A real editor component is a quarter of a megabyte of somebody else's
JavaScript, and what it would buy (completion, folding, a language server) is
not what is wanted. What is wanted is that typing a sentence into a paper
feels like typing, that the keys are the ones in the fingers, and that the
line numbers line up with the ones SyncTeX talks about. One block per source
line is also what keeps the gutter right when the lines wrap, which a gutter
drawn beside a textarea never is.

Every change goes in through `execCommand`, so the browser's own undo still
holds. Assigning `.value` would be two lines shorter and would throw away the
undo history of whoever is typing.

Three decisions:

- **The keymaps are data, and there are two of them.** `standard` and `emacs`,
  as a table from a chord to a command name; a chord is a sequence, so `C-x 3`
  is two strokes and the echo area says so while it waits. Emacs keys on a
  page lose to the browser in four places (`C-w`, `C-n`, `C-t`, `C-q`), and
  the help says which rather than pretending.
- **The writing is to the working tree, and only when asked.** No copy, no
  lock, no autosave: git stays the thing that knows what changed, and a paper
  is never written to while a sentence is half rewritten.
- **A file that moved underneath is a question, not a merge.** The stamp is
  nanoseconds and a length rather than a float mtime, because a float has to
  be compared with a tolerance and the tolerance is exactly the window in
  which two writes are confused. When the stamp does not match, both answers
  are offered and neither is taken by default.

## Reading against the history

The reader shows one build of one tree, and which tree that is depends on what
happens to be checked out. A paper under review is read against its past as
much as against itself (a co-author's Overleaf merge arrives as one commit,
and the question is what it did), so there is a second view of the same paper
with builds of a commit, the working tree, and latexdiff between them, beside
the log they were picked from.

The builds are upstream's. A version is the same `Paper` with its repository
pointed at an extracted tree and its cache pointed at a directory of its own,
built by the same `cmd_build`; otherwise the old PDF and the PDF being read
would be made by two different recipes, and what they differ in would partly
be the recipe.

Three decisions are worth keeping:

- **`git archive`, not `git worktree`.** A worktree writes into `.git`, takes
  a lock, and leaves administration behind that somebody has to prune. A paper
  being compared should be a paper nothing is happening to, including one
  that is dirty or mid-rebase.
- **A version with the working tree on one side goes stale.** A commit cannot
  change and neither can a diff between two of them; once built they are right
  forever. The working tree is the side that moves, so those builds are
  checked against the source's clock and say when they have been overtaken.
  They are not rebuilt silently: a build is a minute of latexmk, and redrawing
  under a reader who is mid-comparison is its own kind of wrong.
- **The server does not run a paper's own build command.** A `build` line in
  `papers.json` runs when somebody types `paperpen build`, never because a
  browser asked. A plain latexmk build does run from the browser, and it reads
  the repository's `.latexmkrc`; [docs/writing.md](docs/writing.md) says what
  that means for a repository you did not write.

## Handwriting

A handwritten note is kept as ink: the strokes on the page in page points,
the strokes in the pad in the pad's own pixels with the pad's size, and, when
the round is delivered, `ink/<id>.png`, the page region with the ink drawn on
it. Whoever answers the round reads the picture. The agent is told to, and
asks in the note's thread when it cannot read it.

That is fine when an agent is going to run anyway, and not when one is not:
a student's draft marked up by hand goes out as a PDF whose margin says
*(handwritten, not transcribed)* wherever the note was only ink.

### Not built yet: recognition

The app should transcribe the strokes itself. The plan:

- The pen already gives full stroke data, which recognises far better than a
  picture of strokes, and is what recognisers want.
- One interface, tried in order: **the browser**, where it offers
  `navigator.createHandwritingRecognizer` (on-device, nothing to install, and
  the transcription is back before the note is saved, so the pad shows it and
  you fix it on the spot); **a local stroke recogniser on the server**, as an
  optional dependency, when the browser has nothing; and **none**, which is
  today's behaviour.
- A note would gain the text, a confidence and the engine that produced it.
  The one piece in place is the reading side: what a note says already
  prefers a `hand_text` field when there is one, but nothing writes it yet.
  `NOTES.md` would print the transcription, mark it uncertain below a
  threshold, and still ship `ink/<id>.png` beside it. The image is the
  evidence; the transcription is a guess.
- A command would run the recogniser over a round again, for notes made
  before an engine was there.

Open question: whether the browser recogniser exists on the tablets that
matter. It shipped on ChromeOS; Android and iPadOS have not been measured.
Everything about this feature is cheaper if it does.

## Staying in step with upstream

The dashboard is where the reader is exercised daily, and it keeps changing.
Picking those changes up here has to be one command with a diff you can read,
which rules out reorganising the code into what it would have looked like if
it had been written here. So:

- `upstream/` holds the dashboard's files **verbatim**: `paper.py`,
  `annotate_paper.py`, `PAPERS.md`, and `reader.html`, which is the reader's
  page lifted out of the dashboard mechanically. `routes_dashboard.py`, the
  dashboard's own paper routes, is kept for reference only and never
  imported, so a change to them shows up in a sync diff.
- `upstream/UPSTREAM.json` records the commit each file came from and the
  patches applied, so "which version is this" is never a guess.
- **Nothing paperpen-specific is written into those files by hand.** The
  product lives in modules beside them that import from them, and
  `paperpen/bind.py` points upstream at paperpen's directories at import.
  Where upstream genuinely has to change, the change is a patch in
  `upstream/patches/`, replayed by the sync, so it survives the next one and
  is visible as a list rather than buried.
- `scripts/sync.py` re-extracts and replays the patches; `--check` says
  whether `upstream/` is still in step and changes nothing.

A patch has to fail loudly or it is worse than no mechanism at all. Two ways
it can fail quietly, and both are closed: `git apply` run inside a repository
resolves a patch's paths against the repository root and ignores whatever
falls outside the current directory *while exiting 0*, so patches are applied
from the parent with `--directory`; and a patch that applies but changes
nothing is an error rather than a line in the report.

This is the opposite of the usual advice and it is deliberate: the code has
one author and two homes, and the cost of a merge conflict in 1700 lines of
handwritten pen handling is much higher than the cost of a layout nobody would
have chosen from scratch. If the dashboard later depends on this package
instead, the patches are the list of what has to be agreed first.

## Layout

```
DESIGN.md  README.md  pyproject.toml  LICENSE
upstream/                 verbatim, synced, never edited by hand
  paper.py  annotate_paper.py  reader.html  routes_dashboard.py  PAPERS.md
  UPSTREAM.json  patches/
paperpen/
  bind.py                 loads upstream and points it at paperpen's directories
  config.py               where the registry, the rounds and the cache live
  registry.py             papers, kind, brief, delivery
  rounds.py               open / sent / answered, the local record
  deliver.py              finishing a round: a commit, a PDF or a folder
  archive.py              the record a paper carries, adopt, and the bundle
  shelf.py                the home page
  queue.py                every open note, from every paper
  agenda.py               what to do first, across every paper
  feedback.py             fixes proposed for notes, and their threads
  review.py               committing what the fixes changed, on a branch or not
  agent.py                the agent that answers a round, Claude Code or Codex
  proposals.py            the agent reading first: its notes, approved or rejected
  edit.py                 the source, and SyncTeX in both directions
  spell.py                spelling for the editor, through aspell
  search.py  orderless.py search, orderless, over the paper and its source
  versions.py             a past commit, and latexdiff between two
  auth.py                 the password, and TOTP when it is wanted
  tls.py                  the self-signed certificate
  qr.py                   the address, for a camera
  serving.py              where the browser view is, for the other commands
  onboard.py              what a new machine needs, and whether it has it
  cli.py                  the commands
  web/                    the app: shelf, queue, fixes, editor, versions,
                          the login, and the reader from upstream
tests/
docs/                     the docs the README links to
manual/                   the manual, committed as HTML
demo/                     the films, and the invented shelf they are filmed on
scripts/                  sync.py, manual.py, manual-shots.py, demo-gif.py
```

## Not built yet, and open questions

- **Handwriting recognition**, as above. Until it exists, a handwritten note
  is read from its picture, by you or by the agent.
- Whether a round should be closed by hand once every note in it is answered,
  or whether "answered" as a computed state is enough.
- Whether `implement` should ever be the default for a paper that is not your
  own. Today it is not: a co-author's paper gets `propose`, a student's draft
  and a referee job get no agent at all.
