"""The child's record in a language other systems read — FHIR R4.

A file, not a door. The doctor presses a button on the child's file and gets
one JSON document (a FHIR ``Bundle`` of type ``collection``) to hand to the
hospital the child is going to, the insurer or whoever asked. Nothing listens
on the network and nothing is sent anywhere: the record leaves the building
the way the printed report does, in someone's hand, and the audit log says
who took it.

**Plain R4, and no profile claimed.** Nobody has yet said who will receive
these files, and each receiver narrows FHIR its own way (the International
Patient Summary, a national profile, an insurer's). A file that claimed one of
those and met it by accident would be worse than one that claims nothing, so
it follows the base specification and waits to be told.

**No code this program does not hold.** A code in a FHIR file is a promise
to a machine that will act on it without asking. So:

* diagnoses carry their ICD code in the ICD-10 or ICD-11 system the doctor
  chose it from — and no code at all when the doctor wrote only a title;
* the growth and vital-sign readings carry the LOINC codes the FHIR vital
  signs profile names for exactly those measurements, in UCUM units — they
  are what the columns *are*, not a guess about what a free-text field meant;
* everything the clinic names itself — its vaccines, its file numbers — is
  labelled as the clinic's own, in a system that belongs to this clinic
  (see :func:`namespace`), never passed off as a national or WHO code;
* everything else is the clinic's own words, as text.

**What is not in it yet**, so the file never reads as more complete than it
is: nursing observation rounds, specialty measurement panels, dental charts,
the free text of a visit's examination and plan, documents and scans, and
money. They are listed in ``docs/FHIR_EXPORT.md``.
"""
import json
import uuid
from datetime import date, datetime, timezone

from app.extensions import db

FHIR_VERSION = "4.0.1"
MEDIA_TYPE = "application/fhir+json"

ICD_SYSTEMS = {"10": "http://hl7.org/fhir/sid/icd-10",
               "11": "http://id.who.int/icd/release/11/mms"}
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
_TERMINOLOGY = "http://terminology.hl7.org/CodeSystem/"

#: The clinic's own identifier for this installation's records. Random,
#: made on the first export and kept: stable, so a receiver sees the same
#: child as the same child next time, and saying nothing about the machine.
NAMESPACE_KEY = "fhir_namespace"

# (column, LOINC, display, UCUM code) — the codes the FHIR vital signs
# profile fixes for these measurements.
GROWTH = (
    ("weight_kg", "29463-7", "Body weight", "kg"),
    ("height_cm", "8302-2", "Body height", "cm"),
    ("head_circ_cm", "9843-4", "Head Occipital-frontal circumference", "cm"),
    ("bmi", "39156-5", "Body mass index (BMI) [Ratio]", "kg/m2"),
)
VITALS = (
    ("temperature_c", "8310-5", "Body temperature", "Cel"),
    ("pulse_bpm", "8867-4", "Heart rate", "/min"),
    ("resp_rate", "9279-1", "Respiratory rate", "/min"),
    ("spo2", "2708-6", "Oxygen saturation in Arterial blood", "%"),
)
BLOOD_PRESSURE = ("85354-9", "Blood pressure panel with all children optional")
SYSTOLIC = ("8480-6", "Systolic blood pressure")
DIASTOLIC = ("8462-4", "Diastolic blood pressure")
BIRTH_WEIGHT = ("8339-4", "Birth weight Measured")
BLOOD_GROUP = ("882-1", "ABO and Rh group [Type] in Blood")

#: Who the adult on the family card is to the child, in HL7's own words.
RELATION = {"father": ("FTH", "father"), "mother": ("MTH", "mother"),
            "guardian": ("GUARD", "guardian")}

# How sure the doctor was, where the program recorded it. A *secondary*
# diagnosis is a rank, not a certainty, and says nothing either way.
DX_VERIFICATION = {"final": "confirmed", "working": "provisional"}

VISIT_STATUS = {"completed": "finished", "open": "in-progress"}


# ------------------------------------------------------------ helpers ----
def namespace():
    """This clinic's namespace — made once, on the first export. The caller
    commits."""
    from app.models import Setting

    value = Setting.get(NAMESPACE_KEY)
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        made = uuid.uuid4()
        Setting.set(NAMESPACE_KEY, str(made))
        return made


