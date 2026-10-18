"""الشهادات بضغطة من الكشف (DOCTOR_EASE_PLAN.md ب-٣).

* إجازة مرضية، لياقة طبية، تقرير مختصر — من الكشف، بنص العيادة واللي الكشف
  بيعرفه (الاسم والسن والتاريخ)، والدكتور بيكتب اللي الكشف ما يعرفوش بس؛
* التشخيص ما بيظهرش ولا بيتحفظ غير لو الأهل وافقوا؛
* كل شهادة ليها رقم وبتتسجل في ملف المريض (مين وإمتى)، وبتتلغي بسبب — ما
  بتتمسحش؛ والنص اللي اتطبع هو اللي بيفضل حتى لو العيادة غيرت نصها؛
* الطبيب بس اللي بيطلّعها؛ ونص كل نوع بتكتبه العيادة.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _with_dx(clinic):
    from app.models import Diagnosis

    with clinic["app"].app_context():
        clinic["db"].session.add(Diagnosis(visit_id=clinic["ids"]["visit"], code="J03.9",
                                           title="التهاب لوزتين", title_en="Tonsillitis",
                                           dx_type="final"))
        clinic["db"].session.commit()


def _issue(client, clinic, **form):
    return client.post(f"/visits/{clinic['ids']['visit']}/certificate", data=form)


def test_a_sick_leave_is_numbered_kept_and_keeps_the_diagnosis_private(clinic):
    from app.models import MedicalCertificate, Visit

    _with_dx(clinic)
    doc = clinic["sign_in"]("doc")
    page = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-to-cert" in page
    r = _issue(doc, clinic, kind="sick_leave", lang="ar", days="3",
               date_from="2026-10-10", addressed_to="مدرسة النور")
    assert r.status_code == 302
    with clinic["app"].app_context():
        cert = MedicalCertificate.query.one()
        visit = clinic["db"].session.get(Visit, clinic["ids"]["visit"])
        assert (cert.days, cert.date_from, cert.date_to) == (3, date(2026, 10, 10), date(2026, 10, 12))
        assert cert.number.endswith("-00001") and cert.diagnosis is None
        assert visit.patient.display_name("ar") in cert.body and "2026-10-12" in cert.body
        assert "التهاب لوزتين" not in cert.body and "مدرسة النور" in cert.body
        cid = cert.id
    page = doc.get(f"/visits/certificates/{cid}").get_data(as_text=True)
    assert "data-cert-print" in page and "التهاب لوزتين" not in page
    # Days are the doctor's to write; none, or a slip, is refused.
    assert _issue(doc, clinic, kind="sick_leave", lang="ar").status_code == 302
    _issue(doc, clinic, kind="sick_leave", lang="ar", days="3000")
    with clinic["app"].app_context():
        assert MedicalCertificate.query.count() == 1


def test_the_diagnosis_only_when_the_family_agreed_and_in_the_certificate_s_language(clinic):
    from app.models import MedicalCertificate

    _with_dx(clinic)
    doc = clinic["sign_in"]("doc")
    _issue(doc, clinic, kind="visit_report", lang="en", show_diagnosis="1")
    _issue(doc, clinic, kind="fitness", lang="ar", purpose="")            # no purpose: refused
    _issue(doc, clinic, kind="fitness", lang="ar", purpose="الالتحاق بالحضانة")
    with clinic["app"].app_context():
        report, fit = MedicalCertificate.query.order_by(MedicalCertificate.id).all()
        assert report.diagnosis == "Tonsillitis" and report.lang == "en"
        assert report.body.startswith(report.patient.display_name("en") or "")
        assert fit.kind == "fitness" and "الالتحاق بالحضانة" in fit.body
        assert fit.number.endswith("-00002")
        rid = report.id
    page = doc.get(f"/visits/certificates/{rid}").get_data(as_text=True)
    assert "Tonsillitis" in page and 'lang="en"' in page


def test_only_a_doctor_issues_and_a_certificate_is_cancelled_not_deleted(clinic):
    from app.models import MedicalCertificate

    desk = clinic["sign_in"]("desk")
    r = _issue(desk, clinic, kind="visit_report", lang="ar")
    with clinic["app"].app_context():
        assert MedicalCertificate.query.count() == 0
    doc = clinic["sign_in"]("doc")
    _issue(doc, clinic, kind="visit_report", lang="ar")
    with clinic["app"].app_context():
        cid = MedicalCertificate.query.one().id
    assert doc.post(f"/visits/certificates/{cid}/void", data={"reason": ""}).status_code == 302
    with clinic["app"].app_context():
        assert clinic["db"].session.get(MedicalCertificate, cid).voided_at is None
    doc.post(f"/visits/certificates/{cid}/void", data={"reason": "اتكتبت على الطفل الغلط"})
    with clinic["app"].app_context():
        row = clinic["db"].session.get(MedicalCertificate, cid)
        assert row.voided_at is not None and row.void_reason == "اتكتبت على الطفل الغلط"
    page = doc.get(f"/visits/certificates/{cid}").get_data(as_text=True)
    assert "data-cert-voided" in page and "data-cert-print" not in page
    # And the patient's file lists it, with its number.
    boss = clinic["sign_in"]("boss")
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-patient-certs" in page and f'data-cert-row="{cid}"' in page


def test_the_clinic_writes_the_wording_and_an_issued_one_keeps_its_own(clinic):
    from app.models import MedicalCertificate

    doc = clinic["sign_in"]("doc")
    _issue(doc, clinic, kind="visit_report", lang="ar")
    boss = clinic["sign_in"]("boss")
    assert doc.get("/visits/certificates/texts").status_code == 403
    assert "data-to-cert-texts" in boss.get("/settings/").get_data(as_text=True)
    boss.post("/visits/certificates/texts",
              data={"text_visit_report_ar": "تقرير العيادة عن {name} — {complaint}"})
    _issue(doc, clinic, kind="visit_report", lang="ar")
    with clinic["app"].app_context():
        old, new = MedicalCertificate.query.order_by(MedicalCertificate.id).all()
        assert old.body.startswith("تم الكشف") and new.body.startswith("تقرير العيادة عن ")
    # An emptied box goes back to the program's own wording.
    boss.post("/visits/certificates/texts", data={"text_visit_report_ar": ""})
    page = boss.get("/visits/certificates/texts").get_data(as_text=True)
    assert "تم الكشف بالعيادة بتاريخ {date}" in page
