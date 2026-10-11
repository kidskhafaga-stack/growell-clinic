"""Two files for one child, made one — and the record of how, so it can be undone.

A child registered twice — a different spelling at the desk, a birthday
typed a year out, an emergency file opened before anyone asked for the old
number — has half a history in each. The doctor reads one half.

A merge **keeps one file** and moves everything the other file had onto it:
every row in every table that points at a patient (found from the database
itself, so a table added later is moved too). The other file is not deleted:
it is archived with ``archive_reason = "merged"`` and ``merged_into``
pointing at the kept one, so an old file number on a paper still leads
somewhere.

**Every moved row is written down here**, table by table, and every field
of the kept file the merge filled or added to, with what it held before —
so a merge done on the wrong pair is undone exactly, not guessed back.
"""
from datetime import datetime

from app.extensions import db


class PatientMerge(db.Model):
    __tablename__ = "patient_merges"

    id = db.Column(db.Integer, primary_key=True)
    keep_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    drop_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    #: As the dropped file was, for the history — its number and name.
    drop_number = db.Column(db.String(40))
    drop_name = db.Column(db.String(120))
    reason = db.Column(db.Text)
    #: JSON ``{"table.column": [row ids]}`` — what moved.
    moved = db.Column(db.Text)
    #: JSON ``{"table.column": [row ids]}`` — left on the dropped file
    #: because the kept file already had its one (a vaccine's plan, a panel).
    left = db.Column(db.Text)
    #: JSON ``{field: value before}`` — the kept file's fields the merge
    #: filled or added to.
    fields = db.Column(db.Text)
    #: JSON — the dropped file's archive state before, to give it back.
    drop_state = db.Column(db.Text)

    merged_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    merged_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    undone_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    undone_at = db.Column(db.DateTime)

    keep = db.relationship("Patient", foreign_keys=[keep_id])
    drop = db.relationship("Patient", foreign_keys=[drop_id])
    merger = db.relationship("User", foreign_keys=[merged_by])
    undoer = db.relationship("User", foreign_keys=[undone_by])

    @property
    def is_undone(self):
        return self.undone_at is not None
