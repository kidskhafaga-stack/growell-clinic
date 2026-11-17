from flask import Blueprint

# Not a module: the alerts are for whoever holds ``infection_control`` —
# see ``app/utils/ipc.py``.
ipc_bp = Blueprint("ipc", __name__, url_prefix="/infection-control")


@ipc_bp.before_request
def _part_switched_on():
    """Off with its part ('ipc', ``utils/facility.FACILITY_PARTS``): a
    clinic that does not run it does not reach it, by link or by address."""
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("ipc"):
        abort(404)


from app.blueprints.ipc import routes  # noqa: E402,F401
from app.blueprints.ipc import program_routes  # noqa: E402,F401
from app.blueprints.ipc import outbreak_routes  # noqa: E402,F401
from app.blueprints.ipc import cleaning_routes  # noqa: E402,F401
from app.blueprints.ipc import sterilization_routes  # noqa: E402,F401
