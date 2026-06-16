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
from app.models.parent import (
    CLIENT_CATEGORIES,
    PARENT_RELATIONS,
    Parent,
)
from app.models.patient import BLOOD_TYPES, GENDERS, Patient
from app.models.permissions import MODULES, ROLE_PERMISSIONS, ROLES
from app.models.setting import Setting
from app.models.user import User

__all__ = [
    "User",
    "Setting",
    "ActivityLog",
    "Family",
    "Parent",
    "Patient",
    "Appointment",
    "DoctorSchedule",
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
]
