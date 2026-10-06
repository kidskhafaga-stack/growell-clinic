"""بلاغ الحوادث — GAHAR `QPI.10` و`QPI.11` و`DAS.23`/`GSR.13`.

* **أي موظف يبلّغ**، بالاسم أو من غير اسم — ومن غير اسم البرنامج ما بيعرفش
  مين؛
* «حدث جسيم» بيتبلّغ للإدارة على طول (الجرس لمراجع الجودة)؛
* المراجعة لصاحب صلاحية «الجودة وسلامة المرضى» بس؛
* القفل بالتحقيق والإجراء — وحدث بأذى لمريض بإبلاغ الأهل — والحدث الجسيم
  بتحليل السبب الجذري والإبلاغ الخارجي؛
* أخطاء الأدوية وحوادث الأجهزة بتظهر جنب البلاغات من شاشاتها.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_now  # noqa: E402


def _report(c, who="desk", **extra):
    form = {"occurred_at": local_now().strftime("%Y-%m-%dT%H:%M"), "category": "fall",
            "affected": "patient", "area": "الاستقبال", "patient_number": "P1",
            "what_happened": "الطفل وقع من على كرسي الانتظار", **extra}
    return c["sign_in"](who).post("/incidents/report", data=form)


def _one(c):
    from app.models import Incident

    with c["app"].app_context():
        return Incident.query.order_by(Incident.id.desc()).first()


def test_anybody_reports_and_may_leave_their_name_off(clinic):
    page = clinic["sign_in"]("desk").get("/dashboard").get_data(as_text=True)
    assert "data-nav-incident-report" in page and "data-nav-incidents" not in page
    got = _report(clinic).get_data(as_text=True)
    assert "data-incident-thanks" in got
    row = _one(clinic)
    assert row.reported_by == clinic["ids"]["desk"] and row.patient_id == clinic["ids"]["child"]
    _report(clinic, anonymous="1", category="injury", affected="staff", patient_number="")
    row = _one(clinic)
    assert row.reported_by is None and row.number.startswith("INC-")


def test_a_report_without_what_happened_or_a_place_is_refused(clinic):
    from app.models import Incident

    _report(clinic, what_happened="")
    _report(clinic, area="")
    _report(clinic, patient_number="NOPE")
    with clinic["app"].app_context():
        assert Incident.query.count() == 0


def test_only_the_quality_reviewer_sees_the_board(clinic):
    _report(clinic)
    assert clinic["sign_in"]("doc").get("/incidents/").status_code == 403
    assert clinic["sign_in"]("doc").post(f"/incidents/{_one(clinic).id}/review",
                                         data={"classification": "near_miss"}).status_code == 403
    page = clinic["sign_in"]().get("/incidents/").get_data(as_text=True)
    assert f'data-incident="{_one(clinic).id}"' in page and "data-incident-analysis" in page


def test_a_serious_report_rings_the_bell_for_the_reviewer(clinic):
    from app.utils.incidents import open_counts

    _report(clinic, serious="1")
    with clinic["app"].app_context():
        c = open_counts()
        assert c["serious"] == 1 and c["new"] == 1
    page = clinic["sign_in"]().get("/incidents/").get_data(as_text=True)
    assert "data-serious-row" in page


def test_closing_needs_the_whole_record(clinic):
    _report(clinic)
    iid = _one(clinic).id
    boss = clinic["sign_in"]()
    boss.post(f"/incidents/{iid}/review", data={"classification": "adverse_harm",
                                                "findings": "الكرسي مكسور", "action": "اتغيّرت الكراسي",
                                                "close": "1"})
    row = _one(clinic)
    assert row.status == "investigating", "harm to a patient: the family not told"
    assert row.findings == "الكرسي مكسور", "what the reviewer wrote is kept"
    boss.post(f"/incidents/{iid}/review", data={"classification": "adverse_harm",
                                                "findings": "الكرسي مكسور", "action": "اتغيّرت الكراسي",
                                                "family_told": "الأم اتبلّغت في ساعتها والطفل اتكشف عليه",
                                                "close": "1"})
    row = _one(clinic)
    assert row.status == "closed" and row.reviewed_by == clinic["ids"]["admin"]


def test_a_sentinel_event_needs_the_root_cause_and_the_external_report(clinic):
    _report(clinic, serious="1")
    iid = _one(clinic).id
    boss = clinic["sign_in"]()
    base = {"classification": "sentinel", "findings": "x", "action": "y", "family_told": "z",
            "close": "1"}
    boss.post(f"/incidents/{iid}/review", data=base)
    assert _one(clinic).status != "closed"
    boss.post(f"/incidents/{iid}/review", data={**base, "root_cause": "ما فيش حزام في الكرسي"})
    assert _one(clinic).status != "closed"
    boss.post(f"/incidents/{iid}/review", data={**base, "root_cause": "ما فيش حزام في الكرسي",
                                                "external_report": "مديرية الصحة — نفس اليوم"})
    assert _one(clinic).status == "closed"


def test_medication_errors_appear_beside_the_reports(clinic):
    from datetime import datetime

    from app.models import MedicationError

    with clinic["app"].app_context():
        clinic["db"].session.add(MedicationError(stage="administration", outcome="C",
                                                 what_happened="جرعة اتأخرت ساعة",
                                                 happened_at=datetime.utcnow()))
        clinic["db"].session.commit()
    page = clinic["sign_in"]().get("/incidents/").get_data(as_text=True)
    assert "data-med-error=" in page and "جرعة اتأخرت ساعة" in page
