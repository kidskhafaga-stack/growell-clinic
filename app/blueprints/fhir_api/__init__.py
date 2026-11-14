from flask import Blueprint

# The FHIR interface (utils/fhir_api): no login — a key per receiver, and
# only the children shared with it. Read-only.
fhir_api_bp = Blueprint("fhir_api", __name__, url_prefix="/fhir/r4")

from app.blueprints.fhir_api import routes  # noqa: E402,F401
