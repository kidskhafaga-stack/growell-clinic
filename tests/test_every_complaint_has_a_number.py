"""Every complaint has a number, an owner, a clock and an ending.

Asked as: *«قسم الشكاوى ده يبقى كامل ويقيس مدى رضاء العميل — كل شكوى تاخد
رقم ومتابعة وإيه اللي حصل فيها … الشكوى ليها سيستم في خدمة العملاء مش في
الاستقبال … نطبع شكوى فاضية … أو العميل يملاها أونلاين … ونظام متابعة مع
العميل»*. And GAHAR ``PCC.16``: tracked (b), somebody responsible (c),
answered in a set time (d), monitored (e).

A complaint was a WhatsApp thread with a topic on it: no number to hand the
family, no record of what was found or done, no deadline, and nothing asked
afterwards whether the answer settled it.

What is held here:

* anybody who works here writes one down and gets a number to hand over —
  numbered per year, in order; reception can *register* and cannot *handle*;
* anonymous means no name, no number and no message;
* customer service contacts, answers (found / done / told), and the family is
  sent the answer with a link — their verdict closes it, or reopens it when
  the answer settled nothing;
* the clinic's own timeframes mark a case late, and only an admin sets them;
* a low survey answer opens a case once; a family can write one from a
  signed link, and a link that is not ours opens nothing;
* whoever handles complaints sees them on the bell; nobody else does.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401


def _phone(clinic, number="01012345678"):
    from app.models import Patient

    with clinic["app"].app_context():
        clinic["db"].session.get(Patient, clinic["ids"]["child"]).own_phone = number
        clinic["db"].session.commit()


def _register(clinic, who="desk", **fields):
    data = {"description": "استنينا ساعتين والدكتور ما شرحش حاجة",
            "kind": "complaint", "channel": "desk", "notify": "1"}
    data.update(fields)
    return clinic["sign_in"](who).post("/complaints/new", data=data)


def _case(clinic, number=None):
    from app.models import Complaint

    with clinic["app"].app_context():
        q = Complaint.query
        row = (q.filter_by(number=number).one() if number
               else q.order_by(Complaint.id.desc()).first())
        return {"id": row.id, "number": row.number, "status": row.status,
                "patient": row.patient_id, "name": row.contact_name,
                "phone": row.contact_phone, "by": row.created_by,
                "token": row.token, "rating": row.resolution_rating,
                "reopened": row.reopened_count, "channel": row.channel,
                "side": row.side, "feedback": row.feedback_id,
                "contact": row.first_contact_at, "answer": row.answer,
                "events": [e.kind for e in row.events]}


def _sent(clinic, template_type):
    from app.models import MessageLog

    with clinic["app"].app_context():
        return [m.body for m in MessageLog.query.filter_by(
            template_type=template_type).all()]


# ------------------------------------------------------------- register ---
def test_reception_writes_it_down_and_hands_over_a_number(clinic):
    _phone(clinic)
    year = datetime.utcnow().year
    reply = _register(clinic, patient_id=clinic["ids"]["child"])
    case = _case(clinic)
    assert case["number"] == f"C-{year}-0001"
    assert (case["status"], case["patient"], case["by"]) == (
        "new", clinic["ids"]["child"], clinic["ids"]["desk"])
    assert case["events"][:1] == ["opened"]
    assert reply.status_code == 302 and "/receipt" in reply.headers["Location"]
    receipt = clinic["sign_in"]("desk").get(reply.headers["Location"]).get_data(as_text=True)
    assert f"C-{year}-0001" in receipt
    # The family is sent the number.
    sent = _sent(clinic, "complaint_received")
    assert len(sent) == 1 and f"C-{year}-0001" in sent[0]
    _register(clinic, patient_id=clinic["ids"]["child"], notify="")
    assert _case(clinic)["number"] == f"C-{year}-0002"
    assert len(_sent(clinic, "complaint_received")) == 1   # asked not to


def test_reception_registers_but_does_not_handle(clinic):
    _register(clinic)
    case = _case(clinic)
    desk = clinic["sign_in"]("desk")
    assert desk.get("/complaints/").status_code == 403
    assert desk.get(f"/complaints/{case['id']}").status_code == 403
    assert desk.post(f"/complaints/{case['id']}/act",
                     data={"do": "close"}).status_code == 403
    assert clinic["sign_in"]("boss").get(f"/complaints/{case['id']}").status_code == 200
    # Another receptionist's receipt is not theirs to open either.
    assert clinic["sign_in"]("doc").get(
        f"/complaints/{case['id']}/receipt").status_code == 403


def test_a_person_granted_it_handles_them(clinic):
    from app.models.user_capability import UserCapability

    with clinic["app"].app_context():
        clinic["db"].session.add(UserCapability(user_id=clinic["ids"]["desk"],
                                                capability="complaints_manage"))
        clinic["db"].session.commit()
    assert clinic["sign_in"]("desk").get("/complaints/").status_code == 200


def test_anonymous_keeps_no_name_and_sends_nothing(clinic):
    _phone(clinic)
    _register(clinic, anonymous="1", patient_id=clinic["ids"]["child"],
              contact_name="أم يوسف", contact_phone="01099999999")
    case = _case(clinic)
    assert (case["patient"], case["name"], case["phone"]) == (None, None, None)
    assert _sent(clinic, "complaint_received") == []


def test_nothing_said_is_not_a_complaint(clinic):
    from app.models import Complaint

    _register(clinic, description="   ")
    with clinic["app"].app_context():
        assert Complaint.query.count() == 0


# --------------------------------------------------------------- handle ---
def _act(clinic, case_id, **data):
    return clinic["sign_in"]("boss").post(f"/complaints/{case_id}/act", data=data)


def test_contact_answer_and_the_familys_verdict_closes_it(clinic):
    _phone(clinic)
    _register(clinic, patient_id=clinic["ids"]["child"])
    case = _case(clinic)
    _act(clinic, case["id"], do="contact", text="كلمت الأم الساعة ٥")
    after = _case(clinic)
    assert after["status"] == "in_progress" and after["contact"] is not None
    _act(clinic, case["id"], do="answer", finding="الانتظار كان ساعتين فعلاً",
         action="اتضاف دكتور تاني يوم الخميس", answer="اعتذرنا وضفنا دكتور تاني",
         notify="1")
    assert _case(clinic)["status"] == "answered"
    sent = _sent(clinic, "complaint_answered")
    assert len(sent) == 1 and "اعتذرنا وضفنا دكتور تاني" in sent[0]
    assert f"/f/c/{case['token']}" in sent[0]

    public = clinic["app"].test_client()
    page = public.get(f"/f/c/{case['token']}").get_data(as_text=True)
    assert "اعتذرنا وضفنا دكتور تاني" in page and "data-verdict-form" in page
    # A score that is not one of the five stars is not a verdict.
    for junk in ("9", "0", "", "خمسة"):
        public.post(f"/f/c/{case['token']}", data={"stars": junk})
    assert _case(clinic)["rating"] is None
    public.post(f"/f/c/{case['token']}", data={"stars": "5", "comment": "تمام"})
    done = _case(clinic)
    assert (done["status"], done["rating"]) == ("closed", 5)
    public.post(f"/f/c/{case['token']}", data={"stars": "1"})     # once
    assert _case(clinic)["rating"] == 5
    assert done["events"] == ["opened", "message", "contacted", "answered",
                              "message", "rated", "closed"]


def test_an_answer_that_settled_nothing_reopens_it(clinic):
    _register(clinic)
    case = _case(clinic)
    _act(clinic, case["id"], do="answer", answer="هنراجع الموضوع")
    clinic["app"].test_client().post(f"/f/c/{case['token']}", data={"stars": "2"})
    after = _case(clinic)
    assert (after["status"], after["reopened"], after["rating"]) == ("in_progress", 1, 2)


def test_no_verdict_before_there_is_an_answer(clinic):
    _register(clinic)
    case = _case(clinic)
    clinic["app"].test_client().post(f"/f/c/{case['token']}", data={"stars": "5"})
    assert _case(clinic)["rating"] is None


def test_it_is_handed_only_to_somebody_who_can_handle_it(clinic):
    from app.models import Complaint

    _register(clinic)
    case = _case(clinic)
    _act(clinic, case["id"], do="assign", owner_id=clinic["ids"]["desk"])
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Complaint, case["id"]).owner_id is None
    _act(clinic, case["id"], do="assign", owner_id=clinic["ids"]["admin"])
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Complaint, case["id"]).owner_id == clinic["ids"]["admin"]


# ------------------------------------------------------------ the clock ---
def test_the_clinics_timeframe_decides_what_is_late(clinic):
    from app.models import Complaint

    _register(clinic)
    case = _case(clinic)
    with clinic["app"].app_context():
        clinic["db"].session.get(Complaint, case["id"]).created_at = (
            datetime.utcnow() - timedelta(hours=30))
        clinic["db"].session.commit()
    boss = clinic["sign_in"]("boss")
    assert f'data-case-row="{case["number"]}"' in boss.get(
        "/complaints/?view=late").get_data(as_text=True)
    # Only an admin changes the policy.
    assert clinic["sign_in"]("desk").post("/complaints/settings", data={
        "complaint_contact_hours": "48"}).status_code == 403
    boss.post("/complaints/settings", data={"complaint_contact_hours": "48",
                                            "complaint_close_days": "10"})
    assert f'data-case-row="{case["number"]}"' not in boss.get(
        "/complaints/?view=late").get_data(as_text=True)
    # And a figure outside any sensible range is not taken — not from the
    # screen, and not if one reached the settings some other way.
    boss.post("/complaints/settings", data={"complaint_contact_hours": "0"})
    from app.models import Setting
    from app.utils import complaint_cases
    with clinic["app"].app_context():
        assert complaint_cases.first_contact_hours() == 48
        Setting.set("complaint_close_days", "900")
        clinic["db"].session.commit()
        assert complaint_cases.close_days() == complaint_cases.DEFAULT_CLOSE_DAYS


# ---------------------------------------------------- from elsewhere ---
def test_a_low_survey_answer_opens_one_case(clinic):
    from app.models import Complaint, Feedback

    _phone(clinic)
    with clinic["app"].app_context():
        fb = Feedback(patient_id=clinic["ids"]["child"], token="tok-low",
                      status="sent")
        clinic["db"].session.add(fb)
        clinic["db"].session.commit()
    form = {"doctor_rating": "4", "service_rating": "3", "finance_rating": "1",
            "nps": "5", "comment": "الفاتورة غالية"}
    public = clinic["app"].test_client()
    public.post("/f/tok-low", data=form)
    public.post("/f/tok-low", data=form)
    with clinic["app"].app_context():
        assert Complaint.query.count() == 1
    case = _case(clinic)
    assert (case["channel"], case["side"], case["patient"]) == (
        "survey", "finance", clinic["ids"]["child"])
    assert case["feedback"] is not None
    # And asked again for the same survey — by a retry, a second worker —
    # it hands back the case it already opened.
    from app.utils import complaint_cases
    with clinic["app"].app_context():
        fb = Feedback.query.filter_by(token="tok-low").one()
        assert complaint_cases.from_feedback(fb).id == case["id"]
        assert Complaint.query.count() == 1


def test_a_family_writes_it_themselves_from_a_signed_link(clinic):
    from app.models import Patient
    from app.utils import complaint_cases

    with clinic["app"].app_context(), clinic["app"].test_request_context():
        token = complaint_cases.invite_token(
            clinic["db"].session.get(Patient, clinic["ids"]["child"]))
    public = clinic["app"].test_client()
    assert "data-online-complaint" in public.get(f"/f/c/new/{token}").get_data(as_text=True)
    reply = public.post(f"/f/c/new/{token}", data={
        "kind": "suggestion", "side": "service",
        "description": "يا ريت مكان انتظار للأطفال"})
    case = _case(clinic)
    assert (case["channel"], case["patient"], case["side"]) == (
        "online", clinic["ids"]["child"], "service")
    assert f"/f/c/{case['token']}" in reply.headers["Location"]
    # A link somebody made up opens nothing and writes nothing.
    assert public.get(f"/f/c/new/{token}x").status_code == 404
    public.post(f"/f/c/new/{token}x", data={"description": "x"})
    from app.models import Complaint
    with clinic["app"].app_context():
        assert Complaint.query.count() == 1


def test_the_thread_starts_the_case_with_what_they_wrote(clinic):
    from app.models import MessageLog

    with clinic["app"].app_context():
        clinic["db"].session.add(MessageLog(
            patient_id=clinic["ids"]["child"], to_phone="201012345678",
            body="الممرضة كلمتنا وحش", direction="in", status="received"))
        clinic["db"].session.commit()
    page = clinic["sign_in"]("desk").get(
        f"/complaints/new?thread=p{clinic['ids']['child']}").get_data(as_text=True)
    assert "الممرضة كلمتنا وحش" in page and "data-patient-chosen" in page


def test_the_paper_form_says_how_soon(clinic):
    page = clinic["sign_in"]("desk").get("/complaints/blank").get_data(as_text=True)
    assert "data-blank-form" in page and "24" in page


def test_the_bell_tells_whoever_handles_them(clinic):
    from app.models import User
    from app.utils.notifications import get_notifications, invalidate

    _register(clinic)
    invalidate()                    # the bell's list is shared, and cached
    with clinic["app"].app_context():
        boss = clinic["db"].session.get(User, clinic["ids"]["admin"])
        desk = clinic["db"].session.get(User, clinic["ids"]["desk"])
        assert any(n["key"] == "complaints" for n in get_notifications(boss))
        assert not any(n["key"] == "complaints" for n in get_notifications(desk))
