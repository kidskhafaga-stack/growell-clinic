"""Did any of the sending bring anybody back.

Phase 2 gave the desk a work list, which means the clinic now sends things:
a birthday, an overdue dose, a recall to a family nobody has seen in a year.
Nothing could then say whether that was worth doing — the send log counts
what left the building and the service board counts how fast the clinic
answers what arrives.

Most of what is tested here is the arithmetic refusing to flatter itself.
A screen that reports outreach as working is a screen somebody spends money
on the strength of, so the interesting cases are all the ones where a naive
count would say yes and the honest answer is no:

* an appointment that was **already in the diary** before the message went;
* a message sent **yesterday**, which has not had time to work and would
  otherwise drag the rate down for no reason but when somebody looked;
* a booking made **after the window closed**, which is not a response to
  anything.

The last one is the reason `mature` exists at all, and it is the number most
likely to be "simplified" away by somebody who finds it confusing later.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402


def _sent(clinic, kind="patient_recall", days_ago=20, patient=None):
    """A message the clinic actually sent, `days_ago` days back."""
    from app.extensions import db
    from app.models import MessageLog, Patient

    kid = patient or Patient.query.first()
    when = datetime.utcnow() - timedelta(days=days_ago)
    log = MessageLog(patient_id=kid.id, to_phone=kid.contact_phone or "01000000000",
                     direction="out", body="تعالوا نطمن عليه", status="sent",
                     template_type=kind, sent_at=when, created_at=when)
    db.session.add(log)
    return kid


def _other_child(clinic):
    """A second family, for the cases where one would blur two reasons."""
    from app.extensions import db
    from app.models import Patient

    kid = Patient(patient_number="OUT2", full_name="طفل تاني", gender="female",
                  date_of_birth=date(2022, 5, 1),
                  own_phone="01099999999", is_active=True)
    db.session.add(kid)
    db.session.flush()
    return kid


def _booked(clinic, patient, days_ago=18):
    """A booking *made* `days_ago` days back — the moment, not the day booked for."""
    from app.extensions import db
    from app.models import Appointment, User

    doc = User.query.filter_by(username="doc").first()
    appt = Appointment(patient_id=patient.id, doctor_id=doc.id,
                       appt_date=local_today(), appt_time=time(10, 0),
                       status="scheduled",
                       created_at=datetime.utcnow() - timedelta(days=days_ago))
    db.session.add(appt)
    return appt


def _visited(clinic, patient, days_ago=17):
    from app.extensions import db
    from app.models import User, Visit

    doc = User.query.filter_by(username="doc").first()
    visit = Visit(patient_id=patient.id, doctor_id=doc.id,
                  visit_date=local_today(), status="completed",
                  created_at=datetime.utcnow() - timedelta(days=days_ago))
    db.session.add(visit)
    return visit


def _report(clinic, build, days=30):
    from app.extensions import db
    from app.utils.outcomes import reach_report

    with clinic["app"].app_context():
        build()
        db.session.commit()
        return reach_report(days=days)


def _row(report, reason):
    for row in report["rows"]:
        if row["reason"] == reason:
            return row
    return None


# ------------------------------------------------------------ it counts ----

def test_a_family_that_booked_after_the_message_is_counted(clinic):
    def build():
        kid = _sent(clinic)
        _booked(clinic, kid)

    row = _row(_report(clinic, build), "patient_recall")

    assert row and row["booked"] == 1, "a booking after the recall was not counted"
    assert row["booked_rate"] == 100.0


def test_arriving_is_counted_separately_from_booking(clinic):
    """Two different facts. A diary full of people who do not turn up is not
    a recall that worked, and one number covering both would hide it."""
    def build():
        kid = _sent(clinic)
        _booked(clinic, kid)          # booked, and never came

    row = _row(_report(clinic, build), "patient_recall")

    assert row["booked"] == 1
    assert row["attended"] == 0, "a booking nobody attended was counted as a visit"


def test_a_visit_after_the_message_counts_as_arriving(clinic):
    def build():
        kid = _sent(clinic)
        _visited(clinic, kid)

    assert _row(_report(clinic, build), "patient_recall")["attended"] == 1


# ------------------------------------------------- it refuses to flatter ----

def test_an_appointment_already_in_the_diary_is_not_credited(clinic):
    """The mistake that would make every number here meaningless.

    A family with an appointment booked *before* the recall went out did not
    book because of it, and counting it would score the clinic's own diary
    as its outreach.
    """
    def build():
        kid = _sent(clinic, days_ago=20)
        _booked(clinic, kid, days_ago=25)      # booked five days *before*

    row = _row(_report(clinic, build), "patient_recall")

    assert row["booked"] == 0, \
        "an appointment that predates the message was credited to it"


def test_a_booking_that_predates_only_the_second_message_is_not_credited_to_it(clinic):
    """The case that actually exercises the guard, found by mutation testing.

    The simple version of this test — one message, one earlier booking —
    passes even with the "was it after?" check deleted, because the query
    only loads bookings made since the *earliest* send and an earlier one is
    never fetched at all. So it proved nothing.

    Two sends at different times is where the check earns its place: a
    booking made after the recall and before the birthday is inside the
    loaded set, and only the per-message comparison keeps the birthday from
    taking credit for something that had already happened when it went out.
    """
    def build():
        kid = _sent(clinic, kind="patient_recall", days_ago=30)
        _sent(clinic, kind="birthday", days_ago=16, patient=kid)
        _booked(clinic, kid, days_ago=25)

    report = _report(clinic, build, days=90)

    assert _row(report, "patient_recall")["booked"] == 1, \
        "the recall did precede the booking and should be credited"
    assert _row(report, "birthday")["booked"] == 0, \
        "a booking made before the birthday went out was credited to it"


def test_a_booking_after_the_window_closed_is_not_credited(clinic):
    """Past the follow window, "they came back after the message" stops
    meaning anything even as association."""
    from app.utils.outcomes import FOLLOW_DAYS

    def build():
        kid = _sent(clinic, days_ago=40)
        _booked(clinic, kid, days_ago=40 - FOLLOW_DAYS - 3)

    row = _row(_report(clinic, build, days=90), "patient_recall")

    assert row["booked"] == 0, \
        f"a booking more than {FOLLOW_DAYS} days later was credited"


def test_a_message_too_recent_to_judge_is_not_in_the_rate(clinic):
    """Otherwise the rate moves with the hour somebody opens the screen.

    A recall sent yesterday has had one day to produce a booking. In the
    denominator it is a failure; it is actually just young.
    """
    def build():
        _sent(clinic, days_ago=1)

    row = _row(_report(clinic, build), "patient_recall")

    assert row["sent"] == 1
    assert row["mature"] == 0, "a message sent yesterday is being scored"
    assert row["too_recent"] == 1, "and it has to still be visible, not dropped"
    assert row["booked_rate"] is None, \
        "a rate was computed out of nothing and will read as 0%"


def test_the_young_ones_are_shown_rather_than_silently_dropped(clinic):
    """A number that quietly excludes things is worse than one showing gaps."""
    def build():
        _sent(clinic, days_ago=1)
        _sent(clinic, days_ago=20)

    row = _row(_report(clinic, build), "patient_recall")

    assert row["sent"] == 2, "the young message vanished from the count entirely"
    assert row["mature"] == 1 and row["too_recent"] == 1


def test_a_failed_message_is_not_treated_as_something_the_clinic_said(clinic):
    from app.extensions import db
    from app.models import MessageLog, Patient

    def build():
        kid = Patient.query.first()
        when = datetime.utcnow() - timedelta(days=20)
        db.session.add(MessageLog(
            patient_id=kid.id, to_phone="01000000000", direction="out",
            body="x", status="failed", error="number not on whatsapp",
            template_type="patient_recall", created_at=when))

    assert _row(_report(clinic, build), "patient_recall") is None, \
        "a message that never arrived is being scored as outreach"


def test_an_inbound_message_is_not_outreach(clinic):
    from app.extensions import db
    from app.models import MessageLog, Patient

    def build():
        kid = Patient.query.first()
        when = datetime.utcnow() - timedelta(days=20)
        db.session.add(MessageLog(
            patient_id=kid.id, to_phone="01000000000", direction="in",
            body="عندي سؤال", status="sent", template_type="patient_recall",
            created_at=when))

    assert _row(_report(clinic, build), "patient_recall") is None


# ------------------------------------------------------------- the shape ---

def test_each_reason_is_scored_on_its_own(clinic):
    """A recall and a birthday are different conversations with different
    odds, and one blended rate would let a good one hide a useless one."""
    def build():
        kid = _sent(clinic, kind="patient_recall")
        _booked(clinic, kid)
        _sent(clinic, kind="birthday", patient=_other_child(clinic))

    report = _report(clinic, build)

    assert _row(report, "patient_recall")["booked"] == 1
    assert _row(report, "birthday")["booked"] == 0
    assert report["totals"]["sent"] == 2, "the totals row lost one"


def test_two_reasons_to_one_family_both_get_the_credit(clinic):
    """Pinned on purpose, because it looks like a bug until you try to fix it.

    One family sent a recall and a birthday inside the same fortnight, who
    then book: there is nothing in this data that says which one moved them.
    Crediting neither throws the signal away; crediting one is a guess. So
    both rows count it, and the unit of every number here is the message
    rather than the family — which is what the totals row means too.
    """
    def build():
        kid = _sent(clinic, kind="patient_recall")
        _sent(clinic, kind="birthday", patient=kid)
        _booked(clinic, kid)

    report = _report(clinic, build)

    assert _row(report, "patient_recall")["booked"] == 1
    assert _row(report, "birthday")["booked"] == 1, \
        "the second reason lost credit for a booking it may equally have caused"
    assert report["totals"]["booked"] == 2, \
        "the totals row counts families; every other number here counts messages"


def test_the_totals_agree_with_the_rows_they_head(clinic):
    """A total that disagrees with its own table is why nobody trusts one."""
    def build():
        kid = _sent(clinic, kind="patient_recall")
        _booked(clinic, kid)
        _sent(clinic, kind="birthday")
        _sent(clinic, kind="vaccine_due", days_ago=1)

    report = _report(clinic, build)

    for field in ("sent", "mature", "too_recent", "booked", "attended"):
        assert report["totals"][field] == sum(r[field] for r in report["rows"]), \
            f"the totals row disagrees with the table on '{field}'"


def test_the_median_is_the_ordinary_wait(clinic):
    from app.utils.outcomes import _median

    assert _median([]) is None
    assert _median([1.0, 2.0, 30.0]) == 2.0, "one late booking moved the middle"
    assert _median([1.0, 3.0]) == 2.0


def test_nothing_sent_is_an_answer_not_a_crash(clinic):
    from app.utils.outcomes import reach_report

    with clinic["app"].app_context():
        report = reach_report(days=30)

    assert report["rows"] == []
    assert report["totals"]["sent"] == 0
    assert report["totals"]["booked_rate"] is None


# -------------------------------------------------------- delivery health --

def test_failures_are_grouped_by_what_the_provider_said(clinic):
    """"Not on WhatsApp" is a wrong number somebody can fix; a dead
    connection is not. One failure count conflates them and gets ignored."""
    from app.extensions import db
    from app.models import MessageLog, Patient
    from app.utils.outcomes import delivery_health

    with clinic["app"].app_context():
        kid = Patient.query.first()
        for err, phone in [("number not on whatsapp", "01111111111"),
                           ("number not on whatsapp", "01111111111"),
                           ("connection refused", "01222222222")]:
            db.session.add(MessageLog(
                patient_id=kid.id, to_phone=phone, direction="out", body="x",
                status="failed", error=err, created_at=datetime.utcnow()))
        db.session.commit()
        health = delivery_health(days=30)

    assert health["failed"] == 3
    assert health["by_error"][0]["error"] == "number not on whatsapp"
    assert health["by_error"][0]["count"] == 2, "the errors were not grouped"


def test_a_number_that_keeps_failing_is_surfaced(clinic):
    """One failure is a blip. A number failing repeatedly is a wrong number
    in a patient file — the one thing on this screen somebody can act on."""
    from app.extensions import db
    from app.models import MessageLog, Patient
    from app.utils.outcomes import delivery_health

    with clinic["app"].app_context():
        kid = Patient.query.first()
        for phone in ["01111111111", "01111111111", "01222222222"]:
            db.session.add(MessageLog(
                patient_id=kid.id, to_phone=phone, direction="out", body="x",
                status="failed", error="no", created_at=datetime.utcnow()))
        db.session.commit()
        health = delivery_health(days=30)

    numbers = [r["phone"] for r in health["repeat_numbers"]]
    assert numbers == ["01111111111"], \
        f"the repeat offender was not singled out: {health['repeat_numbers']}"


# ------------------------------------------------------------ the screen ---

def test_the_screen_opens_for_the_desk(clinic):
    """Work, not setup — it reports on what the desk itself did."""
    assert clinic["sign_in"]("desk").get("/messages/outcomes").status_code == 200
    assert clinic["sign_in"]("boss").get("/messages/outcomes").status_code == 200


def test_the_screen_says_out_loud_that_this_is_not_cause(clinic):
    """The line that stops the number being read as proof.

    Not decoration: somebody decides whether to keep sending on the strength
    of this screen, and "came back after" and "came back because of" lead to
    different decisions.
    """
    from app.i18n import t

    page = clinic["sign_in"]("desk").get("/messages/outcomes").data.decode()

    with clinic["app"].test_request_context("/"):
        marker = t("outcomes.not_because")[:30]
    assert marker in page, "the screen presents association as cause"


def test_the_period_buttons_work_and_nonsense_does_not_break_it(clinic):
    client = clinic["sign_in"]("desk")

    for days in (7, 30, 90):
        assert client.get(f"/messages/outcomes?days={days}").status_code == 200
    assert client.get("/messages/outcomes?days=../etc/passwd").status_code == 200
    assert client.get("/messages/outcomes?days=99999").status_code == 200


def test_the_desk_has_a_way_in(clinic):
    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "/messages/outcomes" in page, "the desk has no link to the board"


def test_an_empty_board_says_so_rather_than_showing_nothing(clinic):
    from app.i18n import t

    page = clinic["sign_in"]("desk").get("/messages/outcomes").data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("outcomes.no_sends")[:20] in page, \
            "a clinic that has sent nothing gets a blank panel"
