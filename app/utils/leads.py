"""Families who asked and have not come yet — the rules, in one place.

``CONNECTHUB_PLAN.md``, stage one. The screens only ask; everything that
decides is here:

* **a contact is found by an identity, never by a name** — a phone, an
  e-mail, a handle. Two people with one name stay two people, and an
  identity that already belongs to somebody is never moved onto somebody
  else;
* **one open lead per contact**: the same family asking again on another
  channel is a step on the lead they already have, not a second one to
  chase;
* **"not completed" says why**, from a short list a manager can count;
* **"converted" is not a button.** It is what happens when a booking request
  is actually made from the lead — through the same queue, the same card and
  the same approval as every other request — and a request needs a number
  to call back, so a lead with only a handle is asked for one first;
* **a file is linked by a person**, with who and when — the inbox's rule for
  a number, kept for every channel;
* every step is a line on the lead (``LeadEvent``).

Nothing here writes to the family, and nothing says a time is booked.
"""
from datetime import datetime, timedelta
from statistics import median

from app.extensions import db
from app.models import (ActivityLog, BookingRequest, Contact, ContactIdentity,
                        Lead, LeadEvent)
from app.models.booking_request import REQUEST_SOURCES
from app.models.crm import (IDENTITY_KINDS, LOST_REASONS, MANUAL_STAGES,
                            OPEN_STAGES, SOURCE_KINDS)
from app.utils import channels

NAME_MAX = 120
NOTE_MAX = 255
REPORT_PERIODS = (30, 90, 365)


# ------------------------------------------------------------- contacts ---
def _clean_identities(identities):
    """``{kind: raw}`` → ``[(kind, value, shown)]``, usable ones only, in the
    registry's order (a phone is the strongest proof, so it is tried first)."""
    out = []
    for kind in IDENTITY_KINDS:
        raw = (identities or {}).get(kind)
        value = channels.identity_value(kind, raw)
        if value:
            out.append((kind, value, (raw or "").strip()[:160]))
    return out


def find_contact(identities):
    """The contact one of these identities already belongs to, or ``None``.
    Names are not looked at."""
    for kind, value, _ in _clean_identities(identities):
        row = ContactIdentity.query.filter_by(kind=kind, value=value).first()
        if row is not None:
            return row.contact
    return None


def contact_for(name, identities, user=None):
    """Find the contact by identity, or make one. Identities they did not
    have yet are added — unless another contact already holds them, which is
    left alone: one number on two people is for a person to sort out, not
    for the program to decide."""
    clean = _clean_identities(identities)
    contact = find_contact(identities)
    if contact is None:
        contact = Contact(name=(name or "").strip()[:NAME_MAX] or "—",
                          created_by=getattr(user, "id", None))
        db.session.add(contact)
        db.session.flush()
    for kind, value, shown in clean:
        taken = ContactIdentity.query.filter_by(kind=kind, value=value).first()
        if taken is None:
            # Through the relationship, so a contact already in hand sees
            # the new way to reach them at once.
            contact.identities.append(ContactIdentity(kind=kind, value=value,
                                                      shown=shown))
    db.session.flush()
    return contact


def link_patient(contact, patient, user, ip_address=None):
    """A person says this contact is this child's family."""
    contact.patient_id = patient.id
    contact.linked_by = getattr(user, "id", None)
    contact.linked_at = datetime.utcnow()
    ActivityLog.record("crm.link_patient", user_id=contact.linked_by,
                       entity="crm_contact", entity_id=contact.id,
                       detail=f"patient {patient.id}", ip_address=ip_address)
    for lead in contact.leads:
        if lead.is_open:
            _event(lead, "linked", patient.display_name(), user)
    return contact


def suggestions(contact):
    """Children reachable on the contact's number — for a person to choose
    from. Nothing is linked by this."""
    from app.utils.inbox import match_patients

    if contact.patient_id or not contact.phone:
        return []
    return match_patients(contact.phone)


# ---------------------------------------------------------------- leads ---
def _event(lead, kind, detail, user):
    db.session.add(LeadEvent(lead_id=lead.id, kind=kind,
                             detail=(detail or "")[:NOTE_MAX] or None,
                             user_id=getattr(user, "id", None),
                             at=datetime.utcnow()))


def open_lead_of(contact):
    return (Lead.query.filter(Lead.contact_id == contact.id,
                              Lead.stage.in_(OPEN_STAGES))
            .order_by(Lead.id.desc()).first())


