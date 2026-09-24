"""Managing implantable devices — GAHAR SAS.11, the rest of it.

*"The hospital has a system for managing implantable devices, including
recall."* The two halves every case touches were already here: the implant
confirmed in the room (SAS.06 ز) and what went into the child with its batch
number (`OperationImplant`), with a screen that finds the children by batch.
The standard asks for a *system* of eight parts around those, and these are
the parts a record can hold:

(a)+(b) **The hospital's list** (:class:`ImplantDevice`) — evidence 2, *"a
        list of implantable devices used in the hospital"*. Each entry names
        its **primary source**, because the intent asks for tracking *"from
        its primary source"*, and who approved it onto the list, which is the
        selection. Empty until the hospital writes it: which plates a
        children's theatre uses is its decision, not the program's.
(c)     **Who fitted it** — hospital staff or the company's representative —
        on the implant row itself.
(e)+(g) **Adverse events and malfunctions** (:class:`ImplantEvent`), each
        with where it was reported, when and under what reference. One that
        was noted and never reported stays visible until it is.
(h)     **Discharge instructions** — written by the hospital against the
        device, and the moment somebody gave them to the family recorded on
        the case.
(f)     **Recall** (:class:`ImplantRecall`) — evidence 5, and the intent's
        *"reachable within a defined time frame"*. A search answers "which
        children"; a recall is the process after it: who was reached, who
        was not, and whether that happened inside the hospital's own time
        frame (:data:`RECALL_HOURS_SETTING`, empty until it sets one — the
        program does not choose how fast a hospital must reach a family).
"""
from datetime import datetime

from app.extensions import db

#: (e) an adverse event in the child · (g) the device failing.
EVENT_KINDS = ("adverse", "malfunction")

#: What a call to a family came to. Two words, because the only question
#: the recall asks of each child is "reached or not yet".
CONTACT_OUTCOMES = ("reached", "not_reached")

#: The hospital's time frame for reaching every child on a recall, in hours.
#: A `Setting`, unset until the hospital writes one.
RECALL_HOURS_SETTING = "implant_recall_hours"


class ImplantDevice(db.Model):
    """One entry on the hospital's list of implantable devices."""

    __tablename__ = "implant_devices"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    manufacturer = db.Column(db.String(120))
    #: (b) the primary source — the supplier it is bought from. What a trace
    #: back from a defective batch starts at.
    supplier = db.Column(db.String(160))
    #: (h) what the family is told when the child goes home, infection
    #: prevention included. The hospital's words; empty until written.
    instructions = db.Column(db.Text)
    note = db.Column(db.String(200))
    #: (a) the selection: who put it on the list, and when.
    approved_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: Retired, never deleted — a child implanted with it last year still
    #: points at this row.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    approver = db.relationship("User", foreign_keys=[approved_by])

    def __repr__(self):
        return f"<ImplantDevice {self.name!r}>"


class ImplantEvent(db.Model):
    """An adverse event or a malfunction, against one implant in one child."""

    __tablename__ = "implant_events"

    id = db.Column(db.Integer, primary_key=True)
    implant_id = db.Column(db.Integer, db.ForeignKey("operation_implants.id"),
                           nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    description = db.Column(db.Text, nullable=False)
    noted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    noted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: Where it was reported, when, and the reference that came back. Kept
    #: as the record of a report, not a checkbox: a surveyor asking "was it
    #: reported" is asking to whom.
    reported_to = db.Column(db.String(160))
    reported_at = db.Column(db.DateTime)
    reference = db.Column(db.String(80))
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    implant = db.relationship("OperationImplant", backref=db.backref(
        "events", order_by="ImplantEvent.noted_at",
        cascade="all, delete-orphan"))
    noter = db.relationship("User", foreign_keys=[noted_by])
    reporter = db.relationship("User", foreign_keys=[reported_by])

    @property
    def reported(self):
        return self.reported_at is not None


class ImplantRecall(db.Model):
    """One recall notice, and the work of reaching every child it names."""

    __tablename__ = "implant_recalls"

    id = db.Column(db.Integer, primary_key=True)
    #: The notice itself, as it arrived — the manufacturer's or the
    #: authority's words.
    notice = db.Column(db.String(255), nullable=False)
    #: What it names. The same four fields the recall search takes; the
    #: children are found again from these each time, so a child recorded
    #: late with the same batch is not missed.
    name = db.Column(db.String(160))
    lot = db.Column(db.String(60))
    serial = db.Column(db.String(60))
    manufacturer = db.Column(db.String(120))
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    close_note = db.Column(db.String(255))

    opener = db.relationship("User", foreign_keys=[opened_by])
    closer = db.relationship("User", foreign_keys=[closed_by])

    @property
    def terms(self):
        return {"name": self.name, "lot": self.lot, "serial": self.serial,
                "manufacturer": self.manufacturer}


class ImplantRecallContact(db.Model):
    """One attempt to reach one child's family about one recall."""

    __tablename__ = "implant_recall_contacts"

    id = db.Column(db.Integer, primary_key=True)
    recall_id = db.Column(db.Integer, db.ForeignKey("implant_recalls.id"),
                          nullable=False, index=True)
    implant_id = db.Column(db.Integer, db.ForeignKey("operation_implants.id"),
                           nullable=False, index=True)
    outcome = db.Column(db.String(12), nullable=False)
    note = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    recall = db.relationship("ImplantRecall", backref=db.backref(
        "contacts", order_by="ImplantRecallContact.at",
        cascade="all, delete-orphan"))
    by = db.relationship("User")
