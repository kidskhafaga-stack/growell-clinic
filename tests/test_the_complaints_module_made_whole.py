"""الشكاوى والاقتراحات — المديول الكامل (COMPLAINTS_PLAN.md ش-١ … ش-٥).

The owner, on the register screen: *«فين البحث عن اسم الحالة ورقم الملف …
لازم بحث، وهل التواصل بنفس أرقام التليفون ولا برقم تاني وإيه السبب لأننا
عندنا البيانات، وفي الاقتراحات ممكن نضيف حد، وداش بورد كام مشكل خلال فترة
ورضا العملاء مع الربط»*.

* the child is searched for by name, file number or phone, by anybody who
  registers a case; the file's numbers are offered, and another number keeps
  its reason;
* who brought it when not the family — a suggestion from a staff member or a
  visitor with no file; the visit it was about, only if it is the child's;
* the staff it is about;
* a suggestion is decided (done, by when — or not, and why), its maker told,
  and then done; it has no call-back clock;
* the category and the root cause, and «has this happened before»;
* a board for a period: counts against the period before, per 1,000 visits,
  week by week, categories, units beside their survey score, the people by
  count only, the suggestions, and families who came back.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def family(clinic):
    """The test child with a mother and a father on file."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name="عائلة الاختبار")
        db.session.add(fam)
        db.session.flush()
        db.session.add_all([
            Parent(family_id=fam.id, relation="mother", full_name="منى", phone="01011111111",
                   is_primary_contact=True),
            Parent(family_id=fam.id, relation="father", full_name="أحمد", phone="01022222222",
                   phone_alt="01033333333"),
        ])
        child = db.session.get(Patient, clinic["ids"]["child"])
        child.family_id = fam.id
        child.full_name = "يوسف عمر"
        db.session.commit()
    return clinic


def _last(clinic):
    from app.models import Complaint

    with clinic["app"].app_context():
        c = Complaint.query.order_by(Complaint.id.desc()).first()
        return {"id": c.id, "patient": c.patient_id, "phone": c.contact_phone,
                "note": c.phone_note, "by": c.by_who, "by_staff": c.by_staff_id,
                "visit": c.visit_id, "category": c.category, "kind": c.kind,
                "staff": sorted(u.id for u in c.staff), "status": c.status,
                "decision": c.decision, "done": c.done_at, "cause": c.root_cause,
                "events": [e.kind for e in c.events]}


def _new(clinic, who="desk", **data):
    body = {"description": "استنينا كتير", "kind": "complaint", "channel": "desk"}
    body.update(data)
    return clinic["sign_in"](who).post("/complaints/new", data=body)


def _visit_id(clinic):
    from app.models import Visit

    with clinic["app"].app_context():
        return Visit.query.filter_by(patient_id=clinic["ids"]["child"]).first().id


# ------------------------------------------------------------ ش-١ ---------
def test_the_desk_finds_the_child_by_name_number_or_phone(family):
    desk = family["sign_in"]("desk")
    page = desk.get("/complaints/new").get_data(as_text=True)
    assert "data-patient-picker" in page and "/complaints/patient-search" in page
    for q in ("يوسف", "P1", "01011111111"):
        got = desk.get(f"/complaints/patient-search?q={q}").get_json()
        assert [p["id"] for p in got] == [family["ids"]["child"]], q


def test_the_files_numbers_are_offered_with_whose_they_are(family):
    facts = family["sign_in"]("desk").get(f"/complaints/patient/{family['ids']['child']}/facts").get_json()
    phones = [(p["who"], p["phone"]) for p in facts["phones"]]
    assert phones[0] == ("mother", "01011111111"), "the primary contact first"
    assert ("father", "01022222222") in phones and ("father", "01033333333") in phones
    assert facts["visits"] and facts["visits"][0]["id"] == _visit_id(family)


def test_a_number_from_the_file_needs_no_reason_another_keeps_its_own(family):
    _new(family, patient_id=family["ids"]["child"], phone_pick="01022222222", phone_note="asked")
    got = _last(family)
    assert (got["phone"], got["note"]) == ("01022222222", None)
    _new(family, patient_id=family["ids"]["child"], phone_pick="other",
         contact_phone="01155555555", phone_note="file_wrong")
    got = _last(family)
    assert (got["phone"], got["note"]) == ("01155555555", "file_wrong")
    page = family["sign_in"]("boss").get(f"/complaints/{got['id']}").get_data(as_text=True)
    assert 'data-phone-note="file_wrong"' in page


