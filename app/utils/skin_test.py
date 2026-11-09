"""The skin test before an antibiotic injection, in emergency.

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


def is_antibiotic(order):
    """An antibiotic by its ingredients' ATC code, or by name."""
    from app.utils.allergy import _families_of
    from app.utils.rx_safety import _generic_of

    generics = []
    drug = getattr(order, "drug", None)
    if drug is not None:
        generics = list(drug.all_ingredients())
    if not generics:
        g = _generic_of({"name": order.name or "", "drug": drug})
        generics = [g] if g is not None else []
    if any((getattr(g, "atc_code", "") or "").upper().startswith("J01") for g in generics):
        return True
    names = [order.name or ""] + [getattr(g, "name_en", "") or "" for g in generics] \
        + [getattr(g, "name_ar", "") or "" for g in generics]
    return any(set(_families_of(n)) & set(ANTIBIOTIC_FAMILIES) for n in names if n)


def needed(order):
    """Does this order wait for a skin test before it is given?"""
    if order is None or not enabled() or order.given_at or order.cancelled_at:
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
    if order.given_at or order.cancelled_at:
        raise SkinTestError("closed")
    order.skin_test_result = result
    order.skin_test_at = at or datetime.utcnow()
    order.skin_test_by = getattr(user, "id", None)
    if result == "positive":
        patient = order.patient
        when = (at or datetime.utcnow()).date().isoformat()
        line = f"{order.name} (اختبار جلد إيجابي {when})"
        existing = (patient.allergies or "").strip()
        if order.name and order.name.lower() not in existing.lower():
            patient.allergies = f"{existing}، {line}" if existing else line
    db.session.flush()
    return order
