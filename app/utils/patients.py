"""Helpers for the patients module: file numbers, age formatting, uploads."""
import os
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from app.extensions import db
from app.i18n import t
from app.models import Patient, Setting
from app.utils import numbering

ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

# Defaults; overridable via the settings table without code changes.
DEFAULT_SCHEME = "yearly"          # "yearly" -> AT-2026-0001, "fixed" -> AT-000123
#
# The *letters* are not a constant any more. They used to be ``PM`` and
# ``GC`` — the second one being one particular clinic's initials, handed out
# by every copy of the program wherever it was installed. They now come from
# the name of the clinic this copy belongs to, and once a file number has gone
# out, from the numbers already issued rather than from the name — so renaming
# a clinic never splits its series. See :mod:`app.utils.numbering`.


def _next_sequence(prefix):
    """Highest trailing integer among existing numbers sharing ``prefix``,
    plus one — asked of the database (see :mod:`app.utils.sequences`)."""
    from app.utils.sequences import highest

    return highest(Patient.patient_number, prefix) + 1


def generate_patient_number(scheme=None, prefix=None):
    """Generate the next unique system file number.

    Two schemes (selectable in settings):
      * ``yearly`` -> ``<PREFIX>-YYYY-NNNN`` (sequence resets each year)
      * ``fixed``  -> ``<PREFIX>-NNNNNN``    (single continuous sequence)
    """
    scheme = scheme or Setting.get("patient_number_scheme", DEFAULT_SCHEME)

    if scheme == "fixed":
        prefix = prefix or numbering.prefix_for("fixed")
        base = f"{prefix}-"
        seq = _next_sequence(base)
        candidate = f"{base}{seq:06d}"
    else:  # yearly (default)
        prefix = prefix or numbering.prefix_for("yearly")
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


_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _search_date(term):
    """``(start, end)`` of the birth dates a typed term names — a whole day
    (``2021-05-03``, ``3/5/2021``, ``3-5-2021``, ``3.5.2021``) or a whole
    year (``2021``) — or ``None`` when it names no date."""
    from datetime import date

    term = term.translate(_ARABIC_DIGITS)
    if term.isdigit() and len(term) == 4 and 1900 <= int(term) <= 2100:
        year = int(term)
        return date(year, 1, 1), date(year, 12, 31)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            day = datetime.strptime(term, fmt).date()
        except ValueError:
            continue
        return day, day
    return None


def _term_conditions(term):
    """Every field one typed term may match, as a list of SQL conditions."""
    from sqlalchemy import or_

    from app.extensions import db
    from app.models import Parent

    like = f"%{term}%"
    western = term.translate(_ARABIC_DIGITS)
    conds = [
        Patient.full_name.ilike(like),
        Patient.full_name_en.ilike(like),
        Patient.patient_number.ilike(like),
        Patient.reference_number.ilike(like),
        Patient.national_id.ilike(like),
        # The mother's, the father's or the guardian's name — «ابن مين؟» is
        # how half of every waiting room is found.
        Patient.family_id.in_(db.session.query(Parent.family_id).filter(or_(
            Parent.full_name.ilike(like), Parent.full_name_en.ilike(like)))),
    ]
    # Phone search: only when the term has digits, matched against normalised
    # (space/dash-free) numbers so formatting differences don't hide a match.
    digits = "".join(ch for ch in term.translate(_ARABIC_DIGITS) if ch.isdigit())
    if digits:
        pat = f"%{digits}%"
        conds.append(_digits_norm(Patient.own_phone).like(pat))
        guardians = db.session.query(Parent.family_id).filter(or_(
            _digits_norm(Parent.phone).like(pat),
            _digits_norm(Parent.phone_alt).like(pat),
        ))
        conds.append(Patient.family_id.in_(guardians))
    if western != term:
        # A file or national number typed in Arabic-Indic digits.
        conds += [Patient.patient_number.ilike(f"%{western}%"),
                  Patient.national_id.ilike(f"%{western}%")]
    born = _search_date(term)
    if born is not None:
        conds.append(Patient.date_of_birth.between(*born))
    return conds