def _instant(moment):
    """A stored moment (UTC, naive) as a FHIR instant."""
    if moment is None:
        return None
    if isinstance(moment, datetime):
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.isoformat(timespec="seconds")
    return moment.isoformat()


def _day(value):
    """A clinic day (a ``date``) as a FHIR date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, date) else None


def _text(*parts):
    """Non-empty parts, joined — or ``None`` when there is nothing to say."""
    words = [str(p).strip() for p in parts if p is not None and str(p).strip()]
    return " — ".join(words) or None


def _concept(text, coding=None):
    concept = {}
    if coding:
        concept["coding"] = [coding]
    if text:
        concept["text"] = text
    return concept


def _hl7(system, code, display=None):
    coding = {"system": _TERMINOLOGY + system, "code": code}
    if display:
        coding["display"] = display
    return coding


def _clean(value):
    """Drop empty fields: FHIR forbids an element with no value in it."""
    if isinstance(value, dict):
        out = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        out = [_clean(v) for v in value]
        return [v for v in out if v not in (None, "", [], {})]
    return value


DATA_ABSENT = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"


def _absent(reason="unknown"):
    """An element nobody recorded, said so — FHIR's own way of leaving a
    required field honestly empty instead of filling it with a guess."""
    return {"extension": [{"url": DATA_ABSENT, "valueCode": reason}]}


def _number(value):
    """A stored reading as a JSON number, or ``None`` when there is none."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 4)


# ------------------------------------------------------------ builder ----
class _Record:
    """One bundle being assembled. Every resource gets a stable id derived
    from the clinic's namespace and the row it came from, so references
    inside the file resolve and a second export names things the same way."""

    def __init__(self, ns, lang="ar"):
        self.ns = ns
        self.lang = lang
        self.entries = []
        self.seen = set()

    # -- identity -----------------------------------------------------
    def uid(self, kind, row_id):
        return str(uuid.uuid5(self.ns, f"{kind}/{row_id}"))

    def ref(self, kind, row_id):
        return {"reference": f"urn:uuid:{self.uid(kind, row_id)}"}

    def system(self, name):
        """A code system that is this clinic's own — its file numbers, its
        vaccine codes. A URN, so it can never be taken for anyone else's."""
        return f"urn:uuid:{uuid.uuid5(self.ns, 'system/' + name)}"

    def add(self, kind, row_id, resource):
        key = (kind, row_id)
        if key in self.seen:
            return
        self.seen.add(key)
        uid = self.uid(kind, row_id)
        resource = _clean({"resourceType": kind, "id": uid, **resource})
        self.entries.append({"fullUrl": f"urn:uuid:{uid}", "resource": resource})

    # -- people -------------------------------------------------------
    def practitioner(self, user):
        """A reference to the member of staff, adding them the first time."""
        if user is None:
            return None
        names = [{"use": "official", "text": user.full_name}]
        if (user.full_name_en or "").strip():
            names.append({"use": "usual", "text": user.full_name_en})
        self.add("Practitioner", user.id, {"active": bool(user.is_active),
                                            "name": names})
        return self.ref("Practitioner", user.id)

    def place(self, name):
        """An organisation known only by the name the clinic wrote for it —
        the outside lab, the other hospital."""
        name = (name or "").strip()
        if not name:
            return None
        key = f"place-{uuid.uuid5(self.ns, 'place/' + name)}"
        self.add("Organization", key, {"active": True, "name": name})
        return self.ref("Organization", key)

    def organization(self):
        from app.models import Setting

        name = (Setting.get("clinic_name_ar") or Setting.get("clinic_name")
                or "").strip()
        if not name:
            return None
        english = (Setting.get("clinic_name_en") or "").strip()
        self.add("Organization", "clinic", {
            "active": True, "name": name,
            "alias": [english] if english and english != name else None})
        return self.ref("Organization", "clinic")


def bundle_for(patient, lang="ar", now=None):
    """The whole exportable record of one child, as a FHIR R4 ``Bundle``
    (a ``dict``, ready for :func:`json.dumps`)."""
    record = build(patient, lang)
    stamp = now or datetime.now(timezone.utc)
    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"lastUpdated": _instant(stamp)},
        "type": "collection",
        "timestamp": _instant(stamp),
        "entry": record.entries,
    }


