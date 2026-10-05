from flask import Blueprint

# Not a module: hand hygiene is observed in every care area, by whoever works
# there, and read by the infection-control lead — see ``routes._door``.
hand_hygiene_bp = Blueprint("hand_hygiene", __name__, url_prefix="/hand-hygiene")

from app.blueprints.hand_hygiene import routes  # noqa: E402,F401
