"""Internal item codes for the two inventories.

Every stock item gets a program-issued code — ITM-0001 for general-store
items, VAC-0001 for vaccine brands — assigned on creation and backfilled on
upgrade. The code doubles as the printed/scanned barcode whenever the item
has no supplier barcode of its own, so every item can carry a label.
"""
from app.extensions import db
from app.models import StoreItem
from app.models.vaccine import VaccineBrand


def _next(model, column, prefix):
    top = 0
    for (code,) in model.query.with_entities(column).all():
        if code and code.upper().startswith(prefix):
            tail = code[len(prefix):]
            if tail.isdigit():
                top = max(top, int(tail))
    return f"{prefix}{top + 1:04d}"


def next_store_code():
    return _next(StoreItem, StoreItem.item_code, "ITM-")


def next_brand_code():
    return _next(VaccineBrand, VaccineBrand.item_code, "VAC-")


def backfill_item_codes():
    """Give every code-less store item / vaccine brand its internal code and
    default an empty barcode to that code (fill-only; no commit)."""
    fixed = 0
    for item in StoreItem.query.filter(
            (StoreItem.item_code.is_(None)) | (StoreItem.item_code == "")).all():
        item.item_code = next_store_code()
        db.session.flush()
        fixed += 1
    for brand in VaccineBrand.query.filter(
            (VaccineBrand.item_code.is_(None)) | (VaccineBrand.item_code == "")).all():
        brand.item_code = next_brand_code()
        db.session.flush()
        fixed += 1
    for item in StoreItem.query.filter(
            (StoreItem.barcode.is_(None)) | (StoreItem.barcode == "")).all():
        item.barcode = item.item_code
    for brand in VaccineBrand.query.filter(
            (VaccineBrand.barcode.is_(None)) | (VaccineBrand.barcode == "")).all():
        brand.barcode = brand.item_code
    return fixed