def build(patient, lang="ar"):
    """Every resource the record holds, in a :class:`_Record` — the one
    mapping from this program to FHIR, which the full file and the patient
    summary (:mod:`app.utils.fhir_ips`) are both read from."""
    record = _Record(namespace(), lang)
    child = record.ref("Patient", patient.id)
    _patient(record, patient)
    _allergies(record, patient, child)
    _problems(record, patient, child)
    _birth_and_blood(record, patient, child)
    _visits(record, patient, child)
    _stays(record, patient, child)
    _growth(record, patient, child)
    _results(record, patient, child)
    _immunizations(record, patient, child)
    _prescriptions(record, patient, child)
    _inpatient_orders(record, patient, child)
    _long_term_medicines(record, patient, child)
    _operations(record, patient, child)
    return record


def dumps(bundle):
    """The bundle as the file that is downloaded — UTF-8, Arabic as itself."""
    return json.dumps(bundle, ensure_ascii=False, indent=2)


# ------------------------------------------------------------ the child ----
def _patient(record, patient):
    identifiers = [{
        "use": "usual",
        "type": _concept("Medical record number",
                         _hl7("v2-0203", "MR", "Medical record number")),
        "system": record.system("patient-number"),
        "value": patient.patient_number,
    }]
    if (patient.national_id or "").strip():
        identifiers.append({
            "use": "official",
            "type": _concept("National ID",
                             _hl7("v2-0203", "NI",
                                  "National unique individual identifier")),
            # The clinic's record of the number, not the registry's system:
            # nothing has told this program which URI the registry uses.
            "system": record.system("national-id"),
            "value": patient.national_id.strip(),
        })
    names = [{"use": "official", "text": patient.full_name}]
    if (patient.full_name_en or "").strip():
        names.append({"use": "usual", "text": patient.full_name_en})
    contacts = []
    family = patient.family
    for parent in (family.parents if family is not None else []):
        code, word = RELATION.get(parent.relation, (None, None))
        phones = [p for p in (parent.phone, parent.phone_alt) if (p or "").strip()]
        contacts.append({
            # Who they are to the child, and — in the list FHIR binds this
            # field to — that they are the child's next of kin, which a
            # parent or guardian on the family card is.
            "relationship": [
                _concept(parent.relation,
                         _hl7("v3-RoleCode", code, word) if code else None),
                _concept(None, _hl7("v2-0131", "N", "Next-of-Kin")),
            ],
            "name": {"text": parent.full_name},
            "telecom": [{"system": "phone", "value": p.strip()} for p in phones]
            + ([{"system": "email", "value": parent.email.strip()}]
               if (parent.email or "").strip() else []),
            "address": ({"text": parent.address.strip()}
                        if (parent.address or "").strip() else None),
        })
    resource = {
        "identifier": identifiers,
        "active": bool(patient.is_active),
        "name": names,
        "telecom": ([{"system": "phone", "value": patient.own_phone.strip()}]
                    if (patient.own_phone or "").strip() else None),
        "gender": patient.gender if patient.gender in ("male", "female")
        else "unknown",
        "birthDate": _day(patient.date_of_birth),
        "contact": contacts,
        "managingOrganization": record.organization(),
    }
    record.add("Patient", patient.id, resource)


def _allergies(record, patient, child):
    """The allergies exactly as the clinic typed them — one per phrase, the
    same phrases the prescription check reads."""
    from app.utils.allergy import allergy_phrases

    for index, phrase in enumerate(allergy_phrases(patient)):
        record.add("AllergyIntolerance", f"{patient.id}-{index}", {
            "clinicalStatus": _concept(
                None, _hl7("allergyintolerance-clinical", "active", "Active")),
            "code": _concept(phrase),
            "patient": child,
        })


def _problems(record, patient, child):
    """The problem list, and the free-text chronic conditions on the card."""
    from app.models import PatientProblem

    rows = (PatientProblem.query.filter_by(patient_id=patient.id)
            .order_by(PatientProblem.id).all())
    for row in rows:
        resolved = row.status == "resolved"
        record.add("Condition", f"problem-{row.id}", {
            "clinicalStatus": _concept(None, _hl7(
                "condition-clinical", "resolved" if resolved else "active")),
            "category": [_concept(None, _hl7(
                "condition-category", "problem-list-item", "Problem List Item"))],
            "code": _dx_code(row.icd_code, row.icd_version, row.title,
                             row.title_en),
            "subject": child,
            "onsetDateTime": _day(row.onset_date),
            "abatementDateTime": _day(row.resolved_date) if resolved else None,
            "recordedDate": _day(row.noted_date),
            "note": [{"text": row.notes}] if (row.notes or "").strip() else None,
        })
    for index, phrase in enumerate(_phrases(patient.chronic_diseases)):
        record.add("Condition", f"chronic-{patient.id}-{index}", {
            "clinicalStatus": _concept(None, _hl7("condition-clinical",
                                                  "active")),
            "category": [_concept(None, _hl7(
                "condition-category", "problem-list-item", "Problem List Item"))],
            "code": _concept(phrase),
            "subject": child,
        })


