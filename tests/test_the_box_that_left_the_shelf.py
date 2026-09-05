"""The pharmacy counter — the act nothing recorded.

``HOSPITAL_PLAN.md`` مرحلة ج بند ٧ names three things and **two of them were
already built**: the paediatric dose (``dosing``) and the interaction and
allergy checks (``rx_safety``), both shown to the doctor by the prescription
writer for years. Neither is rebuilt here, and one of the tests below exists
to keep it that way — a second rulebook at the counter would defeat the whole
purpose of a second pair of eyes.

**What had no row anywhere is the handover.** A prescription was written,
printed, and that was the end of it as far as this software was concerned: the
box left the shelf without the clinic's own stock knowing, and nothing was
charged.

Three rules are asserted here more than anything else:

1. **A line with no box of ours on it is filled outside** — nothing leaves the
   stock, nothing is charged, and the clinic that works that way is untouched.
2. **The pharmacist asks, never refuses.** A query is recorded and the line
   stays dispensable.
3. **A box is never refused for want of stock.** The pharmacy handed it over;
   that happened, and the count going negative is the store's problem rather
   than a medicine to take back off a child.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def counter(clinic):
    """A clinic with a pharmacy, one medicine on the shelf, one prescription."""
    from app.models import (Prescription, PrescriptionItem, Setting, StoreItem,
                            User)
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        Setting.set("mod_enabled:pharmacy", "1")

        chemist = User(username="chem", full_name="الصيدلي", role="pharmacy",
                       is_active=True)
        chemist.set_password("secret")
        clinic["db"].session.add(chemist)

        box = StoreItem(name="أموكسيسيلين شراب", unit="زجاجة", item_type="drug",
                        sell_price=60, purchase_price=25, is_active=True)
        gloves = StoreItem(name="قفازات", unit="علبة", item_type="consumable",
                           sell_price=30, purchase_price=10, is_active=True)
        clinic["db"].session.add_all([box, gloves])
        clinic["db"].session.flush()

        rx = Prescription(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          created_at=datetime.utcnow())
        clinic["db"].session.add(rx)
        clinic["db"].session.flush()
        first = PrescriptionItem(prescription_id=rx.id,
                                 drug_name="أموكسيسيلين", dose="5 مل",
                                 frequency="٣ مرات يومياً")
        second = PrescriptionItem(prescription_id=rx.id, drug_name="فيتامين د",
                                  dose="نقطة")
        clinic["db"].session.add_all([first, second])
        clinic["db"].session.commit()

        clinic["chemist"] = chemist.id
        clinic["box"] = box.id
        clinic["gloves"] = gloves.id
        clinic["rx"] = rx.id
        clinic["line"] = first.id
        clinic["other_line"] = second.id
    return clinic


def _state(counter, line_id):
    from app.models import PrescriptionItem

    with counter["app"].app_context():
        row = counter["db"].session.get(PrescriptionItem, line_id)
        return {"shelf": row.store_item_id, "quantity": row.quantity,
                "dispensed": row.dispensed_at is not None,
                "at": row.dispensed_at,
                "dispensed_by": row.dispensed_by,
                "billed": row.invoice_item_id is not None,
                "moved": row.stock_movement_id is not None,
                "query": row.query_note}


def _stock(counter, item_id):
    from app.models import StoreItem

    with counter["app"].app_context():
        return counter["db"].session.get(StoreItem, item_id).current_stock


def _collect(counter, line_id, price="60", qty="2"):
    """The desk takes the money. Not the pharmacist: they hand the box over
    and the cashier collects, and the pharmacy role has no finance screen."""
    return counter["sign_in"]("boss").post(
        f"/finance/collect/{counter['ids']['child']}", data={
            "doctor_id": counter["ids"]["doctor"], "discount_id": "none",
            "line_service_id": [""], "line_desc": ["أموكسيسيلين شراب"],
            "line_price": [price], "line_qty": [qty],
            "line_no_commission": ["1"], "line_brand_id": [""],
            "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
            "line_op_id": [""], "line_test_id": [""],
            "line_rx_line_id": [str(line_id)],
        }, follow_redirects=True)


def _put_on_shelf(counter, line=None, quantity=1):
    client = counter["sign_in"]("chem")
    client.post(f"/pharmacy/line/{line or counter['line']}/shelf",
                data={"store_item_id": counter["box"], "quantity": quantity},
                follow_redirects=True)
    return client


# ======================= filled outside is the normal case ==================
def test_a_line_with_no_box_of_ours_is_filled_outside(counter):
    """**The clinic this module must not disturb.** Families fill the paper at
    the pharmacy downstairs; nothing leaves our stock and nothing is charged.
    """
    from app.utils import pharmacy

    with counter["app"].app_context():
        from app.models import Prescription

        rx = counter["db"].session.get(Prescription, counter["rx"])
        assert pharmacy.pending(rx) == []
        assert pharmacy.queue() == []

    page = counter["sign_in"]("chem").get("/pharmacy/")
    assert "مفيش حاجة مستنية".encode() in page.data


def test_a_line_with_a_box_joins_the_queue(counter):
    """And only then."""
    from app.utils import pharmacy

    _put_on_shelf(counter)

    with counter["app"].app_context():
        assert [rx.id for rx in pharmacy.queue()] == [counter["rx"]]


def test_the_shelf_is_the_counters_call_not_the_doctors(counter):
    """Which of three strengths the clinic actually stocks is the pharmacy's
    knowledge, and asking the doctor mid-consultation is asking them to do
    somebody else's job with worse information."""
    _put_on_shelf(counter, quantity=2)

    state = _state(counter, counter["line"])
    assert state["shelf"] == counter["box"]
    assert state["quantity"] == 2


