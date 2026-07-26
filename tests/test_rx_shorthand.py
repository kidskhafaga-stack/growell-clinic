"""Writing a prescription the way a doctor writes one.

A paediatrician writes "every eight hours" forty times a day, and by hand it
comes out differently every time. These tests pin the two halves of the fix:
the shorthand doctors already use on paper expands into one settled Arabic
phrasing, and anything that isn't shorthand is handed back exactly as typed —
because a doctor writing a real sentence must never have it rewritten
underneath them.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.rx_shorthand import (  # noqa: E402
    expand_dose, expand_duration, expand_frequency, expand_line,
    parse_frequency)


# ------------------------------------------------------------- frequency --
@pytest.mark.parametrize("written, expected", [
    ("1x3", "كل ٨ ساعات"),
    ("1*2", "كل ١٢ ساعة"),
    ("3x", "كل ٨ ساعات"),          # the × is written on either side
    ("x4", "كل ٦ ساعات"),
    ("q8h", "كل ٨ ساعات"),
    ("q12", "كل ١٢ ساعة"),
    ("كل 8", "كل ٨ ساعات"),
    ("tds", "كل ٨ ساعات"),
    ("bd", "كل ١٢ ساعة"),
    ("od", "مرة واحدة يومياً"),
    ("q24h", "مرة واحدة يومياً"),
    ("prn", "عند اللزوم"),
    ("hs", "قبل النوم"),
])
def test_the_shorthand_a_doctor_already_uses(written, expected):
    assert expand_frequency(written) == expected


def test_the_frequency_keeps_the_number_a_dosing_check_needs(written=None):
    """Free text can't tell a safety check how many times a day a child takes
    something. The parsed form can."""
    assert parse_frequency("1x3")["per_day"] == 3
    assert parse_frequency("bd")["per_day"] == 2
    assert parse_frequency("prn")["per_day"] is None


def test_1x3_carries_the_amount_as_well_as_the_interval():
    """"1x3" means one tablet three times a day — losing the "1" loses half
    of what the doctor wrote."""
    assert parse_frequency("1x3")["amount"] == "قرص"
    assert parse_frequency("2x3")["amount"] == "قرصين"
    assert parse_frequency("5ml*2")["amount"] == "٥ مل"


def test_a_real_sentence_is_never_rewritten():
    """The single most important property. A doctor typing an instruction must
    get back exactly what they typed."""
    for text in ("كل ٨ ساعات بعد الأكل", "مرة صباحاً ومرة مساءً",
                 "حسب تعليمات الطبيب", "once a day with food"):
        assert expand_frequency(text) == text
    assert expand_frequency("") == ""


def test_a_nonsense_interval_is_left_alone():
    """99 times a day is a typo, not a prescription."""
    assert expand_frequency("1x99") == "1x99"
    assert expand_frequency("x0") == "x0"


# -------------------------------------------------------------- duration --
@pytest.mark.parametrize("written, expected", [
    ("1d", "يوم واحد"),
    ("2d", "يومين"),
    ("5d", "٥ أيام"),
    ("11d", "١١ يوم"),          # Arabic counts its nouns in four shapes
    ("1w", "أسبوع"),
    ("2w", "أسبوعين"),
    ("3w", "٣ أسابيع"),
    ("1m", "شهر"),
    ("٥ي", "٥ أيام"),           # typed with Arabic digits
    ("7", "٧ أيام"),            # a bare number means days
])
def test_duration_shorthand(written, expected):
    assert expand_duration(written) == expected


def test_a_written_duration_stays_written():
    assert expand_duration("لمدة أسبوع كامل") == "لمدة أسبوع كامل"
    assert expand_duration("") == ""


# ------------------------------------------------------------------ dose --
@pytest.mark.parametrize("written, expected", [
    ("5ml", "٥ مل"),
    ("2.5ml", "٢.٥ مل"),
    ("1t", "قرص"),
    ("2t", "قرصين"),
    ("1c", "كبسولة"),
    ("10 مل", "١٠ مل"),
    ("2 معلقة", "معلقتين"),
])
def test_dose_shorthand(written, expected):
    assert expand_dose(written) == expected


def test_a_written_dose_stays_written():
    assert expand_dose("نص قرص") == "نص قرص"
    assert expand_dose("حسب الوزن") == "حسب الوزن"


# ------------------------------------------------------------ whole line --
def test_a_whole_line_expands_together():
    line = expand_line({"dose": "", "frequency": "1x3", "duration": "5d"})
    assert line == {"dose": "قرص", "frequency": "كل ٨ ساعات",
                    "duration": "٥ أيام"}


def test_the_amount_never_overwrites_a_dose_the_doctor_wrote():
    line = expand_line({"dose": "نص قرص", "frequency": "1x3", "duration": "5d"})
    assert line["dose"] == "نص قرص"


# ------------------------------------------------------- ready-made sets --
@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, User

        doc = User(username="doc", full_name="د. أ", role="doctor",
                   is_active=True)
        other = User(username="doc2", full_name="د. ب", role="doctor",
                     is_active=True)
        doc.set_password("x")
        other.set_password("x")
        child = Patient(patient_number="R1", full_name="طفل", gender="male",
                        date_of_birth=date(2019, 1, 1))
        db.session.add_all([doc, other, child])
        db.session.commit()
        yield {"app": app, "db": db, "doc": doc, "other": other}


def _preset(clinic, name="نزلة برد", shared=False, owner=None):
    from app.models import RxPreset, RxPresetItem

    row = RxPreset(name=name, doctor_id=(owner or clinic["doc"]).id,
                   is_shared=shared, is_active=True, diagnosis="نزلة برد")
    row.items.append(RxPresetItem(drug_name="Cetal", dose="٥ مل",
                                  frequency="كل ٨ ساعات", duration="٥ أيام"))
    clinic["db"].session.add(row)
    clinic["db"].session.commit()
    return row


def test_a_set_belongs_to_the_doctor_who_made_it(clinic):
    """Two doctors in one clinic rarely treat a cold identically, and one
    quietly inheriting the other's habits is worse than a little duplication."""
    with clinic["app"].app_context():
        preset = _preset(clinic)
        assert preset.visible_to(clinic["doc"]) is True
        assert preset.visible_to(clinic["other"]) is False


def test_a_shared_set_is_everyones(clinic):
    with clinic["app"].app_context():
        preset = _preset(clinic, shared=True)
        assert preset.visible_to(clinic["other"]) is True


def test_a_clinic_wide_set_has_no_owner(clinic):
    from app.models import RxPreset

    with clinic["app"].app_context():
        row = RxPreset(name="بروتوكول العيادة", doctor_id=None, is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        assert row.visible_to(clinic["doc"]) is True
        assert row.visible_to(clinic["other"]) is True


def test_deleting_a_set_takes_its_medicines_with_it(clinic):
    from app.models import RxPresetItem

    with clinic["app"].app_context():
        preset = _preset(clinic)
        clinic["db"].session.delete(preset)
        clinic["db"].session.commit()
        assert RxPresetItem.query.count() == 0
