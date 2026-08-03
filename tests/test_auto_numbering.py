"""Anything the program creates gets its number from the program.

The rule was stated as a general one — contract number, item code, any other
numbering — and the reason given was not convenience: **a number somebody types
is a number that gets typed twice**, and two rows sharing one is a data problem
with no clean fix afterwards.

Most of it was already done: services, store items, invoices, purchase orders
and store documents all generate. This closes the two that were still asking a
person, both found by going back over the plan rather than by anybody hitting
them:

* **renewing a contract.** A brand-new contract generated its number; the
  *copy* took whatever was typed — on a form that sits directly beside last
  year's number on the same screen, which is exactly where a duplicate comes
  from. Left blank it produced a contract with no number at all.
* **defining a vaccine brand.** Store items got a generated ``ITM-`` code;
  vaccine brands were left with whatever was typed, and blank meant *no code
  until the next update ran the backfill* — so a product created this morning
  could not be found by the barcode screen this afternoon.

Not everything with a "code" belongs here, and that matters as much. A
vaccine's ``PCV`` and a schedule template's ``A`` are names a clinician
chooses and reads; replacing them with ``VCN-0007`` would be obeying the letter
of the rule and losing the thing the field is for.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def payer(clinic):
    """A cash payer with one contract, as a clinic starts out."""
    from app.models import PayerEntity

    with clinic["app"].app_context():
        row = PayerEntity(name="نقدي", entity_type="cash", is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


# ================================================================= contracts ==
def test_a_new_contract_numbers_itself(boss, payer, clinic):
    from app.models import PayerContract

    boss.post(f"/finance/payers/{payer}/contract/new",
              data={"start_date": "2026-01-01"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert PayerContract.query.one().number


def test_renewing_a_contract_numbers_itself_too(boss, payer, clinic):
    """The case that most needs it: the renewal form sits beside last year's
    number on the same screen."""
    from app.models import PayerContract

    boss.post(f"/finance/payers/{payer}/contract/new",
              data={"start_date": "2026-01-01"}, follow_redirects=True)
    with clinic["app"].app_context():
        first = PayerContract.query.one().id

    boss.post(f"/finance/contract/{first}/copy",
              data={"start_date": "2027-01-01"}, follow_redirects=True)

    with clinic["app"].app_context():
        numbers = [c.number for c in PayerContract.query.all()]
    assert len(numbers) == 2
    assert all(numbers), "a contract with no number at all"
    assert len(set(numbers)) == 2, "two contracts sharing one number"


def test_a_typed_number_can_no_longer_collide(boss, payer, clinic):
    """Even posted directly — the field is gone from the screen, and the route
    ignores it rather than trusting whatever arrives."""
    from app.models import PayerContract

    boss.post(f"/finance/payers/{payer}/contract/new",
              data={"start_date": "2026-01-01"}, follow_redirects=True)
    with clinic["app"].app_context():
        first = PayerContract.query.one()
        first_id, taken = first.id, first.number

    boss.post(f"/finance/contract/{first_id}/copy",
              data={"number": taken, "start_date": "2027-01-01"},
              follow_redirects=True)

    with clinic["app"].app_context():
        numbers = [c.number for c in PayerContract.query.all()]
    assert len(set(numbers)) == len(numbers)


def test_the_renewal_form_no_longer_asks(boss, payer, clinic):
    body = boss.get("/finance/payers").get_data(as_text=True)
    assert 'name="number"' not in body


# =========================================================== vaccine brands ==
def test_a_new_vaccine_brand_gets_its_internal_code(boss, clinic):
    """It was the last creation form asking a person for one."""
    from app.models import VaccineBrand

    boss.post("/inventory/items/new", data={
        "item_kind": "vaccine", "vaccine_id": clinic["ids"]["pcv"],
        "name": "Synflorix", "price": "800"}, follow_redirects=True)

    with clinic["app"].app_context():
        brand = VaccineBrand.query.filter_by(name="Synflorix").one()
        assert brand.item_code
        assert brand.item_code.startswith("VAC-")


def test_two_brands_never_share_a_code(boss, clinic):
    from app.models import VaccineBrand

    for name in ("Vaxneuvance", "Prevenar 20"):
        boss.post("/inventory/items/new", data={
            "item_kind": "vaccine", "vaccine_id": clinic["ids"]["pcv"],
            "name": name, "price": "900"}, follow_redirects=True)

    with clinic["app"].app_context():
        codes = [b.item_code for b in VaccineBrand.query.all() if b.item_code]
    assert len(set(codes)) == len(codes)


def test_a_brand_created_today_is_findable_today(boss, clinic):
    """Blank used to mean *no code until the next update ran the backfill*, so
    the barcode screen could not find a product defined this morning."""
    from app.models import VaccineBrand

    boss.post("/inventory/items/new", data={
        "item_kind": "vaccine", "vaccine_id": clinic["ids"]["pcv"],
        "name": "Pneumo 23", "price": "700"}, follow_redirects=True)

    with clinic["app"].app_context():
        code = VaccineBrand.query.filter_by(name="Pneumo 23").one().item_code
        found = VaccineBrand.query.filter_by(item_code=code).one()
    assert found.name == "Pneumo 23"


def test_the_item_form_no_longer_asks_for_a_code(boss, clinic):
    body = boss.get("/inventory/items").get_data(as_text=True)
    assert 'name="item_code"' not in body


def test_the_suppliers_own_number_still_has_a_field(boss, clinic):
    """Generating the internal code must not take away the place to record the
    barcode on the box."""
    body = boss.get("/inventory/items").get_data(as_text=True)
    assert 'name="barcode"' in body


# ============================================ and what is deliberately typed ==
def test_a_vaccines_own_code_is_still_chosen_by_the_clinic(boss, clinic):
    """"PCV" and "MMR" are names a clinician reads, not serials. Replacing them
    with VCN-0007 would follow the letter of the rule and lose what the field
    is for."""
    body = boss.get("/vaccinations/manage").get_data(as_text=True)
    assert 'name="code"' in body


def test_the_store_item_code_was_already_generated(boss, clinic):
    """Pinned because it is the pattern the two fixes above were made to
    match — a later edit re-adding the field would undo it silently."""
    from app.models import StoreItem

    boss.post("/inventory/items/new", data={
        "item_kind": "store", "name": "قطن", "price": "10"},
        follow_redirects=True)
    with clinic["app"].app_context():
        assert StoreItem.query.filter_by(name="قطن").one().item_code
