"""The International Patient Summary — the child's record, short, in the
shape any IPS reader expects.

The full file (:mod:`app.utils.fhir_export`) is everything: every visit,
every reading, every line ever written. The IPS (HL7 FHIR IPS 2.0.0, STU2,
on R4) is the other thing a hospital asks for — *what does a doctor meeting
this child for the first time need to know* — as a FHIR ``document``: one
``Composition`` first, a fixed set of sections, each with a narrative a
person can read and entries a machine can.

**One mapping, two views.** Nothing here reads the database: the resources
are the full file's, built by :func:`fhir_export.build`, and this module
chooses among them and arranges them. A child's allergy cannot read one way
in the full file and another in the summary, because there is only one piece
of code that says what an allergy looks like in FHIR.

**What the summary holds, and why that and not more:**

* *Problems* — the problem list as it stands, and the chronic conditions on
  the card. *Past problems* — what was on the list and is resolved.
* *Allergies* — every phrase on the card.
* *Medications* — what the program knows is current: long-term medicines not
  stopped, ward orders not stopped, and the most recent day's prescription.
  An older prescription is history, and the full file carries it.
* *Immunizations* — every vaccine event, refusals included.
* *Results* — every test with a result, and the blood group.
* *Procedures* — operations that happened.
* *Vital signs* — the latest of each reading.

**Empty is said, not guessed.** IPS requires the first three sections. When
the program holds nothing for one, the section says *unavailable* — the
information is not in this record — which is exactly what an empty field
here means. It never says *nil known*: an allergy field nobody filled in is
not a clinic stating the child has none.

**No code the program does not hold**, as in the full file. Every binding IPS
places on these resources is *preferred*, not *required*: a problem or a
medicine in the clinic's own words is a conformant IPS entry, and a SNOMED
code guessed to satisfy a reader would be the only non-conformant thing in
it.
"""
import copy
import html
import uuid
from datetime import datetime, timezone

from app.utils import fhir_export as fx

IPS = "http://hl7.org/fhir/uv/ips/StructureDefinition/"
VITALS_PROFILE = "http://hl7.org/fhir/StructureDefinition/vitalsigns"
LIST_EMPTY = fx._TERMINOLOGY + "list-empty-reason"

# (key, LOINC, LOINC display, Arabic title, English title)
SECTIONS = (
    ("problems", "11450-4", "Problem list - Reported",
     "المشاكل الصحية", "Problem List"),
    ("allergies", "48765-2", "Allergies and adverse reactions Document",
     "الحساسية", "Allergies and Intolerances"),
    ("medications", "10160-0", "History of Medication use Narrative",
     "الأدوية", "Medication Summary"),
    ("immunizations", "11369-6", "History of Immunization note",
     "التطعيمات", "Immunizations"),
    ("results", "30954-2", "Relevant diagnostic tests/laboratory data note",
     "النتائج", "Results"),
    ("procedures", "47519-4", "History of Procedures Document",
     "العمليات", "History of Procedures"),
    ("past", "11348-0", "History of Past illness note",
     "مشاكل سابقة", "History of Past Problems"),
    ("vitals", "8716-3", "Vital signs note",
     "العلامات الحيوية والقياسات", "Vital Signs"),
)
REQUIRED = ("problems", "allergies", "medications")

PROFILES = {
    "Patient": "Patient-uv-ips", "AllergyIntolerance": "AllergyIntolerance-uv-ips",
    "Condition": "Condition-uv-ips",
    "MedicationStatement": "MedicationStatement-uv-ips",
    "MedicationRequest": "MedicationRequest-uv-ips",
    "Immunization": "Immunization-uv-ips", "Procedure": "Procedure-uv-ips",
    "Organization": "Organization-uv-ips", "Practitioner": "Practitioner-uv-ips",
}


# ------------------------------------------------------------ reading ----
def _category(resource):
    for concept in resource.get("category") or []:
        for coding in concept.get("coding") or []:
            return coding.get("code")
    return None


def _status(concept):
    for coding in (concept or {}).get("coding") or []:
        return coding.get("code")
    return None


def _code(resource):
    for coding in (resource.get("code") or {}).get("coding") or []:
        return coding.get("code")
    return None


def _when(resource):
    return (resource.get("effectiveDateTime") or resource.get("authoredOn")
            or resource.get("occurrenceDateTime")
            or resource.get("performedDateTime")
            or (resource.get("performedPeriod") or {}).get("start")
            or (resource.get("effectivePeriod") or {}).get("start") or "")


