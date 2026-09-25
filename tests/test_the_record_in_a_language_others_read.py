"""The child's record in a language other systems read — FHIR, stage one.

A button on the child's file that downloads the whole record as a FHIR R4
``Bundle``: visits and stays, diagnoses and the problem list, allergies,
growth and vital signs, results, every vaccine event, prescriptions and ward
orders, long-term medicines and operations. A file handed over, not a port
opened.

What is held here:

* **It is FHIR.** Every resource is read back by an independent model of the
  specification (``fhir.resources``, R4B — the same resources as R4 for
  everything this file uses); every reference inside the file resolves.
* **No code the program does not hold.** ICD in the book it was chosen from,
  LOINC and UCUM for the measurements that *are* those measurements, HL7's
  own vocabularies for FHIR's own fields, and the clinic's own names in a
  system that is visibly the clinic's. A test lists every code system in the
  file and there are no others.
* **The same child is the same child.** Identifiers are stable from one
  export to the next, and differ between clinics.
* **Only the people who read the file take it**, and the audit log says so.
"""
from datetime import date, datetime, time, timedelta

import pytest
from fhir.resources.R4B import get_fhir_model_class

from app.utils.clock import local_today


@pytest.fixture()
def chart(clinic):
    """A child with one of everything the file carries."""
    from app.models import (Admission, Diagnosis, Family, GrowthRecord,
                            MedicationOrder, Operation, Parent,
                            PatientMedication, PatientProblem,
                            PatientVaccine, Prescription, PrescriptionItem,
                            Setting, Theatre, Visit, VisitInvestigation,
                            VitalSigns)

    db = clinic["db"]
    ids = clinic["ids"]
    with clinic["app"].app_context():
        Setting.set("clinic_name_ar", "عيادة النمو")
        Setting.set("clinic_name_en", "Growell Clinic")
        family = Family(family_name="عائلة التجربة")
        db.session.add(family)
        db.session.flush()
        db.session.add_all([
            Parent(family_id=family.id, relation="mother", full_name="الأم",
                   phone="01000000001", email="mum@example.com"),
            Parent(family_id=family.id, relation="father", full_name="الأب",
                   phone="01000000002"),
        ])
        from app.models import Patient
        kid = db.session.get(Patient, ids["child"])
        kid.family_id = family.id
        kid.full_name_en = "Test Child"
        kid.national_id = "32501010100011"
        kid.allergies = "بنسلين، Augmentin"
        kid.chronic_diseases = "ربو شعبي"
        kid.birth_weight_kg = 3.2
        kid.gestation_weeks = 38
        kid.gestation_days = 3
        kid.blood_type = "O+"
        kid.notes = "ملاحظة داخلية للاستقبال"

        db.session.add(PatientProblem(patient_id=kid.id, title="ربو",
                                      title_en="Asthma", icd_code="J45",
                                      icd_version="10", status="active",
                                      onset_date=date(2025, 6, 1)))
        db.session.add(PatientProblem(patient_id=kid.id, title="التهاب أذن",
                                      icd_code="H66", icd_version=None,
                                      status="resolved",
                                      resolved_date=date(2025, 9, 1)))

        visit = db.session.get(Visit, ids["visit"])
        visit.status = "completed"
        visit.chief_complaint = "كحة وسخونية"
        db.session.flush()
        db.session.add_all([
            Diagnosis(visit_id=visit.id, code="J20.9", title="التهاب شعبي",
                      title_en="Acute bronchitis", icd_version="10",
                      dx_type="final"),
            Diagnosis(visit_id=visit.id, code="CA23", title="ربو",
                      icd_version="11", dx_type="working"),
            Diagnosis(visit_id=visit.id, code=None, title="اشتباه حساسية",
                      icd_version="10", dx_type="secondary"),
            VitalSigns(visit_id=visit.id, temperature_c=38.4, pulse_bpm=120,
                       spo2=97, bp_systolic=95, bp_diastolic=60),
            GrowthRecord(patient_id=kid.id, visit_id=visit.id,
                         record_date=local_today(), weight_kg=11.2,
                         height_cm=82.5, head_circ_cm=46.0),
            VisitInvestigation(visit_id=visit.id, patient_id=kid.id,
                               kind="lab", name="هيموجلوبين", status="resulted",
                               result_value=11.4, result_unit="g/dL",
                               result_low=11, result_high=14,
                               resulted_at=datetime.utcnow()),
            VisitInvestigation(visit_id=visit.id, patient_id=kid.id,
                               kind="imaging", name="أشعة صدر",
                               status="resulted", result_text="طبيعية",
                               resulted_at=datetime.utcnow()),
            VisitInvestigation(visit_id=visit.id, patient_id=kid.id,
                               kind="lab", name="مزرعة", status="requested"),
        ])

        for event, outside, reason in (("given", False, None),
                                       ("given", True, None),
                                       ("refused", False, "سخونية")):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=ids["pcv"], brand_id=ids["brand"],
                dose_number=1, given_date=local_today() - timedelta(days=30),
                event_type=event, given_outside=outside,
                outside_place="وحدة صحية" if outside else None,
                lot_number="LOT-9" if event == "given" and not outside else None,
                doctor_id=ids["doctor"], refusal_reason=reason))

        rx = Prescription(patient_id=kid.id, doctor_id=ids["doctor"],
                          visit_id=visit.id, rx_date=local_today())
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id,
                                        drug_name="أموكسيسيللين شراب",
                                        dose="5 مل", frequency="3 مرات",
                                        duration="7 أيام"))
        db.session.add(PatientMedication(patient_id=kid.id, name="فنتولين",
                                         dose="بخّتين", frequency="عند اللزوم",
                                         started_on=date(2025, 6, 1)))

        stay = Admission(patient_id=kid.id, doctor_id=ids["doctor"],
                         reason="التهاب رئوي",
                         admitted_at=datetime.utcnow() - timedelta(days=3),
                         discharged_at=datetime.utcnow() - timedelta(days=1))
        db.session.add(stay)
        room = Theatre(name="غرفة", is_active=True)
        db.session.add(room)
        db.session.flush()
        db.session.add(MedicationOrder(
            admission_id=stay.id, patient_id=kid.id, drug_name="سيفترياكسون",
            dose="500 مجم", route="IV", every_hours=24, is_prn=False,
            started_at=datetime.utcnow() - timedelta(days=3),
            ordered_by=ids["doctor"]))
        db.session.add(MedicationOrder(
            admission_id=stay.id, patient_id=kid.id, drug_name="باراسيتامول",
            dose="150 مجم", route="PO", every_hours=6, is_prn=True,
            started_at=datetime.utcnow() - timedelta(days=3),
            stopped_at=datetime.utcnow() - timedelta(days=1),
            ordered_by=ids["doctor"]))
        for status, what in (("done", "استئصال لوز"), ("cancelled", "طهارة")):
            db.session.add(Operation(patient_id=kid.id, theatre_id=room.id,
                                     admission_id=stay.id, procedure=what,
                                     status=status,
                                     on_date=local_today() - timedelta(days=2),
                                     surgeon_id=ids["doctor"],
                                     start_time=time(9, 0)))
        db.session.commit()
    return clinic


