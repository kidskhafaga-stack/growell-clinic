from flask import Blueprint

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")

from app.blueprints.finance import routes  # noqa: E402,F401