# ======================= handing it over ====================================
def test_handing_over_charges_it_and_takes_it_off_the_shelf(counter):
    """The whole of the gap: the box left and neither the money nor the stock
    ever heard about it."""
    from app.models.invoice import Invoice

    client = _put_on_shelf(counter, quantity=2)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    assert _state(counter, counter["line"])["dispensed"]

    # The desk, not the counter: a pharmacist hands the box over and the
    # cashier takes the money, and the pharmacy role has no finance screen.
    counter["sign_in"]("boss").post(f"/finance/collect/{counter['ids']['child']}", data={
        "doctor_id": counter["ids"]["doctor"], "discount_id": "none",
        "line_service_id": [""], "line_desc": ["أموكسيسيلين شراب"],
        "line_price": ["60"], "line_qty": ["2"],
        "line_no_commission": ["1"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
        "line_op_id": [""], "line_test_id": [""],
        "line_rx_line_id": [str(counter["line"])],
    }, follow_redirects=True)

    state = _state(counter, counter["line"])
    assert state["billed"] and state["moved"]
    # And it never comes back to the desk: the line carries what paid for it,
    # the same stamp the nights, the doses and the theatre cases use.
    again = counter["sign_in"]("boss").get(
        f"/finance/collect/{counter['ids']['child']}")
    assert b'"rx_line_id"' not in again.data
    # Two bottles at 60, off the shelf and onto the bill.
    assert _stock(counter, counter["box"]) == -2
    with counter["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.total == 120
        # No service on the line, so nobody's percentage rides on a box being
        # handed across a counter.
        assert [i.commission_amount or 0 for i in invoice.items] == [0]


def test_the_desk_offers_what_was_handed_over(counter):
    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    page = counter["sign_in"]("boss").get(
        f"/finance/collect/{counter['ids']['child']}")

    assert f'"rx_line_id": {counter["line"]}'.encode() in page.data
    # And the screen carries it into the form it submits — the checkout
    # rebuilds every line from a fixed list of fields.
    assert b"rx_line_id:l.rx_line_id" in page.data


def test_what_was_never_handed_over_is_never_offered(counter):
    """Written is not dispensed. A prescription the family took away costs the
    clinic nothing."""
    _put_on_shelf(counter)

    page = counter["sign_in"]("boss").get(
        f"/finance/collect/{counter['ids']['child']}")

    assert b'"rx_line_id"' not in page.data


def test_a_handed_over_line_leaves_the_queue(counter):
    """The queue is what is still owed. A line that stayed on it after being
    handed over would send the next pharmacist to fetch the same box."""
    from app.models import Prescription
    from app.utils import pharmacy

    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    with counter["app"].app_context():
        rx = counter["db"].session.get(Prescription, counter["rx"])
        assert pharmacy.pending(rx) == []
        assert pharmacy.queue() == []


def test_the_same_box_is_never_handed_over_twice(counter):
    """The second press is a keystroke on the wrong row. It must not move the
    time it was handed over, and must not put a second box on the bill."""
    from app.utils import pharmacy

    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    first = _state(counter, counter["line"])

    # Somebody else, later, pressing the same button on the same row.
    counter["sign_in"]("boss").post(
        f"/pharmacy/line/{counter['line']}/dispense", follow_redirects=True)

    with counter["app"].app_context():
        # One thing owed, once — not two boxes for one handover.
        assert len(pharmacy.unbilled(
            patient_id=counter["ids"]["child"])) == 1
    again = _state(counter, counter["line"])
    # **The moment it crossed the counter, unmoved.** Asserted on the time and
    # the name rather than on "is it dispensed": both stay true while a second
    # press quietly rewrites when the box was handed over and by whom, which
    # is the whole of what the record is for.
    assert again["at"] == first["at"]
    assert again["dispensed_by"] == counter["chemist"]


def test_the_handover_says_who_made_it(counter):
    """A box that left the shelf with nobody's name on it is a box nobody can
    be asked about."""
    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    assert _state(counter, counter["line"])["dispensed_by"] == counter["chemist"]


def test_the_quantity_can_be_settled_at_the_moment_of_handing_over(counter):
    """Two bottles were written and one is on the shelf: the number that ends
    up on the bill is the number that crossed the counter."""
    client = _put_on_shelf(counter, quantity=1)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                data={"quantity": "3"}, follow_redirects=True)

    assert _state(counter, counter["line"])["quantity"] == 3


def test_a_box_is_never_refused_for_want_of_stock(counter):
    """The pharmacy handed it over; that happened. Declining to record it
    because our own count says the shelf is empty replaces a true fact with a
    tidy one."""
    client = _put_on_shelf(counter, quantity=3)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    counter["sign_in"]("boss").post(f"/finance/collect/{counter['ids']['child']}", data={
        "doctor_id": counter["ids"]["doctor"], "discount_id": "none",
        "line_service_id": [""], "line_desc": ["أموكسيسيلين شراب"],
        "line_price": ["60"], "line_qty": ["3"],
        "line_no_commission": ["1"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
        "line_op_id": [""], "line_test_id": [""],
        "line_rx_line_id": [str(counter["line"])],
    }, follow_redirects=True)

    # Negative, and that is the honest number: a discrepancy for the store to
    # reconcile rather than a medicine to take back off a child.
    assert _stock(counter, counter["box"]) == -3


def test_the_cost_of_the_box_reaches_the_ledger(counter):
    """The issue document rides on the invoice, so the **cost of goods** is
    journalled in the same posting the till already does for a service's
    consumables.

    Asserted on the store entry and not merely on the document: a version that
    checked an issue document existed and the invoice was journalled stayed
    true with the document never handed to the ledger at all — the medicine
    was sold and its cost was never booked.
    """
    from app.models import JournalEntry, StockMovement, StoreDocument

    with counter["app"].app_context():
        # Stock in first, so the issue has a cost to book against it.
        counter["db"].session.add(StockMovement(
            item_id=counter["box"], kind="in", qty=10, unit_cost=25))
        counter["db"].session.commit()

    client = _put_on_shelf(counter, quantity=2)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    _collect(counter, counter["line"])

    with counter["app"].app_context():
        document = StoreDocument.query.filter_by(kind="issue").one()
        cost = JournalEntry.query.filter_by(source_type="store_doc",
                                            source_id=document.id).one()
        moved = {(line.account.code, line.debit, line.credit)
                 for line in cost.lines}
        # Debit cost of sales, credit the stock it came out of: two at 25.
        assert ("5020", 50.0, 0.0) in moved
        assert ("1040", 0.0, 50.0) in moved


def test_the_desk_line_is_prefilled_with_no_commission(counter):
    """Nobody's percentage rides on a box being handed across a counter.

    Asserted on what the screen is *filled with*, not on what a test posts: a
    hand-written form carrying the flag would pass while every real checkout
    quietly paid a commission on a bottle of syrup.
    """
    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    page = counter["sign_in"]("boss").get(
        f"/finance/collect/{counter['ids']['child']}")

    assert b'"no_commission": "1"' in page.data


def test_nothing_to_dispense_is_refused_and_says_so(counter):
    """A line with no box chosen has nothing to hand over."""
    client = counter["sign_in"]("chem")
    client.post(f"/pharmacy/line/{counter['other_line']}/dispense",
                follow_redirects=True)

    assert not _state(counter, counter["other_line"])["dispensed"]


# ======================= the question =======================================
def test_the_pharmacist_asks_and_the_line_stays_dispensable(counter):
    """**A question, never a veto.** The doctor may well have meant it, and a
    pharmacy that can block a prescription is one prescriptions get written
    around."""
    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/query",
                data={"note": "الجرعة عالية للوزن ده"}, follow_redirects=True)

    assert _state(counter, counter["line"])["query"] == "الجرعة عالية للوزن ده"

    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    assert _state(counter, counter["line"])["dispensed"]


def test_a_blank_question_is_refused(counter):
    """It would clear the flag and say nothing, which reads on the doctor's
    screen as "the pharmacy looked and was happy"."""
    from app.utils import pharmacy
    from app.models import PrescriptionItem

    with counter["app"].app_context():
        with pytest.raises(ValueError):
            pharmacy.query(counter["db"].session.get(PrescriptionItem,
                                                     counter["line"]),
                           note="   ")
        counter["db"].session.rollback()

    assert _state(counter, counter["line"])["query"] is None


def test_an_open_question_reaches_the_counter_screen(counter):
    """Without a list of them, a question asked at the counter is answered
    only if somebody walks round — the gap the results inbox closes for a film
    that came back."""
    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/query",
                data={"note": "نسأل الدكتور"}, follow_redirects=True)

    page = client.get("/pharmacy/")

    assert b"data-queries" in page.data
    assert "نسأل الدكتور".encode() in page.data


