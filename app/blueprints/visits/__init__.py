from flask import Blueprint

visits_bp = Blueprint("visits", __name__, url_prefix="/visits")

from app.blueprints.visits import routes  # noqa: E402,F401
