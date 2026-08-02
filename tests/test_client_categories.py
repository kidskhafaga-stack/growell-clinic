"""The clinic's own client categories, not four names fixed in the code.

Found while planning the history import for a clinic that was already running.
Its export carries a column the clinic corrected me about: it is not a contract
or a payer, it is the **client category** — نقدي, عاملين, أطباء, أعضاء نادي
سبورتنج — and some of those carry a discount.

The program already had the right mechanism: a ``NamedDiscount`` with
``dtype="category"`` and a ``client_category`` does "this category pays less".
What it did not have was the clinic's actual list:

    CLIENT_CATEGORIES = ["normal", "friend", "relative", "employee"]

Two of the four real ones had nowhere to go. Forcing "أطباء" into ``friend``
would hang a real discount on a category with the wrong name, and every report
grouping clients by category then says something meaningless.

Same shape as the service-type catalogue, and for the same reason: **keys are
not labels.** Every parent row and every discount stores the key, so renaming a
category has to move the label and nothing else.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def seeded(clinic):
    from app.utils.client_categories import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
    return clinic


def _keys(clinic):
    from app.utils.client_categories import all_categories

    with clinic["app"].app_context():
        return [c.key for c in all_categories()]


def _add(boss, name, name_en=None):
    return boss.post("/finance/client-categories/new",
                     data={"name": name, "name_en": name_en or ""},
                     follow_redirects=True)


# ================================================================ seeding ===
def test_the_built_in_four_are_there_to_start(seeded, clinic):
    assert _keys(clinic) == ["normal", "friend", "relative", "employee"]


def test_seeding_twice_does_not_double_them(clinic):
    from app.utils.client_categories import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
        assert ensure_seeded() == 0
    assert len(_keys(clinic)) == 4


def test_the_screens_work_before_anything_is_seeded(clinic, boss):
    """A fresh install, or a database that has not been upgraded yet, must not
    show an empty dropdown where the categories should be."""
    from app.models import ClientCategory

    with clinic["app"].app_context():
        for row in ClientCategory.query.all():
            clinic["db"].session.delete(row)
        clinic["db"].session.commit()

    from app.utils.client_categories import all_categories

    with clinic["app"].app_context():
        assert [c.key for c in all_categories()] == [
            "normal", "friend", "relative", "employee"]


# ============================================== the two that had nowhere to go
def test_a_clinic_can_add_its_own(seeded, boss, clinic):
    _add(boss, "أعضاء نادي سبورتنج", "Sporting Club")
    assert "sporting-club" in _keys(clinic)


def test_an_arabic_only_name_still_gets_a_key(seeded, boss, clinic):
    """A key derived from Arabic yields no ASCII at all. An empty key would
    collide with the next one and silently merge two categories."""
    _add(boss, "أطباء")
    keys = _keys(clinic)
    assert len(keys) == 5
    assert all(k for k in keys)


def test_two_categories_with_the_same_english_name_get_different_keys(seeded,
                                                                     boss,
                                                                     clinic):
    _add(boss, "أطباء", "Doctors")
    _add(boss, "أطباء زائرين", "Doctors")
    keys = [k for k in _keys(clinic) if k.startswith("doctors")]
    assert len(keys) == 2 and len(set(keys)) == 2


def test_a_nameless_category_is_refused(seeded, boss, clinic):
    boss.post("/finance/client-categories/new", data={"name": "  "},
              follow_redirects=True)
    assert len(_keys(clinic)) == 4


# ================================================= keys are not labels ======
def test_renaming_moves_the_label_and_not_the_key(seeded, boss, clinic):
    """Every parent row and every discount stores the key. If renaming "عادي"
    to "نقدي" changed it, every family on it would be orphaned — and any
    discount aimed at it would stop applying."""
    from app.models import ClientCategory

    with clinic["app"].app_context():
        row = ClientCategory.query.filter_by(key="normal").one()
        row_id = row.id

    boss.post("/finance/client-categories/save", data={
        f"name_{row_id}": "نقدي", f"active_{row_id}": "1",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        row = clinic["db"].session.get(ClientCategory, row_id)
        assert row.key == "normal"
        assert row.name_ar == "نقدي"


def test_the_new_name_is_what_the_screens_show(seeded, boss, clinic):
    from app.models import ClientCategory
    from app.utils.client_categories import label

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="normal").one().id
    boss.post("/finance/client-categories/save",
              data={f"name_{row_id}": "نقدي", f"active_{row_id}": "1"},
              follow_redirects=True)

    with clinic["app"].test_request_context("/"):
        assert label("normal") == "نقدي"


def test_a_clinic_added_category_has_a_label_without_a_dictionary_entry(seeded,
                                                                       boss,
                                                                       clinic):
    """Templates printed `t('categories.' ~ key)`, which only ever worked for
    the four built-ins — a clinic's own category printed its raw key."""
    from app.utils.client_categories import label

    _add(boss, "أعضاء نادي سبورتنج", "Sporting Club")
    with clinic["app"].test_request_context("/"):
        assert label("sporting-club") == "أعضاء نادي سبورتنج"


