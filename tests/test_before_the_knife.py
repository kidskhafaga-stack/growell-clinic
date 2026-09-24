"""The assessment before the knife — GAHAR SAS.03.

*"Comprehensive medical and nursing assessment is performed before surgical
and invasive procedures."* Five evidence items: the medical assessment, the
nursing assessment, the investigation results, the identified risks written
down, and action taken on them — every one of them **before** the child goes
in, measured against the moment the program already stamps (`started_at`).

The program had a verdict (fit / with conditions / unfit) with nothing under
it. These tests hold the assessment the verdict was supposed to be made of.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def case(clinic):
    from app.models import Operation, Setting, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        room = Theatre(name="غرفة ١", is_active=True)
        db.session.add(room)
        db.session.flush()
        op = Operation(patient_id=clinic["ids"]["child"], theatre_id=room.id,
                       procedure="استئصال لوز", status="scheduled",
                       on_date=local_today() + timedelta(days=2),
                       surgeon_id=clinic["ids"]["doctor"],
                       workup_needed=False)
        db.session.add(op)
        db.session.commit()
        clinic["ids"]["op"] = op.id
    return clinic


def _op(case, key="op"):
    from app.models import Operation

    return case["db"].session.get(Operation, case["ids"][key])


def _classes(case, *names):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        rows = [pa.add_risk_class(n) for n in names]
        case["db"].session.commit()
        return [r.key for r in rows]


MEDICAL = {"indication": "التهاب لوز متكرر ٧ مرات في السنة",
           "history": "مفيش أمراض، مفيش تخدير قبل كده، مفيش نزيف في العيلة",
           "examination": "لوز متضخمة درجة ٣، الصدر سليم"}


def _medical(case, **extra):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        pa.save(_op(case), "medical", **dict(MEDICAL, **extra))
        case["db"].session.commit()


def _nursing(case, now=None, **extra):
    from app.utils import preop_assessment as pa

    base = {"fasting_food_at": datetime.utcnow() - timedelta(hours=7),
            "fasting_fluid_at": datetime.utcnow() - timedelta(hours=3),
            "weight_kg": 18.4, "vitals": "نبض ١٠٠ · تنفس ٢٢ · ٣٧ · ٩٩٪",
            "allergies_checked": True, "general": "حالة عامة جيدة"}
    base.update(extra)
    with case["app"].app_context():
        pa.save(_op(case), "nursing", now=now, **base)
        case["db"].session.commit()


def _evidence(case):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        return pa.evidence(_op(case))


def _missing(case, kind):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        return pa.missing(_op(case), kind)


# ------------------------------------------------------------- nothing ----
def test_a_new_case_meets_none_of_the_five_but_results(case):
    """The work-up was answered "not needed" at booking — EOC 3 reads that,
    and nothing else is met."""
    ev = _evidence(case)
    assert [ev[n]["met"] for n in (1, 2, 3, 4, 5)] == [False, False, True,
                                                       False, False]
    assert ev[1]["why"] == "none" and ev[4]["why"] == "unasked"


# ------------------------------------------------------------- medical ----
def test_the_medical_assessment_names_what_it_lacks(case):
    _medical(case, history="")
    assert _missing(case, "medical") == ["history", "risk_class", "risks"]


def test_a_risk_class_must_come_from_the_hospitals_list(case):
    """The program chooses no scale. With no list, no class can be picked."""
    from app.utils import preop_assessment as pa

    with case["app"].app_context(), pytest.raises(ValueError):
        pa.save(_op(case), "medical", risk_class="ASA I", **MEDICAL)


def test_a_complete_medical_assessment(case):
    key, = _classes(case, "خطورة منخفضة")
    _medical(case, risk_class=key, risks_none=True)
    assert _missing(case, "medical") == []
    ev = _evidence(case)
    assert ev[1]["met"] and ev[4]["met"] and ev[5]["met"]


def test_no_risks_is_an_answer_silence_is_not(case):
    key, = _classes(case, "خطورة منخفضة")
    _medical(case, risk_class=key)
    assert "risks" in _missing(case, "medical")
    assert _evidence(case)[4] == {"met": False, "why": "unasked"}


# ------------------------------------------------------------- nursing ----
def test_a_complete_nursing_assessment(case):
    _nursing(case)
    assert _missing(case, "nursing") == []
    assert _evidence(case)[2]["met"]


@pytest.mark.parametrize("field, value", [
    ("fasting_food_at", None), ("weight_kg", None), ("vitals", ""),
    ("allergies_checked", None), ("general", "")])
def test_each_nursing_element_is_named_when_missing(case, field, value):
    _nursing(case, **{field: value})
    named = {"fasting_food_at": "fasting", "weight_kg": "weight",
             "vitals": "vitals", "allergies_checked": "allergies",
             "general": "general"}[field]
    assert _missing(case, "nursing") == [named]


def test_not_checked_is_an_answer(case):
    """«ما اتراجعتش» is recorded, and it counts as answered — the gap is
    visible on the page, not hidden as a blank."""
    _nursing(case, allergies_checked=False)
    assert "allergies" not in _missing(case, "nursing")


@pytest.mark.parametrize("extra", [
    {"fasting_food_at": datetime.utcnow() + timedelta(hours=2)},
    {"weight_kg": 0.0}, {"weight_kg": 400.0}])
def test_what_could_not_be_true_is_refused(case, extra):
    with pytest.raises(ValueError):
        _nursing(case, **extra)


# --------------------------------------------------------------- risks ----
def test_a_risk_without_an_action_is_open(case):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        pa.add_risk(_op(case), "أنيميا Hb 8")
        case["db"].session.commit()
    ev = _evidence(case)
    assert ev[4]["met"] is True
    assert ev[5] == {"met": False, "why": "open"}


def test_acting_on_it_closes_it(case):
    from app.models import PreOpRisk
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        pa.add_risk(_op(case), "أنيميا Hb 8")
        case["db"].session.commit()
        pa.act(PreOpRisk.query.one(), "حديد ٣ أسابيع، Hb ١١")
        case["db"].session.commit()
    assert _evidence(case)[5]["met"] is True


def test_naming_a_risk_clears_no_risks(case):
    """"No risks" and a risk cannot both be true."""
    from app.utils import preop_assessment as pa

    key, = _classes(case, "خطورة منخفضة")
    _medical(case, risk_class=key, risks_none=True)
    with case["app"].app_context():
        pa.add_risk(_op(case), "ربو")
        case["db"].session.commit()
        assert pa.get(_op(case), "medical").risks_none is False


def test_no_risks_over_a_list_of_risks_is_refused(case):
    from app.utils import preop_assessment as pa

    with case["app"].app_context():
        pa.add_risk(_op(case), "ربو")
        case["db"].session.commit()
        with pytest.raises(ValueError):
            pa.save(_op(case), "medical", risks_none=True, **MEDICAL)


# ---------------------------------------------------------------- time ----
def test_an_assessment_written_after_the_child_went_in_does_not_count(case):
    """"Before" is the standard's word, measured against `started_at`."""
    with case["app"].app_context():
        op = _op(case)
        op.status, op.started_at = "in_theatre", datetime.utcnow() - timedelta(hours=1)
        case["db"].session.commit()
    _nursing(case)
    assert _evidence(case)[2] == {"met": False, "why": "late"}


