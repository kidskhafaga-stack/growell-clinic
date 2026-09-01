"""The discount chooser: one discount per line, and always the biggest one.

A child can qualify for several offers at the same time — his club gives
members 20%, and he came in with his brother for 50% off the exam. He must get
one of them, the one worth more on his own bill, and reception must be able to
overrule the choice. That is what these tests pin down.

Runs on the in-memory testing config, so nothing here touches a real database.
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
def clinic():
    """A family of two, a club card on one brother, and two rival discounts."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Appointment, Family, NamedDiscount,
                                Patient, PatientCoverage, PayerEntity,
                                Service, User)

        fam = Family(family_name="عائلة الاختبار")
        doctor = User(username="d1", full_name="د. أ", role="doctor")
        other = User(username="d2", full_name="د. ب", role="doctor")
        doctor.set_password("x")
        other.set_password("x")
        club = PayerEntity(name="نادٍ", entity_type="club", is_active=True)
        db.session.add_all([fam, doctor, other, club])
        db.session.flush()

        exam = Service(code="T-EXAM", name="كشف", price=200,
                       category="consultation", is_active=True)
        echo = Service(code="T-ECHO", name="إيكو", price=800,
                       category="radiology", is_active=True)
        db.session.add_all([exam, echo])

        brother = Patient(patient_number="T1", full_name="أخ", gender="male",
                          date_of_birth=date(2018, 1, 1), family_id=fam.id)
        child = Patient(patient_number="T2", full_name="أخت", gender="female",
                        date_of_birth=date(2020, 1, 1), family_id=fam.id)
        db.session.add_all([brother, child])
        db.session.flush()
        # Only the brother's name is on the club card.
        db.session.add(PatientCoverage(patient_id=brother.id, payer_id=club.id,
                                       membership_number="C-1", is_active=True,
                                       expiry_date=date(2099, 1, 1)))
        # Both children are booked today, with the same doctor.
        db.session.add_all([
            Appointment(patient_id=brother.id, doctor_id=doctor.id,
                        appt_date=local_today(), appt_time=time(10, 0),
                        status="booked"),
            Appointment(patient_id=child.id, doctor_id=doctor.id,
                        appt_date=local_today(), appt_time=time(10, 30),
                        status="booked")])

        member = NamedDiscount(name="خصم الأعضاء", dtype="payer", value=20,
                               is_percent=True, payer_id=club.id, scope="all",
                               family_wide=True, auto_apply=True, is_active=True)
        sibling = NamedDiscount(name="خصم الإخوة", dtype="sibling", value=50,
                                is_percent=True, min_siblings=2,
                                scope="consultation", same_doctor=True,
                                auto_apply=True, is_active=True)
        db.session.add_all([member, sibling])
        db.session.commit()
        yield {"app": app, "db": db, "child": child, "brother": brother,
               "doctor": doctor, "other": other, "exam": exam, "echo": echo,
               "member": member, "sibling": sibling, "club": club}


def _invoice(env, lines, number="T-INV"):
    from app.models import Invoice, InvoiceItem

    db = env["db"]
    inv = Invoice(invoice_number=number, patient_id=env["child"].id,
                  doctor_id=env["doctor"].id, invoice_date=date.today())
    db.session.add(inv)
    db.session.flush()
    for service, price in lines:
        inv.items.append(InvoiceItem(service_id=service.id, quantity=1,
                                     description=service.name, unit_price=price))
    db.session.flush()
    return inv


def test_biggest_discount_wins_on_a_small_bill(clinic):
    """Exam alone: 50% of 200 beats 20% of 200."""
    from app.blueprints.finance import routes as fr

    with clinic["app"].test_request_context("/"):
        inv = _invoice(clinic, [(clinic["exam"], 200)], "T-1")
        assert fr._discount_worth(inv, clinic["sibling"]) == 100.0
        assert fr._discount_worth(inv, clinic["member"]) == 40.0
        assert fr._best_discount(inv, clinic["child"],
                                 clinic["doctor"].id) is clinic["sibling"]


