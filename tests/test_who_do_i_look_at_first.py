"""Emergency and the incubators — the two departments, over the same base.

Asked for months ago, in the same breath as the repeated readings: *"لازم
مديول الطوارئ والحضانة"*. Both foundations landed first — the readings
(``Observation``) and the place and the stay (``Unit``/``Bed``/``Admission``)
— and this is the layer over them.

**They are not two systems, and that is the thing to hold.** Both screens are
``utils/department.live`` over the same three tables. The plan settled it:
*"الأقسام الأربعة مش أربع أنظمة — دي أربع كثافات ملاحظة فوق نفس الأساس"*. So
most of what is tested here is the ordering — the one question the bed board
cannot answer, which is **who do I look at first** — and then the two things
each department adds: the exit decision in emergency, and the four newborn
facts in the incubators.

The ordering is four clauses, and each one is a real morning:

1. a child nobody has measured since they arrived — invisible on every other
   screen, because an absence leaves no row;
2. a child whose rounds are overdue;
3. a child whose last reading the program reads as urgent;
4. everybody else, longest wait first.

None of those judgements is made in the department code. The flag is
``red_flags``, the lateness is ``observations``, the place is ``beds``. A
department that judged a temperature by its own rule would be a second copy of
the clinic's thresholds — the failure this codebase keeps a whole file to
avoid — so there is a test below that the answer moves when the *clinic's*
threshold moves.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A clinic with an emergency department and an incubator room."""
    from app.models import Setting
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        for module in ("observations", "beds", "emergency", "nicu"):
            Setting.set(f"mod_enabled:{module}", "1")

        made = {}
        for key, kind, space_kind, beds in (
                ("er", "emergency", "partition", ["ط١", "ط٢", "ط٣"]),
                ("nicu", "nicu", "bay", ["س١", "ح١", "ك١"])):
            unit = Unit(name=f"قسم {key}", kind=kind)
            clinic["db"].session.add(unit)
            clinic["db"].session.flush()
            space = Space(unit_id=unit.id, name=f"حيّز {key}", kind=space_kind)
            clinic["db"].session.add(space)
            clinic["db"].session.flush()
            for order, name in enumerate(beds):
                bed = Bed(space_id=space.id, name=name, sort_order=order,
                          kind="incubator" if key == "nicu" and name.startswith("ح")
                          else ("capsule" if name.startswith("ك") else "bed"))
                clinic["db"].session.add(bed)
            made[key] = unit
        clinic["db"].session.commit()
        clinic["units"] = {k: u.id for k, u in made.items()}
        clinic["beds"] = {
            b.name: b.id for b in Bed.query.all()}
    return clinic


def _child(clinic, name, born_days=400, **extra):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"E{name}", full_name=name,
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=born_days),
                        **extra)
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, bed_name, minutes_ago=30, reason=None):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as ward

    with clinic["app"].app_context():
        admission = ward.admit(
            Patient.query.get(patient_id),
            Bed.query.get(clinic["beds"][bed_name]),
            reason=reason,
            when=datetime.utcnow() - timedelta(minutes=minutes_ago))
        clinic["db"].session.commit()
        return admission.id


def _observe(clinic, patient_id, minutes_ago=5, every=15, **readings):
    """A reading, under a running order — which is what makes it late-able."""
    from app.models.observation import Observation, ObservationOrder

    with clinic["app"].app_context():
        order = (ObservationOrder.query
                 .filter_by(patient_id=patient_id, stopped_at=None).first())
        if order is None:
            order = ObservationOrder(
                patient_id=patient_id, every_minutes=every,
                started_at=datetime.utcnow() - timedelta(hours=2))
            clinic["db"].session.add(order)
            clinic["db"].session.flush()
        clinic["db"].session.add(Observation(
            patient_id=patient_id, order_id=order.id,
            taken_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            **readings))
        clinic["db"].session.commit()


# ------------------------------------------------------------ the module ---
@pytest.mark.parametrize("module,path", [("emergency", "/emergency/"),
                                         ("nicu", "/nicu/")])
