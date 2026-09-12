"""The theatre day, and whether it is safe to cut.

Two questions, and the second is the one this module exists for.

**What is on today** is a list, and an easy one: the bookings for a date,
theatre by theatre, in time order. Nothing clever, and nothing clever wanted —
a theatre list is printed and pinned to a wall.

**Whether the checklist has been done** is the other question, and it is the
same shape as every other absence this program has learned to answer: a stop
that nobody ran leaves no row behind. So the state of an operation's checklist
is worked out from which of the three rows exist, and the screen can say *the
team has not stopped before the first cut* — which is the sentence the WHO
Surgical Safety Checklist exists to force somebody to say out loud.

**And the program refuses to start a case whose sign-in is missing**, which is
the one hard refusal here. Everything else it will let a hospital do and
record: a stop signed with items unticked is stored with the unticked ones
named, because a checklist that silently rounds "four of seven" up to "done"
is worse than no checklist — it manufactures a signature.
"""
from datetime import datetime

from app.extensions import db
from app.models.theatre import (CHECK_ITEMS, CHECK_STOPS, PREOP_KINDS,
                                REVIEW_KINDS,
                                REVIEW_VERDICTS, SIGN_IN, SIGN_OUT, TIME_OUT,
                                Operation, PreOpReview, SafetyCheck, Theatre)
from app.utils import case_rates
from app.utils.clock import local_today


class NotSafeYet(Exception):
    """The team has not signed in, and somebody asked to start.

    Raised rather than returned, for the reason ``BedTaken`` is: every caller
    has to deal with it, and this is the one place in the program where the
    right answer to a request is *no*.
    """


def day(on_date=None, who=None):
    """Every booking on a date, theatre by theatre, in time order.

    Cancelled cases stay on the list, marked. A theatre morning where two of
    six were called off is a fact about that morning — dropping them would
    make the list agree with itself and disagree with the day.

    ``who`` narrows it to one person's cases — *"ليست للجراح وطبيب التخدير"*.
    **Either role counts.** A surgeon and an anaesthetist read the same day for
    different reasons, and a filter that answered only "cases I am cutting"
    would hand the anaesthetist somebody else's list and call it theirs.

    Rooms with none of their cases **drop out** rather than showing empty. A
    filter that leaves five empty rooms behind has not filtered anything, and
    the whole point is a short list somebody can hold in their head.
    """
    from sqlalchemy.orm import selectinload

    on_date = on_date or local_today()
    theatres = (Theatre.query.filter(Theatre.is_active.is_(True))
                .order_by(Theatre.sort_order, Theatre.id).all())
    bookings = (Operation.query
                .options(selectinload(Operation.patient),
                         selectinload(Operation.checks),
                         selectinload(Operation.surgeon))
                .filter(Operation.on_date == on_date)
                .order_by(Operation.start_time, Operation.id).all())
    if who:
        bookings = [b for b in bookings
                    if who in (b.surgeon_id, b.anaesthetist_id)]

    by_theatre = {}
    for booking in bookings:
        by_theatre.setdefault(booking.theatre_id, []).append(booking)

    rooms = [{"theatre": room,
              "operations": [{"operation": op, "safety": safety(op)}
                             for op in by_theatre.get(room.id, [])]}
             for room in theatres]
    # Empty rooms are part of the day — a theatre with nothing in it is a
    # theatre standing idle, and the person running the list wants to see
    # that. They are **not** part of one person's list, where they would be
    # five headings above nothing.
    return [r for r in rooms if r["operations"]] if who else rooms


def people_on(on_date=None):
    """The surgeons and anaesthetists who have a case on this day.

    For the dropdown, and deliberately **not** every doctor in the clinic: a
    list of forty names to find the two who are operating today is the kind of
    picker somebody stops using. Each person appears once however many cases
    they have, and in whichever role.
    """
    on_date = on_date or local_today()
    rows = (Operation.query
            .filter(Operation.on_date == on_date)
            .order_by(Operation.start_time, Operation.id).all())
    seen, out = set(), []
    for op in rows:
        for person in (op.surgeon, op.anaesthetist):
            if person is not None and person.id not in seen:
                seen.add(person.id)
                out.append(person)
    return sorted(out, key=lambda p: (p.full_name or "").strip())


