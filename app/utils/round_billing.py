"""The consultant's round, on the family's bill.

The last of the three ways a doctor is paid in a hospital, and the only one
that was still missing. It was described in one sentence:

    «غالباً الاستشاري يا بيتحاسب من المستشفى في ساعتها، والمستشفى بتحط على
     فاتورة الأهل بعد كده وغالباً بيبقى ليها نسبة من المبلغ ده»

Two movements of money, not one. The hospital pays the consultant for the
visit; the hospital charges the family more than that, and keeps the
difference. **Both of them already exist in this program** — a service has a
price, and a doctor has a fixed commission on it — and what was missing was
only the sentence joining them to a round: *this consultant saw this child on
Tuesday and nobody billed it.*

**Nothing new was invented to price it.** The round is a ``Service``, so it
goes through the one price list where the insurance, the contract tariff, the
family discount and the tax code already work. The per-consultant part is the
doctor–service row every other service already uses: ``price_override`` is
what the family pays for *that* consultant's round, and a ``fixed`` commission
on the same row is what the consultant is paid. The hospital's margin is the
subtraction, and it is done by the same ``doctor_share`` as every other line.

**The price is the switch**, exactly as it is for a bed night. A clinic that
has priced nobody's round is never charged for one and never sees a card about
it. That is also how the resident is kept out of this without a flag saying
so: a house officer walking the ward every morning has no price on their
round, so their notes stay what they have always been — clinical, and free.

**Charged to the person who did it, not to the person the stay belongs to.**
The share is read against the doctor who wrote the round and the line records
them, for the same reason the surgeon's line does: repricing the bill later
must not hand a visiting cardiologist's fee to the admitting paediatrician.

**And it goes onto the stay's one invoice**, folded into the same posting as
the nights, the drugs, the theatre and the lab — because a family gets one
account for an admission, not five bills for the same three days.
"""
from app.extensions import db
from app.models.round_note import RoundNote

#: The service every round is billed as. One code, priced per consultant.
ROUND_CODE = "SVC-ROUND"


def round_service():
    """The round service, or ``None`` where the clinic has never had one."""
    from app.models import Service

    return Service.query.filter_by(code=ROUND_CODE).first()


def rate_for(doctor, service=None):
    """What the family is charged for this doctor's round, or ``None``.

    ``None`` is the ordinary answer and the important one: it means this
    doctor's round is not a chargeable thing here, which is true of every
    resident and of every doctor in a clinic that has not set this up.
    """
    if doctor is None:
        return None
    service = service or round_service()
    if service is None or not service.is_active:
        return None
    price = float(service.price_for(doctor) or 0)
    return price if price > 0 else None


def unbilled(admission_id=None, patient_id=None):
    """Rounds that happened, are chargeable, and have not been charged.

    Same shape as an unbilled operation: the round carries the invoice line it
    went onto, so asking twice charges once. "Chargeable" is decided by the
    price and by nothing else — see the module docstring.
    """
    service = round_service()
    if service is None or not service.is_active:
        return []
    # ``by_id`` here is a **pre-filter, not the guard** — measured, by a
    # mutation that deleted it and changed nothing: a round with no author
    # falls out below anyway, because `rate_for(None)` has no doctor to read a
    # price against. It stays because loading anonymous rows to discard them
    # is work, and it is written down as redundant so that nobody later
    # removes the real check believing this one covers it.
    query = RoundNote.query.filter(RoundNote.invoice_item_id.is_(None),
                                   RoundNote.by_id.isnot(None))
    if admission_id is not None:
        query = query.filter(RoundNote.admission_id == admission_id)
    if patient_id is not None:
        query = query.filter(RoundNote.patient_id == patient_id)
    rows = query.order_by(RoundNote.at, RoundNote.id).all()
    return [r for r in rows if rate_for(r.by, service) is not None]


def describe(note, service, lang="ar"):
    """The line as a family reads it: what it was, whose, and which day."""
    from app.utils.clock import to_local

    name = (service.display_name(lang) if hasattr(service, "display_name")
            else service.name)
    parts = [name]
    if note.by is not None:
        parts.append(note.by.full_name or note.by.username)
    when = to_local(note.at)
    if when is not None:
        parts.append(when.strftime("%Y-%m-%d"))
    return " · ".join(p for p in parts if p)


def charge(admission, invoice, user=None, lang="ar"):
    """Put this stay's chargeable rounds on its bill. Returns how many."""
    from app.models.invoice import InvoiceItem

    if admission is None or invoice is None:
        return 0
    service = round_service()
    due = unbilled(admission_id=admission.id)
    for note in due:
        price = float(service.price_for(note.by) or 0)
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description=describe(note, service, lang),
                           unit_price=price, quantity=1)
        # Read against **the consultant who came**, not the admitting doctor.
        # The fixed part of this is what the hospital pays them; the rest of
        # the line is the hospital's, and neither number is written down twice.
        item.commission_amount = service.doctor_share(item.net, note.by)
        item.doctor_id = note.by_id
        db.session.add(item)
        db.session.flush()
        note.invoice_item_id = item.id
    return len(due)
