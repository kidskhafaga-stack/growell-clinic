"""Case history brought in from the program a clinic used before this one.

A clinic that has been running for ten years does not start over. It brings its
services and its vaccinations across, attaches them to the patient files, and
corrects them one at a time — which is why these rows are stored as their own
thing rather than being replayed as invoices and visits: they are a record of
what another program said happened, not events this one witnessed.

``source_key`` is what makes a second upload a *comparison* instead of a second
copy. It holds the source program's own row number when the export has one —
measured on a real export as unique across all 9,908 rows with no blanks — and
otherwise a fingerprint of patient, date, time, service and price, which was
also unique across the same file. The time is in that fingerprint deliberately:
without it the same file produces 80 collisions, and 80 rows of history would
be silently dropped as duplicates.
"""
from datetime import datetime

from app.extensions import db


class ImportBatch(db.Model):
    """One upload: who, when, from which file, and how it went.

    Every imported row points at its batch, so an import of ten thousand rows
    against real data has a way back — "undo this import" removes what it
    added and leaves what the clinic has typed since.
    """
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), default="history", nullable=False)
    filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    rows_total = db.Column(db.Integer, default=0, nullable=False)
    rows_added = db.Column(db.Integer, default=0, nullable=False)
    rows_skipped = db.Column(db.Integer, default=0, nullable=False)
    rows_rejected = db.Column(db.Integer, default=0, nullable=False)
    # Whether this batch's money is allowed to appear in the clinic's own
    # money screens, chosen on the preview before anything is written.
    #
    # Per batch rather than a global switch, because the answer differs by
    # batch: a decade of another program's takings is history, and last
    # month's rows — imported because the clinic switched over mid-year — are
    # this year's earnings. One setting could not say both.
    #
    # Off by default. Ten years replayed as revenue counts a decade twice, in
    # the reports and in the accountant's opening balances, and a default that
    # does that quietly is the wrong default.
    count_money = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)

    creator = db.relationship("User")

    def __repr__(self):
        return f"<ImportBatch {self.id} {self.kind} +{self.rows_added}>"


class ImportedService(db.Model):
    """One service or vaccination that happened before this program.

    Deliberately *not* an ``Invoice``. The money on these rows is a decade of
    another program's takings; replaying it as live invoices would count ten
    years of revenue twice, in the reports and in the accountant's opening
    balances. It is history attached to a patient file.
    """
    __tablename__ = "imported_services"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"),
                         nullable=True, index=True)

    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    service_date = db.Column(db.Date, nullable=False, index=True)
    service_time = db.Column(db.Time)
    # What the source called it, kept verbatim: the clinic recognises its own
    # wording, and a mapping that was got wrong can be re-read from this.
    source_name = db.Column(db.String(255), nullable=False)

    # What it was matched to here. Both may be empty while a row is only
    # history — a name and a date is still worth keeping.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=True, index=True)
    vaccine_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                                 nullable=True, index=True)
    dose_number = db.Column(db.Integer)

    quantity = db.Column(db.Integer, default=1, nullable=False)
    price = db.Column(db.Float, default=0, nullable=False)
    doctor_share = db.Column(db.Float, default=0, nullable=False)
    paid_cash = db.Column(db.Float, default=0, nullable=False)
    paid_company = db.Column(db.Float, default=0, nullable=False)
    client_category = db.Column(db.String(30))

    # The key a re-upload is compared against — see the module docstring.
    # Indexed because the comparison runs once per row of a ten-thousand-row
    # file, and an unindexed lookup there is a table scan ten thousand times.
    source_key = db.Column(db.String(120), index=True)
    source_row = db.Column(db.String(40))

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User")
    service = db.relationship("Service")
    brand = db.relationship("VaccineBrand")
    batch = db.relationship("ImportBatch")

    def __repr__(self):
        return f"<ImportedService {self.source_name} {self.service_date}>"
