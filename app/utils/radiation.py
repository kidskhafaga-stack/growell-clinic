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
adds up and compares; it does not estimate a dose, set a reference level, or
convert one measure into another. The measures are kept apart and never
added across each other — a CT's dose-length product and a film's
dose-area product are different quantities.
"""
from datetime import datetime, timedelta

from app.extensions import db

#: The kind of machine a scan is done on.
MODALITIES = ("xray", "ct", "fluoro", "mri", "us", "nuclear", "other")
#: The ones that give the child ionising radiation.
IONISING = frozenset({"xray", "ct", "fluoro", "nuclear"})
#: The dose measures a machine reports, each in its own unit (the label says
#: which). Kept apart: they are not the same quantity and are never summed
#: together.
DOSE_KINDS = ("dlp", "ctdi", "dap", "msv", "fluoro_s")
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
    the test, in the same measure."""
    inv = getattr(order, "investigation", None)
    return bool(inv is not None and inv.dose_ref_value and order.dose_value is not None
                and order.dose_kind == inv.dose_ref_kind
                and order.dose_value > inv.dose_ref_value)


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
    kind = (form.get("dose_kind") or "").strip() or None
    if dose is not None and kind not in DOSE_KINDS:
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
    totals, recent_totals = {}, {}
    for r in rows:
        if r.dose_value is None or r.dose_kind not in DOSE_KINDS:
            continue
        totals[r.dose_kind] = round(totals.get(r.dose_kind, 0) + r.dose_value, 3)
        when = r.performed_at or r.created_at
        if when and when >= since:
            recent_totals[r.dose_kind] = round(recent_totals.get(r.dose_kind, 0)
                                               + r.dose_value, 3)
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

    start = datetime.combine(date_from, datetime.min.time())
    end = datetime.combine(date_to, datetime.max.time())
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
