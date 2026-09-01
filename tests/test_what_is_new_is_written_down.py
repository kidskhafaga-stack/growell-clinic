"""What changed, written down rather than inferred.

Asked for directly: *"عايز ايه الجديد فى النسخه المحدثه تحسينات فى ايه وايه
المزايا الجديده تصليح باج معين كده لازم يتكتب"*.

The program already showed something — the subject lines of the commits
between the installed version and the new one. Those are titles, and a good
title still does not say whether a release is a feature somebody asked for or
the bug they have been hitting all week. A clinic reading them cannot decide
whether to close for five minutes now or after lunch, which is the only
decision this screen exists to support.

So there is a file, `WHATS_NEW.md`, and the three things a clinic is ever told
about a release: what is new, what improved, what was fixed.

**Fetched, not read from disk.** The interesting copy is the *new* version's:
a clinic on last month's release does not have the file that describes what it
is about to install.

**Compared by section, not by version number.** A clinic three releases behind
is shown all three. Being shown only the newest is how somebody concludes an
update is smaller than it is and puts it off again.
"""
import os

import pytest

from app.utils import updates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

SAMPLE = """# الجديد

## 2026-09-01

### new
- a new thing
- another new thing

### fixed
- a fixed thing

## 2026-08-01

### improved
- an older improvement
"""


# ------------------------------------------------------------- the format ---
def test_it_reads_a_release_into_its_three_groups():
    found = updates._sections(SAMPLE)
    assert [heading for heading, _g in found] == ["2026-09-01", "2026-08-01"]
    _heading, groups = found[0]
    assert groups["new"] == ["a new thing", "another new thing"]
    assert groups["fixed"] == ["a fixed thing"]
    assert groups["improved"] == []


def test_a_group_it_does_not_know_is_ignored_not_guessed():
    """An unknown heading must not silently become one of the three — a
    clinic reading "fixed" has to be reading something somebody filed as
    fixed."""
    found = updates._sections(
        "## r1\n### sideways\n- something\n### new\n- real\n")
    _heading, groups = found[0]
    assert groups["new"] == ["real"]
    assert "sideways" not in groups


def test_a_release_with_nothing_in_it_is_not_listed():
    assert updates._sections("## r1\n\n## r2\n### new\n- x\n") == [
        ("r2", {"new": ["x"], "improved": [], "fixed": []})]


def test_the_file_heading_is_not_mistaken_for_a_release():
    """`#` opens the document, `##` opens a release. A parser that took any
    heading would announce "الجديد في PediaPro" as a version."""
    found = updates._sections("# الجديد في PediaPro\n## r1\n### new\n- x\n")
    assert [heading for heading, _g in found] == ["r1"]


@pytest.mark.parametrize("text", ["", "   ", None, "no headings at all"])
def test_a_file_that_says_nothing_is_no_sections_and_never_a_crash(text):
    assert updates._sections(text) == []


# ------------------------------------------------ only what is not known ----
def test_it_shows_the_releases_this_copy_has_not_got(monkeypatch):
    """The clinic already has the August section; it is about to get the
    September one."""
    monkeypatch.setattr(updates, "_notes_file_at", lambda rev: SAMPLE)
    already = "## 2026-08-01\n### improved\n- an older improvement\n"
    monkeypatch.setattr(updates, "_local_notes", lambda: already)

    found = updates.release_notes("b" * 40)
    assert [rel["heading"] for rel in found] == ["2026-09-01"]
    assert found[0]["new"] == ["a new thing", "another new thing"]


def test_a_clinic_several_releases_behind_sees_all_of_them(monkeypatch):
    """Showing only the newest is how somebody decides an update is smaller
    than it is and puts it off again."""
    monkeypatch.setattr(updates, "_notes_file_at", lambda rev: SAMPLE)
    monkeypatch.setattr(updates, "_local_notes", lambda: "")

    found = updates.release_notes("b" * 40)
    assert [rel["heading"] for rel in found] == ["2026-09-01", "2026-08-01"]


