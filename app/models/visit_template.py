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
    # **The rest of the ready visit** (ب-١, the part left for later): the
    # tests it orders (catalogue ids, JSON), what the family is told on the
    # way out, the follow-up in days, and the specialty panel's own template.
    # On the visit they are offered beside the boxes and land only when the
    # doctor saves — never ordered by the press itself.
    tests = db.Column(db.Text)
    family_instructions = db.Column(db.Text)
    followup_days = db.Column(db.Integer)
    panel_template_id = db.Column(db.Integer, db.ForeignKey("panel_templates.id"), nullable=True)
    is_shared = db.Column(db.Boolean, default=False, nullable=False)
    use_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    rx_preset = db.relationship("RxPreset")
    panel_template = db.relationship("PanelTemplate")

    @property
    def test_ids(self):
        import json

        try:
            data = json.loads(self.tests or "[]")
        except (TypeError, ValueError):
            return []
        return [int(x) for x in data if str(x).isdigit()]

    def visible_to(self, user):
        return self.is_shared or (user is not None and self.doctor_id == user.id)

    def __repr__(self):
        return f"<VisitTemplate {self.name}>"
