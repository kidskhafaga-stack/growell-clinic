"""Clinic services, pricing & doctor commissions (Finance foundation).

A ``Service`` is any chargeable item in the clinic (consultation, procedure,
vaccination fee, booking…). Each carries a price, an optional max discount and
a default doctor commission (percentage or fixed amount). Commissions can be
overridden per doctor. Services may be bundled (e.g. a booking + a vaccination
fee sold together).
"""
from datetime import datetime

from app.extensions import db

SERVICE_CATEGORIES = [
    "consultation", "procedure", "vaccination_fee", "booking",
    "lab", "radiology", "other",
]
COMMISSION_TYPES = ["none", "percent", "fixed"]


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    code = db.Column(db.String(40))
    category = db.Column(db.String(40), default="other", nullable=False)
    price = db.Column(db.Float, default=0, nullable=False)
    max_discount = db.Column(db.Float)  # max allowed discount (%)

    # Default doctor commission for this service.
    commission_type = db.Column(db.String(10), default="none", nullable=False)
    commission_value = db.Column(db.Float, default=0)

    is_bundle = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    bundle_items = db.relationship(
        "ServiceBundleItem", back_populates="bundle",
        foreign_keys="ServiceBundleItem.bundle_id",
        cascade="all, delete-orphan",
    )
    doctor_commissions = db.relationship(
        "DoctorServiceCommission", back_populates="service",
        cascade="all, delete-orphan",
    )

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def commission_for(self, doctor=None):
        """Return (type, value) for a doctor, honouring per-doctor overrides."""
        if doctor is not None:
            for oc in self.doctor_commissions:
                if oc.doctor_id == doctor.id:
                    return oc.commission_type, (oc.commission_value or 0)
        return self.commission_type, (self.commission_value or 0)

    def doctor_share(self, amount, doctor=None):
        """Doctor's cut of ``amount`` for this service (never exceeds amount)."""
        ctype, cval = self.commission_for(doctor)
        if ctype == "percent":
            return round(max(amount, 0) * (cval or 0) / 100.0, 2)
        if ctype == "fixed":
            return round(min(cval or 0, max(amount, 0)), 2)
        return 0.0

    def clinic_share(self, amount, doctor=None):
        return round(max(amount, 0) - self.doctor_share(amount, doctor), 2)

    @property
    def bundle_price(self):
        """For a bundle, the sum of its components' prices (reference value)."""
        return round(sum((bi.component.price or 0) * (bi.quantity or 1)
                         for bi in self.bundle_items if bi.component), 2)

    def __repr__(self):
        return f"<Service {self.name}>"


class ServiceBundleItem(db.Model):
    """A component service inside a bundle service."""
    __tablename__ = "service_bundle_items"

    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    component_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)

    bundle = db.relationship("Service", back_populates="bundle_items", foreign_keys=[bundle_id])
    component = db.relationship("Service", foreign_keys=[component_id])

    def __repr__(self):
        return f"<BundleItem bundle={self.bundle_id} comp={self.component_id}>"


class DoctorServiceCommission(db.Model):
    """Per-doctor override of a service's commission."""
    __tablename__ = "doctor_service_commissions"
    __table_args__ = (
        db.UniqueConstraint("doctor_id", "service_id", name="uq_doctor_service"),
    )

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    commission_type = db.Column(db.String(10), default="none", nullable=False)
    commission_value = db.Column(db.Float, default=0)

    doctor = db.relationship("User")
    service = db.relationship("Service", back_populates="doctor_commissions")

    def __repr__(self):
        return f"<DocCommission doc={self.doctor_id} svc={self.service_id}>"