def test_one_written_before_does(case):
    _nursing(case, now=datetime.utcnow() - timedelta(hours=2))
    with case["app"].app_context():
        op = _op(case)
        op.status, op.started_at = "in_theatre", datetime.utcnow() - timedelta(hours=1)
        case["db"].session.commit()
    assert _evidence(case)[2]["met"] is True


def test_results_still_waiting_are_not_ready(case):
    with case["app"].app_context():
        op = _op(case)
        op.workup_needed = True
        case["db"].session.commit()
    assert _evidence(case)[3] == {"met": False, "why": "none_named"}


# ----------------------------------------------------------- postponed ----
def test_a_postponed_case_starts_again_from_the_old_words(case):
    """"Reviewed and repeated" — the new booking has no assessment of its
    own; the form opens on the old one's words, and nothing is saved until
    somebody presses save."""
    from app.utils import preop_assessment as pa
    from app.utils import theatres as theatre

    key, = _classes(case, "خطورة منخفضة")
    _medical(case, risk_class=key, risks_none=True)
    with case["app"].app_context():
        new = theatre.postpone(_op(case), _op(case).on_date + timedelta(days=7),
                               reason="برد")
        case["db"].session.commit()
        new_id = new.id
        assert pa.get(new, "medical") is None
        values, source = pa.starting_point(new, "medical")
        assert source == "postponed"
        assert values["indication"] == MEDICAL["indication"]
    page = case["sign_in"]("boss").get(
        f"/theatres/operation/{new_id}").get_data(as_text=True)
    assert "data-assess-postponed" in page
    assert MEDICAL["examination"] in page


# ------------------------------------------------------------- screens ----
def test_saving_from_the_case_screen(case):
    boss = case["sign_in"]("boss")
    op = case["ids"]["op"]
    boss.post(f"/theatres/operation/{op}/assessment/nursing",
              data={"weight_kg": "18.4", "vitals": "نبض ١٠٠",
                    "allergies_checked": "yes", "general": "جيد",
                    "fasting_food_at": "2020-01-01T06:00",
                    "fasting_fluid_at": "2020-01-01T09:00"})
    assert _missing(case, "nursing") == []
    boss.post(f"/theatres/operation/{op}/risk",
              data={"risk": "ربو", "action": "بخاخة قبل العملية"})
    page = boss.get(f"/theatres/operation/{op}").get_data(as_text=True)
    assert 'data-evidence-item="2" data-met="yes"' in page
    assert 'data-managed="yes"' in page


def test_the_preop_list_shows_both_assessments(case):
    page = case["sign_in"]("boss").get("/theatres/preop").get_data(as_text=True)
    assert 'data-assess-state="medical:none"' in page
    assert 'data-assess-state="nursing:none"' in page
    assert "data-risk-classes-empty" in page


def test_only_an_administrator_writes_the_risk_classes(case):
    from app.models import Lookup

    case["sign_in"]("doc").post("/theatres/preop/risk-class", data={"name": "منخفضة"})
    with case["app"].app_context():
        assert Lookup.query.filter_by(domain="surgical_risk_class").count() == 0
    case["sign_in"]("boss").post("/theatres/preop/risk-class", data={"name": "منخفضة"})
    with case["app"].app_context():
        assert Lookup.query.filter_by(domain="surgical_risk_class").count() == 1


def test_what_the_file_knows_is_shown_not_asked(case):
    from app.models import Patient, PatientMedication

    with case["app"].app_context():
        db = case["db"]
        child = db.session.get(Patient, case["ids"]["child"])
        child.allergies = "بنسلين"
        db.session.add(PatientMedication(patient_id=child.id, name="Ventolin"))
        db.session.commit()
    page = case["sign_in"]("boss").get(
        f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert "بنسلين" in page and "Ventolin" in page
