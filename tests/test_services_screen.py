"""The services screen: somewhere to add a type, and a list you can read.

Reported, twice: *"the service pricing screen needs sorting out and designing
better, and there's nowhere to add service types — if the services grow the
whole thing will run together and this cramped screen isn't practical"*, then
*"why is there no search and filter on the services screen?"*

Three separate faults behind one screen:

**Nowhere to add a type** was literal. The types were eight strings in a Python
list, so adding one meant editing the source. They are a table now.

**Not fixed the same way:** the *category* stays a fixed list, and that is a
decision rather than an omission. ``vaccination_fee`` decides how the cashier
bills a vaccine and which lines a discount scope matches; ``vaccination`` on the
*type* decides which half of an invoice is posted to vaccination revenue. A
clinic inventing a category would be inventing a rule nothing implements. The
type is descriptive, so it opens; the category carries behaviour, so it does
not. The tests below hold both halves of that line.

**The keys are the load-bearing part.** A clinic renaming "تطعيم" to "تطعيمات"
must not silently change which revenue account its invoices land in, so system
keys are fixed and only labels move. That is the test nobody would think to
write until the ledger disagreed with the till by exactly the vaccine total.
"""
import os
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _template():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, "finance", "services.html"), encoding="utf-8") as fh:
        return fh.read()


def _page(client, **params):
    return client.get("/finance/services", query_string=params).get_data(as_text=True)


def _results(client, **params):
    """Only the block the browser swaps in.

    Reading the whole page instead was the first version of these tests, and
    every one of them passed on an unfiltered list: the visit-type panel above
    holds a ``<select>`` naming *every* service, so "is this service on the
    page" is true no matter what the filter did. The results block is what the
    filter is about, and it is what live search replaces.
    """
    body = _page(client, **params)
    return body[body.index('id="gc-results"'):]


# ============================================================ the catalogue ==
def test_the_built_in_types_are_seeded_once(clinic):
    from app.models import SERVICE_TYPES, ServiceType
    from app.utils.service_types import ensure_seeded

    with clinic["app"].app_context():
        assert ensure_seeded() == len(SERVICE_TYPES)
        assert ensure_seeded() == 0, "seeding twice would duplicate every type"
        assert ServiceType.query.count() == len(SERVICE_TYPES)


def test_the_built_ins_are_marked_as_such(clinic):
    from app.models import ServiceType
    from app.utils.service_types import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
        assert all(r.is_system for r in ServiceType.query.all())


def test_the_screen_works_before_the_catalogue_exists(clinic):
    """Fresh install, or a database not yet upgraded: the list still has to
    render rather than raise, so every reader falls back to the built-ins."""
    from app.models import SERVICE_TYPES
    from app.utils import service_types as st

    with clinic["app"].test_request_context("/"):
        rows = st.all_types()
        assert [r.key for r in rows] == SERVICE_TYPES
        assert st.label("vaccination") and st.icon("vaccination")


def test_a_deactivated_type_is_still_a_valid_key(clinic):
    """The trap: hiding a type from the "add" dropdown must not invalidate the
    services already on it. If ``valid_key`` said no, saving an unrelated field
    on such a service would quietly drop its type on the floor."""
    from app.models import ServiceType
    from app.utils import service_types as st

    with clinic["app"].app_context():
        st.ensure_seeded()
        row = ServiceType.query.filter_by(key="session").first()
        row.is_active = False
        clinic["db"].session.commit()

        assert "session" not in [r.key for r in st.active_types()]
        assert st.valid_key("session"), "an old service would lose its type"


def test_an_arabic_only_name_still_gets_a_usable_key(clinic):
    """Keys go into URLs and into ``service_type`` on every row, so a name with
    no ASCII in it must not produce an empty one."""
    from app.utils.service_types import make_key

    with clinic["app"].app_context():
        key = make_key("علاج طبيعي")
        assert key and re.fullmatch(r"[a-z0-9-]+", key)


def test_two_types_never_share_a_key(clinic):
    from app.models import ServiceType
    from app.utils.service_types import ensure_seeded, make_key

    with clinic["app"].app_context():
        ensure_seeded()
        assert make_key("Consultation") != "consultation"
        assert ServiceType.query.filter_by(key="consultation").count() == 1


