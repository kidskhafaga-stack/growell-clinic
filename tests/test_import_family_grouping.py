"""One household, one family — however much of the name anybody wrote down.

Reported from a real import: *every patient ends up under a different family
name*. The import derived a guardian from each child's own name and grouped by
that string, and two entirely ordinary things break it.

**Different lengths.** Egyptian names run child → father → grandfather →
family, and a clinic's sheet records as many as whoever filled it in knew.
"زياد محمود سعيد أحمد" and "عمر محمود سعيد" are brothers; the derivation gives
"محمود سعيد أحمد" and "محمود سعيد", which are two different strings and became
two different families.

**Spelling.** "أحمد" and "احمد" are one name to every human being and two
strings to a computer. A third sibling typed on a keyboard without the hamza
became a third family.

The fix keys on a *fixed* number of leading words of the guardian's name,
folded — the father and the grandfather, which are the same in every recording
of the same household. What gets *stored* is still the fullest name anybody
wrote, because that is what somebody has to read on a screen.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _row(name, gender="male", dob="2020-01-01", **extra):
    row = {"full_name": name, "gender": gender, "date_of_birth": dob}
    row.update(extra)
    return row


def _import(clinic, rows):
    from app.blueprints.patients.routes import _process_import

    result = _process_import(rows)
    clinic["db"].session.commit()
    return result


def _families(clinic):
    from app.models import Family

    return {f.family_name: sorted(p.full_name for p in f.patients)
            for f in Family.query.all()}


# ============================================== the report, reproduced ======
def test_siblings_recorded_at_different_lengths_are_one_family(clinic):
    """The first half of the bug. One sheet, one household, three spellings of
    how far down the ancestry somebody bothered to write."""
    with clinic["app"].app_context():
        _import(clinic, [
            _row("زياد محمود سعيد أحمد"),
            _row("عمر محمود سعيد"),
            _row("مريم محمود سعيد احمد", gender="female"),
        ])
        families = _families(clinic)

        assert len(families) == 1, (
            "one household was split across several families: "
            + ", ".join(families))
        assert len(next(iter(families.values()))) == 3


def test_the_hamza_does_not_split_a_household(clinic):
    """"أحمد" and "احمد" are the same name. Whichever keyboard the typist had
    must not decide which family a child belongs to."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود أحمد"), _row("عمر محمود احمد")])
        assert len(_families(clinic)) == 1


def test_unrelated_children_still_get_their_own_family(clinic):
    """Guarding the guard: a fix that merged everybody would be worse than the
    bug, and much harder to notice."""
    with clinic["app"].app_context():
        _import(clinic, [
            _row("زياد محمود سعيد"),
            _row("حسن إبراهيم علي"),
        ])
        assert len(_families(clinic)) == 2


def test_two_fathers_sharing_a_first_name_are_not_merged(clinic):
    """"محمد" is a quarter of Egypt. The key is father *and* grandfather for
    exactly this reason — one word would have merged half the register."""
    with clinic["app"].app_context():
        _import(clinic, [
            _row("زياد محمد سعيد"),
            _row("عمر محمد إبراهيم"),
        ])
        assert len(_families(clinic)) == 2


# ============================================== and next month's import =====
def test_a_later_import_joins_the_family_the_first_one_made(clinic):
    """Clinics import in batches, months apart. Matching only within one file
    would build a parallel family beside the existing one every time — the
    same bug, arriving more slowly."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود سعيد أحمد")])
        _import(clinic, [_row("سلمى محمود سعيد", gender="female")])

        families = _families(clinic)
        assert len(families) == 1
        assert len(next(iter(families.values()))) == 2


def test_a_family_created_by_hand_is_joined_too(clinic):
    """The receptionist who typed a family last week did not use the import's
    wording, and should not end up with a duplicate because of it."""
    from app.models import Family

    db = clinic["db"]
    with clinic["app"].app_context():
        db.session.add(Family(family_name="محمود سعيد"))
        db.session.commit()

        _import(clinic, [_row("زياد محمود سعيد أحمد")])
        assert Family.query.count() == 1


# ============================================== what gets shown =============
def test_the_family_keeps_the_fullest_name_anybody_wrote(clinic):
    """The short key is for matching. A screen reading "محمود سعيد" when the
    sheet said "محمود سعيد أحمد" has thrown away a name for no reason."""
    with clinic["app"].app_context():
        _import(clinic, [
            _row("عمر محمود سعيد"),                 # the shorter one first
            _row("زياد محمود سعيد أحمد"),
        ])
        assert list(_families(clinic)) == ["محمود سعيد أحمد"]


def test_an_explicit_family_name_still_wins(clinic):
    """A sheet that names the family is stating a fact, not offering a hint,
    and nothing derived should override it."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود سعيد", family_name="عائلة الصعيدي")])
        assert "عائلة الصعيدي" in _families(clinic)


def test_a_shared_phone_still_groups_siblings(clinic):
    """The rule that was already there and must keep working: two children
    with different-looking names and one guardian phone are siblings."""
    with clinic["app"].app_context():
        _import(clinic, [
            _row("زياد محمود", parent_phone="01001234567"),
            _row("عمر محمود", parent_phone="01001234567"),
        ])
        assert len(_families(clinic)) == 1


def test_a_child_with_only_one_name_gets_no_family(clinic):
    """Nothing to derive a household from. Inventing one would make a family
    per single-named child, which is the bug in a different disguise."""
    from app.models import Family

    with clinic["app"].app_context():
        _import(clinic, [_row("زياد")])
        assert Family.query.count() == 0
