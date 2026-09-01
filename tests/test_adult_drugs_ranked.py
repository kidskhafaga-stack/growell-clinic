"""Two thousand adult products, and a clinic that treats to eighteen.

``ANTINEOPLASTIC``, ``PSYCHIATRIC``, ``STATINS``, ``ANTI-HYPERTENSIVE``,
``ANTI-DIABETIC`` — about 2,000 products the paediatric catalogue was carrying
without anybody having decided about them.

**The obvious move is the wrong one.** The cosmetics were deleted because a
children's clinic has no use for them at all. These are different, and the
clinic said why: *this doctor sees patients up to eighteen*. A sixteen-year-old
with type 1 diabetes needs insulin. An adolescent gets an antihypertensive, a
statin, an antidepressant. Deleting these takes the medicine away from the
patient who needs it — quietly, and on the day they need it.

So they stay, and the search stops putting them in front of a two-year-old.
Order, not deletion: the same answer as the doctor's own service list, and for
the same reason — the complaint is about hunting, so ranking fixes it and
permission would break something else.

**What the doctor typed always wins.** Age is a tie-breaker and never more.
Type "Concor" for a teenager and Concor is first whatever the ranking thinks;
the tier this actually repairs is the partial match, where two thousand adult
products crowd in beside the paediatric ones.

**And the real number beats the inference.** Where a product is linked to an
ingredient carrying ``min_age_months``, that is used — it is a fact about the
drug rather than a guess from a shelf label.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


def _drug(clinic, name, drug_class=None, generic=None):
    with clinic["app"].app_context():
        from app.models import Drug
        db = clinic["db"]
        row = Drug(trade_name=name, generic_name=name, drug_class=drug_class,
                   generic_id=generic, is_active=True)
        db.session.add(row)
        db.session.commit()
        return row.id


def _aged(clinic, years):
    with clinic["app"].app_context():
        from app.models import Patient
        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.date_of_birth = local_today() - timedelta(days=int(years * 365.25))
        db.session.commit()
        return patient.id


def _search(clinic, q, age_months=None):
    with clinic["app"].app_context():
        from app.utils.drug_search import search_drugs
        return [r["trade"] for r in
                search_drugs(q, limit=20, include_generics=False,
                             age_months=age_months)]


# --- nothing is deleted ---------------------------------------------------

@pytest.mark.parametrize("label", [
    "ANTI-DIABETIC", "STATINS", "PSYCHIATRIC", "ANTI-HYPERTENSIVE",
    "ANTINEOPLASTIC",
])
def test_the_adult_classes_are_still_seeded(label):
    """The decision that separates these from the cosmetics.

    A sixteen-year-old with type 1 diabetes is this clinic's patient. Removing
    insulin from the catalogue takes it away from them on the day they need it.
    """
    from app.utils.drug_classing import is_cosmetic

    assert is_cosmetic(label) is False, f"{label} is being dropped at seed time"


def test_an_adult_drug_is_still_findable_for_a_toddler(clinic):
    """Sunk, never hidden — a two-year-old occasionally needs one of these,
    and a doctor who cannot find a drug at all is a worse problem."""
    _drug(clinic, "Glucophage", drug_class="ANTI-DIABETIC")
    assert "Glucophage" in _search(clinic, "gluco", age_months=24)


# --- ranking --------------------------------------------------------------

def test_a_toddlers_list_puts_the_paediatric_one_first(clinic):
    """The complaint, reproduced: two products, one partial match.

    The names are chosen so the **alphabet opposes the expected answer** — the
    adult product sorts first. Written the natural way round, this passed with
    the ranking removed entirely, which is to say it tested nothing. Every
    ordering assertion below is built the same way.
    """
    _drug(clinic, "Cardio A", drug_class="ANTI-HYPERTENSIVE")
    _drug(clinic, "Cardio Z syrup", drug_class="VITAMIN")

    order = _search(clinic, "cardi", age_months=24)
    assert order.index("Cardio Z syrup") < order.index("Cardio A")


def test_a_teenagers_list_does_not_sink_them(clinic):
    """The whole reason these were not deleted.

    Above the adolescent threshold nothing sinks: a teenager's insulin must
    not be buried by a rule written for toddlers.
    """
    _drug(clinic, "Cardio A", drug_class="ANTI-HYPERTENSIVE")
    _drug(clinic, "Cardio Z syrup", drug_class="VITAMIN")

    # Asserted as "the age stops changing the order", not as a fixed order:
    # once nothing sinks, the tiebreak is the plain alphabetical one and
    # pinning that here would only be re-testing `sorted`.
    teen = _search(clinic, "cardi", age_months=16 * 12)
    assert teen == _search(clinic, "cardi"), (
        "a teenager's list is still being reordered by an adult-shelf label")

    toddler = _search(clinic, "cardi", age_months=24)
    assert toddler != teen, "the two ages produce the same list"


def test_what_the_doctor_typed_still_wins(clinic):
    """Age is a tie-breaker and never outranks the text.

    Somebody typing an exact brand for a two-year-old means that brand — the
    program does not get to second-guess it from a shelf label.
    """
    _drug(clinic, "Concor", drug_class="ANTI-HYPERTENSIVE")
    _drug(clinic, "Concor-like syrup", drug_class="VITAMIN")

    assert _search(clinic, "concor", age_months=24)[0] == "Concor"


def test_no_patient_ranks_exactly_as_it_used_to(clinic):
    """A search with nobody behind it must not invent an opinion."""
    _drug(clinic, "Cardio A", drug_class="ANTI-HYPERTENSIVE")
    _drug(clinic, "Cardio Z syrup", drug_class="VITAMIN")

    assert _search(clinic, "cardi") == sorted(_search(clinic, "cardi"))


# --- the real number beats the label --------------------------------------

def test_the_ingredients_own_minimum_age_is_used_when_there_is_one(clinic):
    """A fact about the drug, not an inference from a shelf.

    Ibuprofen is not on any adult shelf and is still wrong for a newborn. The
    dosing rule already knows that, so the ranking asks it.
    """
    with clinic["app"].app_context():
        from app.models import GenericDrug
        db = clinic["db"]
        gen = GenericDrug(name_en="ibuprofen", name_ar="إيبوبروفين",
                          min_age_months=6, is_active=True)
        db.session.add(gen)
        db.session.commit()
        gen_id = gen.id

    _drug(clinic, "Bruf A drops", drug_class="ANTIPYRETIC", generic=gen_id)
    _drug(clinic, "Bruf Z syrup", drug_class="ANTIPYRETIC")

    young = _search(clinic, "bruf", age_months=2)
    assert young.index("Bruf Z syrup") < young.index("Bruf A drops"), (
        "a two-month-old is being offered ibuprofen first")

    # Past the minimum the rule stops applying, so the order returns to what
    # it is with no patient at all.
    older = _search(clinic, "bruf", age_months=24)
    assert older == _search(clinic, "bruf")
    assert older != young, "the minimum age changed nothing"


def test_the_class_is_only_consulted_without_a_dosing_rule(clinic):
    """Otherwise a linked adult drug with paediatric dosing would still sink."""
    from app.utils.drug_search import age_fit

    class _Gen:
        min_age_months = 0

    class _Drug:
        drug_class = "ANTI-DIABETIC"
        generic = _Gen()

    assert age_fit(_Drug(), 24) == 0, (
        "an explicit paediatric minimum is being overruled by the shelf label")


# --- reaching the screen --------------------------------------------------

def test_the_visit_room_sends_the_patient(clinic):
    """The ranking is worth nothing if the age never leaves the page."""
    body = (clinic["sign_in"]("doc")
            .get(f"/visits/{clinic['ids']['visit']}/record")
            .get_data(as_text=True))
    assert f"patient_id={clinic['ids']['child']}" in body


def test_the_search_endpoint_reads_it(clinic):
    _drug(clinic, "Cardio A", drug_class="ANTI-HYPERTENSIVE")
    _drug(clinic, "Cardio Z syrup", drug_class="VITAMIN")
    patient_id = _aged(clinic, 2)

    doc = clinic["sign_in"]("doc")
    ranked = doc.get(f"/visits/drugs/search?q=cardi&patient_id={patient_id}").get_json()
    names = [r["trade"] for r in ranked]
    assert names.index("Cardio Z syrup") < names.index("Cardio A")


def test_an_unknown_patient_is_not_an_error(clinic):
    """A stale id in a URL must rank on the text, not raise."""
    _drug(clinic, "Cardio A", drug_class="ANTI-HYPERTENSIVE")
    response = clinic["sign_in"]("doc").get(
        "/visits/drugs/search?q=cardi&patient_id=999999")
    assert response.status_code == 200
