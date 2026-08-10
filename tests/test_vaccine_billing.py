"""The vial and the fee for giving it are two charges.

Reported from the cashier screen: *"why is the vaccination fee showing as a
service above the vaccine? Somebody could discount the fee and still collect the
vaccine's price."*

The design was already right in intent — the vial bills at the brand's price
with no commission (the doctor's share is tracked on the dose), and the
administration fee is added once. But **both lines were written with the
vaccination-fee service's id**, so as far as the discount engine was concerned
they were the same kind of charge. A rule aimed at "رسم تطعيم" — by category or
by that exact service, the narrowest targeting the program offers — reduced the
price of the vaccine too.

A vial is not a service. It is stock with a purchase price, sold on. Giving it
is the service. Once they are told apart, each can be discounted deliberately
and neither by accident, which is the whole point: a clinic that wants to waive
the fee for a staff member's child should not thereby be giving away a
900-pound vial.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# One clock. The program works, bills and counts "today" with
# ``local_today``; a test that builds its data with ``date.today``
# is on another day whenever the server's zone and the clinic's
# differ — every night after 22:00 UTC for a Cairo clinic.
from app.utils.clock import local_today  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture()
def billed(clinic):
    """A vaccination-fee service, and an invoice with a vial line and a fee line."""
    from app.models import Invoice, InvoiceItem, Service

    with clinic["app"].app_context():
        fee = Service(name="رسم تطعيم", code="SVC-VACFEE", price=100,
                      category="vaccination_fee", commission_type="fixed",
                      commission_value=20, is_active=True)
        clinic["db"].session.add(fee)
        clinic["db"].session.flush()

        inv = Invoice(invoice_number="INV-V001",
                      patient_id=clinic["ids"]["child"],
                      invoice_date=local_today(), status="issued")
        clinic["db"].session.add(inv)
        clinic["db"].session.flush()
        # The vial: priced by its brand, carrying no service.
        inv.items.append(InvoiceItem(
            description="المكورات — Prevenar", quantity=1, unit_price=900,
            vaccine_brand_id=clinic["ids"]["brand"]))
        # The fee for giving it: a service, like any other.
        inv.items.append(InvoiceItem(
            description="رسم تطعيم", quantity=1, unit_price=100,
            service_id=fee.id))
        clinic["db"].session.commit()
        clinic["fee_service"] = fee.id
        clinic["invoice"] = inv.id
    return clinic


def _lines(billed):
    from app.models import Invoice

    inv = billed["db"].session.get(Invoice, billed["invoice"])
    vial = next(i for i in inv.items if i.vaccine_brand_id)
    fee = next(i for i in inv.items if i.service_id)
    return vial, fee


def _rule(billed, **kw):
    from app.models import NamedDiscount

    row = NamedDiscount(name=kw.pop("name", "خصم"), value=kw.pop("value", 50),
                        is_percent=True, is_active=True, **kw)
    billed["db"].session.add(row)
    billed["db"].session.flush()
    return row


# ------------------------------------------------ telling them apart -------
def test_a_discount_on_the_fee_does_not_touch_the_vials_price(billed):
    """The reported bug, stated as the rule it broke."""
    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope="vaccination_fee")
        assert rule.applies_to_line(fee) is True
        assert rule.applies_to_line(vial) is False


def test_a_discount_on_that_exact_service_does_not_touch_the_vial(billed):
    """The narrowest targeting the program offers — and the worst place for
    the two charges to be confused, because somebody aiming this precisely is
    being deliberate."""
    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, service_id=billed["fee_service"])
        assert rule.applies_to_line(fee) is True
        assert rule.applies_to_line(vial) is False


def test_the_vial_can_still_be_discounted_on_purpose(billed):
    """Separating them must not make the vial undiscountable — that would trade
    one wrong answer for another. It gets its own scope."""
    from app.models import VACCINE_SCOPE

    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope=VACCINE_SCOPE)
        assert rule.applies_to_line(vial) is True
        assert rule.applies_to_line(fee) is False


def test_a_clinic_wide_discount_still_reaches_both(billed):
    """A campaign that says "everything 10% today" means everything."""
    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope="all")
        assert rule.applies_to_line(vial) is True
        assert rule.applies_to_line(fee) is True


def test_an_unrelated_category_reaches_neither(billed):
    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope="consultation")
        assert rule.applies_to_line(vial) is False
        assert rule.applies_to_line(fee) is False


def test_a_free_text_line_is_only_reached_by_an_all_discount(billed):
    """No service and no brand — there is nothing narrower to aim at, so a
    scoped rule must not guess."""
    from app.models import InvoiceItem

    with billed["app"].app_context():
        loose = InvoiceItem(description="حاجة", quantity=1, unit_price=50)
        assert _rule(billed, scope="all").applies_to_line(loose) is True
        assert _rule(billed, scope="consultation").applies_to_line(loose) is False
        from app.models import VACCINE_SCOPE
        assert _rule(billed, scope=VACCINE_SCOPE).applies_to_line(loose) is False


# --------------------------------------------- what the money comes to -----
def test_the_money_lands_where_it_should(billed):
    """The complaint in figures: 50% off the fee should take 50, not 500."""
    from app.blueprints.finance.routes import _line_discount_amount

    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope="vaccination_fee", value=50)
        assert _line_discount_amount(fee, rule) == 50.0
        assert _line_discount_amount(vial, rule) == 0.0


def test_the_vial_keeps_its_full_price_when_only_the_fee_is_waived(billed):
    """A staff member's child gets the fee waived; the clinic does not give
    away a 900-pound vial with it."""
    from app.blueprints.finance.routes import _line_discount_amount

    with billed["app"].app_context():
        vial, fee = _lines(billed)
        rule = _rule(billed, scope="vaccination_fee", value=100)
        assert _line_discount_amount(fee, rule) == 100.0
        assert _line_discount_amount(vial, rule) == 0.0


# --------------------------------------------------- the prefilled lines ---
def test_the_prefilled_vial_line_carries_no_service(billed):
    """Where the confusion came from: the prefill wrote the fee's service id
    onto the vial's line. It carries the brand instead, which is what the vial
    actually is."""
    from app.blueprints.finance.routes import _vaccine_prefill_lines
    from app.models import PatientVaccine

    with billed["app"].app_context():
        billed["db"].session.add(PatientVaccine(
            patient_id=billed["ids"]["child"], vaccine_id=billed["ids"]["pcv"],
            brand_id=billed["ids"]["brand"], dose_number=1,
            given_date=local_today(), event_type="given"))
        billed["db"].session.commit()

        lines = _vaccine_prefill_lines(billed["ids"]["child"], None, "ar", False)
        vials = [ln for ln in lines if ln.get("brand_id")]
        assert vials, "the uncharged dose should have produced a vial line"
        for line in vials:
            assert not line["service_id"]
            assert line["brand_id"] == billed["ids"]["brand"]


def test_the_fee_line_still_carries_the_fee_service(billed):
    """Only the vial changed. The fee is a service and stays one, or it drops
    out of revenue-by-service and out of the doctor's commission.

    Today's invoice is cleared first: with a fee already on it the prefill
    correctly declines to add a second one, which is the next test.
    """
    from app.blueprints.finance.routes import _vaccine_prefill_lines
    from app.models import Invoice, PatientVaccine

    with billed["app"].app_context():
        inv = billed["db"].session.get(Invoice, billed["invoice"])
        billed["db"].session.delete(inv)
        billed["db"].session.add(PatientVaccine(
            patient_id=billed["ids"]["child"], vaccine_id=billed["ids"]["pcv"],
            brand_id=billed["ids"]["brand"], dose_number=1,
            given_date=local_today(), event_type="given"))
        billed["db"].session.commit()

    # The fee line is labelled through `t()`, which reads the request's
    # language, so this one needs a request context where the others did not.
    with billed["app"].test_request_context():
        lines = _vaccine_prefill_lines(billed["ids"]["child"], None, "ar", False)
        fees = [ln for ln in lines if not ln.get("brand_id")]
        assert fees, "the administration fee line should have been added"
        assert all(ln["service_id"] for ln in fees)


def test_the_fee_is_not_charged_twice_on_the_same_day(billed):
    """Found while writing the test above, and worth keeping: today's invoice
    already carries a vaccination fee, so collecting a leftover dose adds the
    vial and **not** a second fee. One visit, one act of giving."""
    from app.blueprints.finance.routes import _vaccine_prefill_lines
    from app.models import PatientVaccine

    with billed["app"].app_context():
        billed["db"].session.add(PatientVaccine(
            patient_id=billed["ids"]["child"], vaccine_id=billed["ids"]["pcv"],
            brand_id=billed["ids"]["brand"], dose_number=1,
            given_date=local_today(), event_type="given"))
        billed["db"].session.commit()

        lines = _vaccine_prefill_lines(billed["ids"]["child"], None, "ar", False)
        assert [ln for ln in lines if ln.get("brand_id")]      # the vial
        assert not [ln for ln in lines if not ln.get("brand_id")]  # no 2nd fee
