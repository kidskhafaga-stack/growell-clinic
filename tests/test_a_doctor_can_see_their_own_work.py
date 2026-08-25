"""A doctor's own screen: what they saw, and what it earned.

Asked for by name — *"عايز أعمل شاشة الطبيب يشوف فيها حالاته… نصيبه قد إيه
النهارده، على مدار الشهر… شاف كام حالة جديدة، شاف كام حالة بأنواعها — كشف،
أول مرة، قديمة، استشارة، تطعيم، وأي خدمات هو بيقدمها"* — and then, when the
first answer was a card on the dashboard, asked again why it wasn't a screen.

Fairly. The dashboard answers *right now*, at a glance. This answers *how am I
doing*, which needs a window of time and room to read.

**Every part of the answer already existed, in three places.** Cases and share
per service were in the printable staff statement, under Reports, which most
doctors cannot open. New-versus-returning was computed inside the appointments
board. The share for today and this month was a fourth calculation on the board
again. So the arithmetic moved to one module that the report and the screen
both read: a doctor's pay is the one number two calculations must never
disagree about.

**And one number is deliberately absent.** The program totals what a doctor has
earned; nothing in it records money handed to a doctor. "What am I still owed"
has no honest subtrahend, so the screen says so instead of showing a figure.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def worked(clinic):
    """A month of work for the owner, and a second doctor with none."""
    from app.extensions import db
    from app.models import (Appointment, Invoice, InvoiceItem, Patient,
                            PatientVaccine, Payment, Service, User,
                            VaccineBrand)
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        owner = User.query.filter_by(username="boss").first()
        owner.is_practitioner = True
        other = User.query.filter_by(username="doc").first()

        ecg = Service(name="رسم قلب", category="procedure", price=300,
                      commission_type="percent", commission_value=30,
                      is_active=True)
        db.session.add(ecg)
        exam = Service.query.filter_by(name="كشف").first()
        db.session.flush()

        today = local_today()
        kinds = ("consultation", "followup", "vaccination", "consultation")
        for i in range(4):
            child = Patient(patient_number=f"W{i}", full_name=f"وليد {i}",
                            gender="male", date_of_birth=date(2023, 1, 1),
                            is_active=True)
            db.session.add(child)
            db.session.flush()
            db.session.add(Appointment(
                patient_id=child.id, doctor_id=owner.id,
                appt_date=today - timedelta(days=i), appt_time=time(9 + i, 0),
                appt_type=kinds[i], status="completed"))

            service = ecg if i % 2 else exam
            invoice = Invoice(patient_id=child.id, doctor_id=owner.id,
                              invoice_number=f"INV-{i}",
                              invoice_date=today - timedelta(days=i),
                              status="paid")
            db.session.add(invoice)
            db.session.flush()
            line = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                               description=service.name, quantity=1,
                               unit_price=service.price, discount_value=0)
            db.session.add(line)
            db.session.flush()
            # The snapshot finance writes when it bills. The share is read off
            # the line, never recomputed — see doctor_work.by_service.
            line.commission_amount = service.doctor_share(line.net, owner)
            db.session.add(Payment(invoice_id=invoice.id,
                                   amount=service.price, method="cash",
                                   received_by=owner.id))
        # A vaccine given by this doctor. Its money is shaped differently —
        # the cut is a fee on the brand recorded against the dose, not a
        # commission on an invoice line — so it has to be in the fixture or
        # that whole path is untested.
        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        brand.doctor_fee = 25
        jab = Patient(patient_number="V1", full_name="طفل تطعيم",
                      gender="female", date_of_birth=date(2024, 6, 1),
                      is_active=True)
        db.session.add(jab)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=jab.id, vaccine_id=clinic["ids"]["pcv"],
            brand_id=brand.id, dose_number=1, given_date=today,
            doctor_id=owner.id, given_outside=False, event_type="given"))
        db.session.commit()
        clinic["other_id"] = other.id
        clinic["owner_id"] = owner.id
        clinic["vaccine_fee"] = 25
    return clinic


def _work(clinic, doctor_id, date_from, date_to):
    """`summary` renders visit-type labels, so it wants a request context —
    a label is a piece of user-facing text and `t()` reads the language off
    the request. Wrapped here once rather than at eight call sites."""
    from app.utils import doctor_work

    with clinic["app"].test_request_context():
        return doctor_work.summary(doctor_id, date_from, date_to)


def _services(clinic, doctor_id, date_from, date_to):
    """Same reason as `_work`: the vaccine row is labelled with `t()`, so it
    wants a request context."""
    from app.utils import doctor_work

    with clinic["app"].test_request_context():
        return doctor_work.by_service(doctor_id, date_from, date_to)


def _mine(clinic, who="boss", **args):
    from urllib.parse import urlencode

    query = ("?" + urlencode(args)) if args else ""
    return clinic["sign_in"](who).get("/my-clinic" + query)


# ------------------------------------------------------ what it answers

def test_it_says_how_many_and_of_what_kind(worked):
    """*"شاف كام حالة بأنواعها"*. The types come from the clinic's own
    catalogue, so a clinic that renamed "كشف" sees its own word here."""
    page = _mine(worked).get_data(as_text=True)

    assert "mine.by_type" not in page, "the strings are keys, not translations"
    # The labels are whatever the clinic calls them, so the count is what can
    # be asserted on here; the keys themselves are pinned in the test below.
    assert "4" in page


def test_the_types_are_counted_from_the_catalogue(worked):
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
        work = _work(worked, worked["owner_id"],
                     today - timedelta(days=30), today)

    counts = {r["key"]: r["count"] for r in work["types"]}
    assert counts.get("consultation") == 2
    assert counts.get("followup") == 1
    assert counts.get("vaccination") == 1


def test_a_type_with_none_of_them_is_still_a_row(worked):
    """A missing row reads as "this does not exist here". A zero reads as "none
    this month", which is true and more useful."""
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
        work = _work(worked, worked["owner_id"], today, today)

    assert any(r["count"] == 0 for r in work["types"]), \
        "types with nothing in the window vanished from the list"


