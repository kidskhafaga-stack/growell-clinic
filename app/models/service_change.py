"""A service changed on a bill — the visit turned out to be something else.

``MONEY_SAFETY_PLAN.md`` ف-٨. Asked for in the owner's words: *«الى عنده
صلاحية انا عايز ادخله فى ويزر ويطبع ايصال بالارجاع او بدفع فرق الفلوس فى
حال تغيير الخدمة ويبقى متضمن رقم ايصال الخدمة الاصلية ورقم الارجاع»*.

One numbered row per change, kept for good: which line, what it was and what
it became (price, the payer's share, what the family pays), why, who did it,
and the money that followed — the refund or the collection, or the refund
request waiting for a manager. Its number is what the voucher prints beside
the original bill's number, so the paper the family takes home and the line
an accountant finds in the books name each other.

Nothing here moves money. The line is rewritten by
:mod:`app.utils.service_settlement`, and the refund or the collection is an
ordinary :class:`Payment` on the bill, made by the till's own functions.
"""
from datetime import datetime

from app.extensions import db

#: settled — the difference was paid or given back in the same step;
#: nothing — the change cost nothing either way;
#: awaiting_approval — a refund is waiting for a manager (`RefundRequest`);
#: owed — a difference the family still has to pay, left on the bill;
#: rejected — the manager turned the refund down.
STATUSES = ("settled", "nothing", "awaiting_approval", "owed", "rejected")

#: The voucher's series. Its own, so a change is never mistaken for a bill.
PREFIX = "SC"


class ServiceChange(db.Model):
    __tablename__ = "service_changes"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    # The line itself, while it exists. The figures below are the record —
    # a line edited again later must not rewrite what this change said.
    item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"))

    old_service_id = db.Column(db.Integer, db.ForeignKey("services.id"))
    old_description = db.Column(db.String(255))
    old_price = db.Column(db.Float, default=0, nullable=False)
    old_payer = db.Column(db.Float, default=0, nullable=False)
    old_family = db.Column(db.Float, default=0, nullable=False)

    new_service_id = db.Column(db.Integer, db.ForeignKey("services.id"))
    new_description = db.Column(db.String(255))
    new_price = db.Column(db.Float, default=0, nullable=False)
    new_payer = db.Column(db.Float, default=0, nullable=False)
    new_family = db.Column(db.Float, default=0, nullable=False)

    # What the family paid before the change, and the difference after it:
    # positive is collected from them, negative is given back.
    collected = db.Column(db.Float, default=0, nullable=False)
    difference = db.Column(db.Float, default=0, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="nothing", nullable=False,
                       index=True)

    # The money that followed, when it did.
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"))
    refund_request_id = db.Column(db.Integer,
                                  db.ForeignKey("refund_requests.id"),
                                  index=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    invoice = db.relationship("Invoice")
    item = db.relationship("InvoiceItem")
    old_service = db.relationship("Service", foreign_keys=[old_service_id])
    new_service = db.relationship("Service", foreign_keys=[new_service_id])
    payment = db.relationship("Payment")
    refund_request = db.relationship("RefundRequest")
    creator = db.relationship("User", foreign_keys=[created_by])

    @property
    def is_refund(self):
        return (self.difference or 0) < 0

    @property
    def amount(self):
        return round(abs(self.difference or 0), 2)

    def __repr__(self):
        return f"<ServiceChange {self.number} {self.difference}>"


def next_number():
    """The next voucher number: ``SC-000001``."""
    from app.utils.sequences import highest

    base = f"{PREFIX}-"
    seq = highest(ServiceChange.number, base) + 1
    candidate = f"{base}{seq:06d}"
    while ServiceChange.query.filter_by(number=candidate).first() is not None:
        seq += 1
        candidate = f"{base}{seq:06d}"
    return candidate
