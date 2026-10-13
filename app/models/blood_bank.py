"""The hospital's blood store, supplied from outside — GAHAR DAS.28, DAS.29
and DAS.30.

The hospital does not collect or test blood (DAS.26 and DAS.27 do not
apply); it receives units from a contracted blood bank, keeps them, and issues
them to a child. So:

* a **supplier** — selected and evaluated, with the agreement's validity and
  the acceptance criteria every unit is received against (DAS.29);
* a **unit** — received only with the label's nine elements (DAS.28 a–i) and
  an inspection on arrival: the transport, the label, the group confirmed for
  red cells (DAS.29 d); kept until it is issued, returned or discarded;
* an **issue** — against an open request, only compatible on cross-match for
  whole blood and red cells and only after the bag was looked at (DAS.30 a,
  e), with who did it and the segment number (c, d).

A unit is traced from receipt to the transfusion that used it by its number
(DAS.28 ev. 3).
"""
from datetime import datetime

from app.extensions import db

ABO = ("A", "B", "AB", "O")
RH = ("pos", "neg")
STATES = ("stored", "issued", "transfused", "discarded", "rejected")
#: The components DAS.30 (a) cross-matches.
CROSSMATCHED = ("whole", "prbc")


class BloodSupplier(db.Model):
    __tablename__ = "blood_suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    accreditation = db.Column(db.String(160))
    agreement_until = db.Column(db.Date)
    #: DAS.29 (c) — the agreement's terms as written: scope, storage and
    #: transport, look-back, disputes.
    agreement = db.Column(db.Text)
    #: DAS.29 (c v) — the acceptance criteria every unit is received against.
    acceptance = db.Column(db.Text)
    evaluated_on = db.Column(db.Date)
    evaluation_note = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class BloodUnit(db.Model):
    __tablename__ = "blood_units"

    id = db.Column(db.Integer, primary_key=True)
    #: (a) the traceable number.
    unit_number = db.Column(db.String(64), nullable=False, unique=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("blood_suppliers.id"), nullable=False)
    product = db.Column(db.String(16), nullable=False)
    volume_ml = db.Column(db.Integer)
    abo = db.Column(db.String(2), nullable=False)
    rh = db.Column(db.String(3), nullable=False)
    seronegative = db.Column(db.Boolean, nullable=False)
    anticoagulant = db.Column(db.String(60))
    storage = db.Column(db.String(120), nullable=False)
    collected_on = db.Column(db.Date, nullable=False)
    expires_on = db.Column(db.Date, nullable=False, index=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: DAS.29 (d) the inspection on arrival.
    transport_ok = db.Column(db.Boolean, nullable=False)
    label_ok = db.Column(db.Boolean, nullable=False)
    abo_confirmed = db.Column(db.Boolean)
    reject_reason = db.Column(db.String(200))
    status = db.Column(db.String(12), nullable=False, default="stored", index=True)
    #: DAS.30 — the issue.
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), index=True)
    segment_number = db.Column(db.String(40))
    crossmatch_compatible = db.Column(db.Boolean)
    crossmatch_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    visual_ok = db.Column(db.Boolean)
    issued_at = db.Column(db.DateTime)
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: (f) returned to the store — reissued, or not.
    returned_at = db.Column(db.DateTime)
    returned_note = db.Column(db.String(200))
    discarded_at = db.Column(db.DateTime)
    discard_reason = db.Column(db.String(200))

    supplier = db.relationship("BloodSupplier")
    request = db.relationship("BloodRequest")
    issuer = db.relationship("User", foreign_keys=[issued_by])
    matcher = db.relationship("User", foreign_keys=[crossmatch_by])
