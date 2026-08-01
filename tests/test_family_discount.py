"""A child is entitled through every parent, not just the one you phone.

Reported: *"the father is staff and the mother is a friend and is the primary
contact — apply the bigger entitlement."*

The program read ``patient.client_category``, which sorts the parents by who is
the primary contact and takes the first one. That field decides **who to ring
about an appointment**. It was deciding what the family pays.

What this fix does **not** do is rank the categories. Whether staff is worth
more than friend is the clinic's pricing decision, written into the discounts
themselves; inventing an order in the model would quietly overrule it — and the
clinic that made "friend" the generous one would never find out why.

It does not need to, either: the billing side already prices **every** rule the
child qualifies for against the real invoice and applies the largest. That part
was right all along. The only thing broken was eligibility, so the only thing
that changes is eligibility.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def family(clinic):
    """A child with a staff father and a friend mother — and she is the contact."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        fam = Family(family_name="عائلة قنديل")
        clinic["db"].session.add(fam)
        clinic["db"].session.flush()

        clinic["db"].session.add(Parent(
            family_id=fam.id, full_name="الأب", relation="father",
            client_category="employee", is_primary_contact=False))
        clinic["db"].session.add(Parent(
            family_id=fam.id, full_name="الأم", relation="mother",
            client_category="friend", is_primary_contact=True))

        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.family_id = fam.id
        clinic["db"].session.commit()
        clinic["family"] = fam.id
    return clinic


def _child(family):
    from app.models import Patient

    return family["db"].session.get(Patient, family["ids"]["child"])


def _rule(family, category, value, name="خصم"):
    from app.models import NamedDiscount

    row = NamedDiscount(name=name, dtype="category", client_category=category,
                        value=value, is_percent=True, is_active=True,
                        auto_apply=True, scope="all")
    family["db"].session.add(row)
    family["db"].session.flush()
    return row


def _invoice(family, total=1000):
    from app.models import Invoice, InvoiceItem

    inv = Invoice(invoice_number="INV-F1", patient_id=family["ids"]["child"],
                  invoice_date=date.today(), status="issued")
    family["db"].session.add(inv)
    family["db"].session.flush()
    inv.items.append(InvoiceItem(description="كشف", quantity=1,
                                 unit_price=total))
    family["db"].session.flush()
    return inv


# ------------------------------------------------------- who counts --------
def test_the_child_is_entitled_through_every_parent(family):
    with family["app"].app_context():
        assert _child(family).client_categories == {"employee", "friend"}


def test_the_single_category_still_names_the_contact(family):
    """Kept deliberately: a screen has to print one thing beside the name. It
    just must not be what decides the price."""
    with family["app"].app_context():
        assert _child(family).client_category == "friend"


def test_the_fathers_rule_now_reaches_the_child(family):
    """The reported case. Before this, the father being staff was thrown away
    by a field that only decides who to telephone."""
    with family["app"].app_context():
        assert _rule(family, "employee", 30).applies_to(_child(family)) is True


def test_the_mothers_rule_still_reaches_the_child(family):
    with family["app"].app_context():
        assert _rule(family, "friend", 10).applies_to(_child(family)) is True


def test_a_category_nobody_in_the_family_has_does_not(family):
    """Widening eligibility must not become "everyone qualifies for
    everything"."""
    with family["app"].app_context():
        assert _rule(family, "relative", 90).applies_to(_child(family)) is False


def test_a_child_with_no_family_is_an_ordinary_client(family):
    from app.models import Patient

    with family["app"].app_context():
        orphaned = Patient(patient_number="P9", full_name="طفل", gender="male",
                           date_of_birth=date(2024, 1, 1), is_active=True)
        family["db"].session.add(orphaned)
        family["db"].session.flush()
        assert orphaned.client_categories == {"normal"}
        assert _rule(family, "employee", 30).applies_to(orphaned) is False


def test_a_parent_with_no_category_reads_as_normal(family):
    """An imported row with the column blank is an ordinary client, not a
    family with a ``None`` entitlement floating in the set."""
    from app.models import Family, Parent, Patient

    with family["app"].app_context():
        fam = Family(family_name="عائلة تانية")
        family["db"].session.add(fam)
        family["db"].session.flush()
        parent = Parent(family_id=fam.id, full_name="أب", relation="father",
                        is_primary_contact=True)
        parent.client_category = None
        family["db"].session.add(parent)
        kid = Patient(patient_number="P8", full_name="طفل", gender="male",
                      date_of_birth=date(2024, 1, 1), is_active=True,
                      family_id=fam.id)
        family["db"].session.add(kid)
        family["db"].session.commit()
        assert kid.client_categories == {"normal"}


# ------------------------------------------------- and the bigger one wins --
def test_the_larger_entitlement_is_the_one_applied(family):
    """The whole point of the report. The father's 30% beats the mother's 10%,
    and it is chosen by pricing both against the actual bill — not by ranking
    "staff" above "friend" in the code."""
    from app.blueprints.finance.routes import _best_discount

    with family["app"].app_context():
        _rule(family, "friend", 10, name="صديق")
        _rule(family, "employee", 30, name="موظف")
        inv = _invoice(family, total=1000)
        best = _best_discount(inv, _child(family))
        assert best is not None and best.name == "موظف"


def test_the_bigger_one_wins_whichever_parent_it_came_from(family):
    """The mirror image: if the friend rule is the generous one, it wins. The
    code has no opinion about which category is worth more."""
    from app.blueprints.finance.routes import _best_discount

    with family["app"].app_context():
        _rule(family, "friend", 40, name="صديق")
        _rule(family, "employee", 5, name="موظف")
        inv = _invoice(family, total=1000)
        best = _best_discount(inv, _child(family))
        assert best is not None and best.name == "صديق"


def test_only_one_is_applied_not_both(family):
    """Entitled through two parents is not entitled twice."""
    from app.blueprints.finance.routes import _best_discount, _discount_worth

    with family["app"].app_context():
        _rule(family, "friend", 10, name="صديق")
        _rule(family, "employee", 30, name="موظف")
        inv = _invoice(family, total=1000)
        best = _best_discount(inv, _child(family))
        assert _discount_worth(inv, best) == 300.0        # not 400
