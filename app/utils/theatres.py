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
from datetime import datetime, time

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

#: And the one a marked site answers. **The never-event.** SAS.06 (د) asks
#: for the site to be marked; the program had a box saying it was, with no
#: record of which site — which is exactly how a wrong-side operation gets a
#: signature saying it was verified.
SITE_ITEM = "site_marked"

#: And the one a recorded identity check answers. **The other half of the
#: never-event.** SAS.06 (أ) asks for the child and the planned procedure to be
#: confirmed *with the family taking part*; the program had a box anybody could
#: tick — and in paediatrics that box carries the most, because the child
#: cannot confirm their own name and two siblings are on the same morning's
#: list under the same surname.
IDENTITY_ITEM = "identity"

#: And the one the imaging half of the workup answers. **Already on the list**
#: — the WHO time-out asks «الأشعة معروضة», and that is the same question
#: SAS.06 (هـ) asks about imaging. Deriving an item that exists touches only
#: what is signed from now on; adding a new one would make every checklist ever
#: signed read as short, which is a record rewritten by a release.
IMAGING_ITEM = "imaging_ready"


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


def site_state(operation):
    """Whether somebody marked the site, and recorded which — in one word.

    ``none`` · ``marked``. Two and not five, because unlike the consent there
    is no half-way: either a person put their name against a side and a place,
    or nobody did.

    ``not_applicable`` **counts as marked** and is the commonest answer on a
    children's list — a tonsillectomy has no side, and somebody recording
    that is somebody who considered the question. Refusing it would make the
    honest answer unavailable and leave people picking "left" to get past the
    screen, which is worse than the box it replaced.
    """
    if operation is None:
        return "none"
    from app.models.theatre import SITE_SIDES

    if operation.site_side not in SITE_SIDES:
        return "none"
    if operation.site_marked_by is None or operation.site_marked_at is None:
        # A side with nobody's name against it is a note, not a marking.
        return "none"
    return "marked"


def site_ok(operation):
    """The one question the checklist item asks."""
    return site_state(operation) == "marked"


def mark_site(operation, side, user=None, note=None, at=None):
    """Record which side, and who says so. Returns the operation, or ``None``.

    Refused without a recognised side: a free-typed one would put the
    checklist's answer beyond anything the program could read, which is the
    tick it replaced wearing a different hat.
    """
    from app.models.theatre import SITE_SIDES

    if operation is None or side not in SITE_SIDES:
        return None
    operation.site_side = side
    operation.site_note = (note or "").strip()[:160] or None
    operation.site_marked_by = getattr(user, "id", None)
    operation.site_marked_at = at or datetime.utcnow()
    return operation


def identity_state(operation):
    """Whether somebody confirmed this child, and who stood with them.

    ``none`` · ``with_family`` · ``alone``.

    Three words and not two, because the difference between the last two is
    the thing the standard is actually asking about, and it must not vanish
    into a tick. ``alone`` is an **honest answer**, not a failure: a child
    brought by a school, or arriving in an emergency with nobody, still has
    their identity confirmed by a named person at a recorded moment. What
    ``alone`` does is leave that visible — so a month of them is a finding
    somebody can go and look at, rather than a wall of green.

    A record with nobody's name against it is ``none``: same rule as the site,
    where a side with no signature is a note and not a marking.
    """
    if operation is None:
        return "none"
    from app.models.theatre import IDENTITY_PRESENT, IDENTITY_WITH

    if operation.identity_with not in IDENTITY_WITH:
        return "none"
    if operation.identity_checked_by is None or operation.identity_checked_at is None:
        return "none"
    return "with_family" if operation.identity_with in IDENTITY_PRESENT else "alone"


def identity_ok(operation):
    """The one question the checklist item asks.

    Both recorded answers count. The program records; it does not refuse a
    case because the family could not come — and refusing would only teach
    people to name somebody who was not there, which is the tick again.
    """
    return identity_state(operation) in ("with_family", "alone")


def _wristbands():
    """Does this clinic band its patients?

    Off by default, and read rather than assumed: most outpatient paediatric
    clinics do not use wristbands at all, and an identifier nobody wears is
    one more box on a screen that people learn to tick without reading.
    """
    from app.models import Setting

    return Setting.get("theatre_wristbands", "0") == "1"


def identity_options(operation):
    """What the screen may offer: the guardians on file, and the identifiers
    this child actually has.

    Two lists, and the second one is the point. ``national_id`` is not offered
    for a child who has none on record, because a ticked "national id matched"
    on a child with no national id is a record of something that cannot have
    happened — the program would be collecting a confirmation of its own
    empty column.
    """
    from app.models.theatre import IDENTITY_KEYS

    people = []
    patient = getattr(operation, "patient", None)
    family = getattr(patient, "family", None) if patient is not None else None
    for row in (getattr(family, "parents", None) or []):
        people.append({"relation": row.relation if row.relation in
                       ("father", "mother", "guardian") else "guardian",
                       "name": row.display_name()})

    have = {
        # The name and the procedure are always there — a case cannot be
        # booked without either.
        "name": bool(getattr(patient, "full_name", None)),
        "birth_date": getattr(patient, "date_of_birth", None) is not None,
        "file_number": bool(getattr(patient, "patient_number", None)),
        "national_id": bool((getattr(patient, "national_id", None) or "").strip()),
        "procedure": bool(getattr(operation, "procedure", None)),
        # A clinic that does not band its patients has nothing to match, and
        # offering it invites a tick for a bracelet nobody wears.
        "wristband": _wristbands(),
    }
    # Named ``identifiers`` and not ``keys`` on purpose. In Jinja,
    # ``options.keys`` resolves to the dict's own ``keys`` *method* and renders
    # as a bound method rather than the list — this program has already shipped
    # that exact bug once, as ``row.items`` on the invoice screen. The name
    # that cannot collide is the fix; ``['keys']`` would only work until the
    # next person writes the dotted form.
    # ``named`` is the same people keyed by relation, so the screen can put
    # the guardian's actual name *in the option label* — «الأم — فاطمة السيد».
    # Whoever is confirming then reads who is on file before choosing, instead
    # of picking a role and finding out afterwards which name it filled in.
    named = {}
    for person in people:
        named.setdefault(person["relation"], person["name"])
    return {"people": people, "named": named,
            "identifiers": [k for k in IDENTITY_KEYS if have.get(k)]}