def test_an_answered_question_leaves_the_list(counter):
    """Handing the box over is the answer."""
    from app.utils import pharmacy

    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/query",
                data={"note": "نسأل"}, follow_redirects=True)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)

    with counter["app"].app_context():
        assert pharmacy.open_queries() == []


# ======================= the check is the same check ========================
def test_the_counter_shows_the_same_check_the_doctor_saw(counter):
    """A second pair of eyes reading a different rulebook is not a second pair
    of eyes. `review` calls `rx_safety` and adds nothing."""
    from app.models import Prescription
    from app.utils import pharmacy, rx_safety

    with counter["app"].app_context():
        rx = counter["db"].session.get(Prescription, counter["rx"])
        mine = pharmacy.review(rx)
        theirs = rx_safety.check(list(rx.items), patient=rx.patient)

        assert [line["name"] for line in mine["lines"]] == \
               [line["name"] for line in theirs["lines"]]
        assert mine["interactions"] == theirs["interactions"]


def test_each_warning_is_keyed_to_the_line_it_belongs_to(counter):
    """Never by position. Two lists that came back in the same order is an
    assumption that holds until somebody filters one of them and puts a dose
    warning under the wrong medicine."""
    from app.models import Prescription
    from app.utils import pharmacy

    with counter["app"].app_context():
        rx = counter["db"].session.get(Prescription, counter["rx"])
        found = pharmacy.review(rx)
        assert set(found["by_item"]) == {counter["line"],
                                         counter["other_line"]}
        assert found["by_item"][counter["line"]]["name"] == "أموكسيسيلين"


