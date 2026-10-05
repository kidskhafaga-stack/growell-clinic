from flask import Blueprint

labs_bp = Blueprint("labs", __name__, url_prefix="/labs")

from app.blueprints.labs import routes  # noqa: E402,F401
from app.blueprints.labs import competency_routes  # noqa: E402,F401