def verify_identity(operation, with_whom, name=None, matched=None, user=None,
                    at=None):
    """Record that somebody confirmed this child. Returns it, or ``None``.

    Refused without a recognised answer for who took part, for the reason
    :func:`mark_site` refuses a free-typed side: a value the program cannot
    read puts the checklist's answer past anything it can derive, which is the
    tick it replaced wearing a different hat.

    ``none_present`` **clears the name**. "Nobody from the family was there,
    and her name is Fatma" is a contradiction, and storing both halves of it
    would leave whoever reads the record later choosing which one to believe.
    """
    from app.models.theatre import IDENTITY_KEYS, IDENTITY_PRESENT, IDENTITY_WITH

    if operation is None or with_whom not in IDENTITY_WITH:
        return None
    operation.identity_with = with_whom
    if with_whom in IDENTITY_PRESENT:
        operation.identity_with_name = (name or "").strip()[:120] or None
    else:
        operation.identity_with_name = None
    keys = [k for k in (matched or []) if k in IDENTITY_KEYS]
    operation.identity_matched = ",".join(keys) or None
    operation.identity_checked_by = getattr(user, "id", None)
    operation.identity_checked_at = at or datetime.utcnow()
    return operation


def identity_matched_keys(operation):
    """What was matched, as a list. ``identity_matched`` is a joined string
    and every caller wants the parts."""
    raw = (getattr(operation, "identity_matched", None) or "")
    return [k for k in (p.strip() for p in raw.split(",")) if k]


def privilege_state(operation):
    """Where this booking stands against the surgeon's privileges.

    ``unknown`` · ``ok`` · ``supervised`` · ``outside`` · ``acknowledged``.

    Derived, and **judged against the day of the operation** — a case booked
    in March under a privilege that stood in March goes on reading as correct
    after it lapses, and one granted in April does not retroactively make
    March's booking fine. Same rule as the consent, for the same reason.

    ``unknown`` is the honest answer for a case booked as free text with no
    service behind it: there is nothing to check it against, and calling that
    ``ok`` would report a verification the program never did.

    ``acknowledged`` outranks ``outside`` because it *is* the answer once
    somebody has taken the decision and put their name to it — but it never
    reads as ``ok``: the gap stays visible, which is the whole point of
    recording it rather than clearing it.
    """
    if operation is None:
        return "unknown"
    from app.utils import privileges

    answer = privileges.state(operation.surgeon_id, operation.service,
                              operation.on_date)
    if answer == "outside" and operation.privilege_ack_at:
        return "acknowledged"
    return answer


def privilege_ok(operation):
    """Is there nothing outstanding here?

    ``acknowledged`` counts: somebody senior looked at the gap and put their
    name to it, which is what the standard asks for. ``outside`` does not, and
    neither does ``unknown`` — an unanswerable question is not a passed one.
    """
    return privilege_state(operation) in ("ok", "supervised", "acknowledged")


def acknowledge_privilege(operation, reason, user=None, at=None):
    """Record who accepted a booking outside the privileges, and why.

    Refused without a reason. "Somebody clicked accept" is the tick this whole
    module keeps replacing; the sentence they typed is the only part of this a
    review afterwards can use.
    """
    if operation is None:
        return None
    text = (reason or "").strip()[:200]
    if not text:
        return None
    operation.privilege_ack_reason = text
    operation.privilege_ack_by = getattr(user, "id", None)
    operation.privilege_ack_at = at or datetime.utcnow()
    return operation


def implants_for(operation):
    """The implants recorded against this case, in list order."""
    if operation is None or getattr(operation, "id", None) is None:
        return []
    from app.models.theatre import OperationImplant

    return (OperationImplant.query
            .filter_by(operation_id=operation.id)
            .order_by(OperationImplant.sort_order, OperationImplant.id).all())


def implant_state(operation):
    """Where this case stands on implants — in one word.

    ``unasked`` · ``not_needed`` · ``none_named`` · ``waiting`` · ``ready``.

    This is the **SAS.06 (ز)** half only: is what this case needs *here*,
    before the patient is called for. What actually went into the child is a
    different question with a different answer, asked after the case — see
    :func:`implanted_in`.

    ``not_needed`` is nearly every case on a children's list, which is exactly
    why it has to be a recorded answer and not the absence of one.
    """
    if operation is None or operation.implants_needed is None:
        return "unasked"
    if not operation.implants_needed:
        return "not_needed"
    rows = implants_for(operation)
    if not rows:
        return "none_named"
    return "ready" if all(r.available_at for r in rows) else "waiting"


