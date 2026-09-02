from flask import Blueprint

panels_bp = Blueprint("panels", __name__, url_prefix="/panels")

from app.blueprints.panels import routes  # noqa: E402,F401
