"""Where a tube was drawn, how it reached the lab, and its whole journey.

LAB_GLAB360_PLAN.md م-٣ — *«أماكن السحب: في المعمل، أو الحضانة، أو العناية
المركزة، أو في الطوارئ غرفة الإجراءات، أو في الداخلي»* — the owner's list,
and then the operating theatre and recovery, both with the theatres module:
a haemoglobin during the operation, electrolytes in recovery. (A test run on
a device inside the theatre is a bedside test — `lab_poct` — and travels
nowhere; tissue taken at the operation is `Specimen`, the theatre's own.)

* **The places are fixed**, each tied to its department's module: a clinic
  that runs the program at clinic level only has the lab and nothing else,
  so it never sees a place, a batch or a «send» button — its lab works
  exactly as before (`spread`).
* **Where a tube was drawn** is asked when it is drawn, with the answer
  already filled in from where the child is: the bed's unit for a child in a
  bed, the procedure room for a child in emergency, the lab otherwise.
* **Sending**: the tubes drawn outside the lab wait on a list per place; the
  nurse ticks those going now and presses «send» — one batch, numbered, with
  a list to print and carry. The lab receives each tube as it always did (by
  scanning at the door), and that marks it arrived on its batch. What was
  sent and never arrived is shown, and late after :data:`LATE_MINUTES`.
* **The journey**: every step a tube took — ordered, drawn and where, sent,
  received or refused, kept, sent out, answered, released — with the time and
  the person, and how long each step took. That is what tells where a late
  result lost its time (`place_report`).
"""
from datetime import datetime, time

from app.extensions import db

LAB = "lab"

#: ``(place, module)`` — the owner's list, in the owner's order. The lab is
#: always there; each other place only while its department's module is on.
PLACES = (
    (LAB, None),
    ("nicu", "nicu"),
    ("icu", "icu"),
    ("emergency", "emergency"),
    ("ward", "ward"),
    ("theatres", "theatres"),
    ("recovery", "theatres"),
)

#: A unit's kind (`models.place.UNIT_KINDS`) → the place its tubes are drawn.
_UNIT_PLACE = {"nicu": "nicu", "icu": "icu", "ward": "ward",
               "emergency": "emergency", "recovery": "recovery"}
#: Where an operation under way says the child is (`Operation.where`).
_CASE_PLACE = {"theatre": "theatres", "recovery": "recovery"}
#: A case started longer ago than this and never closed is not where the
#: child is now — a theatre list nobody finished must not draw every tube
#: in the building into the operating room.
_CASE_HOURS = 24

#: A tube on the way longer than this is shown as late. Most hospitals carry
#: a batch in minutes; half an hour is a tube somebody should look for.
LATE_MINUTES = 30


class TransferError(ValueError):
    """A refusal with a key the screen can name (``lab_transfer.err_<key>``)."""


# --------------------------------------------------------------- places --
def available():
    """The places this hospital draws in, in order."""
    from app.utils.facility import module_enabled

    return [key for key, module in PLACES
            if module is None or module_enabled(module)]


def spread():
    """Whether tubes are drawn anywhere but the lab here. ``False`` in a
    clinic — and then nothing on this page shows."""
    return len(available()) > 1


def name(place):
    from app.i18n import t

    return t(f"lab_transfer.place_{place or LAB}")


def _unit_kind(admission_id):
    from app.models.admission import Admission

    admission = db.session.get(Admission, admission_id)
    if admission is None or not admission.is_open:
        return None
    bed = admission.bed
    unit = bed.space.unit if bed is not None and bed.space is not None else None
    return unit.kind if unit is not None else None


def _in_theatre(patient_id):
    """``theatres`` / ``recovery`` while this child's operation is under way."""
    from datetime import timedelta

    from app.models import Operation
    from app.utils.facility import module_enabled

    if not module_enabled("theatres"):
        return None
    case = (Operation.query
            .filter(Operation.patient_id == patient_id,
                    Operation.started_at.isnot(None),
                    Operation.started_at >= datetime.utcnow() - timedelta(hours=_CASE_HOURS),
                    Operation.discharged_at.is_(None))
            .order_by(Operation.started_at.desc()).first())
    return _CASE_PLACE.get(case.where) if case is not None else None


def default_for(order):
    """Where this tube is most likely drawn: the operating theatre or
    recovery while the child's operation is under way, the bed's unit, the
    emergency procedure room, or the lab."""
    here = available()
    guess = _in_theatre(order.patient_id)
    if guess is None and order.admission_id:
        guess = _UNIT_PLACE.get(_unit_kind(order.admission_id))
    if guess is None and order.visit is not None and order.visit.channel == "emergency":
        guess = "emergency"
    return guess if guess in here else LAB


