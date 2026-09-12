"""Selling a package, and drawing a session off it.

The rules live here rather than in the checkout, because the same three
questions get asked from three screens and one wrong answer in any of them is
a family charged twice:

* **what can be sold** — active offers, for services this clinic can actually
  deliver;
* **what covers today's session** — an open balance of the right service, and
  which one when there are two;
* **what a draw is allowed to do** — never past the count, never after the
  window, never on a cancelled sale.

The last one is the only place a balance goes down, so it is the only place
the count can be got wrong.
"""
from app.extensions import db
from app.models import PackageUse, PatientPackage, ServicePackage
from app.utils.clock import local_today


def catalogue(service=None, active_only=True):
    """The offers, in screen order."""
    q = ServicePackage.query
    if service is not None:
        q = q.filter(ServicePackage.service_id
                     == getattr(service, "id", service))
    if active_only:
        q = q.filter(ServicePackage.is_active.is_(True))
    return q.order_by(ServicePackage.sort_order, ServicePackage.id).all()


def sellable(lang="ar"):
    """The offers reception may put on a bill today.

    Filtered through :func:`app.utils.services.deliverable`, so a package of
    something this clinic does not do is not on the list — the same rule the
    services themselves follow, and for the same reason: a price for a thing
    nobody here performs is a promise somebody has to ring back and unmake.
    """
    from app.utils.services import deliverable

    rows = catalogue()
    keep = {s.id for s in deliverable([r.service for r in rows
                                       if r.service is not None])}
    return [r for r in rows if r.service_id in keep]


def open_for(patient_id, on=None, service_id=None):
    """This patient's balances that can still be drawn on, soonest to expire.

    Order is the order they should be spent in: a course with a window that
    closes next month goes before one with no window at all, because the
    other way round quietly wastes the one that could be lost. Ties fall back
    to the older sale.
    """
    on = on or local_today()
    q = PatientPackage.query.filter(
        PatientPackage.patient_id == patient_id,
        PatientPackage.cancelled_at.is_(None))
    if service_id is not None:
        q = q.filter(PatientPackage.service_id == service_id)
    rows = [p for p in q.order_by(PatientPackage.id).all() if p.is_open(on)]
    # Sorted in Python, not SQL: "remaining" is derived from the use rows and
    # "no window" has to sort *last* rather than first, which is the opposite
    # of how NULL orders in SQLite.
    rows.sort(key=lambda p: (p.expires_on is None, p.expires_on or on, p.id))
    return rows


def covering(patient_id, service_id, on=None):
    """The balance today's session should come off, or ``None``."""
    if not service_id:
        return None
    rows = open_for(patient_id, on=on, service_id=service_id)
    return rows[0] if rows else None


def sell(patient, offer, invoice=None, item=None, on=None, user_id=None):
    """Record the balance a paid-for package created.

    Called with the invoice line that charged for it: the balance exists
    because that line does, and a package with no line behind it is a course
    nobody paid for.
    """
    on = on or local_today()
    expires = None
    if offer.valid_days:
        from datetime import timedelta

        expires = on + timedelta(days=int(offer.valid_days))
    row = PatientPackage(
        patient_id=getattr(patient, "id", patient),
        package_id=offer.id,
        service_id=offer.service_id,
        invoice_id=getattr(invoice, "id", None),
        invoice_item_id=getattr(item, "id", None),
        # Snapshot, so renaming the offer never rewrites what a family bought.
        name=offer.display_name("ar"),
        sessions_total=max(1, int(offer.sessions or 1)),
        price_paid=offer.price or 0,
        sold_on=on,
        expires_on=expires,
        created_by=user_id,
    )
    db.session.add(row)
    return row


def draw(package, item=None, visit_id=None, on=None, user_id=None, note=None):
    """Take one session off a balance. Returns the use, or ``None``.

    ``None`` and no row written is the whole point: a spent, expired or
    cancelled course must not quietly go to eleven of ten. Callers check the
    answer — a draw that failed means the session has to be charged for.
    """
    on = on or local_today()
    if package is None or not package.is_open(on):
        return None
    use = PackageUse(patient_package_id=package.id, used_on=on,
                     invoice_item_id=getattr(item, "id", None),
                     visit_id=visit_id, recorded_by=user_id, note=note)
    # Appended to the relationship as well as the session, so ``remaining``
    # is right for the *next* caller in this same request — two lines on one
    # checkout drawing on one balance is the case that breaks otherwise.
    package.uses.append(use)
    db.session.add(use)
    return use


def line_label(package, lang="ar", nth=None, count=1):
    """What the zero line on the bill says.

    Names the session number and the course, because "which session was that"
    is the question the line exists to answer months later. ``count`` covers
    the rare line that pays for two at once, which reads as a range.
    """
    nth = nth if nth is not None else package.used + 1
    total = package.sessions_total or 0
    which = f"{nth}" if count <= 1 else f"{nth}-{nth + count - 1}"
    name = package.display_name(lang)
    if lang == "en":
        word = "Session" if count <= 1 else "Sessions"
        return f"{word} {which} of {total} — {name}"[:200]
    word = "جلسة" if count <= 1 else "جلسات"
    return f"{word} {which} من {total} — {name}"[:200]


def cancel(package, reason=None, user_id=None):
    """Close a balance without spending it (a refund, a family that stopped).

    Kept as a stamp rather than a delete: the sessions already had happened,
    and the money already moved through an invoice that still exists.
    """
    from datetime import datetime

    if package.cancelled_at is None:
        package.cancelled_at = datetime.utcnow()
        package.cancel_reason = (reason or "")[:200] or None
    return package


def history(patient_id):
    """Every balance this patient has ever had, newest first — for the card."""
    return (PatientPackage.query
            .filter(PatientPackage.patient_id == patient_id)
            .order_by(PatientPackage.id.desc()).all())
