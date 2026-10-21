"""The family's insurance card, as reception has to see it (CONTRACTS_PLAN.md ع-١).

Asked as *«بيانات الكارت الى بتبقى موجوده فى التسجيل … ويذكر الاستقبال انه
يراجع الحالة و تاريخ الانتهاء جه ومقدمش خدمه يحوله الى كاش او تعديل مثلاُ
تاريخ الانتهاء وتاريخ الانتاج بصورة مرفقة»*.

* **Where reception looks** — the booking, the day's board, the cashier — the
  card says what it is: valid, running out within :data:`SOON_DAYS`, run out,
  or the payer's own contract no longer in force.
* **A card that ran out needs a decision**, not a bill that turned to cash on
  its own: renew it (new dates, and the new card's picture), or bill this
  visit as cash — and who decided is kept on the bill.
* **A stay is judged on the day it began** (agreed with the clinic): a card
  that runs out on the fourth night of a stay that began while it was valid
  still covers the stay, as contracts usually read.
* **A renewal is a new card**; the old one stays, switched off, so a claim
  answered months later can be checked against the card it was billed on.
"""
from datetime import datetime, timedelta

from app.extensions import db

#: Reception is told this many days before a card runs out.
SOON_DAYS = 14
#: The states, in the order a screen worries about them.
VALID, SOON, EXPIRED, CONTRACT, NONE = "valid", "soon", "expired", "contract", "none"


def current_card(patient):
    """The card reception is talking about: the newest one still switched on
    (a renewed card is switched off), or ``None``."""
    cards = [c for c in getattr(patient, "coverages", []) or [] if c.is_active]
    if not cards:
        return None
    return sorted(cards, key=lambda c: (c.created_at or datetime.min, c.id), reverse=True)[0]


def card_on(patient, day):
    """The card that holds on ``day``, newest first, or ``None``."""
    cards = [c for c in getattr(patient, "coverages", []) or [] if c.is_valid_on(day)]
    if not cards:
        return None
    return sorted(cards, key=lambda c: (c.created_at or datetime.min, c.id), reverse=True)[0]


def billing_day(invoice):
    """The day a bill's cover is judged on: the stay's first day for a stay's
    bill, the bill's own day otherwise."""
    from app.utils.clock import local_date, local_today

    if getattr(invoice, "admission_id", None):
        from app.models import Admission

        adm = db.session.get(Admission, invoice.admission_id)
        if adm is not None and adm.admitted_at:
            return local_date(adm.admitted_at)
    return invoice.invoice_date or local_today()


def state(patient, on=None):
    """``{state, card, days_left, needs_decision}`` for reception.

    ``needs_decision`` — the family has a card, none of its cards holds today,
    so the bill is either a renewal away or a decision to bill cash.
    """
    from app.utils.clock import local_today

    on = on or local_today()
    card = current_card(patient)
    if card is None:
        return {"state": NONE, "card": None, "days_left": None, "needs_decision": False}
    holding = card_on(patient, on)
    if holding is not None:
        payer = holding.payer
        if payer is not None and payer.contracts and payer.active_contract(on) is None:
            return {"state": CONTRACT, "card": holding, "days_left": None, "needs_decision": True}
        days = (holding.expiry_date - on).days if holding.expiry_date else None
        soon = days is not None and days <= SOON_DAYS
        return {"state": SOON if soon else VALID, "card": holding, "days_left": days,
                "needs_decision": False}
    days = (card.expiry_date - on).days if card.expiry_date else None
    return {"state": EXPIRED, "card": card, "days_left": days, "needs_decision": True}


def states_for(patient_ids, on=None):
    """``{patient_id: state}`` for a board, in one query — only for the
    children that have a card at all."""
    from app.models import PatientCoverage, Patient
    from sqlalchemy.orm import selectinload

    ids = [i for i in set(patient_ids or []) if i]
    if not ids:
        return {}
    have = {pid for (pid,) in db.session.query(PatientCoverage.patient_id)
            .filter(PatientCoverage.patient_id.in_(ids)).distinct().all()}
    if not have:
        return {}
    patients = (Patient.query.options(selectinload(Patient.coverages))
                .filter(Patient.id.in_(have)).all())
    return {p.id: state(p, on) for p in patients}


def expiring(within=SOON_DAYS, on=None):
    """The current cards that run out within ``within`` days, or ran out in
    the last month and were not renewed — soonest first. For the list
    reception calls the families from."""
    from app.models import PatientCoverage
    from app.utils.clock import local_today

    on = on or local_today()
    rows = (PatientCoverage.query
            .filter(PatientCoverage.is_active.is_(True),
                    PatientCoverage.expiry_date.isnot(None),
                    PatientCoverage.expiry_date <= on + timedelta(days=within),
                    PatientCoverage.expiry_date >= on - timedelta(days=30))
            .order_by(PatientCoverage.expiry_date).all())
    out = []
    for c in rows:
        if c.patient is None or current_card(c.patient) is not c:
            continue
        out.append({"card": c, "patient": c.patient, "days_left": (c.expiry_date - on).days})
    return out


class CardError(ValueError):
    """A refusal with a locale key (``card.err_<key>``)."""


def _day(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def details_from(form):
    """The card's own words from a form — the same boxes on «add» and «renew»."""
    def text(name, limit):
        return (form.get(name) or "").strip()[:limit] or None

    return {"membership_number": text("membership_number", 60),
            "issue_date": _day(form.get("issue_date")),
            "expiry_date": _day(form.get("expiry_date")),
            "plan_name": text("plan_name", 80),
            "holder_name": text("holder_name", 120),
            "holder_relation": text("holder_relation", 30)}


def save_pictures(card, files, required=False):
    """The card's front and back. ``required`` — a renewal needs the front."""
    from app.utils.uploads import save_document

    front = files.get("card_front") if files else None
    back = files.get("card_back") if files else None
    if required and not (front and front.filename):
        raise CardError("photo")
    for name, upload in (("card_front", front), ("card_back", back)):
        if upload and upload.filename:
            stored = save_document(upload)
            if stored is None:
                raise CardError("bad_photo")
            setattr(card, name, stored)


def renew(card, form, files, user):
    """A new card in place of ``card``: new dates and the new card's picture.
    The old one is switched off and kept. Returns the new card."""
    from app.models import PatientCoverage

    details = details_from(form)
    if details["expiry_date"] is None:
        raise CardError("expiry")
    if details["issue_date"] and details["issue_date"] > details["expiry_date"]:
        raise CardError("dates")
    new = PatientCoverage(patient_id=card.patient_id, payer_id=card.payer_id, is_active=True,
                          renewed_from_id=card.id, renewed_by=getattr(user, "id", None))
    for key, value in details.items():
        setattr(new, key, value)
    # What the renewal form left empty is the old card's.
    for key in ("membership_number", "plan_name", "holder_name", "holder_relation"):
        if getattr(new, key) is None:
            setattr(new, key, getattr(card, key))
    save_pictures(new, files, required=True)
    card.is_active = False
    db.session.add(new)
    db.session.flush()
    return new


def decide_cash(invoice, user):
    """This bill is cash although the family has a card: who and when."""
    invoice.coverage_decision = "cash"
    invoice.coverage_decided_by = getattr(user, "id", None)
    invoice.coverage_decided_at = datetime.utcnow()


def history(patient):
    """Every card the child has had, newest first — renewals included."""
    cards = list(getattr(patient, "coverages", []) or [])
    return sorted(cards, key=lambda c: (c.created_at or datetime.min, c.id), reverse=True)
