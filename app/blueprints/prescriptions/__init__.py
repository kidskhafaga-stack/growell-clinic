from flask import Blueprint

prescriptions_bp = Blueprint("prescriptions", __name__, url_prefix="/prescriptions")

from app.blueprints.prescriptions import routes  # noqa: E402,F401
