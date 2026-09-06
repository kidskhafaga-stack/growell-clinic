"""The medicines this hospital decided to be careful with.

**The standard is explicit that the list is the hospital's own.** JCI's
medication-management chapter, which GAHAR's Egyptian standards follow, says a
hospital *"needs to develop its own list(s) of high-alert medications based on
its unique utilization patterns … and its own internal data about near misses,
medication errors and sentinel events, as well as known safety issues
published in professional literature."*

That is unusually convenient, because it is the rule this program already
runs on: it does not ship clinical judgements. A list of dangerous drugs
bundled with the software would be wrong for somebody on the first day —
a paediatric oncology ward and a village clinic do not fear the same
molecules — and being wrong about *this* list is being wrong about the
medicines that kill people when they go wrong.

So nothing is seeded. The list is empty until a pharmacy writes it, and an
empty list marks nothing, which is exactly where a fresh install should be.

**Keyed on the active ingredient, not the brand.** The same argument the
interaction pairs are built on: mark the ingredient and every trade name of it
is caught, including the one the clinic has not stocked yet. A row may name a
brand instead when the concern really is one product, and one that names
neither is refused — a rule matching nothing is a rule that reads as cover.
"""
from datetime import datetime

from app.extensions import db


class HighAlertDrug(db.Model):
    """One medicine this hospital wants flagged wherever it appears."""

    __tablename__ = "high_alert_drugs"
    __table_args__ = (
        db.UniqueConstraint("generic_id", "drug_id", name="uq_high_alert"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # The ingredient, which is the usual and the better one: every brand of
    # it is covered by one row.
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=True, index=True)
    # Or one product, when the concern genuinely is that box — a strength that
    # looks like another, a presentation that gets confused.
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"),
                        nullable=True, index=True)

    # Why. **Required**, and the reason is the point: "insulin" on a list with
    # nothing beside it tells a night nurse nothing, while "ten-fold errors —
    # always have a second person check the units" tells them what to do.
    reason = db.Column(db.String(255), nullable=False)

    # What this hospital wants done about it. Free text on purpose: a double
    # check, a witness signature, a separate shelf — the practice is theirs,
    # and a fixed list of ours would be a fixed list of somebody else's.
    precaution = db.Column(db.String(255))

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    generic = db.relationship("GenericDrug")
    drug = db.relationship("Drug")
    author = db.relationship("User", foreign_keys=[added_by])

    def display_name(self, lang="ar"):
        if self.generic is not None:
            return self.generic.display_name(lang)
        if self.drug is not None:
            return getattr(self.drug, "trade_name", None) or self.drug.name
        return ""

    def __repr__(self):
        return f"<HighAlertDrug {self.display_name()}>"
