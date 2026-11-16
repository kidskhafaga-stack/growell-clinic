from flask import Blueprint

# The clinic's own forms (FORM_BUILDER_PLAN.md): designed behind
# `forms_design`, filled by each form's own audience.
forms_bp = Blueprint("forms", __name__, url_prefix="/forms")

from app.blueprints.forms import routes  # noqa: E402,F401
