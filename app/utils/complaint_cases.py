"""Complaint cases: taken by anybody, owned by customer service, answered on time.

GAHAR ``PCC.16`` in five lines, and where each one lives here:

(a) *how a family knows where to complain* — the printed form and its words
    (``complaints/blank.html``), the online link, the desk;
(b) *tracking* — a numbered case (:func:`open_case`) and its timeline
    (:func:`log`), every step with who did it;
(c) *who answers* — the case's owner, from the people holding
    ``complaints_manage``;
(d) *within what time* — :func:`first_contact_hours` and :func:`close_days`,
    the clinic's own policy, with the case marked late when it passes them;
(e) *monitored* — the counts and times in :func:`summary`, and the family's
    own verdict on the answer (:func:`rate`).

**The clinic sets the timeframes.** The defaults (a day to contact the
family, a week to answer) are a starting point on the screen, not a rule
this program makes: PCC.16 asks for *the hospital's approved* timeframe.
"""
from datetime import datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models import Setting
from app.models.complaint import (CHANNELS, KINDS, OPEN_STATUSES, SEVERITIES,
                                  SIDES, Complaint, ComplaintEvent)

DEFAULT_CONTACT_HOURS = 24
DEFAULT_CLOSE_DAYS = 7
#: How long an "ask your complaint online" link stays good.
INVITE_DAYS = 14
CAPABILITY = "complaints_manage"


def _int_setting(key, default, lo, hi):
    try:
        value = int(Setting.get(key, default) or default)
    except (TypeError, ValueError):
        return default
    return value if lo <= value <= hi else default


def first_contact_hours():
    return _int_setting("complaint_contact_hours", DEFAULT_CONTACT_HOURS, 1, 720)


def close_days():
    return _int_setting("complaint_close_days", DEFAULT_CLOSE_DAYS, 1, 90)


# ------------------------------------------------------------ numbering ---
def next_number(now=None):
    """``C-<year>-<n>``, counted per year — what the family quotes back."""
    year = (now or datetime.utcnow()).year
    prefix = f"C-{year}-"
    top = 0
    for (num,) in (Complaint.query.filter(Complaint.number.like(prefix + "%"))
                   .with_entities(Complaint.number).all()):
        tail = num[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:04d}"


# ------------------------------------------------------------- the file ---
def log(case, kind, text=None, user=None, at=None):
    """Write one line on the case's timeline. The caller commits."""
    row = ComplaintEvent(complaint_id=case.id, kind=kind,
                         text=(text or "").strip()[:4000] or None,
                         user_id=getattr(user, "id", None),
                         at=at or datetime.utcnow())
    db.session.add(row)
    return row


def _pick(value, allowed, default):
    return value if value in allowed else default


def open_case(description, kind="complaint", channel="desk", patient=None,
              contact_name=None, contact_phone=None, anonymous=False,
              side=None, severity="normal", cost_centre_id=None, wanted=None,
              user=None, feedback=None, thread_key=None, notify=True,
              lang="ar"):
    """Write a case down and give it a number. Returns the ``Complaint``.

    Anonymous means anonymous: a name or number typed in anyway is not
    kept, and nothing is sent. The acknowledgement goes to a family that
    left a number, for a complaint or a suggestion — a thank-you is passed
    on, not answered with a case number.
    """
    description = (description or "").strip()
    if not description:
        raise ValueError("empty")
    anonymous = bool(anonymous)
    case = Complaint(
        number=next_number(),
        kind=_pick(kind, KINDS, "complaint"),
        channel=_pick(channel, CHANNELS, "desk"),
        severity=_pick(severity, SEVERITIES, "normal"),
        side=_pick(side, SIDES, None),
        status="new",
        patient_id=None if anonymous else getattr(patient, "id", None),
        anonymous=anonymous,
        contact_name=None if anonymous else ((contact_name or "").strip()[:120] or None),
        contact_phone=None if anonymous else ((contact_phone or "").strip()[:30] or None),
        cost_centre_id=cost_centre_id,
        description=description[:4000],
        wanted=(wanted or "").strip()[:2000] or None,
        created_by=getattr(user, "id", None),
        token=Complaint.new_token(),
        feedback_id=getattr(feedback, "id", None),
        thread_key=thread_key,
    )
    db.session.add(case)
    db.session.flush()
    log(case, "opened", None, user)
    if notify and case.kind != "compliment":
        _tell(case, "complaint_received", user=user, lang=lang)
    return case


def phone_of(case):
    if case.anonymous:
        return None
    if case.contact_phone:
        return case.contact_phone
    return case.patient.contact_phone if case.patient is not None else None


