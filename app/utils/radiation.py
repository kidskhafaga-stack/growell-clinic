"""What a scan gave the child: the dose, the contrast, and the running total.

Asked as *«الموضوع بتاع الصبغة ده مهم لان فى اشتراطات فى GAHAR تقريباً عليه كل
طفل اتعرض لاشعة او للصبغة اد ايه ويقلل النسب»*. A child scanned in three
departments over a year has a dose nobody added up, and a contrast reaction
written in one report that the next room never read. So:

* each scan keeps **what the machine reported** — the dose, in the measure
  the machine gives it — and **the contrast**: which agent, how, how much,
  and how the child took it;
* the child's file adds them up, and every scan's screen shows them
  **before** the next one — the moment the question «does this child need
  it» is still worth asking;
* a previous reaction to contrast is said in red on the next scan's screen;
* the hospital sets, per test, the dose it should not usually pass (its own
  reference level), and a scan above it is listed for review.

**Every number is the machine's or the hospital's.** The program records,
adds up and compares; it does not estimate a dose or set a reference level.
The measures are kept apart and never added across each other — a CT's
dose-length product and a film's dose-area product are different
quantities.

**And every machine's unit.** The program is sold to more than one place,
and machines print the same measure in different units — a DAP meter may
say Gy·cm², dGy·cm², cGy·cm², mGy·cm² or µGy·m². So a dose is kept in the
unit it was read in, and turned into one unit per measure only to add and
compare — by the fixed factors of the units themselves (1 µGy·m² is 10
mGy·cm²), never a clinical figure. Each hospital names the unit its own
machines print (`default_unit`), and that is what the form offers first and
the totals are shown in.
"""
from datetime import datetime, timedelta

from app.extensions import db

#: The kind of machine a scan is done on.
MODALITIES = ("xray", "ct", "fluoro", "mri", "us", "nuclear", "other")
#: The ones that give the child ionising radiation.
IONISING = frozenset({"xray", "ct", "fluoro", "nuclear"})
#: The dose measures a machine reports. Kept apart: they are not the same
#: quantity and are never summed together. For each, the units machines print
#: it in, with the exact factor that turns one into the measure's base unit
#: (the first). Physics, not medicine: 1 Gy = 1000 mGy, 1 m² = 10 000 cm²,
#: 1 mCi = 37 MBq.
MEASURES = {
    "dlp": {"mgycm": 1.0, "gycm": 1000.0},
    "ctdi": {"mgy": 1.0},
    "dap": {"mgycm2": 1.0, "gycm2": 1000.0, "dgycm2": 100.0, "cgycm2": 10.0,
            "ugym2": 10.0, "ugycm2": 0.001, "mgym2": 10000.0},
    "kar": {"mgy": 1.0, "gy": 1000.0, "ugy": 0.001},
    "esak": {"mgy": 1.0, "ugy": 0.001},
    "msv": {"msv": 1.0, "usv": 0.001},
    "fluoro_time": {"s": 1.0, "min": 60.0},
    "activity": {"mbq": 1.0, "gbq": 1000.0, "mci": 37.0},
}
DOSE_KINDS = tuple(MEASURES)
#: Every unit any measure is printed in (for the labels).
UNITS = tuple(dict.fromkeys(u for units in MEASURES.values() for u in units))


def base_unit(kind):
    return next(iter(MEASURES[kind])) if kind in MEASURES else None


def default_unit(kind):
    """The unit this hospital's machines print ``kind`` in — set once on the
    dose review screen; the measure's base unit until then."""
    from app.models import Setting

    if kind not in MEASURES:
        return None
    chosen = (Setting.get(f"dose_unit:{kind}") or "").strip()
    return chosen if chosen in MEASURES[kind] else base_unit(kind)


def to_base(value, kind, unit=None):
    """``value`` in ``unit`` as the measure's base unit. A row written
    before units were kept is in the base unit."""
    if value is None or kind not in MEASURES:
        return None
    factor = MEASURES[kind].get(unit or base_unit(kind))
    return None if factor is None else value * factor


def from_base(value, kind, unit):
    factor = MEASURES.get(kind, {}).get(unit)
    return None if value is None or not factor else value / factor


def measures():
    """``[(kind, unit)]`` for the form's one select — each measure in each
    unit, this hospital's unit first."""
    out = []
    for kind, units in MEASURES.items():
        first = default_unit(kind)
        out.append((kind, first))
        out += [(kind, u) for u in units if u != first]
    return out


def parse_measure(raw):
    """``"dap:ugym2"`` → ``("dap", "ugym2")``, or ``(None, None)``."""
    kind, _, unit = (raw or "").partition(":")
    if kind in MEASURES and unit in MEASURES[kind]:
        return kind, unit
    return None, None
CONTRAST_ROUTES = ("iv", "oral", "rectal", "other")
REACTIONS = ("none", "mild", "moderate", "severe")


class ExposureError(ValueError):
    """A refusal with a key the screen can name (``radiation.err_<key>``)."""


def ionising(order):
    inv = getattr(order, "investigation", None)
    return bool(inv is not None and inv.modality in IONISING)


def has_exposure(order):
    return bool(order.dose_value is not None or order.contrast_agent)


