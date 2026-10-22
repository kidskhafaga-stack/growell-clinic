"""The family's insurance card, as reception has to see it (CONTRACTS_PLAN.md ع-١).

Asked as *«بيانات الكارت الى بتبقى موجوده فى التسجيل … ويذكر الاستقبال انه
يراجع الحالة و تاريخ الانتهاء جه ومقدمش خدمه يحوله الى كاش او تعديل مثلاُ
تاريخ الانتهاء وتاريخ الانتاج بصورة مرفقة»*.

* **Where reception looks** — the booking, the day's board, the cashier — the
  card says what it is: valid, running out within :data:`SOON_DAYS`, run out,
  or the payer's own contract no longer in force.
* **A card that ran out does not stop the family paying, and asks nobody for
  a decision** (*«انا مش عايز يبقى فيه كتير قرارات واسترجاع كتير»*): they pay
  cash and the bill is marked «waiting for the new card» for the clinic's
  :func:`wait_days`. When the new card is saved, every waiting bill it covers
  turns into a contract bill by itself, and what the family paid beyond their
  share goes to their own account (:func:`convert_waiting`) — one movement,
  handed back in cash from «رد الرصيد» only if they ask. A line the contract
  wants an approval for waits for it, and is credited when it is recorded.
  Past the wait, the bill is simply cash. «Cash for good» is there for a
  family that says they will not renew.
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
#: How long a bill paid in cash waits for the new card — the clinic's
#: setting, «المهلة» (blank: :data:`DEFAULT_WAIT_DAYS`; 0: no waiting).
WAIT_KEY = "card_wait_days"
DEFAULT_WAIT_DAYS = 30
#: ``Invoice.coverage_decision``.
WAITING, CASH, CONVERTED = "waiting", "cash", "converted"
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
    from app.models import Patient

    patient = db.session.get(Patient, card.patient_id)
    if waiting_bills(patient) and new.issue_date is None:
        # Which waiting bills the new card covers is decided by the day it
        # starts — a payer does not pay for a visit before its card.
        raise CardError("issue_needed")
    save_pictures(new, files, required=True)
    card.is_active = False
    db.session.add(new)
    db.session.flush()
    db.session.expire(patient, ["coverages"])
    new.converted = convert_waiting(patient, new, user)
    return new


# ------------------------------------------------------------ the wait ----
def wait_days():
    """The clinic's «المهلة»: how many days a cash bill waits for the new card."""
    from app.models import Setting

    raw = (Setting.get(WAIT_KEY, "") or "").strip()
    if not raw:
        return DEFAULT_WAIT_DAYS
    try:
        return max(0, min(int(raw), 365))
    except ValueError:
        return DEFAULT_WAIT_DAYS


def mark_waiting(invoice, user):
    """The family has a card that ran out and paid in cash: the bill waits
    for the new card — or is cash straight away when the clinic waits 0 days."""
    if wait_days() <= 0:
        decide_cash(invoice, user)
        return
    invoice.coverage_decision = WAITING
    invoice.coverage_decided_by = getattr(user, "id", None)
    invoice.coverage_decided_at = datetime.utcnow()


def close_stale(patient_id=None):
    """Bills whose wait ran out are cash, by themselves. Returns how many."""
    from app.models import Invoice

    limit = datetime.utcnow() - timedelta(days=wait_days())
    q = Invoice.query.filter(Invoice.coverage_decision == WAITING,
                             Invoice.coverage_decided_at < limit)
    if patient_id:
        q = q.filter(Invoice.patient_id == patient_id)
    rows = q.all()
    for inv in rows:
        inv.coverage_decision = CASH
    return len(rows)


def waiting_bills(patient):
    """This child's bills still waiting for the new card, oldest first."""
    from app.models import Invoice

    if patient is None:
        return []
    close_stale(patient.id)
    return (Invoice.query.filter(Invoice.patient_id == patient.id,
                                 Invoice.coverage_decision == WAITING,
                                 Invoice.status != "refunded")
            .order_by(Invoice.invoice_date, Invoice.id).all())


