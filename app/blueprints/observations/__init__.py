from flask import Blueprint

observations_bp = Blueprint("observations", __name__, url_prefix="/observations")

from app.blueprints.observations import routes  # noqa: E402,F401
