"""Two installs a hundred commits apart, both saying **0.1**.

``APP_VERSION`` was typed once and never changed again — through every release
since. The doctor's machine and the newest build printed the same string, so
the number on the About page answered "which version is this?" **wrongly**
rather than admitting it did not know, which is the worse of the two.

And it was typed twice: once in ``version.py`` for the backup manifest, once
in the app factory for the sidebar. Two copies of one stale string.

The file already made this argument about the *schema* number: *"a number
somebody has to remember to bump is a number that will be wrong exactly when
it matters — the release where a column was added and the version was not.
Deriving it means it cannot drift from the thing it describes."* The release
number was the one number in it that had not been derived.

**So it is a date, worked out from the build.** Sortable, readable by anybody,
and obviously wrong when it is wrong. Asked for in those words: *«عايز رقم
النسخة يبقى واضح، بلاش بالأرقام والحروف كده»* — the hashes stay where they
belong, in the support block, and the headline says a date.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_the_version_is_a_date(clinic):
    from app.utils.version import app_version

    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", app_version()), app_version()


def test_it_is_not_the_string_that_never_changed(clinic):
    from app.utils.version import APP_VERSION, FALLBACK_VERSION

    assert APP_VERSION != FALLBACK_VERSION


def test_it_reads_as_a_version_and_not_as_a_hash(clinic):
    """The whole of the request: no letters to read out over a phone."""
    from app.utils.version import app_version

    assert app_version().replace(".", "").isdigit()


def test_two_builds_are_ordered_by_it(clinic):
    """A version that cannot be compared is a label, not a version. Dates in
    this shape sort as strings, which is why the year comes first."""
    assert "2026.09.06" < "2026.09.07" < "2026.10.01" < "2027.01.01"


def test_a_copy_with_no_repository_still_knows_when_it_arrived(clinic, tmp_path):
    """The clinic that installed from a download. Whatever put the files there
    set their date — an unzip or a checkout — so this is a true answer rather
    than a guess."""
    from app.utils.version import _file_date

    package = tmp_path / "app" / "utils"
    package.mkdir(parents=True)
    (package / "thing.py").write_text("x = 1", encoding="utf-8")
    stamped = _file_date(str(tmp_path))
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", stamped or ""), stamped


def test_an_empty_folder_says_so_rather_than_inventing_a_date(clinic, tmp_path):
    from app.utils.version import _file_date

    assert _file_date(str(tmp_path)) is None


def test_there_is_one_copy_of_it(clinic):
    """It was written in two places, and the second was the one on the screen
    every user looks at."""
    source = open(os.path.join(ROOT, "app", "__init__.py"),
                  encoding="utf-8").read()
    assert '"app_version": "0.1"' not in source
    assert "app_version()" in source


def test_the_page_and_the_manifest_say_the_same_thing(clinic):
    """A backup that names a different version from the program that wrote it
    is the exact confusion ``version.py`` exists to prevent."""
    from app.utils.version import app_version, manifest

    page = clinic["sign_in"]("boss").get("/about").get_data(as_text=True)
    assert app_version() in page
    assert manifest()["app_version"] == app_version()


def test_the_support_block_still_carries_the_technical_answer(clinic):
    """The hashes are not deleted, they are put where they belong: the
    schema fingerprint is what tells somebody a restored backup came from an
    older build, and it is for whoever is helping, not for the doctor."""
    from app.utils.project import support_lines

    with clinic["app"].app_context():
        block = "\n".join(support_lines())
    assert "schema" in block and "gen " in block
