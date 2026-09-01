"""How long the family waited, how long the doctor took, and who is in which عيادة.

Three separate things are pinned here, and each one exists because the
straightforward version of it is wrong in a way that only shows up in a clinic
with more than one doctor in it.

**The stamps have to happen by themselves.** ``Appointment.started_at`` was in
the schema for a long time and was almost always empty: the only thing that
set it was a status button on the board that nobody in a running clinic stops
to press. A timing report over a column nobody fills is not a small
inaccuracy, it is a screen of confident numbers about nothing.

**"The current patient" is not a question with one answer.** With ten doctors
working there are ten current patients, and the board used to answer with
``next(...)`` — the first row that happened to say ``in_progress`` — under a
heading reading "المريض الحالي".

**The counter has to survive the timezone.** Times are stored with
``datetime.utcnow()``, which carries no marker. Handed to a browser as-is it
reads as local time, and every counter in a clinic on UTC+3 runs three hours
high — which looks like a broken counter rather than a broken timestamp.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# One clock. The program books, bills and lists "today" with
# ``local_today``; a test that builds or asserts with ``date.today``
# sits on a different day whenever the server's zone and the clinic's
# disagree — on a UTC server and a Cairo clinic, every night after
# 22:00. These twenty failed on the hour rather than on a change.
from app.utils.clock import local_today  # noqa: E402


def _midday(days_ago=0):
    """A fixed hour of the day, ``days_ago`` days back.

    Not ``utcnow()``. A consultation that starts before midnight and ends
    after it is deliberately *not* counted — a visit that crossed into another
    day is not evidence about how long consultations take — so a test that
    anchors its stamps to the current moment quietly fails for the half hour
    before midnight UTC and passes every other hour of the day. It did, on a
    run at 23:33.
    """
    return datetime.combine(local_today() - timedelta(days=days_ago),
                            time(10, 0))


def _appt(db, clinic_ids, doctor_id=None, status="waiting", **kw):
    from app.models import Appointment

    kw.setdefault("appt_time", time(10, 0))
    appt = Appointment(patient_id=clinic_ids["child"],
                       doctor_id=doctor_id or clinic_ids["doctor"],
                       appt_date=local_today(),
                       duration_minutes=15, status=status, **kw)
    db.session.add(appt)
    db.session.flush()
    return appt


# ======================================================= the stamps =========
def test_the_doctor_opening_the_record_starts_the_clock(clinic):
    """The fix for the empty column.

    Opening the record is the doctor's own action at the moment the
    consultation really begins — unlike a status button, it cannot be
    forgotten, because it is the thing they came to the screen to do.
    """
    from app.models import Appointment, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"])
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.appointment_id = appt.id
        db.session.commit()
        appt_id, visit_id = appt.id, visit.id
        assert db.session.get(Appointment, appt_id).started_at is None

    clinic["sign_in"]("doc").get(f"/visits/{visit_id}/record")

    with clinic["app"].app_context():
        appt = db.session.get(Appointment, appt_id)
        assert appt.started_at is not None
        assert appt.status == "in_progress"


def test_somebody_else_opening_the_file_does_not_start_the_clock(clinic):
    """The admin looks a child up mid-morning to answer a phone call.

    That is not the start of a consultation, and if it stamped one, the
    doctor's day would show a consultation that began at whatever moment the
    front desk was curious — and ran until they closed the record.
    """
    from app.models import Appointment, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"])
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.appointment_id = appt.id
        db.session.commit()
        appt_id, visit_id = appt.id, visit.id

    clinic["sign_in"]("boss").get(f"/visits/{visit_id}/record")

    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).started_at is None


def test_the_clock_starts_once_however_often_the_screen_is_opened(clinic):
    """A doctor opens and closes the record several times in one consultation
    — to write, to check a result, to come back after a phone call. The first
    time is the one that means anything."""
    from app.models import Appointment, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"])
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.appointment_id = appt.id
        db.session.commit()
        appt_id, visit_id = appt.id, visit.id

    client = clinic["sign_in"]("doc")
    client.get(f"/visits/{visit_id}/record")
    with clinic["app"].app_context():
        first = db.session.get(Appointment, appt_id).started_at
    client.get(f"/visits/{visit_id}/record")

    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).started_at == first


def test_reopening_a_finished_appointment_does_not_restart_it(clinic):
    """A record opened next week to fix a typo must not be dragged into today
    as a live consultation — nor should it wipe the time it really took."""
    from app.models import Appointment, Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        started = datetime.utcnow() - timedelta(days=7)
        appt = _appt(db, clinic["ids"], status="completed",
                     started_at=started,
                     completed_at=started + timedelta(minutes=12))
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.appointment_id = appt.id
        db.session.commit()
        appt_id, visit_id = appt.id, visit.id

    clinic["sign_in"]("doc").get(f"/visits/{visit_id}/record")

    with clinic["app"].app_context():
        appt = db.session.get(Appointment, appt_id)
        assert appt.status == "completed"
        assert appt.started_at == started


def test_the_nurse_station_stamps_when_the_vitals_were_done(clinic):
    """Without this moment the wait is one number covering two queues — the
    one at reception and the one at the doctor's door — and the clinic cannot
    tell which of them is slow."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"])
        db.session.commit()
        appt_id = appt.id

    clinic["sign_in"]("doc").post(f"/visits/station/{appt_id}/vitals",
                                  data={"weight_kg": "9.4", "height_cm": "72"},
                                  follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).vitals_at is not None


