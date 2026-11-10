"""«Scan the wristband» — DOCTOR_EASE ٤-ب د-٨.

The wristband is printed with a barcode of the child's file number
(``patients.wristband``). Asked by the owner: *the nurse should get something
out of it* — scan it and the child opens; scan it before giving a dose,
hanging blood or drawing a sample, and the program says when it is another
child.

**The hospital chooses** how strict (:data:`SETTING`):

* ``off`` — no scan boxes anywhere;
* ``optional`` (the default) — the box is there; a scan of another child is
  refused, and no scan is not;
* ``required`` — a dose, a bag or a tube on a child in a bed waits for the
  scan.

A child who is not in a bed or in emergency wears no band, so a sample drawn
at the clinic is never asked for one — the clinic's behaviour does not change.
Works with a barcode reader (it types the number and Enter) and with a phone
camera (``static/js/scan.js``).
"""
SETTING = "band_scan"
MODES = ("off", "optional", "required")
DEFAULT = "optional"


def mode():
    from app.models import Setting

    got = (Setting.get(SETTING, DEFAULT) or DEFAULT).strip()
    return got if got in MODES else DEFAULT


def on():
    return mode() != "off"


def _clean(code):
    # Code 39 readers may pass the start/stop asterisks through.
    return (code or "").strip().strip("*").strip()


def find(code):
    """The child whose band this is, or ``None``."""
    from app.models import Patient

    code = _clean(code)
    if not code:
        return None
    row = Patient.query.filter(Patient.patient_number == code).first()
    if row is None:
        row = Patient.query.filter(Patient.patient_number.ilike(code)).first()
    return row


def wears_a_band(patient):
    """In a bed or in emergency now — the children who wear one."""
    from app.models import Admission, EmergencyVisit

    if patient is None:
        return False
    if Admission.query.filter_by(patient_id=patient.id, discharged_at=None).first():
        return True
    return EmergencyVisit.query.filter_by(patient_id=patient.id, departed_at=None).first() is not None


def check(patient_id, code, banded=True):
    """Why this act is refused, or ``None``: ``(key, other_child_or_None)``
    with key ``band_needed`` / ``band_unknown`` / ``band_other``. ``banded`` —
    whether this child wears a band at all (a clinic outpatient does not)."""
    m = mode()
    if m == "off" or not banded:
        return None
    code = _clean(code)
    if not code:
        return ("band_needed", None) if m == "required" else None
    child = find(code)
    if child is None:
        return ("band_unknown", None)
    if child.id != patient_id:
        return ("band_other", child)
    return None


def scanned(code):
    """Whether a band was scanned with the act (for the record)."""
    return bool(_clean(code))


def say(why, lang="ar"):
    """The refusal in words."""
    from app.i18n import t

    key, other = why
    if key == "band_other":
        return t("band.err_other", name=other.display_name(lang), number=other.patient_number)
    return t("band." + ("err_needed" if key == "band_needed" else "err_unknown"))


def destination(patient):
    """Where a scan of this band opens: the open stay (on its treatment), the
    open emergency attendance, or the child's file."""
    from flask import url_for

    from app.models import Admission, EmergencyVisit

    stay = Admission.query.filter_by(patient_id=patient.id, discharged_at=None).first()
    if stay is not None:
        return url_for("beds.admission", admission_id=stay.id) + "#treatment"
    er = EmergencyVisit.query.filter_by(patient_id=patient.id, departed_at=None).first()
    if er is not None:
        return url_for("emergency.attendance", attendance_id=er.id)
    return url_for("patients.view", patient_id=patient.id)
