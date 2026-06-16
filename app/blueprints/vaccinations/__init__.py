from flask import Blueprint

vaccinations_bp = Blueprint("vaccinations", __name__, url_prefix="/vaccinations")

from app.blueprints.vaccinations import routes  # noqa: E402,F401
