"""One offer, however many clubs honour it.

A club discount named exactly one entity. A clinic offering the same terms to
four clubs therefore kept four identical rules — and four places to forget when
the terms change, which is how one club quietly keeps last year's discount.

The offer is one thing; the list of cards it honours is a list.

**Nothing an existing clinic saved stops working.** The old single column is
still read and still written when exactly one club is chosen, so a rule saved
before this reads the same afterwards and a rule saved after this reads the
same to anything still looking at the old column.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def clubs(clinic):
    """Two clubs, and a child holding a card for the second one."""
    from app.models import PayerEntity

    with clinic["app"].app_context():
        smouha = PayerEntity(name="نادي سموحة", entity_type="club", is_active=True)
        sporting = PayerEntity(name="نادي سبورتنج", entity_type="club",
                               is_active=True)
        clinic["db"].session.add_all([smouha, sporting])
        clinic["db"].session.commit()
        return {"smouha": smouha.id, "sporting": sporting.id}


def _card(clinic, payer_id):
    """Give the fixture's child a valid card for one club."""
    from app.models import PatientCoverage

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=payer_id,
            membership_number="M-1", is_active=True))
        clinic["db"].session.commit()


def _discount(clinic, payer_ids):
    from app.models import NamedDiscount, PayerEntity

    with clinic["app"].app_context():
        row = NamedDiscount(name="أعضاء الأندية", dtype="payer", value=20,
                            is_percent=True, is_active=True)
        row.payers = PayerEntity.query.filter(
            PayerEntity.id.in_(payer_ids)).all()
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _applies(clinic, discount_id):
    from app.models import NamedDiscount, Patient

    with clinic["app"].app_context():
        row = clinic["db"].session.get(NamedDiscount, discount_id)
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        return row.applies_to(patient=patient)


# ================================================ one rule, several clubs ===
def test_a_member_of_either_club_gets_the_one_discount(clubs, clinic):
    """The point: the same terms across several clubs are one rule."""
    _card(clinic, clubs["sporting"])
    assert _applies(clinic, _discount(clinic, [clubs["smouha"],
                                               clubs["sporting"]])) is True


def test_a_member_of_the_other_one_gets_it_too(clubs, clinic):
    _card(clinic, clubs["smouha"])
    assert _applies(clinic, _discount(clinic, [clubs["smouha"],
                                               clubs["sporting"]])) is True


def test_somebody_with_no_card_still_gets_nothing(clubs, clinic):
    """Widening who is covered must not widen it to everybody."""
    assert _applies(clinic, _discount(clinic, [clubs["smouha"],
                                               clubs["sporting"]])) is False


def test_a_card_for_a_club_that_is_not_named_does_not_qualify(clubs, clinic):
    _card(clinic, clubs["sporting"])
    assert _applies(clinic, _discount(clinic, [clubs["smouha"]])) is False


def test_a_rule_naming_nobody_applies_to_nobody(clubs, clinic):
    _card(clinic, clubs["sporting"])
    assert _applies(clinic, _discount(clinic, [])) is False


# ====================================== and the rules already on the books ==
def test_a_rule_saved_the_old_way_still_works(clubs, clinic):
    """Written straight to the single column, as every existing clinic's rules
    are. Reading only the new list would silently switch those off — a discount
    that stops applying and says nothing is the worst way for this to fail."""
    from app.models import NamedDiscount

    _card(clinic, clubs["smouha"])
    with clinic["app"].app_context():
        row = NamedDiscount(name="قديم", dtype="payer", value=10,
                            payer_id=clubs["smouha"], is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        rid = row.id
    assert _applies(clinic, rid) is True


def test_choosing_exactly_one_still_fills_the_old_column(boss, clubs, clinic):
    """So a rule saved today reads the same to anything still looking there."""
    from app.models import NamedDiscount

    boss.post("/finance/discounts", data={
        "name": "نادي واحد", "dtype": "payer", "value": "15",
        "unit": "percent", "payer_ids": [str(clubs["smouha"])]},
        follow_redirects=True)
    with clinic["app"].app_context():
        row = NamedDiscount.query.filter_by(name="نادي واحد").one()
        assert row.payer_id == clubs["smouha"]
        assert [p.id for p in row.payers] == [clubs["smouha"]]


def test_choosing_several_leaves_the_old_column_empty(boss, clubs, clinic):
    """It cannot hold two, and picking one of them arbitrarily would make old
    code report the wrong club rather than none."""
    from app.models import NamedDiscount

    boss.post("/finance/discounts", data={
        "name": "ناديين", "dtype": "payer", "value": "15", "unit": "percent",
        "payer_ids": [str(clubs["smouha"]), str(clubs["sporting"])]},
        follow_redirects=True)
    with clinic["app"].app_context():
        row = NamedDiscount.query.filter_by(name="ناديين").one()
        assert row.payer_id is None
        assert set(row.payer_ids) == {clubs["smouha"], clubs["sporting"]}


# ================================================================ the screen ==
def test_the_screen_lets_more_than_one_be_picked(boss, clubs, clinic):
    body = boss.get("/finance/discounts").get_data(as_text=True)
    assert 'name="payer_ids" multiple' in body


def test_editing_keeps_the_clubs_that_were_chosen(boss, clubs, clinic):
    from app.models import NamedDiscount

    rid = _discount(clinic, [clubs["smouha"], clubs["sporting"]])
    boss.post(f"/finance/discounts/{rid}/edit", data={
        "name": "أعضاء الأندية", "dtype": "payer", "value": "25",
        "unit": "percent",
        "payer_ids": [str(clubs["smouha"]), str(clubs["sporting"])]},
        follow_redirects=True)
    with clinic["app"].app_context():
        row = clinic["db"].session.get(NamedDiscount, rid)
        assert row.value == 25
        assert set(row.payer_ids) == {clubs["smouha"], clubs["sporting"]}


def test_the_list_shows_every_club_the_rule_covers(boss, clubs, clinic):
    """A row saying only the first one is a row that hides half the rule."""
    _discount(clinic, [clubs["smouha"], clubs["sporting"]])
    body = boss.get("/finance/discounts").get_data(as_text=True)
    assert "نادي سموحة" in body and "نادي سبورتنج" in body


def test_both_languages_carry_the_hint(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["discounts"].get("payer_multi_hint"), lang


# ============================================ and who, not just which club ==
def test_the_row_says_how_many_members_it_reaches(boss, clubs, clinic):
    """"Which club" is not the same question as "who gets it". A rule naming a
    club and showing nothing else leaves an admin unable to answer the only
    thing they opened the screen to check."""
    _card(clinic, clubs["smouha"])
    _discount(clinic, [clubs["smouha"], clubs["sporting"]])

    body = boss.get("/finance/discounts").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("discounts.members_hint") in body


def test_the_count_is_of_cards_that_are_valid_today(boss, clubs, clinic):
    """A club with forty expired cards gives nobody a discount, and a row
    saying "40" there would be worse than saying nothing."""
    from datetime import timedelta

    from app.models import PatientCoverage

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=clubs["smouha"],
            membership_number="OLD", is_active=True,
            expiry_date=date.today() - timedelta(days=1)))
        clinic["db"].session.commit()

    from app.blueprints.finance.routes import _valid_member_counts

    with clinic["app"].app_context():
        assert _valid_member_counts().get(clubs["smouha"], 0) == 0


