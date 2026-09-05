from flask import Blueprint

ward_bp = Blueprint("ward", __name__, url_prefix="/ward")

from app.blueprints.ward import routes  # noqa: E402,F401