def safety(operation):
    """Where this operation's checklist stands.

    ``{"done": [...], "next": stop or None, "missed": {...}, "ready": bool}``
    — ``ready`` meaning the team has signed in and the knife may be picked up
    at all. The missing stop is the finding, so it is named rather than left
    to be noticed.
    """
    signed = {c.stop: c for c in (operation.checks if operation else [])}
    pending = [stop for stop in CHECK_STOPS if stop not in signed]
    return {
        "signed": signed,
        "done": [stop for stop in CHECK_STOPS if stop in signed],
        "next": pending[0] if pending else None,
        # What was ticked short at each stop that *was* signed. A checklist
        # completed with gaps is not a completed checklist, and the screen
        # says which ones rather than showing a green tick.
        "missed": {stop: row.missed for stop, row in signed.items()
                   if row.missed},
        "ready": SIGN_IN in signed,
        "closed": SIGN_OUT in signed,
    }


#: The checklist item a family's signature is supposed to answer. Named here
#: because :func:`sign` refuses to take it from the form — see
#: :func:`consent_state`.
CONSENT_ITEM = "consent"

#: And the item an anaesthetist's assessment is supposed to answer. Same
#: treatment and the same reason: the standard asks for an assessment
#: *immediately before induction* (GAHAR SAS.16 EOC 5), and a tick is not one.
ANAESTHESIA_ITEM = "anaesthesia_check"


def consent_state(operation):
    """Whether a signed, standing consent covers this case — in one word.

    ``linked`` · ``unsigned`` · ``withdrawn`` · ``expired`` · ``none``, and
    they are five different conversations at the theatre door. Lumping them
    into a boolean would tell whoever is holding the knife that something is
    wrong without telling them what, which is the same as telling them
    nothing.

    Checked **against the day of the operation**, not against today: a case
    reviewed a week later must read as it read on the morning it happened.
    """
    if operation is None or operation.consent_id is None:
        return "none"
    row = operation.consent
    if row is None:
        return "none"
    if row.is_withdrawn:
        return "withdrawn"
    if not row.has_signature:
        return "unsigned"
    if row.expired_on(operation.on_date):
        return "expired"
    return "linked"


def consent_ok(operation):
    """The one question the checklist item asks."""
    return consent_state(operation) == "linked"


def consent_choices(operation):
    """The consents on this child's file that could cover this case.

    Everything not withdrawn, newest first — **including the unsigned and the
    expired ones**, because the person linking has to be able to see that the
    document they were about to rely on is unsigned. Hiding them would turn a
    visible problem into an empty list.
    """
    if operation is None or operation.patient is None:
        return []
    return [c for c in operation.patient.consents if not c.is_withdrawn]


def pre_induction_state(operation):
    """Whether an assessment was made in the anaesthetic room — in one word.

    ``none`` · ``stale`` · ``unfit`` · ``done``, because they are four
    different things to say to whoever is about to give the anaesthetic.

    **``stale`` is the one that matters and the one a boolean would hide.**
    The standard asks for an assessment *immediately before induction*, not
    for one on file: a case put off to the next day has an assessment that
    was true yesterday, and counting it would be the record claiming somebody
    looked at this child this morning. So it is judged against **the day of
    the operation**.
    """
    if operation is None:
        return "none"
    row = reviews(operation).get("pre_induction")
    if row is None:
        return "none"
    from app.utils.clock import local_date

    seen_on = local_date(row.at)
    if seen_on is not None and operation.on_date and seen_on != operation.on_date:
        return "stale"
    if row.verdict == "unfit":
        return "unfit"
    return "done"


def pre_induction_ok(operation):
    """The one question the checklist item asks.

    ``conditions`` counts: *"fit, once the chest is clear"* is an assessment
    that was made and a condition that was named — which is the whole reason
    that verdict exists. Only ``unfit`` and a missing or stale one do not.
    """
    return pre_induction_state(operation) == "done"


def reviews(operation):
    """What the surgeon and the anaesthetist have said about this case.

    Shaped like :func:`safety`: a dict keyed by what was asked, whose missing
    entries **are** the finding. A case with no ``anaesthesia`` key is one
    nobody has assessed, and that is a sentence the list can say rather than a
    silence somebody has to notice.
    """
    if operation is None:
        return {}
    return {r.kind: r for r in (operation.reviews or [])}


