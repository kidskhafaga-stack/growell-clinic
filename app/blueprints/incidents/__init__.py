from flask import Blueprint

# Not a module: every member of staff reports, and the board is for whoever
# holds ``incident_manage`` — see ``routes``.
incidents_bp = Blueprint("incidents", __name__, url_prefix="/incidents")


@incidents_bp.before_request
def _part_switched_on():
    """Off with its part ('quality', ``utils/facility.FACILITY_PARTS``): a
    clinic that does not run it does not reach it, by link or by address."""
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("quality"):
        abort(404)


from app.blueprints.incidents import routes  # noqa: E402,F401