def apply_patient_search(query, q):
    """Filter a Patient query by a free-text term.

    Matches the child's name, file number, legacy reference, national id,
    **the name of a parent or guardian**, **the date of birth** (a day in any
    of the usual ways of writing one, or a year) and — when the term has
    digits — any phone on record: the child's own and their guardians'.
    Arabic-Indic digits are read as digits.

    **Several words narrow it down.** «سارة 2021» or «أحمد 0100» finds the
    children every word matches, each word in any field; and the whole phrase
    still matches as before, so a search that found a child yesterday finds
    them today. Shared by every patient-listing page and every patient picker,
    so search behaves identically everywhere.
    """
    from sqlalchemy import and_, or_

    q = (q or "").strip()
    if not q:
        return query
    phrase = or_(*_term_conditions(q))
    words = [w for w in q.split() if w]
    if len(words) < 2:
        return query.filter(phrase)
    each = and_(*[or_(*_term_conditions(w)) for w in words])
    return query.filter(or_(phrase, each))


def patient_hint(patient, lang="ar"):
    """One line that tells two children of the same name apart, for every
    picker: the date of birth and age, the mother's name, and the last digits
    of the contact phone. Only what is written; nothing guessed."""
    parts = []
    if patient.date_of_birth:
        years, months = patient.age_parts
        age = (f"{years}y {months}m" if years else f"{months}m") if lang == "en" else (
            f"{years} سنة {months} شهر" if years else f"{months} شهر")
        parts.append(f"{patient.date_of_birth.isoformat()} ({age})")
    family = getattr(patient, "family", None)
    if family is not None:
        mother = next((g for g in (family.parents or []) if g.relation == "mother"), None)
        if mother is not None and (mother.full_name or "").strip():
            label = "Mother" if lang == "en" else "الأم"
            parts.append(f"{label}: {mother.display_name(lang)}")
    phone = "".join(ch for ch in (patient.contact_phone or "") if ch.isdigit())
    if len(phone) >= 4:
        parts.append(f"…{phone[-4:]}")
    return " · ".join(parts)


def patient_number_allocator(scheme=None, prefix=None):
    """Return a generator of sequential file numbers with no per-call DB query.

    ``generate_patient_number`` asks the database for the highest number on
    every call — one query now (it used to read every patient, which turned a
    bulk import into an O(n²) hang), but still one per child. This computes
    the starting sequence once and then increments in memory — callers must
    persist the patients so a later import continues from the right number.
    """
    scheme = scheme or Setting.get("patient_number_scheme", DEFAULT_SCHEME)
    if scheme == "fixed":
        prefix = prefix or numbering.prefix_for("fixed")
        base = f"{prefix}-"
        width = 6
    else:  # yearly
        prefix = prefix or numbering.prefix_for("yearly")
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


# ----------------------------------------- the file that gets finished later
#
# Reception registers a child in three fields because there is a child in
# front of them, and the rest of the file gets written when there is time.
# That is not sloppiness — it is the only way an emergency desk can work, and
# refusing it would push the registration onto paper.
#
# **What makes it safe is that the gap is visible afterwards**, which is what
# `app.utils.patient_basics` is for. This function exists so the three fields
# are the *same* three wherever the quick door is opened: the appointment
# desk had its own copy, the booking screen was about to grow a second, and
# two copies of a rule about what a patient record must contain is how the
# two screens end up disagreeing about it.

#: What to tell whoever is registering, per missing field. Three fields, and
#: each one is there for a reason: a name so somebody can be called; a date of
#: birth because every dose in the program is weight- and age-bound and a child
#: with no age cannot be prescribed for; a sex because the growth charts and
#: the reference ranges are different curves.
QUICK_REASONS = {"name": "patients.quick_need_name",
                 "gender": "patients.quick_need_gender",
                 "dob": "patients.quick_need_dob"}


def quick_create(full_name, gender, date_of_birth):
    """Register a child from the three fields, or say which one is wrong.

    Returns ``(patient, reason)`` — exactly one of them set. ``reason`` is a
    key from :data:`QUICK_REASONS`, not a sentence, because the two screens
    that call this show their errors in different places and neither of them
    should be handed a string the other one worded.

    The row is added to the session and flushed so the caller has an id; the
    commit is the caller's, because on the booking screen the child and the
    case are one action and half of it landing is worse than neither.
    """
    from app.models import GENDERS

    name = (full_name or "").strip()
    if not name:
        return None, "name"
    if (gender or "").strip() not in GENDERS:
        return None, "gender"
    born = date_of_birth
    if isinstance(born, str):
        try:
            born = datetime.strptime(born.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None, "dob"
    if born is None:
        return None, "dob"

    from app.utils.sequences import claim

    patient = Patient(full_name=name, gender=gender.strip(),
                      date_of_birth=born, is_active=True)
    # Numbered while holding the write lock — two desks registering at once
    # must not both get "the next file number".
    claim(patient, "patient_number", generate_patient_number)
    return patient, None