def open_lead(user, name, identities, channel, source_kind="message",
              campaign=None, source_url=None, doctor_id=None, interest=None,
              message=None, owner_id=None, follow_up_on=None,
              conversation_key=None, patient=None):
    """Write down somebody who asked. Returns ``(lead, created)`` — the
    family's open lead when they already have one. Raises ``ValueError``
    when there is nobody to get back to: no name, or no way to reach them."""
    name = (name or "").strip()
    if patient is not None and not name:
        name = patient.display_name()
    if not name or not (_clean_identities(identities) or patient is not None):
        raise ValueError("who")
    if channel not in channels.CHANNELS:
        raise ValueError("channel")
    contact = contact_for(name, identities, user)
    if patient is not None and contact.patient_id is None:
        # Taken from a conversation the inbox had already put on this
        # child's file — a person made that link; it is carried, not guessed.
        link_patient(contact, patient, user)
    campaign = channels.clean_tag(campaign)
    lead = open_lead_of(contact)
    if lead is not None:
        _event(lead, "again", " · ".join(filter(None, [
            channel, campaign, (message or "").strip()[:120]])), user)
        if message and not lead.message:
            lead.message = message.strip()
        return lead, False
    now = datetime.utcnow()
    lead = Lead(contact_id=contact.id, stage="new", channel=channel,
                source_kind=(source_kind if source_kind in SOURCE_KINDS
                             else "other"),
                campaign=campaign,
                source_url=(source_url or "").strip()[:300] or None,
                doctor_id=doctor_id or None,
                interest=(interest or "").strip()[:200] or None,
                message=(message or "").strip() or None,
                owner_id=owner_id or None, follow_up_on=follow_up_on,
                conversation_key=(conversation_key or "").strip()[:64] or None,
                created_by=getattr(user, "id", None), created_at=now,
                stage_at=now)
    db.session.add(lead)
    db.session.flush()
    _event(lead, "opened", " · ".join(filter(None, [channel, campaign])), user)
    return lead, True


def move(lead, stage, user, reason=None, note=None):
    """Move a lead by hand. ``None`` when nothing changed: a converted lead
    is finished, an unknown stage is refused, and "not completed" without a
    reason from the list is not saved."""
    if lead is None or lead.stage == "converted" or stage not in MANUAL_STAGES:
        return None
    if stage == "lost" and reason not in LOST_REASONS:
        return None
    if stage == lead.stage:
        return None
    now = datetime.utcnow()
    if lead.first_contact_at is None and stage != "new":
        lead.first_contact_at = now
    lead.stage = stage
    lead.stage_at = now
    lead.lost_reason = reason if stage == "lost" else None
    lead.closed_at = now if stage == "lost" else None
    # Keys, not words: the screen says them in the reader's language.
    _event(lead, "stage", f"lost:{reason}" if stage == "lost" else stage,
           user)
    if (note or "").strip():
        _event(lead, "note", note.strip(), user)
    return lead


def assign(lead, owner, user):
    lead.owner_id = getattr(owner, "id", None)
    _event(lead, "owner", owner.display_name() if owner else "—", user)
    return lead


def follow_up(lead, on, user):
    lead.follow_up_on = on
    _event(lead, "follow_up", on.isoformat() if on else "—", user)
    return lead


def note(lead, text, user):
    text = (text or "").strip()
    if not text:
        return None
    _event(lead, "note", text, user)
    return lead


def _request_source(channel):
    return channel if channel in REQUEST_SOURCES else "desk"


def convert(lead, user, doctor_id=None, wanted_date=None, appt_type=None,
            message=None, ip_address=None, source=None):
    """Make the booking request — the one way a lead becomes "converted".
    Raises ``ValueError("phone")`` when there is no child on file and no
    number to call back, and ``ValueError("closed")`` on a lead that is not
    open."""
    from app.utils import booking_requests

    if lead is None or not lead.is_open:
        raise ValueError("closed")
    contact = lead.contact
    if not contact.patient_id and not contact.phone:
        raise ValueError("phone")
    row = booking_requests.take(
        user, patient_id=contact.patient_id,
        contact_name=contact.name, contact_phone=contact.phone,
        doctor_id=doctor_id or lead.doctor_id, wanted_date=wanted_date,
        appt_type=appt_type, message=message or lead.message,
        source=source or _request_source(lead.channel),
        ip_address=ip_address, conversation_key=lead.conversation_key,
        lead_id=lead.id, campaign=lead.campaign)
    now = datetime.utcnow()
    lead.booking_request_id = row.id
    lead.stage = "converted"
    lead.stage_at = now
    lead.closed_at = now
    if lead.first_contact_at is None and user is not None:
        lead.first_contact_at = now
    _event(lead, "converted", f"#{row.id}", user)
    return row