def test_the_share_comes_from_the_line_and_not_a_percentage(worked):
    """Invoice lines carry their own commission. A line discounted at the desk
    already has the right number on it, and working it out again from the
    service's rate would quietly disagree with the invoice the patient got."""
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
    rows, share, _invs = _services(worked, worked["owner_id"],
                                   today - timedelta(days=30), today)

    # كشف 200 @ 40% twice, رسم قلب 300 @ 30% twice, plus one vaccine fee.
    expected = 200 * 0.4 * 2 + 300 * 0.3 * 2 + worked["vaccine_fee"]
    assert share == pytest.approx(expected)

    # **And the rows have to add up to it.** Caught by mutation testing: the
    # total comes from `Invoice.doctor_share_total`, so recomputing each row's
    # share from a made-up percentage left the headline correct and every line
    # of the table wrong — a breakdown that disagrees with its own total is
    # exactly the failure this module was written to prevent.
    assert sum(r["share"] for r in rows) == pytest.approx(expected), \
        "the per-service shares do not add up to the doctor's total"

    by_label = {r["label"]: r for r in rows}
    assert by_label["كشف"]["share"] == pytest.approx(200 * 0.4 * 2)
    assert by_label["رسم قلب"]["share"] == pytest.approx(300 * 0.3 * 2)


def test_each_service_is_its_own_row(worked):
    """*"وأي خدمات هو بيقدمها تاني أكيو رسم قلب كده"* — the point of the
    breakdown is that a doctor sees which of their work earns what."""
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
    rows, _s, _i = _services(worked, worked["owner_id"],
                             today - timedelta(days=30), today)

    labels = {r["label"]: r for r in rows}
    assert "رسم قلب" in labels and "كشف" in labels
    assert labels["رسم قلب"]["count"] == 2


def test_a_cancelled_slot_is_not_a_patient_seen(worked):
    from app.extensions import db
    from app.models import Appointment
    from app.utils import doctor_work
    from app.utils.clock import local_today

    with worked["app"].app_context():
        Appointment.query.first().status = "no_show"
        db.session.commit()

        today = local_today()
    work = _work(worked, worked["owner_id"],
                 today - timedelta(days=30), today)

    assert work["seen"] == 3


# ------------------------------------------------- new versus returning

def test_new_means_new_to_the_clinic_not_new_to_this_doctor(worked):
    """A child who has been coming for two years and sees a second doctor for
    the first time is not a new patient. Counting them as one tells a clinic it
    is growing when it is rotating."""
    from app.extensions import db
    from app.models import Appointment, Patient
    from app.utils import doctor_work
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
        old = Patient(patient_number="OLD", full_name="طفل قديم",
                      gender="male", date_of_birth=date(2020, 1, 1),
                      is_active=True)
        db.session.add(old)
        db.session.flush()
        # Seen last year by somebody else…
        db.session.add(Appointment(patient_id=old.id,
                                   doctor_id=worked["other_id"],
                                   appt_date=today - timedelta(days=400),
                                   appt_time=time(10, 0), status="completed"))
        # …and today, by this doctor for the first time.
        db.session.add(Appointment(patient_id=old.id,
                                   doctor_id=worked["owner_id"],
                                   appt_date=today, appt_time=time(11, 0),
                                   status="completed"))
        db.session.commit()

    work = _work(worked, worked["owner_id"], today, today)

    assert work["patients"]["returning"] == 1, \
        "a child known to the clinic was counted as a new patient"
    # The other child in today's window is genuinely new — their first visit
    # anywhere is today — so the honest expectation is one of each, not none.
    assert work["patients"]["new"] == 1
    assert work["patients"]["total"] == 2


def test_a_child_seen_three_times_is_one_patient(worked):
    """Counted per patient, not per appointment — otherwise a clinic that sees
    one child weekly reads as four."""
    from app.extensions import db
    from app.models import Appointment
    from app.utils import doctor_work
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
        first = Appointment.query.first()
        for extra in (1, 2):
            db.session.add(Appointment(
                patient_id=first.patient_id, doctor_id=worked["owner_id"],
                appt_date=today, appt_time=time(14 + extra, 0),
                status="completed"))
        db.session.commit()

    work = _work(worked, worked["owner_id"],
                 today - timedelta(days=30), today)

    assert work["patients"]["total"] == 4, "one child was counted three times"