def _phrases(text):
    import re

    return [p.strip() for p in re.split(r"[,،;\n]", text or "") if p.strip()]


def _dx_code(code, version, title, title_en=None):
    """A diagnosis as a CodeableConcept: the ICD code in the book it was
    chosen from, and the doctor's words. A code whose book nobody recorded
    goes in as text — naming the book would be inventing it."""
    code = (code or "").strip()
    system = ICD_SYSTEMS.get((version or "").strip())
    coding = None
    if code and system:
        coding = {"system": system, "code": code}
        if (title_en or "").strip():
            coding["display"] = title_en.strip()
    words = title
    if code and not system:
        words = _text(code, title)
    return _concept(words, coding)


def _birth_and_blood(record, patient, child):
    if patient.birth_weight_kg:
        record.add("Observation", f"birth-weight-{patient.id}", {
            "status": "final",
            "category": [_vital_category()],
            "code": _loinc(*BIRTH_WEIGHT),
            "subject": child,
            "effectiveDateTime": _day(patient.date_of_birth),
            "valueQuantity": _quantity(patient.birth_weight_kg, "kg"),
        })
    if patient.gestation_weeks:
        # No code: the program holds the number and not a vocabulary for it,
        # and a wrong code is worse than none.
        weeks = patient.gestation_weeks + (patient.gestation_days or 0) / 7.0
        record.add("Observation", f"gestation-{patient.id}", {
            "status": "final",
            "code": _concept("Gestational age at birth"),
            "subject": child,
            "effectiveDateTime": _day(patient.date_of_birth),
            "valueQuantity": _quantity(round(weeks, 2), "wk"),
        })
    if (patient.blood_type or "").strip():
        record.add("Observation", f"blood-group-{patient.id}", {
            "status": "final",
            "category": [_concept(None, _hl7("observation-category",
                                             "laboratory", "Laboratory"))],
            "code": _loinc(*BLOOD_GROUP),
            "subject": child,
            "valueCodeableConcept": _concept(patient.blood_type.strip()),
        })


# ------------------------------------------------------------ encounters ----
def _visits(record, patient, child):
    from sqlalchemy.orm import selectinload

    from app.models import Visit

    visits = (Visit.query
              .options(selectinload(Visit.diagnoses),
                       selectinload(Visit.vitals),
                       selectinload(Visit.doctor))
              .filter(Visit.patient_id == patient.id)
              .order_by(Visit.visit_date, Visit.id).all())
    for visit in visits:
        virtual = visit.channel == "whatsapp"
        doctor = record.practitioner(visit.doctor)
        encounter = record.ref("Encounter", f"visit-{visit.id}")
        record.add("Encounter", f"visit-{visit.id}", {
            "status": VISIT_STATUS.get(visit.status, "unknown"),
            "class": _hl7("v3-ActCode", "VR" if virtual else "AMB",
                          "virtual" if virtual else "ambulatory"),
            "subject": child,
            "participant": [{"individual": doctor}] if doctor else None,
            "period": {"start": _day(visit.visit_date)},
            "reasonCode": ([_concept(visit.chief_complaint.strip())]
                           if (visit.chief_complaint or "").strip() else None),
        })
        for dx in visit.diagnoses:
            verification = DX_VERIFICATION.get(dx.dx_type)
            record.add("Condition", f"dx-{dx.id}", {
                "verificationStatus": (_concept(None, _hl7(
                    "condition-ver-status", verification))
                    if verification else None),
                "category": [_concept(None, _hl7(
                    "condition-category", "encounter-diagnosis",
                    "Encounter Diagnosis"))],
                "code": _dx_code(dx.code, dx.icd_version, dx.title,
                                 dx.title_en),
                "subject": child,
                "encounter": encounter,
                "recordedDate": _instant(dx.created_at),
                "recorder": doctor,
                "note": [{"text": dx.notes}] if (dx.notes or "").strip()
                else None,
            })
        _vitals(record, visit, child, encounter)


