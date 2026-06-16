from flask import Blueprint

appointments_bp = Blueprint("appointments", __name__, url_prefix="/appointments")

from app.blueprints.appointments import routes  # noqa: E402,F401
