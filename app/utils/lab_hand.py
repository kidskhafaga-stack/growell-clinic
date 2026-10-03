"""What a test measures and its ranges, typed by hand on the test's page.

Asked as *«فى تحاليل … مش مفتوح ان المعمل يدخلها او يغيراها بايده؟ ليه»*.
Until now every analyte and every range arrived by importing a sheet; a lab
that wanted to add one band, or correct one figure, had to edit a
spreadsheet and import it again.

**Nothing typed here judges a result until it is approved** — the same rule
as an imported range (`models/lab_reference.py`). What is different is what
approval replaces:

* a **new sheet** replaces every approved band of an analyte, because that is
  what a new sheet from the laboratory means (`lab_import.approve_test`);
* a **hand row** replaces only the row it corrects. Adding one band for the
  newborn must not wipe the approved bands for every other age.

Correcting an approved row never edits it: a draft is written beside it,
pointing at it, and the approved one keeps judging until the draft is
approved. Every result already written keeps the range it was read against
— the figures are copied onto the result (`LabResultValue`).

The age is typed the way the sheet writes it — «6-23 months», «<1 year»,
«all» — and read by the same reader (`lab_import.age_band`), so a band means
the same thing whichever door it came in by.
"""
from datetime import datetime

from app.extensions import db

KINDS = ("interval", "cutoff", "note")
SEXES = ("all", "male", "female")


class Refused(ValueError):
    """A hand entry that cannot be kept, with the locale key that says why."""

    def __init__(self, key):
        super().__init__(key)
        self.key = key


def _number(value):
    from app.utils.lab_import import _number as read

    return read(value)


def _text(value, size):
    return ((value or "").strip()[:size]) or None


def add_analyte(investigation, name, name_ar=None, unit=None):
    """Put one measured thing on this test, reusing an analyte of the same
    name rather than making a second sodium."""
    from app.models import LabAnalyte, LabTestAnalyte

    name = _text(name, 160)
    if not name:
        raise Refused("lab_hand.need_analyte_name")
    analyte = (LabAnalyte.query
               .filter(db.func.lower(LabAnalyte.name) == name.lower()).first())
    if analyte is None:
        analyte = LabAnalyte(name=name, name_ar=_text(name_ar, 160),
                             unit=_text(unit, 30))
        db.session.add(analyte)
        db.session.flush()
    else:
        analyte.name_ar = analyte.name_ar or _text(name_ar, 160)
        analyte.unit = analyte.unit or _text(unit, 30)
    exists = LabTestAnalyte.query.filter_by(
        investigation_id=investigation.id, analyte_id=analyte.id).first()
    if exists is None:
        last = max([link.sort_order or 0 for link in investigation.analyte_links]
                   or [0])
        db.session.add(LabTestAnalyte(investigation_id=investigation.id,
                                      analyte_id=analyte.id, sort_order=last + 1))
        db.session.flush()
    return analyte


def remove_analyte(investigation, analyte_id):
    """Take a measured thing off this test. The analyte and its ranges stay —
    another test may measure it, and results already written name it."""
    from app.models import LabTestAnalyte

    link = LabTestAnalyte.query.filter_by(
        investigation_id=investigation.id, analyte_id=analyte_id).first()
    if link is not None:
        db.session.delete(link)
        db.session.flush()


def _read(form):
    """The posted figures, checked. Raises :class:`Refused`."""
    from app.utils.lab_import import age_band

    label = _text(form.get("age"), 60)
    band = age_band(label or "")
    if band is None:
        raise Refused("lab_hand.age_unreadable")
    kind = form.get("kind") if form.get("kind") in KINDS else "interval"
    sex = form.get("sex") if form.get("sex") in SEXES else "all"
    low, high = _number(form.get("low")), _number(form.get("high"))
    crit_low = _number(form.get("critical_low"))
    crit_high = _number(form.get("critical_high"))
    note = _text(form.get("note"), 255)
    if kind == "note":
        if not note:
            raise Refused("lab_hand.need_note")
        low = high = crit_low = crit_high = None
    elif low is None and high is None:
        raise Refused("lab_hand.need_figure")
    if low is not None and high is not None and low >= high:
        raise Refused("lab_hand.low_above_high")
    if crit_low is not None and crit_high is not None and crit_low >= crit_high:
        raise Refused("lab_hand.low_above_high")
    return {"age_from_days": band[0], "age_to_days": band[1],
            "age_label": label, "sex": sex, "kind": kind,
            "low": low, "high": high,
            "critical_low": crit_low, "critical_high": crit_high,
            "note": note, "source": _text(form.get("source"), 160)}


