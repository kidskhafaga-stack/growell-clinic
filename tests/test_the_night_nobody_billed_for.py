"""The resident who covered the night, and the money with no invoice behind it.

**Every figure this program could produce was a share of something a family
paid.** A line on an invoice, a fee on a dose. That answers the doctor who
does the consultation and nobody else — and it cannot answer the resident who
sits in the department from ten at night until eight in the morning and bills
no one, because a shift has no invoice. There is no patient whose bill it is a
share of, and inventing one would put "night cover" on some child's account.

Said in one line: *"الطبيب المقيم بيتحاسب بالشيفتات"*.

**And it is not a hospital feature.** *"موضوع الشيفتات بتاع الأطباء المقيمين
موجود وليهم حسابات في العيادات الخارجية — في الشيفتات الليلية"*. So the
department is optional and the rota is nobody's corner of ``beds``: a clinic
with no wards and one resident covering the night is the ordinary case. This
codebase has built a feature with no door in front of it enough times to test
for it on purpose.

**Rostered is not worked.** A name in a square on a wall chart is a plan, and
paying for a plan is paying for nothing. A duty is created worth zero and
becomes payable only when somebody says it happened — and a past duty nobody
has spoken for stays visible and unpaid rather than being quietly settled.
The program cannot see the corridor at three in the morning; what it can do is
refuse to guess.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def rota(clinic):
    """A clinic that runs a rota: three shifts, a resident, no departments.

    **No departments on purpose.** The whole claim is that a clinic with no
    beds can roster a night, and a fixture with a ward in it would pass
    whether or not that were true.
    """
    from app.extensions import db
    from app.models import Setting, User
    from app.models.duty import DutySlot

    with clinic["app"].app_context():
        Setting.set("mod_enabled:duty", "1")

        resident = User(username="res", full_name="د. مقيم", role="doctor",
                        is_active=True)
        resident.set_password("secret")
        db.session.add(resident)

        morning = DutySlot(name="صباحي", start_time=time(8, 0),
                           end_time=time(15, 0), rate=500, sort_order=1)
        evening = DutySlot(name="مسائي", start_time=time(15, 0),
                           end_time=time(22, 0), rate=500, sort_order=2)
        night = DutySlot(name="ليلي", start_time=time(22, 0),
                         end_time=time(8, 0), rate=700, sort_order=3)
        db.session.add_all([morning, evening, night])
        db.session.commit()

        clinic["resident"] = resident.id
        clinic["morning"] = morning.id
        clinic["evening"] = evening.id
        clinic["night"] = night.id
    return clinic


def _put_on(rota_fx, slot_key, on_date=None, doctor=None, status=None):
    """Roster one duty straight through the utility, and return its id."""
    from app.extensions import db
    from app.models import User
    from app.models.duty import DutySlot
    from app.utils import duty
    from app.utils.clock import local_today

    with rota_fx["app"].app_context():
        who = db.session.get(User, doctor or rota_fx["resident"])
        slot = db.session.get(DutySlot, rota_fx[slot_key])
        row = duty.assign(who, slot, on_date or local_today(), user=who)
        if status:
            row.status = status
        db.session.commit()
        return row.id


def _earned(rota_fx, doctor_id=None):
    from app.utils import doctor_work

    with rota_fx["app"].app_context():
        return doctor_work.earned_ever(doctor_id or rota_fx["resident"])


# ------------------------------------------------------- rostered vs worked

def test_a_rostered_night_is_worth_nothing(rota):
    """The bug this prevents: a wall chart that pays itself."""
    _put_on(rota, "night")
    assert _earned(rota) == 0.0


def test_saying_it_happened_is_what_makes_it_pay(rota):
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
    assert _earned(rota) == 700.0


def test_a_night_that_did_not_happen_pays_nothing_and_keeps_its_row(rota):
    """Absent is recorded, not deleted. "Nobody came" is a fact somebody may
    need in a month, and a deleted row answers nothing."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.mark_absent(db.session.get(Duty, duty_id), note="مرض")
        db.session.commit()
        assert db.session.get(Duty, duty_id).status == "absent"
    assert _earned(rota) == 0.0


