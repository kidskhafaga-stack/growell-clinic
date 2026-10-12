"""End-of-life care on a stay — GAHAR CSS.04.

*"Terminally ill patients are assessed and receive the appropriate
management of symptoms"* (ev. 3), *"Patients and family are involved in
decisions and care"* (ev. 4), and the assessment, reassessment and
management recorded (ev. 5).

So a **plan** — the goals of care as decided with the family (who, and what
was decided), the psychosocial and spiritual support asked for, and the team
— and **reviews** of the symptoms the intent names (pain, breathlessness,
anxiety, agitation), each present or not with what was done. No score and
no scale: present symptoms need what was done, and that is all the program
judges.
"""
from datetime import datetime

from app.extensions import db

SYMPTOMS = ("pain", "dyspnea", "anxiety", "agitation")


class PalliativePlan(db.Model):
    __tablename__ = "palliative_plans"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    goals = db.Column(db.Text, nullable=False)
    decided_with = db.Column(db.String(160), nullable=False)
    support = db.Column(db.String(255))
    team = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])


class PalliativeReview(db.Model):
    __tablename__ = "palliative_reviews"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    #: Comma list of ``SYMPTOMS`` present.
    present = db.Column(db.String(60))
    action = db.Column(db.String(255))
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def present_list(self):
        return [s for s in (self.present or "").split(",") if s in SYMPTOMS]