def review(operation, kind, verdict, user=None, note=None, at=None):
    """Record one person's look at the case before the day.

    Re-reviewing replaces: a child seen again after a chest infection cleared
    has **one** current answer, and keeping both would leave the list showing
    an "unfit" that stopped being true a week ago. The row carries who and
    when, so what was superseded is still attributable.
    """
    if operation is None:
        raise ValueError("no operation")
    if kind not in REVIEW_KINDS:
        raise ValueError("unknown kind")
    if verdict not in REVIEW_VERDICTS:
        raise ValueError("unknown verdict")
    text = (note or "").strip()[:500] or None
    # "Not fit" with nothing after it stops a list and tells the next person
    # nothing — they have to ring somebody to learn what the program already
    # knew. Only `fit` may be silent.
    if verdict != "fit" and not text:
        raise ValueError("needs a reason")

    row = reviews(operation).get(kind)
    if row is None:
        row = PreOpReview(operation_id=operation.id, kind=kind)
        db.session.add(row)
    row.verdict = verdict
    row.note = text
    row.at = at or datetime.utcnow()
    row.by_id = getattr(user, "id", None)
    return row


def unreviewed(on_date=None, kind=None):
    """Cases still waiting to be looked at — the working list.

    The whole point of moving the question earlier is that somebody can sit
    down and clear it, so what they need is *the ones nobody has done*, not
    the day's list with a column to scan. Cancelled cases are not waiting for
    anybody.

    ``kind`` narrows it to one person's queue; without it, a case missing
    either review is on the list.

    **The pre-induction assessment is not one of these.** It happens in the
    anaesthetic room on the day, so a queue that waited for it would never
    clear — see :data:`PREOP_KINDS`.
    """
    wanted = (kind,) if kind in PREOP_KINDS else PREOP_KINDS
    rows = (Operation.query
            .filter(Operation.on_date >= (on_date or local_today()),
                    Operation.status == "scheduled")
            .order_by(Operation.on_date, Operation.start_time).all())
    return [op for op in rows
            if any(k not in reviews(op) for k in wanted)]


def plan_for(operation):
    """This case's anaesthesia plan, or ``None`` — which is the finding."""
    return getattr(operation, "anaesthesia_plan", None) if operation else None


def write_plan(operation, user=None, **fields):
    """Record or correct the six-element plan. Returns the plan.

    Every field is the anaesthetist's own words: the program supplies the
    headings the standard names and writes none of the content. A blank stays
    blank rather than becoming an empty string that reads as "nothing to
    report" — see :attr:`AnaesthesiaPlan.missing`.
    """
    from app.models import ANAESTHESIA_TYPES, AnaesthesiaPlan

    if operation is None:
        raise ValueError("no operation")
    row = plan_for(operation)
    if row is None:
        row = AnaesthesiaPlan(operation_id=operation.id)
        db.session.add(row)
    kind = (fields.get("kind") or "").strip()
    row.kind = kind if kind in ANAESTHESIA_TYPES else None
    for name in ("induction", "airway", "fluids", "given_during", "events"):
        if name in fields:
            setattr(row, name, (fields.get(name) or "").strip() or None)
    row.at = datetime.utcnow()
    row.by_id = getattr(user, "id", None)
    return row


def blocking(operation):
    """Reviews that say this case should not go ahead as listed.

    Read by the screen to put the warning where the start button is. It does
    **not** refuse — ``start`` holds the one hard stop in this module, and it
    stays that way: a bleeding child does not wait for a form, and a program
    that blocked an emergency would be dangerous in the other direction.
    Saying it loudly, on the screen, every time, is the trade this module
    already makes for the missing sign-out.
    """
    return [r for r in reviews(operation).values() if r.verdict == "unfit"]


