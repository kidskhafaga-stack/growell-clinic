"""The child who stopped coming — and the reason this one is sent by a person.

Every other message this program sends is a reply to something: a booking, a
missed visit, a rating, a failed send. This one is not. Nothing has happened —
that *is* the thing — so it goes out to families who are not currently talking
to the clinic, which makes it the only message here that can turn the clinic's
number into a source of unasked-for mail. A number that becomes that gets
blocked, and then the vaccination reminder does not arrive either.

So three deliberate limits, and none of them is a matter of taste:

**The clinic decides who counts as lapsed.** A practice seeing well children
yearly and one following chronic asthma have different answers, and neither is
the program's to pick. ``recall_after_months`` is the setting.

**No cap of its own.** The daily send cap is defined for *all* messages
(``wa_daily_cap``) and this obeys it like everything else. A per-type cap would
mean a second, quieter limit sitting under the one the clinic set, and the two
would disagree the first time somebody changed one — and deciding whether the
messaging hub should have per-type caps at all is a question about the hub, not
about this feature.

**It is a list somebody presses, not a sweep that runs.** Nothing here is
scheduled or automatic.

**And it has to know about archiving.** The program already retires a file
after ``archive_inactive_years`` of no visits: ``is_active`` goes false and the
patient leaves the roster. Two consequences, and the second is the one that
would have been shipped as a mystery:

1. An archived file is never recalled. The clinic has already decided that
   patient is not on its books, and messaging them is the program overruling
   that quietly.
2. A recall window at or past the archive window selects **nobody** — everyone
   that old has already been archived out of the candidate pool. That is an
   empty screen with no explanation, which reads exactly like a broken
   feature, so :func:`archive_conflict` says it out loud instead.
"""
from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import MessageLog, Patient, Setting, Visit
from app.utils.clock import local_today

TYPE = "patient_recall"

# Long enough that a family with a well child is not chased, short enough to
# reach them while the clinic is still "their" clinic.
DEFAULT_MONTHS = 12
MIN_MONTHS = 1
MAX_MONTHS = 60

# Nobody is recalled twice in this window, however many times the button is
# pressed. One message is an offer; the second is the clinic nagging.
REPEAT_GUARD_DAYS = 180


def after_months():
    """How long without a visit before a family is worth a message."""
    try:
        months = int(Setting.get("recall_after_months", DEFAULT_MONTHS))
    except (TypeError, ValueError):
        return DEFAULT_MONTHS
    return max(MIN_MONTHS, min(MAX_MONTHS, months))


def cutoff(months=None, today=None):
    """The last-visit date on or before which a family is a candidate."""
    months = after_months() if months is None else months
    today = today or local_today()
    # Calendar months, not 30-day blocks: "a year since we saw them" should
    # mean the same date, not eleven days early.
    total = (today.year * 12 + today.month - 1) - months
    y, m = divmod(total, 12)
    day = min(today.day, 28)
    return today.replace(year=y, month=m + 1, day=day)


def archive_conflict():
    """Is the recall window at or past the archiving window?

    When it is, the candidate list is empty for a reason nobody could guess
    from looking at it: every file that old has already left the roster. The
    screen says so rather than showing an empty table.
    """
    from app.utils.archiving import inactive_years

    return after_months() >= inactive_years() * 12


def _recently_recalled_ids(today=None):
    """Patients already sent a recall inside the repeat guard."""
    since = (today or local_today()) - timedelta(days=REPEAT_GUARD_DAYS)
    rows = (db.session.query(MessageLog.patient_id)
            .filter(MessageLog.template_type == TYPE,
                    MessageLog.patient_id.isnot(None),
                    MessageLog.created_at >= since)
            .distinct().all())
    return {r[0] for r in rows}


def candidates(months=None, today=None, limit=200):
    """Active families whose last visit predates the cutoff.

    Returns ``(patient, last_visit_date)`` oldest-first — the review list, not
    a send queue. Archived files are excluded by ``is_active``: the clinic has
    already said those are off its books.
    """
    from sqlalchemy.orm import joinedload

    from app.models import Family

    today = today or local_today()
    line = cutoff(months, today)

    # The lapsed condition is the selective one, so it belongs in the database.
    # This used to read **every active patient** into memory and decide here —
    # a full scan of the register to build a review list, on a screen the desk
    # opens daily. Only patients whose newest visit is already past the cutoff
    # come back now.
    #
    # "No visit at all" is excluded by the join itself, and deliberately: a
    # file somebody created and never used is not a lapsed family, and a
    # message about a visit that never happened reads as a mistake.
    lapsed = (db.session.query(Visit.patient_id.label("pid"),
                               func.max(Visit.visit_date).label("seen"))
              .group_by(Visit.patient_id)
              .having(func.max(Visit.visit_date) <= line)
              .subquery())

    rows = (db.session.query(Patient, lapsed.c.seen)
            .join(lapsed, lapsed.c.pid == Patient.id)
            .filter(Patient.is_active.is_(True))
            # `contact_phone` falls back to the guardians' numbers, so without
            # this it is one more query per candidate.
            .options(joinedload(Patient.family).joinedload(Family.parents))
            .order_by(lapsed.c.seen)
            .all())

    # The rest stays in Python, on what is now a small set. The opt-out in
    # particular: it is nullable on older rows, and `wa_opt_out IS false` in
    # SQL would quietly disagree with the truthiness test this has always
    # used — a difference that would show up as somebody being written to.
    skip = _recently_recalled_ids(today)
    out = []
    for patient, seen in rows:
        if patient.id in skip or patient.wa_opt_out:
            continue
        if not patient.contact_phone:
            continue
        out.append((patient, seen))
    return out[:limit]


def render(patient, last_visit, lang="ar"):
    from app.utils import whatsapp as wa

    return wa.render(wa.template_body(TYPE), {
        "patient": patient.display_name(lang),
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": last_visit.strftime("%Y-%m-%d") if last_visit else "",
        "months": after_months(),
    })


def send_to(patient, last_visit, user_id=None, lang="ar"):
    """Send one family their recall. Returns the log row, or None."""
    from app.utils import whatsapp as wa

    if patient is None or not patient.is_active:
        return None
    phone = patient.contact_phone
    if not phone or wa.type_is_off(TYPE):
        return None
    return wa.send(render(patient, last_visit, lang), phone,
                   patient_id=patient.id, user_id=user_id,
                   template_type=TYPE, image_url=wa.template_image(TYPE))


def send_all(months=None, limit=200, user_id=None, lang="ar"):
    """Send to everybody currently on the list. Returns a small summary."""
    rows = candidates(months=months, limit=limit)
    sent = 0
    for patient, last_visit in rows:
        if send_to(patient, last_visit, user_id=user_id, lang=lang) is not None:
            sent += 1
    if sent:
        db.session.commit()
    return {"considered": len(rows), "sent": sent}
