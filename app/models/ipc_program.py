"""Infection control's program — surveillance, care bundles, the committee.

GAHAR IPC.17, IPC.11 and IPC.03, the three the program can carry beyond
the alert organisms (`models/micro.IpcAlert`):

* **Surveillance (IPC.17)** — a case of healthcare-associated infection is
  written down with what it is (the four the standard names: CLABSI, CAUTI,
  VAP, SSI — or another, said in words), where and when it began, and by
  whose criteria it was confirmed. *"Setting criteria to define HAIs"* is the
  committee's job (IPC.03 a), so the program holds no definition: a case is
  ``suspected`` until somebody holding ``infection_control`` confirms or
  rules it out. Rates are counted against the device-days and patient-days
  the program already has (`models/line`, `models/admission`).
* **Care bundles (IPC.11)** — the hospital writes its own bundles and their
  three-to-five elements; nothing is preset. A check is filed for a line or a
  stay on a day, every element answered, and it is met only if every element
  is — *"all or none"*, in the standard's words.
* **The committee (IPC.03)** — a monthly meeting with who attended, the
  minutes, and the decisions, each with an owner and a date, followed up
  until done; and the quarter's surveillance report marked as reviewed
  (IPC.17 ev. 3).
"""
from datetime import datetime

from app.extensions import db

#: IPC.11 a–d by name; ``other`` is said in words.
HAI_KINDS = ("clabsi", "cauti", "vap", "ssi", "other")
HAI_STATUSES = ("suspected", "confirmed", "ruled_out")
#: Which kinds of line a device-associated infection is counted against —
#: the line kinds the program already records (`models/line`). VAP has no
#: ventilator line here and SSI no device, so they are counted without one.
DEVICE_LINES = {"clabsi": ("central", "umbilical"), "cauti": ("urinary",)}
BUNDLE_SCOPES = ("line", "stay")
ANSWERS = ("yes", "no", "na")


class HaiCase(db.Model):
    __tablename__ = "hai_cases"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    line_id = db.Column(db.Integer, db.ForeignKey("lines.id"))
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"), index=True)
    kind = db.Column(db.String(10), nullable=False, index=True)
    kind_note = db.Column(db.String(120))
    onset_on = db.Column(db.Date, nullable=False, index=True)
    organism = db.Column(db.String(160))
    #: Which of the hospital's criteria were met — in its own words.
    criteria = db.Column(db.Text)
    status = db.Column(db.String(10), default="suspected", nullable=False, index=True)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)
    decision_note = db.Column(db.Text)

    patient = db.relationship("Patient")
    unit = db.relationship("Unit")
    line = db.relationship("Line")
    reporter = db.relationship("User", foreign_keys=[reported_by])
    decider = db.relationship("User", foreign_keys=[decided_by])


class CareBundle(db.Model):
    __tablename__ = "care_bundles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    #: Which infection it prevents (IPC.11 a–d, or other).
    kind = db.Column(db.String(10), nullable=False)
    #: ``line`` — checked on each line of the kinds below; ``stay`` — on a
    #: child's stay (a ventilated child, a wound).
    scope = db.Column(db.String(6), default="line", nullable=False)
    line_kinds = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    elements = db.relationship("BundleElement", back_populates="bundle",
                               order_by="BundleElement.sort_order",
                               cascade="all, delete-orphan")

    @property
    def kinds(self):
        return [k for k in (self.line_kinds or "").split(",") if k]


class BundleElement(db.Model):
    __tablename__ = "bundle_elements"

    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey("care_bundles.id"), nullable=False, index=True)
    text = db.Column(db.String(255), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    bundle = db.relationship("CareBundle", back_populates="elements")


class BundleCheck(db.Model):
    """One bundle checked on one line or stay on one day."""
    __tablename__ = "bundle_checks"

    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey("care_bundles.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), index=True)
    line_id = db.Column(db.Integer, db.ForeignKey("lines.id"), index=True)
    checked_on = db.Column(db.Date, nullable=False, index=True)
    #: JSON ``{element_id: "yes"|"no"|"na"}`` — the elements as they were.
    answers = db.Column(db.Text, nullable=False)
    #: All or none: every element answered yes (or not applicable).
    all_met = db.Column(db.Boolean, nullable=False)
    note = db.Column(db.String(255))
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    checked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    bundle = db.relationship("CareBundle")
    patient = db.relationship("Patient")
    checker = db.relationship("User", foreign_keys=[checked_by])


class IpcMeeting(db.Model):
    __tablename__ = "ipc_meetings"

    id = db.Column(db.Integer, primary_key=True)
    held_on = db.Column(db.Date, nullable=False, index=True)
    #: Who attended and from which discipline, as the minutes list them.
    attendees = db.Column(db.Text, nullable=False)
    minutes = db.Column(db.Text, nullable=False)
    #: The quarter whose surveillance report this meeting reviewed
    #: (``2026-Q3``) — IPC.17 ev. 3.
    surveillance_quarter = db.Column(db.String(7))
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    decisions = db.relationship("IpcDecision", back_populates="meeting",
                                order_by="IpcDecision.id", cascade="all, delete-orphan")
    writer = db.relationship("User", foreign_keys=[written_by])


class IpcDecision(db.Model):
    __tablename__ = "ipc_decisions"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("ipc_meetings.id"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    owner = db.Column(db.String(120), nullable=False)
    due_on = db.Column(db.Date)
    done_at = db.Column(db.DateTime)
    done_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    done_note = db.Column(db.String(255))

    meeting = db.relationship("IpcMeeting", back_populates="decisions")
    closer = db.relationship("User", foreign_keys=[done_by])
