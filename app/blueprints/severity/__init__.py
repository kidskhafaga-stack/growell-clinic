from flask import Blueprint

# HOSPITAL_PLAN.md ٥‑د ت-٦ب — severity scores on entering intensive care and
# the deaths they expect. Only with the ICU or NICU module; locked until the
# hospital enters a score from its paper and it reproduces the worked examples.
severity_bp = Blueprint("severity", __name__, url_prefix="/severity")

from app.blueprints.severity import routes  # noqa: E402,F401
