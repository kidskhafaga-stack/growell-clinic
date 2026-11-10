"""The drugs this clinic writes most that have no dose by weight behind them
(PLAN_2026-08-08 «تغطية حساب الجرعة»).

The dose check covers the ingredients that carry a rule — a few dozen — and
the register holds twenty-five thousand names. Filling it is clinical work,
and the program will not invent a number. So this lists, from the clinic's
own prescriptions, what is written most and has no rule, most first, each
with the door to write its rule — so a doctor starts with the thirty that
cover most of what is actually prescribed, not with the register.

A line is **covered** when its ingredient carries a dose per kilo (the rule
the prescription check reads), or its product does. It is grouped by
ingredient where one is known, else by product, else by the name as typed.
"""
from collections import OrderedDict
from datetime import timedelta

from app.extensions import db


def _covered(generic, drug):
    return bool((generic is not None and generic.dose_per_kg)
                or (drug is not None and drug.dose_per_kg))


def report(date_from, date_to, limit=200):
    """``{"lines", "covered", "pct", "rows"}`` — ``rows`` are the uncovered
    groups, most written first: ``{"kind", "generic", "drug", "name", "count",
    "last"}``."""
    from app.models import Prescription, PrescriptionItem
    from app.utils.rx_safety import _generic_of

    items = (db.session.query(PrescriptionItem, Prescription.rx_date)
             .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
             .filter(Prescription.rx_date >= date_from, Prescription.rx_date <= date_to)
             .all())
    seen, groups = {}, OrderedDict()
    covered = 0
    for item, day in items:
        drug = item.drug if item.drug_id else None
        key = (item.drug_id, (item.drug_name or "").strip().lower())
        if key not in seen:
            generic = _generic_of({"name": item.drug_name or "", "drug": drug})
            seen[key] = (generic, _covered(generic, drug))
        generic, ok = seen[key]
        if ok:
            covered += 1
            continue
        if generic is not None:
            gkey, kind = ("g", generic.id), "generic"
        elif drug is not None:
            gkey, kind = ("d", drug.id), "brand"
        else:
            gkey, kind = ("n", key[1]), "free"
        row = groups.setdefault(gkey, {"kind": kind, "generic": generic, "drug": drug,
                                       "name": (item.drug_name or "").strip(),
                                       "count": 0, "last": day})
        row["count"] += 1
        if day and (row["last"] is None or day > row["last"]):
            row["last"] = day
    total = len(items)
    rows = sorted(groups.values(), key=lambda r: (-r["count"], r["name"]))[:limit]
    return {"lines": total, "covered": covered,
            "pct": round(covered * 100 / total) if total else None, "rows": rows}


def window(days=180):
    from app.utils.clock import local_today

    end = local_today()
    return end - timedelta(days=days), end


#: The rule's fields, their type, and what a number may be.
FIELDS = (("dose_per_kg", float, 0.001, 1000), ("dose_per_kg_max", float, 0.001, 1000),
          ("doses_per_day", int, 1, 24), ("max_per_kg_day", float, 0.001, 5000),
          ("max_single_dose_mg", float, 0.001, 100000), ("max_daily_dose_mg", float, 0.001, 200000))


class RuleError(ValueError):
    """A refusal with a key (``dose_gaps.err_<key>``)."""


def write_rule(generic, form):
    """A doctor writes an ingredient's dose rule, **with its reference** — no
    reference, no rule. Returns ``{field: (old, new)}`` for the log. The
    caller commits."""
    reference = (form.get("reference") or "").strip()[:255]
    if not reference:
        raise RuleError("reference")
    new = {}
    for field, cast, low, high in FIELDS:
        raw = (form.get(field) or "").strip()
        if not raw:
            new[field] = None
            continue
        try:
            value = cast(float(raw))
        except ValueError:
            raise RuleError("number")
        if not low <= value <= high:
            raise RuleError("number")
        new[field] = value
    if not new["dose_per_kg"]:
        raise RuleError("dose")
    if new["dose_per_kg_max"] and new["dose_per_kg_max"] < new["dose_per_kg"]:
        raise RuleError("range")
    basis = form.get("dose_basis")
    new["dose_basis"] = basis if basis in ("per_dose", "per_day") else "per_dose"
    new["dose_note"] = (form.get("dose_note") or "").strip()[:255] or None
    new["reference"] = reference
    changed = {}
    for field, value in new.items():
        old = getattr(generic, field)
        if old != value:
            changed[field] = (old, value)
            setattr(generic, field, value)
    db.session.flush()
    return changed


def may_write(user):
    """A doctor, or whoever runs the clinic — a dose rule is a clinical number."""
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_admin or getattr(user, "role", None) == "doctor"))
