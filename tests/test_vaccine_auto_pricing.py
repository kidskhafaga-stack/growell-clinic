"""Auto-pricing a vaccine: the engine was there, the switch was not.

*"هامش الربح والتحديث التلقائي لسعر البيع موجود في الأصناف — يتعمل نفسه على
التطعيمات."*

The odd part is that nothing needed building underneath. ``VaccineBrand`` has
carried ``price_policy`` and ``margin_percent`` all along, and every goods
receipt already calls the same :func:`apply_purchase_cost` for a vaccine brand
as for a store item. What was missing was any way to *switch it on*: the
general store's item screen has the two fields and the vaccine's item card did
not, so the columns sat at their defaults for ever and the feature existed for
half the stock room.

So most of this file is about the behaviour that was already implemented and
unreachable — worth pinning precisely because "it was already there" is how a
feature gets quietly removed by somebody tidying up.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _set_pricing(clinic, policy="auto", margin=25, price=100, cost=80):
    """Save the brand's pricing through the screen, the way a user would."""
    return clinic["sign_in"]("boss").post(
        f"/inventory/item/{clinic['ids']['brand']}/pricing",
        data={"price_policy": policy, "margin_percent": margin,
              "price": price, "purchase_price": cost, "doses_per_vial": 1},
        follow_redirects=True)


def _brand(clinic):
    from app.models import VaccineBrand

    return clinic["db"].session.get(VaccineBrand, clinic["ids"]["brand"])


def _receive_at(clinic, cost):
    """A delivery at a new purchase cost, through the receipt screen."""
    return clinic["sign_in"]("boss").post("/inventory/receipt/new", data={
        "receipt_reason": "purchase", "received_date": date.today().isoformat(),
        "line_brand_id": clinic["ids"]["brand"], "line_qty": 5,
        "line_unit": "doses", "line_cost": cost,
    }, follow_redirects=True)


# ============================================== the switch ==================
def test_the_card_can_turn_auto_pricing_on(clinic):
    """The whole gap: the columns existed and nothing could set them."""
    _set_pricing(clinic, policy="auto", margin=30)

    with clinic["app"].app_context():
        brand = _brand(clinic)
        assert brand.price_policy == "auto"
        assert brand.margin_percent == 30


def test_the_fields_are_on_the_screen(clinic):
    page = clinic["sign_in"]("boss").get(
        f"/inventory/item/{clinic['ids']['brand']}").data.decode()
    assert 'name="price_policy"' in page
    assert 'name="margin_percent"' in page


def test_it_can_be_turned_back_off(clinic):
    """A clinic that priced a vaccine by hand after a supplier deal must not
    have the next delivery overwrite it."""
    _set_pricing(clinic, policy="auto", margin=30)
    _set_pricing(clinic, policy="manual", margin="", price=250)

    with clinic["app"].app_context():
        assert _brand(clinic).price_policy == "manual"

    _receive_at(clinic, 80)
    with clinic["app"].app_context():
        assert _brand(clinic).price == 250, "a manual price was overwritten"


# ============================================== what it then does ===========
def test_a_delivery_reprices_an_auto_vaccine(clinic):
    """The behaviour that was already implemented and unreachable."""
    _set_pricing(clinic, policy="auto", margin=25, price=100)
    _receive_at(clinic, 80)

    with clinic["app"].app_context():
        # 80 + 25% of 80.
        assert _brand(clinic).price == 100


def test_an_empty_margin_uses_the_clinics_default(clinic):
    """"سيبه فاضي = الهامش الافتراضي للعيادة" — the same rule the store has."""
    from app.models import Setting

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("default_margin_percent", "50")
        db.session.commit()

    _set_pricing(clinic, policy="auto", margin="", price=100)
    _receive_at(clinic, 80)

    with clinic["app"].app_context():
        assert _brand(clinic).margin_percent is None
        assert _brand(clinic).price == 120


def test_a_manual_vaccine_is_left_alone(clinic):
    """The default, and it has to stay the default: a clinic that has never
    heard of this feature must not find its prices moving."""
    _set_pricing(clinic, policy="manual", margin="", price=300)
    _receive_at(clinic, 80)

    with clinic["app"].app_context():
        assert _brand(clinic).price == 300


# ============================================== the preview =================
def test_the_screen_previews_the_price_the_engine_will_set(clinic):
    """The preview and the engine must use one formula. A preview computing
    the margin off the sell price instead of the cost would show 106.67 where
    the next delivery writes 100 — and the number would appear to change by
    itself days later."""
    from app.utils.costing import _auto_sell

    with open(os.path.join(os.path.dirname(__file__), "..", "app", "templates",
                           "inventory", "item_card.html"), encoding="utf-8") as fh:
        source = fh.read()

    assert "this.cost * (1 + m / 100)" in source, \
        "the preview no longer mirrors _auto_sell"
    assert _auto_sell(80, 25) == 100

