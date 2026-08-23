"""A measurement a specialty takes, on a visit, in one table.

The specialties survey asks for about sixty of these across ten specialties —
EF and LVEDD for the cardiologist, Tanner and insulin units for the
endocrinologist, ACT and FEV1 for the chest clinic, dmft and a tooth chart for
the dentist, visual acuity and eye pressure for the ophthalmologist.

**Sixty columns is not the answer**, and neither is a table per specialty. The
first makes every clinic carry every specialty's schema; the second makes
"show me this child across every doctor who saw them" a query nobody writes.
One table, one row per reading, and the catalogue in a data file — the same
shape as the vaccine schedules, for the same reason: adding a specialty should
be an edit to a JSON file and not a migration.

**A value can be a number or a word, and both are first class.** EF is 55. Ross
is II. NYHA is III. A design that forced everything numeric would have somebody
storing 2 for Ross II and drawing a chart of it; one that forced everything
textual would lose every curve. So there are two columns and the catalogue says
which one a field uses.

**And nothing here is a vital sign.** Weight, height, pulse, respiratory rate,
oxygen saturation and blood pressure live on ``VitalSigns`` where the nurse
records them, and a panel *reads* them rather than asking again. Two weights
for one visit, from two screens, is a record nobody can trust.
"""
from datetime import datetime

from app.extensions import db


class Measurement(db.Model):
    """One reading of one field, taken at one visit."""

    __tablename__ = "measurements"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # Nullable because a reading can arrive outside a visit — a result phoned
    # in, a measurement taken at the desk. The patient is what it always has.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"),
                         nullable=True, index=True)

    # The catalogue's code for this field: `ef_pct`, `nyha_ross`, `lvedd_mm`.
    # A code and not a label, so a clinic that renames a field in Arabic does
    # not orphan every reading ever taken with it.
    code = db.Column(db.String(40), nullable=False, index=True)
    # Which panel it was entered from. Kept because the same code could be
    # offered by two panels later, and because "what did the cardiology panel
    # record on this visit" is a question worth being able to answer.
    panel = db.Column(db.String(40), index=True)

    value_num = db.Column(db.Float)
    value_text = db.Column(db.String(80))
    unit = db.Column(db.String(20))

    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                            index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    patient = db.relationship("Patient")
    visit = db.relationship("Visit")

    __table_args__ = (
        # One reading per field per visit. A panel saved twice corrects the
        # reading; it does not add a second one, which would make "the EF at
        # this visit" a question with two answers.
        db.UniqueConstraint("visit_id", "code", name="uq_measurement_visit_code"),
    )

    @property
    def value(self):
        """Whichever of the two was filled — number first."""
        if self.value_num is not None:
            return self.value_num
        return self.value_text

    @property
    def is_empty(self):
        return self.value_num is None and not (self.value_text or "").strip()

    def display(self):
        """The reading as it should be read: value then unit, if it has one."""
        if self.value_num is not None:
            number = (f"{self.value_num:g}")
            return f"{number} {self.unit}".strip() if self.unit else number
        return self.value_text or ""

    def __repr__(self):
        return f"<Measurement {self.code}={self.display()} visit={self.visit_id}>"
