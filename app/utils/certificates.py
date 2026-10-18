"""Medical certificates from the visit (DOCTOR_EASE_PLAN.md ب-٣) — see
``models/medical_certificate.py``.

The wording of each kind is the clinic's: a text per kind and language in the
settings (``cert_text:<kind>:<lang>``), with the program's own as the start.
The text names what it needs in braces and the visit fills it in:

``{name}`` ``{age}`` ``{file}`` ``{date}`` ``{from}`` ``{to}`` ``{days}``
``{purpose}`` ``{to_whom}`` ``{complaint}`` ``{exam}`` ``{plan}``
``{diagnosis}`` ``{doctor}``

``{diagnosis}`` is empty unless the family agreed to it appearing.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.medical_certificate import CERT_KINDS

PLACEHOLDERS = ("name", "age", "file", "date", "from", "to", "days", "purpose",
                "to_whom", "complaint", "exam", "plan", "diagnosis", "doctor")
MAX_DAYS = 365          # a typing slip (3000 for 30), not a medical limit
TEXT_MAX = 4000


class CertError(ValueError):
    """A refusal with a locale key (``cert.err_<key>``)."""


def _say(key, lang):
    """A locale string in the certificate's own language, not the screen's."""
    from app.i18n import _load_translations, _lookup

    text = _lookup(_load_translations(), lang, key)
    return text if text is not None else (_lookup(_load_translations(), "en", key) or "")


def default_text(kind, lang):
    return _say(f"cert.default_{kind}", lang)


def text_for(kind, lang):
    from app.models import Setting

    own = (Setting.get(f"cert_text:{kind}:{lang}") or "").strip()
    return own or default_text(kind, lang)


def save_text(kind, lang, text):
    """Keep the clinic's wording; an empty box goes back to the program's."""
    from app.models import Setting

    if kind not in CERT_KINDS or lang not in ("ar", "en"):
        raise CertError("kind")
    text = (text or "").strip()[:TEXT_MAX]
    Setting.set(f"cert_text:{kind}:{lang}", "" if text == default_text(kind, lang) else text)


class _Blank(dict):
    def __missing__(self, key):
        return ""


def fill(text, values):
    try:
        return text.format_map(_Blank(values))
    except (ValueError, IndexError):
        # A stray brace in the clinic's own text: print it as written rather
        # than refuse the certificate.
        out = text
        for k, v in values.items():
            out = out.replace("{" + k + "}", str(v))
        return out


def age_text(patient, lang):
    years, months = patient.age_parts
    if not years and not months:
        return _say("patients.newborn", lang)
    parts = []
    if years:
        parts.append(f"{years} {_say('patients.years', lang)}")
    if months:
        parts.append(f"{months} {_say('patients.months', lang)}")
    return " ".join(parts)


def diagnosis_of(visit, lang):
    finals = visit.final_diagnoses()
    rows = finals if finals else (visit.diagnoses[:1] if visit.diagnoses else [])
    return "، ".join(d.display_title(lang) for d in rows) if lang == "ar" else \
        ", ".join(d.display_title(lang) for d in rows)


def next_number(on=None):
    from app.models import MedicalCertificate

    year = (on or datetime.utcnow()).year
    prefix = f"{year}-"
    last = (MedicalCertificate.query.filter(MedicalCertificate.number.like(prefix + "%"))
            .order_by(MedicalCertificate.number.desc()).first())
    seq = int(last.number.split("-")[1]) + 1 if last else 1
    return f"{prefix}{seq:05d}"


def _date(value):
    from datetime import date

    if isinstance(value, date):
        return value
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def issue(visit, user, kind, lang="ar", addressed_to="", purpose="", date_from=None,
          days=None, show_diagnosis=False, note=""):
    """Write one certificate for this visit, numbered and kept."""
    from app.models import MedicalCertificate

    if kind not in CERT_KINDS:
        raise CertError("kind")
    lang = lang if lang in ("ar", "en") else "ar"
    addressed_to = (addressed_to or "").strip()[:160]
    purpose = (purpose or "").strip()[:160]
    start = end = None
    if kind == "sick_leave":
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise CertError("days") from None
        if not 1 <= days <= MAX_DAYS:
            raise CertError("days")
        start = _date(date_from) or visit.visit_date
        end = start + timedelta(days=days - 1)
    else:
        days = None
    if kind == "fitness" and not purpose:
        raise CertError("purpose")

    patient = visit.patient
    doctor = visit.doctor or user
    # In an Arabic sentence a date or a file number is written left to right;
    # without an isolate around it «P-1024» prints as «1024-P» and a date
    # reads backwards.
    ltr = (lambda v: f"\u2066{v}\u2069" if v else v) if lang == "ar" else (lambda v: v)
    dx = diagnosis_of(visit, lang) if show_diagnosis else ""
    values = {
        "name": patient.display_name(lang), "age": age_text(patient, lang),
        # A non-breaking hyphen: a line never ends on «P-» with «1024» below.
        "file": ltr((patient.patient_number or "").replace("-", "\u2011")), "date": ltr(visit.visit_date.isoformat()),
        "from": ltr(start.isoformat()) if start else "", "to": ltr(end.isoformat()) if end else "",
        "days": days or "", "purpose": purpose,
        "to_whom": addressed_to or _say("cert.to_whom_body", lang),
        "complaint": visit.chief_complaint or "—", "exam": visit.clinical_exam or "—",
        "plan": visit.plan or "—", "diagnosis": dx,
        "doctor": doctor.doctor_print_name(lang) if doctor else "",
    }
    body = fill(text_for(kind, lang), values).strip()
    row = MedicalCertificate(
        number=next_number(), kind=kind, lang=lang, patient_id=patient.id,
        visit_id=visit.id, doctor_id=doctor.id if doctor else None, issued_by=user.id,
        seen_on=visit.visit_date, addressed_to=addressed_to or None,
        purpose=purpose or None, date_from=start, days=days, date_to=end,
        diagnosis=dx or None, body=body, note=(note or "").strip()[:1000] or None)
    db.session.add(row)
    db.session.flush()
    return row


def void(cert, user, reason):
    reason = (reason or "").strip()[:255]
    if not reason:
        raise CertError("reason")
    if cert.voided_at is None:
        cert.voided_at, cert.voided_by, cert.void_reason = datetime.utcnow(), user.id, reason
    return cert


def for_patient(patient_id):
    from app.models import MedicalCertificate

    return (MedicalCertificate.query.filter_by(patient_id=patient_id)
            .order_by(MedicalCertificate.issued_at.desc()).all())


__all__ = ["CERT_KINDS", "CertError", "PLACEHOLDERS", "age_text", "default_text",
           "diagnosis_of", "fill", "for_patient", "issue", "next_number", "save_text",
           "text_for", "void"]