def test_the_department_is_off_until_a_clinic_says_it_has_one(clinic, module,
                                                              path):
    from app.utils.facility import OPT_IN_MODULES

    assert module in OPT_IN_MODULES
    assert clinic["sign_in"]("boss").get(path).status_code == 404


@pytest.mark.parametrize("capability,module", [("emergency_care", "emergency"),
                                               ("nicu", "nicu")])
def test_the_wizard_switches_it_on_for_a_clinic_that_says_it_runs_one(
        clinic, capability, module):
    """The gate, not just the build. Six times in this project something was
    built and nothing led to it."""
    from app.utils.facility import (apply_facility, derive_modules,
                                    module_enabled)

    assert module in derive_modules([capability])
    with clinic["app"].app_context():
        assert not module_enabled(module)
        apply_facility("hospital", "مستشفى", [capability],
                       derive_modules([capability]))
        clinic["db"].session.commit()
        assert module_enabled(module)
        # And the two foundations come with it — a department that cannot
        # record a second temperature or hold a bed is not a department.
        assert module_enabled("observations") and module_enabled("beds")


def test_the_nurse_can_reach_both_and_reception_cannot(hospital):
    from app.models.permissions import role_modules

    for module in ("emergency", "nicu"):
        assert module in role_modules("nursing")
        assert module in role_modules("doctor")
        assert module not in role_modules("reception")


def test_a_department_with_nothing_built_says_so(hospital):
    """Rule one, in its most literal form: an empty screen reads as a module
    that does not work. It names what to build and links to where."""
    from app.i18n import t
    from app.models.place import Unit

    with hospital["app"].app_context():
        Unit.query.filter_by(kind="emergency").delete()
        hospital["db"].session.commit()
        sentence = None

    with hospital["app"].test_request_context("/"):
        sentence = t("dept.no_unit_emergency")

    page = hospital["sign_in"]("boss").get("/emergency/").get_data(as_text=True)
    assert sentence in page
    assert "/beds/setup" in page


# --------------------------------------------------------- who comes first --
def test_a_child_nobody_has_measured_comes_before_everybody(hospital):
    """The one an absence hides. No row is written when a reading is *not*
    taken, so this child is invisible on every screen that lists readings —
    and they are the child to see first."""
    from app.utils import department

    seen = _child(hospital, "مقيس")
    unseen = _child(hospital, "مش مقيس")
    _admit(hospital, seen, "ط١", minutes_ago=90)
    _admit(hospital, unseen, "ط٢", minutes_ago=10)
    _observe(hospital, seen, minutes_ago=2, temperature_c=37.0)

    with hospital["app"].app_context():
        rows = department.live("emergency")
        assert [r["patient"].id for r in rows] == [unseen, seen]
        assert rows[0]["level"] == department.UNSEEN


def test_an_overdue_round_comes_before_a_child_who_is_merely_unwell(hospital):
    from app.utils import department

    late = _child(hospital, "متأخرة")
    warm = _child(hospital, "سخنة")
    _admit(hospital, late, "ط١", minutes_ago=200)
    _admit(hospital, warm, "ط٢", minutes_ago=200)
    # Measured two hours ago on quarter-hourly rounds: overdue.
    _observe(hospital, late, minutes_ago=120, every=15, temperature_c=37.0)
    _observe(hospital, warm, minutes_ago=2, every=15, temperature_c=38.6)

    with hospital["app"].app_context():
        rows = department.live("emergency")
        assert rows[0]["patient"].id == late
        assert rows[0]["level"] == department.LATE
        assert rows[1]["level"] in (department.URGENT, department.WATCH)


def test_the_urgent_reading_comes_before_the_steady_one(hospital):
    from app.utils import department

    sick = _child(hospital, "حالة")
    fine = _child(hospital, "مستقرة")
    _admit(hospital, sick, "ط١", minutes_ago=20)
    _admit(hospital, fine, "ط٢", minutes_ago=200)
    _observe(hospital, sick, minutes_ago=1, every=60, spo2=88)
    _observe(hospital, fine, minutes_ago=1, every=60, spo2=99)

    with hospital["app"].app_context():
        rows = department.live("emergency")
        assert [r["patient"].id for r in rows] == [sick, fine]
        assert rows[0]["level"] == department.URGENT
        assert rows[1]["level"] == department.STEADY


