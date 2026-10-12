from flask import Blueprint

users_bp = Blueprint("users", __name__, url_prefix="/users")

from app.blueprints.users import routes  # noqa: E402,F401
from app.blueprints.users import staff_file_routes  # noqa: E402,F401
