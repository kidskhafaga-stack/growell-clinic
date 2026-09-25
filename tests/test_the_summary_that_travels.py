"""The summary that travels — the International Patient Summary (IPS 2.0.0).

The full FHIR file is everything; the IPS is what a hospital meeting the
child for the first time reads. Its rules are HL7's, read off the published
package (``hl7.fhir.uv.ips`` 2.0.0, STU2, on R4) and held here one by one:

* a ``document`` Bundle with an identifier and a timestamp, the Composition
  first and no other, typed LOINC 60591-5;
* problems, allergies and medicines always present — with entries, or with
  the reason there are none, and a narrative a person can read either way;
* every section's entries in the bundle and of the kind the section takes;
* a result says when and by whom, a medicine says since when — and where
  the record does not know, the field says so instead of guessing.

The file was also run through HL7's own validator against the IPS package
(``tools/fhir_validate``); the result is in ``docs/FHIR_EXPORT.md``.

And the program's own rules on top: the summary is chosen from the same
resources as the full file, never re-derived; an empty field is
*unavailable*, never *nil known*; and nothing points at a visit, because a
summary has no visits in it.
"""
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import pytest
from fhir.resources.R4B import get_fhir_model_class

from app.utils.clock import local_today
from tests.test_the_record_in_a_language_others_read import chart  # noqa: F401

LOINC = "http://loinc.org"
IPS = "http://hl7.org/fhir/uv/ips/StructureDefinition/"
SECTION_CODES = {"11450-4": "problems", "48765-2": "allergies",
                 "10160-0": "medications", "11369-6": "immunizations",
                 "30954-2": "results", "47519-4": "procedures",
                 "11348-0": "past", "8716-3": "vitals"}
TAKES = {"problems": {"Condition"}, "past": {"Condition"},
         "allergies": {"AllergyIntolerance"},
         "medications": {"MedicationStatement", "MedicationRequest"},
         "immunizations": {"Immunization"}, "results": {"Observation"},
         "procedures": {"Procedure"}, "vitals": {"Observation"}}


@pytest.fixture()
def summary(chart):
    """The chart, plus what only the summary has to choose between: an older
    prescription, an older reading, a test done outside."""
    from app.models import (GrowthRecord, PatientMedication, Prescription,
                            PrescriptionItem, Visit, VisitInvestigation)

    db = chart["db"]
    ids = chart["ids"]
    with chart["app"].app_context():
        kid_id = ids["child"]
        old = Visit(patient_id=kid_id, doctor_id=ids["doctor"],
                    visit_date=local_today() - timedelta(days=60),
                    status="completed")
        db.session.add(old)
        db.session.flush()
        rx = Prescription(patient_id=kid_id, doctor_id=ids["doctor"],
                          visit_id=old.id,
                          rx_date=local_today() - timedelta(days=60))
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="دوا قديم", dose="1"))
        db.session.add(GrowthRecord(patient_id=kid_id, visit_id=old.id,
                                    record_date=local_today()
                                    - timedelta(days=60), weight_kg=9.9))
        db.session.add(VisitInvestigation(
            visit_id=old.id, patient_id=kid_id, kind="lab", name="فيتامين د",
            status="resulted", result_value=18, result_unit="ng/mL",
            done_outside=True, outside_place="معمل برّه",
            resulted_at=datetime.utcnow() - timedelta(days=59)))
        db.session.add(PatientMedication(
            patient_id=kid_id, name="دوا اتوقف", dose="1",
            started_on=date(2025, 1, 1), stopped_on=date(2025, 3, 1)))
        db.session.commit()
    return chart


def _ips(fx, patient_id=None):
    from app.models import Patient, User
    from app.utils.fhir_ips import ips_for

    with fx["app"].app_context():
        db = fx["db"]
        patient = db.session.get(Patient, patient_id or fx["ids"]["child"])
        doc = ips_for(patient, author=db.session.get(User, fx["ids"]["doctor"]))
        db.session.commit()
        return doc


def _sections(doc):
    composition = doc["entry"][0]["resource"]
    return {SECTION_CODES[s["code"]["coding"][0]["code"]]: s
            for s in composition["section"]}


def _entries(doc, section):
    by_url = {e["fullUrl"]: e["resource"] for e in doc["entry"]}
    return [by_url[ref["reference"]]
            for ref in _sections(doc)[section].get("entry", [])]


def _bare_child(fx):
    from app.models import Patient

    with fx["app"].app_context():
        bare = Patient(patient_number="E1", full_name="طفل من غير ملف",
                       gender="female", date_of_birth=date(2024, 5, 1),
                       is_active=True)
        fx["db"].session.add(bare)
        fx["db"].session.commit()
        return bare.id