def test_correcting_a_weight_is_not_a_second_trip_to_the_station(clinic):
    """The nurse re-saves to fix a typed weight. The child did not walk back
    out and queue again, so the moment must not move."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"])
        db.session.commit()
        appt_id = appt.id

    client = clinic["sign_in"]("doc")
    client.post(f"/visits/station/{appt_id}/vitals", data={"weight_kg": "9.4"},
                follow_redirects=True)
    with clinic["app"].app_context():
        first = db.session.get(Appointment, appt_id).vitals_at
    client.post(f"/visits/station/{appt_id}/vitals", data={"weight_kg": "9.6"},
                follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(Appointment, appt_id).vitals_at == first


# ======================================================= the arithmetic =====
def test_the_two_waits_are_reported_apart(clinic):
    """Reception's queue and the doctor's queue have different causes and
    different fixes, so a single "wait: 40 minutes" is not actionable."""
    from app.utils.waiting import intervals

    db = clinic["db"]
    with clinic["app"].app_context():
        base = datetime(2026, 8, 8, 9, 0)
        appt = _appt(db, clinic["ids"], checked_in_at=base,
                     vitals_at=base + timedelta(minutes=10),
                     started_at=base + timedelta(minutes=45),
                     completed_at=base + timedelta(minutes=60))
        db.session.commit()

        spans = intervals(appt)
        assert spans["to_vitals"] == 10
        assert spans["after_vitals"] == 35
        assert spans["wait"] == 45
        assert spans["consult"] == 15
        assert spans["total"] == 60


def test_a_missing_stamp_reads_as_unknown_not_as_zero(clinic):
    """A clinic that never recorded vitals should see a blank. A confident 0
    would claim the nurse was instantaneous."""
    from app.utils.waiting import intervals

    db = clinic["db"]
    with clinic["app"].app_context():
        appt = _appt(db, clinic["ids"], checked_in_at=datetime(2026, 8, 8, 9, 0))
        db.session.commit()
        assert intervals(appt)["to_vitals"] is None
        assert intervals(appt)["consult"] is None


def test_a_record_left_open_all_day_is_not_a_long_consultation(clinic):
    """It is a forgotten record, and counting it would let one of them move a
    whole month's average."""
    from app.utils.waiting import is_sane, summarise

    db = clinic["db"]
    with clinic["app"].app_context():
        base = datetime(2026, 8, 8, 9, 0)
        real = _appt(db, clinic["ids"], started_at=base,
                     completed_at=base + timedelta(minutes=14))
        forgotten = _appt(db, clinic["ids"], started_at=base,
                          completed_at=base + timedelta(hours=7))
        db.session.commit()

        assert is_sane(real) and not is_sane(forgotten)
        summary = summarise([real, forgotten])
        assert summary["consult"] == 14        # the 7 hours did not drag it
        assert summary["forgotten"] == 1       # but it is still reported