def all_waiting():
    """Every bill still waiting for a new card — for reception's list."""
    from app.models import Invoice

    close_stale()
    rows = (Invoice.query.filter(Invoice.coverage_decision == WAITING,
                                 Invoice.status != "refunded")
            .order_by(Invoice.invoice_date).all())
    days = wait_days()
    return [{"invoice": inv, "patient": inv.patient,
             "ends": (inv.coverage_decided_at + timedelta(days=days)).date()
             if inv.coverage_decided_at else None} for inv in rows]


def _named_share(item, disc):
    """What the bill's named (cash-category) discount gave this line, so it can
    be told apart from a discount somebody typed."""
    if disc is None or not disc.applies_to_line(item):
        return 0
    amount = disc.amount_for(item.gross)
    service = item.service
    if service is not None and service.max_discount:
        amount = min(amount, round(item.gross * service.max_discount / 100.0, 2))
    return max(round(amount, 2), 0)


def _snapshot(invoice):
    cols = lambda obj: {c.key: getattr(obj, c.key) for c in obj.__table__.columns}  # noqa: E731
    return cols(invoice), [(item, cols(item)) for item in invoice.items]


def _restore(invoice, snap):
    head, lines = snap
    for key, value in head.items():
        setattr(invoice, key, value)
    for item, values in lines:
        for key, value in values.items():
            setattr(item, key, value)


def convert_waiting(patient, card, user):
    """The new card is here: every bill waiting for it that falls inside the
    card's dates becomes a contract bill, and what the family paid beyond their
    share goes to their own account.

    * The bill's **cash-category discount** comes off the lines the payer
      covers (a family does not get the contract and the cash discount
      together) and stays on the lines it does not; a discount somebody typed
      is left alone, and its line stays cash.
    * A line the contract wants an **approval** for is not credited yet: the
      family's money for it waits for the approval, and the approvals desk
      credits it when the approval is recorded (``approvals.decide``).
    * A bill is **never left owing more**: if the contract's family share comes
      to more than they paid, the bill stays as it was and is reported.

    Returns ``{"converted": [(invoice, credited)], "kept": [(invoice, reason)]}``.
    """
    from app.models import NamedDiscount
    from app.utils import approvals, billing

    out = {"converted": [], "kept": []}
    payer = card.payer
    start = card.issue_date
    for inv in waiting_bills(patient):
        day = billing_day(inv)
        if (start and day < start) or (card.expiry_date and day > card.expiry_date):
            out["kept"].append((inv, "dates"))
            continue
        if payer is not None and payer.contracts and payer.active_contract(day) is None:
            out["kept"].append((inv, "contract"))
            continue
        snap = _snapshot(inv)
        disc = db.session.get(NamedDiscount, inv.discount_id) if inv.discount_id else None
        for item in inv.items:
            if (disc is not None and item.service is not None and (item.discount_value or 0) > 0
                    and not item.discount_is_percent
                    and abs(item.discount_value - _named_share(item, disc)) < 0.005
                    and payer is not None and payer.covers(item.service, item.gross, day) > 0):
                item.discount_value = 0
        inv.coverage_decision = None
        billing.apply_coverage(inv, patient)
        for item in inv.items:
            # Waiting for an approval: the family's money for this line waits
            # with it, rather than being handed back before the payer agrees.
            if item.approval_needed and item.cover_note != "awaiting_approval":
                item.discount_value = 0
                item.payer_amount = 0.0
                item.cover_note = "awaiting_approval"
        db.session.flush()
        if inv.payer_id is None:
            _restore(inv, snap)
            out["kept"].append((inv, "not_covered"))
            continue
        if inv.total > inv.paid + 0.009:
            _restore(inv, snap)
            out["kept"].append((inv, "would_owe"))
            continue
        credited = approvals.credit_surplus(inv, user, "بعد تجديد الكارت")
        inv.coverage_decision = CONVERTED
        inv.recalc_status()
        out["converted"].append((inv, credited))
    db.session.flush()
    return out


def decide_cash(invoice, user):
    """This bill is cash although the family has a card: who and when."""
    invoice.coverage_decision = "cash"
    invoice.coverage_decided_by = getattr(user, "id", None)
    invoice.coverage_decided_at = datetime.utcnow()


def history(patient):
    """Every card the child has had, newest first — renewals included."""
    cards = list(getattr(patient, "coverages", []) or [])
    return sorted(cards, key=lambda c: (c.created_at or datetime.min, c.id), reverse=True)