def sign(operation, stop, items=None, user=None, note=None, at=None):
    """Record one stop of the checklist.

    Stores the items that were actually confirmed, so a stop signed with two
    of seven ticked is kept as exactly that. Re-signing the same stop updates
    it rather than adding a second row — the unique constraint is what makes
    that safe when two screens run the checklist in the same minute.
    """
    if operation is None:
        raise ValueError("no operation")
    if stop not in CHECK_STOPS:
        raise ValueError("unknown stop")

    known = set(CHECK_ITEMS.get(stop, ()))
    confirmed = [i for i in (items or []) if i in known]

    # **The consent item is read, never taken.** Reported as the thing that
    # was wrong: *«بند الموافقة في الـ checklist بيتعلّم بالإيد حتى لو مفيش
    # إقرار متسجّل»* — a tick that could say a family had consented when no
    # document said so.
    #
    # So it is answered from the record in both directions: ticked when a
    # signed, standing consent is linked to this case even if nobody thought
    # to tick it, and dropped when none is, however firmly somebody ticked.
    # The stop can still be signed — a hospital may proceed, and this program
    # records rather than refuses — but the gap then shows in ``missed``,
    # where it is a finding instead of a green tick.
    if CONSENT_ITEM in known:
        confirmed = [i for i in confirmed if i != CONSENT_ITEM]
        if consent_ok(operation):
            confirmed.append(CONSENT_ITEM)

    # **And the anaesthetic check, for the same reason.** The standard asks
    # for an assessment immediately before induction (SAS.16 EOC 5); the
    # program had a box somebody ticked on the way past. Read from the
    # recorded assessment in both directions, exactly as the consent is — and
    # it refuses nothing either: a stop signed without it is signed, and the
    # gap shows in ``missed``.
    if ANAESTHESIA_ITEM in known:
        confirmed = [i for i in confirmed if i != ANAESTHESIA_ITEM]
        if pre_induction_ok(operation):
            confirmed.append(ANAESTHESIA_ITEM)

    row = operation.check_for(stop)
    if row is None:
        row = SafetyCheck(operation_id=operation.id, stop=stop)
        db.session.add(row)
    row.at = at or datetime.utcnow()
    row.by_id = getattr(user, "id", None)
    row.confirmed = ",".join(confirmed)
    row.note = (note or "").strip()[:255] or None
    return row


def start(operation, user=None, when=None):
    """Take the child into theatre — refused until the team has signed in.

    **The one hard refusal in this module.** Everything else a hospital may do
    and the program records; this is the stop the checklist exists for, and a
    program that lets a case start without it has a checklist that is a poster.
    """
    if operation is None or operation.status not in ("scheduled",):
        raise ValueError("not scheduled")
    if operation.check_for(SIGN_IN) is None:
        raise NotSafeYet(SIGN_IN)
    operation.status = "in_theatre"
    operation.started_at = when or datetime.utcnow()
    return operation


def finish(operation, user=None, findings=None, when=None):
    """The case is over. The sign-out is asked for but never forced.

    Refusing to record that an operation finished because the last stop is
    unsigned would leave the child in theatre for ever in the program's own
    telling. What the screen does instead is say the sign-out is missing and
    keep saying it — a gap that is visible is worth more than a refusal that
    gets worked around.
    """
    if operation is None or operation.status != "in_theatre":
        raise ValueError("not in theatre")
    operation.status = "done"
    operation.finished_at = when or datetime.utcnow()
    if findings is not None:
        operation.findings = (findings or "").strip() or None
    return operation


def cancel(operation, reason=None, user=None):
    """Called off. Kept on the list, marked, because a cancelled morning is
    a fact about the theatre's day."""
    if operation is None or not operation.is_open:
        return operation
    operation.status = "cancelled"
    operation.cancel_reason = (reason or "").strip()[:200] or None
    return operation


def book(patient, theatre, procedure, on_date=None, user=None, **extra):
    """Put a case on the list.

    Refuses a booking with no procedure named: "an operation" is not something
    a theatre list can be read from, and a name is the one thing nobody can
    supply later from the record.
    """
    name = (procedure or "").strip()[:200]
    # Each refusal names itself. "No child" and "no room" send whoever is
    # booking to two different next steps, and one message for both wastes
    # the trip — the same lesson the admission screen already learned.
    if patient is None:
        raise ValueError("no patient")
    if theatre is None:
        raise ValueError("no theatre")
    if not name:
        raise ValueError("no procedure")
    row = Operation(
        patient_id=patient.id, theatre_id=theatre.id, procedure=name,
        on_date=on_date or local_today(),
        booked_by=getattr(user, "id", None),
        **{k: v for k, v in extra.items() if v not in ("", None)})
    db.session.add(row)
    return row