def clean(value, order):
    """What the form said, if it is a place here; otherwise the guess."""
    value = (value or "").strip()
    return value if value in available() else default_for(order)


# -------------------------------------------------------------- sending --
def _on_a_batch():
    """The orders whose present tube is already on a batch."""
    from app.models import SampleBatchItem, VisitInvestigation

    return (db.session.query(SampleBatchItem.id)
            .filter(SampleBatchItem.order_id == VisitInvestigation.id,
                    SampleBatchItem.sample_code == VisitInvestigation.sample_code)
            .exists())


def waiting_to_send(place=None):
    """Tubes drawn outside the lab, not yet received, and not on a batch —
    oldest first."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation

    query = (VisitInvestigation.query
             .options(selectinload(VisitInvestigation.patient))
             .filter(VisitInvestigation.kind == "lab",
                     VisitInvestigation.collected_at.isnot(None),
                     VisitInvestigation.received_at.is_(None),
                     VisitInvestigation.status != "resulted",
                     VisitInvestigation.collected_where.isnot(None),
                     VisitInvestigation.collected_where != LAB,
                     ~_on_a_batch()))
    if place:
        query = query.filter(VisitInvestigation.collected_where == place)
    return query.order_by(VisitInvestigation.collected_at,
                          VisitInvestigation.id).all()


def waiting_by_place():
    """``[(place, [orders])]`` for every place with tubes waiting to leave."""
    out = {}
    for row in waiting_to_send():
        out.setdefault(row.collected_where, []).append(row)
    return [(p, out[p]) for p in available() if p in out]


def send(place, order_ids, user=None, note=None, at=None):
    """The ticked tubes leave ``place`` together. Returns the batch. The
    caller commits."""
    from app.models import ActivityLog, SampleBatch, SampleBatchItem

    if place not in available() or place == LAB:
        raise TransferError("bad_place")
    wanted = {int(i) for i in order_ids if str(i).isdigit()}
    rows = [r for r in waiting_to_send(place) if r.id in wanted]
    if not rows:
        raise TransferError("nothing")
    now = at or datetime.utcnow()
    batch = SampleBatch(from_place=place, sent_at=now,
                        sent_by=getattr(user, "id", None),
                        note=(note or "").strip()[:200] or None)
    db.session.add(batch)
    db.session.flush()
    batch.code = f"T{now:%y%m%d}-{batch.id}"
    for row in rows:
        db.session.add(SampleBatchItem(batch_id=batch.id, order_id=row.id,
                                       sample_code=row.sample_code))
    ActivityLog.record("lab.batch_sent", user_id=getattr(user, "id", None),
                       entity="sample_batch", entity_id=batch.id,
                       detail=f"{batch.code} {place} n={len(rows)}")
    db.session.flush()
    return batch


def arrived(order, outcome, user=None, at=None):
    """The lab's door saw this tube: mark it arrived on its batch, if it was
    sent on one. Called by `lab_reception` on receiving and on refusing."""
    from app.models import SampleBatchItem

    if order is None or not order.sample_code:
        return None
    item = (SampleBatchItem.query
            .filter_by(order_id=order.id, sample_code=order.sample_code)
            .filter(SampleBatchItem.arrived_at.is_(None)).first())
    if item is None:
        return None
    item.arrived_at = at or datetime.utcnow()
    item.arrived_by = getattr(user, "id", None)
    item.outcome = outcome
    return item


def on_the_way():
    """Every tube sent and not yet arrived, oldest batch first."""
    from sqlalchemy.orm import selectinload

    from app.models import SampleBatch, SampleBatchItem

    return (SampleBatchItem.query.join(SampleBatch)
            .options(selectinload(SampleBatchItem.batch),
                     selectinload(SampleBatchItem.order))
            .filter(SampleBatchItem.arrived_at.is_(None))
            .order_by(SampleBatch.sent_at, SampleBatchItem.id).all())


def on_the_way_count():
    from app.models import SampleBatchItem

    if not spread():
        return 0
    return SampleBatchItem.query.filter(SampleBatchItem.arrived_at.is_(None)).count()


def open_batches():
    """``[(batch, [items still on the way])]`` — batches with a tube that has
    not arrived."""
    out = {}
    for item in on_the_way():
        out.setdefault(item.batch, []).append(item)
    return list(out.items())


def recent_batches(limit=20):
    from app.models import SampleBatch

    return SampleBatch.query.order_by(SampleBatch.sent_at.desc()).limit(limit).all()


def is_late(batch, now=None):
    now = now or datetime.utcnow()
    return (now - batch.sent_at).total_seconds() > LATE_MINUTES * 60


def by_code(code):
    from app.models import SampleBatch

    code = (code or "").strip()
    return SampleBatch.query.filter_by(code=code).first() if code else None


# -------------------------------------------------------------- journey --
def _who(user, lang):
    return user.display_name(lang) if user is not None else None


def journey(order, lang="ar"):
    """Every step this order's tubes took, in time order: ``[{key, at, who,
    detail, minutes}]`` — ``minutes`` is how long since the step before."""
    from app.models import SampleBatchItem
    from app.utils import lab_storage

    steps = [{"key": "ordered", "at": order.created_at,
              "who": _who(order.orderer, lang), "detail": None}]
    for refused in order.rejections:
        if refused.collected_at:
            steps.append({"key": "drawn", "at": refused.collected_at,
                          "who": _who(refused.collector, lang),
                          "detail": refused.sample_code})
        steps.append({"key": "refused", "at": refused.rejected_at,
                      "who": _who(refused.rejecter, lang),
                      "detail": refused.sample_code})
    if order.collected_at:
        where = name(order.collected_where) if spread() else None
        steps.append({"key": "drawn", "at": order.collected_at,
                      "who": _who(order.collector, lang),
                      "detail": " · ".join(x for x in (order.sample_code, where) if x)})
    for item in (SampleBatchItem.query.filter_by(order_id=order.id)
                 .order_by(SampleBatchItem.id).all()):
        batch = item.batch
        steps.append({"key": "sent", "at": batch.sent_at,
                      "who": _who(batch.sender, lang),
                      "detail": f"{batch.code} · {name(batch.from_place)}",
                      "batch": batch.code})
        if item.arrived_at is None:
            steps.append({"key": "on_the_way", "at": None, "who": None,
                          "detail": item.sample_code})
    if order.received_at:
        steps.append({"key": "received", "at": order.received_at,
                      "who": _who(order.receiver, lang), "detail": order.received_note})
    kept = lab_storage.current(order.sample_code) if order.sample_code else None
    if kept is not None:
        steps.append({"key": "kept", "at": kept.stored_at,
                      "who": _who(kept.storer, lang),
                      "detail": lab_storage.place_label(kept)})
    if order.sent_at:
        steps.append({"key": "sent_out", "at": order.sent_at,
                      "who": _who(order.sender, lang),
                      "detail": order.sent_lab.name if order.sent_lab else None})
    if order.resulted_at:
        steps.append({"key": "answered", "at": order.resulted_at,
                      "who": _who(order.resulter, lang), "detail": None})
    if order.verified_at:
        steps.append({"key": "released", "at": order.verified_at,
                      "who": _who(order.verifier, lang), "detail": None})
    timed = sorted((s for s in steps if s["at"] is not None), key=lambda s: s["at"])
    waiting = [s for s in steps if s["at"] is None]
    before = None
    for step in timed:
        step["minutes"] = (int((step["at"] - before).total_seconds() // 60)
                           if before is not None else None)
        before = step["at"]
    for step in waiting:
        step["minutes"] = (int((datetime.utcnow() - before).total_seconds() // 60)
                           if before is not None else None)
    return timed + waiting


# ------------------------------------------------- where the time went --
def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[len(values) // 2]


def place_report(start, end):
    """For results answered between two clinic days, per place drawn:
    ``[{place, count, to_lab, at_lab}]`` — the median minutes from drawing to
    the lab's door, and from the door to the answer."""
    from app.models import VisitInvestigation
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.collected_at.isnot(None),
                    VisitInvestigation.resulted_at >= since,
                    VisitInvestigation.resulted_at <= until).all())
    groups = {}
    for row in rows:
        entry = groups.setdefault(row.collected_where or LAB,
                                  {"to_lab": [], "at_lab": [], "count": 0})
        entry["count"] += 1
        if row.received_at:
            entry["to_lab"].append((row.received_at - row.collected_at).total_seconds() // 60)
            entry["at_lab"].append((row.resulted_at - row.received_at).total_seconds() // 60)
    out = []
    for place in [p for p, _m in PLACES]:
        if place in groups:
            g = groups[place]
            out.append({"place": place, "count": g["count"],
                        "to_lab": _median(g["to_lab"]), "at_lab": _median(g["at_lab"])})
    return out
