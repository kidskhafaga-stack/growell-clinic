"""Helpers for the patients module: file numbers, age formatting, uploads."""
import os
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from app.i18n import t
from app.models import Patient, Setting

ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

# Defaults; overridable via the settings table without code changes.
DEFAULT_SCHEME = "yearly"          # "yearly" -> PM-2026-0001, "fixed" -> GC-000123
DEFAULT_YEARLY_PREFIX = "PM"
DEFAULT_FIXED_PREFIX = "GC"


def _next_sequence(prefix):
    """Highest trailing integer among existing numbers sharing ``prefix``."""
    rows = Patient.query.filter(
        Patient.patient_number.like(prefix + "%")
    ).all()
    top = 0
    for row in rows:
        tail = row.patient_number[len(prefix):]
        try:
            top = max(top, int(tail))
        except (ValueError, TypeError):
            continue
    return top + 1


def generate_patient_number(scheme=None, prefix=None):
    """Generate the next unique system file number.

    Two schemes (selectable in settings):
      * ``yearly`` -> ``<PREFIX>-YYYY-NNNN`` (sequence resets each year)
      * ``fixed``  -> ``<PREFIX>-NNNNNN``    (single continuous sequence)
    """
    scheme = scheme or Setting.get("patient_number_scheme", DEFAULT_SCHEME)

    if scheme == "fixed":
        prefix = prefix or Setting.get(
            "patient_number_prefix_fixed", DEFAULT_FIXED_PREFIX
        )
        base = f"{prefix}-"
        seq = _next_sequence(base)
        candidate = f"{base}{seq:06d}"
    else:  # yearly (default)
        prefix = prefix or Setting.get(
            "patient_number_prefix", DEFAULT_YEARLY_PREFIX
        )
        year = datetime.utcnow().year
        base = f"{prefix}-{year}-"
        seq = _next_sequence(base)
        candidate = f"{base}{seq:04d}"

    # Guard against rare collisions (e.g. concurrent imports).
    while Patient.query.filter_by(patient_number=candidate).first() is not None:
        seq += 1
        candidate = (
            f"{base}{seq:06d}" if scheme == "fixed" else f"{base}{seq:04d}"
        )
    return candidate


def _digits_norm(col):
    """SQL expression that strips spaces, dashes and a leading + from a phone
    column, so a stored ``0100 000-0000`` still matches a typed ``01000000000``.

    The example is deliberately a number nobody has. It used to be a real one,
    which mattered the moment this repository stopped being private.
    """
    from sqlalchemy import func
    return func.replace(func.replace(func.replace(col, " ", ""), "-", ""), "+", "")


def apply_patient_search(query, q):
    """Filter a Patient query by a free-text term.

    Matches the patient's name, file number, legacy reference, national id and
    — when the term contains digits — any phone on record: the patient's own
    number *and* their guardians' primary/alt numbers. Shared by every patient-
    listing page (patients, vaccinations, growth, booking) so search behaves
    identically everywhere.
    """
    from sqlalchemy import or_

    from app.extensions import db
    from app.models import Parent

    q = (q or "").strip()
    if not q:
        return query
    like = f"%{q}%"
    conds = [
        Patient.full_name.ilike(like),
        Patient.full_name_en.ilike(like),
        Patient.patient_number.ilike(like),
        Patient.reference_number.ilike(like),
        Patient.national_id.ilike(like),
    ]

    # Phone search: only when the term has digits, matched against normalised
    # (space/dash-free) numbers so formatting differences don't hide a match.
    digits = "".join(ch for ch in q if ch.isdigit())
    if digits:
        pat = f"%{digits}%"
        conds.append(_digits_norm(Patient.own_phone).like(pat))
        guardians = db.session.query(Parent.family_id).filter(or_(
            _digits_norm(Parent.phone).like(pat),
            _digits_norm(Parent.phone_alt).like(pat),
        ))
        conds.append(Patient.family_id.in_(guardians))

    return query.filter(or_(*conds))


def patient_number_allocator(scheme=None, prefix=None):
    """Return a generator of sequential file numbers with no per-call DB query.

    ``generate_patient_number`` scans every existing patient on each call, which
    turns a bulk import into an O(n²) hang. This computes the starting sequence
    once and then increments in memory — callers must persist the patients so a
    later import continues from the right number.
    """
    scheme = scheme or Setting.get("patient_number_scheme", DEFAULT_SCHEME)
    if scheme == "fixed":
        prefix = prefix or Setting.get(
            "patient_number_prefix_fixed", DEFAULT_FIXED_PREFIX
        )
        base = f"{prefix}-"
        width = 6
    else:  # yearly
        prefix = prefix or Setting.get(
            "patient_number_prefix", DEFAULT_YEARLY_PREFIX
        )
        base = f"{prefix}-{datetime.utcnow().year}-"
        width = 4

    seq = _next_sequence(base) - 1

    def allocate():
        nonlocal seq
        seq += 1
        return f"{base}{seq:0{width}d}"

    return allocate


def format_age(years, months, lang="ar"):
    """Human-friendly pediatric age, e.g. ``3y 2m`` / ``3 سنة 2 شهر``."""
    if lang == "ar":
        if years == 0 and months == 0:
            return t("patients.newborn")
        parts = []
        if years:
            parts.append(f"{years} {t('patients.years')}")
        if months:
            parts.append(f"{months} {t('patients.months')}")
        return " ".join(parts)
    # English / default
    if years == 0 and months == 0:
        return t("patients.newborn")
    parts = []
    if years:
        parts.append(f"{years}{t('patients.y_short')}")
    if months:
        parts.append(f"{months}{t('patients.m_short')}")
    return " ".join(parts)


def allowed_photo(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_PHOTO_EXTENSIONS
    )


def save_patient_photo(file_storage, upload_dir):
    """Persist an uploaded photo and return its stored filename, or None."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_photo(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, secure_filename(name)))
    return name


def delete_patient_photo(filename, upload_dir):
    if not filename:
        return
    path = os.path.join(upload_dir, filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
