"""تحويل لطبيب (DOCTOR_EASE_PLAN.md ب-٨).

* لطبيب جوه العيادة من القايمة: بيلاقي الطفل في «محوّلين ليك» وعلى زيارة
  الطفل، وبيرد، والرد بيرجع للي حوّل يراجعه ويوقّع؛ ومعاه زرار حجز.
* لطبيب بره باسمه وتخصصه ومكانه: بيتحفظ في دفتر العيادة مرة واحدة.
* السبب مطلوب، والطبيب مطلوب.
* خطاب التحويل بقالب الروشتة، بالعربي أو الإنجليزي، وورقة رد للي بره.
* «محوّل إلى د. …» على روشتة الكشف لما الطبيب يختار، وبيتشال.
* الإلغاء مش مسح، ومش بيلمس «تحويل للطوارئ».
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _second_doctor(clinic):
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        u = User(username="cardio", full_name="منى سامي", role="doctor", is_active=True,
                 specialty="قلب أطفال")
        u.set_password("secret")
        db.session.add(u)
        db.session.commit()
        return u.id


def _url(clinic, tail=""):
    return f"/visits/{clinic['ids']['visit']}{tail}"


def test_inside_the_clinic_reaches_the_other_doctor_and_comes_back(clinic):
    from app.models import Referral

    cardio = _second_doctor(clinic)
    doc = clinic["sign_in"]("doc")
    page = doc.get(_url(clinic, "/record")).get_data(as_text=True)
    assert "data-docref-form" in page and "منى سامي" in page

    # No reason: refused.
    doc.post(_url(clinic, "/refer-doctor"), data={"where": "inside", "to_doctor_id": cardio})
    with clinic["app"].app_context():
        assert Referral.query.count() == 0

    doc.post(_url(clinic, "/refer-doctor"),
             data={"where": "inside", "to_doctor_id": cardio, "reason": "لغط في القلب"})
    with clinic["app"].app_context():
        row = Referral.query.one()
        assert row.kind == "doctor" and row.to_doctor_id == cardio
        assert row.visit_id == clinic["ids"]["visit"] and "منى سامي" in row.sent_to
        rid = row.id
        # Not the emergency referral: the visit is not marked as sent away.
        from app.models import Visit

        assert not clinic["db"].session.get(Visit, clinic["ids"]["visit"]).is_referred

    page = doc.get(_url(clinic, "/record")).get_data(as_text=True)
    assert f'data-docref-row="{rid}"' in page and f'data-docref-book="{rid}"' in page

    # The other doctor finds the child on «Referred to you».
    them = clinic["sign_in"]("cardio")
    listing = them.get("/visits/referrals").get_data(as_text=True)
    assert f'data-to-me="{rid}"' in listing and "لغط في القلب" in listing
    assert f'data-to-me="{rid}"' not in doc.get("/visits/referrals").get_data(as_text=True)

    them.post(f"/visits/referrals/{rid}/feedback", data={"feedback": "إيكو طبيعي، لغط بريء"})
    page = doc.get(_url(clinic, "/record")).get_data(as_text=True)
    assert f'data-docref-answer="{rid}"' in page and "لغط بريء" in page
    assert f'data-docref-sign="{rid}"' in page
    doc.post(f"/visits/referrals/{rid}/review")
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Referral, rid).closed


def test_the_child_shows_on_the_other_doctor_s_own_visit(clinic):
    from app.models import Referral, Visit
    from app.utils.clock import local_today

    cardio = _second_doctor(clinic)
    clinic["sign_in"]("doc").post(_url(clinic, "/refer-doctor"), data={
        "where": "inside", "to_doctor_id": cardio, "reason": "لغط في القلب"})
    with clinic["app"].app_context():
        db = clinic["db"]
        v = Visit(patient_id=clinic["ids"]["child"], doctor_id=cardio, visit_date=local_today())
        db.session.add(v)
        db.session.commit()
        vid, rid = v.id, Referral.query.one().id
    page = clinic["sign_in"]("cardio").get(f"/visits/{vid}/record").get_data(as_text=True)
    assert f'data-docref-to-me="{rid}"' in page and f'data-docref-reply="{rid}"' in page


def test_outside_doctor_is_kept_once_in_the_clinic_s_book(clinic):
    from app.models import ExternalDoctor, Referral

    doc = clinic["sign_in"]("doc")
    form = {"where": "outside", "ext_name": "خالد يوسف", "ext_specialty": "عيون أطفال",
            "ext_place": "مستشفى الرمد — الدقي", "ext_phone": "0123", "reason": "حول"}
    doc.post(_url(clinic, "/refer-doctor"), data=form)
    doc.post(_url(clinic, "/refer-doctor"), data=dict(form, reason="متابعة"))
    with clinic["app"].app_context():
        assert ExternalDoctor.query.count() == 1
        ext = ExternalDoctor.query.one()
        rows = Referral.query.all()
        assert len(rows) == 2 and all(r.external_doctor_id == ext.id for r in rows)
        assert "عيون أطفال" in rows[0].sent_to and "الدقي" in rows[0].sent_to
        ext_id = ext.id
    page = doc.get(_url(clinic, "/record")).get_data(as_text=True)
    assert f'<option value="{ext_id}">' in page
    # Picked from the book next time.
    doc.post(_url(clinic, "/refer-doctor"), data={"where": "outside", "external_id": ext_id,
                                                   "reason": "مراجعة"})
    with clinic["app"].app_context():
        assert ExternalDoctor.query.count() == 1 and Referral.query.count() == 3
    # Neither a name nor a pick: refused.
    doc.post(_url(clinic, "/refer-doctor"), data={"where": "outside", "reason": "x"})
    with clinic["app"].app_context():
        assert Referral.query.count() == 3


def test_the_letter_prints_on_the_prescription_layout_with_a_reply_slip(clinic):
    from app.models import Patient, Referral

    with clinic["app"].app_context():
        p = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        p.allergies = "بنسلين"
        clinic["db"].session.commit()
    doc = clinic["sign_in"]("doc")
    doc.post(_url(clinic, "/refer-doctor"), data={
        "where": "outside", "ext_name": "خالد يوسف", "ext_specialty": "عيون أطفال",
        "reason": "حول في العين الشمال"})
    with clinic["app"].app_context():
        rid = Referral.query.one().id
    letter = doc.get(f"/visits/referrals/{rid}/letter").get_data(as_text=True)
    assert f'data-referral-letter="{rid}"' in letter
    assert "خطاب تحويل" in letter and "حول في العين الشمال" in letter
    assert "د. خالد يوسف" in letter and "بنسلين" in letter
    assert "data-letter-slip" in letter and "Cairo" in letter
    english = doc.get(f"/visits/referrals/{rid}/letter?lang=en").get_data(as_text=True)
    assert "Referral letter" in english and "Dr. خالد يوسف" in english


def test_the_line_on_the_prescription_comes_and_goes(clinic):
    from app.models import Prescription, Referral

    with clinic["app"].app_context():
        db = clinic["db"]
        rx = Prescription(patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
                          visit_id=clinic["ids"]["visit"])
        db.session.add(rx)
        db.session.commit()
        rx_id = rx.id
    doc = clinic["sign_in"]("doc")
    doc.post(_url(clinic, "/refer-doctor"), data={
        "where": "outside", "ext_name": "خالد يوسف", "ext_specialty": "عيون أطفال",
        "reason": "حول", "on_rx": "1"})
    paper = doc.get(f"/prescriptions/{rx_id}").get_data(as_text=True)
    assert "data-paper-referral" in paper and "د. خالد يوسف — عيون أطفال" in paper
    with clinic["app"].app_context():
        rid = Referral.query.one().id
    doc.post(f"/visits/referrals/{rid}/doctor", data={"action": "rx_off"})
    assert "data-paper-referral" not in doc.get(f"/prescriptions/{rx_id}").get_data(as_text=True)


def test_cancel_keeps_the_row_and_leaves_the_emergency_card_alone(clinic):
    from app.models import Referral, Visit

    doc = clinic["sign_in"]("doc")
    doc.post(_url(clinic, "/refer"), data={"kind": "referral", "referred_to": "مستشفى",
                                           "referral_note": "ضيق تنفس"})
    doc.post(_url(clinic, "/refer-doctor"), data={
        "where": "outside", "ext_name": "خالد يوسف", "reason": "حول"})
    with clinic["app"].app_context():
        mine = Referral.query.filter_by(kind="doctor").one().id
    # Another user cannot cancel the doctor's referral.
    assert clinic["sign_in"]("desk").post(f"/visits/referrals/{mine}/doctor",
                                          data={"action": "cancel"}).status_code in (403, 302)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(Referral, mine).cancelled_at is None
    doc.post(f"/visits/referrals/{mine}/doctor", data={"action": "cancel"})
    with clinic["app"].app_context():
        db = clinic["db"]
        assert db.session.get(Referral, mine).cancelled_at is not None
        assert db.session.get(Visit, clinic["ids"]["visit"]).is_referred
        er = Referral.query.filter_by(kind="referral").one()
        assert er.cancelled_at is None
    # Undoing the emergency referral cancels that one, not a doctor referral.
    doc.post(_url(clinic, "/refer-doctor"), data={
        "where": "outside", "ext_name": "خالد يوسف", "reason": "تاني"})
    doc.post(_url(clinic, "/refer"), data={"undo": "1"})
    with clinic["app"].app_context():
        assert Referral.query.filter_by(kind="referral").one().cancelled_at is not None
        live = Referral.query.filter_by(kind="doctor", cancelled_at=None).count()
        assert live == 1