def charge(admission, invoice, user=None, lang="ar"):
    """Put this stay's finished operations on its bill. Returns how many.

    Folded into the stay's one posting rather than billed on its own, for the
    reason the drugs are: a family gets one account for the admission, not a
    bed bill and a theatre bill and a pharmacy bill for the same three days.
    The procedure is a ``Service``, so the doctor's share, the insurance and
    the consumables it burns all follow with nothing added here.
    """
    from app.models.invoice import InvoiceItem

    if admission is None or invoice is None:
        return 0
    due = unbilled(admission_id=admission.id)
    for operation in due:
        service = operation.service
        surgeon = operation.surgeon or invoice.doctor
        # **The surgeon's rate for this kind of case**, which is one number
        # resolved in one place. It used to be ``service.price`` here and
        # ``service.price_for(surgeon)`` at the desk, so the same operation
        # cost a family one thing through a stay and another thing as a day
        # case — and neither door knew the other existed.
        price = float(case_rates.price_for(service, surgeon,
                                           operation.case_type))
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=_line(operation, service, lang),
            service_date=operation.on_date,
            unit_price=price, quantity=1)
        # The surgeon's share, snapshotted like any other chargeable line —
        # and read against **the surgeon**, not the admitting doctor, because
        # the person who did the operation is the person it is owed to.
        item.commission_amount = case_rates.share_for(
            service, item.net, surgeon, operation.case_type)
        # And recorded on the line, so repricing the bill from the cash list
        # later works it out at the surgeon's rate rather than handing it back
        # to the doctor the invoice belongs to.
        item.doctor_id = operation.surgeon_id or None
        db.session.add(item)
        db.session.flush()
        operation.invoice_item_id = item.id
        _charge_anaesthesia(operation, invoice, lang)
    return len(due)


ANAESTHESIA_CODE = "SVC-ANAES"


def anaesthesia_service():
    """The anaesthesia service, or ``None`` where the clinic has never had one.

    ``None`` is the ordinary answer and the important one: a clinic that
    prices the operation inclusive of the anaesthetic has no such row, and
    must not suddenly find a second line on every theatre bill. The line
    appears because somebody priced it, the same way the consultant's round
    does.
    """
    from app.models import Service

    return Service.query.filter_by(code=ANAESTHESIA_CODE).first()


def _charge_anaesthesia(operation, invoice, lang="ar"):
    """The anaesthetist's own line, when there is one to write.

    Reported as *«سعر الجراح والمخدر مختلف وبيختلف بين طبيب وطبيب»* — two
    people, two rates, and until now one line carrying only the surgeon's.
    The anaesthetist did the work and the bill said nothing about it, so
    their share was whatever the surgeon's service happened to pay, on a line
    recorded as the surgeon's.

    Three things have to be true before it is written, and each of them is
    somebody saying so: the clinic prices anaesthesia at all, an anaesthetist
    is named on the case, and the price comes out above zero.
    """
    from app.models.invoice import InvoiceItem

    if operation.anaesthesia_item_id is not None:
        return None                      # already billed; never twice
    service = anaesthesia_service()
    if service is None or not service.is_active:
        return None
    doctor = operation.anaesthetist
    if doctor is None:
        return None
    price = float(case_rates.price_for(service, doctor, operation.case_type))
    if price <= 0:
        return None

    item = InvoiceItem(
        invoice_id=invoice.id, service_id=service.id,
        description=_anaesthesia_line(operation, service, lang),
        service_date=operation.on_date,
        unit_price=price, quantity=1)
    item.commission_amount = case_rates.share_for(
        service, item.net, doctor, operation.case_type)
    # **Theirs, on the line.** Without this the anaesthetist's fee is paid to
    # whoever the invoice belongs to, and the two people the theatre owes are
    # one person in the books.
    item.doctor_id = doctor.id
    db.session.add(item)
    db.session.flush()
    operation.anaesthesia_item_id = item.id
    return item


def _anaesthesia_line(operation, service, lang):
    name = (service.display_name(lang) if hasattr(service, "display_name")
            else service.name)
    return f"{name} — {operation.procedure} ({operation.on_date.isoformat()})"[:200]


def _line(operation, service, lang):
    name = (service.display_name(lang) if hasattr(service, "display_name")
            else service.name)
    parts = [name]
    if operation.procedure and operation.procedure != name:
        parts.append(operation.procedure)
    return f"{' · '.join(parts)} ({operation.on_date.isoformat()})"[:200]


def unbilled(admission_id=None, patient_id=None):
    """Operations that were done and never charged.

    Same shape as an uncharged night or an unbilled dose: the operation
    carries the invoice line it went onto, so asking twice charges once.
    Only a **finished** case is chargeable — a cancelled morning owes nothing,
    and a case still on the table has not happened yet.
    """
    query = Operation.query.filter(Operation.status == "done",
                                   Operation.invoice_item_id.is_(None),
                                   Operation.service_id.isnot(None))
    if admission_id is not None:
        query = query.filter(Operation.admission_id == admission_id)
    if patient_id is not None:
        query = query.filter(Operation.patient_id == patient_id)
    return query.order_by(Operation.on_date, Operation.id).all()
