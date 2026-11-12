# Posting a paper here, and acting on the notes that come back

This is written for whoever works in a **paper's own repository**: the owner
reads his papers on a tablet through the board in this repo, marks them up with
a pen, and his notes land in that paper's repository as a commit. This file is
the whole contract, and it is the only place it is written down. Nothing here
edits a paper's repository except the notes themselves.

Everything below is run from this repo, which lives at
`$PAPERPEN_BOARD` (the main checkout, not a worktree).

```sh
scripts/paper.py howto     # print this file
```

## 1. Compiling, so the paper can be read

**The build must produce a SyncTeX map**, `<main>.synctex.gz`, beside the PDF.
That map is what turns a note put on a sentence into `sec_intro.tex:53`, which
is most of the value of a note. `latexmk` writes it:

```sh
latexmk -pdf -synctex=1 -interaction=nonstopmode <main>.tex
```

A paper that will not compile with SyncTeX can still be posted and read, but
its notes will carry a page and a quoted sentence and no source line.

Nothing needs changing in the paper's own Makefile: the board compiles into a
cache of its own and never writes into the paper's working tree.

## 2. Posting it

```sh
scripts/paper.py check <repo>   # is it ready?
scripts/paper.py add   <repo>   # register it
```

`add` finds the `.tex` holding `\documentclass`, takes the paper's name from
its `\title`, compiles it once to check, and registers it in `papers.json`
here. A paper that does not compile is not registered. `--main`, `--name` and
`--task` override what it worked out; `--task` ties the paper to a card on the
board.

It then appears in the board's **Papers** menu, and at `/paper/<id>`.

The id is written into `papers.json` at registration and stays put. It is in
URLs, in cache paths and in notes already sent, so it must not move because
somebody improved the paper's name; rename freely, the id does not follow.

## 3. The notes that come back

A reading session lands in the paper's repository, committed there, as
`review/<date>/`:

- **`NOTES.md`** is what to act on. Each note gives the file and line it is
  anchored to, what it is about, and what to change. The owner selects the
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
  was made on top, with any marks drawn on the page itself, and what the owner
  wrote in the pad underneath at the size he wrote it. Read the image, write
  what it says into the note, then act on it. There is no OCR anywhere in
  this; reading it is the job of whoever picks the note up.
- **A note marked `unclassified`** is one the owner left on Auto, which is the
  default. Decide from what it says whether it is SCIENCE, LANGUAGE, QUESTION
  or TODO, and record it:

  ```sh
  scripts/paper.py classify <paper> <id> SCIENCE
  ```

Working through a round, in the paper's repository:

1. Read `review/<date>/NOTES.md`, newest date first.
2. Make each change in the LaTeX.
3. Classify anything still `unclassified`, and close each note, so the next
   reading shows what happened to it:

   ```sh
   scripts/paper.py resolve <paper> <id> done "what was changed"
   scripts/paper.py resolve <paper> <id> rejected "why not"
   ```

   That writes into `notes.json` and regenerates `NOTES.md`.
4. Rebuild, so the next reading is of the new version:

   ```sh
   scripts/paper.py build <paper>
   ```

   The reader says when the source has moved past the PDF on show, and its
   Rebuild button does the same thing from the tablet.

`scripts/paper.py notes <paper>` lists every note and whether it is still open.

## What this never does

It does not edit a paper repository's `CLAUDE.md`, `README.md`, `Makefile` or
sources. The only thing it ever writes there is `review/<date>/`, which is the
owner's notes, which is the point. Everything else, including these
instructions, stays in this repo.