def over_reference(order):
    """Whether this scan's dose passed the hospital's reference level for
    the test, in the same measure — compared in its base unit, whatever unit
    each was written in."""
    inv = getattr(order, "investigation", None)
    if not (inv is not None and inv.dose_ref_value and order.dose_value is not None
            and order.dose_kind == inv.dose_ref_kind):
        return False
    mine = to_base(order.dose_value, order.dose_kind, order.dose_unit)
    ref = to_base(inv.dose_ref_value, inv.dose_ref_kind, inv.dose_ref_unit)
    return bool(mine is not None and ref is not None and mine > ref + 1e-9)


def _number(raw, low=0.0):
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ExposureError("bad_number") from None
    if value < low:
        raise ExposureError("bad_number")
    return round(value, 3)


def save(order, form, user=None):
    """Write what a scan gave the child from ``form``. A blank box clears
    its figure — a mistyped dose is corrected, not stacked."""
    if order is None or order.kind != "imaging":
        raise ExposureError("not_a_scan")
    dose = _number(form.get("dose_value"))
    kind, unit = parse_measure(form.get("dose_measure"))
    if dose is not None and kind is None:
        raise ExposureError("dose_needs_kind")
    agent = (form.get("contrast_agent") or "").strip()[:80] or None
    route = (form.get("contrast_route") or "").strip() or None
    ml = _number(form.get("contrast_ml"))
    reaction = (form.get("contrast_reaction") or "").strip() or None
    if agent is None and (ml is not None or reaction not in (None, "none")):
        raise ExposureError("contrast_needs_agent")
    if route is not None and route not in CONTRAST_ROUTES:
        raise ExposureError("bad_route")
    if reaction is not None and reaction not in REACTIONS:
        raise ExposureError("bad_reaction")
    order.dose_value = dose
    order.dose_kind = kind if dose is not None else None
    order.dose_unit = unit if dose is not None else None
    order.contrast_agent = agent
    order.contrast_route = route if agent else None
    order.contrast_ml = ml if agent else None
    order.contrast_reaction = reaction if agent else None
    order.contrast_note = ((form.get("contrast_note") or "").strip()[:200] or None) if agent else None
    order.exposure_by = getattr(user, "id", None)
    db.session.flush()
    return order


def history(patient_id, exclude_id=None):
    """The child's scans that gave a dose or contrast, or were done on an
    ionising machine — newest first."""
    from app.models import Investigation, VisitInvestigation

    query = (VisitInvestigation.query
             .outerjoin(Investigation, VisitInvestigation.investigation_id == Investigation.id)
             .filter(VisitInvestigation.patient_id == patient_id,
                     VisitInvestigation.kind == "imaging",
                     db.or_(VisitInvestigation.dose_value.isnot(None),
                            VisitInvestigation.contrast_agent.isnot(None),
                            db.and_(Investigation.modality.in_(tuple(IONISING)),
                                    VisitInvestigation.status != "requested"))))
    if exclude_id:
        query = query.filter(VisitInvestigation.id != exclude_id)
    return query.order_by(VisitInvestigation.created_at.desc()).all()


def summary(patient_id, exclude_id=None, months=12):
    """``{rows, ionising, recent, totals, recent_totals, contrast,
    reactions}`` for the child's file and the next scan's screen."""
    rows = history(patient_id, exclude_id)
    since = datetime.utcnow() - timedelta(days=round(months * 30.4))
    base, recent_base = {}, {}
    for r in rows:
        value = to_base(r.dose_value, r.dose_kind, r.dose_unit)
        if value is None:
            continue
        base[r.dose_kind] = base.get(r.dose_kind, 0) + value
        when = r.performed_at or r.created_at
        if when and when >= since:
            recent_base[r.dose_kind] = recent_base.get(r.dose_kind, 0) + value

    def shown(sums):
        """Each measure's total in the hospital's own unit for it."""
        out = {}
        for kind, value in sums.items():
            unit = default_unit(kind)
            out[kind] = (round(from_base(value, kind, unit), 3), unit)
        return out

    totals, recent_totals = shown(base), shown(recent_base)
    ion = [r for r in rows if ionising(r)]
    return {
        "rows": rows,
        "ionising": len(ion),
        "recent": sum(1 for r in ion if (r.performed_at or r.created_at) >= since),
        "totals": totals, "recent_totals": recent_totals, "months": months,
        "contrast": sum(1 for r in rows if r.contrast_agent),
        "reactions": [r for r in rows if r.contrast_reaction in ("mild", "moderate", "severe")],
    }


def report(date_from, date_to):
    """Scans with a dose recorded in the window, those above the hospital's
    reference first — the list a radiation-safety review starts from."""
    from app.models import VisitInvestigation

    # The clinic's days, turned into the UTC moments the rows are stored
    # in — a scan at two in the morning belongs to that night, not the day
    # before (`utils/clock`).
    from datetime import time

    from app.utils.clock import to_utc

    start = to_utc(datetime.combine(date_from, time.min))
    end = to_utc(datetime.combine(date_to, time.max))
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.kind == "imaging",
                    db.or_(VisitInvestigation.dose_value.isnot(None),
                           VisitInvestigation.contrast_agent.isnot(None)),
                    db.func.coalesce(VisitInvestigation.performed_at,
                                     VisitInvestigation.created_at) >= start,
                    db.func.coalesce(VisitInvestigation.performed_at,
                                     VisitInvestigation.created_at) <= end)
            .all())
    rows.sort(key=lambda r: (not over_reference(r), r.contrast_reaction not in
                             ("mild", "moderate", "severe"),
                             -(r.performed_at or r.created_at).timestamp()))
    return rows
