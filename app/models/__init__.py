"""Database models for GROWELL CLINIC.

Phase 1 establishes the foundation models (users, settings, activity log).
Later phases add the clinical and financial domain models. Importing them
here ensures SQLAlchemy registers every table when ``db.create_all()`` runs.
"""
from app.models.activity_log import ActivityLog
from app.models.appointment import (
    ACTIVE_STATUSES,
    APPOINTMENT_STATUSES,
    APPOINTMENT_TYPES,
    DEFAULT_APPT_TYPE,
    STATUS_TRANSITIONS,
    Appointment,
    type_minutes,
)
from app.models.doctor_schedule import WEEKDAY_ORDER, DoctorSchedule
from app.models.schedule_exception import ScheduleException
from app.models.waitlist import WAITLIST_STATUSES, WaitlistEntry
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
from app.models.role import Role
from app.models.setting import Setting
from app.models.user import User
from app.models.visit import (
    INVESTIGATION_STATUSES,
    VISIT_STATUSES,
    PatientAttachment,
    Visit,
    VisitInvestigation,
)
from app.models.vital_signs import VitalSigns
from app.models.vaccine import (
    PatientVaccine,
    VACCINE_EVENT_TYPES,
    VACCINE_ROUTES,
    Vaccine,
    VaccineBrand,
    VaccineBrandDose,
    VaccineScheduleDose,
    VaccineScheduleTemplate,
)
from app.models.inventory import (
    LOW_STOCK_QTY,
    NEAR_EXPIRY_DAYS,
    Supplier,
    VaccineInventory,
)
from app.models.service import (
    COMMISSION_TYPES,
    ETA_ITEM_TYPES,
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
from app.models.payer import (
    COVERAGE_TYPES,
    PAYER_TYPES,
    PatientCoverage,
    PayerContract,
    PayerEntity,
    PayerServiceRate,
)
from app.models.einvoice import EINVOICE_STATUSES, EInvoiceDocument
from app.models.prescription import (
    DRUG_FORMS,
    INVESTIGATION_KINDS,
    RX_PAGE_SIZES,
    Drug,
    DrugInteraction,
    Investigation,
    Prescription,
    PrescriptionInvestigation,
    PrescriptionItem,
    RxPrintTemplate,
)
from app.models.message import (
    DEFAULT_BIRTHDAY_BODY,
    MESSAGE_STATUSES,
    OCCASION_TYPES,
    SYSTEM_TEMPLATE_TYPES,
    TEMPLATE_DEFAULTS,
    TEMPLATE_VARIABLES,
    MessageLog,
    MessageTemplate,
)
from app.models.store import MOVEMENT_KINDS, StockMovement, StoreItem

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
    "VisitInvestigation",
    "PatientAttachment",
    "INVESTIGATION_STATUSES",
    "VitalSigns",
    "Diagnosis",
    "GrowthRecord",
    "ROLES",
    "Role",
    "MODULES",
    "ROLE_PERMISSIONS",
    "PARENT_RELATIONS",
    "CLIENT_CATEGORIES",
    "GENDERS",
    "BLOOD_TYPES",
    "APPOINTMENT_STATUSES",
    "APPOINTMENT_TYPES",
    "DEFAULT_APPT_TYPE",
    "type_minutes",
    "ACTIVE_STATUSES",
    "STATUS_TRANSITIONS",
    "ScheduleException",
    "WaitlistEntry",
    "WAITLIST_STATUSES",
    "WEEKDAY_ORDER",
    "VISIT_STATUSES",
    "DIAGNOSIS_TYPES",
    "ICD_VERSIONS",
    "Vaccine",
    "VaccineBrand",
    "VaccineBrandDose",
    "VaccineScheduleTemplate",
    "VaccineScheduleDose",
    "PatientVaccine",
    "VACCINE_ROUTES",
    "VACCINE_EVENT_TYPES",
    "Supplier",
    "VaccineInventory",
    "NEAR_EXPIRY_DAYS",
    "LOW_STOCK_QTY",
    "Service",
    "ServiceBundleItem",
    "DoctorServiceCommission",
    "SERVICE_CATEGORIES",
    "COMMISSION_TYPES",
    "ETA_ITEM_TYPES",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "INVOICE_STATUSES",
    "PAYMENT_METHODS",
    "PayerEntity",
    "PayerServiceRate",
    "PayerContract",
    "PatientCoverage",
    "PAYER_TYPES",
    "COVERAGE_TYPES",
    "EInvoiceDocument",
    "EINVOICE_STATUSES",
    "Drug",
    "DrugInteraction",
    "Investigation",
    "Prescription",
    "PrescriptionItem",
    "PrescriptionInvestigation",
    "RxPrintTemplate",
    "DRUG_FORMS",
    "INVESTIGATION_KINDS",
    "RX_PAGE_SIZES",
    "MessageLog",
    "MessageTemplate",
    "MESSAGE_STATUSES",
    "OCCASION_TYPES",
    "SYSTEM_TEMPLATE_TYPES",
    "TEMPLATE_DEFAULTS",
    "TEMPLATE_VARIABLES",
    "DEFAULT_BIRTHDAY_BODY",
    "StoreItem",
    "StockMovement",
    "MOVEMENT_KINDS",
]
