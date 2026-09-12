"""After the operation: the recovery room, going home, and what to do there.

Described by the clinic as the ordinary path, not an edge case:

> «الحالات اللي بتعمل جراحة بمخدر كلي بتقعد في الإفاقة وتخرج على طول لو
> العملية مش كبيرة، والحالات اللي بتاخد مخدر موضعي زي الطهارة بتخرج بعد
> الإفاقة على طول، ويتكتبلها تعليمات بعد الجراحة، ويا بتطلب استشارة بعد
> العملية يا لأ»

Three things the program had nothing for, and a day-case list is mostly made
of them: **where the child is after theatre**, **what the family were told**,
and **whether anybody is expecting to see them again**.

**Stamps, not statuses.** ``Operation.status`` keeps the four words it has
always had, because code reads ``done`` by name — the billing query is exactly
that filter — and moving a recovered child to a fifth word would quietly drop
their operation off the bill. Where they are is derived from which moments
have happened.

**And "nobody decided" is a state.** ``followup_needed`` is nullable on
purpose: a surgeon saying *no* and a screen nobody filled in look identical
the moment those two share a column, and the child who is never seen again is
the second one, not the first.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Operation
from app.utils.clock import local_today


def to_recovery(operation, user=None, at=None):
    """The child has left theatre. Returns the operation, or ``None``.

    Only a case that actually happened: an operation still scheduled, or one
    that was cancelled, has no recovery to be in — and stamping one would put
    a child in a room they were never taken to.

    Idempotent: a second press keeps the first moment, because the first is
    the true one and the second is somebody clicking twice.
    """
    if operation is None or operation.status != "done":
        return None
    if operation.recovery_at is None:
        operation.recovery_at = at or datetime.utcnow()
    return operation


def in_recovery(on_date=None):
    """Who is in the recovery room right now — arrived, not yet gone home.

    The screen this answers is the one a nurse looks at to know the room is
    not empty. Ordered by how long they have been there, longest first: the
    child who has been in recovery two hours is the one somebody should be
    asking about.
    """
    query = (Operation.query
             .filter(Operation.recovery_at.isnot(None),
                     Operation.discharged_at.is_(None))
             .order_by(Operation.recovery_at))
    if on_date is not None:
        query = query.filter(Operation.on_date == on_date)
    return query.all()


def awaiting_discharge(on_date=None):
    """Today's finished cases that have not been sent home.

    Wider than :func:`in_recovery` by one group — the cases that finished and
    were never marked into recovery at all. They are the ones that fall
    through: nobody pressed anything, so nobody is counting them, and a
    discharge list built only from the recovery room would never show them.
    """
    query = (Operation.query
             .filter(Operation.status == "done",
                     Operation.discharged_at.is_(None))
             .order_by(Operation.on_date.desc(), Operation.id))
    if on_date is not None:
        query = query.filter(Operation.on_date == on_date)
    return query.all()


def followup_default(operation):
    """When this procedure would usually be seen again, or ``None``.

    Read off the **service**, because it is a property of the operation and
    not of the child: a circumcision under local anaesthetic usually needs
    none, and a clinic writes that once rather than deciding it every time.
    A default, never the decision — that lives on the case.
    """
    service = getattr(operation, "service", None)
    days = getattr(service, "followup_days", None)
    if not days:
        return None
    base = operation.on_date or local_today()
    return base + timedelta(days=int(days))


def discharge(operation, user=None, note=None, followup=None, followup_on=None,
              at=None):
    """Send a day case home, with the one decision that must not be skipped.

    ``followup`` is **required**: ``None`` is refused, because the whole point
    of recording it is that "no follow-up needed" and "nobody was asked" stop
    being the same thing. Returns the operation, or ``None`` when it refuses.

    A child already sent home is not sent home twice — the first discharge is
    the real one, and the second is a double press.
    """
    if operation is None or operation.status != "done":
        return None
    if operation.discharged_at is not None:
        return None
    if followup is None:
        return None

    operation.discharged_at = at or datetime.utcnow()
    operation.discharged_by = getattr(user, "id", None)
    operation.discharge_note = (note or "").strip() or None
    operation.followup_needed = bool(followup)
    # A date only where somebody is actually expected. Keeping one against a
    # "no" would put a child on a list nobody meant to put them on.
    operation.followup_on = (followup_on or followup_default(operation)
                             if followup else None)
    # Somebody left theatre without anybody marking the recovery room, and
    # they were plainly in it — stamped here rather than left empty, so the
    # gap between theatre and home is not a hole in the record.
    if operation.recovery_at is None:
        operation.recovery_at = operation.discharged_at
    return operation


def instructions_for(operation, lang="ar"):
    """What this family should be told to do at home, or ``None``.

    Written per procedure on the service. ``None`` where nobody wrote any —
    and then nothing is sent, because a message that says only «تعليمات بعد
    الجراحة:» and then stops is worse than no message.
    """
    service = getattr(operation, "service", None)
    text = (getattr(service, "post_op_instructions", None) or "").strip()
    return text or None


def send_instructions(operation, user=None):
    """Send the family what to do at home. Returns the log, or ``None``.

    Through the same door every other message goes out of — the same opt-out,
    the same window, the same log — because a clinic that has silenced its
    messages has silenced this one too, and a second path would not know it.
    """
    from app.utils import whatsapp

    if operation is None:
        return None
    text = instructions_for(operation)
    if not text:
        return None
    patient = operation.patient
    if patient is None or not patient.contact_phone:
        return None

    body = whatsapp.render(whatsapp.template_body(
        "post_op", getattr(patient, "gender", None)), {
        "patient": patient.display_name("ar"),
        "first_name": whatsapp.first_name_of(patient.display_name("ar")),
        "procedure": operation.procedure or "",
        "instructions": text,
        "followup": (operation.followup_on.isoformat()
                     if operation.followup_on else ""),
    })
    log = whatsapp.send(body, patient.contact_phone, patient_id=patient.id,
                        user_id=getattr(user, "id", None),
                        template_type="post_op")
    if log is not None and log.status not in ("failed", "skipped"):
        operation.instructions_sent_at = datetime.utcnow()
    return log


def expecting(on_date=None):
    """Children somebody said they would see again, and when.

    The other half of the decision: recording "yes, in ten days" and then
    having no list of who that was is the same as not recording it.
    """
    query = (Operation.query
             .filter(Operation.followup_needed.is_(True),
                     Operation.followup_on.isnot(None))
             .order_by(Operation.followup_on))
    if on_date is not None:
        query = query.filter(Operation.followup_on <= on_date)
    return query.all()


def undecided(on_date=None):
    """Discharged cases where nobody answered the follow-up question.

    Should be empty, because :func:`discharge` refuses without an answer —
    which makes this the query that proves it, and the one that finds the
    cases discharged before the question existed.
    """
    query = (Operation.query
             .filter(Operation.discharged_at.isnot(None),
                     Operation.followup_needed.is_(None))
             .order_by(Operation.discharged_at.desc()))
    if on_date is not None:
        query = query.filter(Operation.on_date == on_date)
    return query.all()
