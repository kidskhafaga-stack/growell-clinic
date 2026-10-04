"""«Pay first, then it is done» in emergency — for a child triaged
non-urgent, and never for anybody else.

Asked as *«خيار يدفع الاول وبعدين يتنفذ والحالة الخطر تتنفذ على طول»*, with
the hospital's lawyer confirming decree 1063 of 2014 (emergency treatment
free for the first 48 hours). What is held here:

* off unless the hospital switches it on;
* on, a child the triage called non-urgent waits for the desk before a
  treatment is given or a bedside study done — the doctor still writes;
* an urgent child, or one nobody has triaged yet, never waits;
* the desk lifts it («paid, go ahead»), and triaging the child urgent lifts
  it for the doctor with no one's leave; the waiting chips say so;
* the urgent attendances and their first 48 hours are listed for claiming.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    from app.models import Patient, Setting, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:emergency", "1")
        row = util.arrive(db.session.get(Patient, clinic["ids"]["child"]),
                          at=datetime.utcnow() - timedelta(minutes=20))
        db.session.flush()
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        order = eo.write(row, doctor, name="باراسيتامول شراب")
        test = eo.order_test(row, doctor, name="رسم قلب", kind="diagnostic")
        db.session.commit()
        clinic["ids"].update(attendance=row.id, order=order.id, test=test.id)
    return clinic


def _triage(c, urgent):
    from app.models import EmergencyVisit
    from app.utils import emergency as util

    with c["app"].app_context():
        row = c["db"].session.get(EmergencyVisit, c["ids"]["attendance"])
        util.triage(row, level="أخضر" if urgent is False else "أحمر", urgent=urgent)
        c["db"].session.commit()


def _switch(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        Setting.set("er_pay_first", "1" if on else "0")
        c["db"].session.commit()


def _given(c):
    from app.models import EmergencyOrder

    with c["app"].app_context():
        return c["db"].session.get(EmergencyOrder, c["ids"]["order"]).given_at is not None


def _give(c, who="boss"):
    c["sign_in"](who).post(f"/emergency/order/{c['ids']['order']}/give")


def test_off_unless_the_hospital_switches_it_on(er):
    _triage(er, urgent=False)
    _give(er)
    assert _given(er), "a hospital that never asked for it held a child"


def test_a_child_triaged_non_urgent_waits_for_the_desk(er):
    from app.models import VisitInvestigation

    _switch(er)
    _triage(er, urgent=False)
    boss = er["sign_in"]("boss")
    page = boss.get(f"/emergency/attendance/{er['ids']['attendance']}").get_data(as_text=True)
    assert "data-pay-waits" in page and "data-pay-clear" in page
    _give(er)
    assert not _given(er)
    boss.post(f"/emergency/attendance/{er['ids']['attendance']}/test/{er['ids']['test']}/done")
    with er["app"].app_context():
        assert er["db"].session.get(VisitInvestigation, er["ids"]["test"]).performed_at is None
    from app.models import EmergencyVisit
    from app.utils import waiting_on

    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, er["ids"]["attendance"])
        assert waiting_on.for_attendances([row])[row.id]["top"]["kind"] == "payment"

    boss.post(f"/emergency/attendance/{er['ids']['attendance']}/paid")
    _give(er)
    assert _given(er)


@pytest.mark.parametrize("urgent", [True, None])
def test_an_urgent_or_untriaged_child_never_waits(er, urgent):
    _switch(er)
    if urgent is not None:
        _triage(er, urgent=True)
    _give(er)
    assert _given(er)


def test_triaged_urgent_lifts_it_at_once(er):
    _switch(er)
    _triage(er, urgent=False)
    _give(er)
    assert not _given(er)
    _triage(er, urgent=True)
    _give(er)
    assert _given(er)


def test_only_whoever_takes_money_says_paid(er):
    from app.models import EmergencyVisit

    _switch(er)
    _triage(er, urgent=False)
    er["sign_in"]("doc").post(f"/emergency/attendance/{er['ids']['attendance']}/paid")
    with er["app"].app_context():
        assert er["db"].session.get(EmergencyVisit, er["ids"]["attendance"]).pay_cleared_at is None


def test_the_urgent_cases_are_listed_for_their_first_48_hours(er):
    _triage(er, urgent=True)
    boss = er["sign_in"]("boss")
    page = boss.get("/emergency/free-48h").get_data(as_text=True)
    assert f'data-free-row="{er["ids"]["attendance"]}"' in page
    assert "data-to-free-48h" in boss.get("/emergency/register").get_data(as_text=True)
    _triage(er, urgent=False)
    page = boss.get("/emergency/free-48h").get_data(as_text=True)
    assert "data-free-row" not in page
