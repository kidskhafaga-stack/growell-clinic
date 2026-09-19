"""أرقام مكتب خدمة العملاء بتتقرا كأرقام.

التلات أرقام اللي الموظف بيتصرّف بناءً عليهم — اتبعت كام، فشل كام، مستني كام —
كانوا متكتبين بـ`info-grid`، وده تنسيق «اسم صغير رمادي فوق قيمة» معمول لبيانات
المريض: تاريخ ميلاد، فصيلة دم. حاجة بتتقرا مرة، مش رقم حد بيتصرّف عليه.

فطلعوا باهتين وسط شاشة كلها كروت وشارات، ومحدّش بيشوفهم — وهو المكتب اللي
موجود علشان حد يشوف الأرقام دي.

دلوقتي `stat-card`، وهو الشكل اللي البرنامج نفسه بيعرض بيه الأرقام في المرضى
والتطعيمات: **مش شكل جديد، الشكل اللي موجود**.

**واللون معلومة مش زينة:** الفشل بيبقى أحمر لما يبقى فيه فشل، وأزرق عادي لما
ميكونش — عشان كارت أحمر دايماً بيبطّل يعني حاجة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:messages", "1")
        clinic["db"].session.commit()
    return clinic


def _page(clinic):
    page = clinic["sign_in"]("boss").get("/messages/desk")
    return page, page.get_data(as_text=True)


def test_the_three_numbers_are_drawn_as_numbers(desk):
    page, body = _page(desk)

    assert page.status_code == 200
    assert "data-desk-today" in body
    for stat in ("sent", "failed", "due"):
        assert f'data-desk-stat="{stat}"' in body
    assert "stat-card" in body


def test_they_use_the_shape_the_rest_of_the_program_uses(desk):
    """`stat-card` is what the patients list and the vaccination plans draw
    their counts with. A fourth spelling of «رقم على الشاشة» is a fourth thing
    to keep looking the same."""
    body = _page(desk)[1]
    others = open("app/templates/patients/list.html", errors="ignore").read()

    assert "stat-card" in others
    assert "stat-grid" in body


def test_a_quiet_day_is_not_painted_red(desk):
    """Nothing failed, so nothing is red. A card that is red whether or not
    anything is wrong stops meaning anything."""
    body = _page(desk)[1]

    assert "edge-red" not in body


def test_a_failure_turns_the_card_red(desk):
    """And the colour is the fact, not decoration."""
    from datetime import datetime

    from app.models import MessageLog

    with desk["app"].app_context():
        desk["db"].session.add(MessageLog(
            patient_id=desk["ids"]["child"], to_phone="0100",
            body="test", status="failed", error="missing_phone",
            created_at=datetime.utcnow()))
        desk["db"].session.commit()

    body = _page(desk)[1]
    assert "edge-red" in body


def test_a_failed_message_names_the_person_and_the_reason_apart(desk):
    """Two different facts on one line: **who**, and **why**. The old markup
    ran them together in one grey bullet, so the eye could not separate the
    name from the reason — and the reason is what says what to do: a missing
    number is a job in the file, a network failure is a retry button."""
    from datetime import datetime

    from app.models import MessageLog

    with desk["app"].app_context():
        desk["db"].session.add(MessageLog(
            patient_id=desk["ids"]["child"], to_phone="0100",
            body="test", status="failed", error="missing_phone",
            created_at=datetime.utcnow()))
        desk["db"].session.commit()

    body = _page(desk)[1]
    assert "data-desk-failures" in body
    assert "data-desk-failure" in body
    assert "missing_phone" in body


def test_a_desk_with_nothing_wrong_shows_no_failure_list(desk):
    body = _page(desk)[1]

    assert "data-desk-failures" not in body
