"""Microbiology on the bench — see ``app/models/micro.py`` for the shape.

* :func:`add_names` — the laboratory's lists, one name a line;
* :func:`set_outcome`, :func:`add_isolate`, :func:`save_isolate` — the
  culture answered in its parts, each part writing the summary again;
* :func:`summary` — the words every other screen reads;
* :func:`antibiogram` — a period's isolates counted as CLSI M39 counts them:
  **the first isolate of each organism per child** in the period, so one
  child cultured ten times is one child, not ten resistant strains.
"""
from datetime import datetime

from app.extensions import db
from app.models.micro import (OUTCOMES, READINGS, CultureIsolate, CultureResult,
                              CultureSusceptibility, MicroAntibiotic,
                              MicroOrganism)

#: CLSI M39: an organism with fewer isolates than this in the period is
#: shown, but said to be too few to guide a choice — the published figure,
#: not one of ours.
M39_MIN = 30


class MicroError(ValueError):
    """A refusal with a locale key (``micro.err_<key>``)."""


# ----------------------------------------------------------- the lists ---
def add_names(model, text):
    """One name a line; a name already there (any case) is skipped.
    Returns how many were added."""
    have = {m.name.casefold() for m in model.query.all()}
    added = 0
    for line in (text or "").splitlines():
        name = line.strip()[:120]
        if not name or name.casefold() in have:
            continue
        row = model(name=name)
        if model is MicroAntibiotic:
            row.sort_order = len(have) + added
        db.session.add(row)
        have.add(name.casefold())
        added += 1
    db.session.flush()
    return added


def organisms():
    return (MicroOrganism.query.filter_by(is_active=True)
            .order_by(MicroOrganism.name).all())


def antibiotics():
    return (MicroAntibiotic.query.filter_by(is_active=True)
            .order_by(MicroAntibiotic.sort_order, MicroAntibiotic.name).all())


# ----------------------------------------------------------- a culture ---
def is_culture(order):
    inv = getattr(order, "investigation", None)
    return bool(inv is not None and inv.is_culture)


def culture_of(order, create=False):
    row = CultureResult.query.filter_by(order_id=order.id).first()
    if row is None and create:
        row = CultureResult(order_id=order.id)
        db.session.add(row)
        db.session.flush()
    return row


def set_outcome(order, form, user=None):
    culture = culture_of(order, create=True)
    outcome = form.get("outcome") or None
    if outcome is not None and outcome not in OUTCOMES:
        raise MicroError("outcome")
    culture.outcome = outcome
    culture.final = form.get("final") == "1"
    culture.comment = (form.get("comment") or "").strip() or None
    return _write(order, culture, user)


def add_isolate(order, form, user=None):
    culture = culture_of(order, create=True)
    organism = db.session.get(MicroOrganism, form.get("organism_id", type=int) or 0)
    if organism is None:
        raise MicroError("organism")
    culture.isolates.append(CultureIsolate(
        organism=organism, count=(form.get("count") or "").strip()[:60] or None,
        sort_order=len(culture.isolates)))
    if culture.outcome in (None, "no_growth"):
        culture.outcome = "growth"
    return _write(order, culture, user)


def save_isolate(order, isolate, form, user=None):
    """The isolate's count and its readings; ``remove`` takes it off."""
    culture = culture_of(order)
    if culture is None or isolate.culture_id != culture.id:
        raise MicroError("isolate")
    if form.get("remove") == "1":
        culture.isolates.remove(isolate)
        db.session.delete(isolate)
        return _write(order, culture, user)
    isolate.count = (form.get("count") or "").strip()[:60] or None
    have = {r.antibiotic_id: r for r in isolate.readings}
    for abx in antibiotics():
        reading = (form.get(f"r_{abx.id}") or "").strip().upper()
        value = (form.get(f"v_{abx.id}") or "").strip()[:20] or None
        row = have.get(abx.id)
        if reading not in READINGS:
            if row is not None:
                isolate.readings.remove(row)
                db.session.delete(row)
            continue
        if row is None:
            row = CultureSusceptibility(antibiotic=abx)
            isolate.readings.append(row)
        row.reading, row.value = reading, value
    return _write(order, culture, user)


def alerts(culture):
    return [i.organism for i in (culture.isolates if culture else []) if i.organism.alert]


def summary(culture):
    """The structured answer in words, for every screen that reads words.
    In the language microbiology reports are written in."""
    if culture is None or not culture.outcome:
        return ""
    lines = []
    if not culture.final:
        lines.append("PRELIMINARY")
    if culture.outcome == "no_growth":
        lines.append("No growth")
    elif culture.outcome == "contaminated":
        lines.append("Contaminated — please repeat the sample")
    else:
        if culture.outcome == "mixed":
            lines.append("Mixed growth")
        for iso in culture.isolates:
            head = iso.organism.name + (f" ({iso.count})" if iso.count else "")
            if iso.organism.alert:
                head = "ALERT ORGANISM: " + head
            lines.append(head)
            by = {k: [] for k in READINGS}
            for r in sorted(iso.readings, key=lambda r: (r.antibiotic.sort_order, r.antibiotic.name)):
                by[r.reading].append(r.antibiotic.name + (f" {r.value}" if r.value else ""))
            for k, word in (("S", "Sensitive"), ("I", "Intermediate"), ("R", "Resistant")):
                if by[k]:
                    lines.append(f"  {word}: " + ", ".join(by[k]))
    if culture.comment:
        lines.append(culture.comment)
    return "\n".join(lines)


def _write(order, culture, user):
    from app.utils import labs as bench

    culture.updated_by = getattr(user, "id", None)
    culture.updated_at = datetime.utcnow()
    db.session.flush()
    bench.record(order, text=summary(culture), comment=None, user=user)
    return culture


# --------------------------------------------------------- antibiogram ---
def antibiogram(start, end):
    """``{"rows": [{organism, n, cells: {abx_id: (susceptible, tested)}}],
    "antibiotics": [...], "few": M39_MIN}`` for cultures resulted between
    ``start`` and ``end`` (dates) — the first isolate of each organism per
    child, with its readings. ``I`` is not counted susceptible (M39)."""
    from app.models import VisitInvestigation
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.max.time()))
    isolates = (CultureIsolate.query
                .join(CultureResult, CultureIsolate.culture_id == CultureResult.id)
                .join(VisitInvestigation, CultureResult.order_id == VisitInvestigation.id)
                .filter(VisitInvestigation.resulted_at >= since,
                        VisitInvestigation.resulted_at <= until)
                .order_by(VisitInvestigation.resulted_at, CultureIsolate.id).all())
    first, seen = [], set()
    for iso in isolates:
        key = (iso.culture.order.patient_id, iso.organism_id)
        if key in seen:
            continue
        seen.add(key)
        first.append(iso)
    rows = {}
    for iso in first:
        row = rows.setdefault(iso.organism_id, {"organism": iso.organism, "n": 0, "cells": {}})
        row["n"] += 1
        for r in iso.readings:
            s, n = row["cells"].get(r.antibiotic_id, (0, 0))
            row["cells"][r.antibiotic_id] = (s + (r.reading == "S"), n + 1)
    used = {a for row in rows.values() for a in row["cells"]}
    return {"rows": sorted(rows.values(), key=lambda r: (-r["n"], r["organism"].name)),
            "antibiotics": [a for a in antibiotics() if a.id in used],
            "few": M39_MIN, "isolates": len(first)}


__all__ = ["M39_MIN", "MicroError", "add_isolate", "add_names", "alerts", "antibiogram",
           "antibiotics", "culture_of", "is_culture", "organisms", "save_isolate",
           "set_outcome", "summary"]
