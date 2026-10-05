from flask import Blueprint

# Not a module: equipment is reported on by whoever is standing beside it —
# the ward, the lab, the theatre — and kept by the store. See ``routes._door``.
equipment_bp = Blueprint("equipment", __name__, url_prefix="/equipment")

from app.blueprints.equipment import routes  # noqa: E402,F401
