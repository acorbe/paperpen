#!/usr/bin/env python3
"""The shelf the demo films: four papers a person could plausibly have open.

Invented, and invented wide on purpose. A demo shelf that is all one subject
reads as one person's desk rather than as a tool, and the tool does not care
what the paper is about: it cares whether the paper has a source to point at,
whether it arrived as a repository or as a PDF, and who is waiting for the
notes. So the four here are four different subjects and four different
relationships (your own manuscript, a student's first draft, a co-author's
nearly-done paper, and a referee job), because those are the four things that
make the app behave differently.

One is in LaTeX and is built here with SyncTeX, so the source lines the demo
shows are the ones the reader really worked out and not a caption someone
wrote. The rest arrive as PDFs with no source behind them, which is exactly
why the app has to cope with that.

    demo/fixture.py [<dir>]      default /tmp/paperpen-demo
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf

WHERE = Path("/tmp/paperpen-demo")

MAIN = r"""\documentclass[twocolumn,10pt]{article}
\usepackage[margin=2cm]{geometry}
\usepackage{amsmath,graphicx,booktabs}
\title{\bf Capacity fade in second-life lithium cells}
\author{J. Marsh}
\date{}
\begin{document}
\maketitle
\begin{abstract}
A battery retired from a car still holds most of its charge, and what happens
to it next depends on how fast it keeps losing it. We cycle 48 retired cells
for eighteen months and report the fade rate against depth of discharge, and
we find the rate turns sharply once the cell is taken below a third full.
\end{abstract}
\input{sec_cells}
\input{sec_results}
\end{document}
"""

CELLS = r"""\section{The cells}
A cell leaves a car at about 80\% of the capacity it was sold with, which is
the point at which the car stops being worth driving and the cell starts being
worth something else. What it is worth depends entirely on the second curve:
how fast it fades from there, under a duty cycle nothing like the one it was
designed for.

The 48 cells here were recovered from vehicles taken off the road over three
years. Every cell in the sample came out of the same vehicle model, and we
report the fade rates as representative of second-life packs in general. They
were cycled at a constant 0.5C between fixed voltage limits, in a room held at
25 degrees Celsius, for eighteen months without interruption.

Capacity was measured every 50 cycles by a full discharge at 0.2C, which is
slow enough that the number does not depend on the rate. The cells were rested
for four hours before each measurement.
"""

RESULTS = r"""\section{Results}
Fade is linear in cycle count while the cell stays above a third full, and
stops being linear below that. Above the knee the 48 cells agree closely; below
it they scatter, and the scatter grows with every hundred cycles.

Taking a cell to 20\% costs roughly three times the capacity per cycle that
taking it to 40\% costs, which is not what a linear model of depth of discharge
predicts and is the main practical result here.

\begin{table}[t]
\centering
\begin{tabular}{lcc}
\toprule
depth of discharge & fade per 100 cycles & spread \\
\midrule
40\% & 0.21\% & 0.03 \\
60\% & 0.38\% & 0.06 \\
80\% & 0.74\% & 0.19 \\
\bottomrule
\end{tabular}
\caption{How fast the cells fade, by how far down they are taken.}
\label{tab:fade}
\end{table}

