"""The drugs a ward gives — on the bill, and off the shelf.

The last gap in the inpatient accounting, and the plainest one: a child on a
ward was given four doses of an antibiotic a day for three days, and the
clinic neither charged for any of it nor saw twelve doses missing from the
store. The drug round recorded every one of them faithfully — it just recorded
them nowhere the money or the stock could see.

**A dose is charged when three things are true**, and each is a decision:

1. **It was given.** A held or refused dose burns nothing and is owed nothing,
   which is the whole reason the outcome is recorded rather than inferred from
   a gap in the chart.
2. **The order names a store item.** Nullable, and that nullability is the
   feature's own switch: an order with no shelf behind it is written, given
   and charted exactly as before. A clinic that keeps its ward drugs on paper
   is untouched — the same rule as a bed with no rate on it.
3. **Nobody has billed it yet.** The dose carries the invoice line it went
   onto, so the posting is safe to run again — the bed nights use a unique
   night for the same job.

**And a dose is never refused for want of stock.** The ward gave the drug;
that happened. A program that declines to record it because its own count says
the shelf is empty has replaced a true fact with a tidy one. The movement is
posted and the stock is allowed to go negative, which is a discrepancy for the
store to reconcile rather than a dose to lose.

**One bill for the stay.** The doses land on the same invoice as the nights,
so a family gets one account rather than a bed bill and a pharmacy bill for
the same three days — and the drugs go through the same insurance, discount
and ledger door that everything else does.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A ward, a priced night, and an antibiotic on the shelf."""
    from app.models import Service, Setting, StoreItem, User
    from app.models.place import Bed, Space, Unit
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        for module in ("observations", "beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")

        nurse = User(username="nurse", full_name="الممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)

        night = Service(name="ليلة داخلي", category="other", price=500)
        clinic["db"].session.add(night)
        drug = StoreItem(name="أموكسيسيلين ٥٠٠", unit="جرعة", item_type="drug",
                         sell_price=25, purchase_price=10, is_active=True)
        gauze = StoreItem(name="شاش", unit="قطعة", item_type="consumable",
                          sell_price=5, purchase_price=2, is_active=True)
        clinic["db"].session.add_all([drug, gauze])
        clinic["db"].session.flush()

        unit = Unit(name="الداخلي", kind="ward", rate_service_id=night.id)
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        clinic["db"].session.add(Bed(space_id=space.id, name="د١"))
        clinic["db"].session.commit()

        clinic["bed"] = Bed.query.first().id
        clinic["drug_item"] = drug.id
        clinic["gauze"] = gauze.id
    return clinic


def _child(clinic, name):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"S{name}", full_name=name,
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=800))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, days_ago=2):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(clinic["bed"]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        clinic["db"].session.commit()
        return row.id


def _order(clinic, admission_id, store_item_id=None, units=1, hours_ago=30):
    from app.models.admission import Admission
    from app.utils import drug_round

    with clinic["app"].app_context():
        row = drug_round.order(
            clinic["db"].session.get(Admission, admission_id),
            "أموكسيسيلين", dose="250 mg", every_hours=8,
            store_item_id=store_item_id, units_per_dose=units,
            when=datetime.utcnow() - timedelta(hours=hours_ago))
        clinic["db"].session.commit()
        return row.id


def _give(clinic, order_id, outcome="given", hours_ago=1, reason=None):
    from app.models.medication import MedicationOrder
    from app.utils import drug_round

    with clinic["app"].app_context():
        drug_round.give(clinic["db"].session.get(MedicationOrder, order_id),
                        outcome, reason=reason,
                        at=datetime.utcnow() - timedelta(hours=hours_ago))
        clinic["db"].session.commit()


def _charge(clinic, admission_id):
    from app.models.admission import Admission
    from app.utils import bed_billing

    with clinic["app"].app_context():
        return bed_billing.charge(
            clinic["db"].session.get(Admission, admission_id))


def _stock(clinic, item_id):
    from app.models import StoreItem

    with clinic["app"].app_context():
        return clinic["db"].session.get(StoreItem, item_id).current_stock


def _bill(clinic, admission_id):
    from app.models.invoice import Invoice

    with clinic["app"].app_context():
        row = Invoice.query.filter_by(admission_id=admission_id).one()
        return {"id": row.id, "total": row.total, "lines": len(row.items),
                "descriptions": [i.description for i in row.items],
                "prices": [i.unit_price for i in row.items],
                "quantities": [i.quantity for i in row.items],
                "commissions": [i.commission_amount for i in row.items]}


# ------------------------------------------------------- given, and only -----
def test_a_dose_that_was_given_is_charged_and_taken_off_the_shelf(ward):
    """**The whole of the gap, in one test.** Twelve doses given and neither
    the money nor the store ever heard about any of them."""
    child = _child(ward, "اداله")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    for hours in (28, 20, 12):
        _give(ward, order, hours_ago=hours)

    result = _charge(ward, admission)

    assert result["doses"] == 3
    assert _stock(ward, ward["drug_item"]) == -3
    bill = _bill(ward, admission)
    # Two nights at 500 and three doses at 25.
    assert bill["total"] == 2 * 500 + 3 * 25


def test_a_held_dose_costs_nothing_and_leaves_the_shelf_alone(ward):
    """Nothing was given, so nothing is owed and nothing left the store. This
    is what the recorded outcome buys: the program can tell a dose that was
    withheld from one that was given, which a gap in the chart cannot."""
    child = _child(ward, "اتأجل")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, "given", hours_ago=20)
    _give(ward, order, "held", hours_ago=8, reason="بيرجّع")
    _give(ward, order, "refused", hours_ago=2, reason="الأهل رفضوا")

    result = _charge(ward, admission)

    assert result["doses"] == 1
    assert _stock(ward, ward["drug_item"]) == -1