def implants_ready(operation):
    """The one question somebody about to call for the patient is asking."""
    return implant_state(operation) in ("not_needed", "ready")


def set_implants_needed(operation, needed, user=None):
    """Record whether this case implants anything at all."""
    if operation is None or needed is None:
        return None
    operation.implants_needed = bool(needed)
    return operation


def add_implant(operation, name, lot=None, manufacturer=None, serial=None,
                expiry=None, size=None, note=None):
    """Name one implant this case plans to use. Returns it, or ``None``.

    A blank name is refused. Everything else is optional at this point on
    purpose: a plate is often chosen from a tray in the room, and demanding
    the batch number before the case would have somebody type a placeholder —
    which is worse than an empty field, because a recall would then search it.
    """
    from app.models.theatre import OperationImplant

    if operation is None or getattr(operation, "id", None) is None:
        return None
    clean = (name or "").strip()[:160]
    if not clean:
        return None
    row = OperationImplant(
        operation_id=operation.id, name=clean,
        manufacturer=(manufacturer or "").strip()[:120] or None,
        lot=(lot or "").strip()[:60] or None,
        serial=(serial or "").strip()[:60] or None,
        expiry=expiry, size=(size or "").strip()[:60] or None,
        note=(note or "").strip()[:160] or None,
        sort_order=len(implants_for(operation)))
    db.session.add(row)
    # Naming one *is* the answer to "does this case implant anything".
    if operation.implants_needed is None:
        operation.implants_needed = True
    return row


def confirm_implant(implant, user=None, at=None):
    """It is here, in the operating location. The SAS.06 (ز) half."""
    if implant is None:
        return None
    implant.available_at = at or datetime.utcnow()
    implant.available_by = getattr(user, "id", None)
    return implant


def record_implanted(implant, lot=None, serial=None, expiry=None, user=None,
                     at=None):
    """It went into this child. The SAS.11 half, and what a recall reads.

    The batch number can be filled in **here**, because this is the moment it
    is actually known: the wrapper is open and in somebody's hand. Refused
    without it — *"the procedure report includes the details of any used
    implantable device, including the batch number"* is the evidence the
    standard asks for by name, and an implant in a child with no batch is a
    child a recall cannot find.
    """
    if implant is None:
        return None
    if lot is not None:
        implant.lot = (lot or "").strip()[:60] or None
    if serial is not None:
        implant.serial = (serial or "").strip()[:60] or None
    if expiry is not None:
        implant.expiry = expiry
    if not implant.lot and not implant.serial:
        # Neither a batch nor a serial is nothing to recall on.
        return None
    implant.implanted_at = at or datetime.utcnow()
    implant.implanted_by = getattr(user, "id", None)
    return implant


def remove_implant(implant):
    """Take one off the case's list. Only ever a *planned* one.

    An implant recorded as having gone into a child is not deletable from
    here: that row is what a recall reads, and a screen that can quietly drop
    it is a screen that can lose a child.
    """
    if implant is None or implant.implanted_at:
        return None
    db.session.delete(implant)
    return True


def implanted_in(patient_id):
    """Everything ever implanted in one child, newest first.

    *"Every patient with an implantable device should be easily identified"* —
    read from the patient's side, because that is the side somebody is
    standing on when a family telephones.
    """
    from app.models.theatre import OperationImplant

    return (OperationImplant.query
            .join(Operation, OperationImplant.operation_id == Operation.id)
            .filter(Operation.patient_id == patient_id,
                    OperationImplant.implanted_at.isnot(None))
            .order_by(OperationImplant.implanted_at.desc()).all())


def recall(name=None, lot=None, serial=None, manufacturer=None):
    """Which children have one of these — the recall list.

    *"There is a process for the recall of a patient who has an implantable
    device when necessary."* This is that process, and the only thing it has
    to do is be **complete and quick**.

    **Only what actually went in.** A planned implant that was never used is
    not in a child, and putting it on a recall list would send somebody to
    telephone a family about a device nobody implanted.

    Matching is partial and case-insensitive on the text fields, because a
    recall notice names a product the way the manufacturer writes it and the
    theatre wrote it the way it was on the box.
    """
    from app.models.theatre import OperationImplant

    q = (OperationImplant.query
         .join(Operation, OperationImplant.operation_id == Operation.id)
         .filter(OperationImplant.implanted_at.isnot(None)))
    for column, value in ((OperationImplant.name, name),
                          (OperationImplant.lot, lot),
                          (OperationImplant.serial, serial),
                          (OperationImplant.manufacturer, manufacturer)):
        text = (value or "").strip()
        if text:
            q = q.filter(column.ilike(f"%{text}%"))
    return q.order_by(OperationImplant.implanted_at.desc()).all()