def test_two_children_at_the_same_level_are_longest_wait_first(hospital):
    from app.utils import department

    early = _child(hospital, "الأقدم")
    later = _child(hospital, "الأحدث")
    _admit(hospital, early, "ط١", minutes_ago=300)
    _admit(hospital, later, "ط٢", minutes_ago=15)
    for who in (early, later):
        _observe(hospital, who, minutes_ago=1, every=60, temperature_c=37.0)

    with hospital["app"].app_context():
        rows = department.live("emergency")
        assert [r["patient"].id for r in rows] == [early, later]


def test_the_urgency_is_the_clinics_own_and_not_a_second_copy(hospital):
    """The rule this whole file is careful about. A clinic that lowers its own
    fever limit changes what the department reads as urgent — because the
    department asks `red_flags`, which asks the clinic's settings."""
    from app.models import Setting
    from app.utils import department

    child = _child(hospital, "حرارة")
    _admit(hospital, child, "ط١", minutes_ago=20)
    _observe(hospital, child, minutes_ago=1, every=60, temperature_c=38.2)

    with hospital["app"].app_context():
        assert department.live("emergency")[0]["level"] != department.URGENT
        # The clinic decides 38.0 is urgent for this age band.
        for index in range(4):
            Setting.set(f"triage_urgent_{index}", "38.0")
        hospital["db"].session.commit()
        assert department.live("emergency")[0]["level"] == department.URGENT


def test_a_discharged_child_leaves_the_department(hospital):
    from app.models.admission import Admission
    from app.utils import beds as ward
    from app.utils import department

    child = _child(hospital, "خرج")
    admission_id = _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        assert len(department.live("emergency")) == 1
        ward.discharge(Admission.query.get(admission_id), "home")
        hospital["db"].session.commit()
        assert department.live("emergency") == []


def test_a_closed_stay_and_an_open_bed_row_still_reads_as_gone(hospital):
    """Both halves are asked, and this is why.

    A discharge closes the admission *and* the bed stay, so either condition
    alone would look sufficient — which is how a redundant filter survives a
    mutation and hides the day the two drift apart. If anything ever closes
    the admission and leaves the bed row open, the child is gone and the
    department must say so rather than showing a bed nobody is in.
    """
    from app.models.admission import Admission
    from app.utils import department
    from datetime import datetime as _dt

    child = _child(hospital, "متضارب")
    admission_id = _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        row = Admission.query.get(admission_id)
        row.discharged_at = _dt.utcnow()      # closed, and the stay left open
        row.outcome = "home"
        hospital["db"].session.commit()
        assert department.live("emergency") == []


def test_each_department_shows_only_its_own_children(hospital):
    from app.utils import department

    in_er = _child(hospital, "طوارئ")
    in_nicu = _child(hospital, "حضّانة", born_days=2)
    _admit(hospital, in_er, "ط١")
    _admit(hospital, in_nicu, "ح١")

    with hospital["app"].app_context():
        assert [r["patient"].id for r in department.live("emergency")] == [in_er]
        assert [r["patient"].id for r in department.live("nicu")] == [in_nicu]


# ----------------------------------------------------------- the exit ------
def test_sending_a_child_home_closes_the_stay_with_its_outcome(hospital):
    from app.models.admission import Admission

    child = _child(hospital, "للبيت")
    admission_id = _admit(hospital, child, "ط١")

    hospital["sign_in"]("boss").post(
        f"/emergency/decide/{admission_id}",
        data={"outcome": "home", "note": "اتحسن"}, follow_redirects=True)

    with hospital["app"].app_context():
        row = Admission.query.get(admission_id)
        assert not row.is_open
        assert row.outcome == "home"
        assert row.discharge_note == "اتحسن"