def test_a_suggestion_from_a_staff_member_with_no_file(family):
    from app.models import User

    with family["app"].app_context():
        doc = User.query.filter_by(username="doc").first().id
    _new(family, kind="suggestion", description="شاشة للدور في الانتظار", by_who="staff", by_staff_id=doc,
         patient_id=family["ids"]["child"])
    got = _last(family)
    assert (got["kind"], got["by"], got["by_staff"]) == ("suggestion", "staff", doc)


def test_the_visit_is_kept_only_when_it_is_the_childs(family):
    from app.extensions import db
    from app.models import Patient, User, Visit

    _new(family, patient_id=family["ids"]["child"], visit_id=_visit_id(family))
    assert _last(family)["visit"] == _visit_id(family)
    with family["app"].app_context():
        other = Patient(patient_number="P2", full_name="غيره", gender="male", is_active=True,
                        date_of_birth=datetime(2024, 1, 1).date())
        db.session.add(other)
        db.session.flush()
        v = Visit(patient_id=other.id, doctor_id=User.query.filter_by(username="doc").first().id)
        db.session.add(v)
        db.session.commit()
        stranger = v.id
    _new(family, patient_id=family["ids"]["child"], visit_id=stranger)
    assert _last(family)["visit"] is None


# ------------------------------------------------------------ ش-٢ / ش-٤ ----
def test_the_staff_and_the_category_and_the_cause(family):
    from app.models import User

    with family["app"].app_context():
        doc = User.query.filter_by(username="doc").first().id
        desk = User.query.filter_by(username="desk").first().id
    _new(family, patient_id=family["ids"]["child"], category="communication", staff_ids=[doc, desk])
    got = _last(family)
    assert got["category"] == "communication" and got["staff"] == sorted([doc, desk])
    boss = family["sign_in"]("boss")
    page = boss.get(f"/complaints/{got['id']}").get_data(as_text=True)
    assert "data-case-staff" in page and 'data-case-category="communication"' in page
    boss.post(f"/complaints/{got['id']}/act", data={"do": "staff", "staff_ids": [doc]})
    assert _last(family)["staff"] == [doc]
    boss.post(f"/complaints/{got['id']}/act", data={
        "do": "answer", "answer": "اتكلمنا مع الدكتور", "root_cause": "communication"})
    assert _last(family)["cause"] == "communication"


def test_has_this_happened_before(family):
    from app.models import CostCentre

    with family["app"].app_context():
        from app.utils import cost_centres
        cost_centres.ensure_all()
        family["db"].session.commit()
        centre = CostCentre.query.first().id
    for _ in range(2):
        _new(family, patient_id=family["ids"]["child"], category="process", cost_centre_id=centre)
    page = family["sign_in"]("boss").get(f"/complaints/{_last(family)['id']}").get_data(as_text=True)
    assert "data-repeat-family" in page and "data-repeat-same" in page


# ------------------------------------------------------------ ش-٣ ---------
def test_a_suggestion_is_decided_told_and_done(family):
    from app.models import MessageLog

    _new(family, kind="suggestion", description="ركن ألعاب", patient_id=family["ids"]["child"],
         phone_pick="01011111111", notify="")
    sid = _last(family)["id"]
    boss = family["sign_in"]("boss")
    page = boss.get(f"/complaints/{sid}").get_data(as_text=True)
    assert 'data-step="decide"' in page and 'data-step="contact"' not in page
    boss.post(f"/complaints/{sid}/act", data={"do": "decide", "decision": "accepted",
                                             "plan": "هنعمل ركن في الدور الأول", "target_date": "2026-12-01",
                                             "notify": "1"})
    got = _last(family)
    assert (got["status"], got["decision"]) == ("answered", "accepted")
    with family["app"].app_context():
        sent = MessageLog.query.filter_by(template_type="suggestion_decided").all()
        assert len(sent) == 1 and "ركن" in sent[0].body
    assert 'data-step="implement"' in boss.get(f"/complaints/{sid}").get_data(as_text=True)
    boss.post(f"/complaints/{sid}/act", data={"do": "done", "text": "الركن اتعمل"})
    got = _last(family)
    assert got["status"] == "closed" and got["done"] is not None and "done" in got["events"]


