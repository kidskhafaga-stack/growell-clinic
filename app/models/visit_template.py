"""A ready visit for a common complaint — DOCTOR_EASE_PLAN.md ب-١.

«التهاب لوز بكتيري», «نزلة معوية بجفاف بسيط»: the complaint, the
examination and the plan the doctor writes for it nine times out of ten,
saved once under a name. On the visit screen one press fills the **empty**
boxes — never over what the doctor already wrote — and, when the template
names one of the doctor's ready prescriptions (``RxPreset``: diagnosis and
medicines), «write the prescription» opens with it applied: the doses are
worked out for this child's weight by the prescription screen, never stored
here.

The doctor's own, or shared with the clinic when its owner says so.
"""
from datetime import datetime

from app.extensions import db


class VisitTemplate(db.Model):
    __tablename__ = "visit_templates"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    chief_complaint = db.Column(db.Text)
    clinical_exam = db.Column(db.Text)
    plan = db.Column(db.Text)
    rx_preset_id = db.Column(db.Integer, db.ForeignKey("rx_presets.id"), nullable=True)
    is_shared = db.Column(db.Boolean, default=False, nullable=False)
    use_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    rx_preset = db.relationship("RxPreset")

    def visible_to(self, user):
        return self.is_shared or (user is not None and self.doctor_id == user.id)

    def __repr__(self):
        return f"<VisitTemplate {self.name}>"