def test_admitting_upstairs_moves_the_child_and_keeps_one_stay(hospital):
    """The decision that is a move and not a discharge. A discharge followed
    by an admission would put two stays on one continuous piece of care, and
    the second one would start at the moment somebody pressed a button."""
    from app.models.admission import Admission

    child = _child(hospital, "تنويم")
    admission_id = _admit(hospital, child, "ط١")

    hospital["sign_in"]("boss").post(
        f"/emergency/decide/{admission_id}",
        data={"outcome": "admitted", "bed_id": hospital["beds"]["س١"]},
        follow_redirects=True)

    with hospital["app"].app_context():
        row = Admission.query.get(admission_id)
        assert row.is_open, "the stay was closed instead of moved"
        assert row.bed.name == "س١"
        assert len(row.stays) == 2
        assert row.stays[0].until is not None
        assert Admission.query.count() == 1


def test_a_child_admitted_upstairs_leaves_the_emergency_board(hospital):
    from app.utils import department

    child = _child(hospital, "طلع فوق")
    admission_id = _admit(hospital, child, "ط١")
    hospital["sign_in"]("boss").post(
        f"/emergency/decide/{admission_id}",
        data={"outcome": "admitted", "bed_id": hospital["beds"]["س١"]},
        follow_redirects=True)

    with hospital["app"].app_context():
        assert department.live("emergency") == []
        assert len(department.live("nicu")) == 1


def test_the_bed_upstairs_is_re_checked_before_the_move(hospital):
    """The screen's list of free beds was drawn seconds ago, and a ward fills
    up between a page loading and a button being pressed."""
    from app.models.admission import Admission

    first = _child(hospital, "الأول")
    second = _child(hospital, "التاني")
    _admit(hospital, first, "س١")               # already upstairs in that bed
    admission_id = _admit(hospital, second, "ط١")

    from app.i18n import t

    reply = hospital["sign_in"]("boss").post(
        f"/emergency/decide/{admission_id}",
        data={"outcome": "admitted", "bed_id": hospital["beds"]["س١"]},
        follow_redirects=True)

    with hospital["app"].app_context():
        row = Admission.query.get(admission_id)
        assert row.bed.name == "ط١", "two children were put in one bed"

    # And the person who pressed it is told. The refusal is `beds.move`'s, so
    # a handler that swallowed it would leave the screen saying the child went
    # upstairs while they are still in the corridor — which is worse than the
    # error, and is what the first version of this test could not tell apart.
    with hospital["app"].test_request_context("/"):
        refused, moved = t("beds.refused_occupied"), t("emergency.admitted_upstairs")
    body = reply.get_data(as_text=True)
    assert refused in body and moved not in body


# ------------------------------------------------------- the incubators ----
def test_the_incubators_show_what_no_other_department_needs(hospital):
    from app.utils import department

    baby = _child(hospital, "مولود", born_days=2,
                  gestation_weeks=36, birth_weight_kg=2.4,
                  birth_time=time(9, 0))
    _admit(hospital, baby, "ح١")

    with hospital["app"].app_context():
        row = department.live("nicu")[0]
        extras = row["newborn"]
        assert extras is not None
        assert extras["weeks"] == 36
        assert extras["birth_weight"] == 2.4
        assert extras["hours"] and extras["hours"] > 24


def test_emergency_carries_no_newborn_block(hospital):
    """It is asked for only where it means something. A gestation beside a
    nine-year-old in emergency is noise on a screen read at a glance."""
    from app.utils import department

    child = _child(hospital, "كبير")
    _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        assert department.live("emergency")[0]["newborn"] is None


def test_the_last_weight_comes_from_the_growth_curve(hospital):
    """Not from a reading. A daily weight in an incubator *is* growth, and a
    second copy of it on a rounds row would be free to disagree with the
    child's own chart in the same file."""
    from app.models import GrowthRecord
    from app.utils import department
    from app.utils.clock import local_today

    baby = _child(hospital, "وزن", born_days=3, gestation_weeks=34)
    _admit(hospital, baby, "ح١")
    with hospital["app"].app_context():
        hospital["db"].session.add(GrowthRecord(
            patient_id=baby, record_date=local_today(), weight_kg=2.15))
        hospital["db"].session.commit()

        assert department.live("nicu")[0]["newborn"]["weight"] == 2.15


