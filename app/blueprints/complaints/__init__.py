from flask import Blueprint

complaints_bp = Blueprint("complaints", __name__, url_prefix="/complaints")

from app.blueprints.complaints import routes  # noqa: E402,F401