# ------------------------------------------------------------ the shape ----
def test_it_is_an_ips_document(summary):
    doc = _ips(summary)
    get_fhir_model_class("Bundle").parse_obj(doc)
    for entry in doc["entry"]:
        get_fhir_model_class(entry["resource"]["resourceType"]).parse_obj(
            entry["resource"])
    assert doc["type"] == "document"
    assert doc["identifier"]["value"].startswith("urn:uuid:")
    assert doc["timestamp"]
    assert doc["meta"]["profile"] == [IPS + "Bundle-uv-ips"]
    kinds = [e["resource"]["resourceType"] for e in doc["entry"]]
    assert kinds[0] == "Composition" and kinds.count("Composition") == 1
    assert kinds[1] == "Patient" and kinds.count("Patient") == 1
    composition = doc["entry"][0]["resource"]
    assert composition["type"]["coding"][0]["code"] == "60591-5"
    assert composition["status"] == "final"
    assert composition["subject"]["reference"] == doc["entry"][1]["fullUrl"]
    assert composition["author"] and composition["title"]


def test_the_clinic_signs_it_and_keeps_it(summary):
    doc = _ips(summary)
    composition = doc["entry"][0]["resource"]
    by_url = {e["fullUrl"]: e["resource"] for e in doc["entry"]}
    signer = by_url[composition["author"][0]["reference"]]
    assert signer["resourceType"] == "Organization"
    assert signer["name"] == "عيادة النمو"
    assert composition["custodian"] == composition["author"][0]


def test_a_clinic_with_no_name_is_signed_by_the_doctor(summary):
    from app.models import Setting

    with summary["app"].app_context():
        for key in ("clinic_name_ar", "clinic_name", "clinic_name_en"):
            Setting.set(key, "")
        summary["db"].session.commit()
    doc = _ips(summary)
    composition = doc["entry"][0]["resource"]
    by_url = {e["fullUrl"]: e["resource"] for e in doc["entry"]}
    signer = by_url[composition["author"][0]["reference"]]
    assert signer["resourceType"] == "Practitioner"
    assert "custodian" not in composition


def test_every_resource_claims_its_ips_profile(summary):
    doc = _ips(summary)
    for entry in doc["entry"][1:]:
        res = entry["resource"]
        profile = res["meta"]["profile"][0]
        if res["resourceType"] == "Observation":
            assert profile in (
                IPS + "Observation-results-laboratory-pathology-uv-ips",
                IPS + "Observation-results-radiology-uv-ips",
                "http://hl7.org/fhir/StructureDefinition/vitalsigns")
        else:
            assert profile == IPS + f"{res['resourceType']}-uv-ips"


def test_the_required_sections_are_always_there(summary):
    for doc in (_ips(summary), _ips(summary, _bare_child(summary))):
        sections = _sections(doc)
        for key in ("problems", "allergies", "medications"):
            assert key in sections
            assert sections[key].get("entry") or sections[key].get(
                "emptyReason")


def test_empty_is_unavailable_never_nil_known(summary):
    doc = _ips(summary, _bare_child(summary))
    sections = _sections(doc)
    assert set(sections) == {"problems", "allergies", "medications"}
    for section in sections.values():
        assert "entry" not in section
        assert section["emptyReason"]["coding"][0]["code"] == "unavailable"


def test_every_section_speaks_to_a_person(summary):
    for doc in (_ips(summary), _ips(summary, _bare_child(summary))):
        for section in _sections(doc).values():
            div = section["text"]["div"]
            ET.fromstring(div)                 # well-formed XHTML
            assert 'xmlns="http://www.w3.org/1999/xhtml"' in div
            assert 'xml:lang="ar"' in div


def test_the_narrative_is_escaped(summary):
    from app.models import Patient

    with summary["app"].app_context():
        kid = summary["db"].session.get(Patient, summary["ids"]["child"])
        kid.allergies = "<b>بيض</b> & لبن"
        summary["db"].session.commit()
    div = _sections(_ips(summary))["allergies"]["text"]["div"]
    ET.fromstring(div)
    assert "<b>" not in div and "&lt;b&gt;" in div


def test_every_section_entry_is_in_the_file_and_the_right_kind(summary):
    doc = _ips(summary)
    present = {e["fullUrl"] for e in doc["entry"]}
    for key, section in _sections(doc).items():
        for ref in section.get("entry", []):
            assert ref["reference"] in present
        assert {r["resourceType"] for r in _entries(doc, key)} <= TAKES[key]


def test_nothing_in_the_summary_points_at_a_visit(summary):
    doc = _ips(summary)
    assert "Encounter" not in {e["resource"]["resourceType"]
                               for e in doc["entry"]}
    assert '"encounter"' not in str(doc).replace("'", '"')
    present = {e["fullUrl"] for e in doc["entry"]}

    def refs(node):
        if isinstance(node, dict):
            if isinstance(node.get("reference"), str):
                yield node["reference"]
            for v in node.values():
                yield from refs(v)
        elif isinstance(node, list):
            for v in node:
                yield from refs(v)

    assert set(refs(doc)) <= present


# ------------------------------------------------------------ the choice ----
def test_problems_now_and_problems_past(summary):
    doc = _ips(summary)
    now = [c["code"]["text"] for c in _entries(doc, "problems")]
    past = [c["code"]["text"] for c in _entries(doc, "past")]
    assert sorted(now) == ["ربو", "ربو شعبي"]
    assert len(past) == 1 and "التهاب أذن" in past[0]
    # A visit's diagnosis is that visit's, not a standing problem.
    assert "التهاب شعبي" not in str(doc)


