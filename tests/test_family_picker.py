"""Typing a family name that already exists must not make a second one.

Reported with a live example. A clinic imported "عمر محمد السيد خفاجة" and his
sister "ميرال محمد السيد خفاجه", saw them in two families, and did the obvious
thing: opened each child and set the family name to "Mohammed Khafaga". The
screen went on suggesting each sibling to the other, because typing the name
twice had made **two family records with the same name** rather than putting
both children in one.

The patient form has two ways to say which family a child belongs to: pick an
existing one from the search, or type a new one. Typing is what somebody does
when they want the family *called* something — and it created a record every
time, with no glance at whether that family was already there.

So a typed name is now matched against the register before anything is
created, folded the way every other Arabic name comparison in the program is
folded — "أحمد" and "احمد" are one household, and so are "Mohammed Khafaga"
and "mohammed khafaga".

Note what is *not* here: renaming a family from the family's own edit button
has always renamed in place, and still does. There is a test for it below,
because the question was asked and the answer should not have to be
rediscovered from the source.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _new_patient(client, name, number, family_name="", family_id=""):
    """Create a patient through the form, the way the screen posts it."""
    return client.post("/patients/new", data={
        "full_name": name, "patient_number": number, "gender": "male",
        "date_of_birth": "2020-01-01", "is_active": "1",
        "new_family_name": family_name, "family_id": family_id,
    }, follow_redirects=True)


def _families(clinic):
    from app.models import Family

    return {f.family_name: sorted(p.full_name for p in f.patients)
            for f in Family.query.all()}


# ============================================== the report, reproduced ======
def test_typing_the_same_family_name_twice_makes_one_family(clinic):
    """The live example. Two children, one name typed on each file."""
    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "عمر محمد السيد خفاجة", "P-A", "Mohammed Khafaga")
    _new_patient(boss, "ميرال محمد السيد خفاجه", "P-B", "Mohammed Khafaga")

    with clinic["app"].app_context():
        families = _families(clinic)
        assert len(families) == 1, (
            "one typed name made several family records: " + ", ".join(families))
        assert len(families["Mohammed Khafaga"]) == 2


def test_the_match_ignores_the_spellings_of_one_name(clinic):
    """"أحمد" and "احمد" are one family to every human being, and so are
    "Mohammed" and "mohammed" — this is the same folding the import uses."""
    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "زياد", "P-A", "عائلة أحمد")
    _new_patient(boss, "عمر", "P-B", "عائلة احمد")
    _new_patient(boss, "سلمى", "P-C", "MOHAMMED KHAFAGA")
    _new_patient(boss, "ليلى", "P-D", "mohammed khafaga")

    with clinic["app"].app_context():
        assert len(_families(clinic)) == 2


def test_a_name_nobody_used_before_still_makes_a_family(clinic):
    """Guarding the guard. A fix that stopped creating families would be a
    worse bug than the one being fixed, and harder to see."""
    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "زياد", "P-A", "عائلة السعيد")
    _new_patient(boss, "حسن", "P-B", "عائلة الشناوي")

    with clinic["app"].app_context():
        assert len(_families(clinic)) == 2


def test_two_different_families_are_not_folded_together(clinic):
    """Folding is about spelling, not about meaning. Two households that wrote
    different names must stay apart."""
    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "زياد", "P-A", "محمد السيد")
    _new_patient(boss, "عمر", "P-B", "محمد إبراهيم")

    with clinic["app"].app_context():
        assert len(_families(clinic)) == 2


# ============================================== editing an existing file ====
def test_setting_the_family_on_a_second_child_joins_the_first(clinic):
    """The exact sequence the clinic followed: the family was named on one
    child's file, then the same name typed on the sibling's."""
    from app.models import Patient

    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "عمر محمد السيد خفاجة", "P-A", "Mohammed Khafaga")

    child_id = clinic["ids"]["child"]
    boss.post(f"/patients/{child_id}/edit", data={
        "full_name": "ميرال محمد السيد خفاجه", "patient_number": "P1",
        "gender": "female", "date_of_birth": "2020-06-01", "is_active": "1",
        "new_family_name": "Mohammed Khafaga", "family_id": "",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        db = clinic["db"]
        omar = Patient.query.filter_by(patient_number="P-A").first()
        meral = db.session.get(Patient, child_id)
        assert omar.family_id is not None
        assert omar.family_id == meral.family_id, \
            "the sibling got a second family record with the same name"


# ============================================== renaming, which was fine ====
def test_renaming_a_family_renames_it_rather_than_making_another(clinic):
    """The other half of the question asked: does *editing* the name the
    import chose split anything? It does not, and never did — the family's own
    edit button writes to the record in place, children and all."""
    from app.models import Family, Patient

    boss = clinic["sign_in"]("boss")
    _new_patient(boss, "زياد محمود سعيد", "P-A", "محمود سعيد")
    _new_patient(boss, "عمر محمود سعيد", "P-B", "محمود سعيد")

    with clinic["app"].app_context():
        family_id = Family.query.one().id

    boss.post(f"/patients/families/{family_id}/edit",
              data={"family_name": "عائلة محمود سعيد أحمد"},
              follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Family as F

        assert F.query.count() == 1, "renaming built a second family"
        family = F.query.one()
        assert family.id == family_id, "the children were moved to a new record"
        assert family.family_name == "عائلة محمود سعيد أحمد"
        assert len(family.patients) == 2
        assert all(p.family_id == family_id
                   for p in Patient.query.filter(
                       Patient.patient_number.in_(("P-A", "P-B"))).all())
