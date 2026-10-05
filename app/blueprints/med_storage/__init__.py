from flask import Blueprint

# Not a module: where medicines are kept is read and written by the pharmacy,
# the store and the ward's nurse alike — see ``routes._door``.
med_storage_bp = Blueprint("med_storage", __name__, url_prefix="/med-storage")

from app.blueprints.med_storage import routes  # noqa: E402,F401