def test_a_doctor_with_two_records_open_is_flagged_not_hidden(clinic):
    """Interrupted mid-consultation, a doctor opens a second child's record.

    The wall clock then charges the first child with the interruption. Rather
    than inventing a pause button whose records nobody would trust, the
    overlap is reported, so a summary can say the average is soft instead of
    quietly being wrong.
    """
    from app.utils.waiting import overlaps

    db = clinic["db"]
    with clinic["app"].app_context():
        base = datetime(2026, 8, 8, 9, 0)
        first = _appt(db, clinic["ids"], started_at=base,
                      completed_at=base + timedelta(minutes=30))
        second = _appt(db, clinic["ids"], started_at=base + timedelta(minutes=10),
                       completed_at=base + timedelta(minutes=20))
        apart = _appt(db, clinic["ids"], started_at=base + timedelta(hours=2),
                      completed_at=base + timedelta(hours=2, minutes=10))
        db.session.commit()

        flagged = overlaps([first, second, apart])
        assert flagged == {first.id, second.id}


def test_two_doctors_at_once_is_not_an_overlap(clinic):
    """The whole point of the clinic running two عيادات is that both are busy
    at the same time. Only one doctor holding two records is a problem."""
    from app.utils.waiting import overlaps

    db = clinic["db"]
    with clinic["app"].app_context():
        base = datetime(2026, 8, 8, 9, 0)
        mine = _appt(db, clinic["ids"], started_at=base,
                     completed_at=base + timedelta(minutes=20))
        theirs = _appt(db, clinic["ids"], doctor_id=clinic["ids"]["admin"],
                       started_at=base, completed_at=base + timedelta(minutes=20))
        db.session.commit()

        assert overlaps([mine, theirs]) == set()


def test_running_over_the_booked_slot_is_the_fair_measure(clinic):
    """The clinic chose the slot; running past it is what pushes the next
    family back. That is a question about the doctor. "Was the consultation
    short" is not."""
    from app.utils.waiting import over_slot

    db = clinic["db"]
    with clinic["app"].app_context():
        base = datetime(2026, 8, 8, 9, 0)
        over = _appt(db, clinic["ids"], started_at=base,
                     completed_at=base + timedelta(minutes=25))
        under = _appt(db, clinic["ids"], started_at=base,
                      completed_at=base + timedelta(minutes=10))
        db.session.commit()

        assert over_slot(over) == 10        # 25 in a 15-minute slot
        assert over_slot(under) == -5


# ======================================================= the board ==========
def test_the_clinic_view_shows_every_doctor_not_one_at_random(clinic):
    """The bug this replaces.

    Two doctors examining, and the board picked whichever ``in_progress`` row
    came back first and captioned it "المريض الحالي". Reception read a heading
    about a patient who was not theirs and not the one they asked about.
    """
    from app.blueprints.appointments.routes import _clinics_now

    db = clinic["db"]
    with clinic["app"].app_context():
        mine = _appt(db, clinic["ids"], status="in_progress",
                     started_at=datetime.utcnow())
        theirs = _appt(db, clinic["ids"], doctor_id=clinic["ids"]["admin"],
                       status="in_progress", started_at=datetime.utcnow())
        db.session.commit()

        cards = _clinics_now([mine, theirs], local_today())
        assert len(cards) == 2
        assert {c["current"].id for c in cards} == {mine.id, theirs.id}


def test_the_card_says_how_long_the_worst_wait_has_run(clinic):
    """The number nobody has today. Reception learns that one family has been
    sitting for fifty minutes *before* the father gets up to complain."""
    from app.blueprints.appointments.routes import _clinics_now

    db = clinic["db"]
    with clinic["app"].app_context():
        now = datetime.utcnow()
        early = _appt(db, clinic["ids"],
                      checked_in_at=now - timedelta(minutes=50))
        _appt(db, clinic["ids"], checked_in_at=now - timedelta(minutes=5))
        db.session.commit()

        card = _clinics_now(db.session.query(type(early)).all(), local_today())[0]
        assert card["waiting"] == 2
        # The moment, not a number of minutes — so the counter on screen keeps
        # ticking instead of freezing at whatever it said when the page drew.
        assert card["longest_since"] == early.checked_in_at


