"""The skin test before an antibiotic injection, in emergency and on the ward.

Asked: *«خد بالك من اختبار حساسية المضادات الحيوية»* — and, when asked which
one: **the skin test before the injection**. Before an antibiotic is injected
(ceftriaxone, penicillin…), the nurse gives a small test dose under the skin
and reads it. The program:

* **asks for it** on every injectable antibiotic written in emergency — an
  order whose route is IM or IV and whose medicine is an antibiotic: an
  ingredient coded J01 (antibacterials for systemic use, ATC), or a name in
  one of the antibiotic families the allergy check already knows;
* **does not let «given» be pressed** until the result is written, and never
  after a positive one;
* **writes a positive result on the child's allergies**, in words, so the
  allergy check, the prescription and every screen after it know it.

**On the ward** (DOCTOR_EASE د-٢) the owner chose **once per drug in the
stay**: the first dose of an injected antibiotic waits for the result, and the
doses after it — and a second order for the same drug in the same stay — do
not ask again. A drug already given in this stay is tolerated, not untested.

It decides nothing about whether a skin test is the right practice — that is
the hospital's: it is on unless the hospital switches it off
(:data:`SETTING`), and the program only holds the line it was asked to hold.
"""
from datetime import datetime

from app.extensions import db

SETTING = "er_skin_test"
RESULTS = ("negative", "positive")
INJECTED = ("im", "iv")
#: The antibiotic families of the allergy check (``utils/allergy.FAMILIES``).
ANTIBIOTIC_FAMILIES = ("penicillin", "cephalosporin", "macrolide", "sulfa")


class SkinTestError(ValueError):
    """A refusal with a key (``skin_test.err_<key>``)."""


def enabled():
    from app.models import Setting

    return (Setting.get(SETTING, "1") or "1") == "1"


def _name(order):
    return getattr(order, "name", None) or getattr(order, "drug_name", None) or ""


def _on_ward(order):
    return hasattr(order, "admission_id") and hasattr(order, "drug_name")


def _same_drug(a, b):
    if a.drug_id and b.drug_id:
        return a.drug_id == b.drug_id
    return (_name(a) or "").strip().lower() == (_name(b) or "").strip().lower()


def _given(order):
    from app.models.medication import GIVEN

    return any(d.outcome == GIVEN for d in (order.doses or []))


def _cleared_in_stay(order):
    """The ward's «once per drug in the stay»: this drug was tested negative
    or already given in this stay — on this order or an earlier one."""
    for other in (order.admission.medication_orders if order.admission else [order]):
        if other.route not in INJECTED or not _same_drug(order, other):
            continue
        if other.skin_test_result == "negative" or _given(other):
            return True
    return False


def is_antibiotic(order):
    """An antibiotic by its ingredients' ATC code, or by name."""
    from app.utils.allergy import _families_of
    from app.utils.rx_safety import _generic_of

    generics = []
    drug = getattr(order, "drug", None)
    if drug is not None:
        generics = list(drug.all_ingredients())
    if not generics:
        g = _generic_of({"name": _name(order), "drug": drug})
        generics = [g] if g is not None else []
    if any((getattr(g, "atc_code", "") or "").upper().startswith("J01") for g in generics):
        return True
    names = [_name(order)] + [getattr(g, "name_en", "") or "" for g in generics] \
        + [getattr(g, "name_ar", "") or "" for g in generics]
    return any(set(_families_of(n)) & set(ANTIBIOTIC_FAMILIES) for n in names if n)


def needed(order):
    """Does this order wait for a skin test before it is given?"""
    if order is None or not enabled():
        return False
    if _on_ward(order):
        if not order.is_running or order.route not in INJECTED:
            return False
        if order.skin_test_result != "positive" and _cleared_in_stay(order):
            return False
        return is_antibiotic(order)
    if order.given_at or order.cancelled_at:
        return False
    return (order.route in INJECTED) and is_antibiotic(order)


def blocks(order):
    """Why «given» is refused now, or ``None``: ``"skin_test"`` until a
    result is written, ``"skin_positive"`` after a positive one."""
    if not needed(order):
        return None
    if order.skin_test_result == "positive":
        return "skin_positive"
    if order.skin_test_result != "negative":
        return "skin_test"
    return None


def record(order, result, user, at=None):
    """Write the result. A positive one goes on the child's allergies. The
    caller commits."""
    if result not in RESULTS:
        raise SkinTestError("result")
    if _on_ward(order):
        if not order.is_running or _given(order):
            raise SkinTestError("closed")
    elif order.given_at or order.cancelled_at:
        raise SkinTestError("closed")
    order.skin_test_result = result
    order.skin_test_at = at or datetime.utcnow()
    order.skin_test_by = getattr(user, "id", None)
    if result == "positive":
        patient = order.patient
        when = (at or datetime.utcnow()).date().isoformat()
        name = _name(order)
        line = f"{name} (اختبار جلد إيجابي {when})"
        existing = (patient.allergies or "").strip()
        if name and name.lower() not in existing.lower():
            patient.allergies = f"{existing}، {line}" if existing else line
    db.session.flush()
    return order
