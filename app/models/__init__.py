"""Database models for GROWELL CLINIC.

Phase 1 establishes the foundation models (users, settings, activity log).
Later phases add the clinical and financial domain models. Importing them
here ensures SQLAlchemy registers every table when ``db.create_all()`` runs.
"""
from app.models.activity_log import ActivityLog
from app.models.permissions import MODULES, ROLE_PERMISSIONS, ROLES
from app.models.setting import Setting
from app.models.user import User

__all__ = [
    "User",
    "Setting",
    "ActivityLog",
    "ROLES",
    "MODULES",
    "ROLE_PERMISSIONS",
]
