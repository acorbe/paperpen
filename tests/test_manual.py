"""The manual, and what must not be in it.

GitHub Pages serves `manual/` as it stands, to anyone with the URL, so the
manual is written for that: no home directories, no
internal hostnames, no private repository names, no addresses of ours. The
examples use the ranges the RFCs set aside for documentation.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "manual"
PAGES = sorted(MANUAL.glob("*.html"))

# What would identify the house. Deliberately narrow: a generic private address
# belongs to everybody and flagging every one of them buries the real finding.
HOUSE = [
    (r"/home/[a-z][a-z0-9_-]*", "a home directory"),
    (r"/Users/[a-z][a-z0-9_-]*", "a home directory"),
    (r"\b[a-z0-9-]+\.(?:tue|edu)\.nl\b", "an internal hostname"),
    (r"\bgit@(?!example\.org)[a-z0-9.-]+:", "a private git remote"),
    (r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", "a private key"),
    (r"\b131\.155\.\d{1,3}\.\d{1,3}\b", "a campus address"),
    (r"\bAKIA[0-9A-Z]{16}\b", "a credential"),
]

# The private dashboard paperpen is taken from is named by $PAPERPEN_BOARD (see
# scripts/sync.py), so its name is checked for without being written here.
_BOARD = os.environ.get("PAPERPEN_BOARD", "").rstrip("/")
if _BOARD:
    HOUSE.append((re.escape(Path(_BOARD).name), "the private dashboard"))

# The documentation ranges, which are the only literal addresses allowed.
FINE = re.compile(r"\b(?:192\.0\.2|198\.51\.100|203\.0\.113)\.\d{1,3}\b|127\.0\.0\.1")


def test_the_manual_is_in_step_with_what_writes_it():
    """The pages are committed as HTML, so the generator and the directory have
    to be checked against each other the way upstream/ is."""
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "manual.py"), "--check"],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_names_the_house(page):
    text = page.read_text(encoding="utf-8")
    for pattern, what in HOUSE:
        found = re.search(pattern, text)
        assert not found, f"{page.name} has {what}: {found.group(0)!r}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_address_is_a_documentation_address(page):
    text = page.read_text(encoding="utf-8")
    for found in re.finditer(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
        assert FINE.fullmatch(found.group(0)), \
            f"{page.name} has the address {found.group(0)}, which is not a " \
            f"documentation range"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_link_and_picture_resolves(page):
    text = page.read_text(encoding="utf-8")
    for where in re.findall(r'(?:href|src)="([^"]+)"', text):
        if where.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert not where.startswith("/"), \
            f"{page.name} links to {where}; Pages may serve this under a " \
            f"prefix, so links have to be relative"
        where, _, anchor = where.partition("#")
        assert (MANUAL / where).is_file(), f"{page.name} points at {where}, which is not there"
        # a link into a page has to land on something: the id has to be there
        if anchor:
            assert f'id="{anchor}"' in (MANUAL / where).read_text(encoding="utf-8"), \
                f"{page.name} points at {where}#{anchor}, and {where} has no such id"


def test_the_pictures_are_the_demo_shelf_and_not_a_real_paper():
    """The shots come from demo/fixture.py, which is invented. What can be
    checked here is that they exist and that the page still asks for them."""
    shots = {p.name for p in (MANUAL / "shots").glob("*.png")}
    assert shots, "no pictures; scripts/manual-shots.py takes them"
    asked = set()
    for page in PAGES:
        asked |= {Path(s).name for s in
                  re.findall(r'src="(shots/[^"]+)"', page.read_text(encoding="utf-8"))}
    assert asked <= shots, f"the manual asks for pictures that are not there: {asked - shots}"
    assert shots <= asked, f"pictures nothing asks for: {shots - asked}"


def test_the_pages_job_publishes_what_is_committed():
    gh = (ROOT / ".github" / "workflows" / "manual.yml").read_text(encoding="utf-8")
    assert "upload-pages-artifact" in gh and "path: manual" in gh, \
        "the job should publish manual/ as it is, not build it"
