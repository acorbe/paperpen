# Writing it back, and the paper as it was

The source with the build beside it, and the paper beside its own past. Back to the [README](../README.md).

## Writing it, with the build beside it

**Edit** in the reader's header, or `edit` on a shelf card, opens the paper's
source on the left and the build on the right.

- **Double click a line** and the place it made lights up on the page.
- **Double click the page** and the line that made it takes the caret, in the
  right file: an `\input` two directories down is where SyncTeX says it is.

Both directions are the same map, the one the reader already uses to hang a
note on a sentence, read forwards and backwards.

The editing window breaks. `C-x 3` puts a second one beside it and `C-x 2`
below, each with its own file or another part of the same one, and the divider
drags. That is what the buttons in the header do as well, for a keymap that
has no chords.

### The keys

Two maps, in the header, and the choice is remembered:

- **standard**: `Ctrl-S` save, `Ctrl-F` find, `F3` again, `Ctrl-Enter` or `F5`
  build, `F8` show this line in the build, `Alt-2`/`Alt-3` split, `Alt-0`
  close, `F6` next window, `F7` next misspelt word, `F1` the list.
- **emacs**: `C-x C-s`, `C-x 2`, `C-x 3`, `C-x 0`, `C-x 1`, `C-x o`,
  `C-c C-c` build, `C-c C-v` show this line, `C-a C-e C-f C-b C-n C-p`,
  `M-f M-b`, `C-k` (a run of them collects), `C-y`, `C-Space` then `C-w` or
  `M-w`, `M-<`, `M->`, `C-v`, `M-v`, `C-s` find, `M-s o` occur, `M-$` spelling, `C-g` quit, `C-/` undo.

Arrow keys, selection with shift, and the browser's own undo work in both.
`?` in the header lists whichever map is on.

**What the browser takes first.** `C-w`, `C-n`, `C-t` and `C-q` are the
browser's own, and a page cannot have them: `C-w` closes the tab. They are
bound anyway for a browser that lets them through, and the region can always
be killed with `C-Space` and `C-k`.

### Spelling

Misspelt words are underlined as you type, a moment after you stop. The check
is aspell, run where paperpen runs, over the text as it is in the window, saved
or not. **spell** in the header turns it off and on, and the choice is
remembered.

- **What is not read.** aspell's TeX mode skips commands and comments. paperpen
  also blanks what it would otherwise read as words: mathematics, inline and
  displayed; the arguments of `\cite`, `\ref`, `\cref`, `\label`,
  `\includegraphics`, `\url` and the like; and options in square brackets. So a
  citation key or `$\rho_{crit}$` is never a misspelling.
- **Fixing one.** Put the caret in an underlined word, or press `F7` (`M-$` in
  emacs) to go to the next one. The bottom bar then offers aspell's
  suggestions, and one tap puts it in. That is an ordinary edit: it is undone
  like one, and saved with the rest.
- **The paper's own words.** *add to the paper's words* writes the word to
  `.paperpen-words` at the root of the paper's repository, one word per line.
  It is a plain file in the tree, so it is committed with the paper and a
  coauthor's editor accepts the same words.
- **The language** is the paper's: `british` or `UKenglish` given to babel
  means en_GB, anything else en_US.

Without aspell the button is greyed out and nothing else changes;
`paperpen onboard --check` says whether it is there.

### Search

Every search here is orderless, as emacs's `orderless` package has it. The
query is split on spaces and a line matches when every piece is in it, in any
order: `density pair` finds "the pair walks abreast at low density". A piece
starting with `!` must not be there, `density !pair`. A piece with a capital
matches as written, one without ignores case. Pieces are plain text, never
regular expressions, so no query is an error.

- **The reader.** The magnifier, `/` or `Ctrl-F` opens a bar over the pages.
  Every matching sentence of the build is banded where it sits, `Enter` and
  `Shift-Enter` step through them, and **list** opens the occur view: one row
  per sentence, with its page, and a tap goes there. `Esc` closes it.
- **The editor.** The find box takes the same queries. **Next** selects the
  next match from the caret; **Occur** lists every matching line of the
  file, and **All files** every matching line of the paper's repository, with
  `file:line`, as `M-s o` does in emacs. The list follows the query while it
  is open, and a row opens the file at that line.