def test_a_switched_off_card_is_not_counted(clubs, clinic):
    from app.models import PatientCoverage

    from app.blueprints.finance.routes import _valid_member_counts

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=clubs["smouha"],
            membership_number="OFF", is_active=False))
        clinic["db"].session.commit()
        assert _valid_member_counts().get(clubs["smouha"], 0) == 0


def test_a_valid_card_is_counted(clubs, clinic):
    from app.blueprints.finance.routes import _valid_member_counts

    _card(clinic, clubs["smouha"])
    with clinic["app"].app_context():
        assert _valid_member_counts()[clubs["smouha"]] == 1


def test_the_members_screen_finds_a_discount_that_names_several_clubs(
        boss, clubs, clinic):
    """The bug the multi-club change would otherwise have introduced: this
    screen asked the single column, so a club covered by a shared rule would
    be told it has no discount — on the screen somebody opens to check."""
    _discount(clinic, [clubs["smouha"], clubs["sporting"]])
    body = boss.get(f"/finance/payers/{clubs['sporting']}/members").get_data(
        as_text=True)
    assert "أعضاء الأندية" in body


# ================================ the two fields that were not additive =====
def test_a_named_service_overrides_the_scope_entirely(clinic):
    """Asked directly, and the answer was yes — a discount with a specific
    service applies to that service and nothing else, whatever the scope above
    it says. Worth a test because the screen used to show both as if they
    combined: pick "vaccinations" and then "كشف" and the discount silently
    lands on the exam."""
    from app.models import NamedDiscount, Service

    with clinic["app"].app_context():
        exam = clinic["db"].session.get(Service, clinic["ids"]["exam"])
        nebul = clinic["db"].session.get(Service, clinic["ids"]["nebul"])
        rule = NamedDiscount(name="كشف بس", dtype="special", value=70,
                             is_percent=False, scope="vaccination_fee",
                             service_id=exam.id, is_active=True)

        class _Line:
            def __init__(self, service):
                self.service = service
                self.vaccine_brand_id = None

        assert rule.applies_to_line(_Line(exam)) is True
        # …and the scope it contradicts changes nothing.
        assert rule.applies_to_line(_Line(nebul)) is False


def test_without_a_named_service_the_scope_is_what_decides(clinic):
    from app.models import NamedDiscount, Service

    with clinic["app"].app_context():
        exam = clinic["db"].session.get(Service, clinic["ids"]["exam"])
        nebul = clinic["db"].session.get(Service, clinic["ids"]["nebul"])
        rule = NamedDiscount(name="الكشوفات", dtype="special", value=10,
                             scope="consultation", is_active=True)

        class _Line:
            def __init__(self, service):
                self.service = service
                self.vaccine_brand_id = None

        assert rule.applies_to_line(_Line(exam)) is True      # consultation
        assert rule.applies_to_line(_Line(nebul)) is False    # procedure


def test_the_screen_says_the_scope_is_being_overridden(boss, clinic):
    """It used to show two fields as though they combined."""
    body = boss.get("/finance/discounts").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("discounts.scope_overridden") in body
        assert t("discounts.service_only") in body
