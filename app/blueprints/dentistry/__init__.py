from flask import Blueprint

dentistry_bp = Blueprint("dentistry", __name__, url_prefix="/dentistry")

from app.blueprints.dentistry import routes  # noqa: E402,F401
