"""Samples sent to a referral laboratory — GAHAR DAS.13 and DAS.15 (د).

*"Records of send-out tests support the compliance"* (DAS.13 دليل ٥) and
*"process of recording all specimens referred to other laboratories"*
(DAS.15 د). A hospital laboratory draws a sample it does not run, labels it,
puts it in a box with a list, and a courier takes it; days later a result
comes back on paper. Each of those steps is recorded here:

* **the referral laboratories** — the hospital's own list, with the
  accreditation as stated, the turnaround its agreement promises, the date
  the agreement runs to, and the last evaluation;
* **the batch** — the samples sent together, numbered, with a manifest to
  print and hand over;
* **late** — a sample is late only against the turnaround its laboratory
  promised, never against a figure of ours;
* **back** — when its result is written (`labs.settle`);
* **the register** — what went where in a period, what came back, what is
  late, and the turnaround each laboratory actually kept, which is the
  evaluation DAS.13 (ب) asks for, measured rather than remembered.
"""
from datetime import date, datetime, time, timedelta

from app.extensions import db


class SendError(ValueError):
    """A refusal with a key the screen can name (``lab_sendout.err_<key>``)."""


# --------------------------------------------------------- the laboratories --
def laboratories(active_only=True):
    from app.models import ReferralLab

    query = ReferralLab.query
    if active_only:
        query = query.filter(ReferralLab.is_active.is_(True))
    return query.order_by(ReferralLab.name).all()


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _int(raw):
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def save_laboratory(form, row=None):
    """Add or update a referral laboratory from a form. The caller commits."""
    from app.models import ReferralLab

    name = (form.get("name") or "").strip()[:160]
    if not name:
        raise SendError("need_name")
    if row is None:
        row = ReferralLab(name=name)
        db.session.add(row)
    row.name = name
    row.accreditation = (form.get("accreditation") or "").strip()[:160] or None
    row.contact = (form.get("contact") or "").strip()[:160] or None
    row.tat_days = _int(form.get("tat_days"))
    row.agreement_until = _day(form.get("agreement_until"))
    row.evaluated_on = _day(form.get("evaluated_on"))
    row.evaluation_note = (form.get("evaluation_note") or "").strip()[:255] or None
    # A hidden «0» beside the box, so an unticked box says no; a new
    # laboratory's form has neither and is in use.
    marks = form.getlist("is_active") if hasattr(form, "getlist") else (
        [form["is_active"]] if "is_active" in form else [])
    row.is_active = ("1" in marks) if marks else True
    db.session.flush()
    return row


def agreement_state(lab, today=None):
    """``"lapsed"``, ``"ending"`` (within 30 days), ``"ok"`` or ``None`` when
    no date was written."""
    if lab is None or lab.agreement_until is None:
        return None
    from app.utils.clock import local_today

    today = today or local_today()
    if lab.agreement_until < today:
        return "lapsed"
    if lab.agreement_until <= today + timedelta(days=30):
        return "ending"
    return "ok"


# ---------------------------------------------------------------- sending --
def to_send():
    """Drawn here, not yet sent, not yet answered — the samples a batch is
    made from. Those whose test names a referral laboratory first."""
    from sqlalchemy.orm import selectinload

    from app.models import Investigation, VisitInvestigation

    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.investigation))
            .outerjoin(Investigation, VisitInvestigation.investigation_id == Investigation.id)
            .filter(VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "collected",
                    VisitInvestigation.sent_at.is_(None),
                    VisitInvestigation.done_outside.is_not(True))
            .order_by(Investigation.referral_lab_id.is_(None),
                      VisitInvestigation.collected_at, VisitInvestigation.id)
            .all())
    return rows


def _batch_code():
    from app.models import VisitInvestigation
    from app.utils.clock import local_today

    stem = f"SO-{local_today():%y%m%d}-"
    taken = (db.session.query(db.func.count(db.distinct(VisitInvestigation.sent_batch)))
             .filter(VisitInvestigation.sent_batch.like(stem + "%")).scalar() or 0)
    return f"{stem}{taken + 1}"


def send(orders, lab, user=None, at=None):
    """Send these samples to ``lab`` on one batch. Returns the batch code."""
    if lab is None or not lab.is_active:
        raise SendError("no_lab")
    chosen = [o for o in orders if o is not None]
    if not chosen:
        raise SendError("nothing_chosen")
    for order in chosen:
        if order.kind != "lab":
            raise SendError("not_lab")
        if order.status != "collected" or order.collected_at is None:
            raise SendError("not_collected")
        if order.sent_at is not None:
            raise SendError("already_sent")
    code = _batch_code()
    now = at or datetime.utcnow()
    for order in chosen:
        order.sent_lab_id = lab.id
        order.sent_at = now
        order.sent_by = getattr(user, "id", None)
        order.sent_batch = code
        order.returned_at = None
    db.session.flush()
    return code


def recall(order):
    """A sample marked sent by mistake, taken back before its result came."""
    if order is None or order.sent_at is None:
        raise SendError("not_sent")
    if order.status == "resulted":
        raise SendError("already_back")
    order.sent_lab_id = order.sent_at = order.sent_by = None
    order.sent_batch = order.returned_at = None
    db.session.flush()
    return order


def batch(code):
    from app.models import VisitInvestigation

    return (VisitInvestigation.query
            .filter(VisitInvestigation.sent_batch == (code or "").strip())
            .order_by(VisitInvestigation.id).all())


# ------------------------------------------------------------------ late --
def late(order, now=None):
    """Past the turnaround its laboratory promised — ``None`` when it was
    not sent, is back, or the laboratory promised nothing."""
    if order is None or order.sent_at is None or order.status == "resulted":
        return None
    lab = order.sent_lab
    if lab is None or not lab.tat_days:
        return None
    return (now or datetime.utcnow()) - order.sent_at > timedelta(days=lab.tat_days)


def out_now():
    """Sent and not back yet, oldest first."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation

    return (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.sent_lab))
            .filter(VisitInvestigation.sent_at.isnot(None),
                    VisitInvestigation.status != "resulted")
            .order_by(VisitInvestigation.sent_at, VisitInvestigation.id).all())


# -------------------------------------------------------------- register --
def register(start, end):
    """Every sample sent between two clinic days, and per laboratory: how
    many went, came back, are late, and the turnaround kept on those back."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.sent_lab))
            .filter(VisitInvestigation.sent_at >= since,
                    VisitInvestigation.sent_at <= until)
            .order_by(VisitInvestigation.sent_at.desc()).all())
    per = {}
    now = datetime.utcnow()
    for row in rows:
        lab = row.sent_lab
        key = lab.id if lab else 0
        entry = per.setdefault(key, {"lab": lab, "sent": 0, "back": 0,
                                     "late": 0, "days": []})
        entry["sent"] += 1
        if row.returned_at is not None:
            entry["back"] += 1
            entry["days"].append((row.returned_at - row.sent_at).total_seconds() / 86400)
        elif late(row, now):
            entry["late"] += 1
    labs = []
    for entry in per.values():
        days = entry.pop("days")
        entry["kept_days"] = round(sum(days) / len(days), 1) if days else None
        labs.append(entry)
    labs.sort(key=lambda e: (e["lab"].name if e["lab"] else ""))
    return rows, labs