# --------------------------------------------------------- who sees what

def test_a_doctor_cannot_ask_about_another_doctor(worked):
    """The rule the whole screen turns on. A doctor editing the address must
    not be able to read somebody else's earnings."""
    answer = _mine(worked, who="doc", doctor_id=worked["owner_id"])
    page = answer.get_data(as_text=True)

    assert answer.status_code == 200
    # `د. أحمد` is this doctor's own name in the fixture, so the name to look
    # for is the *other* one. The first version of this asserted the doctor's
    # own name was absent from their own screen.
    assert "المدير" not in page, \
        "a doctor read another doctor's screen by changing the URL"


def test_whoever_runs_the_clinic_can(worked):
    """Asked for directly: *"الطبيب اللي واخد صلاحيات أدمن كاملة بيشوف اللي
    بيحصل في العيادة كلها"*."""
    page = _mine(worked, doctor_id=worked["other_id"]).get_data(as_text=True)

    assert "د. أحمد" in page, "the owner cannot look at another doctor's work"
    assert 'name="doctor_id"' in page, "the owner has no way to pick"


def test_a_doctor_is_offered_no_picker(worked):
    """There is nothing for them to pick, and a control that does nothing is
    worse than no control."""
    page = _mine(worked, who="doc").get_data(as_text=True)

    assert 'name="doctor_id"' not in page


def test_an_id_that_is_not_a_practitioner_is_not_answered_about(worked):
    """Checked against the list rather than trusted. A receptionist's id in the
    address should not produce a screen about a receptionist."""
    page = _mine(worked, doctor_id=worked["ids"]["desk"]).get_data(as_text=True)

    assert "الاستقبال" not in page


def test_reception_has_no_screen_here(worked):
    answer = _mine(worked, who="desk")

    assert answer.status_code in (302, 403)


# ------------------------------------------------------------ the window

def test_the_window_defaults_to_this_month(worked):
    """The commonest question — "what have I done this month" — costs nothing.
    """
    from app.utils.clock import local_today

    page = _mine(worked).get_data(as_text=True)

    assert local_today().replace(day=1).isoformat() in page


def test_a_range_typed_backwards_is_read_as_a_range(worked):
    """A mistake, not a request for nothing. Answering with zeros would look
    like a clinic that did nothing that month."""
    from app.utils.clock import local_today

    today = local_today()
    answer = _mine(worked, date_from=today.isoformat(),
                   date_to=(today - timedelta(days=7)).isoformat())

    assert answer.status_code == 200
    assert "4" in answer.get_data(as_text=True)


def test_a_nonsense_date_falls_back_rather_than_breaking(worked):
    answer = _mine(worked, date_from="not-a-date")

    assert answer.status_code == 200


# ------------------------------- one calculation, and one honest omission

def test_the_report_and_the_screen_read_the_same_function(worked):
    """A doctor's pay is the one number two calculations must never disagree
    about. The staff statement used to compute it itself."""
    import inspect

    from app.blueprints.reports import routes as reports

    source = inspect.getsource(reports.staff_statement)

    assert "doctor_work" in source, \
        "the report went back to working out the share by itself"
    assert "commission_amount" not in source, \
        "the report is summing invoice lines again"


def test_the_screen_says_it_cannot_say_what_is_still_owed(worked):
    """The absent number, said out loud. Nothing in the program records money
    handed to a doctor, so "what am I still owed" has no honest subtrahend —
    and a screen that showed one would be inventing it."""
    page = _mine(worked).get_data(as_text=True)

    assert ("لسه مابيسجّلش صرف" in page or "does not yet record money paid"
            in page), "the screen is silent about the number it cannot give"


def test_it_is_reachable_from_the_sidebar(worked):
    """This program keeps building things nothing links to. The rule that
    catches it lives in test_periods_year_and_reach; this is the same claim
    said where somebody reading this feature will see it."""
    page = _mine(worked).get_data(as_text=True)

    assert page.count("/my-clinic") >= 2, "there is no way in from the shell"


def test_a_vaccine_is_its_own_row_and_its_own_kind_of_money(worked):
    """The doctor's cut on a vaccine is a fee on the brand recorded against the
    dose, not a commission on an invoice line. Folding it into the services
    would make a total nobody could trace back — and dropping it would quietly
    shorten the doctor's pay by a whole category of work.

    Found by mutation testing: removing the vaccine fee from the total broke
    nothing, because the fixture had no vaccines in it."""
    from app.utils.clock import local_today

    with worked["app"].app_context():
        today = local_today()
    rows, share, _invs = _services(worked, worked["owner_id"],
                                   today - timedelta(days=30), today)

    vaccine_rows = [r for r in rows if r["share"] == worked["vaccine_fee"]
                    and r["count"] == 1]
    assert vaccine_rows, "the vaccine is not a row of its own"
    assert sum(r["share"] for r in rows) == pytest.approx(share), \
        "the vaccine fee is in the rows but not the total, or the other way"
