"""A week in a bed ended with less written down than an hour in recovery.

GAHAR **ACT.15** — *"Discharge summaries are complete"* — calls the discharge
summary **a legal document** and names nine things it must contain:

    a) reason for hospitalization · b) provisional and/or final diagnosis ·
    c) investigations · d) significant findings · e) procedures performed ·
    f) medications (before/during) · g) condition and disposition at
    discharge · h) discharge instructions, including diet, medications and
    follow-up · i) name of the medical staff member who discharged the patient

What the program had was ``Admission.discharge_note`` — one free text box —
and ``outcome``, one word out of four. Meanwhile a day case leaving recovery
**cannot** be discharged without a follow-up decision, because
``recovery.discharge`` refuses one. The child who stayed a week had the weaker
record.

The design this suite pins:

* **Six boxes, not nine.** The reason, the procedures, the drug orders and the
  name of whoever discharged the child are already in the record, and the
  program reads them rather than asking a doctor to type them again. A second
  copy of a fact is a second answer that drifts.
* **The absence is a row that does not exist**, so a stay from before this
  existed reads as *unwritten* rather than as a summary somebody left blank.
* **Three instruction boxes, because the standard names three.** One box lets
  a doctor write about the medicines only while the program records element
  (h) as done — the false green tick this codebase keeps removing.
* **Condition is not disposition.** ``outcome`` says home or transferred;
  element (g) also asks how the child was.
* **Handing a copy over is its own stamp** (evidence 4): nobody gave it is not
  the same fact as nobody wrote it.
* **Nothing refuses a discharge.** Refusing to record that a child went home
  because the paperwork is unfinished would leave them in a bed for ever in
  the program's telling — the argument ``theatres.finish`` already settled.
* **The delay is measured, never graded.** The standard asks for *"an approved
  timeframe"* and names no number, so neither does the program.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.place import Bed, Space, Unit
        from app.utils.clock import local_today

        Setting.set("mod_enabled:beds", "1")
        Setting.set("mod_enabled:theatres", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        unit = Unit(name="العنبر", kind="ward")
        db.session.add_all([boss, unit])
        db.session.flush()
        space = Space(unit_id=unit.id, name="أوضة ١")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير ١")
        db.session.add(bed)
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.commit()
        ids = {"boss": boss.id, "kid": kid.id, "bed": bed.id}

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _stay(ctx, discharge=True, reason="التهاب رئوي"):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as beds_util

    row = beds_util.admit(ctx["db"].session.get(Patient, ctx["ids"]["kid"]),
                          ctx["db"].session.get(Bed, ctx["ids"]["bed"]),
                          user=_boss(ctx), reason=reason,
                          when=datetime.utcnow() - timedelta(days=3))
    ctx["db"].session.commit()
    if discharge:
        beds_util.discharge(row, "home", user=_boss(ctx), note="خرج")
        ctx["db"].session.commit()
    return row


def _filled(html, letter):
    """Whether the ward screen shows element ``letter`` as answered."""
    import re

    marker = 'data-element="%s"' % letter
    assert marker in html, "element %s is not on the screen" % letter
    after = html.split(marker, 1)[1]
    found = re.search(r'data-filled="(yes|no)"', after)
    assert found, "element %s has no filled state" % letter
    return found.group(1)


def _section(html, letter):
    """One lettered section of the printed copy, and nothing else on it.

    Asserting over the whole sheet is how three mutants survived: a page with
    nine elements on it carries «nobody wrote» somewhere whatever happens to
    element (d), and the doctor's name is in the page header as well as under
    element (i).
    """
    marker = "%s) " % letter
    assert marker in html, "element %s is not on the sheet" % letter
    rest = html.split(marker, 1)[1]
    return rest.split("</section>", 1)[0]


FULL = {"diagnosis": "التهاب رئوي فصّي", "findings": "ارتشاح في الفص السفلي",
        "condition": "متحسّن، بيتنفس عادي", "diet": "أكل عادي",
        "medicines": "أموكسيسيللين ٧ أيام", "followup": "بعد أسبوع"}


# ------------------------------------------------------ the absence -------
def test_a_stay_with_no_summary_says_so_rather_than_showing_a_blank_one(ward):
    """**The whole reason it is a row.** Columns on the stay would give every
    stay in the clinic's history a blank summary indistinguishable from one
    nobody wrote."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        assert ds.for_admission(stay) is None
        assert ds.state(stay) == "none"
        assert ds.state(None) == "none"