def _bundle(fx, now=None):
    from app.models import Patient
    from app.utils.fhir_export import bundle_for

    with fx["app"].app_context():
        patient = fx["db"].session.get(Patient, fx["ids"]["child"])
        bundle = bundle_for(patient, now=now)
        fx["db"].session.commit()
        return bundle


def _of(bundle, kind):
    return [e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == kind]


# ------------------------------------------------------------ it is FHIR ----
def test_every_resource_reads_back_as_fhir(chart):
    bundle = _bundle(chart)
    get_fhir_model_class("Bundle").parse_obj(bundle)
    for entry in bundle["entry"]:
        resource = entry["resource"]
        get_fhir_model_class(resource["resourceType"]).parse_obj(resource)
    kinds = {e["resource"]["resourceType"] for e in bundle["entry"]}
    assert kinds == {"Patient", "Organization", "Practitioner",
                     "AllergyIntolerance", "Condition", "Encounter",
                     "Observation", "Immunization", "MedicationRequest",
                     "MedicationStatement", "Procedure"}


def test_every_reference_in_the_file_resolves(chart):
    bundle = _bundle(chart)
    present = {e["fullUrl"] for e in bundle["entry"]}
    assert len(present) == len(bundle["entry"])

    def references(node):
        if isinstance(node, dict):
            if set(node) == {"reference"}:
                yield node["reference"]
            for value in node.values():
                yield from references(value)
        elif isinstance(node, list):
            for value in node:
                yield from references(value)

    found = list(references([e["resource"] for e in bundle["entry"]]))
    assert found and set(found) <= present


