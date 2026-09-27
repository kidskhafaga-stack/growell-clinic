"""A payment asked for through a gateway — before, and after, it is paid.

``BOOKING_APPROVAL_PLAN.md`` §3🅐: a real link for each bill, with an amount
and a reference, and **the confirmation comes from the gateway itself**, never
from a screenshot and never from a model. This row is the link and what
became of it; the money, once the gateway has proved it arrived, is an
ordinary :class:`Payment` on the invoice, so every screen, report and the
ledger see it exactly as they see money taken at the desk.

Reception recording a payment by hand is not replaced by any of this. It is
still how most money arrives, and a clinic with no gateway switched on has
no rows here at all.
"""
from datetime import datetime

from app.extensions import db

#: created — asked of the gateway, nothing back yet (or the gateway refused);
#: pending — the family has a link or a code to pay with;
#: paid — the gateway proved it, and the money is a Payment on the invoice;
#: mismatch — the gateway proved a payment of a different amount or currency:
#:            nothing is recorded, and a person looks at it;
#: failed / expired / cancelled — no money moved.
STATUSES = ("created", "pending", "paid", "mismatch", "failed", "expired",
            "cancelled")
OPEN = ("created", "pending")

#: The method a gateway payment is recorded under. Not in
#: ``invoice.PAYMENT_METHODS``: nobody at the desk can choose it — only a
#: gateway's proved confirmation writes it.
ONLINE_METHOD = "online"


class OnlinePayment(db.Model):
    __tablename__ = "online_payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)
    # Ours, unique, and what the gateway is given to hand back: the only way a
    # confirmation is matched to a bill. Never the invoice number alone — two
    # links for one bill (the first one expired) must stay two.
    reference = db.Column(db.String(40), nullable=False, unique=True,
                          index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="EGP")
    status = db.Column(db.String(10), nullable=False, default="created",
                       index=True)

    # What the family is given: a page to pay on, or a code to pay at a
    # kiosk — a gateway gives one or the other, sometimes both.
    checkout_url = db.Column(db.String(500))
    pay_code = db.Column(db.String(40))
    expires_at = db.Column(db.DateTime)

    # The gateway's own id for the payment, once it has one.
    provider_ref = db.Column(db.String(80), index=True)
    # What the gateway said it received, when it said so — kept even when it
    # did not match, because that is the case a person has to look at.
    reported_amount = db.Column(db.Float)
    reported_currency = db.Column(db.String(3))
    error = db.Column(db.String(300))

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)
    paid_at = db.Column(db.DateTime)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"))

    invoice = db.relationship("Invoice")
    payment = db.relationship("Payment")
    creator = db.relationship("User", foreign_keys=[created_by])

    @property
    def is_open(self):
        return self.status in OPEN

    def __repr__(self):
        return f"<OnlinePayment {self.reference} {self.provider} {self.status}>"
