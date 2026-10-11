from flask import Blueprint

patients_bp = Blueprint("patients", __name__, url_prefix="/patients")

from app.blueprints.patients import routes  # noqa: E402,F401
from app.blueprints.patients import merge_routes  # noqa: E402,F401
