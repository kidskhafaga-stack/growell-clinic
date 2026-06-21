from flask import Blueprint

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

from app.blueprints.ai import routes  # noqa: E402,F401
