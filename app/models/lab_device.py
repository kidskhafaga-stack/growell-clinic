"""The laboratory's analysers and the result files they print
(LAB_GLAB360_PLAN.md م-٢ أ — the first step before a live connection).

* ``LabDevice`` — one analyser: its name, and which column of its file holds
  the tube's number, the test code, the value, the unit and its flag. Left
  empty, the columns are found by their usual names.
* ``LabDeviceCode`` — the analyser's own code for a test (``HGB``, ``K``…)
  linked to the analyte it means here. Nothing is linked by guessing.
* ``LabImportRun`` / ``LabImportLine`` — one file read, and each line of it:
  written onto its tube, or held for a person with the reason why.
"""
from datetime import datetime

from app.extensions import db

#: What became of a line. ``applied`` is written; the rest wait for a person.
LINE_STATES = ("applied", "no_sample", "no_code", "not_on_test", "already",
               "empty", "dismissed")
REVIEW_STATES = ("no_sample", "no_code", "not_on_test", "already")


class LabDevice(db.Model):
    __tablename__ = "lab_devices"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    model = db.Column(db.String(120))
    # The file's column headers — empty means «find it by its usual name».
    col_sample = db.Column(db.String(60))
    col_code = db.Column(db.String(60))
    col_value = db.Column(db.String(60))
    col_unit = db.Column(db.String(60))
    col_flag = db.Column(db.String(60))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    codes = db.relationship("LabDeviceCode", back_populates="device",
                            cascade="all, delete-orphan", order_by="LabDeviceCode.code")


class LabDeviceCode(db.Model):
    __tablename__ = "lab_device_codes"
    __table_args__ = (db.UniqueConstraint("device_id", "code", name="uq_lab_device_code"),)

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("lab_devices.id"), nullable=False, index=True)
    code = db.Column(db.String(40), nullable=False)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"), nullable=False)

    device = db.relationship("LabDevice", back_populates="codes")
    analyte = db.relationship("LabAnalyte")


class LabImportRun(db.Model):
    __tablename__ = "lab_import_runs"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("lab_devices.id"), nullable=False, index=True)
    filename = db.Column(db.String(200))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    shape = db.Column(db.String(8))          # "long" (a row per test) | "wide" (a row per tube)

    device = db.relationship("LabDevice")
    by = db.relationship("User")
    lines = db.relationship("LabImportLine", back_populates="run",
                            cascade="all, delete-orphan", order_by="LabImportLine.row_no")


class LabImportLine(db.Model):
    __tablename__ = "lab_import_lines"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("lab_import_runs.id"), nullable=False, index=True)
    row_no = db.Column(db.Integer, nullable=False)
    sample_code = db.Column(db.String(40))
    code = db.Column(db.String(40))
    raw_value = db.Column(db.String(120))
    unit = db.Column(db.String(30))
    flag = db.Column(db.String(30))          # the analyser's own: H, L, *, a sample warning
    state = db.Column(db.String(12), nullable=False, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"), index=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"))
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(160))

    run = db.relationship("LabImportRun", back_populates="lines")
    order = db.relationship("VisitInvestigation")
    analyte = db.relationship("LabAnalyte")
