from flask import Blueprint

# Short, public-facing prefix ("/f/<token>") — no login required.
feedback_bp = Blueprint("feedback", __name__, url_prefix="/f")

from app.blueprints.feedback import routes  # noqa: E402,F401