def _stays(record, patient, child):
    from app.models import Admission

    for stay in (Admission.query.filter_by(patient_id=patient.id)
                 .order_by(Admission.admitted_at, Admission.id).all()):
        doctor = record.practitioner(stay.doctor)
        record.add("Encounter", f"stay-{stay.id}", {
            "status": "finished" if stay.discharged_at else "in-progress",
            "class": _hl7("v3-ActCode", "IMP", "inpatient encounter"),
            "subject": child,
            "participant": [{"individual": doctor}] if doctor else None,
            "period": {"start": _instant(stay.admitted_at),
                       "end": _instant(stay.discharged_at)},
            "reasonCode": ([_concept(stay.reason.strip())]
                           if (stay.reason or "").strip() else None),
        })


# ------------------------------------------------------------ observations ----
def _vital_category():
    return _concept(None, _hl7("observation-category", "vital-signs",
                               "Vital Signs"))


def _loinc(code, display):
    return _concept(display, {"system": LOINC, "code": code,
                              "display": display})


def _quantity(value, unit):
    number = _number(value)
    if number is None:
        return None
    return {"value": number, "unit": unit, "system": UCUM, "code": unit}


def _growth(record, patient, child):
    """The growth chart's own readings — the rows the percentiles are drawn
    from, so a receiver plots what this clinic plotted."""
    from app.models import GrowthRecord

    rows = (GrowthRecord.query.filter_by(patient_id=patient.id)
            .order_by(GrowthRecord.record_date, GrowthRecord.id).all())
    for row in rows:
        encounter = (record.ref("Encounter", f"visit-{row.visit_id}")
                     if row.visit_id else None)
        for column, code, display, unit in GROWTH:
            value = _number(getattr(row, column))
            if value is None or value <= 0:
                continue
            record.add("Observation", f"growth-{row.id}-{column}", {
                "status": "final",
                "category": [_vital_category()],
                "code": _loinc(code, display),
                "subject": child,
                "encounter": encounter,
                "effectiveDateTime": _day(row.record_date),
                "valueQuantity": _quantity(value, unit),
            })


def _vitals(record, visit, child, encounter):
    """A visit's vital signs. Weight, length and head are left to the growth
    chart, which is where the clinic keeps them."""
    for vitals in _vital_rows(visit):
        when = _day(visit.visit_date)
        for column, code, display, unit in VITALS:
            value = _number(getattr(vitals, column, None))
            if value is None:
                continue
            record.add("Observation", f"vitals-{vitals.id}-{column}", {
                "status": "final",
                "category": [_vital_category()],
                "code": _loinc(code, display),
                "subject": child,
                "encounter": encounter,
                "effectiveDateTime": when,
                "valueQuantity": _quantity(value, unit),
            })
        high, low = _number(vitals.bp_systolic), _number(vitals.bp_diastolic)
        if high is None and low is None:
            continue
        record.add("Observation", f"vitals-{vitals.id}-bp", {
            "status": "final",
            "category": [_vital_category()],
            "code": _loinc(*BLOOD_PRESSURE),
            "subject": child,
            "encounter": encounter,
            "effectiveDateTime": when,
            "bodySite": (_concept(vitals.bp_arm)
                         if (vitals.bp_arm or "").strip() else None),
            "component": [
                {"code": _loinc(*SYSTOLIC),
                 "valueQuantity": _quantity(high, "mm[Hg]")}
                if high is not None else None,
                {"code": _loinc(*DIASTOLIC),
                 "valueQuantity": _quantity(low, "mm[Hg]")}
                if low is not None else None,
            ],
        })


def _vital_rows(visit):
    rows = visit.vitals
    if rows is None:
        return []
    return rows if isinstance(rows, (list, tuple)) else [rows]


