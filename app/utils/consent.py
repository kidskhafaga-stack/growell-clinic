"""Which consents a visit actually needs, and whether the file has them.

Documented consent already existed — a model, a form and a printable sheet —
but only on the patient's file, which is the one place nobody is standing when
the consent is needed. The procedure happens in the room.

This works out what *this* visit asks for (a procedure was done, a device study
was run, a vaccine was given) and reports what is signed and what is missing,
so the visit can say it while the guardian is still in front of you. It warns;
it never blocks a doctor from treating a child.
"""
from datetime import date, timedelta

from app.models import Consent

# A general consent covers the visit itself; the others are asked for by what
# was actually done. Kept small on purpose: a warning nobody reads is worse
# than no warning.
GENERAL_VALID_DAYS = 365


def signed_kinds(patient, on_date=None):
    """The consent kinds on file that still count on ``on_date``.

    A general consent is treated as valid for a year; a consent for something
    done (procedure/vaccination/anaesthesia…) counts for the day it covers and
    afterwards — it documents an event, it doesn't expire retroactively.
    """
    if patient is None:
        return set()
    ref = on_date or date.today()
    out = set()
    for c in getattr(patient, "consents", []):
        if c.signed_date is None or c.signed_date > ref:
            continue
        if c.consent_type == "general":
            if c.signed_date >= ref - timedelta(days=GENERAL_VALID_DAYS):
                out.add("general")
            continue
        out.add(c.consent_type)
    return out


def needed_for_visit(visit):
    """The consent kinds this visit calls for, with why.

    Returns ``[{"kind": …, "reason": …}]`` — reason is a translation key
    suffix, so the screen phrases it in the user's language.
    """
    if visit is None:
        return []
    needed = [{"kind": "general", "reason": "visit"}]
    services = list(getattr(visit, "services", []) or [])
    if any((vs.service.category if vs.service else "") in
           ("procedure", "radiology", "lab") for vs in services):
        needed.append({"kind": "procedure", "reason": "procedure"})
    if getattr(visit, "studies", None):
        if not any(n["kind"] == "procedure" for n in needed):
            needed.append({"kind": "procedure", "reason": "study"})
    if _vaccines_today(visit):
        needed.append({"kind": "vaccination", "reason": "vaccine"})
    return needed


def _vaccines_today(visit):
    """Doses given to this patient on the visit's date."""
    from app.models import PatientVaccine

    if visit is None or not visit.patient_id:
        return []
    return (PatientVaccine.query
            .filter(PatientVaccine.patient_id == visit.patient_id,
                    PatientVaccine.given_date == visit.visit_date,
                    PatientVaccine.event_type == "given").all())


def visit_status(visit):
    """``{"needed": [...], "missing": [...], "signed": {...}}`` for the visit."""
    if visit is None:
        return {"needed": [], "missing": [], "signed": set()}
    have = signed_kinds(visit.patient, visit.visit_date)
    needed = needed_for_visit(visit)
    missing = [n for n in needed if n["kind"] not in have]
    return {"needed": needed, "missing": missing, "signed": have}


def default_guardian(patient, lang=None):
    """Who signs on the child's behalf: the primary guardian, if we know one.

    The name comes from ``display_name(lang)`` and not from ``full_name``.
    Reading the column directly always gives the Arabic name, while the patient
    file next to it uses the language-aware version — so the same guardian
    appeared under two different names on two screens, and one of them ends up
    on a signed consent. A consent is a document with somebody's name on it;
    which name it carries is not a formatting detail.

    ``lang`` defaults to the request's language, so callers that have no
    opinion get the same answer as the rest of the page.
    """
    from flask import g

    guardian = getattr(patient, "primary_guardian", None) if patient else None
    if guardian is None:
        return {"name": "", "relation": "", "id_no": ""}
    lang = lang or getattr(g, "lang", "ar")
    return {
        "name": guardian.display_name(lang) or "",
        "relation": guardian.relation or "",
        "id_no": getattr(guardian, "national_id", "") or "",
    }


def record(patient, kind, guardian_name, relation=None, id_no=None,
           statement=None, notes=None, user_id=None, on_date=None):
    """Write one consent for the patient (caller commits)."""
    from app.models import CONSENT_TYPES

    row = Consent(
        patient_id=patient.id,
        consent_type=kind if kind in CONSENT_TYPES else "general",
        guardian_name=guardian_name,
        guardian_relation=relation or None,
        guardian_id_no=id_no or None,
        statement=statement or None,
        notes=notes or None,
        signed_date=on_date or date.today(),
        obtained_by=user_id,
    )
    from app.extensions import db
    db.session.add(row)
    return row
