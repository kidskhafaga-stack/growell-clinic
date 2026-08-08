"""The fridge as a real warehouse, and a card that says what happened.

Two halves of one complaint: *"الثلاجة كمخزن جوّه الأصناف، ويتعمل جرد من
جوّاها"* and *"كارت الصنف — تقريباً احنا عاملينه بس محتاج افهمه أو نطوّر فيه"*.

**The fridge was a warehouse in name only.** ``kind="fridge"`` existed,
transfers between warehouses worked, and vaccine batches carried a warehouse
column — but nothing ever *received* into it. Every receipt landed in the
default warehouse, so a clinic could open the fridge, find it empty, and be
told by the same program that it held two hundred doses.

**The count kept nothing.** Counting rewrote ``qty_used`` and said nothing
else: no document, no time, no counter, and no way afterwards to tell a
correction from a dose that went into a child. It also counted every batch the
clinic owns as one shelf, which is not a count — nobody walks two rooms at
once.

**The card was a photograph of now.** Batches and what is left in them. A
store card is the history that explains now, and it is what somebody reaches
for when the shelf and the screen disagree. It is derived rather than stored,
so an existing clinic has its history on the day it upgrades instead of an
empty table and a note saying the record starts today.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _fridge(clinic, name="ثلاجة التطعيمات"):
    from app.models import Warehouse

    db = clinic["db"]
    Warehouse.default()                     # the main store exists first
    wh = Warehouse(name=name, kind="fridge", is_active=True)
    db.session.add(wh)
    db.session.commit()
    return wh.id


def _receive(clinic, qty=10, warehouse_id=None, who="boss"):
    data = {"brand_id": clinic["ids"]["brand"], "qty_received": qty,
            "receipt_reason": "purchase", "lot_number": "L1",
            "expiry_date": "2030-01-01"}
    if warehouse_id:
        data["warehouse_id"] = warehouse_id
    return clinic["sign_in"](who).post("/inventory/batch/new", data=data,
                                       follow_redirects=True)


def _batches(clinic):
    from app.models import VaccineInventory

    return VaccineInventory.query.order_by(VaccineInventory.id).all()


# ============================================== receiving into the fridge ===
def test_a_vaccine_receipt_goes_into_the_fridge(clinic):
    """The whole bug in one test: the fridge existed and nothing arrived."""
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)

    _receive(clinic)

    with clinic["app"].app_context():
        new = [b for b in _batches(clinic) if b.lot_number == "L1"]
        assert len(new) == 1
        assert new[0].warehouse_id == fridge_id, \
            "the vaccine was received into the general store"


def test_a_clinic_with_no_fridge_is_unchanged(clinic):
    """Most clinics have one warehouse. They must not acquire a second one, or
    start seeing stock in a place they never made."""
    from app.models import Warehouse

    _receive(clinic)

    with clinic["app"].app_context():
        assert Warehouse.query.count() == 1
        batch = [b for b in _batches(clinic) if b.lot_number == "L1"][0]
        assert batch.warehouse_id == Warehouse.default().id


def test_the_form_can_say_a_different_warehouse(clinic):
    """The fridge is a default, not a rule. A clinic with two fridges has to
    be able to say which one the delivery went in."""
    from app.models import Warehouse

    db = clinic["db"]
    with clinic["app"].app_context():
        _fridge(clinic)
        second = Warehouse(name="ثلاجة الفرع", kind="fridge", is_active=True)
        db.session.add(second)
        db.session.commit()
        second_id = second.id

    _receive(clinic, warehouse_id=second_id)

    with clinic["app"].app_context():
        assert [b for b in _batches(clinic)
                if b.lot_number == "L1"][0].warehouse_id == second_id


def test_a_keeper_cannot_receive_into_somebody_elses_store(clinic):
    """The warehouse arrives as a form field, and a field is not a permission.
    A keeper restricted to one store must not be able to put stock into
    another by editing the page."""
    from app.models import User, Warehouse

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
        other = Warehouse(name="مخزن تاني", kind="sub", is_active=True)
        db.session.add(other)
        # A store keeper of the fridge only — not an admin, who may go
        # anywhere by design.
        keeper = User(username="keeper", full_name="أمين المخزن",
                      role="pharmacy", is_active=True)
        keeper.set_password("secret")
        db.session.add(keeper)
        db.session.flush()
        fridge = db.session.get(Warehouse, fridge_id)
        fridge.keepers.append(keeper)
        db.session.commit()
        other_id = other.id

    _receive(clinic, warehouse_id=other_id, who="keeper")

    with clinic["app"].app_context():
        batch = [b for b in _batches(clinic) if b.lot_number == "L1"][0]
        assert batch.warehouse_id != other_id


# ============================================== counting one warehouse ======
def test_the_stocktake_counts_one_warehouse(clinic):
    """A batch in the general store must not appear on the fridge's count
    sheet — nobody can walk two rooms at once."""
    from app.models import VaccineInventory, Warehouse
    from app.utils import item_card as card

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
        main = Warehouse.default()
        db.session.add(VaccineInventory(brand_id=clinic["ids"]["brand"],
                                        lot_number="IN-STORE", qty_received=4,
                                        warehouse_id=main.id,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()

        fridge = db.session.get(Warehouse, fridge_id)
        lots = {b.lot_number for b in card.batches_in(fridge)}
        assert "IN-STORE" not in lots


def test_counting_writes_down_what_it_found(clinic):
    """"الجرد يوضّح توقيته" — and more than the time: what the shelf held,
    what was counted, and who counted it. Rewriting a number and saying
    nothing is how a stock figure becomes one nobody trusts."""
    from app.models import VaccineAdjustment, VaccineInventory

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
    _receive(clinic, qty=10, warehouse_id=fridge_id)

    with clinic["app"].app_context():
        batch = [b for b in _batches(clinic) if b.lot_number == "L1"][0]
        batch_id = batch.id

    clinic["sign_in"]("boss").post(
        f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}",
        data={f"count_{batch_id}": 7, "reason": "كسر"}, follow_redirects=True)

    with clinic["app"].app_context():
        adj = VaccineAdjustment.query.one()
        assert adj.was == 10 and adj.counted == 7 and adj.diff == -3
        assert adj.created_at is not None
        assert adj.created_by == clinic["ids"]["admin"]
        assert adj.warehouse_id == fridge_id
        assert adj.reason == "كسر"
        assert adj.document is not None, "the count produced no document"
        assert db.session.get(VaccineInventory, batch_id).qty_remaining == 7


def test_a_batch_that_matched_is_not_written_down(clinic):
    """A list of everything that was fine is noise. The document already says
    the whole warehouse was counted."""
    from app.models import VaccineAdjustment

    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
    _receive(clinic, qty=10, warehouse_id=fridge_id)

    with clinic["app"].app_context():
        batch_id = [b for b in _batches(clinic) if b.lot_number == "L1"][0].id

    clinic["sign_in"]("boss").post(
        f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}",
        data={f"count_{batch_id}": 10}, follow_redirects=True)

    with clinic["app"].app_context():
        assert VaccineAdjustment.query.count() == 0


def test_the_screen_says_when_it_was_last_counted(clinic):
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
    _receive(clinic, qty=10, warehouse_id=fridge_id)

    with clinic["app"].app_context():
        batch_id = [b for b in _batches(clinic) if b.lot_number == "L1"][0].id

    boss = clinic["sign_in"]("boss")
    page = boss.get(f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}").data.decode()
    assert _word("never_counted") in page

    boss.post(f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}",
              data={f"count_{batch_id}": 7}, follow_redirects=True)
    page = boss.get(f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}").data.decode()
    assert _word("last_counted") in page


def _word(key, section="inventory", lang="ar"):
    import json

    path = os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                        "locales", f"{lang}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)[section][key]


# ============================================== the movement card ===========
def test_the_card_shows_a_receipt_and_a_dose(clinic):
    """The two movements every vaccine makes, and the balance between them."""
    from app.models import PatientVaccine, VaccineBrand
    from app.utils import item_card as card

    db = clinic["db"]
    _receive(clinic, qty=10)

    with clinic["app"].app_context():
        batch = [b for b in _batches(clinic) if b.lot_number == "L1"][0]
        batch.qty_used = 1
        db.session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=1,
            given_date=date.today(), inventory_id=batch.id))
        db.session.commit()

        rows = card.ledger(db.session.get(VaccineBrand, clinic["ids"]["brand"]))
        kinds = [(r["reason"], r["qty"]) for r in rows if r["batch"].lot_number == "L1"]
        assert ("purchase", 10) in kinds
        assert ("dose", -1) in kinds
        assert rows[-1]["balance"] == sum(r["qty"] for r in rows)


def test_a_count_appears_on_the_card(clinic):
    """The reason the adjustment is stored at all: so the card can explain a
    balance that no receipt and no dose accounts for."""
    from app.models import VaccineBrand
    from app.utils import item_card as card

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
    _receive(clinic, qty=10, warehouse_id=fridge_id)
    with clinic["app"].app_context():
        batch_id = [b for b in _batches(clinic) if b.lot_number == "L1"][0].id

    clinic["sign_in"]("boss").post(
        f"/inventory/vaccine-stocktake?warehouse_id={fridge_id}",
        data={f"count_{batch_id}": 6}, follow_redirects=True)

    with clinic["app"].app_context():
        rows = card.ledger(db.session.get(VaccineBrand, clinic["ids"]["brand"]))
        counts = [r for r in rows if r["reason"] == "stocktake"]
        assert len(counts) == 1
        assert counts[0]["qty"] == -4
        assert counts[0]["at"] is not None, "the card cannot say when"


def test_the_card_can_be_asked_about_one_warehouse(clinic):
    """"What happened to this vaccine" and "what happened in the fridge" are
    different questions, and a clinic with two fridges needs the second."""
    from app.models import VaccineBrand, VaccineInventory, Warehouse
    from app.utils import item_card as card

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
        db.session.add(VaccineInventory(brand_id=clinic["ids"]["brand"],
                                        lot_number="IN-STORE", qty_received=4,
                                        warehouse_id=Warehouse.default().id,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()
    _receive(clinic, qty=10, warehouse_id=fridge_id)

    with clinic["app"].app_context():
        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        fridge = db.session.get(Warehouse, fridge_id)
        lots = {r["batch"].lot_number for r in card.ledger(brand, fridge)}
        assert lots == {"L1"}


def test_stock_that_left_without_a_dose_is_not_hidden(clinic):
    """A transfer out grows ``qty_used`` and writes nothing of its own. A card
    whose closing balance quietly disagrees with the shelf is worse than one
    that says "something else took four"."""
    from app.models import VaccineBrand
    from app.utils import item_card as card

    db = clinic["db"]
    _receive(clinic, qty=10)

    with clinic["app"].app_context():
        batch = [b for b in _batches(clinic) if b.lot_number == "L1"][0]
        batch.qty_used = 4               # as a transfer out would leave it
        db.session.commit()

        rows = card.ledger(db.session.get(VaccineBrand, clinic["ids"]["brand"]))
        mine = [r for r in rows if r["batch"].lot_number == "L1"]
        assert ("other", -4) in [(r["reason"], r["qty"]) for r in mine]
        assert sum(r["qty"] for r in mine) == 6, "the card does not match the shelf"


def test_the_item_card_page_shows_the_movements(clinic):
    _receive(clinic, qty=10)

    page = clinic["sign_in"]("boss").get(
        f"/inventory/item/{clinic['ids']['brand']}").data.decode()
    assert _word("movement_card") in page
    assert _word("held_where") in page


# ============================================== where it is held ============
def test_stock_is_reported_per_warehouse(clinic):
    from app.models import VaccineBrand, Warehouse

    db = clinic["db"]
    with clinic["app"].app_context():
        fridge_id = _fridge(clinic)
    _receive(clinic, qty=10, warehouse_id=fridge_id)

    with clinic["app"].app_context():
        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        fridge = db.session.get(Warehouse, fridge_id)
        main = Warehouse.default()
        # The clinic already had stock on the shelf before the fridge existed;
        # it stays where it was, and the new delivery is in the fridge.
        assert brand.stock_in(fridge) == 10
        assert brand.stock_in(main) == brand.stock - 10
        assert brand.stock_in(main) + brand.stock_in(fridge) == brand.stock, \
            "the two shelves stopped adding up to the total"


def test_batches_from_before_warehouses_are_in_the_default_one(clinic):
    """Every clinic's existing stock has no warehouse on it. It belongs to the
    default store — the alternative is stock that exists nowhere."""
    from app.models import VaccineBrand, VaccineInventory, Warehouse

    db = clinic["db"]
    with clinic["app"].app_context():
        db.session.add(VaccineInventory(brand_id=clinic["ids"]["brand"],
                                        lot_number="OLD", qty_received=6,
                                        warehouse_id=None,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()

        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        assert brand.stock_in(Warehouse.default()) >= 6
