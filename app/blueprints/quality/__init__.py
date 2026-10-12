from flask import Blueprint

# Not a module: the quality team's screens, for whoever holds
# ``incident_manage`` — the same people who review the incident reports.
quality_bp = Blueprint("quality", __name__, url_prefix="/quality")

from app.blueprints.quality import routes  # noqa: E402,F401