def take_from_page(name, phone, child, message, tag=None, doctor_id=None,
                   wanted_date=None, ip_address=None):
    """A request written by the family on the public page: a contact by the
    number they gave, a lead with the campaign that brought them, and a
    booking request in the ordinary queue. Raises ``ValueError("who")``
    without a name and a usable number. Confirms nothing."""
    name = (name or "").strip()[:NAME_MAX]
    if not name or not channels.identity_value("phone", phone):
        raise ValueError("who")
    tag = channels.clean_tag(tag)
    said = "\n".join(filter(None, [
        f"👶 {child.strip()[:120]}" if (child or "").strip() else None,
        (message or "").strip()[:2000] or None]))
    lead, _ = open_lead(None, name, {"phone": phone},
                        channels.channel_of_tag(tag), source_kind="form",
                        campaign=tag, doctor_id=doctor_id, message=said)
    return convert(lead, None, doctor_id=doctor_id, wanted_date=wanted_date,
                   message=said or None, ip_address=ip_address,
                   source="page")


# ---------------------------------------------------------------- board ---
def board(stage=None, channel=None, owner_id=None, due_only=False,
          today=None, limit=300):
    """The leads to show, open ones first: an overdue follow-up on top, then
    the oldest untouched."""
    from app.utils.clock import local_today

    today = today or local_today()
    q = Lead.query
    if stage == "open" or not stage:
        q = q.filter(Lead.stage.in_(OPEN_STAGES))
    elif stage in ("converted", "lost", *OPEN_STAGES):
        q = q.filter(Lead.stage == stage)
    if channel in channels.CHANNELS:
        q = q.filter(Lead.channel == channel)
    if owner_id:
        q = q.filter(Lead.owner_id == owner_id)
    if due_only:
        q = q.filter(Lead.follow_up_on.isnot(None), Lead.follow_up_on <= today)
    rows = q.order_by(Lead.created_at.desc()).limit(limit).all()

    def key(lead):
        overdue = bool(lead.follow_up_on and lead.follow_up_on <= today
                       and lead.is_open)
        return (not overdue, lead.stage != "new", lead.created_at)
    if not stage or stage == "open":
        rows.sort(key=key)
    return rows


def counts():
    """How many leads stand at each stage."""
    rows = (db.session.query(Lead.stage, db.func.count(Lead.id))
            .group_by(Lead.stage).all())
    out = {s: 0 for s in ("new", "contacted", "interested", "waiting",
                          "converted", "lost")}
    out.update({s: n for s, n in rows})
    out["open"] = sum(out[s] for s in OPEN_STAGES)
    return out


def due_count(today=None):
    from app.utils.clock import local_today

    today = today or local_today()
    return (Lead.query.filter(Lead.stage.in_(OPEN_STAGES),
                              Lead.follow_up_on.isnot(None),
                              Lead.follow_up_on <= today).count())


def report(days=90, now=None):
    """Where the families came from, and what became of them: per channel
    and per campaign — how many asked, how many became a request, how many
    of those were booked, how many were not completed — and how long the
    first answer took (the median, in hours)."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    leads = Lead.query.filter(Lead.created_at >= since).all()
    booked_ids = set()
    req_ids = [lead.booking_request_id for lead in leads
               if lead.booking_request_id]
    if req_ids:
        booked_ids = {r.id for r in BookingRequest.query.filter(
            BookingRequest.id.in_(req_ids),
            BookingRequest.status == "booked").all()}

    def bucket(rows):
        total = len(rows)
        converted = sum(1 for x in rows if x.stage == "converted")
        return {"total": total, "converted": converted,
                "booked": sum(1 for x in rows
                              if x.booking_request_id in booked_ids),
                "lost": sum(1 for x in rows if x.stage == "lost"),
                "open": sum(1 for x in rows if x.is_open),
                "rate": round(100 * converted / total) if total else 0}

    by_channel, by_campaign = {}, {}
    for lead in leads:
        by_channel.setdefault(lead.channel, []).append(lead)
        if lead.campaign:
            by_campaign.setdefault(lead.campaign, []).append(lead)
    waits = [(x.first_contact_at - x.created_at).total_seconds() / 3600
             for x in leads if x.first_contact_at]
    lost = {}
    for lead in leads:
        if lead.stage == "lost" and lead.lost_reason:
            lost[lead.lost_reason] = lost.get(lead.lost_reason, 0) + 1
    channel_rows = sorted(((k, bucket(v)) for k, v in by_channel.items()),
                          key=lambda kv: -kv[1]["total"])
    campaign_rows = sorted(((k, bucket(v)) for k, v in by_campaign.items()),
                           key=lambda kv: -kv[1]["total"])
    return {"days": days, "all": bucket(leads), "channels": channel_rows,
            "campaigns": campaign_rows[:30],
            "lost": sorted(lost.items(), key=lambda kv: -kv[1]),
            "first_answer_hours": (round(median(waits), 1) if waits else None)}


__all__ = ["assign", "board", "contact_for", "convert", "counts",
           "due_count", "find_contact", "follow_up", "link_patient", "move",
           "note", "open_lead", "open_lead_of", "report", "suggestions",
           "take_from_page"]
