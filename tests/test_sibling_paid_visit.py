"""Two exams together — not an exam and a free consultation.

Stated plainly by the clinic, and the program was not doing it. A sibling
counted as soon as they had *any* appointment, visit or invoice that day, so a
child who came for a free follow-up made half of a qualifying pair and the
family was given a discount they had not earned. That is money, computed
wrongly, every day two children walk in.

The rule, in the clinic's own words: **the consultation has to be at zero for
this to bite — if it is charged, it counts and the discount applies to it at
its rate.** Which is the same sentence read twice: a visit worth nothing is not
a visit for this purpose, and a visit that is charged is.

So a sibling counts when they had a **chargeable, in-scope** visit that day.
Read from the billed line where there is one, and otherwise from the booking —
because the first child of the day is priced while the second is still in the
waiting room, and a rule that could only fire on the last child billed would
tell reception there is no sibling discount with the siblings visibly in the
room.

One deliberate hole, and it is the honest one: a visit type mapped to no
service at all is counted. The program cannot tell an exam from a free
consultation there, and reading "unknown" as "free" would switch this discount
off silently in every clinic that has not mapped its visit types yet.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def family(clinic):
    """Two siblings, one doctor, and two priced visit types: exam and a free
    consultation — the exact pair the clinic described."""
    from app.models import (Appointment, Family, NamedDiscount, Patient,
                            Service)

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name="عائلة")
        db.session.add(fam)
        db.session.flush()

        kids = []
        for n in (1, 2):
            kid = Patient(patient_number=f"S{n}", full_name=f"طفل {n}",
                          gender="male", date_of_birth=date(2022, 1, 1),
                          family_id=fam.id, is_active=True)
            db.session.add(kid)
            kids.append(kid)

        # The exam is charged; the consultation the clinic gives free.
        exam = Service(name="كشف طوارئ", code="SB-EXAM", price=200,
                       category="consultation", visit_type="sb_exam",
                       is_active=True)
        free = Service(name="إستشارة مجانية", code="SB-FREE", price=0,
                       category="consultation", visit_type="sb_free",
                       is_active=True)
        db.session.add_all([exam, free])

        rule = NamedDiscount(name="خصم الإخوة", dtype="sibling", value=50,
                             is_percent=True, min_siblings=2, same_doctor=True,
                             scope="all", is_active=True, auto_apply=True)
        db.session.add(rule)
        db.session.flush()

        for kid in kids:
            db.session.add(Appointment(
                patient_id=kid.id, doctor_id=clinic["ids"]["doctor"],
                appt_date=local_today(), appt_time=time(10, 0),
                appt_type="sb_exam", status="booked"))
        db.session.commit()
        return {"kids": [k.id for k in kids], "rule": rule.id,
                "exam": exam.id, "free": free.id}


def _met(clinic, family):
    from app.blueprints.finance import routes as fr
    from app.models import NamedDiscount, Patient

    with clinic["app"].test_request_context("/"):
        rule = clinic["db"].session.get(NamedDiscount, family["rule"])
        patient = clinic["db"].session.get(Patient, family["kids"][0])
        return fr._sibling_rule_met(rule, patient, local_today(),
                                    clinic["ids"]["doctor"])


def _retype(clinic, patient_id, appt_type):
    from app.models import Appointment

    with clinic["app"].app_context():
        row = Appointment.query.filter_by(patient_id=patient_id).one()
        row.appt_type = appt_type
        clinic["db"].session.commit()


# ================================================== two exams is the case ===
def test_two_exams_on_the_same_day_qualify(family, clinic):
    assert _met(clinic, family) is True


def test_an_exam_and_a_free_consultation_do_not(family, clinic):
    """The case the clinic named. A visit worth nothing is not the second half
    of a pair, and giving the discount anyway is money out on a rule the
    family never met."""
    _retype(clinic, family["kids"][1], "sb_free")
    assert _met(clinic, family) is False


def test_a_paid_consultation_does_qualify(family, clinic):
    """The other half of the same sentence: charge for the consultation and it
    counts like any other visit."""
    from app.models import Service

    with clinic["app"].app_context():
        clinic["db"].session.get(Service, family["free"]).price = 150
        clinic["db"].session.commit()
    _retype(clinic, family["kids"][1], "sb_free")
    assert _met(clinic, family) is True


def test_a_free_visit_for_the_child_being_billed_is_not_enough_either(family,
                                                                     clinic):
    """The rule is symmetric — it is not "one of them paid"."""
    _retype(clinic, family["kids"][0], "sb_free")
    assert _met(clinic, family) is False


def test_a_lone_child_never_qualifies(family, clinic):
    from app.models import Appointment

    with clinic["app"].app_context():
        Appointment.query.filter_by(patient_id=family["kids"][1]).delete()
        clinic["db"].session.commit()
    assert _met(clinic, family) is False


# ===================================== priced before the second child is in ==
def test_the_first_child_can_be_billed_before_the_second(family, clinic):
    """The booking is what answers it. A rule that only fired on the last
    child billed would tell reception there is no sibling discount while the
    siblings are visibly in the room."""
    from app.models import Invoice, InvoiceItem

    with clinic["app"].app_context():
        inv = Invoice(invoice_number="SB-1", patient_id=family["kids"][0],
                      doctor_id=clinic["ids"]["doctor"],
                      invoice_date=local_today())
        clinic["db"].session.add(inv)
        clinic["db"].session.flush()
        clinic["db"].session.add(InvoiceItem(
            invoice_id=inv.id, service_id=family["exam"], description="كشف",
            quantity=1, unit_price=200))
        clinic["db"].session.commit()
    assert _met(clinic, family) is True


def test_a_billed_line_of_zero_does_not_count(family, clinic):
    """Somebody who was invoiced with the price zeroed had a free visit
    whatever the service list says."""
    from app.models import Appointment, Invoice, InvoiceItem

    with clinic["app"].app_context():
        Appointment.query.filter_by(patient_id=family["kids"][1]).delete()
        inv = Invoice(invoice_number="SB-2", patient_id=family["kids"][1],
                      doctor_id=clinic["ids"]["doctor"],
                      invoice_date=local_today())
        clinic["db"].session.add(inv)
        clinic["db"].session.flush()
        clinic["db"].session.add(InvoiceItem(
            invoice_id=inv.id, service_id=family["exam"], description="كشف",
            quantity=1, unit_price=0))
        clinic["db"].session.commit()
    assert _met(clinic, family) is False


# ============================================ what the scope still decides ==
def test_a_visit_outside_the_discounts_scope_does_not_count(family, clinic):
    """A rule aimed at consultations is not earned by a vaccination."""
    from app.models import NamedDiscount, Service

    with clinic["app"].app_context():
        rule = clinic["db"].session.get(NamedDiscount, family["rule"])
        rule.scope = "consultation"
        other = Service(name="تطعيم", code="SB-VAC", price=300,
                        category="vaccination_fee", visit_type="sb_vac",
                        is_active=True)
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
    _retype(clinic, family["kids"][1], "sb_vac")
    assert _met(clinic, family) is False


def test_an_unmapped_visit_type_is_not_read_as_free(family, clinic):
    """The honest hole: with no service behind the type the program cannot
    tell an exam from a free consultation, and calling it free would switch
    this discount off silently in every clinic that has not mapped its visit
    types yet."""
    _retype(clinic, family["kids"][1], "no_such_type")
    assert _met(clinic, family) is True
