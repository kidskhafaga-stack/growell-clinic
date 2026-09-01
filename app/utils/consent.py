"""Which consents a visit actually needs, and whether the file has them.

Documented consent already existed — a model, a form and a printable sheet —
but only on the patient's file, which is the one place nobody is standing when
the consent is needed. The procedure happens in the room.

This works out what *this* visit asks for (a procedure was done, a device study
was run, a vaccine was given) and reports what is signed and what is missing,
so the visit can say it while the guardian is still in front of you. It warns;
it never blocks a doctor from treating a child.
"""
from datetime import timedelta

from app.models import Consent
from app.utils.clock import local_today

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
    ref = on_date or local_today()
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


# Where a clinic's own wording is kept. One key per kind **per language**,
# because a consent is signed in the language it was read in and the two are
# not translations of each other once a clinic has edited them.
def setting_key(kind, lang):
    return f"consent_text_{kind}_{lang}"


def default_statement(kind, lang):
    """The wording this program ships for one kind, in one language.

    Read from the locale files, which is where it has always lived. Kept as a
    function rather than inlined because everything below depends on the
    default remaining reachable after a clinic has overridden it: a default
    that can be edited *away* is a default the clinic can never get back.
    """
    # Asked of a *named* language, not the active one. The editor shows the
    # Arabic and the English of the same consent side by side, and `t()`
    # answers only about whichever language the request is in — so it cannot
    # be used to fill both boxes on one screen.
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    text = _lookup(tables, lang, f"consent.statements.{kind}")
    if text is None:
        text = _lookup(tables, lang, "consent.default_statement")
    return text or ""


def clinic_statement(kind, lang):
    """The clinic's own wording for one kind, or ``""`` if it uses ours."""
    from app.models import Setting

    try:
        return (Setting.get(setting_key(kind, lang)) or "").strip()
    except Exception:  # noqa: BLE001 — a settings table that is not ready yet
        return ""


def statement_in(kind, lang):
    """What would be signed for this kind, in this language: theirs or ours.

    Overrides sit **beside** the default rather than replacing it, so a clinic
    that has rewritten every consent can still be shown what the program says
    and put it back in one press. The same rule the clinical thresholds
    follow: editable, and not losable.
    """
    return clinic_statement(kind, lang) or default_statement(kind, lang)


def statement_for(kind):
    """The wording for one kind of consent, in the language in use.

    Reported: *"the wording of the consents — its own text for each kind,
    clear in Arabic and in English according to the language in use."* There
    was one sentence for all seven: a photography consent and an anaesthesia
    consent were signed under identical words about "the nature of the medical
    service, its risks and alternatives". That sentence is true of both and
    says what is being agreed to in neither — and a consent form's entire job
    is to say what is being agreed to.

    The language is the one being read at the moment of signing, which is the
    right one: it is the language the guardian was shown the words in.

    Falls back to the general wording for a kind with no text of its own, so a
    new consent type is never signed under a blank.
    """
    from flask import g

    return statement_in(kind, getattr(g, "lang", "ar"))


def all_statements():
    """``{kind: text}`` for the form, so the screen can show the words that
    will be signed the moment the kind is picked."""
    from app.models import CONSENT_TYPES

    return {kind: statement_for(kind) for kind in CONSENT_TYPES}


def record(patient, kind, guardian_name, relation=None, id_no=None,
           statement=None, notes=None, user_id=None, on_date=None):
    """Write one consent for the patient (caller commits).

    The wording is **stored on the row**, not looked up when the form is
    printed. Printing it live meant the paper showed today's text and today's
    language — so re-printing a consent after the wording was edited, or from
    an English session, produced a document stating that somebody agreed to
    words they had never been shown. What was signed is a fact about that day.
    """
    from app.models import CONSENT_TYPES

    kind = kind if kind in CONSENT_TYPES else "general"
    row = Consent(
        patient_id=patient.id,
        consent_type=kind,
        guardian_name=guardian_name,
        guardian_relation=relation or None,
        guardian_id_no=id_no or None,
        statement=(statement or "").strip() or statement_for(kind),
        notes=notes or None,
        signed_date=on_date or local_today(),
        obtained_by=user_id,
    )
    from app.extensions import db
    db.session.add(row)
    return row
