from flask import Blueprint

duty_bp = Blueprint("duty", __name__, url_prefix="/duty")

from app.blueprints.duty import routes  # noqa: E402,F401
