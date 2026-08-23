"""The update replaced the updater with a file Windows could not run.

Reported from the clinic, and it is the worst shape a bug can take: the update
worked. It took the backup, fetched the new code, installed the dependencies,
upgraded the database, checked the program starts, and recorded the version.
Then `robocopy` copied the new `update.bat` over the old one, and the next time
somebody double-clicked it the window opened and shut.

**Every `.bat` in this repository had LF line endings.** `cmd.exe` reads a
batch file expecting CRLF; given LF alone it mangles labels, `goto`, and `^`
line continuations. The evidence was in which files broke and which did not:

    start.bat        goto=0   labels=0    ^=0     ← still worked
    update.bat       goto=2   labels=6    ^=11    ← opened and shut
    tools.bat        goto=13  labels=14   ^=0     ← the restore screen

The file with none of the three was the only one still running. That is not a
coincidence, it is the diagnosis.

**And it had been hidden by an earlier bug.** Every previous update failed at
`[2/5]`, so `robocopy` never ran and the clinic kept whatever `.bat` files it
already had. Fixing the fetch is what finally let the broken copies land — the
first successful update in the program's life was also the one that broke the
updater.

The severity is not the batch file. `tools.bat` is where a clinic restores a
backup, so a clinic that hit this had no way to update *and* no way to roll
back, from a routine maintenance task that reported success.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PATTERNS = ("*.bat", "*.cmd", "*.ps1")


def _scripts():
    found = []
    for pattern in PATTERNS:
        found += sorted(glob.glob(os.path.join(ROOT, pattern)))
    return found


def test_there_are_windows_scripts_to_check():
    """The guard on the guard. If these ever move to a folder, this file goes
    green by finding nothing and stops protecting anything."""
    assert _scripts(), "no Windows scripts found — has this test been left behind?"


@pytest.mark.parametrize("path", _scripts(), ids=os.path.basename)
def test_every_line_ends_the_way_cmd_expects(path):
    """CRLF, on every line, with no lone LF anywhere.

    Checked as bytes rather than by reading text, because Python's own
    universal newlines would hide exactly the difference being tested.
    """
    raw = open(path, "rb").read()

    lone = raw.replace(b"\r\n", b"").count(b"\n")
    assert lone == 0, \
        (f"{os.path.basename(path)} has {lone} line(s) ending in LF alone. "
         f"cmd.exe mangles labels, goto and ^ continuations in such a file, "
         f"and the window opens and shuts.")


@pytest.mark.parametrize("path", _scripts(), ids=os.path.basename)
def test_no_byte_order_mark(path):
    """A BOM arrives as three bytes in front of `@echo off`, and cmd tries to
    run them."""
    assert not open(path, "rb").read(3) == b"\xef\xbb\xbf", \
        f"{os.path.basename(path)} starts with a byte-order mark"


def test_git_is_told_to_leave_them_alone():
    """`-text` rather than `eol=crlf`, and the difference is the whole fix.

    `eol=crlf` normalises on checkout, which helps a `git clone` and does
    nothing at all for a ZIP downloaded from the web page — and the ZIP is the
    copy most clinics have, and the copy this failure happened on. `-text`
    means the bytes in the repository are the bytes everybody gets, by every
    route in.
    """
    path = os.path.join(ROOT, ".gitattributes")
    assert os.path.exists(path), "nothing stops the next commit normalising them"
    rules = open(path, encoding="utf-8").read()

    for pattern in PATTERNS:
        assert f"{pattern} -text" in rules, \
            (f"{pattern} is not pinned to `-text`. Without it git may "
             f"normalise these to LF on the next commit and the clinic gets "
             f"an updater that will not open.")


def test_the_update_still_replaces_them(monkeypatch):
    """It should — and that is precisely why the bytes have to be right.

    Excluding the scripts from the copy would look like a fix and would mean a
    clinic never receiving a correction to its own updater. They keep being
    replaced; what changed is that what replaces them can run.
    """
    update = open(os.path.join(ROOT, "update.bat"), "rb").read().decode("utf-8")

    excluded = update.split("/XF", 1)[1].split("\n", 1)[0] if "/XF" in update else ""
    assert ".bat" not in excluded, \
        "the update stopped shipping its own scripts, so a fix can never arrive"


@pytest.mark.parametrize("script,label_count", [("update.bat", 6), ("tools.bat", 14)])
def test_the_files_that_broke_are_the_ones_with_labels(script, label_count):
    """Kept as a record of the diagnosis rather than as a rule.

    These are the two files whose structure `cmd` cannot survive LF endings
    in. If either ever loses its labels the count here is wrong and somebody
    should read this file before changing the number — the point is that the
    risk is concentrated here, not that six is a magic figure.
    """
    text = open(os.path.join(ROOT, script), "rb").read().decode("utf-8")
    labels = [ln for ln in text.splitlines() if ln.startswith(":")]

    assert len(labels) >= 2, \
        f"{script} has no labels any more — is this test still describing it?"
