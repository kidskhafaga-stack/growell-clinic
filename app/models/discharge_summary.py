"""The document a stay ends with, and the nine things it has to say.

GAHAR **ACT.15** — *"Discharge summaries are complete"* — and the standard is
unusually concrete about what that means:

> A discharge summary is a clinical report prepared by a healthcare
> professional at the conclusion of a hospital stay… **It is considered a
> legal document**, and it has the potential to jeopardize the patient's care
> if errors are made.

> The discharge summary includes at least the following:
> a) The reason for hospitalization.
> b) Provisional and/or final diagnosis.
> c) Investigations.
> d) Significant findings.
> e) Procedures performed.
> f) Medications (before/during) and/or other treatments.
> g) Patient's condition and disposition at discharge.
> h) Discharge instructions, including diet, medications, and follow-up.
> i) Name of the medical staff member who discharged the patient.

**What this program had instead** was ``Admission.discharge_note`` — one free
text box — and ``outcome``, one word out of four. A child who spent a week in
a bed left with less written down than a day case leaving recovery, which
refuses to discharge without a follow-up decision.

**Most of the nine are already in the record**, and the program will not ask
anybody to type them a second time. The reason is on the stay, the procedures
are the operations linked to it, the inpatient drug orders hang off it, and
the name of whoever discharged the child is already stamped. Those are
*derived* — see ``app/utils/discharge_summary.py`` — and a second copy here
would be a second answer that drifts from the first.

**Six things nobody has written anywhere**, and they are what this table
holds:

* ``diagnosis`` — the **final** one. Deliberately not the visit's: the
  standard asks for *"provisional and/or final"*, and they are two different
  facts decided at two different moments by two different amounts of
  evidence. The visit keeps the provisional; this keeps what the stay
  concluded. The screen shows the provisional ones beside the box so nobody
  retypes, which is an offer and not an answer.
* ``findings`` — (d), which exists nowhere else.
* ``condition`` — (g)'s first half. ``outcome`` is the *disposition* — home,
  transferred, died — and it is not the child's condition. A summary that
  said "home" and nothing else would answer half of one element and look
  like it had answered all of it.
* ``diet`` · ``medicines`` · ``followup`` — (h), and **three boxes rather
  than one**. The standard names all three, and one box lets a doctor write
  about the medicines only while the program records element (h) as done.
  That is the same false green tick the checklist work has been removing all
  along.

**A row, not columns on the stay.** Three reasons, and each one is a fact the
columns could not hold:

1. *A summary that was never written leaves no row*, so the absence is the
   finding — the same shape as ``SafetyCheck``. Columns would give every
   stay in the clinic's history a blank summary indistinguishable from an
   unwritten one.
2. *When it was written is not when the child left.* The standard says so
   itself: *"Delays in the completion of the discharge summary are associated
   with higher rates of readmission."* Two stamps, so the delay is a number
   somebody can look at.
3. *Handing a copy to the family is its own event* (evidence 4), and nobody
   handed it is not the same as nobody wrote it.

**And the program does not judge the delay.** How long a summary may take is
the hospital's policy — the standard says *"an approved timeframe"* and names
no number, so neither does this. It measures.
"""
from datetime import datetime

from app.extensions import db


class DischargeSummary(db.Model):
    """One stay's discharge summary — the written half of ACT.15."""

    __tablename__ = "discharge_summaries"

    id = db.Column(db.Integer, primary_key=True)
    # **Unique.** One stay, one summary. A second row would be a second legal
    # document about the same discharge, and nothing could say which was the
    # one given to the family. Corrections edit this one.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, unique=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # (b) the final diagnosis — the stay's conclusion, not the visit's opening.
    diagnosis = db.Column(db.Text)
    # (d) significant findings.
    findings = db.Column(db.Text)
    # (g) the child's condition. The disposition is `Admission.outcome`.
    condition = db.Column(db.Text)
    # (h) three, because the standard names three.
    diet = db.Column(db.Text)
    medicines = db.Column(db.Text)
    followup = db.Column(db.Text)

    # When it was written, which is not when the child left.
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    # Evidence 4: *"A copy of the discharge summary is given to the patient."*
    # Its own stamp — a summary nobody handed over is not a summary nobody
    # wrote, and one field could not tell the two apart.
    given_at = db.Column(db.DateTime)
    given_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    admission = db.relationship("Admission",
                                backref=db.backref("discharge_summary",
                                                   uselist=False))
    patient = db.relationship("Patient")
    author = db.relationship("User", foreign_keys=[written_by])
    giver = db.relationship("User", foreign_keys=[given_by])

    #: The fields a person has to write, in the order the standard names them.
    WRITTEN = ("diagnosis", "findings", "condition", "diet", "medicines",
               "followup")

    @property
    def blanks(self):
        """Which written elements are still empty — the incompleteness itself.

        Derived rather than stored: a count written down at save time would
        be wrong the moment somebody filled one in.
        """
        return [name for name in self.WRITTEN
                if not (getattr(self, name) or "").strip()]

    @property
    def given(self):
        return self.given_at is not None

    def __repr__(self):
        return f"<DischargeSummary stay={self.admission_id}>"
