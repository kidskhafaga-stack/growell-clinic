"""A stay that is not a visit, and the bed it is spent in.

**Why not a visit.** ``Visit.visit_date`` is a ``Date`` — one day. That is
right for an outpatient: they arrive, they are seen, they go home, and the
whole encounter belongs to a date. A stay is a different animal. It runs
across days, it ends in a decision (home, another hospital, or worse), and at
every hour of it the child is in a *place*. A ``Date`` column cannot hold any
of that, and widening it would have made every outpatient visit carry three
columns that mean nothing to it.

**One file, still.** This is not a second medical record. The admission hangs
off the same child, shows up on the same file, and the observations taken
during it are the same ``Observation`` rows the emergency department writes —
see ``HOSPITAL_PLAN.md``, ٨: *"ملف الطفل واحد. لو الطفل اتنوّم، التنويم بيظهر
في نفس الملف."*

**Two tables, because the bed changes and the stay does not.** A child moves
from the bay to an isolation partition, or from a cot into an incubator, and
the stay carries on. So the admission is the stay, and ``BedStay`` is where
they were between two moments. That split is what makes three separate
questions answerable from the same rows:

* *is this bed free?* — has it an open stay
* *where is this child now?* — their admission's open stay
* *who was in this bed last Tuesday?* — the stay that covered it

A ``bed_id`` column on the admission would answer only the first two, and
would answer the third with today's bed for every day of the stay.

**A transport capsule keeps its stay open.** The baby goes down to X-ray, or
out to another hospital, in the capsule — which *is* their bed. The stay does
not end because they left the room; it ends when somebody discharges them.
That is the reason the stay hangs off the bed rather than off the space.
"""
from datetime import datetime

from app.extensions import db

# How a stay ended. Recorded rather than inferred: "went home" and "was moved
# to another hospital" look identical in a table that only stores a discharge
# time, and they are not the same event to anybody who reads the file later.
OUTCOMES = ("home", "transferred", "self_discharge", "died")


class Admission(db.Model):
    """One stay, from the moment a child is admitted until they leave."""

    __tablename__ = "admissions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The visit that sent them in, when there was one. Nullable because a
    # newborn admitted straight from delivery never had an outpatient visit,
    # and refusing the admission until somebody invents one would put a
    # fictional consultation in the child's file.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True,
                          index=True)

    admitted_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False, index=True)
    admitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reason = db.Column(db.String(200))

    discharged_at = db.Column(db.DateTime, index=True)
    discharged_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    outcome = db.Column(db.String(16))
    discharge_note = db.Column(db.Text)

    patient = db.relationship("Patient", backref="admissions")
    visit = db.relationship("Visit", backref="admissions")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    stays = db.relationship("BedStay", back_populates="admission",
                            order_by="BedStay.since, BedStay.id")

    @property
    def is_open(self):
        return self.discharged_at is None

    @property
    def current_stay(self):
        """Where the child is now, or ``None`` once they have gone."""
        return next((s for s in self.stays if s.until is None), None)

    @property
    def bed(self):
        stay = self.current_stay
        return stay.bed if stay else None

    def __repr__(self):
        return f"<Admission patient={self.patient_id} open={self.is_open}>"


class BedStay(db.Model):
    """This child, in this bed, between these two moments."""

    __tablename__ = "bed_stays"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    bed_id = db.Column(db.Integer, db.ForeignKey("care_beds.id"),
                       nullable=False, index=True)

    since = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                      index=True)
    # Open while the child is in it. Every occupancy figure in the program is
    # a count of rows where this is null — never a flag on the bed, which is
    # one forgotten discharge away from a ward that reports itself full with
    # three beds standing empty.
    until = db.Column(db.DateTime, index=True)
    moved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(120))

    admission = db.relationship("Admission", back_populates="stays")
    bed = db.relationship("Bed", backref="stays")

    @property
    def is_open(self):
        return self.until is None

    def __repr__(self):
        return f"<BedStay bed={self.bed_id} open={self.is_open}>"