def test_an_order_with_no_store_item_charges_nothing(ward):
    """The feature's own switch. A clinic that keeps its ward drugs on paper
    writes the order, gives it, charts it — and is billed nothing and deducted
    nothing, exactly as before."""
    child = _child(ward, "بدون_صنف")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=None)
    for hours in (20, 12, 4):
        _give(ward, order, hours_ago=hours)

    result = _charge(ward, admission)

    assert result["doses"] == 0
    assert _stock(ward, ward["drug_item"]) == 0
    # The nights still bill; it is the drug that is silent.
    assert result["periods"] == 2


def test_pressing_twice_does_not_charge_a_dose_twice(ward):
    """The dose carries the line it went onto, which is what makes the second
    press safe — the same job the unique night does for a bed charge."""
    child = _child(ward, "مرتين_جرعة")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=20)
    _give(ward, order, hours_ago=12)

    first = _charge(ward, admission)
    second = _charge(ward, admission)

    assert first["doses"] == 2
    assert second["doses"] == 0
    assert _stock(ward, ward["drug_item"]) == -2
    assert _bill(ward, admission)["lines"] == 2 + 2


def test_a_dose_given_after_the_first_posting_is_picked_up(ward):
    """A stay is not billed once. Thursday's doses go onto the same bill on
    Thursday, and none of Tuesday's are charged again."""
    child = _child(ward, "بعدين")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=20)
    _charge(ward, admission)

    _give(ward, order, hours_ago=2)
    again = _charge(ward, admission)

    assert again["doses"] == 1
    assert _stock(ward, ward["drug_item"]) == -2


# ---------------------------------------------------------- how many units --
def test_two_ampoules_make_one_dose(ward):
    """The store's dispense unit is a dose, and one administration is one unit
    of it — unless the order says otherwise, which on a ward it often does."""
    child = _child(ward, "أمبولتين")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"], units=2)
    _give(ward, order, hours_ago=10)

    _charge(ward, admission)

    assert _stock(ward, ward["drug_item"]) == -2
    bill = _bill(ward, admission)
    assert 2 in bill["quantities"]