def test_medicines_are_what_is_current(summary):
    doc = _ips(summary)
    names = sorted(m["medicationCodeableConcept"]["text"]
                   for m in _entries(doc, "medications"))
    # The long-term medicine, the ward order still running, the latest
    # prescription — not the one from two months ago, not the stopped order.
    assert names == ["أموكسيسيللين شراب", "سيفترياكسون", "فنتولين"]


def test_every_result_says_when_and_by_whom(summary):
    results = _entries(_ips(summary), "results")
    by_name = {(r["code"].get("text") or r["code"]["coding"][0]["display"]): r
               for r in results}
    assert set(by_name) >= {"هيموجلوبين", "أشعة صدر", "فيتامين د",
                            "ABO and Rh group [Type] in Blood"}
    for res in results:
        assert res.get("performer")
        assert res.get("effectiveDateTime") or res.get("_effectiveDateTime")
    doc = _ips(summary)
    orgs = {e["fullUrl"]: e["resource"] for e in doc["entry"]
            if e["resource"]["resourceType"] == "Organization"}
    outside = by_name["فيتامين د"]["performer"][0]["reference"]
    assert orgs[outside]["name"] == "معمل برّه"
    # The blood group was never dated or signed, and says so.
    blood = by_name["ABO and Rh group [Type] in Blood"]
    assert blood["_effectiveDateTime"]["extension"][0]["valueCode"] == "unknown"
    assert blood["performer"][0]["extension"][0]["valueCode"] == "unknown"


def test_the_latest_of_each_reading(summary):
    vitals = _entries(_ips(summary), "vitals")
    codes = [v["code"]["coding"][0]["code"] for v in vitals]
    assert len(codes) == len(set(codes))
    weight = [v for v in vitals if v["code"]["coding"][0]["code"] == "29463-7"]
    assert weight[0]["valueQuantity"]["value"] == 11.2        # not the 9.9
    assert "8339-4" not in codes                              # birth weight


def test_immunizations_and_procedures(summary):
    doc = _ips(summary)
    assert sorted(i["status"] for i in _entries(doc, "immunizations")) == \
        ["completed", "completed", "not-done"]
    assert [p["code"]["text"] for p in _entries(doc, "procedures")] == \
        ["استئصال لوز"]


def test_a_medicine_nobody_dated_says_it_is_not_known(summary):
    doc = _ips(summary)
    statement = [m for m in _entries(doc, "medications")
                 if m["resourceType"] == "MedicationStatement"][0]
    assert statement.get("effectivePeriod") or \
        statement["_effectiveDateTime"]["extension"][0]["valueCode"]
    from app.models import PatientMedication

    with summary["app"].app_context():
        med = PatientMedication.query.first()
        med.started_on = None
        summary["db"].session.commit()
    statement = [m for m in _entries(_ips(summary), "medications")
                 if m["resourceType"] == "MedicationStatement"][0]
    assert "effectivePeriod" not in statement
    assert statement["_effectiveDateTime"]["extension"][0]["valueCode"] == \
        "unknown"


def test_the_summary_is_made_of_the_full_files_resources(summary):
    """One mapping, two views: an allergy reads the same in both."""
    from app.models import Patient
    from app.utils.fhir_export import bundle_for

    doc = _ips(summary)
    with summary["app"].app_context():
        full = bundle_for(summary["db"].session.get(Patient,
                                                    summary["ids"]["child"]))
    full_by_url = {e["fullUrl"]: e["resource"] for e in full["entry"]}
    for entry in doc["entry"][1:]:
        res = dict(entry["resource"])
        res.pop("meta", None)
        original = dict(full_by_url[entry["fullUrl"]])
        original.pop("encounter", None)
        for key in ("_effectiveDateTime", "performer"):
            if key not in original:
                res.pop(key, None)
        assert res == original, entry["resource"]["resourceType"]


# ------------------------------------------------------------ the button ----
def test_the_summary_downloads_from_the_same_door(summary):
    from app.models import ActivityLog

    child = summary["ids"]["child"]
    reply = summary["sign_in"]("doc").get(f"/patients/{child}/fhir?format=ips")
    assert reply.status_code == 200
    assert 'filename="P1-ips.json"' in reply.headers["Content-Disposition"]
    assert reply.headers["Cache-Control"] == "no-store"
    assert '"type": "document"' in reply.get_data(as_text=True)
    with summary["app"].app_context():
        row = ActivityLog.query.filter_by(action="patient.fhir_export").one()
        assert row.detail.startswith("ips:")
    assert summary["sign_in"]("desk").get(
        f"/patients/{child}/fhir?format=ips").status_code in (302, 403)


def test_both_buttons_on_the_file(summary):
    page = summary["sign_in"]("doc").get(
        f"/patients/{summary['ids']['child']}").get_data(as_text=True)
    assert "data-fhir-export" in page and "data-ips-export" in page
    assert "format=ips" in page
