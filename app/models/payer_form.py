"""A payer's own form, laid out once — CONTRACTS_PLAN.md ع-٣.

*«يعمل دروب اند دراج للبيانات فى صفحة التعاقد بحيث يطبع الاستمارة مع كل كشف
او حجز»*. Whoever runs the contracts uploads the company's blank form (a scan
or a photo), and drags the program's facts onto it — the child's name, the
membership number, the diagnosis and its code, the kind of service, the
approval number, the doctor, the date. Each lands at a place in millimetres
on the page, so the form prints filled for any visit, booking or approval on
that company, and the doctor only signs.

Printed on blank paper with the scan behind it, or — for the company's own
printed forms — the facts alone, in their places (the prescription's
«ورق مطبوع» the same way).
"""
import json
from datetime import datetime

from app.extensions import db


class PayerForm(db.Model):
    __tablename__ = "payer_forms"

    id = db.Column(db.Integer, primary_key=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    #: The department it is for (``utils/care_setting``), or every one.
    setting = db.Column(db.String(12))
    width_mm = db.Column(db.Integer, nullable=False, default=210)
    height_mm = db.Column(db.Integer, nullable=False, default=297)
    #: The blank form, scanned (``uploads/patient_docs``).
    background = db.Column(db.String(80))
    #: Print the scan behind the facts (plain paper), or the facts alone
    #: (the company's own printed form in the tray).
    print_background = db.Column(db.Boolean, nullable=False, default=True)
    #: ``[{key, x, y, w, size, align}]`` — millimetres and points.
    fields = db.Column(db.Text, nullable=False, default="[]")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payer = db.relationship("PayerEntity")

    @property
    def layout(self):
        try:
            data = json.loads(self.fields or "[]")
        except (TypeError, ValueError):
            return []
        return data if isinstance(data, list) else []
