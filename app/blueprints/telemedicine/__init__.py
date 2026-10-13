from flask import Blueprint

# GAHAR ACT.16 — remote encounters by video, phone or message. An opt-in
# module: a hospital that sees every child in person never sees it.
telemedicine_bp = Blueprint("telemedicine", __name__, url_prefix="/telemedicine")

from app.blueprints.telemedicine import routes  # noqa: E402,F401
