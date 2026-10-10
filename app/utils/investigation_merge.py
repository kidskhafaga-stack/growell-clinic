"""Two copies of one test, made one — «اعمل أداة الدمج».

Clinics that took the starter list before it was cleaned carry CBC, CRP,
ESR, blood culture and urine culture twice: the codeless rows they have been
ordering for months, and the coded copies the specialty panels brought under
another Arabic name. Doctors pick either, so a child's results are split
between two rows and the curve shows half of them.

**What a merge does** (the kept row is ``keep``, the other ``drop``):

* every order and every prescription line that pointed at ``drop`` points at
  ``keep`` — the name written on each order is its own copy and does not
  change, so nothing already printed reads differently;
* what the laboratory defined on ``drop`` — its components, consumables,
  referral prices, written procedures and method checks — moves to ``keep``,
  except where ``keep`` already has the same thing (``keep``'s wins);
* every box ``keep`` left empty is filled from ``drop`` — the code first,
  so the specialty panels find the one test that remains;
* ``drop``'s names become ``keep``'s aliases, so a doctor who searches the
  old name still finds it;
* ``drop`` is deleted, and the merge is written in the activity log.

**Refused**: a test merged into itself, or across kinds (a film is not a
blood test). Nothing is merged on a guess — :func:`twins` only *suggests*,
and a person chooses which copy stays.
"""
import re

from app.extensions import db

#: Copied onto ``keep`` only where ``keep`` has nothing.
_FILL = ("code", "name_en", "category", "unit", "sample_type", "service_id",
         "tube", "preparation", "tat_min", "tat_max", "tat_stat_min",
         "tat_stat_max", "referral_lab_id", "keep_days", "cost", "device_id",
         "needs_booking", "modality", "dose_ref_kind", "dose_ref_value",
         "dose_ref_unit")


class MergeError(ValueError):
    """A refusal with a key the screen can name (``merge.err_<key>``)."""


def _bare(text):
    """A name without what is in brackets, its punctuation or its case."""
    text = re.sub(r"\(.*?\)", " ", text or "")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.casefold().split())


def twins(kind="lab"):
    """``[(a, b)]`` — tests of one kind whose names are the same once what is
    in brackets is set aside («صورة دم كاملة» / «صورة دم كاملة (CBC)»), or
    whose English names are. A suggestion for a person, never acted on."""
    from app.models import Investigation

    rows = (Investigation.query.filter(Investigation.kind == kind)
            .order_by(Investigation.id).all())
    seen, pairs = {}, []
    for row in rows:
        keys = {("ar", _bare(row.name_ar))}
        if row.name_en:
            keys.add(("en", _bare(row.name_en)))
        partner = next((seen[k] for k in keys if k[1] and k in seen), None)
        if partner is not None and partner is not row:
            pairs.append((partner, row))
            continue
        for k in keys:
            if k[1]:
                seen.setdefault(k, row)
    return pairs


def usage(row):
    """How many orders and prescription lines point at ``row``."""
    from app.models import PrescriptionInvestigation, VisitInvestigation

    return {
        "orders": VisitInvestigation.query.filter_by(investigation_id=row.id).count(),
        "rx": PrescriptionInvestigation.query.filter_by(investigation_id=row.id).count(),
    }


def suggested_keep(a, b):
    """The copy more orders were written against; then the coded one; then
    the older."""
    ua, ub = usage(a), usage(b)
    score = lambda row, u: (u["orders"] + u["rx"], bool(row.code), -row.id)  # noqa: E731
    return a if score(a, ua) >= score(b, ub) else b


def merge(keep, drop, user=None):
    """Make ``drop`` part of ``keep``. Returns what moved. The caller commits."""
    from app.models import (ActivityLog, LabConsumable, LabTestAnalyte,
                            PrescriptionInvestigation, ReferralLabPrice,
                            VisitInvestigation)
    from app.models.lab_quality import LabProcedure, MethodCheck

    if keep is None or drop is None:
        raise MergeError("missing")
    if keep.id == drop.id:
        raise MergeError("same")
    if keep.kind != drop.kind:
        raise MergeError("kinds")

    moved = {
        "orders": VisitInvestigation.query.filter_by(investigation_id=drop.id)
        .update({VisitInvestigation.investigation_id: keep.id}, synchronize_session=False),
        "rx": PrescriptionInvestigation.query.filter_by(investigation_id=drop.id)
        .update({PrescriptionInvestigation.investigation_id: keep.id},
                synchronize_session=False),
        "procedures": LabProcedure.query.filter_by(investigation_id=drop.id)
        .update({LabProcedure.investigation_id: keep.id}, synchronize_session=False),
        "checks": MethodCheck.query.filter_by(investigation_id=drop.id)
        .update({MethodCheck.investigation_id: keep.id}, synchronize_session=False),
    }

    # Unique per test: what ``keep`` already has stays, ``drop``'s copy goes.
    def _move_unique(model, column):
        have = {getattr(r, column) for r in model.query.filter_by(investigation_id=keep.id)}
        n = 0
        for r in model.query.filter_by(investigation_id=drop.id).all():
            if getattr(r, column) in have:
                db.session.delete(r)
            else:
                # Through the relationship: the components and consumables
                # hang off the test with delete-orphan, and a row moved by
                # its column alone would still sit in ``drop``'s loaded list
                # and go when ``drop`` goes.
                r.investigation = keep
                n += 1
        return n

    moved["analytes"] = _move_unique(LabTestAnalyte, "analyte_id")
    moved["consumables"] = _move_unique(LabConsumable, "store_item_id")
    moved["prices"] = _move_unique(ReferralLabPrice, "lab_id")

    # The code is unique: taken off ``drop`` before ``keep`` can hold it.
    if drop.code and not keep.code:
        code, drop.code = drop.code, None
        db.session.flush()
        keep.code = code
    for column in _FILL:
        if column != "code" and getattr(keep, column) in (None, "") \
                and getattr(drop, column) not in (None, ""):
            setattr(keep, column, getattr(drop, column))

    names = [n for n in (drop.name_ar, drop.name_en, drop.aliases) if n]
    known = {a.strip().casefold() for a in (keep.aliases or "").split(",") if a.strip()}
    known |= {(keep.name_ar or "").casefold(), (keep.name_en or "").casefold()}
    extra = []
    for chunk in names:
        for a in chunk.split(","):
            a = a.strip()
            if a and a.casefold() not in known:
                known.add(a.casefold())
                extra.append(a)
    if extra:
        keep.aliases = ", ".join([x for x in [(keep.aliases or "").strip(", ")] if x] + extra)[:400]
    if drop.is_active and not keep.is_active:
        keep.is_active = True

    ActivityLog.record("lab.merge_tests", user_id=getattr(user, "id", None),
                       entity="investigation", entity_id=keep.id,
                       detail=f"{drop.id} «{drop.name_ar}» → {keep.id} «{keep.name_ar}» {moved}")
    db.session.flush()
    # Read ``drop``'s lists again from the database — empty now — so the
    # delete cascades over nothing that moved.
    db.session.expire(drop, ["analyte_links", "lab_consumables"])
    db.session.delete(drop)
    db.session.flush()
    return moved


__all__ = ["MergeError", "merge", "suggested_keep", "twins", "usage"]