def equipment_list_for(operation):
    """What this procedure says it needs, as a list of names.

    Read off the service the case was booked against. Empty when the clinic
    has not written one — and that is the ordinary state, not a gap to fill
    with a default: what a procedure needs in the room is the theatre's
    judgement and the program does not have one.
    """
    service = getattr(operation, "service", None)
    raw = (getattr(service, "equipment_list", None) or "")
    seen, out = set(), []
    for line in raw.splitlines():
        name = line.strip()[:120]
        # A list somebody pasted twice is one list.
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def equipment_for(operation):
    """The items recorded against this case, in list order."""
    if operation is None or getattr(operation, "id", None) is None:
        return []
    from app.models.theatre import OperationEquipment

    return (OperationEquipment.query
            .filter_by(operation_id=operation.id)
            .order_by(OperationEquipment.sort_order,
                      OperationEquipment.id).all())


def stock_equipment(operation):
    """Copy the procedure's list onto the case, once. Returns what is there.

    **Copied, not referenced**: editing the service's list next year must not
    rewrite what somebody checked in the room this morning. And it only ever
    adds what is missing by name, so a case that has been checked keeps its
    answers when somebody opens the screen again.
    """
    from app.models.theatre import OperationEquipment

    if operation is None or getattr(operation, "id", None) is None:
        return []
    have = {row.name for row in equipment_for(operation)}
    order = len(have)
    for name in equipment_list_for(operation):
        if name in have:
            continue
        db.session.add(OperationEquipment(operation_id=operation.id,
                                          name=name, sort_order=order))
        order += 1
    return equipment_for(operation)


def equipment_state(operation):
    """Where this case stands on its equipment — in one word.

    ``unasked`` · ``not_needed`` · ``none_named`` · ``checking`` · ``short`` ·
    ``ready``.

    ``short`` is deliberately one word for two errands — something is missing
    and something is broken — because at this level the answer is the same:
    do not call for the patient yet. *Which* item and *which* way is on the
    screen, where somebody can go and do something about it.

    ``checking`` is the state this program would have lost if the items were a
    boolean: a list copied onto the case that nobody has been through yet is
    not ready and is not short.
    """
    if operation is None or operation.equipment_needed is None:
        return "unasked"
    if not operation.equipment_needed:
        return "not_needed"
    rows = equipment_for(operation)
    if not rows:
        return "none_named"
    if any(r.state in ("missing", "broken") for r in rows):
        return "short"
    if any(r.state == "unchecked" for r in rows):
        return "checking"
    return "ready"


def equipment_ready(operation):
    """The one question somebody about to call for the patient is asking."""
    return equipment_state(operation) in ("not_needed", "ready")


def set_equipment_needed(operation, needed, user=None):
    """Record whether this case needs anything beyond what the room has.

    ``None`` is refused rather than read as no: on this question a blank is
    "nobody asked", and this program does not let one value carry two facts.
    """
    if operation is None or needed is None:
        return None
    operation.equipment_needed = bool(needed)
    if operation.equipment_needed:
        stock_equipment(operation)
    return operation


def add_equipment(operation, name, user=None):
    """Name one more thing this case needs. Returns the row, or ``None``.

    For the item the service's list does not carry — which is most theatres,
    most days. A blank name is refused; an empty row on a checklist is a line
    somebody ticks without reading.
    """
    from app.models.theatre import OperationEquipment

    if operation is None or getattr(operation, "id", None) is None:
        return None
    clean = (name or "").strip()[:120]
    if not clean:
        return None
    rows = equipment_for(operation)
    for row in rows:
        if row.name == clean:
            return row
    item = OperationEquipment(operation_id=operation.id, name=clean,
                              sort_order=len(rows))
    db.session.add(item)
    return item


def check_equipment(operation, answers, user=None, at=None):
    """Record what was found, item by item. Returns the operation.

    ``answers`` maps an item's id to ``present`` / ``working`` / ``note``.
    A thing that is not there **cannot be tested**, so its ``working`` is left
    unknown rather than written False — "it is here and broken" is a different
    finding and would send somebody on the wrong errand.
    """
    rows = {row.id: row for row in equipment_for(operation)}
    if operation is None or not rows:
        return None
    for item_id, answer in (answers or {}).items():
        row = rows.get(item_id)
        if row is None:
            continue
        present = answer.get("present")
        row.present = None if present is None else bool(present)
        if row.present:
            working = answer.get("working")
            row.working = None if working is None else bool(working)
        else:
            row.working = None
        row.note = (answer.get("note") or "").strip()[:160] or None
    operation.equipment_checked_by = getattr(user, "id", None)
    operation.equipment_checked_at = at or datetime.utcnow()
    return operation


def precautions_of(operation):
    """The precautions recorded for this case, as a list."""
    raw = (getattr(operation, "infection_precautions", None) or "")
    return [p for p in (x.strip() for x in raw.split(",")) if p]


def infection_state(operation):
    """What this case needs beyond what every case gets — in one word.

    ``unasked`` · ``standard`` · ``extra``.

    Three, and the first two are the pair that carries it. *Nobody asked* and
    *this case needs nothing beyond the usual* are not the same sentence, and
    on an infection question the difference is a theatre list drawn up in the
    wrong order by somebody who thought the question had been answered.

    ``extra`` is one word for three categories on purpose: the screen shows
    *which*, and a state is for reading across a list at a glance.
    """
    if operation is None:
        return "unasked"
    from app.models.theatre import EXTRA_PRECAUTIONS

    chosen = precautions_of(operation)
    if not chosen:
        return "unasked"
    if operation.infection_noted_by is None or operation.infection_noted_at is None:
        # Same rule as the site and the identity: an answer with nobody's name
        # against it is a note, not a verification.
        return "unasked"
    return "extra" if any(p in EXTRA_PRECAUTIONS for p in chosen) else "standard"