def test_a_duty_says_what_it_is_worth_on_its_own(rota):
    """Asked of the row itself, not through a query that has already filtered.

    Found by breaking it: ``earned`` and ``by_slot`` both narrow to worked
    duties in SQL before ``pay`` is ever read, so ``pay`` could hand back the
    full amount for a rostered night and every test still passed. The property
    is public and the next screen to use it would have been the one that paid
    for a plan.
    """
    from app.extensions import db
    from app.models.duty import Duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        row = db.session.get(Duty, duty_id)
        assert row.status == "rostered"
        assert row.is_payable is False
        assert row.pay == 0.0


def test_a_duty_that_did_not_happen_is_worth_nothing_on_its_own(rota):
    """The other half, and the one that matters more: "absent" is not simply
    "not rostered". A check written as ``status != "rostered"`` reads as
    correct and pays every no-show."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        row = db.session.get(Duty, duty_id)
        duty.mark_absent(row)
        db.session.commit()
        assert row.is_payable is False
        assert row.pay == 0.0


def test_a_worked_duty_is_worth_its_amount_on_its_own(rota):
    """And the guard above must not pass by making everything worth zero."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        row = db.session.get(Duty, duty_id)
        duty.confirm(row)
        db.session.commit()
        assert row.is_payable is True
        assert row.pay == 700.0


def test_a_past_duty_nobody_spoke_for_is_listed(rota):
    """The visible gap. Left alone it becomes a month-end guess."""
    from app.utils import duty
    from app.utils.clock import local_today

    _put_on(rota, "night", on_date=local_today() - timedelta(days=3))
    with rota["app"].app_context():
        assert len(duty.unconfirmed()) == 1


def test_tonights_duty_is_not_a_gap_yet(rota):
    """Today's rostered night is not late — it has not happened yet."""
    from app.utils import duty

    _put_on(rota, "night")
    with rota["app"].app_context():
        assert duty.unconfirmed() == []


# -------------------------------------------------------------- the counting

def test_the_same_person_cannot_be_put_on_one_shift_twice(rota):
    """A rota screen somebody clicks twice must not pay twice — the rule the
    bed nights keep, kept by the database rather than by a screen."""
    from app.extensions import db
    from app.models import User
    from app.models.duty import DutySlot
    from app.utils import duty
    from app.utils.clock import local_today
    from sqlalchemy.exc import IntegrityError

    _put_on(rota, "night")
    with rota["app"].app_context():
        who = db.session.get(User, rota["resident"])
        slot = db.session.get(DutySlot, rota["night"])
        duty.assign(who, slot, local_today(), user=who)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_two_different_shifts_on_one_day_are_two_duties(rota):
    """A long day is a real thing; only the same shift twice is the mistake."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty

    for key in ("morning", "evening"):
        duty_id = _put_on(rota, key)
        with rota["app"].app_context():
            duty.confirm(db.session.get(Duty, duty_id))
            db.session.commit()
    assert _earned(rota) == 1000.0


def test_the_shifts_are_counted_by_kind(rota):
    """"Eleven nights and four evenings" is the sentence a doctor checks their
    pay against, so the rows are grouped the way they are paid."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import duty
    from app.utils.clock import local_today

    today = local_today()
    for i, key in enumerate(("night", "night", "morning")):
        duty_id = _put_on(rota, key, on_date=today - timedelta(days=i))
        with rota["app"].app_context():
            duty.confirm(db.session.get(Duty, duty_id))
            db.session.commit()

    with rota["app"].app_context():
        rows = duty.by_slot(rota["resident"], today - timedelta(days=7), today)
    assert [(r["label"], r["count"], r["share"]) for r in rows] == [
        ("ليلي", 2, 1400.0), ("صباحي", 1, 500.0)]


def test_a_rostered_night_is_not_in_the_money_list(rota):
    """Showing it would tell a doctor they earned something they have not."""
    from app.utils import duty
    from app.utils.clock import local_today

    _put_on(rota, "night")
    with rota["app"].app_context():
        assert duty.by_slot(rota["resident"], local_today(),
                            local_today()) == []


# ------------------------------------------------------------------ the rate

def test_the_rate_is_snapshotted_when_the_duty_is_written(rota):
    """A rate edited in March must not rewrite February — the rule the bed
    charges already keep."""
    from app.extensions import db
    from app.models.duty import Duty, DutySlot

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        db.session.get(DutySlot, rota["night"]).rate = 999
        db.session.commit()
        assert db.session.get(Duty, duty_id).amount == 700.0


