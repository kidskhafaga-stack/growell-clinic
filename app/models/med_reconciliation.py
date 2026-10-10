"""Medication reconciliation at the stay's interfaces — GAHAR MMS.10 / GSR.18.

The clinic's half was already here (``models/medication_review``): at a
visit, every medicine on the child's list gets a decision written down. A
stay has four moments where the list has to be looked at again, and until
now the program could only *show* the lists side by side at one of them
(``clinical_pharmacy.discharge_reconciliation``) and record nothing:

* **admission** — what the child came in on (the home list), each one
  continued on the ward, stopped for now, or changed;
* **transfer** — moved into another unit: the ward chart looked at by the
  team taking the child, each order continued, stopped or changed;
* **discharge** — and a transfer out to another hospital, which is the same
  moment with another destination: the home list and the ward chart
  together, each decided for going home.

One row per decision, including «continue» — a list reviewed and a list
ignored must not leave the same trace (the same reason as the clinic's).
The row is the record of a decision, not the state of the drug: the home
list stays on ``PatientMedication`` and the chart on ``MedicationOrder``.

**It holds nothing up.** A child is admitted, moved and sent home whether or
not this is done; the stay's page says which of the moments are still open.
"""
from datetime import datetime

from app.extensions import db

ADMISSION, TRANSFER, DISCHARGE = "admission", "transfer", "discharge"
INTERFACES = (ADMISSION, TRANSFER, DISCHARGE)
#: The clinic's three, and for the same reason: a longer list is a form
#: somebody skips.
DECISIONS = ("continue", "stop", "modify")


class MedReconciliation(db.Model):
    __tablename__ = "med_reconciliations"

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    interface = db.Column(db.String(12), nullable=False, index=True)
    #: The stay in the new unit, for a transfer — a stay can be moved twice.
    stay_id = db.Column(db.Integer, db.ForeignKey("bed_stays.id"), index=True)
    #: One of the two: a medicine from the home list, or an order on the chart.
    home_med_id = db.Column(db.Integer, db.ForeignKey("patient_medications.id"))
    order_id = db.Column(db.Integer, db.ForeignKey("medication_orders.id"))
    #: The name as it read when decided — the row stays true if the
    #: medicine is renamed later.
    name = db.Column(db.String(200), nullable=False)
    decision = db.Column(db.String(12), nullable=False)
    note = db.Column(db.String(200))
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admission = db.relationship("Admission")
    stay = db.relationship("BedStay")
    home_med = db.relationship("PatientMedication")
    order = db.relationship("MedicationOrder")
    decider = db.relationship("User", foreign_keys=[decided_by])

    @property
    def item_key(self):
        return ("home", self.home_med_id) if self.home_med_id else ("order", self.order_id)
