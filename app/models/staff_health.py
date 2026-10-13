"""The staff health program — GAHAR OGM.17.

* :class:`OccupationalRisk` — ev. 2: the occupational risk assessment, by
  area and job: ergonomic, physical, biological, chemical, radiation or
  psychosocial, with the controls and how serious it is;
* :class:`StaffHealthEntry` — ev. 4–6: the staff member's health record —
  the pre-employment and periodic examinations, screening, immunizations,
  exposures and their prophylaxis, injuries, and work restrictions. A
  positive result carries the action taken and the day the employee was
  told; an exposure carries what was done about it.

The radiation workers' blood counts and dose readings stay where they are
(``radiation_safety``); a staff injury is reported as an incident too
(``Incident.affected == "staff"``). Kept, never edited or deleted.
"""
from datetime import datetime

from app.extensions import db

#: OGM.17 (d) and the hazards ev. 2 names.
HAZARDS = ("ergonomic", "physical", "biological", "chemical", "radiation", "psychosocial")
RISK_LEVELS = ("high", "medium", "low")
#: OGM.17 (a)–(c), (f), (h) and ev. 4–5.
ENTRY_KINDS = ("pre_employment", "periodic", "screening", "immunization", "exposure",
               "injury", "restriction")
RESULTS = ("normal", "positive", "na")


class OccupationalRisk(db.Model):
    __tablename__ = "occupational_risks"

    id = db.Column(db.Integer, primary_key=True)
    area = db.Column(db.String(160), nullable=False)
    job = db.Column(db.String(160))
    hazard = db.Column(db.String(14), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    controls = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(8), nullable=False)
    assessed_on = db.Column(db.Date, nullable=False)
    #: OGM.17 (i) — infection control took part.
    ipc_involved = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    assessed_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class StaffHealthEntry(db.Model):
    __tablename__ = "staff_health_entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False, index=True)
    on = db.Column(db.Date, nullable=False, index=True)
    #: The examination, the test, the vaccine and dose, what the exposure was.
    detail = db.Column(db.String(255), nullable=False)
    result = db.Column(db.String(8), default="na", nullable=False)
    #: ev. 6 — what was done (counselling, prophylaxis, referral, a
    #: restriction), and the day the employee was told.
    action = db.Column(db.Text)
    informed_on = db.Column(db.Date)
    restricted_until = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
