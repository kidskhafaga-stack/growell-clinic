from flask import Blueprint

pharmacy_bp = Blueprint("pharmacy", __name__, url_prefix="/pharmacy")

from app.blueprints.pharmacy import routes  # noqa: E402,F401
from app.blueprints.pharmacy import stewardship_routes  # noqa: E402,F401
from app.blueprints.pharmacy import dtc_routes  # noqa: E402,F401
