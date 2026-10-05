"""طفل حالته بتسوء، ونداء المساعدة واللي حصل بعده — GAHAR `ICD.22` / `GSR.10`.

* **(أ) معايير حسب السن** — حدود النبض والتنفس بقت أرقام المستشفى في سجل
  القواعد، والقراية الحمرا هي اللي بتتنقل على النداء؛
* **(د) الأكواد** — قايمة المستشفى بكلامها؛
* **(هـ) مدة الاستجابة** — رقم المستشفى، ومن غيره البرنامج بيقيس ومش بيحكم؛
* **(و) نفس الاستجابة ٢٤/٧** — التقرير مقسوم على الأيام والساعات؛
* **(ز) التسجيل** — النداء نفسه على ملف الطفل، ومش بيتقفل من غير ما حد يوصل.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """الملاحظة شغّالة، وممرضة، وقراية حمرا للطفل."""
    from app.models import Observation, Setting, User

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:observations", "1")
        nurse = User(username="nurse", full_name="الممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        db.session.add(nurse)
        db.session.flush()
        red = Observation(patient_id=clinic["ids"]["child"], resp_rate=70,
                          spo2=88, pulse_bpm=120, avpu="V",
                          recorded_by=nurse.id)
        db.session.add(red)
        db.session.commit()
        clinic["ids"]["nurse"] = nurse.id
        clinic["ids"]["red"] = red.id
    return clinic


def _last():
    from app.models.deterioration import DeteriorationCall

    return DeteriorationCall.query.order_by(DeteriorationCall.id.desc()).first()


def _call(c, who="nurse", **form):
    pid = c["ids"]["child"]
    return c["sign_in"](who).post(f"/observations/patient/{pid}/call",
                                  data=form)


def test_the_red_reading_is_on_the_chart_and_goes_on_the_call(ward):
    nurse = ward["sign_in"]("nurse")
    page = nurse.get(f"/observations/patient/{ward['ids']['child']}"
                     ).get_data(as_text=True)
    assert "data-call-box" in page and "data-call-form" in page
    assert "RR 70" in page and "SpO2 88" in page and "AVPU V" in page

    got = _call(ward, observation_id=str(ward["ids"]["red"]),
                called_whom="النوبتجي")
    assert got.status_code == 302
    with ward["app"].app_context():
        row = _last()
        assert row.reading.startswith("RR 70") or "RR 70" in row.reading
        assert "AVPU V" in row.reading
        assert row.observation_id == ward["ids"]["red"]
        assert row.noticed_by == ward["ids"]["nurse"]
        assert row.called_whom == "النوبتجي" and row.is_open
        call_id = row.id
    chart = nurse.get(f"/observations/patient/{ward['ids']['child']}"
                      ).get_data(as_text=True)
    assert f'data-open-call="{call_id}"' in chart


def test_a_call_needs_a_reason_and_somebody_called(ward):
    from app.models.deterioration import DeteriorationCall

    _call(ward, called_whom="النوبتجي")              # no reading, no words
    _call(ward, concern="نهجان")                      # nobody called
    with ward["app"].app_context():
        assert DeteriorationCall.query.count() == 0
    # The worry in words is enough — no band replaces the nurse's eyes.
    _call(ward, concern="لونه اتغيّر", called_whom="فريق الطوارئ")
    with ward["app"].app_context():
        row = _last()
        assert row.reading is None and row.concern == "لونه اتغيّر"


def test_a_reading_of_another_child_is_not_copied(ward):
    from app.models import Patient

    with ward["app"].app_context():
        other = Patient(patient_number="P2", full_name="تاني", gender="male",
                        date_of_birth=date(2024, 1, 1), is_active=True)
        ward["db"].session.add(other)
        ward["db"].session.commit()
        other_id = other.id
    ward["sign_in"]("nurse").post(
        f"/observations/patient/{other_id}/call",
        data={"observation_id": str(ward["ids"]["red"]), "concern": "x",
              "called_whom": "y"})
    with ward["app"].app_context():
        row = _last()
        assert row.patient_id == other_id
        assert row.observation_id is None and row.reading is None


def test_the_code_is_the_hospitals_own(ward):
    boss = ward["sign_in"]()
    boss.post("/observations/calls/settings", data={"code": "كود أزرق"})
    with ward["app"].app_context():
        from app.utils import deterioration as det

        (code,) = det.codes()
        key = code.key
    # A code alone is enough to say how help was called.
    _call(ward, concern="مش طبيعي", code_key=key)
    # A key that is not on the list is dropped, not stored.
    _call(ward, concern="مش طبيعي", code_key="code_made_up")
    with ward["app"].app_context():
        from app.models.deterioration import DeteriorationCall

        rows = DeteriorationCall.query.order_by(DeteriorationCall.id).all()
        assert len(rows) == 1 and rows[0].code_key == key
    page = boss.get(f"/observations/call/{rows[0].id}").get_data(as_text=True)
    assert "كود أزرق" in page

    # Only the admin writes the list.
    nurse = ward["sign_in"]("nurse")
    assert nurse.post("/observations/calls/settings",
                      data={"code": "x"}).status_code == 403


def test_nobody_closes_a_call_nobody_answered(ward):
    _call(ward, concern="نهجان", called_whom="النوبتجي")
    with ward["app"].app_context():
        call_id = _last().id
    doc = ward["sign_in"]("doc")
    doc.post(f"/observations/call/{call_id}/close",
             data={"actions": "أكسجين", "outcome": "stayed"})
    with ward["app"].app_context():
        assert _last().is_open

    page = doc.get(f"/observations/call/{call_id}").get_data(as_text=True)
    assert "data-arrive-form" in page and "data-nobody" in page
    doc.post(f"/observations/call/{call_id}/arrive")
    doc.post(f"/observations/call/{call_id}/arrive")       # once only
    with ward["app"].app_context():
        row = _last()
        assert row.arrived_by == ward["ids"]["doctor"]
        first = row.arrived_at

    # Arrived, but nothing written — still open.
    doc.post(f"/observations/call/{call_id}/close",
             data={"actions": "", "outcome": "stayed"})
    doc.post(f"/observations/call/{call_id}/close",
             data={"actions": "أكسجين", "outcome": "made_up"})
    with ward["app"].app_context():
        row = _last()
        assert row.is_open and row.arrived_at == first

    doc.post(f"/observations/call/{call_id}/close",
             data={"actions": "أكسجين ومحلول", "outcome": "transferred"})
    with ward["app"].app_context():
        row = _last()
        assert not row.is_open and row.outcome == "transferred"
        assert row.closed_by == ward["ids"]["doctor"]
    page = doc.get(f"/observations/call/{call_id}").get_data(as_text=True)
    assert "data-call-closed" in page and "أكسجين ومحلول" in page


def test_a_call_that_became_an_arrest_points_at_the_resuscitation(ward):
    from app.models import Resuscitation

    with ward["app"].app_context():
        arrest = Resuscitation(patient_id=ward["ids"]["child"])
        ward["db"].session.add(arrest)
        ward["db"].session.commit()
        arrest_id = arrest.id
    _call(ward, concern="وقف نفس", called_whom="الكود")
    with ward["app"].app_context():
        call_id = _last().id
    doc = ward["sign_in"]("doc")
    doc.post(f"/observations/call/{call_id}/arrive")
    page = doc.get(f"/observations/call/{call_id}").get_data(as_text=True)
    assert "resuscitation_id" in page
    doc.post(f"/observations/call/{call_id}/close",
             data={"actions": "إنعاش", "outcome": "resuscitation",
                   "resuscitation_id": str(arrest_id)})
    with ward["app"].app_context():
        assert _last().resuscitation_id == arrest_id


def test_late_is_the_hospitals_number_or_nothing(ward):
    from app.utils import deterioration as det

    with ward["app"].app_context():
        _call(ward, concern="نهجان", called_whom="النوبتجي")
        row = _last()
        row.called_at = datetime.utcnow() - timedelta(minutes=20)
        ward["db"].session.commit()
        # No number written: measured, not judged.
        assert det.response_minutes() is None
        assert det.late(row) is None

    boss = ward["sign_in"]()
    boss.post("/observations/calls/settings", data={"minutes": "10"})
    with ward["app"].app_context():
        assert det.response_minutes() == 10
        row = _last()
        assert det.late(row) is True
        row.arrived_at = row.called_at + timedelta(minutes=5)
        ward["db"].session.commit()
        assert det.late(row) is False
    # Nonsense clears it rather than inventing one.
    boss.post("/observations/calls/settings", data={"minutes": "abc"})
    with ward["app"].app_context():
        assert det.response_minutes() is None


def test_the_open_call_is_on_the_boards(ward):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        ward["db"].session.commit()
    _call(ward, concern="نهجان", called_whom="النوبتجي")
    with ward["app"].app_context():
        call_id = _last().id
    boss = ward["sign_in"]()
    board = boss.get("/observations/").get_data(as_text=True)
    assert "data-to-calls" in board
    calls = boss.get("/observations/calls").get_data(as_text=True)
    assert f'data-call-row="{call_id}"' in calls
    assert "data-call-settings" in calls
    watch = boss.get("/beds/watch").get_data(as_text=True)
    assert f'data-watch-call="{call_id}"' in watch
    # The nurse sees the list but not the hospital's settings.
    nurse_view = ward["sign_in"]("nurse").get("/observations/calls"
                                              ).get_data(as_text=True)
    assert f'data-call-row="{call_id}"' in nurse_view
    assert "data-call-settings" not in nurse_view


def test_the_report_counts_and_splits_by_day_and_hour(ward):
    from app.utils import deterioration as det
    from app.utils.clock import local_today, to_local

    with ward["app"].app_context():
        for minutes in (4, 12, None):
            _call(ward, concern="نهجان", called_whom="النوبتجي")
            row = _last()
            if minutes is not None:
                row.arrived_at = row.called_at + timedelta(minutes=minutes)
            ward["db"].session.commit()
        det.set_response_minutes(10)
        ward["db"].session.commit()
        today = local_today()
        data = det.report(today, today)
        assert data["count"] == 3
        assert data["median"] == 12           # of 4 and 12, the upper
        assert len(data["unanswered"]) == 1
        # The 12-minute arrival, and the call still waiting past 10 minutes
        # only once it has waited that long.
        assert len(data["late"]) == 1
        local = to_local(_last().called_at)
        day = data["by_weekday"][local.weekday()]
        block = data["by_block"][local.hour // 6]
        assert day["count"] == 3 and block["count"] == 3
        assert sum(d["count"] for d in data["by_weekday"]) == 3
    page = ward["sign_in"]().get("/observations/calls/report"
                                 ).get_data(as_text=True)
    for marker in ("data-report-summary", "data-by-weekday", "data-by-block",
                   "data-report-late"):
        assert marker in page


def test_the_report_without_a_number_says_so(ward):
    page = ward["sign_in"]().get("/observations/calls/report"
                                 ).get_data(as_text=True)
    assert "data-no-limit" in page and "data-report-late" not in page