def link(case):
    """The public page where the family says whether the answer settled it."""
    from app.utils import whatsapp as wa

    base = wa.get_config().get("public_base")
    if base:
        return f"{base}/f/c/{case.token}"
    from flask import url_for
    try:
        return url_for("feedback.case_verdict", token=case.token, _external=True)
    except Exception:  # noqa: BLE001 — no request context
        return f"/f/c/{case.token}"


def _tell(case, template_type, user=None, lang="ar", answer=None):
    """Send the family one of the two case messages, and write that it went
    (or why it did not) on the timeline. Returns the ``MessageLog`` or None."""
    from app.utils import whatsapp as wa

    phone = phone_of(case)
    if not phone:
        log(case, "message", "no_phone", user)
        return None
    if wa.type_is_off(template_type):
        log(case, "message", "type_off", user)
        return None
    name = case.who(lang) or ""
    body = wa.render(wa.template_body(template_type), {
        "patient": name,
        "first_name": name.split()[0] if name else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "number": case.number,
        "hours": str(first_contact_hours()),
        "answer": answer or case.answer or "",
        "link": link(case),
    }).strip()
    row = wa.send(body, phone, patient_id=case.patient_id,
                  user_id=getattr(user, "id", None), template_type=template_type,
                  image_url=wa.template_image(template_type), ignore_window=True)
    log(case, "message", template_type, user)
    return row


# -------------------------------------------------------- the handling ---
def assign(case, owner, user=None):
    case.owner_id = getattr(owner, "id", None)
    log(case, "assigned", owner.full_name if owner is not None else None, user)


def contacted(case, text, user=None):
    """Somebody spoke to the family. The first time is the clock (d) reads."""
    now = datetime.utcnow()
    if case.first_contact_at is None:
        case.first_contact_at = now
    if case.status == "new":
        case.status = "in_progress"
    if case.owner_id is None and user is not None:
        case.owner_id = user.id
    log(case, "contacted", text, user, at=now)


def note(case, text, user=None):
    if (text or "").strip():
        log(case, "note", text, user)


def answer(case, finding, action, reply, user=None, notify=True, lang="ar"):
    """Record what was found, what was done and what the family is told —
    and tell them, with the link that asks whether it settled it."""
    reply = (reply or "").strip()
    if not reply:
        raise ValueError("empty")
    now = datetime.utcnow()
    case.finding = (finding or "").strip()[:4000] or None
    case.action = (action or "").strip()[:4000] or None
    case.answer = reply[:4000]
    case.answered_at = now
    if case.first_contact_at is None:
        case.first_contact_at = now
    case.status = "answered"
    if case.owner_id is None and user is not None:
        case.owner_id = user.id
    log(case, "answered", reply, user, at=now)
    if notify:
        _tell(case, "complaint_answered", user=user, lang=lang, answer=reply)


def close(case, text=None, user=None):
    case.status = "closed"
    case.closed_at = datetime.utcnow()
    log(case, "closed", text, user)


def reopen(case, text=None, user=None):
    case.status = "in_progress"
    case.closed_at = None
    case.reopened_count = (case.reopened_count or 0) + 1
    log(case, "reopened", text, user)


#: At or below this, the family is telling us the answer did not settle it.
UNSETTLED_AT = 2


def rate(case, stars, comment=None):
    """The family's verdict on the answer. Once. A low one reopens the case
    — an answer that did not settle anything is not a closed complaint —
    and anything else closes it."""
    if case.rated_at is not None or case.status not in ("answered", "closed"):
        return False
    case.resolution_rating = stars
    case.resolution_comment = (comment or "").strip()[:2000] or None
    case.rated_at = datetime.utcnow()
    log(case, "rated", f"{stars}/5" + (f" — {case.resolution_comment}"
                                       if case.resolution_comment else ""))
    if stars <= UNSETTLED_AT:
        reopen(case, "unsettled")
    elif case.status != "closed":
        close(case, "rated")
    return True


# ------------------------------------------------------------ lateness ---
def late_contact(case, now=None, hours=None):
    """Nobody has spoken to the family and the clinic's time has passed."""
    now = now or datetime.utcnow()
    hours = first_contact_hours() if hours is None else hours
    return (case.is_open and case.first_contact_at is None
            and now > case.contact_due(hours))


def late_close(case, now=None, days=None):
    """Still not answered, past the clinic's time for an answer."""
    now = now or datetime.utcnow()
    days = close_days() if days is None else days
    return (case.status in ("new", "in_progress")
            and now > case.close_due(days))


def is_late(case, now=None, hours=None, days=None):
    return late_contact(case, now, hours) or late_close(case, now, days)