def test_a_doctor_may_have_their_own_figure_for_a_shift(rota):
    """The same fallback the consultation commissions have, because it is the
    same question asked about a different kind of work."""
    from app.extensions import db
    from app.models import User
    from app.models.duty import Duty, DutyRate, DutySlot
    from app.utils import duty

    with rota["app"].app_context():
        db.session.add(DutyRate(doctor_id=rota["resident"],
                                slot_id=rota["night"], amount=850))
        db.session.commit()

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
    assert _earned(rota) == 850.0


def test_another_doctor_still_gets_the_shifts_own_rate(rota):
    """An override is one person's, and a rate that leaked would overpay a
    whole department from a single agreement."""
    from app.extensions import db
    from app.models.duty import Duty, DutyRate
    from app.utils import duty

    with rota["app"].app_context():
        db.session.add(DutyRate(doctor_id=rota["resident"],
                                slot_id=rota["night"], amount=850))
        db.session.commit()

    duty_id = _put_on(rota, "night", doctor=rota["ids"]["doctor"])
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
    assert _earned(rota, rota["ids"]["doctor"]) == 700.0


def test_a_shift_with_no_rate_pays_nothing_rather_than_guessing(rota):
    """No rate is "not decided yet", not "free" — and the screen says so
    instead of the program inventing a number."""
    from app.extensions import db
    from app.models.duty import Duty, DutySlot
    from app.utils import duty

    with rota["app"].app_context():
        db.session.get(DutySlot, rota["night"]).rate = None
        db.session.commit()

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
        assert db.session.get(Duty, duty_id).amount is None
    assert _earned(rota) == 0.0


def test_a_night_shift_is_known_to_cross_midnight(rota):
    """Ten at night to eight in the morning. Read off the hours, not stored as
    a flag somebody can set to disagree with the times beside it."""
    from app.extensions import db
    from app.models.duty import DutySlot

    with rota["app"].app_context():
        assert db.session.get(DutySlot, rota["night"]).crosses_midnight
        assert not db.session.get(DutySlot, rota["morning"]).crosses_midnight


# ------------------------------------------------------ the door to the money

def test_the_cover_reaches_the_doctors_own_screen(rota):
    """The failure this catches is the one this codebase keeps repeating: the
    fact recorded correctly, and nothing reading it."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import doctor_work, duty
    from app.utils.clock import local_today

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
        rows, share, _ = doctor_work.by_service(
            rota["resident"], local_today(), local_today())
    assert share == 700.0
    assert any(r["label"] == "ليلي" and r["share"] == 700.0 for r in rows)


def test_cover_is_its_own_row_and_bills_nobody(rota):
    """A shift has no price to a patient, so there is no gross to show. A
    column headed "billed" carrying the doctor's own pay reads as revenue."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import doctor_work, duty
    from app.utils.clock import local_today

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
        rows, _, invoices = doctor_work.by_service(
            rota["resident"], local_today(), local_today())
    assert invoices == []
    assert [r["gross"] for r in rows if r["label"] == "ليلي"] == [0.0]


def test_the_balance_counts_it_too(rota):
    """Earned minus paid. A resident on eleven nights was shown a balance of
    zero before this."""
    from app.extensions import db
    from app.models.duty import Duty
    from app.utils import doctor_work, duty

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        duty.confirm(db.session.get(Duty, duty_id))
        db.session.commit()
        assert doctor_work.account(rota["resident"])["earned"] == 700.0


# --------------------------------------------------------------- the screens

def test_the_rota_is_reachable(rota):
    page = rota["sign_in"]("boss").get("/duty/")
    assert page.status_code == 200
    assert "ليلي" in page.get_data(as_text=True)


def test_it_is_in_the_sidebar(rota):
    """A screen nothing links to is a screen nobody opens."""
    page = rota["sign_in"]("boss").get("/duty/").get_data(as_text=True)
    assert 'href="/duty/"' in page


def test_a_clinic_that_does_not_roster_gets_a_404(rota):
    """Off is absent, not an empty screen — the rule every opt-in module here
    keeps."""
    from app.extensions import db
    from app.models import Setting

    with rota["app"].app_context():
        Setting.set("mod_enabled:duty", "0")
        db.session.commit()
    assert rota["sign_in"]("boss").get("/duty/").status_code == 404


