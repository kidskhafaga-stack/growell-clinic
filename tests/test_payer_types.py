"""The third fixed list to be opened up, and the payers screen made readable.

**The kinds.** Six names — club, syndicate, insurance, company, cash, other —
chosen by somebody who has never seen this clinic's books. "جمعية", "بنك" and
"مدرسة" are real payers here, and forcing all three into "other" makes every
report that groups by type stop saying anything. Same treatment as the service
types and the client categories, and for the same reason.

Two rules carried over unchanged, both learned on the client categories:

* **keys never change** — every payer stores one, and ``cash`` is read *by
  name* to find the clinic's own price list, so renaming renames the label;
* **a kind in use cannot be deleted** — the payers would point at something
  that no longer exists, which is a report that quietly drops rows rather than
  an error somebody sees. Hiding it is the answer, and an inactive kind stays
  valid for the payers already on it.

**And the edit form.** It was a 250px popover positioned absolutely inside a
scrolling table: clipped at the edge, its fields stacked into a column. Now the
same in-place full-width editor the services screen uses.
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
    from app.utils.payer_types import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
    return clinic


# ============================================================ the built-ins ==
def test_the_six_that_were_fixed_are_seeded(seeded, clinic):
    from app.utils.payer_types import all_types

    with clinic["app"].app_context():
        keys = {t.key for t in all_types()}
    assert {"club", "syndicate", "insurance", "company", "cash", "other"} <= keys


def test_seeding_twice_changes_nothing(seeded, clinic):
    from app.utils.payer_types import all_types, ensure_seeded

    with clinic["app"].app_context():
        before = len(all_types())
        assert ensure_seeded() == 0
        assert len(all_types()) == before


def test_seeding_never_overwrites_a_rename(seeded, clinic):
    """A clinic that renamed "نادي" to "نادي/جمعية" must not find it reset."""
    from app.models import PayerType
    from app.utils.payer_types import ensure_seeded

    with clinic["app"].app_context():
        row = PayerType.query.filter_by(key="club").first()
        row.name_ar = "نادي/جمعية"
        clinic["db"].session.commit()
        ensure_seeded()
        assert PayerType.query.filter_by(key="club").first().name_ar == "نادي/جمعية"


# ============================================================ adding one ====
def test_a_clinic_can_add_its_own_kind(boss, seeded, clinic):
    from app.models import PayerType

    boss.post("/finance/payer-types/new",
              data={"name": "جمعية خيرية", "name_en": "Charity"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert PayerType.query.filter_by(name_ar="جمعية خيرية").one().key


def test_two_kinds_never_share_a_key(boss, seeded, clinic):
    from app.models import PayerType

    for _ in range(2):
        boss.post("/finance/payer-types/new",
                  data={"name": "جمعية", "name_en": "Charity"},
                  follow_redirects=True)
    with clinic["app"].app_context():
        keys = [t.key for t in PayerType.query.all()]
    assert len(set(keys)) == len(keys)


def test_a_new_kind_can_be_used_on_a_payer(boss, seeded, clinic):
    from app.models import PayerEntity, PayerType

    boss.post("/finance/payer-types/new", data={"name": "مدرسة", "name_en": "School"},
              follow_redirects=True)
    with clinic["app"].app_context():
        key = PayerType.query.filter_by(name_ar="مدرسة").one().key

    boss.post("/finance/payers", data={"name": "مدرسة النصر", "entity_type": key},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert PayerEntity.query.filter_by(name="مدرسة النصر").one().entity_type == key


# ================================================= renaming, never re-keying ==
def test_renaming_changes_the_label_not_the_key(boss, seeded, clinic):
    """Every payer stores the key, and ``cash`` is read by name to find the
    clinic's own price list — re-keying would break both."""
    from app.models import PayerType

    with clinic["app"].app_context():
        row = PayerType.query.filter_by(key="club").first()
        rid = row.id

    boss.post(f"/finance/payer-types/{rid}/edit",
              data={"name": "نادي رياضي", "is_active": "1"},
              follow_redirects=True)
    with clinic["app"].app_context():
        row = clinic["db"].session.get(PayerType, rid)
        assert row.key == "club"
        assert row.name_ar == "نادي رياضي"


def test_the_label_helper_reads_the_clinics_own_name(boss, seeded, clinic):
    """Screens printed ``t('payer_types.' ~ key)``, which shows the raw key for
    anything a clinic added — the bug the client categories already had."""
    from app.models import PayerType
    from app.utils.payer_types import label

    with clinic["app"].app_context():
        boss_row = PayerType.query.filter_by(key="club").first()
        boss_row.name_ar = "نادي رياضي"
        clinic["db"].session.commit()
        assert label("club") == "نادي رياضي"


