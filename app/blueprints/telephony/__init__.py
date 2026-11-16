from flask import Blueprint

# Where the clinic's switchboard posts its call events: no login — the
# clinic's telephone key (utils/telephony). The screens are in `messages`.
telephony_bp = Blueprint("telephony", __name__, url_prefix="/telephony")

from app.blueprints.telephony import routes  # noqa: E402,F401
