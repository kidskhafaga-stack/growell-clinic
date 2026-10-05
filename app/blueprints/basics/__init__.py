from flask import Blueprint

# Not a module: the window that finishes a quick registration is reached from
# the booking, the till and a study alike — see ``routes._desk``.
basics_bp = Blueprint("basics", __name__, url_prefix="/patients")

from app.blueprints.basics import routes  # noqa: E402,F401
