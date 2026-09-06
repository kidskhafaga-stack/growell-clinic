"""Drawing a doctor's month, agreeing it, and paying it.

The figures come from where they already live — ``doctor_work`` for the
invoice lines and the vaccine fees, ``duty`` for the nights, ``collected`` for
what has actually come in. **Nothing is recomputed here**, deliberately: a
statement that worked its own arithmetic out would be a second opinion about a
doctor's pay, and two opinions is how a clinic ends up arguing about which
screen is right rather than about the money.

What this file adds is the part a running balance cannot do: **stopping**. A
draft is redrawn every time it is opened; a closed one is a copy of the
figures at the moment two people agreed them, and nothing afterwards moves it.
"""
from app.extensions import db
from app.models.settlement import (DEFAULT_BASIS, SETTLEMENT_BASES,
                                   Settlement, next_number)


def basis_for(doctor):
    """How this doctor is settled — their agreement, or the default.

    ``billed`` unless somebody has said otherwise, because that is what every
    figure in this program has always meant and a clinic that updates must not
    find its settlements quietly switched to a different basis.
    """
    chosen = getattr(doctor, "settlement_basis", None)
    return chosen if chosen in SETTLEMENT_BASES else DEFAULT_BASIS


def figures(doctor_id, date_from, date_to, basis=DEFAULT_BASIS):
    """``{lines, vaccines, duty, gross, advances, net, awaiting}`` for a period.

    ``lines`` is the doctor's share of the bills in the window, ``vaccines``
    the fees on the doses they gave, ``duty`` the nights they covered.

    **On a collected basis only the lines move.** A shift and a vaccine fee
    are owed by the clinic itself with nobody in between, so there is no
    third party to wait for and holding them back would be the clinic
    refusing to pay its own debt on the grounds that somebody else has not
    paid theirs.
    """
    from app.models import DoctorPayout, Invoice, InvoiceItem, PatientVaccine
    from app.utils import doctor_work
    from app.utils.collected import split_for_doctor

    lines = (db.session.query(db.func.sum(InvoiceItem.commission_amount))
             .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
             .filter(InvoiceItem.earned_by(doctor_id),
                     Invoice.invoice_date >= date_from,
                     Invoice.invoice_date <= date_to).scalar()) or 0
    lines = round(lines, 2)

    doses = (PatientVaccine.query
             .filter(PatientVaccine.doctor_id == doctor_id,
                     PatientVaccine.event_type == "given",
                     PatientVaccine.given_outside.is_(False),
                     PatientVaccine.given_date >= date_from,
                     PatientVaccine.given_date <= date_to).all())
    vaccines = round(sum((d.brand.doctor_fee or 0) for d in doses if d.brand), 2)

    duty = doctor_work._duty_earned(doctor_id, date_from, date_to)

    awaiting = 0.0
    if basis == "collected":
        split = split_for_doctor(doctor_id, date_from, date_to)
        awaiting = round(split["from_family"] + split["from_payer"], 2)
        lines = split["collected"]

    gross = round(lines + vaccines + duty, 2)
    # Money already handed over inside the window — an advance, a payment on
    # the fifteenth. Subtracted rather than ignored, or the month is paid
    # twice, and the second payment looks exactly as right as the first.
    advances = DoctorPayout.paid_to(doctor_id, date_from, date_to)
    return {"lines": lines, "vaccines": vaccines, "duty": duty,
            "gross": gross, "advances": advances,
            "net": round(gross - advances, 2), "awaiting": awaiting}


def overlapping(doctor_id, date_from, date_to, exclude_id=None):
    """Statements for this doctor sharing a day with that period.

    Every one of them, draft included: two drafts over one fortnight is two
    people about to pay the same money, and the moment to say so is before
    either is agreed rather than after both are paid.
    """
    rows = (Settlement.query
            .filter(Settlement.doctor_id == doctor_id,
                    Settlement.date_from <= date_to,
                    Settlement.date_to >= date_from).all())
    return [r for r in rows if exclude_id is None or r.id != exclude_id]


def draw(doctor, date_from, date_to, user=None, basis=None):
    """Open a draft statement for a period. Returns it.

    Raises ``ValueError`` when the period is upside down or already covered —
    a statement over days another one settles pays them twice, and both
    documents look right on their own.
    """
    if doctor is None or not date_from or not date_to:
        raise ValueError("a statement needs a doctor and a period")
    if date_to < date_from:
        raise ValueError("period runs backwards")
    doctor_id = getattr(doctor, "id", doctor)
    if overlapping(doctor_id, date_from, date_to):
        raise ValueError("period already settled")

    basis = basis if basis in SETTLEMENT_BASES else basis_for(doctor)
    row = Settlement(number=next_number(date_to), doctor_id=doctor_id,
                     date_from=date_from, date_to=date_to, basis=basis,
                     status="draft", created_by=getattr(user, "id", None))
    db.session.add(row)
    refresh(row)
    return row


def refresh(statement):
    """Redraw a draft from today's data. A closed one is left alone.

    The refusal is the point of the whole document: a closed statement is a
    figure two people agreed, and an invoice edited afterwards must not move
    it. Silently, and returning the statement either way, because a screen
    that opens a closed month should show it — not raise.
    """
    if statement is None or statement.status != "draft":
        return statement
    found = figures(statement.doctor_id, statement.date_from,
                    statement.date_to, statement.basis)
    statement.lines_amount = found["lines"]
    statement.vaccine_amount = found["vaccines"]
    statement.duty_amount = found["duty"]
    statement.gross_amount = found["gross"]
    statement.advances = found["advances"]
    statement.net_due = found["net"]
    statement.awaiting = found["awaiting"]
    return statement


def close(statement, user=None, note=None):
    """Freeze it at the figures it is showing. Only a draft can be closed."""
    from datetime import datetime

    if statement is None or statement.status != "draft":
        return statement
    refresh(statement)
    statement.status = "closed"
    statement.closed_at = datetime.utcnow()
    statement.closed_by = getattr(user, "id", None)
    if note:
        statement.note = note.strip()[:255] or None
    return statement


def reopen(statement):
    """Back to draft, and only while the money has not gone.

    A mistake found before payment is a correction; the same edit after the
    doctor has been paid is a second set of books. A paid statement stays as
    it is and the next one carries the difference.
    """
    if statement is None or statement.status != "closed":
        return statement
    statement.status = "draft"
    statement.closed_at = None
    statement.closed_by = None
    return refresh(statement)


def mark_paid(statement, payout=None):
    """Record that the money has gone, and tie the payment to the paper.

    The payout is the money leaving a till — it already exists and already
    reaches the ledger. This only says which month it settled, which is the
    question somebody asks in March about a payment made in January.
    """
    from datetime import datetime

    if statement is None or statement.status not in ("closed", "draft"):
        return statement
    if statement.status == "draft":
        close(statement)
    statement.status = "paid"
    statement.paid_at = datetime.utcnow()
    if payout is not None:
        payout.settlement_id = statement.id
    return statement


def for_doctor(doctor_id, limit=24):
    """This doctor's statements, newest period first."""
    return (Settlement.query
            .filter(Settlement.doctor_id == doctor_id)
            .order_by(Settlement.date_from.desc(), Settlement.id.desc())
            .limit(limit).all())
