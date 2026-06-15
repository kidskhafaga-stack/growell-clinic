"""Helpers for the patients module: file numbers, age formatting, uploads."""
import os
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from app.i18n import t
from app.models import Patient

ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def generate_patient_number():
    """Generate the next file number as ``PM-YYYY-NNNN``.

    The sequence resets per calendar year; gaps from deleted records are
    tolerated since the number only needs to be unique, not contiguous.
    """
    year = datetime.utcnow().year
    prefix = f"PM-{year}-"
    last = (
        Patient.query.filter(Patient.patient_number.like(prefix + "%"))
        .order_by(Patient.patient_number.desc())
        .first()
    )
    if last is None:
        seq = 1
    else:
        try:
            seq = int(last.patient_number.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = Patient.query.filter(
                Patient.patient_number.like(prefix + "%")
            ).count() + 1
    return f"{prefix}{seq:04d}"


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
