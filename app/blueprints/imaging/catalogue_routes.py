"""Radiology's own list of scans — its names, its prices, its machines and
the hospital's dose references — behind radiology's module, not the lab's.
The page and its rules are the lab's catalogue's (`labs/catalogue.py`)."""
from app.blueprints.imaging import imaging_bp
from app.blueprints.imaging.routes import MODULE
from app.blueprints.labs import catalogue
from app.utils.decorators import module_required


@imaging_bp.route("/catalogue")
@module_required(MODULE)
def catalogue_page():
    return catalogue.page("imaging")


@imaging_bp.route("/catalogue/add", methods=["POST"])
@module_required(MODULE)
def catalogue_add():
    return catalogue.add("imaging")


@imaging_bp.route("/catalogue/<int:test_id>", methods=["POST"])
@module_required(MODULE)
def catalogue_edit(test_id):
    return catalogue.edit(test_id, kind="imaging")
