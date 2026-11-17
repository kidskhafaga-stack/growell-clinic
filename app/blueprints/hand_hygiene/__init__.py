from flask import Blueprint

# Not a module: hand hygiene is observed in every care area, by whoever works
# there, and read by the infection-control lead — see ``routes._door``.
hand_hygiene_bp = Blueprint("hand_hygiene", __name__, url_prefix="/hand-hygiene")


@hand_hygiene_bp.before_request
def _part_switched_on():
    """Off with its part ('ipc', ``utils/facility.FACILITY_PARTS``): a
    clinic that does not run it does not reach it, by link or by address."""
    from flask import abort

    from app.utils.facility import module_enabled

    if not module_enabled("ipc"):
        abort(404)


from app.blueprints.hand_hygiene import routes  # noqa: E402,F401
