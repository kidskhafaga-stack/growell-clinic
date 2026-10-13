from flask import Blueprint

# GAHAR CSS.06, CSS.07, CSS.10 — the special care programmes. An opt-in
# module: a hospital without dialysis, chemotherapy or rehabilitation never
# sees it.
programs_bp = Blueprint("programs", __name__, url_prefix="/programs")

from app.blueprints.programs import routes  # noqa: E402,F401
