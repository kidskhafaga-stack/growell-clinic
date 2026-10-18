"""A doctor's own panel template — «my routine exam», filled in one press.

DOCTOR_EASE_PLAN.md أ-٣. Like the quick phrases, but for the specialty
panel: a doctor fills the panel once the way a routine visit usually goes,
saves it under a name, and on the next visit one press fills the **empty**
choices with it; the doctor changes what differs.

**Choices only.** A template never holds a number or a date — a number in a
template would be a reading nobody took. And it holds only answers the
panel still offers: one the catalogue has since dropped is skipped when the
template is used, and said.

A template is the doctor's own, or shared with every doctor who works the
same panel when its owner says so.
"""
from datetime import datetime

from app.extensions import db


class PanelTemplate(db.Model):
    __tablename__ = "panel_templates"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    panel_key = db.Column(db.String(40), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    #: ``{code: answer}`` as JSON — choices only.
    values = db.Column(db.Text, nullable=False, default="{}")
    is_shared = db.Column(db.Boolean, default=False, nullable=False)
    use_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")

    def __repr__(self):
        return f"<PanelTemplate {self.panel_key}:{self.name}>"
