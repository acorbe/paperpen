# Where everything lives

The registry, the cache and the rounds, what the paper's own repository carries, and taking all of it somewhere else. Back to the [README](../README.md).

## Where everything lives

Four places, with four different lifetimes, and it is worth knowing which is
which before deleting any of them.

- **The code** is this checkout. `upstream/` inside it is the dashboard's own
  files, verbatim, and is not edited here; see "Where the code comes from"
  below. Nothing about a paper is kept in the checkout.
- **The registry**, `~/.config/paperpen/papers.json`. Which papers are on the
  shelf, and for each one its repo, its main file, and the kind, brief and
  delivery paperpen adds. It is configuration: small, hand-editable, and the
  one thing here worth backing up.
- **The cache**, `~/.cache/paperpen/<paper>/`. The built PDF, its SyncTeX, the
  rendered pages, `build.json`. Derived from the paper and the registry, so
  `paperpen build` makes it again. `versions/<paper>/<commit>/` beside it holds
  the same for a past commit, and the tree it was built from. It is not small: a 22-page paper with every
  page rendered comes to 9.5 MB and a 28-page one to 20 MB, so this is the
  directory to delete when the disk is full.
- **The rounds**, `~/.local/share/paperpen/<paper>/rounds/<date>/`. Per round:
  `notes.json`, `NOTES.md`, `ink/*.png`, and `sent.json` saying where it went.
  What was read, what was said, and to whom. This cannot be made again, and it
  is kept whatever the delivery was, which is the whole reason it exists: a
  draft handed over as a PDF leaves no trace anywhere else, and a repository
  can be on a machine that is not this one.

The paper's own repository is the fifth place, and it is output rather than
state. A round delivered as `repo` commits `review/<date>/` into the paper's
own checkout, and that copy is authoritative: a pass running `paperpen resolve`
there closes notes where the person editing the paper can see them, and the
local record mirrors it rather than keeping a second opinion. A round delivered
as `pdf` writes `<main>-notes-<date>.pdf` beside the paper, or into the round's
own directory when the paper has no directory to be beside, and commits
nothing. Building never writes into the paper's repository at all; latexmk is
given `-outdir` into the cache, so the checkout stays clean.

Each of the three directories takes an override. A `.paperpen/papers.json` in
the working directory wins over `PAPERPEN_HOME` as the registry, so a folder of
drafts can carry its own shelf and be moved whole; the cache and the rounds are
not redirected with it.

## The paper carries its own history

The local record answers "what have I read". It is also the copy that dies with
the machine, so a paper optionally keeps its own history in its own repository,
where anyone holding the paper can read it and any clone can rebuild the shelf
from it:

```
<paper repo>/review/
  paperpen.json           which paper this is, how it is read, which rounds exist
  2026-09-17/notes.json, NOTES.md, ink/*.png
```

`review/<date>/` has been written there since the dashboard. The manifest is
what was missing: those files record the paper's *name*, and a name is not an
identity: it is rewritten when a title is fixed, and the id is deliberately
not allowed to move with it. So `paperpen.json` carries the id, the kind, the
brief, the delivery and an index of the rounds, and `adopt` reads it back.

```sh
paperpen about <paper> --record repo   # let the paper carry it; `local` keeps it here
paperpen record <paper>                # write the manifest now, for a paper read
                                       # before there was one
paperpen adopt <dir>                   # put it back on the shelf from that record
paperpen adopt <git-url> --into <dir>  # clone it first
paperpen sync [<paper>]                # pull the papers' repos, read what came back
```

`record` is `repo` for a paper delivered as a commit, which is already writing
there, and `local` otherwise: a draft you hand back as a PDF does not get a
`review/` directory in somebody else's tree unless you say so.

There is no central store to reconcile and no service to run. Each paper's
history is in that paper's repository, so syncing is pulling the repositories,
and the repository's copy wins wherever both exist. It is the same rule the shelf
already reads by, because a note closed in the paper's own checkout is closed
where the person editing the paper can see it.

Open question: a paper with no repository at all, a referee PDF that arrived by
mail, has nowhere to put its history but here. Its rounds are in the bundle
below and nowhere else.

## Taking the state

```sh
paperpen bundle                  # -> paperpen-<date>.tar.gz, registry and all rounds
paperpen bundle <paper>          # one paper, with its manifest, no registry
paperpen bundle --ink            # include the rendered ink
```

The same two from the browser, because the tablet is where the reading happens
and it has not got a terminal: **take the state** in the shelf header is
`/state.tar.gz`, and each paper has `/paper/<id>/state.tar.gz`. Add `?ink=1`
for the ink.

The rendered ink is left out by default. It is `ink/<id>.png` per handwritten
note, drawn from the strokes that are already in `notes.json`, and on a real
round of 102 handwritten notes it was 7.2 MB against 916 KB for everything
else. What you get without it is the whole reading: the notes, what they are
anchored to, the transcriptions, and the strokes themselves.


```sh
PAPERPEN_HOME=...    # the registry
PAPERPEN_CACHE=...   # the builds
PAPERPEN_DATA=...    # the rounds
paperpen where       # which of them are actually in use
```

One thing is in the wrong place. The open round, the notes written but not yet
delivered, is `session.json` in the *cache*, because that is where the
dashboard keeps it and upstream's `Paper.session` is what both read. So the
directory described above as the one safe to delete holds the one piece of
state that has never been written down anywhere else. `paperpen build` is
careful with it, but `rm -rf ~/.cache/paperpen` is not. Open question: whether
the open round moves next to the delivered ones, which is where it belongs, or
whether upstream keeping it in the cache is a constraint worth living with.