def test_an_unknown_key_falls_back_to_itself_rather_than_blank(seeded, clinic):
    from app.utils.payer_types import label

    with clinic["app"].app_context():
        assert label("nothing_like_this") == "nothing_like_this"


# ============================================== hiding, and what stays valid ==
def test_a_hidden_kind_is_off_the_dropdown(boss, seeded, clinic):
    from app.models import PayerType
    from app.utils.payer_types import active_types

    with clinic["app"].app_context():
        row = PayerType.query.filter_by(key="syndicate").first()
        rid = row.id
    boss.post(f"/finance/payer-types/{rid}/edit", data={"name": "نقابة"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert "syndicate" not in {t.key for t in active_types()}


def test_a_hidden_kind_is_still_valid_for_the_payers_on_it(boss, seeded, clinic):
    """Otherwise saving an unrelated field on that payer's form would quietly
    reset them to "club"."""
    from app.models import PayerType
    from app.utils.payer_types import valid_key

    with clinic["app"].app_context():
        row = PayerType.query.filter_by(key="syndicate").first()
        row.is_active = False
        clinic["db"].session.commit()
        assert valid_key("syndicate") is True


def test_editing_a_payer_keeps_its_hidden_kind(boss, seeded, clinic):
    from app.models import PayerEntity, PayerType

    with clinic["app"].app_context():
        payer = PayerEntity(name="نقابة الأطباء", entity_type="syndicate",
                            is_active=True)
        clinic["db"].session.add(payer)
        row = PayerType.query.filter_by(key="syndicate").first()
        row.is_active = False
        clinic["db"].session.commit()
        pid = payer.id

    boss.post(f"/finance/payers/{pid}/edit",
              data={"name": "نقابة الأطباء", "entity_type": "syndicate",
                    "is_active": "1"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(PayerEntity, pid).entity_type == "syndicate"


# ============================================================== deleting ====
def test_a_built_in_kind_cannot_be_deleted(boss, seeded, clinic):
    from app.models import PayerType

    with clinic["app"].app_context():
        rid = PayerType.query.filter_by(key="cash").first().id
    boss.post(f"/finance/payer-types/{rid}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(PayerType, rid) is not None


def test_a_kind_in_use_is_refused_with_a_reason(boss, seeded, clinic):
    """Deleting it would leave payers pointing at nothing — a report that
    silently drops rows rather than an error anybody sees."""
    from app.models import PayerEntity, PayerType

    boss.post("/finance/payer-types/new", data={"name": "مدرسة", "name_en": "School"},
              follow_redirects=True)
    with clinic["app"].app_context():
        row = PayerType.query.filter_by(name_ar="مدرسة").one()
        rid, key = row.id, row.key
        clinic["db"].session.add(PayerEntity(name="مدرسة النصر",
                                             entity_type=key, is_active=True))
        clinic["db"].session.commit()

    body = boss.post(f"/finance/payer-types/{rid}/delete",
                     follow_redirects=True).get_data(as_text=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(PayerType, rid) is not None
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("payer_types_admin.in_use").split("{")[0].strip() in body


def test_an_unused_clinic_kind_can_be_deleted(boss, seeded, clinic):
    from app.models import PayerType

    boss.post("/finance/payer-types/new", data={"name": "سفارة", "name_en": "Embassy"},
              follow_redirects=True)
    with clinic["app"].app_context():
        rid = PayerType.query.filter_by(name_ar="سفارة").one().id
    boss.post(f"/finance/payer-types/{rid}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(PayerType, rid) is None


# ================================================================ the screen ==
def test_the_kinds_are_managed_on_the_payers_screen(boss, seeded, clinic):
    body = boss.get("/finance/payers").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("payer_types_admin.title") in body
    assert "/finance/payer-types/new" in body


def test_the_edit_form_is_no_longer_a_clipped_popover(boss, seeded, clinic):
    """It was 250px, positioned absolutely inside a scrolling table — cut off
    at the edge with its fields stacked into a column, which is unreadable at
    exactly the moment somebody is changing a discount rate."""
    body = boss.get("/finance/payers").get_data(as_text=True)
    assert 'class="popform"' not in body


def test_the_kinds_can_be_reordered(boss, seeded, clinic):
    from app.models import PayerType

    with clinic["app"].app_context():
        rows = PayerType.query.order_by(PayerType.sort_order).all()
        second = rows[1].id
        first_key = rows[0].key

    boss.post(f"/finance/payer-types/{second}/move", data={"dir": "up"},
              follow_redirects=True)
    with clinic["app"].app_context():
        rows = PayerType.query.order_by(PayerType.sort_order).all()
        assert rows[0].id == second and rows[1].key == first_key


def test_both_languages_carry_the_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("title", "hint", "key_fixed", "added", "in_use",
                    "system_kept"):
            assert data["payer_types_admin"].get(key), f"{lang}.{key}"