def note_precautions(operation, chosen, note=None, empiric=False, user=None,
                     at=None):
    """Record what this case needs. Returns the operation, or ``None``.

    Refused when nothing recognisable was chosen, for the reason
    :func:`mark_site` refuses a free-typed side. And ``standard`` is dropped
    the moment a transmission-based precaution is named beside it: standard
    precautions are in force on every case anyway, so "standard **and**
    contact" says nothing "contact" does not already say, and a list carrying
    both reads as a case somebody could not make up their mind about.
    """
    from app.models.theatre import EXTRA_PRECAUTIONS, PRECAUTIONS

    if operation is None:
        return None
    keep = [p for p in PRECAUTIONS if p in set(chosen or ())]
    if not keep:
        return None
    extra = [p for p in keep if p in EXTRA_PRECAUTIONS]
    keep = extra or ["standard"]
    operation.infection_precautions = ",".join(keep)
    operation.infection_note = (note or "").strip()[:160] or None
    # A case needing nothing extra is not waiting on a diagnosis, so the flag
    # has no meaning there and carrying it would leave a stale yes behind
    # somebody's changed answer.
    operation.infection_empiric = bool(empiric) if extra else None
    operation.infection_noted_by = getattr(user, "id", None)
    operation.infection_noted_at = at or datetime.utcnow()
    return operation


def precaution_cases(day=None):
    """Today's cases that need more than the usual, in list order.

    This is the one place the answer does work rather than being filed:
    whoever draws up the order of the list needs to know before they draw it
    up, and the room is turned over differently afterwards.
    """
    when = day or local_today()
    rows = (Operation.query
            .filter(Operation.on_date == when,
                    Operation.status != "cancelled")
            .order_by(Operation.start_time, Operation.id).all())
    return [r for r in rows if infection_state(r) == "extra"]


def workup_orders(operation, kind=None):
    """The investigations this case is waiting on, oldest first.

    Only the ones somebody attached to this case. Never "everything
    outstanding on the child's file" — a ferritin ordered last month would
    then hold up this morning's appendix.
    """
    if operation is None or getattr(operation, "id", None) is None:
        return []
    from app.models.visit import VisitInvestigation

    q = VisitInvestigation.query.filter_by(operation_id=operation.id)
    if kind:
        q = q.filter(VisitInvestigation.kind == kind)
    return q.order_by(VisitInvestigation.id).all()


def workup_state(operation, kind=None):
    """Where this case stands on its investigations — in one word.

    ``unasked`` · ``not_needed`` · ``none_named`` · ``waiting`` · ``ready``.

    Five, and every one of them is a different sentence at the theatre door:

    * ``unasked`` — nobody has said whether this case waits on anything. The
      state of every case booked before the column existed, and **not** the
      same as needing nothing.
    * ``not_needed`` — somebody considered it and the answer is no. A healthy
      five-year-old's tonsillectomy, most mornings.
    * ``none_named`` — somebody said yes and named nothing. Half an answer,
      and it has to look like one rather than pass as ready.
    * ``waiting`` — an order is attached and its result is not back.
    * ``ready`` — every attached order has a result.

    ``kind`` narrows it to ``lab`` or ``imaging``; the imaging answer is what
    the checklist's «الأشعة معروضة» item reads.
    """
    if operation is None:
        return "unasked"
    if operation.workup_needed is None:
        return "unasked"
    if not operation.workup_needed:
        return "not_needed"
    rows = workup_orders(operation, kind=kind)
    if not rows:
        return "none_named"
    return "ready" if all(r.has_result for r in rows) else "waiting"


def imaging_ok(operation):
    """The one question the checklist's imaging item asks.

    **Ticked unless there is an actual gap.** The WHO item asks whether the
    essential imaging is up; a case with no imaging attached has nothing to
    display and the honest answer is yes — the same way a procedure with no
    side counts as marked. Refusing until somebody answered the workup
    question would paint a red item on every appendicectomy in the country and
    teach people to stop reading the colour.

    So it only *withholds* the tick where the tick would be a lie: imaging was
    ordered for this case and the result is not back.
    """
    return workup_state(operation, kind="imaging") in (
        "unasked", "not_needed", "none_named", "ready")


def set_workup(operation, needed, user=None):
    """Record whether this case waits on investigations at all.

    Blank is not an answer and the caller must not turn one into ``False`` —
    see :func:`workup_state`.
    """
    if operation is None or needed is None:
        return None
    operation.workup_needed = bool(needed)
    return operation


def link_investigation(operation, order):
    """Attach one order to this case. Returns it, or ``None``.

    Refuses an order belonging to another child: an investigation attached
    across patients would put somebody else's result in front of the person
    deciding whether this child is ready.
    """
    if operation is None or order is None:
        return None
    if order.patient_id != operation.patient_id:
        return None
    order.operation_id = operation.id
    # Attaching one *is* the answer to "does this case wait on anything" —
    # leaving the flag NULL beside an attached order would have the screen say
    # nobody asked while an order sits there waiting.
    if operation.workup_needed is None:
        operation.workup_needed = True
    return order


def unlink_investigation(order):
    """Detach an order from its case. The order itself is never deleted — it
    is a real request somebody made, and the wrong case is not a reason to
    lose it."""
    if order is None:
        return None
    order.operation_id = None
    return order


