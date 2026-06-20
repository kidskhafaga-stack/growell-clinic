from flask import Blueprint

messages_bp = Blueprint("messages", __name__, url_prefix="/messages")

from app.blueprints.messages import routes  # noqa: E402,F401