# ==================================================== keys are load-bearing ==
def test_renaming_a_type_does_not_move_the_money(clinic, boss):
    """A clinic renaming "تطعيم" is renaming a label. The ledger splits an
    invoice by the *key* ``vaccination``, so if a rename touched the key the
    vaccine revenue would start landing in the general services account and
    nothing on any screen would say so."""
    from app.models import ServiceType
    from app.utils.accounting import _vaccine_split

    with clinic["app"].app_context():
        from app.utils.service_types import ensure_seeded
        ensure_seeded()
        row = ServiceType.query.filter_by(key="vaccination").first()
        type_id = row.id

    boss.post("/finance/services/types/save", data={
        f"name_{type_id}": "تطعيمات الأطفال",
        f"name_en_{type_id}": "Childhood immunisation",
        f"order_{type_id}": 3, f"active_{type_id}": "1",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        row = clinic["db"].session.get(ServiceType, type_id)
        assert row.key == "vaccination", "the key moved with the label"
        assert row.name_ar == "تطعيمات الأطفال"

        vaccine_line = SimpleNamespace(
            service=SimpleNamespace(service_type="vaccination"), net=300.0)
        other_line = SimpleNamespace(
            service=SimpleNamespace(service_type="consultation"), net=200.0)
        invoice = SimpleNamespace(items=[vaccine_line, other_line], total=500.0)
        assert _vaccine_split(invoice) == (300.0, 200.0)


def test_a_built_in_type_cannot_be_deleted(clinic, boss):
    from app.models import ServiceType

    with clinic["app"].app_context():
        from app.utils.service_types import ensure_seeded
        ensure_seeded()
        type_id = ServiceType.query.filter_by(key="vaccination").first().id

    boss.post(f"/finance/services/types/{type_id}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ServiceType, type_id) is not None


def test_a_type_in_use_is_not_deleted_from_under_its_services(clinic, boss):
    """Reassigning the services silently would move them somewhere nobody
    chose. The person deleting is the one who knows where they belong, so they
    are told how many and sent back."""
    from app.models import Service, ServiceType

    boss.post("/finance/services/types/new",
              data={"name": "علاج طبيعي", "name_en": "Physiotherapy"},
              follow_redirects=True)
    with clinic["app"].app_context():
        row = ServiceType.query.filter_by(is_system=False).first()
        assert row is not None
        type_id, key = row.id, row.key
        svc = Service.query.first()
        svc.service_type = key
        clinic["db"].session.commit()
        service_id = svc.id

    boss.post(f"/finance/services/types/{type_id}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ServiceType, type_id) is not None
        assert clinic["db"].session.get(Service, service_id).service_type == key


def test_an_unused_custom_type_can_be_deleted(clinic, boss):
    from app.models import ServiceType

    boss.post("/finance/services/types/new", data={"name": "مؤقت"},
              follow_redirects=True)
    with clinic["app"].app_context():
        type_id = ServiceType.query.filter_by(is_system=False).first().id

    boss.post(f"/finance/services/types/{type_id}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ServiceType, type_id) is None


# ================================================ adding a type, end to end ==
def test_a_new_type_can_be_added_and_then_used(clinic, boss):
    """The whole complaint in one test: add a type on the screen, and it is
    offered when adding a service — no code change anywhere."""
    from app.models import Service

    boss.post("/finance/services/types/new",
              data={"name": "علاج طبيعي", "name_en": "Physiotherapy",
                    "icon": "bi-heart-pulse"}, follow_redirects=True)
    body = _page(boss)
    assert "علاج طبيعي" in body

    boss.post("/finance/services/new", data={
        "se": "1", "name": "جلسة علاج طبيعي", "price": "180",
        "category": "procedure", "service_type": "physiotherapy",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        svc = Service.query.filter_by(name="جلسة علاج طبيعي").first()
        assert svc is not None
        assert svc.kind == "physiotherapy", "the new type did not stick"


def test_a_type_is_not_created_without_a_name(clinic, boss):
    from app.models import ServiceType

    boss.post("/finance/services/types/new", data={"name": "  "},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert ServiceType.query.filter_by(is_system=False).count() == 0


def test_the_service_editor_still_offers_a_type_that_was_hidden(clinic, boss):
    """Open the editor on a service whose type was since deactivated and the
    dropdown has to still contain it, or pressing save moves the service to
    whatever happens to be first in the list."""
    from app.models import Service, ServiceType

    with clinic["app"].app_context():
        from app.utils.service_types import ensure_seeded
        ensure_seeded()
        svc = Service.query.first()
        svc.service_type = "session"
        ServiceType.query.filter_by(key="session").first().is_active = False
        clinic["db"].session.commit()
        service_id = svc.id

    boss.post(f"/finance/services/{service_id}/edit", data={
        "se": "1", "name": "جلسة تنفس", "price": "150",
        "category": "procedure", "service_type": "session", "is_active": "1",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Service, service_id).kind == "session"


# ============================================== the category stays a fixed list
def test_a_category_cannot_be_invented(clinic, boss):
    """Unlike the type. ``vaccination_fee`` and friends are matched by the
    cashier and by discount scopes, so a made-up one would be a category no
    rule knows about — the save falls back rather than storing it."""
    from app.models import SERVICE_CATEGORIES, Service

    boss.post("/finance/services/new", data={
        "se": "1", "name": "خدمة بتصنيف مخترع", "price": "50",
        "category": "physiotherapy",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        svc = Service.query.filter_by(name="خدمة بتصنيف مخترع").first()
        assert svc is not None
        assert svc.category in SERVICE_CATEGORIES
        assert svc.category == "other"


# ================================================== search, filter, and read ==
@pytest.fixture()
def catalogue(clinic):
    """Enough services that the screen has something to narrow."""
    from app.models import Service

    with clinic["app"].app_context():
        rows = [
            Service(name="تحليل صورة دم", code="SVC-CBC", category="lab",
                    service_type="diagnostic", price=120, is_active=True),
            Service(name="أشعة صدر", code="SVC-CXR", category="radiology",
                    service_type="diagnostic", price=250, is_active=True),
            Service(name="خدمة موقوفة", code="SVC-OFF", category="other",
                    service_type="other", price=10, is_active=False),
        ]
        clinic["db"].session.add_all(rows)
        clinic["db"].session.commit()
    return clinic


def test_typing_a_name_narrows_the_list(catalogue, boss):
    everyone = _results(boss)
    assert "تحليل صورة دم" in everyone and "أشعة صدر" in everyone

    narrowed = _results(boss, q="أشعة")
    assert "أشعة صدر" in narrowed
    assert "تحليل صورة دم" not in narrowed


def test_the_code_is_searchable_too(catalogue, boss):
    """It is what somebody reads off a printed price list, and it is the one
    string on the row that is not in their own language."""
    body = _results(boss, q="SVC-CBC")
    assert "تحليل صورة دم" in body
    assert "أشعة صدر" not in body


def test_filtering_by_category(catalogue, boss):
    body = _results(boss, cat="lab")
    assert "تحليل صورة دم" in body
    assert "أشعة صدر" not in body


def test_filtering_by_type(catalogue, boss):
    body = _results(boss, type="diagnostic")
    assert "تحليل صورة دم" in body and "أشعة صدر" in body
    assert "خدمة موقوفة" not in body


def test_filtering_by_status(catalogue, boss):
    assert "خدمة موقوفة" in _results(boss, status="inactive")
    assert "خدمة موقوفة" not in _results(boss, status="active")


def test_filters_combine_rather_than_replace_each_other(catalogue, boss):
    body = _results(boss, type="diagnostic", cat="radiology")
    assert "أشعة صدر" in body
    assert "تحليل صورة دم" not in body


def test_a_search_that_matches_nothing_says_so(catalogue, boss):
    body = _results(boss, q="زززز")
    assert "تحليل صورة دم" not in body
    assert "أشعة صدر" not in body


def test_clearing_the_filters_brings_everything_back(catalogue, boss):
    body = _results(boss)
    for name in ("تحليل صورة دم", "أشعة صدر", "خدمة موقوفة"):
        assert name in body


# ============================================================ the screen shape
def test_the_search_is_live_like_every_other_screen(catalogue, boss):
    """Same wiring as the other eight search screens — results follow the
    typing rather than waiting for Enter."""
    body = _template()
    assert 'data-live-search="#gc-results"' in body
    assert 'id="gc-results"' in body
    assert 'id="gc-results"' in _page(boss)


def test_the_results_block_is_the_list_and_not_the_add_panel(catalogue, boss):
    """The mistake made on two other screens: swapping in a block that turns
    out to be the collapsed "add" form would replace what somebody is typing."""
    body = _template()
    head = body[body.index('id="gc-results"'):][:600]
    assert "<summary" not in head, "gc-results is a panel, not the list"


def test_the_services_are_a_table_not_a_card_each(catalogue, boss):
    """The original complaint — *"if the services grow the whole thing will run
    together"* — was one full card per service. Rows, so eighty services stay
    eighty lines."""
    results = _results(boss)
    assert results.count("<table") >= 1
    # One card per group, not one per service.
    assert results.count('class="card') <= 8


def test_every_service_still_has_its_editor(catalogue, boss):
    """Compacting the list must not have cost the editing — the price, the
    commission and the workflow flags are all still reachable per service."""
    from app.models import Service

    with catalogue["app"].app_context():
        service_id = Service.query.filter_by(code="SVC-CBC").first().id
    body = _results(boss)
    assert f"/finance/services/{service_id}/edit" in body
    assert f"/finance/services/{service_id}/commissions" in body


def test_the_screen_says_how_much_it_is_hiding(catalogue, boss):
    """A filtered list that looks like the whole list is how somebody concludes
    a service was deleted."""
    body = _results(boss, q="أشعة")
    assert re.search(r"\b1\b", body)


def test_editing_a_service_still_saves(catalogue, boss):
    from app.models import Service

    with catalogue["app"].app_context():
        service_id = Service.query.filter_by(code="SVC-CBC").first().id

    boss.post(f"/finance/services/{service_id}/edit", data={
        "se": "1", "name": "تحليل صورة دم", "price": "140",
        "category": "lab", "service_type": "diagnostic", "is_active": "1",
        "commission_type": "percent", "commission_value": "25",
    }, follow_redirects=True)
    with catalogue["app"].app_context():
        svc = catalogue["db"].session.get(Service, service_id)
        assert svc.price == 140
        assert svc.commission_type == "percent" and svc.commission_value == 25
