from flask import Blueprint

# GAHAR ICD.02 — the hospital's own (or contracted) ambulance. An opt-in
# module: a hospital that relies on the national ambulance never sees it.
ambulance_bp = Blueprint("ambulance", __name__, url_prefix="/ambulance")

from app.blueprints.ambulance import routes  # noqa: E402,F401
