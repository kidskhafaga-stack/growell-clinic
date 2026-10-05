from flask import Blueprint

beds_bp = Blueprint("beds", __name__, url_prefix="/beds")

from app.blueprints.beds import routes  # noqa: E402,F401
from app.blueprints.beds import handover_routes  # noqa: E402,F401
