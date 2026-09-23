"""Patient archiving: keep long-inactive files out of the active roster.

Archiving never deletes anything — it flips ``is_active`` off, stamps
``archived_at`` and records why. A patient is a candidate once their last
activity (latest visit, else file creation) is older than the configured number
of inactive years. Restoring simply flips the file back to active.

The sweep is opt-in (``archive_auto_enabled``) and safe to re-run: it only ever
touches currently-active files whose last activity predates the cutoff.

**Two ways onto the list, two ways off it.** Asked for by the clinic: *"ممكن
نضيف الى عمره يزيد عن سن معين واستثناء اشخاص بعينهم … علشان الناس الى عندها
امراض مزمنة"*.

* On: no activity for N years (as before), **or** — when the clinic sets an
  age — having reached that age. A paediatric roster fills with adults who
  still turn up once a year, and "inactive" never catches them.
* Off: a file somebody marked «ما يتأرشفش», **or** — when the clinic turns it
  on — a file that carries a chronic condition: written in the chronic
  diseases box, an active problem on the list, or a medicine still being
  taken. A child with asthma seen once in three years is not a file the
  clinic is done with.

Both new rules start **off**. An update must change nothing for a running
clinic, and a sweep that suddenly archives every eighteen-year-old — or stops
archiving files it archived yesterday — is exactly that kind of change. The
age is the clinic's number, never a default this module invents.

The list does not hide who was spared. A file that met a condition and was
kept is shown as kept, with why — otherwise "why is this one not archived?"
has no answer on the screen.

And it is never a one-way door: an archived file is found by the ordinary
search and brought back by one button on the file, at any time.
"""
from datetime import datetime

from sqlalchemy import func

from app.extensions import db
from app.models import Patient, Setting, Visit
from app.utils.clock import local_today

DEFAULT_INACTIVE_YEARS = 3

#: Bounds on the age a clinic may set. Wide on purpose — the number is theirs —
#: but not zero, which would archive every child on the roster.
AGE_MIN, AGE_MAX = 1, 120

#: Why a file is on the list.
INACTIVE, AGED_OUT = "inactive", "aged_out"
#: Why a file on the list was kept.
EXEMPT, CHRONIC = "exempt", "chronic"


def inactive_years():
    """Configured inactivity threshold in years (bounded to a sane 1–20)."""
    try:
        n = int(Setting.get("archive_inactive_years", DEFAULT_INACTIVE_YEARS))
    except (TypeError, ValueError):
        n = DEFAULT_INACTIVE_YEARS
    return min(max(n, 1), 20)


def auto_enabled():
    return Setting.get("archive_auto_enabled", "0") == "1"


def age_limit():
    """The age at which a file counts as done, or ``None`` when the clinic has
    not set one. Blank, zero and nonsense all read as "not set": the rule
    that archives by age exists only once someone typed an age."""
    raw = Setting.get("archive_age_years", "")
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if n < AGE_MIN:
        return None
    return min(n, AGE_MAX)


def spare_chronic():
    """Keep files with a chronic condition off the list. Off until turned on."""
    return Setting.get("archive_spare_chronic", "0") == "1"


def age_on(patient, today):
    """Whole years on ``today``."""
    born = patient.date_of_birth
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day)
                                     < (born.month, born.day))


def chronic_ids(patient_ids):
    """The files among these that carry a chronic condition — three queries,
    not three per file.

    What counts is what the file already says, in any of the three places it
    says it: the chronic diseases box, an active entry on the problem list, a
    home medicine with no stop date. Nothing here guesses a condition from a
    diagnosis name.
    """
    from app.models import PatientMedication, PatientProblem

    ids = list(patient_ids)
    if not ids:
        return set()
    out = {pid for pid, text in db.session.query(
        Patient.id, Patient.chronic_diseases).filter(Patient.id.in_(ids))
        if (text or "").strip()}
    out |= {pid for (pid,) in db.session.query(PatientProblem.patient_id)
            .filter(PatientProblem.patient_id.in_(ids),
                    PatientProblem.status == "active").distinct()}
    out |= {pid for (pid,) in db.session.query(PatientMedication.patient_id)
            .filter(PatientMedication.patient_id.in_(ids),
                    PatientMedication.stopped_on.is_(None)).distinct()}
    return out


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