def test_a_blank_unit_count_is_one_and_never_zero(ward):
    """A blank box must not write an order that takes nothing off the shelf
    however often it is given — which would be a drug the store never misses
    and the family never pays for."""
    from app.models.admission import Admission
    from app.models.medication import MedicationOrder
    from app.utils import drug_round

    child = _child(ward, "صفر")
    admission = _admit(ward, child)
    with ward["app"].app_context():
        row = drug_round.order(
            ward["db"].session.get(Admission, admission), "دوا",
            every_hours=8, store_item_id=ward["drug_item"],
            units_per_dose=0)
        ward["db"].session.commit()
        assert ward["db"].session.get(MedicationOrder, row.id).units_per_dose == 1


# ------------------------------------------------- the shelf may go short ----
def test_a_dose_is_never_refused_because_the_shelf_looks_empty(ward):
    """The ward gave the drug; that happened. A program that declines to
    record it because its own count says the shelf is empty has replaced a
    true fact with a tidy one — and the dose would vanish from the chart as
    well as from the store."""
    child = _child(ward, "مخزن_فاضي")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    for hours in (20, 12, 4):
        _give(ward, order, hours_ago=hours)

    assert _stock(ward, ward["drug_item"]) == 0          # nothing was ever in
    result = _charge(ward, admission)

    assert result["doses"] == 3
    assert _stock(ward, ward["drug_item"]) == -3


# ------------------------------------------------------------- one bill -----
def test_the_doses_land_on_the_stays_own_invoice(ward):
    """One account for the stay, not a bed bill plus a pharmacy bill for the
    same three days."""
    from app.models.invoice import Invoice

    child = _child(ward, "فاتورة_واحدة")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)
    _charge(ward, admission)

    with ward["app"].app_context():
        assert Invoice.query.filter_by(patient_id=child).count() == 1


def test_a_dose_line_carries_no_doctor_commission(ward):
    """Nobody's percentage rides on a nurse pushing a syringe. A store item is
    not a ``Service``, so the line has no service behind it and no share to
    compute — and that is the right answer rather than an accident."""
    child = _child(ward, "بدون_نسبة")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)
    _charge(ward, admission)

    bill = _bill(ward, admission)
    drug_lines = [c for c, d in zip(bill["commissions"], bill["descriptions"])
                  if "أموكسيسيلين" in d]
    assert drug_lines and all(not c for c in drug_lines)


def test_the_line_says_which_drug_and_when(ward):
    """The question a family asks of this line is "what is this 25 pounds",
    and "a drug" is not an answer."""
    child = _child(ward, "وصف")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)
    _charge(ward, admission)

    described = [d for d in _bill(ward, admission)["descriptions"]
                 if "أموكسيسيلين" in d]
    assert described, _bill(ward, admission)["descriptions"]
    assert "250 mg" in described[0]


def test_the_cost_of_the_drugs_reaches_the_ledger(ward):
    """The issue document rides on the invoice, so the **cost of goods** is
    journalled in the same posting the till already does for a service's
    consumables.

    Asserted on the store entry and not merely on the document: the first
    version checked that an issue document existed and that the invoice was
    journalled, and both stayed true with the document never handed to the
    ledger at all — the drugs were sold and their cost was never booked.
    """
    from app.models import JournalEntry, StoreDocument, StockMovement

    child = _child(ward, "تكلفة")
    admission = _admit(ward, child)
    # Put stock in first, so the issue has a cost to book against it.
    with ward["app"].app_context():
        ward["db"].session.add(StockMovement(
            item_id=ward["drug_item"], kind="in", qty=20, unit_cost=10))
        ward["db"].session.commit()

    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)
    _charge(ward, admission)

    with ward["app"].app_context():
        document = StoreDocument.query.filter_by(kind="issue").one()
        assert JournalEntry.query.filter_by(source_type="invoice").count() == 1
        cost = JournalEntry.query.filter_by(source_type="store_doc",
                                            source_id=document.id).one()
        moved = {(line.account.code, line.debit, line.credit)
                 for line in cost.lines}
        # Debit cost of sales, credit the stock it came out of.
        assert ("5020", 10.0, 0.0) in moved
        assert ("1040", 0.0, 10.0) in moved