def workup_choices(operation):
    """This child's orders that could be attached to this case, newest first.

    Everything of theirs not already attached to **another** case, results and
    all: whoever is attaching has to be able to see that the result they were
    about to rely on is not back yet, and a list of only unresulted orders
    would hide the ones already answered.
    """
    if operation is None or operation.patient_id is None:
        return []
    from app.models.visit import VisitInvestigation

    rows = (VisitInvestigation.query
            .filter_by(patient_id=operation.patient_id)
            .order_by(VisitInvestigation.id.desc()).all())
    return [r for r in rows
            if r.operation_id in (None, operation.id)]


def blood_state(operation):
    """Where this case stands on blood — in one word.

    ``unasked`` · ``not_needed`` · ``ordered`` · ``reserved``, and the first
    two are the pair that matters: *nobody asked* and *none needed* are not
    the same sentence, and on this question the difference is a child
    bleeding while somebody telephones.
    """
    if operation is None or operation.blood_needed is None:
        return "unasked"
    if not operation.blood_needed:
        return "not_needed"
    return "reserved" if operation.blood_reserved_at else "ordered"


def set_blood(operation, needed, units=None, reserved=False, user=None):
    """Record the surgeon's answer, and the bank's.

    Two acts through one door, because they are two halves of one row — but
    kept apart in what they mean: saying blood is needed does not reserve it,
    and the screen shows ``ordered`` until somebody says it is in the fridge.
    """
    if operation is None:
        return None
    operation.blood_needed = None if needed is None else bool(needed)
    operation.blood_units = int(units) if units else None
    if operation.blood_needed and reserved:
        operation.blood_reserved_at = datetime.utcnow()
        operation.blood_reserved_by = getattr(user, "id", None)
    else:
        # Un-saying it clears the confirmation: a reservation that outlived
        # the decision it was made for is a reservation nobody checked.
        operation.blood_reserved_at = None
        operation.blood_reserved_by = None
    return operation


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


def derived_items():
    """The checklist items answered from the record, each with the question it
    asks. Written as one mapping because it was four near-identical blocks,
    and because **being derived is a fact other code needs to ask about**.

    It has already cost three separate afternoons: every time one of these
    stopped being an ordinary box, tests elsewhere that were using it as a
    *generic tickable item* — to check that signing stores what was ticked, or
    that re-signing updates one row — failed and had to be moved onto a box
    that really is ordinary. There is no way to make that not happen; what
    this does is put the list in one place so the next person can read it
    instead of discovering it from a red suite.

    The ordinary items on the sign-in, for anybody needing one: ``allergy``,
    ``airway``, ``pulse_oximeter``.
    """
    return {
        # *«بند الموافقة في الـ checklist بيتعلّم بالإيد حتى لو مفيش إقرار
        # متسجّل»* — the one this pattern started with.
        CONSENT_ITEM: consent_ok,
        # The assessment the standard asks for immediately before induction
        # (SAS.16 EOC 5). A tick is not an assessment.
        ANAESTHESIA_ITEM: pre_induction_ok,
        # Which side (SAS.06 د) — the never-event.
        SITE_ITEM: site_ok,
        # Which child, and the procedure (SAS.06 أ) — its other half.
        IDENTITY_ITEM: identity_ok,
        # Whether the imaging this case waits on is actually back
        # (SAS.06 هـ). The only one of the five that ticks when nothing is
        # recorded: a case with no imaging has none to display. See
        # :func:`imaging_ok`.
        IMAGING_ITEM: imaging_ok,
    }


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

    # **These four are read, never taken.** Each one replaced a box somebody
    # could tick on the way past, and the derivation runs in both directions:
    # ticked when the record says so even if nobody thought to tick it, and
    # dropped when it does not, however firmly somebody did.
    #
    # It refuses nothing. A hospital may proceed and this program records
    # rather than blocks — the gap then shows in ``missed``, as a finding
    # instead of a green tick.
    for item, answered in derived_items().items():
        if item in known:
            confirmed = [i for i in confirmed if i != item]
            if answered(operation):
                confirmed.append(item)

    row = operation.check_for(stop)
    if row is None:
        row = SafetyCheck(operation_id=operation.id, stop=stop)
        db.session.add(row)
    row.at = at or datetime.utcnow()
    row.by_id = getattr(user, "id", None)
    row.confirmed = ",".join(confirmed)
    row.note = (note or "").strip()[:255] or None
    return row


#: The chain of moments a theatre day is measured by, in order, with the
#: column each one lives in. **Quoted at both ends**: SAS.02's fifth item of
#: evidence says the clock runs *"starting with the patient's call and ending
#: with the room being cleaned after the procedure"*.
#:
#: Held as data rather than five hand-written blocks because every screen that
#: shows punctuality wants the same list, and because a sixth moment should be
#: one line here and not a sixth place to forget.
TIMELINE = (
    ("called", "called_at"),
    ("started", "started_at"),
    ("finished", "finished_at"),
    ("recovery", "recovery_at"),
    ("cleaned", "cleaned_at"),
)