def _oldest_first(row):
    return (row["last"] is None, row["last"])


def review(years=None, today=None):
    """Every active file that meets a condition, sorted into the two lists the
    screen shows: ``{"due": [...], "kept": [...]}``.

    Each row is a dict — ``patient``, ``last`` (the date the file was last
    active), ``why`` (:data:`INACTIVE` or :data:`AGED_OUT`), ``age`` — and a
    kept row also has ``kept`` (:data:`EXEMPT` or :data:`CHRONIC`). A file
    that meets both conditions is listed once, as inactive: the older rule is
    the one the clinic already knows.
    """
    today = today or local_today()
    cutoff = cutoff_date(years, today)
    limit = age_limit()
    actives = Patient.query.filter_by(is_active=True).all()
    last_map = _last_activity_map([p.id for p in actives])

    hits = []
    for p in actives:
        last = last_map.get(p.id) or (p.created_at.date() if p.created_at else None)
        age = age_on(p, today)
        if last is not None and last <= cutoff:
            why = INACTIVE
        elif limit is not None and age is not None and age >= limit:
            why = AGED_OUT
        else:
            continue
        hits.append({"patient": p, "last": last, "why": why, "age": age})

    chronic = (chronic_ids(row["patient"].id for row in hits)
               if spare_chronic() else set())
    due, kept = [], []
    for row in hits:
        p = row["patient"]
        if p.archive_exempt:
            kept.append(dict(row, kept=EXEMPT))
        elif p.id in chronic:
            kept.append(dict(row, kept=CHRONIC))
        else:
            due.append(row)
    due.sort(key=_oldest_first)
    kept.sort(key=_oldest_first)
    return {"due": due, "kept": kept}


def inactive_candidates(years=None, today=None):
    """The files the sweep would archive, as ``(patient, last_date)`` pairs
    sorted oldest-first — the review list before an archive sweep."""
    return [(row["patient"], row["last"])
            for row in review(years, today)["due"]]


def exempt(patient, user=None, on=True):
    """Mark a file «ما يتأرشفش» — or lift it. Does not commit.

    Lifting writes ``False``, not ``None``: somebody decided, and "the clinic
    said no" is a different fact from "nobody was asked".
    """
    patient.archive_exempt = bool(on)
    patient.archive_exempt_by = getattr(user, "id", None)
    patient.archive_exempt_at = datetime.utcnow()
    return patient


def archive_patient(patient, reason="manual"):
    """Archive one file (idempotent). Does not commit."""
    if not patient.is_active:
        return False
    patient.is_active = False
    patient.archived_at = datetime.utcnow()
    patient.archive_reason = reason
    return True


def aged_out(patient, today=None):
    """Past the clinic's age, when it set one."""
    limit = age_limit()
    age = age_on(patient, today or local_today())
    return limit is not None and age is not None and age >= limit


def restore_patient(patient, user=None, today=None):
    """Bring an archived file back to the active roster. Does not commit.

    **A recalled file past the age stays recalled.** The inactivity rule lets
    go of a file once the patient visits again; the age rule never does —
    nobody gets younger — so without this the next sweep would archive the
    file somebody just brought back, and "recall at any time" would last a
    night. Bringing it back is the decision, so it is recorded as one: the
    file is marked «ما يتأرشفش», which the screen shows and anyone can lift.
    Returns ``"kept"`` when that happened, ``True`` for a plain restore.
    """
    if patient.is_active:
        return False
    patient.is_active = True
    patient.archived_at = None
    patient.archive_reason = None
    if aged_out(patient, today) and not patient.archive_exempt:
        exempt(patient, user=user)
        return "kept"
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
    lists = review(years, today)
    return {
        "total": total,
        "active": active,
        "archived": archived,
        "archived_auto": auto,
        "archived_manual": archived - auto,
        "candidates": len(lists["due"]),
        "kept": len(lists["kept"]),
    }
