"""Patient archiving: keep long-inactive files out of the active roster.

Archiving never deletes anything — it flips ``is_active`` off, stamps
``archived_at`` and records why. A patient is a candidate once their last
activity (latest visit, else file creation) is older than the configured number
of inactive years. Restoring simply flips the file back to active.

The sweep is opt-in (``archive_auto_enabled``) and safe to re-run: it only ever
touches currently-active files whose last activity predates the cutoff.
"""
from datetime import datetime

from sqlalchemy import func

from app.extensions import db
from app.models import Patient, Setting, Visit
from app.utils.clock import local_today

DEFAULT_INACTIVE_YEARS = 3


def inactive_years():
    """Configured inactivity threshold in years (bounded to a sane 1–20)."""
    try:
        n = int(Setting.get("archive_inactive_years", DEFAULT_INACTIVE_YEARS))
    except (TypeError, ValueError):
        n = DEFAULT_INACTIVE_YEARS
    return min(max(n, 1), 20)


def auto_enabled():
    return Setting.get("archive_auto_enabled", "0") == "1"


def cutoff_date(years=None, today=None):
    """The last-activity date on/before which an active file is a candidate."""
    years = inactive_years() if years is None else years
    today = today or local_today()
    # Shift back N years, clamping Feb-29 to Feb-28 on non-leap targets.
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


def _last_activity_map(patient_ids):
    """{patient_id: latest visit date} for the given ids (one grouped query)."""
    if not patient_ids:
        return {}
    rows = (db.session.query(Visit.patient_id, func.max(Visit.visit_date))
            .filter(Visit.patient_id.in_(patient_ids))
            .group_by(Visit.patient_id).all())
    return {pid: d for pid, d in rows}


def inactive_candidates(years=None, today=None):
    """Active patients whose last activity is older than the cutoff, each with
    the date we judged them on. Returns a list of ``(patient, last_date)`` sorted
    oldest-first — the review list before an archive sweep."""
    cutoff = cutoff_date(years, today)
    actives = Patient.query.filter_by(is_active=True).all()
    last_map = _last_activity_map([p.id for p in actives])
    out = []
    for p in actives:
        last = last_map.get(p.id) or (p.created_at.date() if p.created_at else None)
        if last is not None and last <= cutoff:
            out.append((p, last))
    out.sort(key=lambda r: r[1])
    return out


def archive_patient(patient, reason="manual"):
    """Archive one file (idempotent). Does not commit."""
    if not patient.is_active:
        return False
    patient.is_active = False
    patient.archived_at = datetime.utcnow()
    patient.archive_reason = reason
    return True


def restore_patient(patient):
    """Bring an archived file back to the active roster. Does not commit."""
    if patient.is_active:
        return False
    patient.is_active = True
    patient.archived_at = None
    patient.archive_reason = None
    return True


def auto_archive(years=None, today=None):
    """Archive every current inactivity candidate. Returns how many were archived.
    Commits once at the end."""
    n = 0
    for patient, _last in inactive_candidates(years, today):
        if archive_patient(patient, reason="auto"):
            n += 1
    if n:
        db.session.commit()
    return n


def archive_stats(years=None, today=None):
    """Counts for the active/inactive analytics panel."""
    total = Patient.query.count()
    active = Patient.query.filter_by(is_active=True).count()
    archived = total - active
    auto = Patient.query.filter_by(is_active=False, archive_reason="auto").count()
    return {
        "total": total,
        "active": active,
        "archived": archived,
        "archived_auto": auto,
        "archived_manual": archived - auto,
        "candidates": len(inactive_candidates(years, today)),
    }