def test_the_bilirubin_is_judged_against_this_babys_own_threshold(hospital):
    """The join that did not exist. The calculator has been here since the
    newborn plan's Phase 4 and the lab result longer, and a nurse was reading
    the number off one screen and doing the comparison in their head."""
    from app.models import Investigation, Setting, Visit, VisitInvestigation
    from app.utils import department

    baby = _child(hospital, "صفراء", born_days=3, gestation_weeks=38,
                  birth_time=time(8, 0))
    _admit(hospital, baby, "ح١")

    with hospital["app"].app_context():
        # The table is shut until a clinician accepts it — and it must stay
        # shut, so this says yes the way the settings screen does.
        Setting.set("jaundice_table_confirmed", "1")
        Setting.set("facility_capabilities",
                    '["general_consultation", "newborn_care"]')
        test = Investigation(code="bilirubin", name_ar="بيليروبين",
                             kind="lab", is_active=True)
        visit = Visit(patient_id=baby, doctor_id=hospital["ids"]["doctor"])
        hospital["db"].session.add_all([test, visit])
        hospital["db"].session.flush()
        hospital["db"].session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=baby, investigation_id=test.id,
            kind="lab", name="بيليروبين", result_value=19.5,
            resulted_at=datetime.utcnow(), status="resulted"))
        hospital["db"].session.commit()

        verdict = department.live("nicu")[0]["newborn"]["jaundice"]
        assert verdict is not None and verdict["ok"], verdict
        assert verdict["points_at"] in ("phototherapy", "exchange")


def test_no_bilirubin_means_no_verdict_rather_than_a_guess(hospital):
    from app.utils import department

    baby = _child(hospital, "بدون تحليل", born_days=2, gestation_weeks=37)
    _admit(hospital, baby, "ح١")

    with hospital["app"].app_context():
        assert department.live("nicu")[0]["newborn"]["jaundice"] is None


# ------------------------------------------------------------ the screen ---
def test_the_board_shows_the_children_in_order(hospital):
    unseen = _child(hospital, "محدش قاسه")
    steady = _child(hospital, "مستقر")
    _admit(hospital, steady, "ط١", minutes_ago=200)
    _admit(hospital, unseen, "ط٢", minutes_ago=5)
    _observe(hospital, steady, minutes_ago=1, every=60, temperature_c=37.0)

    page = hospital["sign_in"]("boss").get("/emergency/").get_data(as_text=True)
    assert 'data-level="unseen"' in page
    assert page.index("محدش قاسه") < page.index("مستقر")


def test_the_department_does_not_ask_once_per_child(hospital):
    """A full department is the normal case, not the exception. Twenty
    children cost what two cost."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.models.place import Bed, Space
    from app.utils import department

    with hospital["app"].app_context():
        space = Space.query.join(Space.unit).filter_by(kind="emergency").first()
        for i in range(20):
            bed = Bed(space_id=space.id, name=f"ط{i + 10}", sort_order=i + 10)
            hospital["db"].session.add(bed)
        hospital["db"].session.commit()
        hospital["beds"] = {b.name: b.id for b in Bed.query.all()}

    def cost():
        seen = []

        def record(conn, cursor, statement, params, context, many):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            with hospital["app"].app_context():
                rows = department.live("emergency")
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        return len(rows), len(seen)

    for i in range(4):
        who = _child(hospital, f"طفل{i}")
        _admit(hospital, who, f"ط{i + 10}")
        _observe(hospital, who, minutes_ago=1, every=60, temperature_c=37.0)
    cost()                                  # warm the settings cache
    few_rows, few = cost()

    for i in range(4, 20):
        who = _child(hospital, f"طفل{i}")
        _admit(hospital, who, f"ط{i + 10}")
        _observe(hospital, who, minutes_ago=1, every=60, temperature_c=37.0)
    many_rows, many = cost()

    assert (few_rows, many_rows) == (4, 20)
    assert many == few, (
        f"{few} queries for 4 children and {many} for 20 — something is "
        "querying inside the loop")
