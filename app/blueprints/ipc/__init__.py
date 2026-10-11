from flask import Blueprint

# Not a module: the alerts are for whoever holds ``infection_control`` —
# see ``app/utils/ipc.py``.
ipc_bp = Blueprint("ipc", __name__, url_prefix="/infection-control")

from app.blueprints.ipc import routes  # noqa: E402,F401
