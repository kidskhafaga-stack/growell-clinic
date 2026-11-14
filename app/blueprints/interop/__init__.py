from flask import Blueprint

# The screens behind the FHIR interface (utils/fhir_api): the administrator's
# receivers and keys, and the child's file's «share with a receiver».
interop_bp = Blueprint("interop", __name__, url_prefix="/interop")

from app.blueprints.interop import routes  # noqa: E402,F401
