from flask import Blueprint

finance_bp = Blueprint("finance", __name__, url_prefix="/finance")

from app.blueprints.finance import routes  # noqa: E402,F401
from app.blueprints.finance import payer_form_routes  # noqa: E402,F401