def _choose(entries):
    """Which resources go in which section."""
    by_kind = {}
    for entry in entries:
        by_kind.setdefault(entry["resource"]["resourceType"], []).append(entry)

    def kind(name):
        return by_kind.get(name, [])

    chosen = {key: [] for key, *_ in SECTIONS}
    for entry in kind("Condition"):
        res = entry["resource"]
        if _category(res) != "problem-list-item":
            continue        # a visit's diagnosis is the visit's, not a problem
        if _status(res.get("clinicalStatus")) == "resolved":
            chosen["past"].append(entry)
        else:
            chosen["problems"].append(entry)
    chosen["allergies"] = list(kind("AllergyIntolerance"))

    current = [e for e in kind("MedicationStatement")
               if e["resource"].get("status") == "active"]
    current += [e for e in kind("MedicationRequest")
                if _category(e["resource"]) == "inpatient"
                and e["resource"].get("status") == "active"]
    written = [e for e in kind("MedicationRequest")
               if _category(e["resource"]) == "outpatient"]
    if written:
        last_day = max(_when(e["resource"])[:10] for e in written)
        current += [e for e in written
                    if _when(e["resource"])[:10] == last_day]
    chosen["medications"] = current

    chosen["immunizations"] = list(kind("Immunization"))
    chosen["procedures"] = list(kind("Procedure"))

    latest = {}
    for entry in kind("Observation"):
        res = entry["resource"]
        category = _category(res)
        if category in ("laboratory", "imaging"):
            chosen["results"].append(entry)
        elif category == "vital-signs" and _code(res) != fx.BIRTH_WEIGHT[0]:
            code = _code(res)
            held = latest.get(code)
            if held is None or _when(res) >= _when(held["resource"]):
                latest[code] = entry
    chosen["vitals"] = list(latest.values())
    return chosen


# ------------------------------------------------------------ narrative ----
def _div(inner):
    return ('<div xmlns="http://www.w3.org/1999/xhtml" lang="ar" '
            'xml:lang="ar" dir="rtl">' + inner + "</div>")


def _table(headers, rows):
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c or ''))}</td>" for c in row)
        + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _text(concept):
    return (concept or {}).get("text") or next(
        (c.get("display") or c.get("code")
         for c in (concept or {}).get("coding") or []), "")


def _quantity(q):
    if not q:
        return ""
    return f"{q.get('value')} {q.get('unit') or ''}".strip()


def _dosage(res):
    for dosage in res.get("dosageInstruction") or res.get("dosage") or []:
        return dosage.get("text") or ""
    return ""


ROWS = {
    "problems": (("المشكلة", "منذ"), lambda r: (
        _text(r.get("code")), r.get("onsetDateTime"))),
    "past": (("المشكلة", "انتهت"), lambda r: (
        _text(r.get("code")), r.get("abatementDateTime"))),
    "allergies": (("الحساسية",), lambda r: (_text(r.get("code")),)),
    "medications": (("الدوا", "الجرعة", "الحالة", "التاريخ"), lambda r: (
        _text(r.get("medicationCodeableConcept")), _dosage(r),
        r.get("status"), _when(r)[:10])),
    "immunizations": (("التطعيم", "التاريخ", "الحالة"), lambda r: (
        _text(r.get("vaccineCode")), r.get("occurrenceDateTime"),
        r.get("status"))),
    "results": (("الفحص", "النتيجة", "التاريخ"), lambda r: (
        _text(r.get("code")),
        _quantity(r.get("valueQuantity")) or r.get("valueString")
        or _text(r.get("valueCodeableConcept")), _when(r)[:10])),
    "procedures": (("العملية", "التاريخ"), lambda r: (
        _text(r.get("code")), _when(r)[:10])),
    "vitals": (("القياس", "القيمة", "التاريخ"), lambda r: (
        _text(r.get("code")), _quantity(r.get("valueQuantity")) or " / ".join(
            _quantity(c.get("valueQuantity")) for c in r.get("component") or []),
        _when(r)[:10])),
}

EMPTY_TEXT = "مفيش بيانات عن ده في ملف الطفل."


def _section(key, loinc, display, title_ar, title_en, entries):
    section = {
        "title": f"{title_ar} — {title_en}",
        "code": {"coding": [{"system": fx.LOINC, "code": loinc,
                             "display": display}]},
    }
    if entries:
        headers, row = ROWS[key]
        section["text"] = {"status": "generated", "div": _div(
            _table(headers, [row(e["resource"]) for e in entries]))}
        section["entry"] = [{"reference": e["fullUrl"]} for e in entries]
    else:
        # The information is not in this record — which is what an empty
        # field here means. Never "nil known": nobody recorded that.
        section["text"] = {"status": "generated",
                           "div": _div(f"<p>{html.escape(EMPTY_TEXT)}</p>")}
        section["emptyReason"] = {
            "coding": [{"system": LIST_EMPTY, "code": "unavailable",
                        "display": "Unavailable"}],
            "text": "No information available"}
    return section