def _results(record, patient, child):
    """Tests with a result. The clinic's own names for them — it holds no
    LOINC for its catalogue, and the unit is written as the lab wrote it."""
    from app.models import VisitInvestigation

    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == patient.id,
                    VisitInvestigation.status == "resulted")
            .order_by(VisitInvestigation.resulted_at, VisitInvestigation.id)
            .all())
    for row in rows:
        kind = "imaging" if row.kind == "imaging" else "laboratory"
        value = _number(row.result_value)
        low, high = _number(row.result_low), _number(row.result_high)
        unit = (row.result_unit or "").strip() or None
        span = {}
        if low is not None:
            span["low"] = {"value": low, "unit": unit}
        if high is not None:
            span["high"] = {"value": high, "unit": unit}
        notes = [n for n in (row.result_comment,
                             _text(row.outside_place) if row.done_outside
                             else None) if (n or "").strip()]
        if row.done_outside and (row.outside_place or "").strip():
            performer = record.place(row.outside_place)
        else:
            performer = (record.practitioner(row.resulter)
                         or record.organization())
        record.add("Observation", f"result-{row.id}", {
            "status": "final",
            "category": [_concept(None, _hl7(
                "observation-category", kind,
                "Imaging" if kind == "imaging" else "Laboratory"))],
            "code": _concept(_text(row.name, row.name_en
                                   if row.name_en != row.name else None)),
            "subject": child,
            "encounter": record.ref("Encounter", f"visit-{row.visit_id}"),
            "effectiveDateTime": _instant(row.collected_at or row.performed_at
                                          or row.resulted_at),
            "issued": _instant(row.resulted_at),
            "performer": [performer] if performer else None,
            "valueQuantity": ({"value": value, "unit": unit}
                              if value is not None else None),
            "valueString": ((row.result_text or "").strip() or None
                            if value is None else None),
            "referenceRange": [span] if span else None,
            "note": [{"text": n} for n in notes],
        })


# ------------------------------------------------------------ vaccines ----
def _immunizations(record, patient, child):
    """Every dose on the card — given, refused, or put off. A refusal is part
    of the record as much as a dose, and a receiver deciding what to give
    next needs both."""
    from sqlalchemy.orm import selectinload

    from app.models import PatientVaccine

    rows = (PatientVaccine.query
            .options(selectinload(PatientVaccine.vaccine),
                     selectinload(PatientVaccine.brand),
                     selectinload(PatientVaccine.doctor))
            .filter(PatientVaccine.patient_id == patient.id)
            .order_by(PatientVaccine.given_date, PatientVaccine.id).all())
    for dose in rows:
        vaccine, brand = dose.vaccine, dose.brand
        given = dose.event_type == "given"
        coding = None
        if vaccine is not None and (vaccine.code or "").strip():
            coding = {"system": record.system("vaccine"),
                      "code": vaccine.code.strip(),
                      "display": vaccine.name_en or vaccine.name_ar}
        name = _text(vaccine.display_name("ar") if vaccine else None,
                     brand.display_name("en") if brand else None)
        reason = None
        if not given:
            reason = _concept(_text(
                "delayed" if dose.event_type == "delayed" else "refused",
                dose.refusal_reason))
        notes = [n for n in (dose.notes, dose.adverse_events)
                 if (n or "").strip()]
        record.add("Immunization", f"dose-{dose.id}", {
            "status": "completed" if given else "not-done",
            "statusReason": reason,
            "vaccineCode": _concept(name, coding),
            "patient": child,
            "occurrenceDateTime": _day(dose.given_date),
            "primarySource": (not dose.given_outside) if given else None,
            "reportOrigin": (_concept(dose.outside_place.strip())
                             if given and dose.given_outside
                             and (dose.outside_place or "").strip() else None),
            "lotNumber": (dose.lot_number or "").strip() or None,
            "performer": ([{"actor": record.practitioner(dose.doctor)}]
                          if given and dose.doctor is not None else None),
            "note": [{"text": n} for n in notes],
            "protocolApplied": ([_dose_number(dose.dose_number)]
                                if given and dose.dose_number else None),
        })


def _dose_number(number):
    if isinstance(number, int) and number >= 1:
        return {"doseNumberPositiveInt": number}
    return {"doseNumberString": str(number)}


# ------------------------------------------------------------ medicines ----
def _dosage(*parts):
    words = " ".join(str(p).strip() for p in parts
                     if p is not None and str(p).strip())
    return [{"text": words}] if words else None