# ======================= the doors ==========================================
def test_the_module_off_means_the_counter_is_absent(counter):
    """A clinic whose families fill their prescriptions outside has no
    counter — not an empty one."""
    from app.models import Setting

    with counter["app"].app_context():
        Setting.set("mod_enabled:pharmacy", "0")
        counter["db"].session.commit()

    client = counter["sign_in"]("chem")
    assert client.get("/pharmacy/").status_code == 404
    assert client.get(f"/pharmacy/rx/{counter['rx']}").status_code == 404


def test_the_desk_says_nothing_about_the_counter_when_it_is_off(counter):
    from app.models import Setting

    client = _put_on_shelf(counter)
    client.post(f"/pharmacy/line/{counter['line']}/dispense",
                follow_redirects=True)
    with counter["app"].app_context():
        Setting.set("mod_enabled:pharmacy", "0")
        counter["db"].session.commit()

    page = counter["sign_in"]("boss").get(
        f"/finance/collect/{counter['ids']['child']}")

    assert page.status_code == 200
    assert b'"rx_line_id"' not in page.data


def test_the_pharmacy_role_can_reach_its_own_counter(counter):
    """The role was named for this job and could not reach it: they saw the
    prescription and had nowhere to record having handed anything over."""
    page = counter["sign_in"]("chem").get("/pharmacy/")

    assert page.status_code == 200


def test_only_medicines_are_offered_from_the_shelf(counter):
    """A prescription line is never a box of gloves, and a picker holding the
    whole store is a picker nobody uses."""
    _put_on_shelf(counter)

    page = counter["sign_in"]("chem").get(f"/pharmacy/rx/{counter['rx']}")

    assert "أموكسيسيلين شراب".encode() in page.data
    assert "قفازات".encode() not in page.data
