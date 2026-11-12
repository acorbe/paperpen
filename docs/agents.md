# After a round, and an agent above the papers

What happens after Finish and send, and the commands to hand something that works through the notes. Back to the [README](../README.md).

## After Finish and send

**Finish and send**, or `paperpen finish`, closes the round and commits
`review/<date>/` into the paper's repository. Answering the notes happens in
the paper's checkout, by an agent. paperpen starts one there itself, headless,
the moment the round is delivered ("The agent, started by Finish", below), and
that is the usual way. The other way is a session you start by hand, pointed at
the round: any LLM that can run a shell command will do, and Claude Opus is
what we have used. Each note carries
the file and line of LaTeX it is about, its class, and the sentence it sits on,
and a handwritten note is a picture, `ink/<id>.png`, which the model reads
directly. A session therefore needs the round and little else:

```text
Work through review/<date>/NOTES.md in this repository. For each note, change
the LaTeX it points at, or say why not; for a handwritten note, read its
ink/<id>.png. Rebuild the paper, close each note with
  paperpen resolve <paper> <note-id> done|rejected "what was done"
and commit.
```

Whether a round's corrections go in, and when, is a decision about the paper:
nothing is committed until you say so, in the reader or with `paperpen commit`.
The commit that comes back is what the
next reading is read against, and `paperpen versions <paper>` shows it beside
the draft the notes were written on.

This applies to a paper delivered into a repository. A draft sent back as a
PDF is corrected by whoever wrote it.

## Proposing instead of changing

The session need not change the paper at all. It can propose, and leave the
choice to you: for each note one fix or several, each an exact piece of the
LaTeX and what should replace it, and a question in the note's thread where it
could not decide. The proposals appear at `/paper/<id>/feedback`, a card per
note with a diff for each fix; you tick the ones you want and apply them, or
answer with a further note. The shelf says when a paper has fixes waiting.

```text
Work through review/<date>/NOTES.md in this repository, and change nothing.
For each note propose one fix, or two when there is a real choice, with
  paperpen propose <paper> <note-id> --summary "..." --why "..." \
      --file main.tex --old "the exact text there now" --new "what replaces it"
and where you cannot decide, ask with
  paperpen reply <paper> <note-id> "the question" --by claude
For a handwritten note, read its ink/<id>.png. Read the thread of each note
first: a reply there is an instruction from the author.
```

Applying writes the working tree through the same safe write the editor uses:
each `old` has to be found exactly once, a fix of several edits goes in whole
or not at all, and a fix whose text has moved since it was proposed is reported
and writes nothing. The note is closed with what was applied. Nothing is
committed; the versions view shows what the working tree now says against the
last commit. A reply keeps the note open, and the next session reads it in the
thread.

What is proposed is kept beside the round it answers, in
`review/<date>/feedback.json`, and `paperpen feedback <paper>` lists it in the
terminal. [papers.md](papers.md) has the format, for a person writing it by
hand.

## The agent, started by Finish

A paper can have its round answered without anybody starting a session: when
Finish delivers a round into the paper's repository, paperpen starts the agent
in the paper's checkout, headless, and the notes fill in while you read the
next paper. The agent is Claude Code by default, and OpenAI Codex with
`--runner codex`.

```sh
paperpen about <paper> --agent implement   # or propose, or off; default goes back
paperpen about <paper> --runner codex      # or claude; default goes back
paperpen about <paper> --branch            # a finished round goes on a branch of its own
paperpen agent <paper>                     # run it now, here, and watch it
paperpen agent <paper> --runner codex      # Codex for this run only
paperpen agent <paper> --print             # the agent's command, to run it yourself
paperpen agent <paper> --status            # how the last run went, who ran it, and its log
paperpen agent <paper> --stop
```

Which runner is in force is decided in that order: `--runner` for one run, the
paper's own setting, `PAPERPEN_RUNNER` for every paper, and Claude Code when
nothing says otherwise. Each signs what it writes with its own name, `--by
claude` or `--by codex`, and the reader, the Fixes page and the queue treat
both as the agent.

- **implement**, the default for a paper of your own: a correction that leaves
  no choice, the way most handwritten ones are, is applied at once with
  `paperpen propose --apply`; a real choice or a scientific point is proposed,
  and what it cannot read or does not know it asks about in the note's thread.