def _prescriptions(record, patient, child):
    """Every line written on a prescription. The status is ``unknown`` and
    means it: the program knows a medicine was prescribed, not whether the
    course was finished."""
    from sqlalchemy.orm import selectinload

    from app.models import Prescription

    rows = (Prescription.query
            .options(selectinload(Prescription.items))
            .filter(Prescription.patient_id == patient.id)
            .order_by(Prescription.rx_date, Prescription.id).all())
    for rx in rows:
        doctor = record.practitioner(getattr(rx, "doctor", None))
        for item in rx.items:
            record.add("MedicationRequest", f"rx-{item.id}", {
                "status": "unknown",
                "intent": "order",
                "category": [_concept(None, _hl7(
                    "medicationrequest-category", "outpatient",
                    "Outpatient"))],
                "medicationCodeableConcept": _concept(item.drug_name),
                "subject": child,
                "encounter": (record.ref("Encounter", f"visit-{rx.visit_id}")
                              if rx.visit_id else None),
                "authoredOn": _day(rx.rx_date) or _instant(rx.created_at),
                "requester": doctor,
                "dosageInstruction": _dosage(item.dose, item.frequency,
                                             item.duration, item.instructions),
            })


def _inpatient_orders(record, patient, child):
    from app.models import MedicationOrder

    rows = (MedicationOrder.query.filter_by(patient_id=patient.id)
            .order_by(MedicationOrder.started_at, MedicationOrder.id).all())
    for order in rows:
        every = (f"every {_number(order.every_hours)} h"
                 if order.every_hours else None)
        dosage = _dosage(order.dose, order.route, every)
        if dosage:
            dosage[0]["asNeededBoolean"] = bool(order.is_prn)
        record.add("MedicationRequest", f"order-{order.id}", {
            "status": "stopped" if order.stopped_at else "active",
            "intent": "order",
            "category": [_concept(None, _hl7(
                "medicationrequest-category", "inpatient", "Inpatient"))],
            "medicationCodeableConcept": _concept(order.drug_name),
            "subject": child,
            "encounter": (record.ref("Encounter", f"stay-{order.admission_id}")
                          if order.admission_id else None),
            "authoredOn": _instant(order.started_at),
            "requester": record.practitioner(getattr(order, "orderer", None)),
            "dosageInstruction": dosage,
            "note": [{"text": order.note}] if (order.note or "").strip()
            else None,
        })


def _long_term_medicines(record, patient, child):
    from app.models import PatientMedication

    rows = (PatientMedication.query.filter_by(patient_id=patient.id)
            .order_by(PatientMedication.id).all())
    for med in rows:
        record.add("MedicationStatement", f"med-{med.id}", {
            "status": "stopped" if med.stopped_on else "active",
            "medicationCodeableConcept": _concept(med.name),
            "subject": child,
            "effectivePeriod": ({"start": _day(med.started_on),
                                 "end": _day(med.stopped_on)}
                                if med.started_on or med.stopped_on
                                else None),
            # When it started is part of the statement; nobody wrote it down.
            "_effectiveDateTime": (None if med.started_on or med.stopped_on
                                   else _absent()),
            "dateAsserted": _instant(med.created_at),
            "reasonCode": [_concept(med.reason)] if (med.reason or "").strip()
            else None,
            "dosage": _dosage(med.dose, med.frequency),
            "note": [{"text": n} for n in (med.notes, med.stop_reason)
                     if (n or "").strip()],
        })


# ------------------------------------------------------------ operations ----
def _operations(record, patient, child):
    """Operations that happened — a booking that was cancelled or is still to
    come is not a procedure."""
    from app.models import Operation

    rows = (Operation.query
            .filter(Operation.patient_id == patient.id,
                    Operation.status.in_(("done", "in_theatre")))
            .order_by(Operation.on_date, Operation.id).all())
    for op in rows:
        performers = []
        for user in (op.surgeon, op.anaesthetist):
            ref = record.practitioner(user)
            if ref:
                performers.append({"actor": ref})
        period = None
        if op.started_at or op.finished_at:
            period = {"start": _instant(op.started_at),
                      "end": _instant(op.finished_at)}
        record.add("Procedure", f"operation-{op.id}", {
            "status": "completed" if op.status == "done" else "in-progress",
            "code": _concept(op.procedure),
            "subject": child,
            "encounter": (record.ref("Encounter", f"stay-{op.admission_id}")
                          if op.admission_id else None),
            "performedPeriod": period,
            "performedDateTime": None if period else _day(op.on_date),
            "performer": performers,
            "note": [{"text": n} for n in (op.findings, op.notes)
                     if (n or "").strip()],
        })
