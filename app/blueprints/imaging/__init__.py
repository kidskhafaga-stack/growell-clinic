from flask import Blueprint

imaging_bp = Blueprint("imaging", __name__, url_prefix="/imaging")

from app.blueprints.imaging import routes  # noqa: E402,F401
from app.blueprints.imaging import safety_routes  # noqa: E402,F401
from app.blueprints.imaging import catalogue_routes  # noqa: E402,F401
