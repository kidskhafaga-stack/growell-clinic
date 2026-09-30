"""Treatment given in the emergency department to a child with no bed.

Asked as *«الناس الى داخله الطوارئ تنفذ علاج معين ومش هتاخد اقامة»* — the
child who comes for an injection, a nebuliser session, a dressing, and goes
home. A child in an emergency *bed* has a stay, and the stay has had orders
and doses for a long time (`MedicationOrder`). The child with no bed had an
attendance (`EmergencyVisit`) and nowhere to write what was given.

**Who the order comes from is the whole of the rule**, and there are three:

* ``ours`` — written here by one of our doctors, who is then the prescriber;
* ``hospital_rx`` — a paper prescription by a doctor who works here, or a
  contracted doctor with an account. The nurse gives it straight away and the
  line carries that doctor's name. If that doctor is in the building at that
  moment they are asked to confirm it; if not, it stays on the file under
  their name, and nobody chases them for it later;
* ``outside_rx`` — a prescription from a doctor who is not ours. It **cannot
  be given** until one of our doctors has seen the child and approved it,
  and the line keeps whose prescription it came from. The doctor may decide
  on something else entirely — a bed, a theatre, the nursery — and those
  exits already exist.

In the doctor's words: *«الدكتور لازم يبص على الحالة الاول ولو طبيب من
المستشفى بتنفذ العلاج على طول وتكتب اسم الطبيب ولو طبيب خارجي مش متعاقد مع
المستشفى لازم الطبيب يكتب اوردر ويكتب ويتاكد وانها جايه من دكتور فلان»*.

**One row is one thing given once.** An emergency attendance is hours, not
days; a drug given every six hours is a stay, and the stay's orders are the
place for it.
"""
from datetime import datetime

from app.extensions import db

OURS, HOSPITAL_RX, OUTSIDE_RX = "ours", "hospital_rx", "outside_rx"
SOURCES = (OURS, HOSPITAL_RX, OUTSIDE_RX)


class EmergencyOrder(db.Model):
    """One drug, service or supply, given once, to a child in emergency."""

    __tablename__ = "emergency_orders"

    id = db.Column(db.Integer, primary_key=True)
    emergency_visit_id = db.Column(db.Integer,
                                   db.ForeignKey("emergency_visits.id"),
                                   nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # ---- what ------------------------------------------------------------
    # A drug by the catalogue and always by the name the person saw, or a
    # service (a nebuliser session, an IM injection, a dressing). Both may be
    # set — «IM injection» of «Ceftriaxone 500 mg».
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"))
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"))
    name = db.Column(db.String(200), nullable=False)
    dose = db.Column(db.String(80))
    route = db.Column(db.String(16))
    # What comes off the shelf when it is given, and how many. Empty, and it
    # is charted and given and touches neither the stock nor the bill —
    # exactly like a ward order with no shelf behind it.
    store_item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"))
    units = db.Column(db.Integer, default=1, nullable=False)
    note = db.Column(db.String(255))

    # ---- whose -----------------------------------------------------------
    source = db.Column(db.String(12), nullable=False, default=OURS)
    #: Our doctor whose order it is — the writer for ``ours``, the doctor on
    #: the paper for ``hospital_rx``. Empty for ``outside_rx``.
    prescriber_id = db.Column(db.Integer, db.ForeignKey("users.id"),
                              index=True)
    #: The outside doctor's name, as the paper says it.
    outside_doctor = db.Column(db.String(120))
    #: Our doctor who saw the child and approved an outside prescription.
    #: Nothing from outside is given before this.
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    #: A hospital doctor's paper, given in their name: asked to confirm only
    #: when they were in the building at the moment it was entered.
    confirm_asked = db.Column(db.Boolean, default=False, nullable=False)
    confirmed_at = db.Column(db.DateTime)

    # ---- what happened ---------------------------------------------------
    given_at = db.Column(db.DateTime, index=True)
    given_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancel_reason = db.Column(db.String(200))

    #: Who typed it in — a nurse entering a paper, or the doctor writing.
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)

    #: The bill line it went onto, once charged — asking twice charges once.
    #: The service's line when there is a service; otherwise the drug's.
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                                index=True)
    #: The drug or supply on a line of its own beside the service, when the
    #: service does not include it (`Service.supplies_mode`).
    item_invoice_item_id = db.Column(db.Integer,
                                     db.ForeignKey("invoice_items.id"))
    #: What it took off the shelf, once — whether or not it was charged.
    stock_movement_id = db.Column(db.Integer,
                                  db.ForeignKey("stock_movements.id"))

    emergency_visit = db.relationship("EmergencyVisit",
                                      backref="orders")
    patient = db.relationship("Patient")
    drug = db.relationship("Drug")
    service = db.relationship("Service")
    store_item = db.relationship("StoreItem")
    prescriber = db.relationship("User", foreign_keys=[prescriber_id])
    approver = db.relationship("User", foreign_keys=[approved_by])
    giver = db.relationship("User", foreign_keys=[given_by])
    enterer = db.relationship("User", foreign_keys=[entered_by])

    @property
    def state(self):
        """``cancelled`` · ``given`` · ``waiting_doctor`` · ``ready``."""
        if self.cancelled_at is not None:
            return "cancelled"
        if self.given_at is not None:
            return "given"
        if self.source == OUTSIDE_RX and self.approved_at is None:
            return "waiting_doctor"
        return "ready"

    @property
    def billed(self):
        return self.invoice_item_id is not None

    @property
    def may_give(self):
        return self.state == "ready"

    @property
    def awaiting_confirmation(self):
        return (self.source == HOSPITAL_RX and self.confirm_asked
                and self.confirmed_at is None and self.cancelled_at is None)

    def __repr__(self):
        return f"<EmergencyOrder {self.name} {self.state}>"
