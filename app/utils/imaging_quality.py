"""Radiology's quality control and the yearly service review — see
``models/imaging_quality``."""
from datetime import date, datetime

from app.extensions import db
from app.models.imaging_quality import SERVICES, ImagingQc, ImagingQcReview, ServiceReview


class ImagingQualityError(ValueError):
    """A refusal with a locale key (``img_qc.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def add_qc(form, user):
    from app.models import Equipment

    held = None
    try:
        held = date.fromisoformat((form.get("held_on") or "").strip())
    except ValueError:
        pass
    if held is None:
        raise ImagingQualityError("held_on")
    test = _text(form.get("test"), 160)
    if not test:
        raise ImagingQualityError("test")
    machine = db.session.get(Equipment, form.get("equipment_id", type=int) or 0)
    device = _text(form.get("device"), 120)
    if machine is None and not device:
        raise ImagingQualityError("device")
    if form.get("passed") not in ("yes", "no"):
        raise ImagingQualityError("passed")
    passed = form.get("passed") == "yes"
    action = _text(form.get("action"))
    if not passed and not action:
        raise ImagingQualityError("action")
    row = ImagingQc(equipment_id=machine.id if machine else None, device=None if machine else device,
                    held_on=held, test=test, passed=passed, value=_text(form.get("value"), 80),
                    action=action, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def review_month(month, note, user):
    note = _text(note, 255)
    if not month or len(month) != 7:
        raise ImagingQualityError("month")
    if not note:
        raise ImagingQualityError("note")
    row = ImagingQcReview(month=month, note=note, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def board(month):
    """The month's checks, the failures, and whether the month was reviewed."""
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + (mon == 12), (mon % 12) + 1, 1)
    rows = (ImagingQc.query.filter(ImagingQc.held_on >= start, ImagingQc.held_on < end)
            .order_by(ImagingQc.held_on.desc(), ImagingQc.id.desc()).all())
    return {"rows": rows, "failed": [r for r in rows if not r.passed], "month": month,
            "reviews": ImagingQcReview.query.filter_by(month=month).order_by(ImagingQcReview.at).all()}


def machines():
    """Radiology's machines in the equipment register, when it keeps them."""
    from app.models import Equipment

    return Equipment.query.order_by(Equipment.name).all()


def save_service_review(service, year, text, user):
    if service not in SERVICES:
        raise ImagingQualityError("service")
    text = _text(text)
    if not text:
        raise ImagingQualityError("review")
    if not year or year > date.today().year + 1:
        raise ImagingQualityError("year")
    row = ServiceReview.query.filter_by(service=service, year=year).first() or ServiceReview(service=service,
                                                                                           year=year)
    row.text, row.by_id, row.at = text, getattr(user, "id", None), datetime.utcnow()
    db.session.add(row)
    db.session.flush()
    return row


def service_reviews(service):
    return ServiceReview.query.filter_by(service=service).order_by(ServiceReview.year.desc()).all()


__all__ = ["ImagingQualityError", "add_qc", "board", "machines", "review_month", "save_service_review",
           "service_reviews"]