def test_a_doctors_own_board_keeps_the_big_card(clinic):
    """The per-عيادة strip answers reception's question. A doctor looking at
    their own board still wants the child in front of them, in full."""
    from app.models import Appointment

    db = clinic["db"]
    with clinic["app"].app_context():
        _appt(db, clinic["ids"], status="in_progress",
              started_at=datetime.utcnow())
        db.session.commit()
        doctor_id = clinic["ids"]["doctor"]

    page = clinic["sign_in"]("doc").get("/appointments/").data.decode()
    assert "current-card" in page
    assert "clinics-strip" not in page

    page = clinic["sign_in"]("boss").get(
        f"/appointments/?doctor_id={doctor_id}").data.decode()
    assert "current-card" in page

    with clinic["app"].app_context():
        assert Appointment.query.count() == 1


def test_the_whole_clinic_view_gets_the_strip(clinic):
    from app.models import Appointment  # noqa: F401  (context for the route)

    db = clinic["db"]
    with clinic["app"].app_context():
        _appt(db, clinic["ids"], status="in_progress",
              started_at=datetime.utcnow())
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/appointments/").data.decode()
    assert "clinics-strip" in page


# ======================================================= the counter ========
def test_the_counter_is_handed_a_time_marked_as_utc(clinic):
    """The trap that would have made every counter read hours high.

    ``datetime.utcnow()`` carries no timezone marker. Printed into the page
    without one, the browser parses it as local time, and a clinic on UTC+3
    sees every wait inflated by three hours — which reads as a broken counter,
    not as a broken timestamp, so it would have been debugged in the wrong
    file.
    """
    db = clinic["db"]
    with clinic["app"].app_context():
        _appt(db, clinic["ids"],
              checked_in_at=datetime.utcnow() - timedelta(minutes=30))
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/appointments/").data.decode()
    marker = page.split('data-since="')[1].split('"')[0]
    assert marker.endswith("Z"), f"not marked as UTC: {marker}"


def test_only_a_waiting_family_can_turn_the_counter_red(clinic):
    """A counter going red in a doctor's face while they examine a sick child
    is pressure to hurry, and hurrying is not what this feature is for. The
    colour thresholds are reachable only through the 'wait' tone."""
    source = open(os.path.join(os.path.dirname(__file__), "..",
                               "app", "static", "js", "app.js"),
                  encoding="utf-8").read()
    block = source.split("live timers")[1]
    red = block.index("lt-red")
    tone = block.index("dataset.tone === 'wait'")
    assert tone < red, "the red class is applied outside the wait-tone guard"


# ======================================================= the عيادات =========
def test_a_doctor_can_be_in_a_different_clinic_tomorrow(clinic):
    """The reason the assignment is a row per day and not a column on the
    doctor: a column holds only today's answer, and silently rewrites every
    day before it."""
    from app.models import ClinicRoom, RoomAssignment

    db = clinic["db"]
    with clinic["app"].app_context():
        one = ClinicRoom(code=1)
        two = ClinicRoom(code=2)
        db.session.add_all([one, two])
        db.session.flush()
        today = local_today()
        db.session.add(RoomAssignment(on_date=today - timedelta(days=1),
                                      doctor_id=clinic["ids"]["doctor"],
                                      room_id=one.id))
        db.session.add(RoomAssignment(on_date=today,
                                      doctor_id=clinic["ids"]["doctor"],
                                      room_id=two.id))
        db.session.commit()

        from app.utils.clinic_now import _rooms_on
        assert _rooms_on(today - timedelta(days=1))[clinic["ids"]["doctor"]].code == 1
        assert _rooms_on(today)[clinic["ids"]["doctor"]].code == 2


