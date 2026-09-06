"""Two medicines this hospital keeps confusing with each other.

The medication-management standards ask a hospital to identify its
look-alike / sound-alike medicines and do something about them. Like the
high-alert list, **the pairs are the hospital's own**: which names get mixed
up depends on what is on their shelves, what their handwriting looks like and
what their staff speak — and a list shipped with the software would be a list
about somebody else's pharmacy.

**Symmetric, because confusion is.** One row covers both directions: writing
either of the two brings up the other. Stored once and read both ways rather
than as two rows, so a pair cannot end up half-deleted and warning in one
direction only — which is the failure mode of every hand-maintained pair list.

The existing ``DrugInteraction`` table is the same shape for a different
question, and this deliberately does not reuse it: an interaction is a fact
about chemistry that holds everywhere, and a LASA pair is a fact about this
building. Merging them would put a clinic's local worry in a table that reads
as clinical truth.
"""
from datetime import datetime

from app.extensions import db


class LasaPair(db.Model):
    """Two ingredients a hospital wants shown side by side when either is
    written."""

    __tablename__ = "lasa_pairs"
    __table_args__ = (
        db.UniqueConstraint("generic_a_id", "generic_b_id", name="uq_lasa"),
    )

    id = db.Column(db.Integer, primary_key=True)
    generic_a_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                             nullable=False, index=True)
    generic_b_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                             nullable=False, index=True)

    # What to do about it: tall-man lettering, separate shelves, a second
    # check. The practice is the hospital's, so the text is theirs.
    precaution = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    added_by = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    generic_a = db.relationship("GenericDrug", foreign_keys=[generic_a_id])
    generic_b = db.relationship("GenericDrug", foreign_keys=[generic_b_id])
    author = db.relationship("User", foreign_keys=[added_by])

    def other_than(self, generic_id):
        """The one this pair warns about, given the one that was written."""
        if generic_id == self.generic_a_id:
            return self.generic_b
        if generic_id == self.generic_b_id:
            return self.generic_a
        return None

    def __repr__(self):
        return f"<LasaPair {self.generic_a_id}/{self.generic_b_id}>"
