"""A decision taken over WhatsApp, written into the medical record.

The film comes back, the doctor reads it, and tells the family to carry on
with the medicine — or to change it, or to go and have one more test done.
That is a consultation. It happened on a phone rather than in the room, and
that is the only thing about it that is unusual.

**A WhatsApp message is not a medical record.** A thread of messages is
evidence that words were exchanged; it is not a record that a doctor decided
something, on what, and when. A year later, whoever opens the file has to
understand why the medicine changed on a day the child never came in. A file
that says nothing happened is worse than silence, because it looks correct.

So the decision is written as a visit of its own — appearing in the history
and the printouts like any other, because it *is* one — carrying:

* who decided it and when          (doctor_id, visit_date)
* that it was decided remotely     (channel="whatsapp")
* what it was decided on           (based_on → the investigation)
* and what was decided             (decision + plan)

The message to the family is sent from the clinic's number, so the
conversation stays in one place and the record stays with the clinic rather
than in somebody's personal phone.
"""
from datetime import datetime
from app.utils.clock import local_today

# What a doctor can conclude from a result. Deliberately three, and
# deliberately explicit: "he replied with some text" is not a decision anybody
# can search, count, or be held to.
DECISIONS = ("continue", "change", "investigate")


def record_decision(order, doctor, decision, note=None, new_test=None,
                    result_text=None, result_comment=None):
    """Write the remote consultation. Returns ``(visit, error_key)``.

    Reading the result and deciding on it are one action, because they are
    one thought: a doctor who has decided has necessarily read it, and
    leaving the order unread afterwards would keep it on the "waiting" list
    for something already dealt with.

    Does not commit — the caller owns the transaction, and the message to the
    family goes out in the same one.
    """
    from app.extensions import db
    from app.models import Visit, VisitInvestigation

    if decision not in DECISIONS:
        return None, "bad_decision"
    if order is None or doctor is None:
        return None, "not_found"

    # The result itself, if the doctor is recording it here — which is the
    # normal case, since this is the screen they read it on.
    if result_text or result_comment:
        order.result_text = (result_text or "").strip() or order.result_text
        order.result_comment = ((result_comment or "").strip()
                                or order.result_comment)
    if order.has_result:
        order.status = "resulted"
        order.resulted_at = order.resulted_at or datetime.utcnow()

    visit = Visit(
        patient_id=order.patient_id,
        doctor_id=doctor.id,
        visit_date=local_today(),
        channel="whatsapp",
        decision=decision,
        based_on_id=order.id,
        chief_complaint=_complaint(order),
        plan=(note or "").strip() or None,
        # Completed on arrival: a remote follow-up has no open-ended
        # examination to come back to, and leaving it open would put it on
        # the doctor's list of unfinished visits for ever.
        status="completed",
        completed_at=datetime.utcnow(),
    )
    db.session.add(visit)
    db.session.flush()

    # "Have one more test done" is only a decision if the test actually
    # exists afterwards — otherwise it is a sentence in a message.
    if decision == "investigate" and new_test:
        name = (new_test.get("name") or "").strip()
        if name:
            kind = new_test.get("kind")
            db.session.add(VisitInvestigation(
                visit_id=visit.id, patient_id=order.patient_id,
                kind=kind if kind in ("lab", "imaging") else "lab",
                name=name, status="requested",
                request_notes=(new_test.get("notes") or "").strip() or None))
    return visit, None


def _complaint(order):
    """What this consultation was about, in the visit's own words."""
    return f"متابعة نتيجة: {order.name}"[:255]


def decision_label(decision, lang="ar"):
    from app.i18n import t

    if decision not in DECISIONS:
        return ""
    return t(f"teleconsult.decision_{decision}")


def message_for(order, decision, note, lang="ar"):
    """A first draft of what to send the family — theirs to edit before it
    goes. Never sent without a person reading it: this is a medical message
    about their child, and the clinic's name is on it."""
    from app.i18n import t

    lines = [t(f"teleconsult.msg_{decision}")]
    if note:
        lines.append(note.strip())
    return "\n".join(line for line in lines if line)
