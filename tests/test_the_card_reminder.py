"""The family reminded that its card runs out (CONTRACTS_PLAN.md ع-١, the part
left: «رسالة تذكير للأهل من القايمة»).

From the list of expiring cards reception reminds one family, or every family
not reminded this week — the clinic's own template (`card_expiring`), sent
the way it sends everything else (WhatsApp, a link to press, or SMS), logged,
and shown on the row as «reminded on».
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_card_reception_sees import _card  # noqa: E402

PHONE = "01001234567"


def _phone(clinic, number=PHONE):
    from app.models import Patient

    with clinic["app"].app_context():
        clinic["db"].session.get(Patient, clinic["ids"]["child"]).own_phone = number
        clinic["db"].session.commit()


def _logs(clinic):
    from app.models import MessageLog

    with clinic["app"].app_context():
        return [(m.template_type, m.status, m.body) for m in
                MessageLog.query.filter_by(template_type="card_expiring").all()]


def test_one_family_reminded_from_the_list(clinic):
    _, cov = _card(clinic, days_left=5)
    _phone(clinic)
    boss = clinic["sign_in"]("boss")
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert f'data-remind="{cov}"' in page and "data-remind-all" in page
    got = boss.post(f"/patients/coverage/{cov}/remind", data={"days": "14"})
    assert got.status_code == 200
    logs = _logs(clinic)
    assert len(logs) == 1
    body = logs[0][2]
    assert "شركة النيل" in body and "طفل" in body
    # The row now says when.
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert "data-reminded" in page


def test_the_template_is_the_clinics_own(clinic):
    from app.models import MessageTemplate

    _, cov = _card(clinic, days_left=5)
    _phone(clinic)
    with clinic["app"].app_context():
        clinic["db"].session.add(MessageTemplate(
            name="كارت", occasion="card_expiring", is_active=True,
            body="يا أهل {first_name}: كارت {payer} بينتهي {expiry_date}"))
        clinic["db"].session.commit()
    clinic["sign_in"]("boss").post(f"/patients/coverage/{cov}/remind")
    assert _logs(clinic)[0][2].startswith("يا أهل طفل: كارت شركة النيل بينتهي ")


def test_remind_all_skips_the_reminded_this_week_and_the_ones_with_no_number(clinic):
    from app.models import MessageLog

    _, cov = _card(clinic, days_left=3)
    boss = clinic["sign_in"]("boss")
    # No number: nothing to send, and no button on the row.
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert f'data-remind="{cov}"' not in page
    boss.post("/patients/coverage/expiring/remind-all", data={"days": "14"})
    assert _logs(clinic) == []
    _phone(clinic)
    got = boss.post("/patients/coverage/expiring/remind-all", data={"days": "14"})
    assert "/messages" in got.headers["Location"]
    assert len(_logs(clinic)) == 1
    # Pressed again the same week: the family is not reminded twice.
    boss.post("/patients/coverage/expiring/remind-all", data={"days": "14"})
    assert len(_logs(clinic)) == 1
    # A week later it is.
    with clinic["app"].app_context():
        row = MessageLog.query.filter_by(template_type="card_expiring").one()
        row.created_at = datetime.utcnow() - timedelta(days=8)
        clinic["db"].session.commit()
    boss.post("/patients/coverage/expiring/remind-all", data={"days": "14"})
    assert len(_logs(clinic)) == 2


def test_a_family_that_asked_not_to_be_messaged_is_not(clinic):
    from app.models import Patient

    _, cov = _card(clinic, days_left=5)
    _phone(clinic)
    with clinic["app"].app_context():
        clinic["db"].session.get(Patient, clinic["ids"]["child"]).wa_opt_out = True
        clinic["db"].session.commit()
    boss = clinic["sign_in"]("boss")
    boss.post(f"/patients/coverage/{cov}/remind")
    assert [s for _t, s, _b in _logs(clinic)] == ["skipped"]
    # A skipped one is not «reminded».
    assert "data-reminded" not in boss.get("/patients/coverage/expiring").get_data(as_text=True)


def test_the_type_is_on_the_templates_screen(clinic):
    page = clinic["sign_in"]("boss").get("/messages/occasions").get_data(as_text=True)
    assert "تذكير بتجديد كارت التأمين" in page
