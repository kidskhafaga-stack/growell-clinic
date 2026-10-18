"""كل القنوات في طابور واحد — المرحلة الأولى من ``CONNECTHUB_PLAN.md``.

* **جهة الاتصال بالهوية، مش بالاسم**: نفس الرقم بأي كتابة شخص واحد، واسمين
  زي بعض على رقمين شخصين؛ والهوية اللي بتاعة حد تاني ما بتتنقلش؛
* **عميل محتمل مفتوح واحد لكل شخص**، و«غير مكتمل» لازم سبب، و«تم التحويل»
  مش زرار: بيحصل بس لما يتعمل طلب موعد فعلاً — ومحتاج رقم يترد عليه؛
* **القنوات لكل عميل**: كل عيادة تختار قنواتها، والصفحة العامة مقفولة لحد
  ما المدير يفتحها؛
* **الصفحة العامة** بتكتب طلب في الطابور العادي بمصدره، وما بتقولش «اتحجز»،
  والطوارئ ليها رد فوري؛ والفخ ما بيكتبش حاجة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def test_a_contact_is_found_by_identity_never_by_name(clinic):
    from app.models import Contact
    from app.utils import leads

    with clinic["app"].app_context():
        a = leads.contact_for("منى أحمد", {"phone": "01001234567"})
        same = leads.contact_for("أم يوسف", {"phone": "+20 100 123 4567"})
        other = leads.contact_for("منى أحمد", {"phone": "01112223334"})
        assert a.id == same.id, "one number, however it is written"
        assert other.id != a.id, "one name, two people"
        ig = leads.contact_for("Mona", {"instagram": "@Mona.K"})
        assert leads.contact_for("x", {"instagram": "mona.k"}).id == ig.id
        # A number that is already somebody's is not moved onto another.
        leads.contact_for("Mona", {"instagram": "mona.k", "phone": "01001234567"})
        assert a.phone == "201001234567" and ig.phone is None
        assert Contact.query.count() == 3


def test_one_open_lead_a_reason_to_lose_it_and_a_number_to_convert_it(clinic):
    from app.models import BookingRequest, User
    from app.utils import leads

    db = clinic["db"]
    with clinic["app"].app_context():
        desk = db.session.get(User, clinic["ids"]["desk"])
        lead, created = leads.open_lead(desk, "Mona", {"instagram": "@mona.k"},
                                        "instagram", source_kind="comment",
                                        campaign="instagram dr ahmed!",
                                        message="الدكتور أحمد موجود إمتى؟")
        assert created and lead.campaign == "instagram-dr-ahmed"
        again, created = leads.open_lead(desk, "Mona", {"instagram": "mona.k"},
                                         "messenger")
        assert again.id == lead.id and not created
        assert [e.kind for e in lead.events][:1] == ["again"]
        with pytest.raises(ValueError):
            leads.open_lead(desk, "", {"phone": "01001234567"}, "phone")
        with pytest.raises(ValueError):
            leads.open_lead(desk, "بلا وسيلة", {}, "phone")

        assert leads.move(lead, "lost", desk) is None, "a reason is required"
        assert leads.move(lead, "converted", desk) is None, "not a button"
        assert leads.move(lead, "contacted", desk) is lead
        assert lead.first_contact_at is not None

        with pytest.raises(ValueError, match="phone"):
            leads.convert(lead, desk)
        leads.contact_for("Mona", {"instagram": "mona.k", "phone": "01005556667"})
        row = leads.convert(lead, desk)
        db.session.commit()
        assert lead.stage == "converted" and lead.booking_request_id == row.id
        req = db.session.get(BookingRequest, row.id)
        assert (req.source, req.campaign, req.lead_id, req.status) == (
            "instagram", "instagram-dr-ahmed", lead.id, "pending")
        assert req.contact_phone == "201005556667"
        with pytest.raises(ValueError, match="closed"):
            leads.convert(lead, desk)

        report = leads.report(30)
        assert dict(report["channels"])["instagram"]["converted"] == 1
        assert report["campaigns"][0][0] == "instagram-dr-ahmed"


def test_the_board_the_lead_and_the_doors_to_them(clinic):
    from app.models import Lead

    desk = clinic["sign_in"]("desk")
    assert desk.get("/messages/leads").status_code == 200
    desk.post("/messages/leads", data={
        "name": "أبو كريم", "phone": "01007778889", "channel": "phone",
        "source_kind": "call", "campaign": "radio", "follow_up_on": "2000-01-01"})
    with clinic["app"].app_context():
        lead = Lead.query.one()
        lid = lead.id
    page = desk.get("/messages/leads").get_data(as_text=True)
    assert f'data-lead="{lid}"' in page and "data-to-leads" not in page
    assert "data-to-leads" in desk.get("/messages/desk").get_data(as_text=True)
    assert "data-to-leads" in desk.get("/messages/inbox").get_data(as_text=True)

    desk.post(f"/messages/leads/{lid}/stage", data={"stage": "lost"})
    with clinic["app"].app_context():
        assert Lead.query.one().stage == "new"
    desk.post(f"/messages/leads/{lid}/stage", data={"stage": "lost", "reason": "price"})
    with clinic["app"].app_context():
        assert Lead.query.one().lost_reason == "price"
    view = desk.get(f"/messages/leads/{lid}").get_data(as_text=True)
    assert 'data-lead-stage="lost"' in view and "lost:price" not in view

    desk.post(f"/messages/leads/{lid}/link", data={"patient_id": clinic["ids"]["child"]})
    with clinic["app"].app_context():
        assert Lead.query.one().contact.patient_id == clinic["ids"]["child"]
        assert Lead.query.one().contact.linked_by == clinic["ids"]["desk"]


def test_a_lead_from_a_whatsapp_conversation(clinic):
    from app.models import Lead, MessageLog

    with clinic["app"].app_context():
        clinic["db"].session.add(MessageLog(to_phone="201009998887", body="بكام الكشف؟",
                                            direction="in", status="received"))
        clinic["db"].session.commit()
    desk = clinic["sign_in"]("desk")
    desk.post("/messages/inbox/201009998887/lead", data={"name": "سارة"})
    with clinic["app"].app_context():
        lead = Lead.query.one()
        assert (lead.channel, lead.conversation_key, lead.contact.phone) == (
            "whatsapp", "201009998887", "201009998887")
    page = desk.get("/messages/inbox/201009998887").get_data(as_text=True)
    assert "data-thread-lead-link" in page


def test_each_clinic_chooses_its_channels(clinic):
    from app.utils import channels

    with clinic["app"].app_context():
        assert channels.enabled() == ["whatsapp", "phone", "walk_in"]
        assert channels.connection("whatsapp") == "link"
        assert channels.connection("instagram") == "manual"
        assert channels.channel_of_tag("ig-dr-ahmed") == "instagram"
        assert channels.channel_of_tag("summer") == "page"
    assert clinic["sign_in"]("desk").get("/messages/channels").status_code in (302, 403)
    boss = clinic["sign_in"]()
    assert boss.get("/messages/channels").status_code == 200
    boss.post("/messages/channels", data={"channel": ["instagram", "phone", "nope"],
                                          "page": "on"})
    with clinic["app"].app_context():
        assert channels.enabled() == ["instagram", "phone", "page"]
    page = boss.get("/messages/channels?c=instagram&label=dr ahmed").get_data(as_text=True)
    assert "src=instagram-dr-ahmed" in page


def test_the_public_page_takes_a_request_and_confirms_nothing(clinic):
    from app.models import BookingRequest, Lead
    from app.utils import channels

    public = clinic["app"].test_client()
    assert public.get("/book").status_code == 404, "closed until opened"
    with clinic["app"].app_context():
        channels.set_page(True)
        clinic["db"].session.commit()
    page = public.get(f"/book?src=instagram-dr-ahmed&doctor={clinic['ids']['doctor']}")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'value="instagram-dr-ahmed"' in body and "selected" in body

    public.post("/book", data={"name": "بوت", "phone": "01000000001", "website": "x"})
    bad = public.post("/book", data={"name": "أم علي", "phone": "12"})
    assert bad.status_code == 400
    with clinic["app"].app_context():
        assert BookingRequest.query.count() == 0, "the trap and a bad number write nothing"

    done = public.post("/book", data={
        "name": "أم علي", "phone": "01002223334", "child": "علي",
        "message": "عنده تشنج من الصبح", "src": "instagram-dr-ahmed",
        "doctor": str(clinic["ids"]["admin"])}, follow_redirects=True)
    text = done.get_data(as_text=True)
    assert "data-book-done" in text and "data-book-urgent" in text
    with clinic["app"].app_context():
        req = BookingRequest.query.one()
        assert (req.source, req.campaign, req.status, req.doctor_id) == (
            "page", "instagram-dr-ahmed", "pending", None)
        lead = Lead.query.one()
        assert (lead.channel, lead.source_kind, lead.stage) == (
            "instagram", "form", "converted")
        assert "علي" in req.message


def test_every_channel_row_says_where_it_is_set_up(clinic):
    """WhatsApp has its own screen; the accounts the clinic connects jump to
    their own box in «connect» on the same page; the phone and the walk-in
    need nothing. A row with no way to its settings read as «there are none»."""
    page = clinic["sign_in"]().get("/messages/channels").get_data(as_text=True)
    assert 'data-channel-settings="whatsapp"' in page
    for k in ("messenger", "instagram", "telegram", "tiktok", "email"):
        assert f'href="#connect-{k}" data-channel-settings="{k}"' in page
        assert f'id="connect-{k}"' in page
    for k in ("phone", "walk_in"):
        assert f'<span class="hint" data-channel-settings="{k}">' in page
