"""Screening for further assessment needs — see ``models/needs_screen``."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.needs_screen import KINDS, NeedsScreen

#: (b) the hospital's criteria per need, in its own words — shown beside the
#: screen, never scored.
CRITERIA_SETTINGS = {k: f"needs_criteria_{k}" for k in KINDS}
#: (c) hours from admission to have every need screened. Empty until set.
HOURS_SETTING = "needs_screen_hours"


class NeedsError(ValueError):
    """A refusal with a locale key (``needscreen.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def criteria():
    from app.models import Setting

    return {k: (Setting.get(key) or "").strip() for k, key in CRITERIA_SETTINGS.items()}


def hours():
    from app.models import Setting

    try:
        value = float((Setting.get(HOURS_SETTING) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def save_settings(form):
    from app.models import Setting

    raw = (form.get("hours") or "").strip()
    if raw:
        try:
            if float(raw) <= 0:
                raise ValueError
        except ValueError:
            raise NeedsError("hours") from None
    Setting.set(HOURS_SETTING, raw)
    for k, key in CRITERIA_SETTINGS.items():
        Setting.set(key, (form.get(k) or "").strip()[:1000])


def screen(stay, form, user):
    """One or more needs screened at once — each answered ``positive`` or
    ``negative``; a need left unanswered is not a row."""
    rows = []
    for kind in KINDS:
        answer = form.get(kind)
        if answer not in ("positive", "negative"):
            continue
        row = NeedsScreen(patient_id=stay.patient_id, admission_id=stay.id, kind=kind,
                          positive=answer == "positive",
                          note=_text(form.get(f"{kind}_note"), 255),
                          by_id=getattr(user, "id", None))
        referred = _text(form.get(f"{kind}_referred_to"), 160)
        if referred and row.positive:
            row.referred_to, row.referred_at = referred, datetime.utcnow()
        db.session.add(row)
        rows.append(row)
    if not rows:
        raise NeedsError("empty")
    db.session.flush()
    return rows


def refer(row, form):
    if not row.positive:
        raise NeedsError("not_positive")
    to = _text(form.get("referred_to"), 160)
    if not to:
        raise NeedsError("referred_to")
    row.referred_to, row.referred_at = to, datetime.utcnow()
    db.session.flush()
    return row


def seen(row, form, user):
    """Ev. 5 — the service's own finding, written back on the screen."""
    if not row.referred_to:
        raise NeedsError("not_referred")
    note = _text(form.get("seen_note"), 255)
    if not note:
        raise NeedsError("seen_note")
    row.seen_note, row.seen_at, row.seen_by = note, datetime.utcnow(), getattr(user, "id", None)
    db.session.flush()
    return row


def for_stay(stay, now=None):
    """The latest screen of each need on this stay, and what is outstanding."""
    now = now or datetime.utcnow()
    rows = (NeedsScreen.query.filter_by(admission_id=stay.id)
            .order_by(NeedsScreen.at.desc(), NeedsScreen.id.desc()).all())
    latest = {}
    for r in rows:
        latest.setdefault(r.kind, r)
    limit = hours()
    due = stay.admitted_at + timedelta(hours=limit) if limit and stay.admitted_at else None
    unscreened = [k for k in KINDS if k not in latest]
    return {"latest": latest, "history": rows[:20], "kinds": KINDS, "criteria": criteria(),
            "unscreened": unscreened,
            "late": bool(due and unscreened and stay.is_open and now > due),
            "due": due,
            "to_refer": [r for r in latest.values() if r.needs_referral],
            "awaiting": [r for r in latest.values() if r.awaiting_service]}


__all__ = ["CRITERIA_SETTINGS", "HOURS_SETTING", "NeedsError", "criteria", "for_stay", "hours",
           "refer", "save_settings", "screen", "seen"]
