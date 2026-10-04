"""Tests and scans ordered from the stay itself.

Asked as *«ليه مش بتطلب من ملف الإقامة؟»* — and there was no reason. An order
could only be written at a visit, because the visit screen was the one door
there ever was; the stay learnt to *read* the orders and nobody gave it a
button to write one. Two things followed, and both were money:

* a child admitted straight to a bed, or a newborn from delivery, has no
  visit — so ordering a CBC meant opening a consultation that never happened,
  with its fee;
* a test written on any visit but the one the stay began from went to the
  outpatient desk, as if the child had walked in for it.

**The stay's own encounter.** An order belongs to a visit in this program —
the lab, the results inbox, the curve and the file all read it there — and a
stay with none gets exactly one, marked ``channel="ward"``: the encounter that
*is* the stay. Not a consultation: it has no appointment, so the desk raises
no fee on it, and it is closed from the start, so it never sits in anybody's
queue of open visits. The stay points at it, so a diagnosis written there is
the stay's diagnosis on the bed map too.

**And the order carries the stay.** ``admission_id`` is what sends it to the
stay's bill (``labs.of_stay``) and keeps it off the desk.

**Nothing here reaches a clinic without beds.** Every door into it is on the
stay's own screen, behind the beds module; a clinic, a clinic with an
emergency room, or a centre with no stays never writes a ward encounter and
never sees a line of this. Orders written at a visit bill exactly as they
always have.
"""
from datetime import datetime

from app.extensions import db
from app.models import Investigation, Visit, VisitInvestigation
from app.models.prescription import INVESTIGATION_KINDS
from app.models.visit import SIDES
from app.utils.clock import local_today

#: What the stay's own encounter is called in ``Visit.channel``. Beside
#: «clinic» and «whatsapp»: where the encounter happened.
WARD = "ward"


class StayClosed(ValueError):
    """An order on a stay that has ended — the child is not in a bed any more,
    and a test «for the stay» would be billed to a bill already closed."""


def encounter(admission, user):
    """The visit this stay's orders are written on, made the first time one is
    needed.

    The visit the stay began from when it has one — the emergency room's, or
    the clinic's that sent the child up — so everything about one illness is
    in one place. Only a stay with none gets its own.
    """
    if admission.visit is not None:
        return admission.visit
    now = datetime.utcnow()
    visit = Visit(patient_id=admission.patient_id, doctor_id=user.id,
                  visit_date=local_today(), status="completed",
                  completed_at=now, channel=WARD)
    db.session.add(visit)
    db.session.flush()
    admission.visit = visit
    return visit


def order(admission, user, investigation=None, name=None, name_en=None,
          kind=None, notes=None, laterality=None, outside=None,
          outside_place=None, urgent=None):
    """Write one test or scan for a child in a bed. Returns the order.

    Refused for a stay that has ended and for an order with no name. Where it
    is done follows the catalogue (``labs.goes_outside``) unless somebody says
    otherwise on the form, the same rule as the visit screen.
    """
    from app.utils import labs

    if admission is None or not admission.is_open:
        raise StayClosed("stay closed")
    if investigation is not None:
        name = investigation.name_ar
        name_en = investigation.name_en
        kind = investigation.kind
    name = (name or "").strip()[:200]
    if not name:
        raise ValueError("no name")
    kind = kind if kind in INVESTIGATION_KINDS else "lab"
    side = (laterality or "").strip()
    goes_out = labs.goes_outside(investigation, asked=outside)
    visit = encounter(admission, user)
    row = VisitInvestigation(
        visit_id=visit.id, patient_id=admission.patient_id,
        admission_id=admission.id,
        investigation_id=investigation.id if investigation else None,
        kind=kind, name=name, name_en=(name_en or "").strip()[:200] or None,
        request_notes=(notes or "").strip()[:255] or None,
        done_outside=goes_out,
        outside_place=((outside_place or "").strip()[:160] or None)
        if goes_out else None,
        ordered_by=user.id,
        laterality=side if (kind == "imaging" and side in SIDES) else None,
        urgent=True if urgent else None)
    db.session.add(row)
    db.session.flush()
    return row


def for_stay(admission):
    """Every test and scan this stay owns, newest first — the same ownership
    the bill uses (``labs.of_stay``), so the list and the bill never disagree
    about what the stay had done."""
    from sqlalchemy.orm import selectinload

    from app.utils import labs

    return (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.investigation))
            .filter(labs.of_stay(admission))
            .order_by(VisitInvestigation.created_at.desc(),
                      VisitInvestigation.id.desc()).all())


def search(query, kind=None, limit=15):
    """The catalogue, for the order box on the stay. Active tests only — a test
    the clinic stopped offering is not orderable, though it stays on every
    file it was ever written on."""
    from sqlalchemy import or_

    text = (query or "").strip()
    if len(text) < 2:
        return []
    like = f"%{text}%"
    rows = Investigation.query.filter(Investigation.is_active.is_(True),
                                      or_(Investigation.name_ar.ilike(like),
                                          Investigation.name_en.ilike(like)))
    if kind in INVESTIGATION_KINDS:
        rows = rows.filter(Investigation.kind == kind)
    return rows.order_by(Investigation.name_ar).limit(limit).all()