def timeline(operation):
    """The moments this case has, in order, with the gap to the one before.

    Returns a list of ``{"step", "at", "minutes"}``. ``minutes`` is the wait
    since the **previous recorded** moment, not the previous one in the list:
    a case whose recovery was never stamped still shows an honest gap between
    finishing and the room being cleaned, instead of a blank that reads as
    instant.

    ``None`` for a moment that never happened — and it stays in the list. A
    chain that silently drops what nobody recorded is a chain that always
    looks complete, which is the opposite of what a punctuality record is for.
    """
    if operation is None:
        return []
    out, previous = [], None
    for step, column in TIMELINE:
        at = getattr(operation, column, None)
        minutes = None
        if at and previous:
            minutes = int((at - previous).total_seconds() // 60)
        out.append({"step": step, "at": at, "minutes": minutes})
        if at:
            previous = at
    return out


def waited_minutes(operation):
    """From the call to the knife — the number a theatre list is run on.

    ``None`` when either end is missing, because a wait with one end is not a
    shorter wait, it is an unknown one.
    """
    if operation is None or not operation.called_at or not operation.started_at:
        return None
    return int((operation.started_at - operation.called_at).total_seconds() // 60)


def turnover_minutes(operation):
    """From the case finishing to the room being ready — what the next case
    waits on, and the moment nobody records because it happens after everybody
    has moved on."""
    if operation is None or not operation.finished_at or not operation.cleaned_at:
        return None
    return int((operation.cleaned_at - operation.finished_at).total_seconds() // 60)


# ------------------------------------------ how long it was meant to take --
#
# SAS.02 (ب) asks that a booking *"specify the start time and end time for
# surgery based on the international surgery times"*, and the standard's third
# item of evidence asks for a process for booking elective procedures *"and
# determining the needed time for each procedure"*.
#
# **The program holds no table of surgery times, and will not invent one.**
# "International surgery times" is a reference this program does not have —
# the same rule that keeps invented vaccine thresholds out of the code. So the
# clinic writes the number it works to, once, on the procedure
# (``Service.duration_minutes``); the booking offers it; the end time is
# derived from the start; and the planned length is shown beside the actual
# one.
#
# **It measures, it does not judge.** No "ran late", no target, no red. A
# theatre that can see its own two numbers can decide for itself which of its
# cases are booked wrong — and a program that decided that for them would be
# deciding it from a reference it does not hold.


def expected_minutes(service):
    """How long this procedure usually needs, as the clinic wrote it.

    ``Service.duration_minutes`` — **the column that was already there.** It
    has had an edit box on the price list since long before this standard was
    read, and nothing read it. A second "how long does this take" column
    beside it would have made the answer depend on which of two screens
    somebody had filled in.

    ``None`` where nobody wrote one, and ``None`` for a zero: a procedure
    that takes no time is not something anybody meant, and letting it through
    would prefill every booking of it with nothing and call that an answer.
    """
    minutes = getattr(service, "duration_minutes", None)
    return minutes if minutes and minutes > 0 else None


def planned_end(operation):
    """The time the list says this case will be finished by, or ``None``.

    **Derived, not a second column.** The booking already carries a start and
    a length, and storing the end as well means a case moved half an hour
    later keeps an end time that belongs to where it used to be.

    A case running past midnight gives the wall-clock time, not tomorrow's
    date: this is what prints on a theatre list, and the list carries its own
    date at the top.

    **Minutes, not a ``datetime``.** Written first as ``datetime.combine`` with
    a placeholder date, which is how every local-date-read-as-UTC bug in this
    program has started — and the repo-wide guard in
    ``tests/test_a_shift_that_lands_on_the_wrong_day.py`` said so. It was a
    false alarm in substance (nothing here is compared against a stored UTC
    column) and a true one in shape, so the date is gone rather than excused:
    an end time has no date, and arithmetic that never builds one cannot get
    the day wrong.
    """
    if operation is None or not operation.start_time or not operation.minutes:
        return None
    started = operation.start_time
    total = started.hour * 60 + started.minute + operation.minutes
    return time((total // 60) % 24, total % 60)


def actual_minutes(operation):
    """Knife to close, or ``None`` — and ``None`` is *unknown*, not short.

    Read off the two stamps the theatre already makes when a case starts and
    finishes, so the measurement costs nobody a keystroke.
    """
    if operation is None or not operation.started_at or not operation.finished_at:
        return None
    return int((operation.finished_at
                - operation.started_at).total_seconds() // 60)


def time_plan(operation):
    """Planned against actual for one case.

    ``{"start", "end", "planned", "usual", "actual", "difference"}``.

    ``planned`` is what this booking was given, ``usual`` what the procedure
    is normally given, and they are kept apart on purpose: a case booked at
    half the clinic's own usual length is visible *before* the morning it
    overruns, and only two separate numbers can show that.

    ``difference`` is **actual minus planned**, signed. A case that finished
    twenty minutes early is as much a booking worth looking at as one that ran
    twenty minutes over, and an unsigned "overrun" would hide half of them.
    It is ``None`` unless both numbers exist — a difference measured from a
    number nobody wrote is not a small difference, it is no difference at all.
    """
    if operation is None:
        return {"start": None, "end": None, "planned": None, "usual": None,
                "actual": None, "difference": None}
    booked = operation.minutes if (operation.minutes or 0) > 0 else None
    done = actual_minutes(operation)
    return {
        "start": operation.start_time,
        "end": planned_end(operation),
        "planned": booked,
        "usual": expected_minutes(operation.service),
        "actual": done,
        "difference": None if booked is None or done is None else done - booked,
    }


def call_patient(operation, to=None, user=None, at=None):
    """Record that the child was called for. Returns the operation, or ``None``.

    SAS.02 (هـ). **Recorded once**: a second call is somebody chasing, not a
    new beginning, and moving the stamp would quietly shorten every wait this
    screen exists to measure.
    """
    if operation is None or operation.called_at:
        return None
    operation.called_at = at or datetime.utcnow()
    operation.called_by = getattr(user, "id", None)
    operation.called_to = (to or "").strip()[:120] or None
    return operation


def mark_cleaned(operation, user=None, at=None):
    """The room is ready for the next case.

    Refused before the case has finished: a room cleaned after an operation
    that has not happened is not a fact, and a stamp that can land in the wrong
    order makes every turnover figure computed from it wrong.
    """
    if operation is None or not operation.finished_at or operation.cleaned_at:
        return None
    operation.cleaned_at = at or datetime.utcnow()
    operation.cleaned_by = getattr(user, "id", None)
    return operation


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


# --------------------------------------- postponed is not cancelled -------
#
# SAS.02's fourth item of evidence: *"There is a process for analyzing
# **postponed and canceled** procedures, and action is taken to improve
# them."* It names two things, and they are two different problems. A theatre
# with thirty postponements and two cancellations is booking badly; one with
# two postponements and thirty cancellations is losing its cases. A single
# "called off" count answers neither of them.
#
# **A postponement is a cancellation that has a successor**, and that is the
# whole mechanism. No fifth status: ``status`` is read by name in this
# codebase — the billing query, ``is_open`` — and a new word there would
# quietly change what every one of those places means.


def postpone(operation, to_date, reason=None, user=None, **extra):
    """Move this case to another day: called off here, booked there, linked.

    Returns the new case, or ``None`` where there was nothing open to move —
    a case already done, or already called off once. Raises ``ValueError``
    with no date, because a postponement to nowhere is a cancellation and the
    two must not be the same button.

    The replacement carries the old case's room, surgeon, anaesthetist,
    service, length, kind and team: a postponed case is the *same* case on
    another day, and retyping it is how the second booking quietly ends up
    different from the first. All of it stays correctable afterwards.
    """
    if operation is None or not operation.is_open:
        return None
    if to_date is None:
        raise ValueError("no date")
    replacement = book(
        operation.patient, operation.theatre, operation.procedure,
        on_date=to_date, user=user,
        admission_id=operation.admission_id,
        service_id=operation.service_id,
        surgeon_id=operation.surgeon_id,
        anaesthetist_id=operation.anaesthetist_id,
        start_time=operation.start_time,
        minutes=operation.minutes,
        case_type=operation.case_type,
        team=operation.team,
        **extra)
    # Flushed for its id: the link is the only thing that tells a postponement
    # from a cancellation, and a link written to ``None`` would file every
    # moved case under "lost".
    db.session.flush()
    cancel(operation, reason=reason, user=user)
    operation.postponed_to_id = replacement.id
    return replacement


def _in_period(query, start=None, end=None):
    """Narrow to the days a theatre list was read on. Either end may be open."""
    if start is not None:
        query = query.filter(Operation.on_date >= start)
    if end is not None:
        query = query.filter(Operation.on_date <= end)
    return query


def call_offs(start=None, end=None):
    """Every case called off in a period, most recent first.

    Counted on **the day it was meant to happen**, not the day somebody
    pressed cancel: the day the theatre lost is the day its list had a hole
    in it, and a case cancelled in March off an April list is April's hole.
    """
    return (_in_period(Operation.query.filter(Operation.status == "cancelled"),
                       start, end)
            .order_by(Operation.on_date.desc(), Operation.id.desc())
            .all())


def calloff_analysis(start=None, end=None):
    """Postponed against cancelled, and why — SAS.02's fourth evidence item.

    Returns ``{"postponed", "cancelled", "booked", "reasons"}``, where each
    row of ``reasons`` is ``{"reason", "postponed", "cancelled", "total"}``,
    commonest first.

    **Grouped by the reason exactly as it was written.** The program ships no
    list of cancellation reasons and invents none, so two spellings stay two
    rows: deciding that «الطفل بيكح» and «عدوى صدر» are one thing is a
    judgement about this clinic's own words, and only this clinic can make it.

    **A case called off with nothing written gets its own row**, keyed
    ``None``. It is not "other". A theatre where half the call-offs carry no
    reason cannot improve anything at all, and that is the first finding this
    screen has to be able to put on a page.

    ``booked`` is every case the period had, called-off ones included — a
    count of call-offs with no denominator is a number that grows with the
    theatre and means nothing on its own.
    """
    totals = {"postponed": 0, "cancelled": 0}
    reasons = {}
    for row in call_offs(start, end):
        kind = row.called_off_as
        totals[kind] += 1
        bucket = reasons.setdefault(
            row.cancel_reason,
            {"reason": row.cancel_reason, "postponed": 0, "cancelled": 0,
             "total": 0})
        bucket[kind] += 1
        bucket["total"] += 1
    return {
        "postponed": totals["postponed"],
        "cancelled": totals["cancelled"],
        "booked": _in_period(Operation.query, start, end).count(),
        # Commonest first, then by the words themselves so a screen reloaded
        # twice reads the same way twice.
        "reasons": sorted(reasons.values(),
                          key=lambda r: (-r["total"], r["reason"] or "")),
    }


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