# ------------------------------------------------------------ fitting ----
def _drop_encounters(node):
    """A summary has no visits in it, so nothing may point at one."""
    if isinstance(node, dict):
        node.pop("encounter", None)
        for value in node.values():
            _drop_encounters(value)
    elif isinstance(node, list):
        for value in node:
            _drop_encounters(value)


def _references(node):
    if isinstance(node, dict):
        if isinstance(node.get("reference"), str):
            yield node["reference"]
        for value in node.values():
            yield from _references(value)
    elif isinstance(node, list):
        for value in node:
            yield from _references(value)


def _claim(resource):
    """Say which IPS profile each resource meets, so a validator holds it to
    that profile rather than only to base FHIR."""
    kind = resource["resourceType"]
    profile = None
    if kind == "Observation":
        category = _category(resource)
        profile = {"laboratory": IPS + "Observation-results-laboratory-"
                                       "pathology-uv-ips",
                   "imaging": IPS + "Observation-results-radiology-uv-ips",
                   "vital-signs": VITALS_PROFILE}.get(category)
    elif kind in PROFILES:
        profile = IPS + PROFILES[kind]
    if profile:
        resource.setdefault("meta", {})["profile"] = [profile]


def _fit_result(resource):
    """A result IPS will take: it has to say when and by whom. Where the
    record does not know, the field says it does not know."""
    if not any(resource.get(k) for k in ("effectiveDateTime",
                                         "effectivePeriod")):
        resource["_effectiveDateTime"] = fx._absent()
    if not resource.get("performer"):
        resource["performer"] = [{**fx._absent(), "display": "غير مسجّل"}]


# ------------------------------------------------------------ the document ----
def ips_for(patient, author=None, lang="ar", now=None):
    """The child's International Patient Summary, as a FHIR ``document``
    Bundle (a ``dict``). ``author`` is the member of staff who asked for it,
    named when the clinic itself has no name to sign it with."""
    record = fx.build(patient, lang)
    stamp = now or datetime.now(timezone.utc)
    clinic = record.organization()
    signer = clinic or record.practitioner(author)
    entries = [copy.deepcopy(e) for e in record.entries]
    for entry in entries:
        _drop_encounters(entry["resource"])
    chosen = _choose(entries)
    for entry in chosen["results"]:
        _fit_result(entry["resource"])

    patient_url = f"urn:uuid:{record.uid('Patient', patient.id)}"
    doc_id = str(uuid.uuid4())
    composition = {
        "resourceType": "Composition",
        "id": doc_id,
        "meta": {"profile": [IPS + "Composition-uv-ips"]},
        "language": lang,
        "identifier": {"system": "urn:ietf:rfc:3986",
                       "value": f"urn:uuid:{doc_id}"},
        "status": "final",
        "type": {"coding": [{"system": fx.LOINC, "code": "60591-5",
                             "display": "Patient summary Document"}]},
        "subject": {"reference": patient_url},
        "date": fx._instant(stamp),
        "author": [signer] if signer else [fx._absent()],
        "title": "ملخص المريض الدولي — International Patient Summary",
        "custodian": clinic,
        "section": [_section(key, loinc, display, ar, en, chosen[key])
                    for key, loinc, display, ar, en in SECTIONS
                    if chosen[key] or key in REQUIRED],
    }
    composition = fx._clean(composition)
    composition["text"] = {"status": "generated", "div": _div(
        f"<p>{html.escape(composition['title'])}</p>")}

    # Only what the summary points at, and what that points at in turn.
    by_url = {e["fullUrl"]: e for e in entries}
    wanted, queue = set(), [patient_url] + list(_references(composition))
    while queue:
        url = queue.pop()
        if url in wanted:
            continue
        wanted.add(url)
        queue.extend(_references(by_url[url]["resource"]))
    kept = [e for e in entries if e["fullUrl"] in wanted]
    kept.sort(key=lambda e: e["fullUrl"] != patient_url)
    for entry in kept:
        _claim(entry["resource"])

    bundle_id = str(uuid.uuid4())
    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {"profile": [IPS + "Bundle-uv-ips"]},
        "language": lang,
        "identifier": {"system": "urn:ietf:rfc:3986",
                       "value": f"urn:uuid:{bundle_id}"},
        "type": "document",
        "timestamp": fx._instant(stamp),
        "entry": [{"fullUrl": f"urn:uuid:{doc_id}", "resource": composition}]
        + kept,
    }