def test_nothing_written_means_every_element_is_missing(ward):
    from app.models.discharge_summary import DischargeSummary
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        assert ds.missing(stay) == list(DischargeSummary.WRITTEN)


def test_a_discharge_is_never_refused_for_a_missing_summary(ward):
    """Refusing to record that a child went home because the paperwork is not
    finished would leave them in a bed for ever in the program's telling."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        assert not stay.is_open
        assert stay.discharged_at is not None
        assert ds.state(stay) == "none"       # and it says so, loudly


# ------------------------------------------------------ writing it --------
def test_a_summary_with_every_element_written_is_complete(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        assert ds.state(stay) == "complete"
        assert ds.missing(stay) == []


def test_a_summary_missing_one_element_is_short_not_complete(ward):
    """Named «short» like the checklist's signed-short stop: a word that
    sounded finished is exactly how a blank element gets past somebody."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **dict(FULL, condition=""))
        ward["db"].session.commit()
        assert ds.state(stay) == "short"
        assert ds.missing(stay) == ["condition"]


def test_the_three_instruction_boxes_are_three(ward):
    """The standard names diet, medications and follow-up. One box lets a
    doctor write about the medicines only while the program records element
    (h) as done."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward),
                 **dict(FULL, diet="", followup=""))
        ward["db"].session.commit()
        assert set(ds.missing(stay)) == {"diet", "followup"}
        # And element (h) is answered only when all three are.
        h = next(e for e in ds.assemble(stay) if e["letter"] == "h")
        assert h["filled"] is False


def test_whitespace_typed_into_a_box_is_not_an_answer(ward):
    """A space bar is how a required box gets past a program that checks for
    emptiness the lazy way. ``write`` strips it to ``None`` on the way in."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **dict(FULL, findings="   "))
        ward["db"].session.commit()
        assert ds.for_admission(stay).findings is None
        assert ds.missing(stay) == ["findings"]


def test_whitespace_already_in_the_record_is_not_an_answer_either(ward):
    """The second half of the same rule, and it needs its own test because
    ``write`` strips on the way in — so nothing that goes through the screen
    can ever reach ``blanks`` with spaces in it. A row imported from
    elsewhere, or written straight to the table, can."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        row = ds.for_admission(stay)
        row.condition = "  \n "
        ward["db"].session.commit()
        assert ds.missing(stay) == ["condition"]
        assert ds.state(stay) == "short"


def test_correcting_a_summary_edits_the_one_that_exists(ward):
    """One stay, one summary. A second row would be a second legal document
    about the same discharge and nothing could say which the family got."""
    from app.models.discharge_summary import DischargeSummary
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        ds.write(stay, user=_boss(ward), diagnosis="تشخيص متعدّل")
        ward["db"].session.commit()
        assert DischargeSummary.query.count() == 1
        row = ds.for_admission(stay)
        assert row.diagnosis == "تشخيص متعدّل"
        # And the elements nobody touched are still there.
        assert row.findings == FULL["findings"]


def test_a_summary_can_be_begun_while_the_child_is_still_in(ward):
    """The standard's own complaint is about summaries written too late, so a
    summary begun early is the good case and is not refused."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward, discharge=False)
        assert stay.is_open
        assert ds.write(stay, user=_boss(ward), **FULL) is not None
        ward["db"].session.commit()
        assert ds.state(stay) == "complete"


