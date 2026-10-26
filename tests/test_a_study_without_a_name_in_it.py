"""The research export — a study's data with no child named in it.

HOSPITAL_PLAN.md ٥‑د ت-٧: *«تختار مجموعة («تحت سنتين، التهاب شعيبات، ٢٠٢٥»)،
وتطلع Excel أو CSV من غير أسماء: كود بدل الاسم، والسن وقت الحالة بدل تاريخ
الميلاد، ومعاها ملف بيشرح كل عمود.»* Only for an approved protocol in its
validity; consented participants always, every child only when the committee
allowed a record review; every export recorded.
"""
import csv
import io
import json
import os
import sys
import zipfile
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def study(clinic):
    """An approved protocol; two babies with bronchiolitis, one enrolled with
    consent; an older child with something else."""
    from app.models import (Diagnosis, Patient, Prescription, PrescriptionItem,
                            ResearchParticipant, ResearchProtocol, Setting, Visit,
                            VitalSigns)
    from app.utils import consent as cs

    db = clinic["db"]
    today = local_today()
    with clinic["app"].app_context():
        Setting.set("mod_enabled:teaching", "1")
        proto = ResearchProtocol(title="التهاب الشعيبات تحت سنتين", eligibility="—",
                                 investigator_id=clinic["ids"]["doctor"], state="approved",
                                 rec_reference="REC-2026-7", approved_on=today - timedelta(days=30),
                                 valid_until=today + timedelta(days=300))
        db.session.add(proto)
        kids = {}
        for key, name, born, gender in (
                ("enrolled", "مريم المشتركة", today - timedelta(days=300), "female"),
                ("other_baby", "آدم غير المشترك", today - timedelta(days=200), "male"),
                ("older", "يوسف الكبير", today - timedelta(days=2000), "male")):
            kid = Patient(patient_number=f"R-{key}", full_name=name, gender=gender,
                          date_of_birth=born, is_active=True, national_id="29901011234567",
                          own_phone="01001234567")
            db.session.add(kid)
            db.session.flush()
            kids[key] = kid.id
            for days_ago, code, title in ((20, "J21.9", "Bronchiolitis"), (10, "J21.9", "Bronchiolitis")):
                if key == "older":
                    code, title = "A09", "Gastroenteritis"
                visit = Visit(patient_id=kid.id, doctor_id=clinic["ids"]["doctor"],
                              visit_date=today - timedelta(days=days_ago),
                              chief_complaint=f"كحة — الأم {name} قالت", notes="ساكنين في شارع النيل")
                db.session.add(visit)
                db.session.flush()
                db.session.add(Diagnosis(visit_id=visit.id, code=code, title="التهاب", title_en=title))
                db.session.add(VitalSigns(visit_id=visit.id, weight_kg=7.4, temperature_c=38.2, spo2=94))
                rx = Prescription(patient_id=kid.id, visit_id=visit.id)
                db.session.add(rx)
                db.session.flush()
                db.session.add(PrescriptionItem(prescription_id=rx.id, drug_name="Salbutamol"))
        db.session.flush()
        consent = cs.record(db.session.get(Patient, kids["enrolled"]), "research", "الأم")
        db.session.flush()
        db.session.add(ResearchParticipant(protocol_id=proto.id, patient_id=kids["enrolled"],
                                           consent_id=consent.id, enrolled_on=today))
        db.session.commit()
        clinic["proto"], clinic["kids"] = proto.id, kids
    return clinic


def _export(c, who="boss", **form):
    data = {"mode": "participants", **form}
    return c["sign_in"](who).post(f"/teaching/protocol/{c['proto']}/export", data=data)


def _unzip(reply):
    zf = zipfile.ZipFile(io.BytesIO(reply.data))
    data = list(csv.DictReader(io.StringIO(zf.read("data.csv").decode("utf-8-sig"))))
    book = list(csv.DictReader(io.StringIO(zf.read("codebook.csv").decode("utf-8-sig"))))
    about = json.loads(zf.read("about.json"))
    return data, book, about, zf


