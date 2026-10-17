from flask import Blueprint

# Public: a family asks for an appointment from a link in a post, a bio or a
# QR — no login. Off until the clinic opens it (``utils/channels.page_open``).
booking_page_bp = Blueprint("booking_page", __name__, url_prefix="/book")

from app.blueprints.booking_page import routes  # noqa: E402,F401
