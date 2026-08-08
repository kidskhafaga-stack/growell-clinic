"""The clinic's own short lists, and the fourth time this problem appeared.

Service types were a fixed list in the code, then client categories, then payer
kinds; each was opened up separately, with its own model, screen and copy of
the same three rules. A fifth and sixth copy is not a pattern, it is a habit —
so the lists that were still hardcoded were opened together.

What was wrong with them differed in a way worth remembering. ``WAREHOUSE_KINDS``
was a Python list: a clinic with a pharmacy store or a second fridge could not
name it, and that at least looked like what it was. Categories and units were
worse *and looked better* — the picker offered the built-in defaults plus every
value anybody had ever typed, so you could add by typing and never remove. One
"قطعه" typed instead of "قطعة" sat beside the correct one for the life of the
installation, and every person after chose between them at random.

Two layers, asked for in those words: a *type* says what a thing fundamentally
is — drug, vaccine, consumable — and a *category* groups within it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _seed(clinic):
    from app.utils.lookups import ensure_seeded

    made = ensure_seeded()
    clinic["db"].session.commit()
    return made


# ================================================== the two layers ==========
def test_a_category_belongs_under_a_type(clinic):
    """The whole reason for two layers. A picker offering every category at
    once is the unreadable pile this replaced."""
    from app.utils.lookups import options

    with clinic["app"].app_context():
        _seed(clinic)
        drug = {r.key for r in options("item_category", parent="drug")}
        assert "antibiotic" in drug
        assert "device_supplies" not in drug, (
            "a device category was offered while adding a drug")


def test_a_category_with_no_type_is_offered_everywhere(clinic):
    """What an imported or hand-typed category starts as. Hiding it would make
    a clinic's own data vanish from its own picker."""
    from app.utils.lookups import options

    with clinic["app"].app_context():
        _seed(clinic)
        for parent in ("drug", "consumable", "vaccine"):
            keys = {r.key for r in options("item_category", parent=parent)}
            assert "other" in keys


def test_the_seeded_items_arrive_already_typed(clinic):
    """Leaving the program's own seed data untyped would teach every clinic
    that the field is optional decoration."""
    from app.models import StoreItem
    from app.utils.reference import seed_reference

    with clinic["app"].app_context():
        seed_reference()
        items = StoreItem.query.all()
        assert items
        untyped = [i.name for i in items if not i.item_type]
        assert not untyped, "seeded items with no type: " + ", ".join(untyped[:5])


def test_the_backfill_runs_after_the_items_exist(clinic):
    """The bug this replaces, and it failed silently.

    The backfill first ran with the *lists*, which are seeded earlier than the
    items — so it typed nothing at all, and every count on the screen still
    looked right. Ordering bugs in a seeder are invisible unless something
    asserts on the result.
    """
    from app.models import StoreItem
    from app.utils.store_seed import backfill_item_types, seed_store_items

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        # Nothing to type yet — this is the state the broken version ran in.
        assert backfill_item_types() == 0

        seed_store_items()
        db.session.commit()
        assert StoreItem.query.filter(StoreItem.item_type.is_(None)).count() > 0
        assert backfill_item_types() > 0
        db.session.commit()
        assert StoreItem.query.filter(StoreItem.item_type.is_(None)).count() == 0


def test_an_upgrading_clinics_own_categories_are_typed_too(clinic):
    """A clinic that has been typing categories for a year should not have to
    open every item to say which of them are drugs."""
    from app.models import StoreItem
    from app.utils.store_seed import backfill_item_types

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        db.session.add(StoreItem(name="شاش", category="مستهلكات طبية"))
        db.session.add(StoreItem(name="ورق ECG", category="مستلزمات الأجهزة"))
        db.session.commit()

        backfill_item_types()
        db.session.commit()
        by_name = {i.name: i.item_type for i in StoreItem.query.all()}
        assert by_name["شاش"] == "consumable"
        assert by_name["ورق ECG"] == "device"


# ================================================== add, and actually remove =
def test_a_typo_can_finally_be_removed(clinic):
    """The thing the old picker could not do. "قطعه" typed once for "قطعة"
    used to sit beside it for ever, offered to everybody after."""
    from app.models import Lookup

    with clinic["app"].app_context():
        _seed(clinic)

    client = clinic["sign_in"]("boss")
    client.post("/inventory/lookups/add",
                data={"domain": "unit", "name_ar": "قطعه"}, follow_redirects=True)

    with clinic["app"].app_context():
        typo = Lookup.query.filter_by(domain="unit", name_ar="قطعه").one()
        typo_id = typo.id

    client.post(f"/inventory/lookups/{typo_id}/delete", follow_redirects=True)

    with clinic["app"].app_context():
        assert clinic["db"].session.get(Lookup, typo_id) is None
        from app.utils.store_seed import store_units
        assert "قطعه" not in store_units()