def add_range(analyte, form, user):
    """A new band for this analyte, as a draft."""
    from app.models import LabRange

    figures = _read(form)
    row = LabRange(analyte_id=analyte.id, manual=True,
                   entered_by=getattr(user, "id", None), **figures)
    row.source = row.source or _who(user)
    db.session.add(row)
    db.session.flush()
    return row


def correct_range(row, form, user):
    """Correct one band. A draft is edited where it stands; an approved row is
    left judging, and a draft is written beside it that will replace it — and
    only it — when approved. A second correction of the same approved row
    replaces the first draft rather than piling up beside it."""
    from app.models import LabRange

    figures = _read(form)
    if not row.approved:
        for key, value in figures.items():
            setattr(row, key, value)
        row.source = row.source or _who(user)
        row.manual = True
        row.entered_by = getattr(user, "id", None)
        db.session.flush()
        return row
    (LabRange.query.filter(LabRange.replaces_id == row.id,
                           LabRange.approved_at.is_(None))
     .delete(synchronize_session=False))
    draft = LabRange(analyte_id=row.analyte_id, manual=True,
                     replaces_id=row.id, entered_by=getattr(user, "id", None),
                     **figures)
    draft.source = draft.source or row.source or _who(user)
    draft.source_url = row.source_url
    db.session.add(draft)
    db.session.flush()
    return draft


def drop_draft(row):
    """Throw a draft away. An approved row is never deleted from here — it is
    replaced by approving a correction, so a result's range always has a
    successor somebody signed."""
    if row.approved:
        raise Refused("lab_hand.approved_stays")
    db.session.delete(row)
    db.session.flush()


def approve(investigation, user):
    """Approve this test's drafts.

    Per analyte: if any draft came from a sheet, the sheet's rule — every
    approved band goes and the drafts take over. If every draft was typed by
    hand, each replaces only the row it names. Returns how many were approved.
    """
    now = datetime.utcnow()
    done = 0
    for link in investigation.analyte_links:
        ranges = list(link.analyte.ranges)
        drafts = [r for r in ranges if not r.approved]
        if not drafts:
            continue
        if any(not r.manual for r in drafts):
            retired = [r for r in ranges if r.approved]
        else:
            named = {r.replaces_id for r in drafts if r.replaces_id}
            retired = [r for r in ranges if r.approved and r.id in named]
        for old in retired:
            db.session.delete(old)
        for row in drafts:
            row.approved_at = now
            row.approved_by = getattr(user, "id", None)
            row.replaces_id = None
            done += 1
    db.session.flush()
    return done


def stop(investigation, reason, user):
    """«توقيف تحليل»: out of the search for new orders, with the reason.
    Every order and result already written stays."""
    reason = _text(reason, 200)
    if not reason:
        raise Refused("lab_hand.need_reason")
    investigation.is_active = False
    investigation.stopped_reason = reason
    investigation.stopped_at = datetime.utcnow()
    investigation.stopped_by = getattr(user, "id", None)
    db.session.flush()


def resume(investigation):
    investigation.is_active = True
    investigation.stopped_reason = None
    investigation.stopped_at = None
    investigation.stopped_by = None
    db.session.flush()


def _who(user):
    from app.i18n import t

    name = getattr(user, "full_name", None) or getattr(user, "username", "") or ""
    return t("lab_hand.typed_by", name=name)[:160]
