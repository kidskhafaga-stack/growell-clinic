from flask import Blueprint

emergency_bp = Blueprint("emergency", __name__, url_prefix="/emergency")

from app.blueprints.emergency import routes  # noqa: E402,F401
