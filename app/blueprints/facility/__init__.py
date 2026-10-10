from flask import Blueprint

# Not a module: the building's safety records belong to whoever looks after
# the building — the administrators and the store — see ``routes._door``.
facility_bp = Blueprint("facility", __name__, url_prefix="/facility")

from app.blueprints.facility import routes  # noqa: E402,F401
