from flask import Blueprint

icu_bp = Blueprint("icu", __name__, url_prefix="/icu")

from app.blueprints.icu import routes  # noqa: E402,F401