def test_one_issue_document_holds_the_whole_round(ward):
    """Three doses posted together are one issue out of the store, not three
    — the same rule the till already keeps for a service's consumables."""
    from app.models import StoreDocument

    child = _child(ward, "مستند_واحد")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    for hours in (20, 12, 4):
        _give(ward, order, hours_ago=hours)
    _charge(ward, admission)

    with ward["app"].app_context():
        assert StoreDocument.query.filter_by(kind="issue").count() == 1


# ---------------------------------------------------------------- the door --
def test_the_order_form_offers_the_shelf(ward):
    """A feature nobody can switch on is a feature that does not exist. The
    picker is on the order form, and "not deducted" is its first option."""
    from app.i18n import t

    child = _child(ward, "بوابة")
    admission = _admit(ward, child)

    page = ward["sign_in"]("doc").get(
        f"/beds/admission/{admission}").get_data(as_text=True)

    assert "data-store-item" in page
    assert 'name="units_per_dose"' in page
    with ward["app"].test_request_context("/"):
        assert t("meds.no_store_item") in page
    assert "أموكسيسيلين ٥٠٠" in page


def test_the_order_written_from_the_screen_carries_the_item(ward):
    """Through the route, because a utility can be right while the form drops
    the field on the floor."""
    from app.models.medication import MedicationOrder

    child = _child(ward, "من_الشاشة")
    admission = _admit(ward, child)

    ward["sign_in"]("doc").post(
        f"/beds/admission/{admission}/medication",
        data={"drug_name": "أموكسيسيلين", "every_hours": 8,
              "store_item_id": ward["drug_item"], "units_per_dose": 2},
        follow_redirects=True)

    with ward["app"].app_context():
        row = MedicationOrder.query.filter_by(admission_id=admission).one()
        assert row.store_item_id == ward["drug_item"]
        assert row.units_per_dose == 2


def test_the_screen_says_the_doses_were_charged(ward):
    """Money and stock both moved. Saying nothing would leave both to be
    discovered — one on the bill, one at the next stock count."""
    from app.i18n import t

    child = _child(ward, "قال")
    admission = _admit(ward, child)
    order = _order(ward, admission, store_item_id=ward["drug_item"])
    _give(ward, order, hours_ago=10)

    page = ward["sign_in"]("boss").post(
        f"/beds/admission/{admission}/nights", data={},
        follow_redirects=True).get_data(as_text=True)

    with ward["app"].test_request_context("/"):
        assert t("meds.n_doses_charged", n=1) in page


# --------------------------------------------------------------- migration --
def test_the_new_columns_reach_a_clinic_that_already_has_the_tables():
    """The four tables shipped in the release that added the wards, so a
    clinic already running it has them **without** these columns — and
    ``create_all`` adds tables, never columns to a table that exists."""
    from app.utils.schema import ADDITIONS

    covered = {(table, column) for table, column, _ddl in ADDITIONS}
    for table, column in (("medication_orders", "store_item_id"),
                          ("medication_orders", "units_per_dose"),
                          ("medication_doses", "invoice_item_id"),
                          ("medication_doses", "stock_movement_id")):
        assert (table, column) in covered, f"{table}.{column}"


def test_every_word_on_the_dose_charge_exists_in_both_languages():
    import json

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        ar = json.load(fh)
    with open("app/i18n/locales/en.json", encoding="utf-8") as fh:
        en = json.load(fh)

    for key in ("given_on_ward", "from_store", "no_store_item",
                "units_per_dose", "n_doses_charged"):
        assert key in ar["meds"] and key in en["meds"]
        assert ar["meds"][key] != en["meds"][key]