- **The lists.** The shelf, the queue, the feedback page and the commit log
  each have a filter box, and `/` goes to it. It hides what does not match,
  and `Esc` clears it.

The sentences come from the page layouts, which are kept after the first
reading, and the lines from the files themselves. A paper is a few hundred
sentences and a repository a few thousand lines, so nothing is indexed.

### What it writes, and when

Nothing until you ask. There is no autosave: this is somebody's manuscript,
and a background write that lands while a sentence is half rewritten is a
change to a paper that nobody made. **build on save** compiles after a save,
which is the Overleaf rhythm for anyone who wants it.

Saving writes the file in the paper's own working tree, with no copy and no lock, so
`git status`, `git diff` and `paperpen versions` all go on meaning what they
meant. Two guards sit around that:

- **A file that moved underneath is not overwritten.** The repository takes
  merges from elsewhere, and a `git pull` or an Overleaf sync is allowed to
  win. The save is refused and both answers are offered: *keep mine, write it
  anyway*, or *take the file as it is now*, which puts what you had in the
  kill ring, so `C-y` brings it back into the new text.
- **The previous contents are kept first**, in
  `~/.cache/paperpen/<paper>/edits/`, the last 20 saves of each file. A short
  net for the ten minutes before a commit; git is the long one.

It is an editor for writing sentences in a paper, and nothing else: no
completion, no linting, no live collaboration. The merge tool is git, which is
already there.

### Building runs the repository's own code

A build is `latexmk` run in the paper's repository, or in a past commit's
unpacked tree for the versions view below. latexmk reads a `.latexmkrc` or
`latexmkrc` it finds there, and that file is Perl: it can run any command, and
can turn on `-shell-escape` for LaTeX as well. So building a repository you did
not write runs code you did not write, as you. `paperpen add` builds at once,
and so do **Rebuild**, **build on save**, the versions view and an agent's
`paperpen build`.

Only add papers you trust, or read their `.latexmkrc` first. The same goes for
`paperpen adopt <git-url>`: it clones and does not build, but the first build
of the clone runs whatever came with it, and `paperpen sync` can pull a new
one in later. A paper added as a PDF is never built.

## The same paper, as it was

A draft is read against its own history: what did this paragraph say before the
co-author touched it, and what exactly moved. **Versions** in the reader's
header, or `versions` on a shelf card, opens four panes of the one paper:

```
log                old                new                diff
the repository's   built at a past    built as it is     latexdiff between
commits            commit             now                the two, compiled
```

The page number is shared, so the three show the same page of the paper, and
while `locked` is on (it is by default) they scroll together. A version that
has not been compiled says so and offers to; it is built once and kept, so
looking again is immediate. `source` in the diff pane replaces the marked-up
PDF with `git diff` over the `.tex`, which is the view that shows a macro, a
figure path or a comment.

The same builds from a terminal:

```sh
paperpen versions <paper>                   # the log, and which of it is built
paperpen versions <paper> --build 901c97a   # the paper as it was at that commit
paperpen versions <paper> --diff 901c97a    # latexdiff, against the working tree
paperpen versions <paper> --source 901c97a  # what git diff says about the .tex
paperpen versions <paper> --forget          # throw the version builds away
```

**Nothing is written into the paper's repository.** A version is taken with
`git archive`, which only reads, and unpacked into
`~/.cache/paperpen/versions/<paper>/<commit>/`; a `git worktree` would leave
administration in `.git` and take a lock on a checkout you may be in the middle
of using. So this works on a repository that is dirty, mid-rebase, or somebody
else's.

Two things it will not do. It will not run a paper's own `build` command
because a browser asked, so a paper that has one is compared from a terminal,
where somebody typed it. And a build with the working tree on one side is
marked *the paper has been edited since* rather than quietly redrawn: a diff
against yesterday's edit, shown without a word, is worse than no diff at all.
`rebuild` in the pane header takes it again.

latexdiff does the markup, and has to be installed: `apt install latexdiff`.
A manuscript that needs its own flags sets the whole command:

```sh
PAPERPEN_LATEXDIFF="latexdiff --flatten --math-markup=whole" paperpen serve
```
