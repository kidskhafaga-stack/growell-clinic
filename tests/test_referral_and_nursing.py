"""Two things that leave the consultation room.

*"الطبيب يدّي توجيهات للتمريض"* and *"تحويل للطوارئ من جوّه العيادة، مع تنبيه
على الحالة في لستة الطبيب"*.

Both were being done by voice across a corridor, which is how an instruction
reaches the wrong child or nobody at all — and how a child who left for
hospital mid-consultation leaves behind a visit that simply stops, reading as
one somebody abandoned.

Neither waits for the visit form to be saved. They are their own actions with
their own records, because the minute they are used is the minute nobody is
going to remember to press Save.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _visit(clinic):
    return clinic["ids"]["visit"]


def _refer(clinic, where="مستشفى الأطفال", why="تسحّب شديد", undo=False):
    data = {"referred_to": where, "referral_note": why}
    if undo:
        data = {"undo": "1"}
    return clinic["sign_in"]("doc").post(f"/visits/{_visit(clinic)}/refer",
                                         data=data, follow_redirects=True)


# ============================================== the doctor's instructions ====
def test_the_nurse_reads_what_the_doctor_asked_for(clinic):
    """Written in the room, read at the station."""
    from app.models import Appointment, Visit
    from datetime import date, time

    db = clinic["db"]
    clinic["sign_in"]("doc").post(
        f"/visits/{_visit(clinic)}/nurse-instructions",
        data={"nurse_instructions": "نيبولايزر سالبيوتامول وقيس الحرارة بعد نص ساعة"},
        follow_redirects=True)

    with clinic["app"].app_context():
        visit = db.session.get(Visit, _visit(clinic))
        assert visit.nurse_instructions
        # The station lists today's checked-in children, so give this one a
        # place in the queue to be read from.
        db.session.add(Appointment(patient_id=visit.patient_id,
                                   doctor_id=visit.doctor_id,
                                   appt_date=date.today(), appt_time=time(10, 0),
                                   status="waiting"))
        visit.visit_date = date.today()
        db.session.commit()

    page = clinic["sign_in"]("doc").get("/visits/station").data.decode()
    assert "نيبولايزر سالبيوتامول" in page, \
        "the nurse cannot see what the doctor asked for"


def test_it_does_not_wait_for_the_visit_to_be_saved(clinic):
    """A separate form on purpose: the instruction is urgent and the visit
    form is long."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "templates",
                           "visits", "record.html"), encoding="utf-8") as fh:
        source = fh.read()
    assert "visits.nurse_instructions" in source
    # Its own <form>, not a field inside the clinical one.
    assert 'action="{{ url_for(\'visits.nurse_instructions\'' in source \
        or "visits.nurse_instructions', visit_id=visit.id" in source


def test_clearing_it_removes_it(clinic):
    """An instruction that has been carried out and left on the screen is an
    instruction somebody does twice."""
    from app.models import Visit

    doc = clinic["sign_in"]("doc")
    doc.post(f"/visits/{_visit(clinic)}/nurse-instructions",
             data={"nurse_instructions": "حاجة"}, follow_redirects=True)
    doc.post(f"/visits/{_visit(clinic)}/nurse-instructions",
             data={"nurse_instructions": "  "}, follow_redirects=True)

    with clinic["app"].app_context():
        assert clinic["db"].session.get(Visit, _visit(clinic)).nurse_instructions is None


# ============================================== the referral ================
def test_referring_records_where_and_why_and_when(clinic):
    """The one record that has to survive the panic."""
    from app.models import Visit

    _refer(clinic)

    with clinic["app"].app_context():
        visit = clinic["db"].session.get(Visit, _visit(clinic))
        assert visit.is_referred
        assert visit.referred_to == "مستشفى الأطفال"
        assert visit.referral_note == "تسحّب شديد"
        assert visit.referred_at is not None


def test_the_doctors_list_shows_it(clinic):
    """"مع تنبيه على الحالة في لستة الطبيب" — a child sent to hospital stops
    being a row somebody scrolls past."""
    import json

    _refer(clinic)
    page = clinic["sign_in"]("doc").get("/visits/").data.decode()

    with open(os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                           "locales", "ar.json"), encoding="utf-8") as fh:
        word = json.load(fh)["visits"]["referred_badge"]
    assert word in page


def test_the_nurse_sees_it_too(clinic):
    """She is the one standing next to the child."""
    from app.models import Appointment, Visit
    from datetime import date, time
    import json

    db = clinic["db"]
    _refer(clinic)
    with clinic["app"].app_context():
        visit = db.session.get(Visit, _visit(clinic))
        visit.visit_date = date.today()
        db.session.add(Appointment(patient_id=visit.patient_id,
                                   doctor_id=visit.doctor_id,
                                   appt_date=date.today(), appt_time=time(10, 0),
                                   status="waiting"))
        db.session.commit()

    page = clinic["sign_in"]("doc").get("/visits/station").data.decode()
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                           "locales", "ar.json"), encoding="utf-8") as fh:
        word = json.load(fh)["visits"]["referred_badge"]
    assert word in page


def test_a_referral_can_be_undone(clinic):
    """Written on the wrong child is a thing that happens in exactly the
    minutes this button gets pressed in."""
    from app.models import Visit

    _refer(clinic)
    _refer(clinic, undo=True)

    with clinic["app"].app_context():
        visit = clinic["db"].session.get(Visit, _visit(clinic))
        assert not visit.is_referred
        assert visit.referred_to is None


def test_a_visit_nobody_referred_says_nothing(clinic):
    """Guarding the guard: a badge on every row is a badge nobody reads."""
    import json

    page = clinic["sign_in"]("doc").get("/visits/").data.decode()
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                           "locales", "ar.json"), encoding="utf-8") as fh:
        word = json.load(fh)["visits"]["referred_badge"]
    assert word not in page
