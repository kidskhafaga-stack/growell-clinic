"""Database models for GROWELL CLINIC.

Phase 1 establishes the foundation models (users, settings, activity log).
Later phases add the clinical and financial domain models. Importing them
here ensures SQLAlchemy registers every table when ``db.create_all()`` runs.
"""
from app.models.activity_log import ActivityLog
from app.models.appointment import (
    ACTIVE_STATUSES,
    APPOINTMENT_STATUSES,
    STATUS_TRANSITIONS,
    Appointment,
)
from app.models.doctor_schedule import WEEKDAY_ORDER, DoctorSchedule
from app.models.family import Family
from app.models.diagnosis import DIAGNOSIS_TYPES, ICD_VERSIONS, Diagnosis
from app.models.growth_record import GrowthRecord
from app.models.parent import (
    CLIENT_CATEGORIES,
    PARENT_RELATIONS,
    Parent,
)
from app.models.patient import BLOOD_TYPES, GENDERS, Patient
from app.models.permissions import MODULES, ROLE_PERMISSIONS, ROLES
from app.models.setting import Setting
from app.models.user import User
from app.models.visit import VISIT_STATUSES, Visit
from app.models.vital_signs import VitalSigns
from app.models.vaccine import (
    PatientVaccine,
    Vaccine,
    VaccineBrand,
    VaccineBrandDose,
)
from app.models.inventory import (
    LOW_STOCK_QTY,
    NEAR_EXPIRY_DAYS,
    Supplier,
    VaccineInventory,
)
from app.models.service import (
    COMMISSION_TYPES,
    SERVICE_CATEGORIES,
    DoctorServiceCommission,
    Service,
    ServiceBundleItem,
)
from app.models.invoice import (
    INVOICE_STATUSES,
    PAYMENT_METHODS,
    Invoice,
    InvoiceItem,
    Payment,
)

__all__ = [
    "User",
    "Setting",
    "ActivityLog",
    "Family",
    "Parent",
    "Patient",
    "Appointment",
    "DoctorSchedule",
    "Visit",
    "VitalSigns",
    "Diagnosis",
    "GrowthRecord",
    "ROLES",
    "MODULES",
    "ROLE_PERMISSIONS",
    "PARENT_RELATIONS",
    "CLIENT_CATEGORIES",
    "GENDERS",
    "BLOOD_TYPES",
    "APPOINTMENT_STATUSES",
    "ACTIVE_STATUSES",
    "STATUS_TRANSITIONS",
    "WEEKDAY_ORDER",
    "VISIT_STATUSES",
    "DIAGNOSIS_TYPES",
    "ICD_VERSIONS",
    "Vaccine",
    "VaccineBrand",
    "VaccineBrandDose",
    "PatientVaccine",
    "Supplier",
    "VaccineInventory",
    "NEAR_EXPIRY_DAYS",
    "LOW_STOCK_QTY",
    "Service",
    "ServiceBundleItem",
    "DoctorServiceCommission",
    "SERVICE_CATEGORIES",
    "COMMISSION_TYPES",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "INVOICE_STATUSES",
    "PAYMENT_METHODS",
]
