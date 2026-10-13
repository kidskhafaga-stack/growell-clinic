from flask import Blueprint

# GAHAR ATH — a teaching hospital's learners and its research. An opt-in
# module: a clinic that teaches nobody never sees it.
teaching_bp = Blueprint("teaching", __name__, url_prefix="/teaching")

from app.blueprints.teaching import routes  # noqa: E402,F401
