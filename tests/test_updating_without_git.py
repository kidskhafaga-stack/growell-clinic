"""Updating a copy that was downloaded rather than cloned.

Reported: *"there is an update file in the project, and when I run it on the
machine it asks for git. Does it fetch the update from GitHub directly? And
why doesn't it work? Right now I take the project from GitHub, replace all the
files, restart the server, and it works — is that the same thing?"*

Three answers, and the third is why this exists.

**It does fetch from GitHub** — step two is `git pull --ff-only`.

**It asked for git because it needs a repository, not the program.** A copy
downloaded as a ZIP is not a repository, so no amount of installing git makes
`git pull` work in it — and the ZIP is what the GitHub page offers, so it is
the copy most clinics have. The file diagnosed that as "git is not installed",
which is the wrong sentence and the wrong remedy.

**And replacing the files by hand is not the same thing.** It happens to work,
because `start.bat` runs `sync-db` on every launch and that applies the schema.
What it skips is everything around it: **the backup taken first**, the new
dependencies, the catalogue seeders — a vaccine added to the catalogue only
arrives through `upgrade-db` — and the check that the program still starts.

So the download path is built into the file, and it keeps every one of those
steps. The manual routine becomes the supported one instead of the one people
fall back to because the supported one refused to run.

**These are structural checks, not a run.** A batch file cannot be executed
here, so what is asserted is the part that would be silently wrong: which
folders are excluded from the copy, and the two pieces of batch semantics that
fail without a sound rather than with one.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def script():
    with open(os.path.join(ROOT, "update.bat"), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def code(script):
    """The script with its `REM` lines removed.

    Every one of these checks reads the file as text, and the first versions
    of three of them failed on the file's own comments — including one that
    searched for `if errorlevel 1` and found the comment explaining why
    `if errorlevel 1` would be wrong here. A check that cannot tell an
    explanation from the thing it explains is a check that gets deleted rather
    than read.
    """
    return "\n".join(line for line in script.splitlines()
                      if not line.strip().upper().startswith("REM"))


# ------------------------------------------------------------- both paths

def test_a_clone_is_still_updated_with_git(script):
    assert "git pull --ff-only" in script


def test_a_downloaded_copy_is_updated_too(script):
    """The whole report: this used to stop and blame git."""
    assert ":fetch_zip" in script
    assert "codeload.github.com" in script
    assert "[ERROR] git is not installed" not in script, \
        "the file still refuses to update a copy that is not a clone"


def test_which_path_is_chosen_asks_for_a_repository(script):
    """`where git` alone is the wrong question — a machine can have git and a
    folder that is not a clone, which is exactly the reported case."""
    assert re.search(r'if not errorlevel 1 if exist "\.git"', script), \
        "the choice is made on whether git exists rather than on whether this "\
        "copy is a repository"


# ----------------------------------------- what the copy must never touch

@pytest.mark.parametrize("keep", ["instance", "uploads", "clinic.env",
                                  ".venv", "*.db"])
def test_the_clinics_own_data_is_excluded_from_the_copy(script, keep):
    """`instance` is the database and every backup, `uploads` is every
    photograph, signature and scanned document, and `clinic.env` is this
    machine's port. Copying without them is an update; copying over them is a
    clinic losing its records to a maintenance task."""
    exclusions = re.search(r"/XD (.+?)\^?\n.*?/XF (.+?)\^?\n", script, re.S)

    assert exclusions, "the copy has no exclusions at all"
    assert keep in exclusions.group(0), f"{keep} is not protected from the copy"


def test_the_copy_never_deletes(script):
    """`/E` adds and overwrites; `/MIR` would delete anything not in the
    archive. A stale file costs far less than a mistyped exclusion."""
    assert "/MIR" not in script, "the copy would delete files it does not know"
    assert re.search(r"robocopy .+ /E", script)


def test_it_checks_what_it_downloaded_is_the_program(code):
    """An empty or wrong archive copied over a clinic is worse than a failed
    download."""
    body = code.split(":fetch_zip", 1)[1]

    assert "run.py" in body, \
        "nothing checks the download is PediaPro before copying it over"
    assert "if not defined PP_SRC" in body, \
        "an empty download would be copied over the clinic"


# --------------------------- the two pieces of batch that fail silently

def test_the_download_is_not_run_inside_a_parenthesised_block(code):
    """A variable set inside `( ... )` is expanded when the block is *parsed*,
    so the folder name found by the `for` loop would reach robocopy empty —
    and robocopy with an empty source is not an error. It is a copy of nothing,
    followed by an update that silently did not happen.

    Written as a called subroutine for that reason, and asserted because the
    failure mode has no symptom.
    """
    assert "call :fetch_zip" in code

    body = code.split(":fetch_zip", 1)[1]
    lines = body.splitlines()
    upto = lines[:next(i for i, ln in enumerate(lines) if "robocopy" in ln)]
    depth = sum(ln.count("(") - ln.count(")") for ln in upto)

    assert depth == 0, \
        "the robocopy call sits inside an open block, where %PP_SRC% expands "\
        "empty and the update silently copies nothing"


def test_robocopy_success_is_read_correctly(code):
    """robocopy reports 0–7 for success — 1 means "files were copied". Read
    with `if errorlevel 1`, every successful update is reported as a failure
    and the clinic is told to restore a backup it did not need."""
    after = code.split(":fetch_zip", 1)[1].split("robocopy", 1)[1]

    assert "if errorlevel 8" in after
    assert "if errorlevel 1" not in after, \
        "a successful copy would be read as a failure"


# ------------------------------------------------- the steps around it

def test_the_backup_still_comes_first(script):
    """The reason this file exists at all. Whichever way the code arrives, it
    arrives after a snapshot that has been checked."""
    order = [script.index("backup-now"),
             script.index("[2/5] Fetching"),
             script.index("upgrade-db")]

    assert order == sorted(order), \
        "the code is fetched before the backup is taken"


def test_the_download_path_still_reaches_the_upgrade(script):
    """`sync-db` on launch brings the schema up; only `upgrade-db` re-runs the
    seeders. A vaccine added to the catalogue arrives through this step and no
    other — which is precisely what replacing the files by hand misses."""
    fetched = script.index(":fetched")

    assert script.index("upgrade-db") > fetched
    assert script.index("pip install -r requirements.txt") > fetched


# ------------------------------------------ what it says when it cannot fetch

def test_not_found_is_not_reported_as_being_offline(code):
    """The message that sent somebody hunting for a network fault.

    GitHub answers **404** — not 403 — for a repository the caller may not
    read, so a private repository, a renamed branch and a deleted project all
    arrive here looking identical. What arrived instead was "offline, or
    GitHub is not reachable", which is the one thing it was not: the machine's
    connection was fine and the repository was simply private.

    The download is anonymous on purpose and stays that way — a token able to
    read the source would then sit in plain text on every clinic PC that has
    ever been updated — so 404 is a state this script has to be able to
    describe rather than one it can sign its way out of.
    """
    assert "errorlevel 44" in code, \
        "the download no longer separates 'not found' from any other failure"

    at_404 = code.index("errorlevel 44")
    at_other = code.index("errorlevel 1", at_404)
    assert at_404 < at_other, (
        "`if errorlevel N` means 'N or more', so the 404 branch has to be "
        "tested before the catch-all or it can never be reached")

    tail = code[at_404:at_other]
    assert "not found" in tail.lower(), "the 404 branch does not say what it is"
    assert "offline" not in tail.lower(), \
        "the 404 branch is still calling a private repository an outage"


def test_it_says_what_to_do_instead(code):
    """A clinic told only that something failed is a clinic that stops
    updating. The way that always works is written down next to the error."""
    at_404 = code.index("errorlevel 44")
    tail = code[at_404:code.index("errorlevel 1", at_404)]

    assert "upgrade-db" in tail, \
        "it does not say how to finish an update done by hand"
    for kept in ("instance", "uploads", "clinic.env"):
        assert kept in tail, \
            f"the manual route does not warn about {kept}"


def test_the_real_outage_still_says_so(code):
    """And the other half: an actual network failure must not be described as
    a private repository either."""
    at_other = code.index("errorlevel 1", code.index("errorlevel 44"))
    tail = code[at_other:at_other + 500]

    assert "offline" in tail.lower()
    assert "not found" not in tail.lower()


# ---------------------------------------- the trap that broke a real update

def test_no_command_is_spread_over_lines_inside_a_for_block(code):
    """The bug a clinic hit, and the shape of it rather than the instance.

    A `for /f` that captured PowerShell's output had its command spread over
    three lines with `^` continuations **inside** the block. The caret does not
    mean there what it means everywhere else: the command reached PowerShell in
    pieces, PowerShell complained, and the complaint was captured as the value
    — which was then used as a commit id in a download URL.

    The result was `zip/<an error message>`, and GitHub answered 404 on a
    public repository with the branch sitting right there. The error message
    named three causes and the real one was a fourth the script had invented.

    Held as a rule about the shape, not about that line: a command inside a
    `for /f` capture is one line or it is not trusted.
    """
    lines = code.splitlines()
    offenders = []
    depth_open = False
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if "for /f" in stripped.lower() and "(`" in stripped:
            depth_open = not stripped.rstrip().endswith("`)") \
                and "`)" not in stripped
            if depth_open and stripped.endswith("^"):
                offenders.append(number)
            continue
        if depth_open:
            if stripped.endswith("^"):
                offenders.append(number)
            if "`)" in stripped:
                depth_open = False

    assert not offenders, (
        "a `for /f` capture continues across lines with `^`, which is how the "
        f"update download came to ask GitHub for an error message: {offenders}")


def test_the_download_asks_for_the_branch_by_name(code):
    """One URL, and one that cannot be assembled wrongly.

    What the removed pre-lookup bought was a seconds-wide window in which a
    commit could land between the download and the stamp. `record-version`
    closes that by asking the branch itself, and a race that narrow does not
    justify a line of batch nobody can read.
    """
    assert "refs/heads/%PP_BRANCH%" in code, \
        "the download no longer names the branch it wants"
    assert "PP_SHA" not in code, \
        "the commit-id lookup is back — see the test above for why it went"