def test_the_file_speaks_no_vocabulary_the_program_does_not_hold(chart):
    bundle = _bundle(chart)
    systems = set()

    def walk(node):
        if isinstance(node, dict):
            if "system" in node and "code" in node:
                systems.add(node["system"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk([e["resource"] for e in bundle["entry"]])
    outside = {s for s in systems
               if s not in {"http://hl7.org/fhir/sid/icd-10",
                            "http://id.who.int/icd/release/11/mms",
                            "http://loinc.org", "http://unitsofmeasure.org"}
               and not s.startswith("http://terminology.hl7.org/CodeSystem/")
               and not s.startswith("urn:uuid:")}
    assert outside == set()


# ------------------------------------------------------------ the child ----
def test_the_child_their_family_and_what_stays_behind(chart):
    patient = _of(_bundle(chart), "Patient")[0]
    assert patient["gender"] == "male" and patient["birthDate"] == "2025-01-01"
    assert [n["text"] for n in patient["name"]] == ["طفل", "Test Child"]
    kinds = {i["type"]["coding"][0]["code"]: i["value"]
             for i in patient["identifier"]}
    assert kinds == {"MR": "P1", "NI": "32501010100011"}
    relations = {c["name"]["text"]: c["relationship"][0]["coding"][0]["code"]
                 for c in patient["contact"]}
    assert relations == {"الأب": "FTH", "الأم": "MTH"}
    assert all(c["relationship"][1]["coding"][0]["code"] == "N"
               for c in patient["contact"])
    assert patient["managingOrganization"]["reference"].startswith("urn:uuid:")
    # The desk's own note about the family is not part of a clinical record.
    assert "ملاحظة داخلية" not in str(patient)


def test_allergies_go_as_typed_one_each(chart):
    allergies = _of(_bundle(chart), "AllergyIntolerance")
    assert sorted(a["code"]["text"] for a in allergies) == ["Augmentin",
                                                            "بنسلين"]


def test_the_prescription_check_reads_the_same_phrases(chart):
    """The split moved into one function; the allergy check must still see
    what it saw."""
    from app.models import Patient
    from app.utils.allergy import check_drug, recorded_allergies

    with chart["app"].app_context():
        kid = chart["db"].session.get(Patient, chart["ids"]["child"])
        assert recorded_allergies(kid) == ["بنسلين", "augmentin"]
        assert check_drug(kid, name="Amoxicillin")["level"] == "match"


# ------------------------------------------------------------ diagnoses ----
def test_a_diagnosis_carries_the_book_it_was_chosen_from(chart):
    conditions = _of(_bundle(chart), "Condition")
    by_text = {c["code"]["text"]: c for c in conditions}
    icd10 = by_text["التهاب شعبي"]
    assert icd10["code"]["coding"][0] == {
        "system": "http://hl7.org/fhir/sid/icd-10", "code": "J20.9",
        "display": "Acute bronchitis"}
    assert icd10["verificationStatus"]["coding"][0]["code"] == "confirmed"
    icd11 = [c for c in conditions
             if c["code"].get("coding", [{}])[0].get("code") == "CA23"][0]
    assert icd11["code"]["coding"][0]["system"] == \
        "http://id.who.int/icd/release/11/mms"
    assert icd11["verificationStatus"]["coding"][0]["code"] == "provisional"
    words_only = by_text["اشتباه حساسية"]
    assert "coding" not in words_only["code"]
    assert "verificationStatus" not in words_only


def test_a_code_whose_book_nobody_recorded_stays_words(chart):
    conditions = _of(_bundle(chart), "Condition")
    ear = [c for c in conditions if "التهاب أذن" in c["code"]["text"]][0]
    assert "coding" not in ear["code"] and "H66" in ear["code"]["text"]
    assert ear["clinicalStatus"]["coding"][0]["code"] == "resolved"
    assert ear["abatementDateTime"] == "2025-09-01"


# ------------------------------------------------------------ readings ----
def _codes(bundle):
    out = {}
    for obs in _of(bundle, "Observation"):
        coding = obs["code"].get("coding")
        key = coding[0]["code"] if coding else obs["code"]["text"]
        out.setdefault(key, []).append(obs)
    return out


def test_the_measurements_carry_their_own_codes_and_units(chart):
    codes = _codes(_bundle(chart))
    weight = codes["29463-7"][0]["valueQuantity"]
    assert weight == {"value": 11.2, "unit": "kg",
                      "system": "http://unitsofmeasure.org", "code": "kg"}
    assert codes["8302-2"][0]["valueQuantity"]["value"] == 82.5
    assert codes["9843-4"][0]["valueQuantity"]["value"] == 46
    assert codes["8310-5"][0]["valueQuantity"]["code"] == "Cel"
    assert codes["8867-4"][0]["valueQuantity"]["value"] == 120
    bp = codes["85354-9"][0]
    assert {(c["code"]["coding"][0]["code"], c["valueQuantity"]["value"])
            for c in bp["component"]} == {("8480-6", 95), ("8462-4", 60)}
    assert codes["8339-4"][0]["valueQuantity"]["value"] == 3.2
    assert codes["882-1"][0]["valueCodeableConcept"]["text"] == "O+"
    # No vocabulary for gestation: the number goes, with words.
    assert codes["Gestational age at birth"][0]["valueQuantity"]["value"] \
        == round(38 + 3 / 7, 2)


def test_only_a_result_is_exported_as_one(chart):
    results = [o for o in _of(_bundle(chart), "Observation")
               if o.get("category", [{}])[0].get("coding", [{}])[0].get("code")
               in ("laboratory", "imaging") and "coding" not in o["code"]]
    by_name = {o["code"]["text"]: o for o in results}
    assert set(by_name) == {"هيموجلوبين", "أشعة صدر"}
    hb = by_name["هيموجلوبين"]
    assert hb["valueQuantity"] == {"value": 11.4, "unit": "g/dL"}
    assert hb["referenceRange"] == [{"low": {"value": 11, "unit": "g/dL"},
                                     "high": {"value": 14, "unit": "g/dL"}}]
    assert by_name["أشعة صدر"]["valueString"] == "طبيعية"


# ------------------------------------------------------------ vaccines ----
def test_every_vaccine_event_given_elsewhere_and_refused(chart):
    doses = _of(_bundle(chart), "Immunization")
    here = [d for d in doses if d.get("primarySource") is True]
    away = [d for d in doses if d.get("primarySource") is False]
    refused = [d for d in doses if d["status"] == "not-done"]
    assert len(here) == len(away) == len(refused) == 1
    assert here[0]["lotNumber"] == "LOT-9"
    assert here[0]["protocolApplied"] == [{"doseNumberPositiveInt": 1}]
    assert here[0]["vaccineCode"]["coding"][0]["code"] == "PCV"
    assert here[0]["vaccineCode"]["coding"][0]["system"].startswith("urn:uuid:")
    assert away[0]["reportOrigin"]["text"] == "وحدة صحية"
    assert "سخونية" in refused[0]["statusReason"]["text"]
    assert "performer" not in refused[0]


# ------------------------------------------------------------ medicines ----
def test_prescriptions_orders_and_long_term_medicines(chart):
    bundle = _bundle(chart)
    requests = _of(bundle, "MedicationRequest")
    outpatient = [r for r in requests
                  if r["category"][0]["coding"][0]["code"] == "outpatient"]
    ward = [r for r in requests
            if r["category"][0]["coding"][0]["code"] == "inpatient"]
    assert outpatient[0]["status"] == "unknown"
    assert outpatient[0]["dosageInstruction"][0]["text"] == \
        "5 مل 3 مرات 7 أيام"
    by_drug = {r["medicationCodeableConcept"]["text"]: r for r in ward}
    assert by_drug["سيفترياكسون"]["status"] == "active"
    assert by_drug["سيفترياكسون"]["dosageInstruction"][0]["asNeededBoolean"] \
        is False
    assert by_drug["باراسيتامول"]["status"] == "stopped"
    assert by_drug["باراسيتامول"]["dosageInstruction"][0]["asNeededBoolean"] \
        is True
    stay = [e for e in _of(bundle, "Encounter")
            if e["class"]["code"] == "IMP"][0]
    assert ward[0]["encounter"]["reference"] == f"urn:uuid:{stay['id']}"
    statement = _of(bundle, "MedicationStatement")[0]
    assert statement["status"] == "active"
    assert statement["medicationCodeableConcept"]["text"] == "فنتولين"


def test_only_an_operation_that_happened_is_a_procedure(chart):
    procedures = _of(_bundle(chart), "Procedure")
    assert [p["code"]["text"] for p in procedures] == ["استئصال لوز"]
    assert procedures[0]["status"] == "completed"


# ------------------------------------------------------------ identity ----
def test_the_same_child_is_the_same_child_next_time(chart):
    from app.models import Setting

    first = _bundle(chart)
    second = _bundle(chart, now=datetime.utcnow() + timedelta(days=1))
    assert [e["fullUrl"] for e in first["entry"]] == \
        [e["fullUrl"] for e in second["entry"]]
    assert first["id"] != second["id"]
    with chart["app"].app_context():
        assert Setting.query.filter_by(key="fhir_namespace").count() == 1


def test_another_clinic_names_its_children_differently(chart):
    from app.models import Setting

    first = _bundle(chart)
    with chart["app"].app_context():
        Setting.set("fhir_namespace", "not a uuid")
        chart["db"].session.commit()
    second = _bundle(chart)
    assert not ({e["fullUrl"] for e in first["entry"]}
                & {e["fullUrl"] for e in second["entry"]})


# ------------------------------------------------------------ the button ----
def test_the_doctor_takes_the_file_and_the_log_says_so(chart):
    from app.models import ActivityLog

    reply = chart["sign_in"]("doc").get(
        f"/patients/{chart['ids']['child']}/fhir")
    assert reply.status_code == 200
    assert reply.mimetype == "application/fhir+json"
    assert 'filename="P1-fhir.json"' in reply.headers["Content-Disposition"]
    assert reply.headers["Cache-Control"] == "no-store"
    body = reply.get_data(as_text=True)
    assert "طفل" in body                    # Arabic as itself, not \\u escapes
    get_fhir_model_class("Bundle").parse_raw(body)
    with chart["app"].app_context():
        row = ActivityLog.query.filter_by(action="patient.fhir_export").one()
        assert row.entity_id == chart["ids"]["child"]
        assert row.user_id == chart["ids"]["doctor"]


def test_the_desk_cannot_take_it(chart):
    from app.models import ActivityLog

    reply = chart["sign_in"]("desk").get(
        f"/patients/{chart['ids']['child']}/fhir")
    assert reply.status_code in (302, 403)
    with chart["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="patient.fhir_export").count() == 0


def test_the_button_is_on_the_file_for_those_who_may(chart):
    child = chart["ids"]["child"]
    page = chart["sign_in"]("doc").get(f"/patients/{child}").get_data(
        as_text=True)
    assert "data-fhir-export" in page
    page = chart["sign_in"]("desk").get(f"/patients/{child}").get_data(
        as_text=True)
    assert "data-fhir-export" not in page