def _late_filter(now=None):
    """The same two rules as :func:`is_late`, as SQL — the bell asks on
    every page, and must not load every open case to answer."""
    now = now or datetime.utcnow()
    contact_by = now - timedelta(hours=first_contact_hours())
    close_by = now - timedelta(days=close_days())
    return db.or_(
        db.and_(Complaint.status.in_(OPEN_STATUSES),
                Complaint.first_contact_at.is_(None),
                Complaint.created_at < contact_by),
        db.and_(Complaint.status.in_(("new", "in_progress")),
                Complaint.created_at < close_by))


def open_counts():
    """``{open, new, late, attention}`` for the bell and the list —
    ``attention`` being the cases that are new *or* late, counted once."""
    base = Complaint.query.filter(Complaint.status.in_(OPEN_STATUSES))
    late = _late_filter()
    return {"open": base.count(),
            "new": base.filter(Complaint.status == "new").count(),
            "late": base.filter(late).count(),
            "attention": base.filter(db.or_(Complaint.status == "new",
                                            late)).count()}


def late_cases(query):
    """Narrow a case query to the late ones."""
    return query.filter(_late_filter())


# ------------------------------------------------------ from elsewhere ---
def _lowest_side(fb):
    scores = [(fb.doctor_rating, "medical"), (fb.service_rating, "service"),
              (fb.finance_rating, "finance")]
    scores = [(s, side) for s, side in scores if s is not None]
    return min(scores)[1] if scores else None


def from_feedback(fb, lang="ar"):
    """A low survey answer becomes a case, once. Returns it or None."""
    if fb is None or fb.id is None:
        return None
    existing = Complaint.query.filter_by(feedback_id=fb.id).first()
    if existing is not None:
        return existing
    from app.utils.complaints import summarise
    return open_case(summarise(fb, lang), kind="complaint", channel="survey",
                     patient=fb.patient, side=_lowest_side(fb),
                     cost_centre_id=fb.cost_centre_id, feedback=fb,
                     thread_key=f"p{fb.patient_id}" if fb.patient_id else None,
                     lang=lang)


# -------------------------------------------------- the online invitation ---
def _signer():
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"],
                                  salt="complaint-invite")


def invite_token(patient):
    """A link a family can open to write their complaint themselves. Signed,
    so nobody can write one in another family's name; it expires."""
    return _signer().dumps({"p": patient.id})


def read_invite(token):
    """The patient id an invitation is for, or None when it is not ours or
    has expired."""
    try:
        data = _signer().loads(token, max_age=INVITE_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
    pid = data.get("p") if isinstance(data, dict) else None
    return pid if isinstance(pid, int) else None


def invite_link(patient):
    from app.utils import whatsapp as wa

    token = invite_token(patient)
    base = wa.get_config().get("public_base")
    if base:
        return f"{base}/f/c/new/{token}"
    from flask import url_for
    try:
        return url_for("feedback.case_new", token=token, _external=True)
    except Exception:  # noqa: BLE001
        return f"/f/c/new/{token}"


# -------------------------------------------------------------- reading ---
def summary(date_from=None, date_to=None):
    """What the complaints book says for a period: counts, the two clocks,
    and the family's verdict. Times in hours, averaged over the cases that
    have them."""
    q = Complaint.query
    if date_from is not None:
        q = q.filter(Complaint.created_at >= date_from)
    if date_to is not None:
        q = q.filter(Complaint.created_at < date_to)
    rows = q.all()
    now = datetime.utcnow()
    limit_h, limit_d = first_contact_hours(), close_days()

    def hours(pairs):
        vals = [(b - a).total_seconds() / 3600 for a, b in pairs if a and b]
        return round(sum(vals) / len(vals), 1) if vals else None

    complaints = [c for c in rows if c.kind == "complaint"]
    closed = [c for c in complaints if c.closed_at]
    in_time = [c for c in closed if c.closed_at <= c.close_due(limit_d)]
    rated = [c.resolution_rating for c in rows if c.resolution_rating]
    return {
        "total": len(rows),
        "by_kind": {k: sum(1 for c in rows if c.kind == k) for k in KINDS},
        "open": sum(1 for c in rows if c.is_open),
        "late": sum(1 for c in rows if is_late(c, now, limit_h, limit_d)),
        "first_contact_hours": hours((c.created_at, c.first_contact_at)
                                     for c in complaints),
        "close_hours": hours((c.created_at, c.closed_at) for c in complaints),
        "closed_in_time_pct": (round(len(in_time) * 100 / len(closed))
                               if closed else None),
        "resolution_avg": (round(sum(rated) / len(rated), 1)
                           if rated else None),
        "resolution_count": len(rated),
        "reopened": sum(1 for c in rows if c.reopened_count),
    }
