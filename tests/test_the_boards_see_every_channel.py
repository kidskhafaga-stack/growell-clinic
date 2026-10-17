"""الداشبوردات والتقارير بتشوف كل القنوات.

* **سرعة الرد** بتعدّ كل شخص على ماسنجر أو إنستجرام أو غيرهم محادثة لوحده —
  مش محادثة واحدة اسمها «؟» — وفيه جدول لكل قناة؛
* **لوحة الإدارة** فيها العائلات الجديدة جم منين، جنب الفترة اللي قبلها؛
* **التقارير** فيها كارت العملاء المحتملين وسرعة الرد لمين يقدر يفتحهم؛
* **دليل المستخدم** بيشرح القنوات للي بيشتغل عليها، والربط للي بيظبطه بس.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_reply_speed_counts_each_person_on_each_channel(clinic):
    from app.models import MessageLog
    from app.utils import leads, service_stats

    db = clinic["db"]
    with clinic["app"].app_context():
        a = leads.contact_for("A", {"messenger_psid": "P1"})
        b = leads.contact_for("B", {"instagram_igsid": "I1"})
        now = datetime.utcnow()
        for contact, channel in ((a, "messenger"), (b, "instagram")):
            db.session.add(MessageLog(direction="in", channel=channel, contact_id=contact.id,
                                      body="?", status="received", created_at=now - timedelta(hours=3)))
        db.session.add(MessageLog(direction="out", channel="messenger", contact_id=a.id,
                                  body="ok", status="sent", created_at=now - timedelta(hours=2)))
        db.session.commit()
        stats = service_stats.summary(days=7)
        assert stats["asked"] == 2 and stats["answered"] == 1
        by = {r["channel"]: r for r in stats["by_channel"]}
        assert by["messenger"]["answered"] == 1 and by["instagram"]["answered"] == 0
    page = clinic["sign_in"]().get("/messages/service").get_data(as_text=True)
    assert 'data-service-channel="messenger:1"' in page


def test_the_management_board_shows_where_families_came_from(clinic):
    from app.models import User
    from app.utils import leads

    with clinic["app"].app_context():
        desk = clinic["db"].session.get(User, clinic["ids"]["desk"])
        lead, _ = leads.open_lead(desk, "Mona", {"phone": "01001234567"}, "instagram",
                                  source_kind="comment", campaign="dr-ahmed")
        leads.convert(lead, desk)
        clinic["db"].session.commit()
    page = clinic["sign_in"]().get("/reports/management").get_data(as_text=True)
    assert 'data-board-families="1:0"' in page
    hub = clinic["sign_in"]().get("/reports/").get_data(as_text=True)
    assert "/messages/leads" in hub and "/messages/service" in hub


def test_the_guide_explains_channels_to_the_desk_and_setup_to_setup(clinic):
    from tests.test_guide_and_about import guide_sections

    desk = guide_sections(clinic["sign_in"]("desk").get("/guide").data.decode())
    boss = guide_sections(clinic["sign_in"]().get("/guide").data.decode())
    assert "channels_desk" in desk and "channels_setup" not in desk
    assert "channels_desk" in boss and "channels_setup" in boss