def test_an_entry_in_use_is_switched_off_rather_than_deleted(clinic):
    """Deleting it would leave items pointing at a value that no longer
    exists — a report that quietly drops rows rather than an error anybody
    sees."""
    from app.models import Lookup, StoreItem

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        client = clinic["sign_in"]("boss")
        client.post("/inventory/lookups/add",
                    data={"domain": "unit", "name_ar": "شريط"},
                    follow_redirects=True)
        row = Lookup.query.filter_by(domain="unit", name_ar="شريط").one()
        row_id = row.id
        db.session.add(StoreItem(name="أشرطة سكر", unit="شريط"))
        db.session.commit()

    clinic["sign_in"]("boss").post(f"/inventory/lookups/{row_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        row = db.session.get(Lookup, row_id)
        assert row is not None, "an entry in use was deleted"
        assert row.is_active is False
        # And the item that used it still reads correctly.
        assert StoreItem.query.filter_by(name="أشرطة سكر").one().unit == "شريط"


def test_a_built_in_survives_being_deleted(clinic):
    """A clinic that removes "قطعة" leaves half its own catalogue unreadable."""
    from app.models import Lookup

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        piece_id = Lookup.query.filter_by(domain="unit", key="piece").one().id

    clinic["sign_in"]("boss").post(f"/inventory/lookups/{piece_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        row = db.session.get(Lookup, piece_id)
        assert row is not None and row.is_active is False


def test_editing_never_changes_the_key(clinic):
    """Every item row stored it. Renaming is renaming the *label* — the rule
    the three catalogues before this one arrived at as well."""
    from app.models import Lookup

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        row = Lookup.query.filter_by(domain="item_type", key="drug").one()
        row_id, key = row.id, row.key

    clinic["sign_in"]("boss").post(
        f"/inventory/lookups/{row_id}/edit",
        data={"name_ar": "أدوية ومستحضرات", "key": "medicine", "is_active": "1"},
        follow_redirects=True)

    with clinic["app"].app_context():
        row = db.session.get(Lookup, row_id)
        assert row.key == key, "the key moved and every item pointing at it is orphaned"
        assert row.name_ar == "أدوية ومستحضرات"


# ================================================== the fridge is a warehouse
def test_the_fridge_is_an_ordinary_warehouse_kind(clinic):
    """Said explicitly by the clinic: these are ordinary warehouses with a
    particular nature. So nothing special-cases one, a second fridge is just
    another warehouse, and anything that must behave differently in cold
    storage keys off the nature rather than off a warehouse's name."""
    from app.utils.lookups import options

    with clinic["app"].app_context():
        _seed(clinic)
        kinds = {r.key for r in options("warehouse_kind")}
        assert {"main", "sub", "fridge", "pharmacy"} <= kinds


def test_a_clinic_can_name_a_kind_the_program_never_thought_of(clinic):
    """It was a Python list. A clinic with an emergency store could not say so."""
    from app.models import Lookup

    with clinic["app"].app_context():
        _seed(clinic)

    clinic["sign_in"]("boss").post(
        "/inventory/lookups/add",
        data={"domain": "warehouse_kind", "name_ar": "مخزن الطوارئ",
              "name_en": "Emergency store"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.utils.lookups import options
        assert "مخزن الطوارئ" in [r.display_name("ar")
                                  for r in options("warehouse_kind")]


# ================================================== reachable, and safe ======
def test_the_screen_has_a_door(clinic):
    """The rule this program already enforces elsewhere: a screen with no
    entry point is a screen that does not exist."""
    page = clinic["sign_in"]("boss").get("/inventory/store").data.decode()
    assert "/inventory/lookups" in page


def test_every_list_opens(clinic):
    from app.utils.lookups import DOMAINS

    client = clinic["sign_in"]("boss")
    for domain in DOMAINS:
        response = client.get(f"/inventory/lookups?domain={domain}")
        assert response.status_code == 200, domain


def test_seeding_twice_adds_nothing(clinic):
    """Run on every upgrade; a second run must not double the lists."""
    from app.models import Lookup

    with clinic["app"].app_context():
        first = _seed(clinic)
        assert first > 0
        before = Lookup.query.count()
        assert _seed(clinic) == 0
        assert Lookup.query.count() == before


def test_a_reworded_built_in_is_not_reset_by_the_next_upgrade(clinic):
    """A clinic that renames "مستهلكات" to its own wording keeps it."""
    from app.models import Lookup

    db = clinic["db"]
    with clinic["app"].app_context():
        _seed(clinic)
        row = Lookup.query.filter_by(domain="item_type", key="consumable").one()
        row.name_ar = "مستلزمات"
        db.session.commit()

        _seed(clinic)
        again = Lookup.query.filter_by(domain="item_type", key="consumable").one()
        assert again.name_ar == "مستلزمات"