def test_biggest_is_measured_in_money_not_percent(clinic):
    """Add an echo and the club's 20% of the whole bill is worth more than
    the sibling rule's 50% of the exam. The headline percentage is a trap."""
    from app.blueprints.finance import routes as fr

    with clinic["app"].test_request_context("/"):
        inv = _invoice(clinic, [(clinic["exam"], 200), (clinic["echo"], 800)],
                       "T-2")
        best = fr._best_discount(inv, clinic["child"], clinic["doctor"].id)
        assert best is clinic["member"]
        fr._apply_named_discount(inv, best)
        # One rule, applied once, across the lines it reaches — never stacked.
        assert inv.discount_id == clinic["member"].id
        assert sorted(i.discount_value for i in inv.items) == [40.0, 160.0]


def test_a_line_that_already_has_a_discount_is_left_alone(clinic):
    """No stacking: a manual (or coverage) reduction blocks the named rule."""
    from app.blueprints.finance import routes as fr

    with clinic["app"].test_request_context("/"):
        inv = _invoice(clinic, [(clinic["exam"], 200)], "T-3")
        inv.items[0].discount_value = 30
        inv.items[0].discount_is_percent = False
        assert fr._discount_worth(inv, clinic["sibling"]) == 0
        fr._apply_named_discount(inv, clinic["sibling"])
        assert inv.items[0].discount_value == 30


def test_sibling_rule_wants_the_same_doctor(clinic):
    """Two children who saw two different doctors are two visits, not a pair."""
    from app.blueprints.finance import routes as fr
    from app.models import Appointment

    with clinic["app"].test_request_context("/"):
        child, sibling = clinic["child"], clinic["sibling"]
        assert fr._sibling_rule_met(sibling, child, local_today(),
                                    clinic["doctor"].id)
        (Appointment.query.filter_by(patient_id=clinic["brother"].id)
         .one().doctor_id) = clinic["other"].id
        clinic["db"].session.flush()
        assert not fr._sibling_rule_met(sibling, child, local_today(),
                                        clinic["doctor"].id)
        # …unless the clinic said the offer isn't tied to one doctor.
        sibling.same_doctor = False
        assert fr._sibling_rule_met(sibling, child, local_today(),
                                    clinic["doctor"].id)


def test_the_club_card_reaches_the_sibling(clinic):
    """The card is in the brother's name; the family is still a member."""
    child, member = clinic["child"], clinic["member"]
    with clinic["app"].test_request_context("/"):
        assert not any(c.payer_id == clinic["club"].id for c in child.coverages)
        assert member.applies_to(child, clinic["doctor"].id, date.today())
        member.family_wide = False          # a genuinely personal card
        assert not member.applies_to(child, clinic["doctor"].id, date.today())


def test_a_discount_can_target_one_service(clinic):
    from app.blueprints.finance import routes as fr

    with clinic["app"].test_request_context("/"):
        sibling = clinic["sibling"]
        sibling.scope = "all"
        sibling.service_id = clinic["exam"].id
        inv = _invoice(clinic, [(clinic["exam"], 200), (clinic["echo"], 800)],
                       "T-4")
        assert fr._discount_worth(inv, sibling) == 100.0   # the exam only
        fr._apply_named_discount(inv, sibling)
        assert [i.discount_value for i in inv.items] == [100.0, 0]


def test_reception_can_override_or_refuse_the_automatic_pick(clinic):
    from app.blueprints.finance import routes as fr

    app, member = clinic["app"], clinic["member"]
    cases = {"": (None, True),                 # let the system choose
             "none": (None, False),            # no discount on this bill
             str(member.id): (member, False)}  # the cashier's own choice
    for raw, expected in cases.items():
        with app.test_request_context("/", method="POST",
                                      data={"discount_id": raw}):
            assert fr._chosen_discount() == expected


def test_a_special_discount_is_never_picked_automatically(clinic):
    """"خصم خاص" exists to be granted by hand, for one bill."""
    from app.blueprints.finance import routes as fr
    from app.models import NamedDiscount

    with clinic["app"].test_request_context("/"):
        clinic["db"].session.add(NamedDiscount(
            name="خصم خاص", dtype="special", value=90, is_percent=True,
            scope="all", auto_apply=True, is_active=True))
        clinic["db"].session.flush()
        inv = _invoice(clinic, [(clinic["exam"], 200)], "T-5")
        assert fr._best_discount(inv, clinic["child"],
                                 clinic["doctor"].id) is clinic["sibling"]
