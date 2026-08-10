"""An unhappy family, in front of somebody who can answer them.

Measured before building: ``feedback.py`` holds ``doctor_ratings()``,
``summary()`` and the NPS roll-up — every one of them an *aggregate*. There was
no path at all from a low rating to anybody doing anything. A mother gave one
star out of five, wrote why, and her answer went into a monthly average.

A complaint somebody replies to turns the most annoyed patient into the most
loyal one; a complaint that is only counted gets written on Facebook a week
later. The difference is not analytics — it is whether one person saw it in
time.

**It becomes a conversation, not a new screen.** The clinic already has one
place where patient messages are read, assigned, answered and closed, with a
``complaint`` topic and a first-reply clock over it. Putting these anywhere
else would create a second inbox for staff to remember, and the one they do not
have open is the one that goes unread.

**It is recorded as something the family said, because it is.** The survey is
the clinic asking a question and the family answering it; the answer arrives
as an inbound message on their thread, carrying their own words and the score
that prompted it. Writing it as anything else would put a complaint in the
inbox with no way to see what they actually complained about.

**Only ever raises.** If the thread already carries a topic somebody chose —
including ``urgent`` — this does not overwrite it. Same rule as the triage
guesser: a human's answer is not something to keep second-guessing, and a
complaint label on top of an emergency would move a child down the list.
"""
from datetime import datetime

from app.extensions import db
from app.models import MessageLog, Setting

# At or below this many stars, somebody should be reading it today.
DEFAULT_STARS = 2
# Net Promoter's own definition of a detractor. Somebody who answers 6 is not
# telling you they are content, whatever the stars say.
DEFAULT_NPS = 6


def _threshold(key, default):
    try:
        return int(Setting.get(key, default))
    except (TypeError, ValueError):
        return default


def stars_threshold():
    return _threshold("feedback_complaint_stars", DEFAULT_STARS)


def nps_threshold():
    return _threshold("feedback_complaint_nps", DEFAULT_NPS)


def is_complaint(fb):
    """Is this survey response one somebody has to answer?

    Any single low score counts. A family that rated the doctor five and the
    waiting room one has told the clinic something specific and useful, and
    averaging the two into a comfortable three is how it gets lost.
    """
    if fb is None or fb.status != "submitted":
        return False
    stars = stars_threshold()
    for rating in (fb.doctor_rating, fb.service_rating):
        if rating is not None and rating <= stars:
            return True
    return fb.nps is not None and fb.nps <= nps_threshold()


def summarise(fb, lang="ar"):
    """The complaint in the words that will be read in the inbox.

    The scores first, because they are why this is here, then whatever the
    family wrote. A row that showed only "low rating" would send whoever picks
    it up back to another screen to find out what about.
    """
    parts = []
    if fb.doctor_rating is not None:
        parts.append(f"الطبيب {fb.doctor_rating}/5")
    if fb.service_rating is not None:
        parts.append(f"الخدمة {fb.service_rating}/5")
    if fb.nps is not None:
        parts.append(f"الترشيح {fb.nps}/10")
    head = "تقييم بعد الزيارة — " + " · ".join(parts) if parts else "تقييم بعد الزيارة"
    body = (fb.comment or "").strip()
    return f"{head}\n{body}" if body else head


def already_raised(fb):
    """True when this survey has already produced a thread entry.

    A guardian who opens the survey page twice must not fill the inbox twice.
    """
    return MessageLog.query.filter_by(
        direction="in", template_type=TYPE,
        patient_id=fb.patient_id,
        body=summarise(fb)).first() is not None


TYPE = "feedback_complaint"


def raise_from_feedback(fb, lang="ar"):
    """Put a low rating in the inbox as a thread waiting for an answer.

    Returns the message row, or None when there is nothing to raise. Never
    raises an exception into the survey page: a guardian submitting a rating
    must not meet an error because the clinic's inbox had a problem, and the
    rating itself is already saved by then.
    """
    if not is_complaint(fb) or fb.patient_id is None:
        return None
    if already_raised(fb):
        return None

    phone = fb.patient.contact_phone if fb.patient else None
    row = MessageLog(
        patient_id=fb.patient_id,
        to_phone=phone or "",
        body=summarise(fb, lang),
        provider="survey",
        direction="in",
        status="received",
        template_type=TYPE,
        created_at=datetime.utcnow(),
    )
    db.session.add(row)

    from app.utils.inbox import conversation_for
    conv = conversation_for(f"p{fb.patient_id}")
    if conv is not None:
        conv.patient_id = fb.patient_id
        if phone and not conv.phone:
            conv.phone = phone
        # Only ever raises: a thread already labelled by a person keeps its
        # label, and an "urgent" one certainly does — relabelling that as a
        # complaint would move a child down the list.
        if not conv.topic:
            conv.topic = "complaint"
        # A rating that arrives after somebody closed the thread re-opens it,
        # which is the same rule an inbound message already follows.
        conv.resolved_at = None
    return row
