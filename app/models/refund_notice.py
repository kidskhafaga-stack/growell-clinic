"""What the doctor is told when money goes back, and how they answer.

Asked for in one sentence: *"لو هو معاه الصلاحية لازم يبعت برده إشعار للطبيب —
الحالة الفلانية عاملة استرداد جزء/كل. لو مش موافق يبعت اعتراض. هو مش هيوقف
عملية، بس الطبيب في ساعتها ممكن يعارض ويظهر للاستقبال."*

**The objection does not block anything, and that is the design.** The money
has already gone back over the counter by the time this row exists; a doctor's
disagreement cannot un-hand it, and a program that pretended otherwise would
be holding a family at the desk waiting for somebody who is with a patient.
What the objection does is put the disagreement on the record, in front of the
desk that made it and the manager who reads the day — which is the thing a
doctor actually wants and the thing the program had no way to carry.

**Why the doctor is told at all.** Their share follows the money: a refund of
half an invoice takes half their share of it with it (see
``doctor_work.refunded_share``). So a refund is not an administrative detail
that happens near them — it is a number coming off their account, decided by
somebody else, and they are entitled to know the same day rather than at the
end of the month when the total does not add up.

One row per refund. It carries what was refunded and why, so the doctor reads
the decision rather than a bare figure, and it carries the objection in the
same place so nobody has to join two records to see whether the doctor
disagreed.
"""
from datetime import datetime

from app.extensions import db

# Whether the whole invoice went back or part of it. Recorded rather than
# inferred from the amount: an invoice can be refunded in two goes, and the
# second one is not "partial" merely because it is smaller than the total.
REFUND_SCOPES = ["full", "partial"]


class RefundNotice(db.Model):
    """One refund, as the doctor whose work it was sees it."""

    __tablename__ = "refund_notices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    # The refund payment itself, so the notice can never drift from the money.
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"),
                           nullable=True, index=True)
    # Whose work it was. Nullable because an invoice can carry no doctor —
    # a dressing done by the nurse — and a refund on one of those is still a
    # refund; it simply has nobody to tell.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                          nullable=True, index=True)

    amount = db.Column(db.Float, default=0, nullable=False)
    # What this refund took off the doctor's account, worked out when it
    # happened. Stored rather than recomputed: the invoice can be edited
    # afterwards, and the doctor was told a number.
    doctor_amount = db.Column(db.Float, default=0, nullable=False)
    scope = db.Column(db.String(8), default="partial", nullable=False)
    reason = db.Column(db.String(200))

    refunded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                           index=True)

    # The doctor's answer, if they gave one.
    seen_at = db.Column(db.DateTime)
    objected_at = db.Column(db.DateTime)
    objection_note = db.Column(db.String(300))

    invoice = db.relationship("Invoice")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    actor = db.relationship("User", foreign_keys=[refunded_by])

    @property
    def objected(self):
        return self.objected_at is not None

    @classmethod
    def open_objections(cls, limit=20):
        """Objections the desk has not had answered yet, newest first.

        What reception and the manager see. Not filtered by "unread" — an
        objection is not dealt with by somebody glancing at it, and the one
        thing worse than not showing it is showing it once.
        """
        return (cls.query.filter(cls.objected_at.isnot(None))
                .order_by(cls.objected_at.desc()).limit(limit).all())

    @classmethod
    def for_doctor(cls, doctor_id, limit=50):
        return (cls.query.filter(cls.doctor_id == doctor_id)
                .order_by(cls.created_at.desc()).limit(limit).all())

    def __repr__(self):
        return f"<RefundNotice inv={self.invoice_id} {self.amount} {self.scope}>"