# ============================================ storing one on a family =======
def test_a_family_can_be_put_on_a_clinic_added_category(seeded, boss, clinic):
    """The point of the whole change. `Parent.valid_category` asked the four
    built-ins, so a clinic-added category was silently rejected."""
    from app.models import Parent

    _add(boss, "أطباء", "Doctors")
    with clinic["app"].app_context():
        assert Parent.valid_category("doctors") is True


def test_an_unknown_category_is_still_refused(seeded, clinic):
    """Opening the list up must not mean anything at all can be stored."""
    from app.models import Parent

    with clinic["app"].app_context():
        assert Parent.valid_category("whatever") is False
        assert Parent.valid_category("") is False


def test_a_hidden_category_is_still_valid_for_the_families_on_it(seeded, boss,
                                                                clinic):
    """Hiding one takes it off the "add" dropdown. If it also became invalid,
    saving an unrelated field on such a family would reset their category —
    and take their discount with it."""
    from app.models import ClientCategory, Parent

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="employee").one().id
    boss.post("/finance/client-categories/save",
              data={f"name_{row_id}": "موظف"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert clinic["db"].session.get(ClientCategory, row_id).is_active is False
        assert Parent.valid_category("employee") is True


def test_a_hidden_category_is_still_offered_to_the_family_on_it(seeded, boss,
                                                               clinic):
    """Otherwise opening their profile and pressing save quietly moves them."""
    from app.models import ClientCategory
    from app.utils.client_categories import choices_for

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="employee").one().id
    boss.post("/finance/client-categories/save",
              data={f"name_{row_id}": "موظف"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert "employee" in [c.key for c in choices_for("employee")]
        assert "employee" not in [c.key for c in choices_for(None)]


# ===================================================== deleting one =========
def test_a_built_in_cannot_be_deleted(seeded, boss, clinic):
    from app.models import ClientCategory

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="normal").one().id
    boss.post(f"/finance/client-categories/{row_id}/delete", follow_redirects=True)
    assert "normal" in _keys(clinic)


def test_a_category_with_families_on_it_cannot_be_deleted(seeded, boss, clinic):
    """Reassigning silently would move families somewhere nobody chose — and
    take their discount with them."""
    from app.models import ClientCategory, Family, Parent

    _add(boss, "أطباء", "Doctors")
    with clinic["app"].app_context():
        db = clinic["db"]
        family = Family(family_name="عائلة الطبيب")
        db.session.add(family)
        db.session.flush()
        db.session.add(Parent(family_id=family.id, full_name="د. أب",
                              relation="father", client_category="doctors"))
        db.session.commit()
        row_id = ClientCategory.query.filter_by(key="doctors").one().id

    boss.post(f"/finance/client-categories/{row_id}/delete", follow_redirects=True)
    assert "doctors" in _keys(clinic)


def test_a_category_a_discount_aims_at_cannot_be_deleted(seeded, boss, clinic):
    """Deleting it would leave a discount pointing at nothing — which reads on
    the till as a discount that simply stopped working."""
    from app.models import ClientCategory, NamedDiscount

    _add(boss, "أعضاء نادي سبورتنج", "Sporting Club")
    with clinic["app"].app_context():
        clinic["db"].session.add(NamedDiscount(
            name="خصم النادي", dtype="category", client_category="sporting-club",
            value=15, is_percent=True))
        clinic["db"].session.commit()
        row_id = ClientCategory.query.filter_by(key="sporting-club").one().id

    boss.post(f"/finance/client-categories/{row_id}/delete", follow_redirects=True)
    assert "sporting-club" in _keys(clinic)


def test_an_unused_clinic_category_can_be_deleted(seeded, boss, clinic):
    from app.models import ClientCategory

    _add(boss, "مؤقتة", "Temp")
    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="temp").one().id
    boss.post(f"/finance/client-categories/{row_id}/delete", follow_redirects=True)
    assert "temp" not in _keys(clinic)


# ============================================== the discount that aims at it
def test_a_discount_can_be_aimed_at_a_clinic_added_category(seeded, boss, clinic):
    """The whole reason a clinic adds one."""
    from app.models import NamedDiscount

    _add(boss, "أعضاء نادي سبورتنج", "Sporting Club")
    boss.post("/finance/discounts", data={
        "name": "خصم النادي", "dtype": "category",
        "client_category": "sporting-club", "value": "15", "is_percent": "1",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        row = NamedDiscount.query.filter_by(name="خصم النادي").one()
        assert row.client_category == "sporting-club"


def test_the_discount_dropdown_offers_the_clinics_categories(seeded, boss):
    _add(boss, "أعضاء نادي سبورتنج", "Sporting Club")
    body = boss.get("/finance/discounts").get_data(as_text=True)
    assert 'value="sporting-club"' in body
    assert "أعضاء نادي سبورتنج" in body


def test_the_manager_is_on_the_discounts_screen(seeded, boss, clinic):
    body = boss.get("/finance/discounts").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("categories.manage") in body


def test_the_screen_says_how_many_families_are_on_each(seeded, boss, clinic):
    """What makes deleting one a decision rather than a surprise."""
    body = boss.get("/finance/discounts").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("categories.families") in body


def test_the_patient_profile_offers_the_clinics_categories(seeded, boss, clinic):
    _add(boss, "أطباء", "Doctors")
    body = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert 'value="doctors"' in body


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("manage", "manage_hint", "name", "name_en", "families",
                    "added", "deleted", "is_system", "in_use", "has_discount"):
            assert data["categories"].get(key), f"{lang}.categories.{key}"


# ============================================== the order nobody types =====
def _order(clinic):
    from app.utils.client_categories import all_categories

    with clinic["app"].app_context():
        return [c.key for c in all_categories()]


def test_a_new_category_lands_at_the_end(seeded, boss, clinic):
    _add(boss, "أطباء", "Doctors")
    assert _order(clinic)[-1] == "doctors"


def test_a_category_can_be_moved_up(seeded, boss, clinic):
    """Nobody wants row number 6; they want this row above that one."""
    from app.models import ClientCategory

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="relative").one().id
    boss.post(f"/finance/client-categories/{row_id}/move", data={"dir": "up"},
              follow_redirects=True)
    assert _order(clinic) == ["normal", "relative", "friend", "employee"]


def test_a_category_can_be_moved_down(seeded, boss, clinic):
    from app.models import ClientCategory

    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="normal").one().id
    boss.post(f"/finance/client-categories/{row_id}/move", data={"dir": "down"},
              follow_redirects=True)
    assert _order(clinic) == ["friend", "normal", "relative", "employee"]


def test_moving_the_first_one_up_does_nothing(seeded, boss, clinic):
    """Pressing a button at the end of a list is not an error."""
    from app.models import ClientCategory

    before = _order(clinic)
    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="normal").one().id
    reply = boss.post(f"/finance/client-categories/{row_id}/move",
                      data={"dir": "up"}, follow_redirects=True)
    assert reply.status_code == 200
    assert _order(clinic) == before


