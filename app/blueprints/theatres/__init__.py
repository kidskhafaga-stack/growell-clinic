from flask import Blueprint

theatres_bp = Blueprint("theatres", __name__, url_prefix="/theatres")

from app.blueprints.theatres import routes  # noqa: E402,F401
