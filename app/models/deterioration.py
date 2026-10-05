"""A child getting worse, the call for help, and the answer — GAHAR ICD.22 /
GSR.10.

> Recognition and response to clinical deterioration are **recorded in the
> patient's medical record** (evidence 4).

The resuscitation record (`Resuscitation`, CSS.05) answers the arrest. This
answers everything before it — the respiratory rate that went red at three in
the morning, the nurse who did not like how the child looked — which is where
the standard's intent says the lives are saved: *early detection of warning
signs and provision of urgent care on the right time leads to better outcome
than resuscitation*.

**Four moments, not one**, for the same reason the resuscitation record keeps
three: noticed · called · arrived · closed. The gap between noticing and
calling is a different failure from the gap between calling and arriving,
and one column would make them the same number.

**The reading is copied, not referred to.** What the nurse saw when she
called — «RR 70, SpO2 88» — is written on the call; a later reading must not
change what the call was about.
"""
from datetime import datetime

from app.extensions import db

#: How it ended. Operational, not a clinical grading.
STAYED, TRANSFERRED, RESUSCITATION, OTHER = ("stayed", "transferred",
                                             "resuscitation", "other")
OUTCOMES = (STAYED, TRANSFERRED, RESUSCITATION, OTHER)


class DeteriorationCall(db.Model):
    __tablename__ = "deterioration_calls"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             index=True)
    observation_id = db.Column(db.Integer, db.ForeignKey("observations.id"))

    # (أ) what was seen: the reading as it was, and/or the worry in words.
    reading = db.Column(db.String(200))
    concern = db.Column(db.String(255))
    noticed_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    noticed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # (د) how help was called: the hospital's code, and whom.
    code_key = db.Column(db.String(40))
    called_whom = db.Column(db.String(120))
    called_at = db.Column(db.DateTime, index=True)

    # (ج)(هـ) who answered, and when.
    arrived_at = db.Column(db.DateTime, index=True)
    arrived_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    # (ز) what was done, and how it ended.
    actions = db.Column(db.Text)
    outcome = db.Column(db.String(16), index=True)
    resuscitation_id = db.Column(db.Integer, db.ForeignKey("resuscitations.id"))
    closed_at = db.Column(db.DateTime, index=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    admission = db.relationship("Admission")
    noticer = db.relationship("User", foreign_keys=[noticed_by])
    responder = db.relationship("User", foreign_keys=[arrived_by])
    closer = db.relationship("User", foreign_keys=[closed_by])

    @property
    def is_open(self):
        return self.closed_at is None

    def minutes_to_arrive(self):
        if self.called_at is None or self.arrived_at is None:
            return None
        return max(0, int((self.arrived_at - self.called_at).total_seconds() // 60))

    def minutes_to_call(self):
        if self.called_at is None or self.noticed_at is None:
            return None
        return max(0, int((self.called_at - self.noticed_at).total_seconds() // 60))

    def __repr__(self):
        return f"<DeteriorationCall {self.id} p={self.patient_id}>"
