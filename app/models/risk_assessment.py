"""The three risks a hospital is required to look for — and what it did about them.

> **ICD.10** Patient's risk of **falling** is assessed, periodically
> reassessed, and managed.
> **ICD.11** The patient's risk of developing **pressure ulcers** is assessed,
> periodically reassessed and managed.
> **ICD.12** Patient's risk of developing **venous thromboembolism** is
> assessed, periodically reassessed and managed.

Three standards, one shape. Each of them asks a hospital for the same five
things in the same order — *assess with a tool, on admission · reassess on a
timeframe · general measures · a **tailored** care plan · all of it recorded in
the patient's medical record* — and each ends with the same sentence about the
family being told. Three tables would have been the same table written three
times, and would have made "which risks has anybody looked at for this child"
a question you answer by opening three screens.

---

**The program ships no scale, and this is the design, not a shortcut.**

Every one of the three standards hands the tool to the hospital and says so in
as many words: *"Assessment contents are based on guidelines"* (ICD.10 ب),
*"Contents of assessment based on guidelines"* (ICD.11 ب), *"The hospital shall
adopt and implement a guideline"* (ICD.12). ICD.11's intent goes further and
names the reason — *"The use of a risk assessment tool is **recommended by
many** international pressure ulcer prevention guidelines"*: there is more than
one, and which one suits a paediatric population is a clinical decision this
program is not entitled to make. A Morse score computed in here would be a
number nobody in the building decided on, printed in a medical record over a
nurse's name.

So the assessment carries **the clinic's own two words** — the tool it used and
what the tool said — as text the program stores and never reads.

**And one field it does read, because it has to.** ``at_risk`` is asked
separately from ``level`` for a reason that survives any tool: «متوسط» is
above the line in one hospital's policy and below it in another's, so no amount
of reading ``level`` tells this program whether *this* child needs a plan. That
one bit is the only clinical judgement asked for, it is asked in plain words,
and it is a **nullable** boolean — ``None`` is nobody having said, which is not
"not at risk". The operative report's «or not» fields are the same three states
for the same reason.

---

**It hangs off the child, not off the stay.** ``admission_id`` is nullable
because ICD.10 evidence 4 is about people who were never admitted at all —
*"Outpatients with certain conditions, situations, or locations will be
screened for risk of falls"* — and a table that could only describe an
inpatient would have no room for the child who was screened in the clinic. The
patient is the required link, which is also what makes a readmitted child read
as one story: the same rule the round note follows.
"""
from datetime import datetime

from app.extensions import db

#: The three risks, in the standards' own order — ICD.10, ICD.11, ICD.12.
#:
#: A kind column rather than three tables: see the module docstring. The
#: strings are stored, so they are the program's vocabulary and not the
#: clinic's — what the clinic says goes in ``tool`` and ``level``.
FALL, PRESSURE, VTE = ("fall", "pressure", "vte")
RISK_KINDS = (FALL, PRESSURE, VTE)

#: Which standard each one answers. **Not a translation** — a standard's code
#: is the same three letters and two digits in Cairo as in Geneva, so it lives
#: here rather than in a locale file, beside the vocabulary it belongs to.
STANDARDS = {FALL: "ICD.10", PRESSURE: "ICD.11", VTE: "ICD.12"}


class RiskAssessment(db.Model):
    """One look at one risk, for one child, at one moment."""

    __tablename__ = "risk_assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The stay it belongs to, when there was one. See the module docstring on
    # why this is nullable rather than the link.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    kind = db.Column(db.String(16), nullable=False, index=True)

    # When it was done — not when it was typed. A nurse writing up the round
    # at the desk assessed the child at the bedside twenty minutes ago, and
    # the reassessment clock counts from the bedside.
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    #: What the hospital's policy uses — «Humpty Dumpty», «Braden Q», «تقييم
    #: القسم». Free text because it is the hospital's answer to a question the
    #: standard puts to the hospital.
    tool = db.Column(db.String(120))
    #: What the tool said, in the hospital's own words. Never parsed.
    level = db.Column(db.String(60))

    #: Is this child at risk. ``None`` nobody said · ``False`` no · ``True``
    #: yes. The one bit the program reads — see the module docstring.
    at_risk = db.Column(db.Boolean)

    #: ICD.10 (و) / ICD.11 (هـ) — the measures that are not about this child:
    #: bed rails, call bell, a pressure-relieving mattress.
    general_measures = db.Column(db.Text)
    #: ICD.10 (ز) / ICD.11 (و) / ICD.12 (هـ) — **the tailored plan**, which is
    #: the element all three standards end on and the one a surveyor opens the
    #: record to find.
    plan = db.Column(db.Text)

    #: ICD.10 evidence 5, ICD.11 evidence 4, ICD.12 evidence 4 — *"The
    #: families of patients at higher risk … are aware of and involved in
    #: prevention measures."* Three states again: an empty box is not a family
    #: who was not told.
    family_told = db.Column(db.Boolean)

    patient = db.relationship("Patient", backref="risk_assessments")
    admission = db.relationship("Admission", backref="risk_assessments")
    by = db.relationship("User")

    @property
    def has_plan(self):
        """Whether anybody wrote the tailored plan. A plan of spaces is not one."""
        return bool((self.plan or "").strip())

    def __repr__(self):
        return f"<RiskAssessment {self.kind} patient={self.patient_id}>"