def test_the_rota_does_not_need_a_department(rota):
    """The clinic in this fixture has no units at all, and rostering a night
    still works. This is the whole reason the module is not behind ``beds``."""
    page = rota["sign_in"]("boss").post(
        "/duty/assign",
        data={"doctor_id": rota["resident"], "slot_id": rota["night"],
              "on_date": date.today().isoformat()},
        follow_redirects=True)
    assert page.status_code == 200

    from app.models.duty import Duty

    with rota["app"].app_context():
        row = Duty.query.filter_by(doctor_id=rota["resident"]).first()
        assert row is not None and row.unit_id is None


def test_a_doctor_cannot_set_what_a_night_pays(rota):
    """What a night is worth is the clinic's money, and the person working it
    is not the person who decides that."""
    assert rota["sign_in"]("doc").get("/duty/slots").status_code == 403


def test_a_doctor_can_still_read_who_is_on(rota):
    """"Who is with me tonight" is the question the rota exists to answer, and
    it is not a money question."""
    assert rota["sign_in"]("doc").get("/duty/").status_code == 200


def test_the_desk_has_no_business_here(rota):
    """403 and not 404: the module is on in this clinic, it is simply not
    reception's. The two answers mean different things and the distinction is
    what tells an admin whether to switch something on or to fix a role."""
    assert rota["sign_in"]("desk").get("/duty/").status_code == 403


def test_rostering_the_same_shift_twice_says_so_instead_of_breaking(rota):
    """The unique constraint is the guard; the screen has to survive it."""
    data = {"doctor_id": rota["resident"], "slot_id": rota["night"],
            "on_date": date.today().isoformat()}
    client = rota["sign_in"]("boss")
    client.post("/duty/assign", data=data, follow_redirects=True)
    second = client.post("/duty/assign", data=data, follow_redirects=True)
    assert second.status_code == 200

    from app.models.duty import Duty

    with rota["app"].app_context():
        assert Duty.query.count() == 1


def test_a_shift_is_added_from_the_screen_not_from_a_release(rota):
    """The hours differ between departments and countries, and Ramadan moves
    them. A clinic that runs two shifts must not be told it has three."""
    client = rota["sign_in"]("boss")
    client.post("/duty/slots/add",
                data={"name": "طوارئ ١٢ ساعة", "start_time": "20:00",
                      "end_time": "08:00", "rate": "900"},
                follow_redirects=True)

    from app.models.duty import DutySlot

    with rota["app"].app_context():
        added = DutySlot.query.filter_by(name="طوارئ ١٢ ساعة").first()
        assert added is not None and added.rate == 900
        assert added.crosses_midnight


def test_a_shift_with_no_hours_is_refused(rota):
    from app.models.duty import DutySlot

    rota["sign_in"]("boss").post("/duty/slots/add", data={"name": "بلا ساعات"},
                                 follow_redirects=True)
    with rota["app"].app_context():
        assert DutySlot.query.filter_by(name="بلا ساعات").first() is None


def test_clearing_a_doctors_own_rate_goes_back_to_the_shifts(rota):
    """An empty box means "use the shift's rate", not "works for nothing" — a
    clinic correcting a mistake must not have to delete the person."""
    from app.extensions import db
    from app.models.duty import DutyRate

    client = rota["sign_in"]("boss")
    client.post(f"/duty/slots/{rota['night']}/rate",
                data={"doctor_id": rota["resident"], "amount": "850"},
                follow_redirects=True)
    client.post(f"/duty/slots/{rota['night']}/rate",
                data={"doctor_id": rota["resident"], "amount": ""},
                follow_redirects=True)
    with rota["app"].app_context():
        assert DutyRate.query.filter_by(doctor_id=rota["resident"]).count() == 0

    duty_id = _put_on(rota, "night")
    with rota["app"].app_context():
        from app.models.duty import Duty

        assert db.session.get(Duty, duty_id).amount == 700.0


def test_the_week_starts_on_saturday(rota):
    """The Egyptian working week, and the one the booking calendar already
    uses — a rota and a calendar that start their weeks on different days is
    a fortnight of confusion."""
    from app.utils import duty

    with rota["app"].app_context():
        # 2026-09-09 is a Wednesday.
        start, end = duty.week_of(date(2026, 9, 9))
    assert start == date(2026, 9, 5) and start.weekday() == 5
    assert end == date(2026, 9, 11)