def test_moving_the_last_one_down_does_nothing(seeded, boss, clinic):
    from app.models import ClientCategory

    before = _order(clinic)
    with clinic["app"].app_context():
        row_id = ClientCategory.query.filter_by(key="employee").one().id
    boss.post(f"/finance/client-categories/{row_id}/move", data={"dir": "down"},
              follow_redirects=True)
    assert _order(clinic) == before


def test_the_numbers_are_compacted_not_swapped(seeded, boss, clinic):
    """A swap preserves whatever ties and gaps were already there, and the next
    move then misbehaves for a reason nobody can see."""
    from app.models import ClientCategory

    with clinic["app"].app_context():
        rows = ClientCategory.query.all()
        for row in rows:            # everything tied on 5, as typed numbers do
            row.sort_order = 5
        clinic["db"].session.commit()
        row_id = ClientCategory.query.filter_by(key="employee").one().id

    boss.post(f"/finance/client-categories/{row_id}/move", data={"dir": "up"},
              follow_redirects=True)

    with clinic["app"].app_context():
        orders = sorted(c.sort_order for c in ClientCategory.query.all())
    assert orders == [0, 1, 2, 3], "the ties survived the move"


def test_saving_the_names_also_tidies_the_order(seeded, boss, clinic):
    """A clinic that numbered its list by hand before this change should not be
    left with the gaps forever."""
    from app.models import ClientCategory

    with clinic["app"].app_context():
        for i, row in enumerate(ClientCategory.query.all()):
            row.sort_order = i * 7
        clinic["db"].session.commit()

    boss.post("/finance/client-categories/save", data={}, follow_redirects=True)

    with clinic["app"].app_context():
        orders = sorted(c.sort_order for c in ClientCategory.query.all())
    assert orders == [0, 1, 2, 3]


def test_the_screen_has_no_number_to_type(seeded, boss):
    body = boss.get("/finance/discounts").get_data(as_text=True)
    assert 'name="order_' not in body


def test_the_service_types_moved_the_same_way(seeded, boss, clinic):
    """Two managers doing the same job must not behave differently."""
    from app.models import ServiceType
    from app.utils.service_types import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
        rows = ServiceType.query.order_by(ServiceType.sort_order,
                                          ServiceType.id).all()
        second = rows[1].key
        row_id = rows[1].id

    boss.post(f"/finance/services/types/{row_id}/move", data={"dir": "up"},
              follow_redirects=True)

    with clinic["app"].app_context():
        first = ServiceType.query.order_by(ServiceType.sort_order,
                                           ServiceType.id).first()
        assert first.key == second


def test_the_services_screen_has_no_number_to_type_either(seeded, boss):
    body = boss.get("/finance/services").get_data(as_text=True)
    assert 'name="order_' not in body
