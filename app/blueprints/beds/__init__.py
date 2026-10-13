from flask import Blueprint

beds_bp = Blueprint("beds", __name__, url_prefix="/beds")

from app.blueprints.beds import routes  # noqa: E402,F401
from app.blueprints.beds import handover_routes  # noqa: E402,F401
from app.blueprints.beds import precaution_routes  # noqa: E402,F401
from app.blueprints.beds import milk_routes  # noqa: E402,F401
from app.blueprints.beds import own_med_routes  # noqa: E402,F401
from app.blueprints.beds import adr_routes  # noqa: E402,F401
from app.blueprints.beds import med_family_routes  # noqa: E402,F401
from app.blueprints.beds import palliative_routes  # noqa: E402,F401
from app.blueprints.beds import stay_care_routes  # noqa: E402,F401
from app.blueprints.beds import mental_routes  # noqa: E402,F401
from app.blueprints.beds import against_advice_routes  # noqa: E402,F401
