"""Spelling, for the editor: which words of a LaTeX file aspell does not know.

aspell's own TeX mode skips command names and comments, and not much else: it
reads the key of every `\\cite` and `\\cref` as a word, and the whole of the
mathematics, so `$\\rho_{crit}$` is a misspelling of "crit". So before the text
goes to aspell, what is not prose is blanked, character for character, so that
the offsets aspell gives back are still offsets into the file:

- mathematics, inline and displayed, including the usual environments
- the arguments of commands that name things rather than say them: citations,
  references, labels, files, packages, environments, addresses
- options in square brackets after a command

A paper keeps its own words, the ones aspell has not heard of and the paper
uses on purpose, in `.paperpen-words` at the root of its repository, one per
line. It is a plain file in the paper's tree, so it is committed with the paper
and a coauthor's editor accepts the same words.

The language is the paper's own: `british` or `UKenglish` given to babel means
en_GB, anything else en_US.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from . import bind, edit

WORDS = ".paperpen-words"
MOST = 2000         # words reported for one file; past that it is not English

MATH_ENVS = ("equation", "align", "alignat", "gather", "multline", "eqnarray",
             "math", "displaymath", "flalign", "split", "subequations")
NAMING = ("cite", "citep", "citet", "citealp", "citeauthor", "citeyear", "nocite",
          "parencite", "textcite", "autocite", "footcite",
          "ref", "eqref", "cref", "Cref", "autoref", "pageref", "nameref", "vref",
          "label", "input", "include", "includegraphics", "includepdf", "bibliography",
          "bibliographystyle", "addbibresource", "usepackage", "RequirePackage",
          "documentclass", "begin", "end", "url", "href", "hypersetup", "graphicspath",
          "newcommand", "renewcommand", "providecommand", "DeclareMathOperator",
          "newenvironment", "setlength", "addtolength", "color", "textcolor",
          "definecolor", "SI", "si", "num", "unit", "qty", "ang")

_ENVS = "|".join(MATH_ENVS)
_MATH = re.compile(
    r"\$\$.*?\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\(.*?\\\)|\\\[.*?\\\]"
    r"|\\begin\{(" + _ENVS + r")\*?\}.*?\\end\{\1\*?\}", re.S)
_NAMING = re.compile(r"\\(?:" + "|".join(NAMING) + r")\*?(?:\s*\[[^\]\n]*\])*(?:\s*\{[^{}\n]*\})+")
_OPTIONS = re.compile(r"(?<=[a-zA-Z*])\[[^\]\n]*\]")
_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)


def available() -> bool:
    return bool(shutil.which("aspell"))


def _blank(text: str, pattern: re.Pattern) -> str:
    # every character but a newline becomes a space, so lines and offsets hold
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def prose(text: str) -> str:
    """The text with everything that is not prose blanked, the same length."""
    for pattern in (_COMMENT, _MATH, _NAMING, _OPTIONS):
        text = _blank(text, pattern)
    return text


def language(paper) -> str:
    try:
        main = edit.read(paper, paper.main)["text"]
    except (bind.Refused, OSError):
        main = ""
    babel = re.search(r"\\usepackage\[([^\]]*)\]\{babel\}", main)
    if babel and re.search(r"\b(british|UKenglish)\b", babel.group(1)):
        return "en_GB"
    return "en_US"


def words(paper) -> list[str]:
    """The paper's own words, as kept in its repository."""
    full = paper.repo / WORDS
    if not full.is_file():
        return []
    return [w.strip() for w in full.read_text(encoding="utf-8").splitlines() if w.strip()]


def accept(pid: str, word: str) -> dict:
    """Add a word to the paper's own, so it is no longer marked."""
    paper = bind.resolve_paper(pid)
    edit.need(paper)
    word = word.strip()
    if not word or re.search(r"\s", word) or len(word) > 80:
        raise bind.Refused("one word, please")
    have = words(paper)
    if word not in have:
        # a fixed name at the root, not a path from the page, so it needs
        # none of the checks `edit.inside` makes of one
        full = paper.repo / WORDS
        if full.is_symlink():
            raise bind.Refused(f"{WORDS} is a link, and paperpen writes only real files")
        full.write_text("\n".join(sorted(have + [word], key=str.lower)) + "\n", encoding="utf-8")
    return {"word": word, "words": len(set(have) | {word})}


def check(pid: str, text: str) -> dict:
    """The words of `text` aspell does not know, each with its line, where it
    starts and ends on that line, and what aspell would put instead."""
    paper = bind.resolve_paper(pid)
    edit.need(paper)
    lang = language(paper)
    if not available():
        return {"available": False, "lang": lang, "words": []}
    lines = prose(text).split("\n")
    # `!` is terse mode, `@word` accepts a word for this run, and `^` in front
    # of every line keeps a line that starts with a special character from
    # being read as a command
    feed = ["!"] + ["@" + w for w in words(paper)] + ["^" + line for line in lines]
    try:
        out = subprocess.run(
            ["aspell", "-a", "--mode=tex", "-l", lang, "--encoding=utf-8"],
            input="\n".join(feed) + "\n", capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise bind.Refused(f"aspell did not answer: {err}")
    if out.returncode:
        raise bind.Refused("aspell: " + (out.stderr.strip().splitlines() or ["failed"])[-1])
    found, n, more = [], 0, False
    # after the banner, each input line answers with its findings and then a
    # blank line; an offset counts the `^`, so it is one past the character
    for row in out.stdout.split("\n")[1:]:
        if not row:
            n += 1
            continue
        if row[0] not in "&#":
            continue
        head, _, rest = row.partition(":")
        bits = head.split()
        word = bits[1]
        at = int(bits[-1]) - 1
        if len(found) >= MOST:
            more = True
            break
        found.append({"line": n + 1, "from": at, "to": at + len(word), "word": word,
                      "suggest": [s.strip() for s in rest.split(",") if s.strip()][:6]})
    return {"available": True, "lang": lang, "words": found, "more": more}
