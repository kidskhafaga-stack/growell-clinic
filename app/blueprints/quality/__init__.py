from flask import Blueprint

# Not a module: the quality team's screens, for whoever holds
# ``incident_manage`` — the same people who review the incident reports.
quality_bp = Blueprint("quality", __name__, url_prefix="/quality")


@quality_bp.before_request
def _part_switched_on():
    """Off with its part ('quality', ``utils/facility.FACILITY_PARTS``): a
    clinic that does not run it does not reach it, by link or by address."""
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("quality"):
        abort(404)


from app.blueprints.quality import routes  # noqa: E402,F401
from app.blueprints.quality import governance_routes  # noqa: E402,F401
from app.blueprints.quality import rca_routes  # noqa: E402,F401
