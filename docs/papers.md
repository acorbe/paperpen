# Putting a paper on the shelf, and acting on the notes that come back

This is written for whoever works in a **paper's own repository**. Its reader
reads the paper on a tablet with paperpen, marks it up with a pen, and the
notes land in that paper's repository as a commit. This file is the whole
contract. Nothing here edits a paper's repository except the notes themselves.

```sh
paperpen howto     # print this file
```

## 1. Compiling, so the paper can be read

**The build must produce a SyncTeX map**, `<main>.synctex.gz`, beside the PDF.
That map is what turns a note put on a sentence into `sec_intro.tex:53`, which
is most of the value of a note. `latexmk` writes it:

```sh
latexmk -pdf -synctex=1 -interaction=nonstopmode <main>.tex
```

A paper that will not compile with SyncTeX can still be put on the shelf and
read, but its notes will carry a page and a quoted sentence and no source line.

Nothing needs changing in the paper's own Makefile: paperpen compiles into a
cache of its own and never writes into the paper's working tree.

## 2. Putting it on the shelf

```sh
paperpen check <repo>   # is it ready?
paperpen add   <repo>   # put it on the shelf
```

`add` finds the `.tex` holding `\documentclass`, takes the paper's name from
its `\title`, compiles it once to check, and registers it in paperpen's
`papers.json`. A paper that does not compile is not registered. `--main` and
`--name` override what it worked out.

It then appears on the shelf, and at `/paper/<id>`.

The id is written into `papers.json` at registration and stays put. It is in
URLs, in cache paths and in notes already sent, so it must not move because
somebody improved the paper's name; rename freely, the id does not follow.

## 3. The notes that come back

A reading lands in the paper's repository, committed there, as
`review/<date>/`:

- **`NOTES.md`** is what to act on. Each note gives the file and line it is
  anchored to, what it is about, and what to change. The reader selects the
  thing on the tablet, so a note is never vague about its target:

  - **a sentence**: the sentence is quoted.
  - **a word**: the word is named, and quoted in bold inside its own sentence,
    so it is clear which occurrence is meant.
  - **a figure or table**: it is named (`Figure 3`), its caption is quoted, and
    the source line is the caption's, which sits next to its `\label`.

  **The line number is from the build the note was made on and drifts as the
  source is edited; the quoted sentence is what to search for.**
- **`notes.json`** is the record. `NOTES.md` is generated from it, so never
  hand-edit `NOTES.md`.
- **`ink/<id>.png`** accompanies a handwritten note: the page where the note
  was made on top, with any marks drawn on the page itself, and what was
  written in the pad underneath, at the size it was written. Read the image,
  write what it says into the note, then act on it. There is no OCR anywhere
  in this; reading it is the job of whoever picks the note up.
- **A note marked `unclassified`** is one left on Auto, which is the default.
  Decide from what it says whether it is SCIENCE, LANGUAGE, QUESTION or TODO,
  and record it:

  ```sh
  paperpen classify <paper> <id> SCIENCE
  ```

Working through a round, in the paper's repository:

1. Read `review/<date>/NOTES.md`, newest date first.
2. Make each change in the LaTeX.
3. Classify anything still `unclassified`, and close each note, so the next
   reading shows what happened to it:

   ```sh
   paperpen resolve <paper> <id> done "what was changed"
   paperpen resolve <paper> <id> rejected "why not"
   ```

   That writes into `notes.json` and regenerates `NOTES.md`.
4. Rebuild, so the next reading is of the new version:

   ```sh
   paperpen build <paper>
   ```

   The reader says when the source has moved past the PDF on show, and its
   Rebuild button does the same thing from the tablet.

`paperpen notes <paper>` lists every note and whether it is still open.

This is also the work an LLM session is handed after Finish and send: see
[agents.md](agents.md).

## 4. Answering with proposals instead

A round can also be answered without changing the paper: fixes are proposed,
and the author chooses among them in the browser. The proposals go beside the
round, in `review/<date>/feedback.json`:

```json
{
  "format": "paperpen-feedback/1",
  "notes": {
    "<note id>": {
      "fixes": [
        {"id": "1", "by": "claude", "at": "2026-09-24T10:12:00",
         "summary": "say which density, where it is first used",
         "why": "the note asks what density means; the text never says",
         "edits": [{"file": "main.tex",
                    "old": "depends on the density of the crowd",
                    "new": "depends on the local density of the crowd"}],
         "state": "proposed"}
      ],
      "thread": [{"by": "claude", "at": "...", "text": "a question"}]
    }
  }
}
```

- A fix is one or more **edits**, each an exact piece of text in a file of the
  repository and what replaces it. Exact text, not a line number: it either is
  still there or says plainly that it is not. It has to occur once in the file.
- Two fixes for one note are alternatives. Propose both when the choice is the
  author's, and say in `why` what each one answers.
- The **thread** is where a question goes, and where the author's reply comes
  back. Read it before answering again.
- `state` is written by paperpen: `proposed`, then `applied`, `failed` or
  `rejected`.
- `by` is free text, whoever proposed it. `claude` and `codex` are the agent,
  Claude Code or Codex, and the reader draws those in the agent's colour.

A round can also be written by the agent rather than by you: `paperpen review`
reads the paper and writes notes of its own, each with its fix, into a round
of its own, `review/<date>-claude/`, or `review/<date>-codex/` when Codex
wrote it. Its `notes.json` is a round like any other, except that each note
carries `"by"`, `"claude"` or `"codex"`, and `"about"`, the exact source text
it was placed from; its fixes are in that round's `feedback.json`,
in the format above. Approving one is `apply`; rejecting closes the note as
`rejected` and keeps the reason in its thread. [agents.md](agents.md#the-agent-reading-first)
has the rest.

The commands write the file for you and check each edit against the source
before keeping it:

```sh
paperpen propose <paper> <id> --summary "..." --file F --old "..." --new "..." [--why "..."]
paperpen propose <paper> <id> --summary "..." --edits '[{"file": ..., "old": ..., "new": ...}]'
paperpen reply   <paper> <id> "..." [--by claude]
paperpen feedback <paper>             # what is proposed, and the threads
paperpen apply   <paper> <id> <fix>... # what the page's Apply does
```

## What this never does

It does not edit a paper repository's `CLAUDE.md`, `README.md` or `Makefile`.
It writes `review/<date>/`, which is the reader's notes, which is the point;
and the sources only when the author applies a fix they chose, and then the
text that fix names and nothing else. It never commits a fix: what was applied
is in the working tree, to be read before it becomes history.