def test_participants_only_with_codes_ages_and_nothing_that_names_a_child(study):
    reply = _export(study)
    assert reply.status_code == 200 and reply.mimetype == "application/zip"
    data, book, about, zf = _unzip(reply)
    assert len(data) == 2 and about["children"] == 1          # the enrolled baby, two visits
    row = data[0]
    assert row["study_code"].startswith(f"S{study['proto']}-")
    assert row["sex"] == "F" and 9 <= int(row["age_months"]) <= 10
    assert row["dx_codes"] == "J21.9" and row["dx_titles"] == "Bronchiolitis"
    assert row["weight_kg"] == "7.4" and row["spo2"] == "94" and row["medicines"] == "Salbutamol"
    assert [r["day_of_course"] for r in data] == ["0", "10"]
    # Every column explained.
    assert [b["column"] for b in book] == list(data[0].keys())
    # Nothing that identifies the child, anywhere in the zip.
    blob = b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8-sig")
    for leak in ("مريم", "R-enrolled", "29901011234567", "01001234567", "شارع النيل",
                 "الأم", (local_today() - timedelta(days=300)).isoformat(),
                 (local_today() - timedelta(days=10)).isoformat()):
        assert leak not in blob, leak


def test_the_same_child_keeps_the_same_code_and_another_study_gives_another(study):
    from app.utils import research_export as rx

    first = _unzip(_export(study))[0][0]["study_code"]
    second = _unzip(_export(study))[0][0]["study_code"]
    assert first == second
    with study["app"].app_context():
        assert rx.study_code(study["proto"] + 1, study["kids"]["enrolled"]) != first


def test_a_record_review_needs_the_committees_word(study):
    from app.models import ResearchProtocol

    reply = _export(study, mode="records")
    assert reply.status_code == 302                         # refused, back to the page
    with study["app"].app_context():
        study["db"].session.get(ResearchProtocol, study["proto"]).record_review = True
        study["db"].session.commit()
    data, _b, about, _z = _unzip(_export(study, mode="records", dx="J21", age_to="24"))
    assert about["children"] == 2 and len(data) == 4         # both babies, not the older child
    assert {r["dx_codes"] for r in data} == {"J21.9"}


def test_only_an_approved_protocol_in_its_validity(study):
    from app.models import ResearchExport, ResearchProtocol

    with study["app"].app_context():
        row = study["db"].session.get(ResearchProtocol, study["proto"])
        row.valid_until = local_today() - timedelta(days=1)
        study["db"].session.commit()
    assert _export(study).status_code == 302
    with study["app"].app_context():
        row = study["db"].session.get(ResearchProtocol, study["proto"])
        row.valid_until, row.state = None, "suspended"
        study["db"].session.commit()
    assert _export(study).status_code == 302
    page = study["sign_in"]("boss").get(f"/teaching/protocol/{study['proto']}").get_data(as_text=True)
    assert 'data-export-refused="not_approved"' in page and "data-export-form" not in page
    with study["app"].app_context():
        assert ResearchExport.query.count() == 0


def test_every_export_is_recorded_and_only_the_investigator_or_admin_exports(study):
    from app.models import ActivityLog, ResearchExport

    assert _export(study, who="desk").status_code in (403, 302)
    assert _export(study, who="doc").status_code == 200      # the investigator
    with study["app"].app_context():
        rec = ResearchExport.query.one()
        assert (rec.children, rec.rows, rec.mode) == (1, 2, "participants")
        assert ActivityLog.query.filter_by(action="research.export").count() == 1
    page = study["sign_in"]("boss").get(f"/teaching/protocol/{study['proto']}").get_data(as_text=True)
    assert "data-export-log" in page and "data-export-form" in page


def test_a_clinic_without_teaching_has_no_export(clinic):
    from app.models import ResearchProtocol

    with clinic["app"].app_context():
        p = ResearchProtocol(title="x", eligibility="—", investigator_id=clinic["ids"]["doctor"],
                             state="approved", approved_on=date.today())
        clinic["db"].session.add(p)
        clinic["db"].session.commit()
        pid = p.id
    reply = clinic["sign_in"]("boss").post(f"/teaching/protocol/{pid}/export", data={"mode": "participants"})
    assert reply.status_code in (302, 403, 404)
    assert reply.mimetype != "application/zip"