def test_writing_against_no_stay_is_refused(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        assert ds.write(None, user=_boss(ward), **FULL) is None


def test_a_caller_cannot_move_a_summary_to_another_stay(ward):
    """Only the six written columns are accepted, so a stray keyword cannot
    set the stamps or re-point the document."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        # `given_at` rather than only `admission_id`: the row is built through
        # the relationship, so SQLAlchemy re-syncs the foreign key from it on
        # flush and a mutant that wrote every keyword would still pass that
        # assertion. A stamp is not re-synced by anything.
        row = ds.write(stay, user=_boss(ward), admission_id=99,
                       given_at=datetime(2020, 1, 1, 9, 0), **FULL)
        ward["db"].session.commit()
        assert row.admission_id == stay.id
        assert row.given_at is None
        assert row.given is False


# ------------------------------------------- what the record answers ------
def test_the_elements_the_record_already_holds_are_not_asked_for(ward):
    """«المهم الطبيب ميكتبش كتير». Four of the nine are in the record: the
    reason, the investigations, the procedures, the drugs and the name of
    whoever discharged the child."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        written = {e["key"] for e in ds.assemble(stay) if e["written"]}
        derived = {e["key"] for e in ds.assemble(stay) if not e["written"]}
        assert written == {"diagnosis", "findings", "condition", "instructions"}
        assert derived == {"reason", "investigations", "procedures",
                           "medications", "discharged_by"}


def test_all_nine_elements_are_there_in_the_standards_order(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        letters = [e["letter"] for e in ds.assemble(_stay(ward))]
        assert letters == list("abcdefghi")


def test_the_reason_and_the_name_come_off_the_stay(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward, reason="التهاب رئوي")
        filled = {e["key"]: e["filled"] for e in ds.assemble(stay)}
        assert filled["reason"] is True
        assert filled["discharged_by"] is True


def test_a_stay_admitted_with_no_reason_says_that_element_is_empty(ward):
    """Derived does not mean assumed: an element the record does not answer
    is shown as unanswered rather than ticked because it was derivable."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward, reason="")
        filled = {e["key"]: e["filled"] for e in ds.assemble(stay)}
        assert filled["reason"] is False


def test_the_operations_of_the_stay_answer_element_e(ward):
    from app.models.theatre import Operation, Theatre
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        stay = _stay(ward)
        room = Theatre(name="غرفة ١")
        ward["db"].session.add(room)
        ward["db"].session.flush()
        ward["db"].session.add(
            Operation(patient_id=ward["ids"]["kid"], theatre_id=room.id,
                      procedure="استئصال زائدة", on_date=local_today(),
                      admission_id=stay.id, status="done"))
        ward["db"].session.commit()

        assert [op.procedure for op in ds.procedures_during(stay)] == \
            ["استئصال زائدة"]
        filled = {e["key"]: e["filled"] for e in ds.assemble(stay)}
        assert filled["procedures"] is True


def test_an_operation_from_another_stay_is_not_on_this_summary(ward):
    from app.models.theatre import Operation, Theatre
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        stay = _stay(ward)
        room = Theatre(name="غرفة ١")
        ward["db"].session.add(room)
        ward["db"].session.flush()
        # A day case, no stay behind it at all.
        ward["db"].session.add(
            Operation(patient_id=ward["ids"]["kid"], theatre_id=room.id,
                      procedure="ختان", on_date=local_today(), status="done"))
        ward["db"].session.commit()
        assert ds.procedures_during(stay) == []


def test_the_drugs_ordered_on_the_stay_answer_element_f(ward):
    from app.models.medication import MedicationOrder
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ward["db"].session.add(
            MedicationOrder(admission_id=stay.id, patient_id=ward["ids"]["kid"],
                            drug_name="أموكسيسيللين", dose="٢٥٠ مجم",
                            route="oral", every_hours=8))
        ward["db"].session.commit()
        assert [m.drug_name for m in ds.medicines_during(stay)] == \
            ["أموكسيسيللين"]


def test_what_the_child_arrived_taking_is_its_own_half_of_element_f(ward):
    """The standard writes «medications (before/during)» as two things, and
    what the child came in on is the half nobody records anywhere else."""
    from app.models.patient_medication import PatientMedication
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_date

    with ward["app"].app_context():
        stay = _stay(ward)
        day = local_date(stay.admitted_at)
        ward["db"].session.add_all([
            PatientMedication(patient_id=ward["ids"]["kid"], name="فنتولين",
                              started_on=day - timedelta(days=100)),
            # Stopped before this stay began — not what they arrived on.
            PatientMedication(patient_id=ward["ids"]["kid"], name="دوا قديم",
                              started_on=day - timedelta(days=200),
                              stopped_on=day - timedelta(days=10)),
            # Started after they came in — not what they arrived on either.
            PatientMedication(patient_id=ward["ids"]["kid"], name="دوا جديد",
                              started_on=day + timedelta(days=30)),
        ])
        ward["db"].session.commit()
        assert [m.name for m in ds.medicines_before(stay)] == ["فنتولين"]


def test_the_investigations_of_the_stay_are_the_ones_in_its_window(ward):
    """``VisitInvestigation`` hangs off a visit and there is no admission on
    it, so the episode is the window — which is what a discharge summary means
    by «investigations» whichever door the order came through."""
    from app.models.visit import Visit, VisitInvestigation
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        stay = _stay(ward)
        visit = Visit(patient_id=ward["ids"]["kid"],
                      doctor_id=ward["ids"]["boss"], visit_date=local_today())
        ward["db"].session.add(visit)
        ward["db"].session.flush()
        during = VisitInvestigation(
            visit_id=visit.id, patient_id=ward["ids"]["kid"], name="صورة دم",
            created_at=stay.admitted_at + timedelta(hours=4))
        before = VisitInvestigation(
            visit_id=visit.id, patient_id=ward["ids"]["kid"], name="تحليل قديم",
            created_at=stay.admitted_at - timedelta(days=30))
        after = VisitInvestigation(
            visit_id=visit.id, patient_id=ward["ids"]["kid"], name="تحليل بعدين",
            created_at=stay.discharged_at + timedelta(days=5))
        ward["db"].session.add_all([during, before, after])
        ward["db"].session.commit()

        assert [r.name for r in ds.investigations_during(stay)] == ["صورة دم"]


def test_the_provisional_diagnosis_is_offered_and_never_stored_as_the_final(ward):
    """Two facts decided at two moments on two amounts of evidence. A stay
    that changed the answer has to be able to say so."""
    from app.models.diagnosis import Diagnosis
    from app.models.visit import Visit
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        visit = Visit(patient_id=ward["ids"]["kid"],
                      doctor_id=ward["ids"]["boss"], visit_date=local_today())
        ward["db"].session.add(visit)
        ward["db"].session.flush()
        ward["db"].session.add(Diagnosis(visit_id=visit.id, title="نزلة شعبية"))
        ward["db"].session.commit()

        stay = _stay(ward)
        stay.visit_id = visit.id
        ward["db"].session.commit()

        assert [d.title for d in ds.provisional_diagnoses(stay)] == ["نزلة شعبية"]
        # Offered, not stored: the final diagnosis is still unwritten.
        assert "diagnosis" in ds.missing(stay)


# ------------------------------------------------- the copy and the clock -
def test_a_copy_handed_to_the_family_is_its_own_stamp(ward):
    """Evidence 4. Nobody handed it over is not the same fact as nobody wrote
    it, and one field could not tell the two apart."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        row = ds.for_admission(stay)
        assert row.given is False

        ds.hand_over(stay, user=_boss(ward))
        ward["db"].session.commit()
        row = ds.for_admission(stay)
        assert row.given is True
        assert row.given_by == ward["ids"]["boss"]


def test_a_summary_nobody_wrote_cannot_be_handed_over(ward):
    """A clerk cannot give a family a document that does not exist."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        assert ds.hand_over(_stay(ward), user=_boss(ward)) is None


def test_handing_it_over_twice_does_not_move_the_moment(ward):
    """The second press is a second copy, not a second handover — and moving
    the stamp would erase when the family actually got it."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ds.hand_over(stay, user=_boss(ward),
                     at=datetime(2026, 3, 1, 10, 0))
        ward["db"].session.commit()

        assert ds.hand_over(stay, user=_boss(ward)) is None
        ward["db"].session.commit()
        assert ds.for_admission(stay).given_at == datetime(2026, 3, 1, 10, 0)


def test_the_delay_is_measured_and_never_graded(ward):
    """«An approved timeframe» is the hospital's policy and the standard names
    no number, so the program names none either — it counts the hours."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        row = ds.for_admission(stay)
        row.written_at = stay.discharged_at + timedelta(hours=30)
        ward["db"].session.commit()
        assert ds.delay_hours(stay) == 30


def test_a_summary_written_before_the_discharge_is_no_delay_at_all(ward):
    """Begun while the child was still in is the good case, and reads as
    zero rather than as a negative number nobody could interpret."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        row = ds.for_admission(stay)
        row.written_at = stay.discharged_at - timedelta(hours=6)
        ward["db"].session.commit()
        assert ds.delay_hours(stay) == 0


def test_no_summary_and_no_discharge_have_no_delay(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        assert ds.delay_hours(_stay(ward)) is None
        open_stay = _stay(ward, discharge=False)
        ds.write(open_stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        assert ds.delay_hours(open_stay) is None


def test_the_queue_of_stays_that_ended_with_nothing_written(ward):
    """Evidence 2's queue. An open stay is not on it — a child still in a bed
    has not been discharged, and counting them would be a list nobody could
    ever clear."""
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        done = _stay(ward)
        _stay(ward, discharge=False)
        assert [s.id for s in ds.unwritten()] == [done.id]

        ds.write(done, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        assert ds.unwritten() == []


# ------------------------------------------------- through the screens ----
def test_the_ward_screen_says_a_stay_has_no_summary(ward):
    from app.i18n import translate as t

    with ward["app"].app_context():
        stay = _stay(ward)
        html = ward["sign_in"]().get(
            "/beds/admission/%s" % stay.id).get_data(as_text=True)
        assert 'data-summary-state="none"' in html
        assert t("summary.not_written") in html


def test_writing_it_from_the_ward_screen_records_every_box(ward):
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ward["sign_in"]().post("/beds/admission/%s/summary" % stay.id,
                               data=FULL, follow_redirects=True)
        row = ds.for_admission(stay)
        for name, value in FULL.items():
            assert getattr(row, name) == value
        assert ds.state(stay) == "complete"


def test_saving_a_short_summary_says_how_many_are_blank(ward):
    """Said now, rather than found by a surveyor."""
    from app.i18n import translate as t

    with ward["app"].app_context():
        stay = _stay(ward)
        html = ward["sign_in"]().post(
            "/beds/admission/%s/summary" % stay.id,
            data=dict(FULL, findings="", condition=""),
            follow_redirects=True).get_data(as_text=True)
        assert t("summary.saved_short", n=2) in html
        assert 'data-summary-state="short"' in html


def test_the_nine_elements_are_on_the_ward_screen_with_their_letters(ward):
    """A doctor can see at a glance that (e) is answered by the theatre
    record and needs nothing from them."""
    with ward["app"].app_context():
        stay = _stay(ward)
        html = ward["sign_in"]().get(
            "/beds/admission/%s" % stay.id).get_data(as_text=True)
        for letter in "abcdefghi":
            assert 'data-element="%s"' % letter in html
        # (a) is answered by the stay's reason, (d) is not answered at all.
        # Read off the badge rather than matched as one string: the two
        # attributes sit on separate lines in the template, and an assertion
        # that needed them adjacent would be about the whitespace.
        assert _filled(html, "a") == "yes"
        assert _filled(html, "d") == "no"


def test_handing_a_copy_over_from_the_screen(ward):
    from app.i18n import translate as t
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        client = ward["sign_in"]()
        client.post("/beds/admission/%s/summary" % stay.id, data=FULL,
                    follow_redirects=True)
        html = client.post("/beds/admission/%s/summary/given" % stay.id,
                           follow_redirects=True).get_data(as_text=True)
        assert t("summary.given") in html
        assert "data-summary-given" in html
        assert ds.for_admission(stay).given is True


def test_the_screen_refuses_to_hand_over_what_nobody_wrote(ward):
    from app.i18n import translate as t

    with ward["app"].app_context():
        stay = _stay(ward)
        html = ward["sign_in"]().post(
            "/beds/admission/%s/summary/given" % stay.id,
            follow_redirects=True).get_data(as_text=True)
        assert t("summary.nothing_to_give") in html


def test_the_printed_copy_carries_all_nine_elements(ward):
    """Evidence 3 keeps one in the record and evidence 4 hands one over, so
    there has to be something to print."""
    from app.i18n import translate as t
    from app.models.theatre import Operation, Theatre
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        stay = _stay(ward, reason="التهاب رئوي")
        room = Theatre(name="غرفة ١")
        ward["db"].session.add(room)
        ward["db"].session.flush()
        ward["db"].session.add(
            Operation(patient_id=ward["ids"]["kid"], theatre_id=room.id,
                      procedure="استئصال زائدة", on_date=local_today(),
                      admission_id=stay.id, status="done"))
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()

        html = ward["sign_in"]().get(
            "/beds/admission/%s/summary/print" % stay.id).get_data(as_text=True)
        # The written half.
        for value in FULL.values():
            assert value in html
        # The derived half.
        assert "التهاب رئوي" in html                 # (a)
        assert "استئصال زائدة" in html               # (e)
        assert t("beds.outcome_home") in _section(html, "g")   # disposition
        # Under (i), not merely on the page: the same name is in the sheet's
        # header as whoever generated it.
        assert "المدير" in _section(html, "i")
        # And every element has its letter on the sheet.
        for letter in "abcdefghi":
            assert "%s) " % letter in html


def test_the_printed_copy_names_what_nobody_wrote(ward):
    """A blank line on a legal document reads as an element somebody decided
    was not applicable. It has to say nobody wrote it."""
    from app.i18n import translate as t
    from app.utils import discharge_summary as ds

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), diagnosis="التهاب رئوي فصّي")
        ward["db"].session.commit()
        html = ward["sign_in"]().get(
            "/beds/admission/%s/summary/print" % stay.id).get_data(as_text=True)
        # In element (d)'s own section: the sheet has five unwritten elements
        # on it, so the phrase appearing *somewhere* proves nothing about the
        # one being tested.
        assert t("summary.not_recorded") in _section(html, "d")
        # And the element that was written does not say it.
        assert t("summary.not_recorded") not in _section(html, "b")


def test_the_printed_copy_reads_the_record_at_the_moment_of_printing(ward):
    """A summary printed after somebody linked the operation that was missing
    carries it, and nobody has to rewrite the document to correct the
    record."""
    from app.models.theatre import Operation, Theatre
    from app.utils import discharge_summary as ds
    from app.utils.clock import local_today

    with ward["app"].app_context():
        stay = _stay(ward)
        ds.write(stay, user=_boss(ward), **FULL)
        ward["db"].session.commit()
        client = ward["sign_in"]()
        before = client.get("/beds/admission/%s/summary/print"
                            % stay.id).get_data(as_text=True)
        assert "استئصال زائدة" not in before

        room = Theatre(name="غرفة ١")
        ward["db"].session.add(room)
        ward["db"].session.flush()
        ward["db"].session.add(
            Operation(patient_id=ward["ids"]["kid"], theatre_id=room.id,
                      procedure="استئصال زائدة", on_date=local_today(),
                      admission_id=stay.id, status="done"))
        ward["db"].session.commit()

        after = client.get("/beds/admission/%s/summary/print"
                           % stay.id).get_data(as_text=True)
        assert "استئصال زائدة" in after


def test_the_childs_file_says_a_finished_stay_has_no_summary(ward):
    """On the file, because that is where somebody reading the record
    afterwards would notice it missing."""
    from app.i18n import translate as t

    with ward["app"].app_context():
        _stay(ward)
        html = ward["sign_in"]().get(
            "/patients/%s" % ward["ids"]["kid"]).get_data(as_text=True)
        assert 'data-summary-state="none"' in html
        assert t("summary.not_written") in html


def test_a_stay_still_running_is_not_asked_for_a_summary_on_the_file(ward):
    """A child still in a bed has not been discharged, and asking for their
    discharge summary would be a finding that can never be cleared."""
    with ward["app"].app_context():
        _stay(ward, discharge=False)
        html = ward["sign_in"]().get(
            "/patients/%s" % ward["ids"]["kid"]).get_data(as_text=True)
        assert 'data-summary-state="none"' not in html
