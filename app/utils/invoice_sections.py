"""The sections a bill is read in, seeded once and edited from the screen.

Same shape as :mod:`app.utils.service_types`, and deliberately so: a clinic
that has learned where to add a service type should not have to learn a second
pattern to add a bill section.

**Why this list opens and the accounting category does not.** Nothing reads a
section by name. The summary groups by whatever sections exist, and a
percentage charge names the sections it is levied on — so a hospital adding
«مستلزمات غرفة العمليات» gets a section that works the day it is typed. The
category is the opposite: code reads ``vaccination_fee`` to decide which half
of an invoice is posted to vaccination revenue, so a clinic inventing one
would be inventing a rule nothing implements.
"""
from app.models.service import (INVOICE_SECTION_ICONS, INVOICE_SECTIONS,
                                InvoiceSection)


def ensure_seeded():
    """Fill the catalogue from the built-in list if it is empty.

    Idempotent — safe from init-db, upgrade-db and the screen itself.
    """
    from app.extensions import db

    if InvoiceSection.query.first() is not None:
        return 0
    added = 0
    for order, key in enumerate(INVOICE_SECTIONS):
        db.session.add(InvoiceSection(
            key=key, icon=INVOICE_SECTION_ICONS.get(key), sort_order=order,
            is_active=True, is_system=True,
        ))
        added += 1
    db.session.commit()
    return added


def all_sections():
    """Every section, ordered for display.

    Falls back to the built-in keys when the table is not there yet — the
    screen must still draw during an upgrade rather than raising.
    """
    try:
        rows = (InvoiceSection.query
                .order_by(InvoiceSection.sort_order, InvoiceSection.id).all())
    except Exception:                                   # noqa: BLE001
        rows = []
    return rows or [InvoiceSection(key=k, sort_order=i, is_system=True)
                    for i, k in enumerate(INVOICE_SECTIONS)]


def active_sections():
    return [r for r in all_sections() if r.is_active]


def make_key(name, name_en=None):
    """A stable ASCII key for a clinic-added section.

    Derived and never typed, for the reason a service type's key is: the key
    is what services already filed under this section match on, so renaming
    the label must not orphan them. An Arabic-only name yields no ASCII, so
    it falls back to a numbered key rather than an empty one.
    """
    import re

    base = re.sub(r"[^a-z0-9]+", "-", (name_en or name or "").lower()).strip("-")
    if not base:
        base = "section"
    key, n = base[:30], 2
    while InvoiceSection.query.filter_by(key=key).first() is not None:
        suffix = f"-{n}"
        key = base[:30 - len(suffix)] + suffix
        n += 1
    return key
