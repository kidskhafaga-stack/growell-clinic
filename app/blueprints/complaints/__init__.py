from flask import Blueprint

complaints_bp = Blueprint("complaints", __name__, url_prefix="/complaints")


@complaints_bp.before_request
def _part_switched_on():
    """Off with its part ('complaints', ``utils/facility.FACILITY_PARTS``): a
    clinic that does not run it does not reach it, by link or by address."""
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("complaints"):
        abort(404)


from app.blueprints.complaints import routes  # noqa: E402,F401
