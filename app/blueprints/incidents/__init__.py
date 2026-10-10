from flask import Blueprint

# Not a module: every member of staff reports, and the board is for whoever
# holds ``incident_manage`` — see ``routes``.
incidents_bp = Blueprint("incidents", __name__, url_prefix="/incidents")

from app.blueprints.incidents import routes  # noqa: E402,F401