def test_a_refused_suggestion_closes_with_its_reason(family):
    _new(family, kind="suggestion", description="مواعيد بالليل", anonymous="1")
    sid = _last(family)["id"]
    boss = family["sign_in"]("boss")
    boss.post(f"/complaints/{sid}/act", data={"do": "decide", "decision": "rejected", "plan": ""})
    assert _last(family)["decision"] is None, "a decision needs its reason"
    boss.post(f"/complaints/{sid}/act", data={"do": "decide", "decision": "rejected",
                                             "plan": "مفيش دكاترة بالليل"})
    assert (_last(family)["status"], _last(family)["decision"]) == ("closed", "rejected")


def test_a_suggestion_has_no_call_back_clock(family):
    from app.extensions import db
    from app.models import Complaint
    from app.utils import complaint_cases as cases

    _new(family, kind="suggestion", description="اقتراح")
    _new(family, kind="complaint", description="شكوى")
    with family["app"].app_context():
        for c in Complaint.query.all():
            c.created_at = datetime.utcnow() - timedelta(hours=30)
        db.session.commit()
        late = {c.kind: cases.is_late(c) for c in Complaint.query.all()}
        assert late == {"suggestion": False, "complaint": True}
        assert cases.open_counts()["late"] == 1


# ------------------------------------------------------------ ش-٥ ---------
def test_the_board_counts_and_opens_the_cases(family):
    from app.models import User

    with family["app"].app_context():
        doc = User.query.filter_by(username="doc").first().id
    _new(family, patient_id=family["ids"]["child"], category="process", staff_ids=[doc])
    _new(family, patient_id=family["ids"]["child"], category="process")
    _new(family, kind="compliment", description="شكراً للدكتور", staff_ids=[doc])
    _new(family, kind="suggestion", description="اقتراح")
    boss = family["sign_in"]("boss")
    page = boss.get("/complaints/board").get_data(as_text=True)
    assert boss.get("/complaints/board").status_code == 200
    for mark in ('data-kpi="complaints"', 'data-kpi="rate"', "data-weeks", 'data-bar="category.process"',
                 'data-staff-row="%d"' % doc, "data-suggestions", "data-survey", "data-repeat"):
        assert mark in page, mark
    listed = boss.get("/complaints/?view=all&category=process").get_data(as_text=True)
    assert listed.count("data-case-row=") == 2 and "data-narrowed" in listed
    staff = boss.get(f"/complaints/?view=all&staff={doc}").get_data(as_text=True)
    assert staff.count("data-case-row=") == 2


def test_the_board_numbers(family):
    from app.utils import complaint_board, cs_board

    _new(family, patient_id=family["ids"]["child"])
    _new(family, patient_id=family["ids"]["child"])
    _new(family, kind="suggestion", description="اقتراح")
    with family["app"].app_context():
        d = complaint_board.board(*cs_board.period(None, None))
        assert d["counts"]["complaint"] == 2 and d["counts"]["suggestion"] == 1
        assert d["visits"] == 1 and d["rate"] == 2000.0
        assert sum(w["total"] for w in d["weeks"]) == 3
        assert [(p.id, n) for p, n in d["repeat"]] == [(family["ids"]["child"], 2)]
        assert d["suggestions"]["received"] == 1 and d["suggestions"]["waiting"] == 1


def test_a_person_is_never_judged_on_a_handful(family):
    from app.models import User
    from app.utils import complaint_board, cs_board

    with family["app"].app_context():
        doc = User.query.filter_by(username="doc").first().id
    _new(family, staff_ids=[doc])
    with family["app"].app_context():
        rows = complaint_board.board(*cs_board.period(None, None))["staff"]
        assert rows[0]["complaint"] == 1 and rows[0]["judged"] is False


def test_only_customer_service_sees_the_board(family):
    assert family["sign_in"]("desk").get("/complaints/board").status_code == 403
    page = family["sign_in"]("boss").get("/complaints/").get_data(as_text=True)
    assert "data-to-board" in page
