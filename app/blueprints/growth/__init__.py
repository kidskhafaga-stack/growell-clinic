from flask import Blueprint

growth_bp = Blueprint("growth", __name__, url_prefix="/growth")

from app.blueprints.growth import routes  # noqa: E402,F401
