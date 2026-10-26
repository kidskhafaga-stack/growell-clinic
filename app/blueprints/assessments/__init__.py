from flask import Blueprint

# ASSESSMENTS_PLAN.md ت-١ — the assessments of the neurology and development
# specialties: written by a specialist or a doctor, approved by a doctor.
# With the specialties module («panels»); a clinic without it never sees it.
assessments_bp = Blueprint("assessments", __name__, url_prefix="/assessments")

from app.blueprints.assessments import routes  # noqa: E402,F401