def test_a_clinic_with_history_is_switched_off_rather_than_deleted(clinic):
    """Deleting it would take its assignments with it, and "who was in عيادة ٢
    that Tuesday" would quietly stop having an answer."""
    from app.models import ClinicRoom, RoomAssignment

    db = clinic["db"]
    with clinic["app"].app_context():
        room = ClinicRoom(code=1)
        db.session.add(room)
        db.session.flush()
        db.session.add(RoomAssignment(on_date=local_today(),
                                      doctor_id=clinic["ids"]["doctor"],
                                      room_id=room.id))
        db.session.commit()
        room_id = room.id

    clinic["sign_in"]("boss").post(f"/appointments/clinics/{room_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        room = db.session.get(ClinicRoom, room_id)
        assert room is not None and room.is_active is False
        assert RoomAssignment.query.count() == 1


def test_an_unused_clinic_really_is_deleted(clinic):
    """The other half — otherwise a typo made on Tuesday is on the list
    forever, greyed out, with nothing to explain it."""
    from app.models import ClinicRoom

    db = clinic["db"]
    with clinic["app"].app_context():
        room = ClinicRoom(code=9)
        db.session.add(room)
        db.session.commit()
        room_id = room.id

    clinic["sign_in"]("boss").post(f"/appointments/clinics/{room_id}/delete",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert db.session.get(ClinicRoom, room_id) is None


def test_the_clinic_number_is_generated_not_typed(clinic):
    """The clinic's own rule for everything the program creates."""
    from app.models import ClinicRoom

    db = clinic["db"]
    client = clinic["sign_in"]("boss")
    client.post("/appointments/clinics/add", data={"name_ar": ""},
                follow_redirects=True)
    client.post("/appointments/clinics/add", data={"name_ar": "الحضّانة"},
                follow_redirects=True)

    with clinic["app"].app_context():
        codes = sorted(r.code for r in ClinicRoom.query.all())
        assert codes == [1, 2]
        named = ClinicRoom.query.filter_by(name_ar="الحضّانة").one()
        assert named.display_name("ar") == "الحضّانة"
        blank = ClinicRoom.query.filter_by(code=1).one()
        assert blank.display_name("ar") == "عيادة 1"


def test_a_deleted_number_is_reused_rather_than_leaving_a_hole(clinic):
    """A clinic that deletes عيادة ٢ and adds one back expects عيادة ٢, not
    عيادة ٧ with no explanation for the gap."""
    from app.models import ClinicRoom

    db = clinic["db"]
    with clinic["app"].app_context():
        db.session.add_all([ClinicRoom(code=1), ClinicRoom(code=3)])
        db.session.commit()
        assert ClinicRoom.next_code() == 2


# ======================================================= the scorecard ======
def test_the_doctors_screen_describes_the_month_without_scoring_it(clinic):
    """The number goes on the screen; the ranking does not.

    A clinic that starts rewarding shorter consultations gets shorter
    consultations, which is the opposite of what a stopwatch was bought for.
    So the screen carries the median *with its spread*, and says in words that
    it is a description — checked here, because a note like that is exactly
    the kind of thing a later redesign drops.
    """
    from app.utils.waiting import doctor_timings

    db = clinic["db"]
    with clinic["app"].app_context():
        base = _midday(1)
        for minutes in (10, 14, 30):
            _appt(db, clinic["ids"], status="completed", started_at=base,
                  completed_at=base + timedelta(minutes=minutes))
        db.session.commit()

        row = doctor_timings(local_today() - timedelta(days=30), local_today())
        row = row[clinic["ids"]["doctor"]]
        assert row["consult"] == 14                 # median, not the mean 18
        assert (row["shortest"], row["longest"]) == (10, 30)
        assert row["over_slot"] == -1               # 14 in a 15-minute slot

    page = clinic["sign_in"]("boss").get("/users/doctors").data.decode()
    assert "14" in page
    from app.i18n import t
    with clinic["app"].test_request_context():
        assert t("doctors.timing_note") in page


def test_the_report_stops_reporting_one_wait_for_two_queues(clinic):
    """A single average spans the front desk and the doctor's door. The fix
    for a slow front desk and the fix for a doctor running late are not the
    same fix, so the sum of them is not something anybody can act on."""
    db = clinic["db"]
    with clinic["app"].app_context():
        base = _midday()
        _appt(db, clinic["ids"], status="completed", checked_in_at=base,
              vitals_at=base + timedelta(minutes=8),
              started_at=base + timedelta(minutes=40),
              completed_at=base + timedelta(minutes=55))
        db.session.commit()

    page = clinic["sign_in"]("boss").get(
        "/reports/operational", follow_redirects=True).data.decode()
    from app.i18n import t
    with clinic["app"].test_request_context():
        assert t("reports.wait_to_vitals") in page
        assert t("reports.wait_after_vitals") in page


# ======================================================= the clinic clock ===
def test_starting_late_is_measured_against_the_clinics_own_clock(clinic):
    """The metric the timezone setting unblocked.

    ``appt_time`` is ten in the morning *in the clinic*; ``started_at`` is
    stored UTC. Subtracting one from the other directly — which is all the
    program could do before there was a timezone — reports a doctor who opened
    exactly on time as two or three hours late.
    """
    from zoneinfo import ZoneInfo

    from app.models import Setting
    from app.utils.waiting import clinic_start

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Africa/Cairo")
        db.session.commit()

        # 10:00 in Cairo, expressed as the UTC moment the program would store.
        # The offset comes from zoneinfo directly and *not* from the app's own
        # converter: deriving it from the code under test would make this pass
        # whether or not the conversion happens at all.
        booked = datetime.combine(local_today(), time(10, 0))
        offset = booked.replace(tzinfo=ZoneInfo("Africa/Cairo")).utcoffset()
        assert offset.total_seconds() != 0, (
            "Cairo is not UTC; if it were, this test could not tell a "
            "converted answer from an unconverted one")
        on_time_utc = booked - offset

        _appt(db, clinic["ids"], status="completed",
              started_at=on_time_utc + timedelta(minutes=12),
              completed_at=on_time_utc + timedelta(minutes=25))
        db.session.commit()

        row = clinic_start(local_today(), local_today())[clinic["ids"]["doctor"]]
        assert row["late"] == 12, "the UTC offset leaked into the answer"
        assert row["days"] == 1


def test_only_the_first_appointment_of_the_day_counts_as_the_start(clinic):
    """Everything after it inherits the delay of everything before it, so
    counting them all would charge a doctor over and over for one late
    opening."""
    from zoneinfo import ZoneInfo

    from app.models import Setting
    from app.utils.waiting import clinic_start

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Africa/Cairo")
        db.session.commit()

        booked = datetime.combine(local_today(), time(9, 0))
        offset = booked.replace(tzinfo=ZoneInfo("Africa/Cairo")).utcoffset()
        opened = booked - offset + timedelta(minutes=20)

        _appt(db, clinic["ids"], appt_time=time(9, 0), started_at=opened,
              completed_at=opened + timedelta(minutes=15))
        # Booked for 09:15, seen at 09:35 — pushed by the late start, not a
        # second offence.
        _appt(db, clinic["ids"], appt_time=time(9, 15),
              started_at=opened + timedelta(minutes=15),
              completed_at=opened + timedelta(minutes=30))
        db.session.commit()

        row = clinic_start(local_today(), local_today())[clinic["ids"]["doctor"]]
        assert row["late"] == 20 and row["days"] == 1


def test_a_machine_that_cannot_resolve_its_zone_reports_nothing(clinic):
    """The whole reason this metric waited.

    A silent fallback to UTC is how the wrong-by-three-hours number would have
    shipped anyway — it would have looked like a working feature. Blank is the
    truth on a Windows box without ``tzdata``.
    """
    from app.models import Setting
    from app.utils.waiting import clinic_start

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Mars/Olympus_Mons")
        db.session.commit()
        base = _midday()
        _appt(db, clinic["ids"], started_at=base,
              completed_at=base + timedelta(minutes=15))
        db.session.commit()

        assert clinic_start(local_today(), local_today()) == {}


def test_the_settings_screen_says_when_the_zone_cannot_be_read(clinic):
    """Blank numbers with no explanation read as a broken screen. The clinic
    is told which package is missing instead of guessing."""
    from app.models import Setting
    from app.i18n import t

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Mars/Olympus_Mons")
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/settings/").data.decode()
    with clinic["app"].test_request_context():
        assert t("settings.timezone_broken") in page


def test_a_real_zone_raises_no_warning(clinic):
    """Guarding the guard — a banner that is always on says nothing."""
    from app.models import Setting
    from app.i18n import t

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Africa/Cairo")
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/settings/").data.decode()
    with clinic["app"].test_request_context():
        assert t("settings.timezone_broken") not in page


def test_the_timezone_survives_being_saved(clinic):
    """It is a plain setting, and plain settings have been silently dropped
    from the form's key list before."""
    from app.models import Setting

    clinic["sign_in"]("boss").post("/settings/",
                                   data={"clinic_timezone": "Asia/Riyadh"},
                                   follow_redirects=True)
    with clinic["app"].app_context():
        assert Setting.get("clinic_timezone") == "Asia/Riyadh"
