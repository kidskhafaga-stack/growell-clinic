from flask import Blueprint

# Where the laboratory's middleware (tools/lab_listener.py) posts an
# analyser's messages: no login — the device's own key (lab_device_import).
lab_intake_bp = Blueprint("lab_intake", __name__, url_prefix="/lab-intake")

from app.blueprints.lab_intake import routes  # noqa: E402,F401