\section{Conclusions}
A second-life pack should be sized so that it is never taken below a third
full. Sizing it on the average load instead, which is what the linear model
invites, buys a smaller pack and spends the saving twice over in replacement.
"""

# What arrives from other people, as PDFs, with no source to point at.
DRAFTS = [
    ("sleep", "Sleep timing and next-day reaction time in first-year students",
     "student",
     "A first draft. Language throughout, and whether the claim in Sec. 3 survives"
     " the small sample.",
     ["Sleep timing and next-day reaction time in first-year students",
      "P. Okafor",
      "",
      "Abstract. We asked 91 first-year students to record when they went to sleep and",
      "to take a reaction-time test the next morning. Students who went to sleep after",
      "02:00 were slower the following morning by 38 ms on average, and the effect",
      "persisted after controlling for how long they had slept.",
      "",
      "1. Introduction",
      "Going to bed late is the commonest complaint in first-year teaching, and it is",
      "commonly assumed to matter only through total sleep. That assumption is worth",
      "testing, because the two are easy to separate in a student population: plenty",
      "of them sleep eight hours starting at three in the morning.",
      "",
      "2. Method",
      "Participants recorded sleep onset in a phone diary for four weeks.",
      "A session was counted when the diary entry arrived before the test and the test",
      "was taken within an hour of waking. Of 91 students, 63 completed all four weeks;",
      "the remaining 28 contributed between one and three.",
      "",
      "Reaction time was measured with a five-minute visual task taken on the",
      "student's own laptop, which introduces a display-latency term we have not",
      "measured and assume to be constant within a participant.",
      "",
      "3. Results",
      "Sleep onset after 02:00 costs 38 ms, with a standard error of 9 ms. Total sleep",
      "duration costs a further 11 ms per hour lost. The two terms are separable in our",
      "sample, which we did not expect at this sample size.",
      "",
      "The effect is larger in the first week than in the fourth. We take this as",
      "practice on the task rather than as an adaptation to late nights, though we",
      "cannot separate the two from these data.",
      "",
      "4. Discussion",
      "When a student goes to sleep appears to matter on its own, and not only through",
      "how long they then sleep. Timetabling that assumes otherwise is assuming too",
      "much."]),
    ("particulate", "A field calibration for low-cost particulate sensors",
     "coauthor",
     "Ready to submit as far as I am concerned. One more read for the figures.",
     ["A field calibration for low-cost particulate sensors",
      "L. Ferrero and J. Marsh",
      "",
      "Abstract. Cheap optical particulate sensors read high in humid air and the",
      "error is not constant. We give a two-parameter correction fitted against a",
      "reference instrument over one winter, and show it holds at a second site the",
      "following winter without refitting.",
      "",
      "1. The problem",
      "An optical sensor counts droplets as particles. In humid air it therefore reads",
      "high, by a factor that rises steeply above 75% relative humidity and that",
      "differs between units of the same model.",
      "",
      "2. The correction",
      "The correction is a growth factor in relative humidity with a per-unit scale.",
      "The scale is fitted once against a reference instrument and does not need the",
      "reference again afterwards.",
      "",
      "3. Validation",
      "Against a second site and a second winter the corrected readings are within 12%",
      "of the reference at all humidities below 95%, against 60% uncorrected."]),
    ("wake", "Wake transitions behind a heated cylinder", "referee",
     "Referee for JFM. The claim in Sec. 3 and the statistics behind Fig. 4 are what"
     " matters; language only where it obscures the physics.",
     ["Wake transitions behind a heated cylinder",
      "(manuscript JFM-2026-0917, under review)",
      "",
      "Abstract. Heating a cylinder delays the onset of vortex shedding. We locate the",
      "transition for four heating rates and find it shifts to a Reynolds number 18%",
      "higher at the strongest heating, which we attribute to the change in viscosity",
      "in the boundary layer.",
      "",
      "3. Where the wake turns over",
      "The shift we measure, 18% +/- 4%, is the same at all four heating rates. This is",
      "surprising, since the viscosity argument predicts a shift that grows with the",
      "heating. We believe the discrepancy is due to the finite length of the cylinder.",
      "",
      "4. Statistics",
      "Each point in the figure averages 200 shedding cycles. Error bars are the",
      "standard error on the mean. The four heating rates are wall temperatures of 20,",
      "40, 60 and 80 K above ambient, and each was run for 400 convective time units",
      "after the transient had passed.",
      "",
      "5. Comparison with the literature",
      "Our shift is larger than the 11% reported for an unheated cylinder in a confined",
      "channel at comparable blockage. We attribute the difference to the walls, which",
      "suppress the spanwise mode that would otherwise set in first.",
      "",
      "6. Conclusions",
      "Heating moves the transition, and the move does not depend on how hard the",
      "cylinder is heated over the range we can reach. A model that predicts a",
      "dependence is therefore incomplete."]),
]


def run(cmd: list[str], cwd: Path) -> None:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    if done.returncode != 0 and not (cwd / "main.pdf").is_file():
        raise SystemExit(f"{' '.join(cmd[:2])} failed in {cwd}:\n{done.stdout[-1200:]}")


def latex_paper(root: Path) -> Path:
    repo = root / "secondlife"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "main.tex").write_text(MAIN, encoding="utf-8")
    (repo / "sec_cells.tex").write_text(CELLS, encoding="utf-8")
    (repo / "sec_results.tex").write_text(RESULTS, encoding="utf-8")
    run(["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", "main.tex"], repo)
    if not (repo / ".git").is_dir():
        run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "add", "-A"], repo)
    subprocess.run(["git", "-c", "user.name=J. Marsh", "-c", "user.email=j@example.org",
                    "commit", "-qm", "second-life cells, first full draft"],
                   cwd=repo, capture_output=True, text=True)
    return repo


def pdf_draft(root: Path, slug: str, lines: list[str]) -> Path:
    repo = root / slug
    repo.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page()
    y = 90
    # A numbered heading is bold; a line that merely opens with digits is not,
    # or "02:00 were slower..." comes out looking like a section.
    heading = re.compile(r"^\d+\.\s")
    for i, line in enumerate(lines):
        big = i == 0
        page.insert_text(pymupdf.Point(64, y), line,
                         fontname="hebo" if big or heading.match(line) else "helv",
                         fontsize=15 if big else 9.5)
        y += 26 if big else 14
    doc.new_page()  # so every draft has more than one page to swipe through
    doc.save(repo / "draft.pdf")
    doc.close()
    return repo


def build(root: Path = WHERE, fresh: bool = True) -> Path:
    """Made again from nothing every time.

    Left standing, the cache and the rounds from the last run leak into the
    next one: a note the film has not made yet is already on the shelf in its
    first frame. A demo that cannot be rebuilt identically is a recording.
    """
    if fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config"
    config.mkdir(exist_ok=True)

    papers = [{
        "id": "second-life-cells",
        "name": "Capacity fade in second-life lithium cells",
        "repo": str(latex_paper(root)), "main": "main.tex", "kind": "mine",
        "brief": "My own. The cells section is new since the last read.",
    }]
    for slug, name, kind, brief, lines in DRAFTS:
        papers.append({"id": f"{slug}-draft", "name": name,
                       "repo": str(pdf_draft(root, slug, lines)), "main": "draft.pdf",
                       "kind": kind, "brief": brief})
    (config / "papers.json").write_text(
        json.dumps({"papers": papers}, indent=2) + "\n", encoding="utf-8")
    return root


def env(root: Path = WHERE) -> dict:
    return {**os.environ,
            "PAPERPEN_HOME": str(root / "config"),
            "PAPERPEN_CACHE": str(root / "cache"),
            "PAPERPEN_DATA": str(root / "data"),
            # the film shows the answer as the agent would give it, but does
            # not start one: nothing in a demo calls out to a model
            "PAPERPEN_AGENT": "off"}


if __name__ == "__main__":
    where = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else WHERE
    print(f"{build(where)}: {len(json.loads((where / 'config' / 'papers.json').read_text())['papers'])} papers")