- **propose**, the default for a co-authored paper: everything is proposed, and
  chosen in the notes.
- **off**, for a student's draft or a referee job, which you do not answer.

Claude Code is started with `--allowedTools` and a short list: `Read`, `Glob`
and `Grep`, and the commands `paperpen feedback`, `notes`, `propose` and
`reply`, with `paperpen build` added when it implements. It has no other way
to edit a file, no git and no other shell command, and `--strict-mcp-config`
leaves out your own MCP servers. The list limits the tools, not the places:
`Read`, `Glob` and `Grep` reach any file your account can read, not only the
paper's checkout. Two of the commands do more than read: `propose --apply`
writes into the source, through paperpen, and `build` runs latexmk, which runs
the paper's own `.latexmkrc` (see
[docs/writing.md](writing.md#building-runs-the-repositorys-own-code)). Your
own Claude Code settings still apply on top of the list, so an allow rule or a
permission mode there that skips asking widens it.

Codex has no list like that to be given. It runs as `codex exec
--sandbox workspace-write`, which is its fence instead: it can write the
paper's checkout, paperpen's data and cache, where those commands write, and
the temporary directory, and nothing else. It can read more widely and run
commands inside that sandbox. Within the checkout it could edit a file or run
git; the prompt tells it to answer through paperpen and not to commit, and
nothing is committed unless you do it. Its own config is read as it stands,
the model, MCP servers and hooks included.

**A manuscript can try to steer the agent.** The agent reads the paper's
source and the notes, and text in them is read the same way as the prompt: a
comment in the LaTeX that tells it to do something else is an instruction it
may follow (prompt injection). The prompt is no defence; the fences above are.
A steered Claude Code still has only its list, and a steered Codex still
writes only where its sandbox lets it, but either can write wrong fixes, and
Codex can change any file in the checkout. So read what it did as a proposal:
each change is a fix on its note with its diff, and nothing reaches history
until you commit it, or take the branch it was committed on. Run the agent on
a paper whose repository you trust, the same rule as for building it.

Every change it makes is a fix on its note with its diff, so the note shows
what was done with an **Undo**. It runs once per round and at most twenty
minutes; its output is `agent.log` in the round's folder under the rounds
directory, and the reader's header says whether it is answering, has answered,
or could not.

Nothing it does is committed unless you ask. The header's **Commit (N notes)**
commits what the applied fixes changed and nothing else, with a message that
lists the notes, and the versions view shows that commit against the one
before. **on a branch** does the same on `paperpen/<round>`, made from where
you are; **Take it** merges it back, **Drop it** goes back and deletes it.
With `--branch`, a round the agent finished arrives on that branch already.
From a terminal, `paperpen commit <paper> [--branch]` and `paperpen branch
<paper> take|drop` are the same steps.

It needs `claude`, or `codex`, installed and signed in on the machine that
serves paperpen; `paperpen onboard --check` says which are.
The line `--print` gives is complete: it goes into the paper's folder, puts this
paperpen on the PATH, which a paperpen run with `uv run` is not otherwise, and
names the registry and the rounds when they are not the usual ones, so it can
be pasted into any terminal and answers the same round.

## The agent reading first

Everything above starts with your notes. This is the reverse: the agent reads
the paper on its own initiative and writes the notes, each one already carrying
the fix it would make, and you only decide.

```sh
paperpen review <paper>                              # read it, write notes, here
paperpen review <paper> --focus "clarity, notation"  # what to look for, in words
paperpen review <paper> --max 10 --background        # at most ten, and return
paperpen review <paper> --runner codex               # Codex reads it, into <date>-codex
paperpen review <paper> --print                      # the agent's command, to run yourself
paperpen approve <paper> <note> [<fix>]              # put its fix in, close it done
paperpen reject <paper> <note>... [--why "..."]      # close them as rejected
```

The reader's header has the same thing as **Review**: the first press asks
what to look for, in a field beside it, and the second starts the run; left
empty, it is a general read for clarity, consistency of notation, symbols used
before they are defined, grammar, references and overlong sentences. The
paper's brief, when it has one, is given to the run as the purpose of the read.

It is the agent above, headless in the paper's checkout, with a shorter list
of what it may do: read files, and run `paperpen suggest` and `paperpen notes`.
Run by Claude Code it cannot edit a file, run git, or answer your own rounds;
run by Codex it is held by the sandbox, as above. Each `suggest` is
one note, signed `--by claude` unless the run says `--by codex`:

```sh
paperpen suggest <paper> --by codex --tag LANGUAGE --note "what is wrong, and why" \
    --summary "what the fix does" --file main.tex --old "the exact text" --new "what replaces it"
paperpen suggest <paper> --tag QUESTION --note "..." --file main.tex --at "the exact text"
```

The note is **placed from its fix**: the line the `old` text starts on goes
through SyncTeX to its page, and the sentence there that carries those words
is what the note is anchored to, exactly as a note made with a finger on that
sentence would be. Matching is against the reader's own sentences, with the
line-end hyphens taken out, so a word LaTeX broke over two lines is still
found; a build without SyncTeX goes by the words alone, and text that cannot
be found anywhere leaves the note on its source line with no pin, which
`suggest` says. A fix is checked before the note is written, so one that could
never apply is refused and nothing is left behind.

Four decisions, which were the open questions when the feature was asked
for:

- **A round of its own**, `review/<date>-claude/`, or `review/<date>-codex/`
  for Codex, not mixed into yours or into each other's. A second run on the
  same day by the same agent joins it. The agent that answers your rounds
  skips it: its proposals wait for you, not for another pass of an agent.
- **A note without a fix is allowed**, for a question or a remark with no one
  right rewording (`--at` in place of `--old`/`--new`). It can be rejected, or
  closed by hand; there is nothing to approve.
- **Capped**, at 25 notes a run unless `--max` says otherwise. The run is told
  the number and `suggest` refuses the one after it. One note per place, too: a
  second note on the same text, while the first is open, is refused.
- **Nothing is committed.** An approved fix lands in the working tree as
  `apply` does, and the review's **Commit**, or `paperpen commit [--branch]`,
  is how it becomes history, on a branch of its own if you like.

In the reader, the agent's notes, Claude's or Codex's, are square pins in the
agent's colour, ringed when a fix is waiting, and say which of the two wrote
them. A note opens with **Approve** on its fix and **Reject** beside
the reply field, whatever is typed there being kept as the reason; either one
moves on to the next note with something to decide. The **Claude** chip hides
them with the rest of Claude's notes, and **proposals** shows nothing else. The
Fixes page, `/paper/<id>/feedback`, has a filter, **the agent's proposals**, and a
box on each of them, so a selection is approved or rejected at once: each note
on its own, and one that cannot go (two fixes to choose between, text that has
moved) is left open and named.

A rejection is not forgotten. Its reason stays in the note's thread, and the
next run is given the list of what was rejected and told not to propose it
again.

## An agent above the papers

The work of a round is repository work (read `NOTES.md`, change the LaTeX,
rebuild, close the notes), and that belongs in the paper's own checkout. What
does *not* belong there is deciding which paper to do that in. The registry,
the shelf and the queue already stand above every repository, so the commands
that read them are the ones to hand something that has not been given a
paper's source:

```sh
paperpen queue                   # every open note, from every paper, oldest first
paperpen queue --json            # the same, on stdout, with nothing else on it
paperpen queue --unclassified    # the ones left on AUTO, which is the triage
paperpen queue --paper X --older-than 14
paperpen next                    # what to do first, and the command that does it
paperpen next --all --json       # the whole list, in order, with a weight each
```

`next` answers with one of four kinds and never invents a fifth: **classify**
when delivered notes have no class (the class decides who acts on the note),
**work** when a round is still open, **build** when the source has moved past
the build the reader is showing, and **finish** when a reading is open and
unsent, which is reported rather than urged, because whether a round is
finished is a judgment about a paper.

Neither command writes anything, so both are safe to give something that has
no business editing a manuscript. Every row carries what is needed to act on
one note without opening the paper first: the source line, the sentence it
sits on, and for a handwritten one the path to its `ink/<id>.png`, because
there is no OCR anywhere in this and the picture is the note.

Closing the loop is `paperpen classify <paper> <id> <TAG>` and
`paperpen resolve <paper> <id> done "what was changed"`, which work from
anywhere: they go through the registry, not through the directory you happen
to be standing in. One caveat: `paperpen where` says which registry is in
force, and a `.paperpen/papers.json` in the current directory wins over the
global one, so an agent that runs inside such a directory is looking at a
different shelf.
