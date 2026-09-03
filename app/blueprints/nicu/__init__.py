from flask import Blueprint

nicu_bp = Blueprint("nicu", __name__, url_prefix="/nicu")

from app.blueprints.nicu import routes  # noqa: E402,F401