def test_a_copy_that_is_already_current_is_told_nothing(monkeypatch):
    monkeypatch.setattr(updates, "_notes_file_at", lambda rev: SAMPLE)
    monkeypatch.setattr(updates, "_local_notes", lambda: SAMPLE)
    assert updates.release_notes("b" * 40) == []


def test_it_reads_the_new_version_s_file_and_not_this_one_s(monkeypatch):
    """The whole reason it is fetched. The installed copy's file cannot
    describe what the installed copy does not have."""
    asked = {}

    def spy(revision):
        asked["revision"] = revision
        return SAMPLE

    monkeypatch.setattr(updates, "_notes_file_at", spy)
    monkeypatch.setattr(updates, "_local_notes", lambda: "")
    updates.release_notes("b" * 40)
    assert asked["revision"] == "b" * 40


def test_offline_is_no_notes_and_never_a_crash(monkeypatch):
    """The commit subjects are still there — a worse answer and a real one."""
    monkeypatch.setattr(updates, "_notes_file_at", lambda rev: None)
    assert updates.release_notes("b" * 40) == []


def test_no_version_is_no_notes(monkeypatch):
    called = []
    monkeypatch.setattr(updates, "_notes_file_at",
                        lambda rev: called.append(1) or SAMPLE)
    assert updates.release_notes(None) == []
    assert called == [], "it went looking without knowing which version"


# -------------------------------------------------------- the real file -----
def test_the_repository_has_one_and_it_parses():
    """A format nobody can be bothered with is a changelog nobody writes.
    This is the check that ours is still readable by the thing that reads
    it."""
    path = os.path.join(ROOT, updates.NOTES_FILE)
    assert os.path.exists(path), f"{updates.NOTES_FILE} is missing"
    with open(path, encoding="utf-8") as fh:
        found = updates._sections(fh.read())
    assert found, "the notes file has no releases a clinic could be shown"
    _heading, groups = found[0]
    assert any(groups[name] for name in updates.GROUPS)


def test_every_line_in_it_is_filed_under_one_of_the_three():
    """A bullet outside a group is written and never shown, which is worse
    than not writing it."""
    path = os.path.join(ROOT, updates.NOTES_FILE)
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    inside, group, stray, hidden = False, None, [], False
    for raw in lines:
        line = raw.strip()
        # Same skip the parser makes — the file documents its own format
        # inside a comment, example bullets and all.
        if "<!--" in line:
            hidden = True
        if hidden:
            if "-->" in line:
                hidden = False
            continue
        if line.startswith("## ") and not line.startswith("### "):
            inside, group = True, None
        elif line.startswith("### "):
            group = line[4:].strip().lower()
        elif line.startswith("- ") and inside and group not in updates.GROUPS:
            stray.append(line)
    assert not stray, f"lines nobody will ever see: {stray}"


# -------------------------------------------------------------- on screen ---
def test_the_screen_renders_the_three_groups(clinic):
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    for key in ("update.notes_new", "update.notes_improved",
                "update.notes_fixed"):
        assert key not in page, f"untranslated key on the screen: {key}"
    assert "rel.heading" in page
    assert "groups()" in page


def test_the_commit_subjects_are_still_the_fallback(clinic):
    """They appear only when nothing was written. Both at once would be the
    same release described twice."""
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert 'x-show="!groups().length"' in page


def test_the_format_example_in_the_file_is_not_shown_as_a_release():
    """The notes file documents its own format inside a comment, and that
    documentation contains a `##` heading. A parser reading straight through
    would ship that example to every clinic as a version they were about to
    install.

    Ours escaped only by luck: the example writes the three group names on one
    line, which matches no group, so the section came out empty and was
    dropped. A clearer example would have shipped a phantom release."""
    path = os.path.join(ROOT, updates.NOTES_FILE)
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    assert "<!--" in body, "the premise changed — no comment left to skip"

    headings = [heading for heading, _g in updates._sections(body)]
    assert all("<" not in heading for heading in headings), headings

    # And directly: a comment carrying a complete, well-formed release.
    faked = ("<!--\n## PHANTOM\n### new\n- never happened\n-->\n"
             "## real\n### new\n- did happen\n")
    assert [h for h, _g in updates._sections(faked)] == ["real"]
