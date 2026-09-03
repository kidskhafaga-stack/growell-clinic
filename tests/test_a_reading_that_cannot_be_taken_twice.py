"""One temperature per visit, in a department that measures every fifteen minutes.

The request, in the words it arrived in: *"لازم مديول الطوارئ والحضانة بيقيسوا
vital signs حسب ما الدكتور بيطلب كل ربع ساعة او كل ساعة ولازم تكون مديول ما
يقصرش على العيادات"*.

What made it impossible rather than merely missing is one line in
``app/models/vital_signs.py``:

    visit_id = db.Column(..., unique=True, ...)

A child watched for six hours in emergency had **one** reading on file — the
one taken on arrival. The second one had nowhere to go, and the database, not
a screen, was what refused it. The first test here is that line: it holds the
old behaviour in place, because the fix must not be "loosen the constraint and
let every screen that reads ``visit.vitals`` as one object break".

The rest is the new table, and what a station actually asks of it: not *what
was the last reading* — that a pile of rows can answer — but **who has not
been measured for longer than the doctor asked**, which nothing can answer
without knowing that a reading was due.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

MODULE = "observations"


@pytest.fixture()
def rounds_on(clinic):
    """The module switched on, which it is not by default."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(f"mod_enabled:{MODULE}", "1")
        clinic["db"].session.commit()
    return clinic


# --------------------------------------------------------- the old shape ---
def test_the_clinic_still_keeps_one_set_of_vitals_per_visit():
    """The constraint that made this necessary is still there, deliberately.

    Every screen in the program reads ``visit.vitals`` as an object — the
    record, the print-out, the board, the red-flag assessment. Dropping the
    unique key to make room for repeated readings would have turned it into a
    list under all of them at once.
    """
    from app.models import VitalSigns

    assert VitalSigns.__table__.c.visit_id.unique is True


def test_an_observation_carries_the_same_column_names_as_the_vitals():
    """Named after ``VitalSigns`` on purpose, so the clinical rules apply.

    ``red_flags.assess`` and ``vital_bands.read`` read these attributes off
    whatever they are handed. A table that spelt its temperature ``temp_c``
    would have needed its own thresholds within a week, and a second copy of a
    clinical number is the failure this program keeps a whole file to avoid.
    """
    from app.models import Observation, VitalSigns

    shared = {"temperature_c", "pulse_bpm", "resp_rate", "spo2",
              "bp_systolic", "bp_diastolic", "bp_arm"}
    assert shared <= set(VitalSigns.__table__.c.keys())
    assert shared <= set(Observation.__table__.c.keys())


def test_the_clinical_rules_read_an_observation_without_being_told(clinic):
    """The proof of the naming: the triage assessment judges one unchanged.

    Inside an application context because the thresholds are the *clinic's* —
    ``red_flags.bands()`` reads whatever this clinic set before falling back
    to the paediatric defaults, and a test that bypassed that would be
    checking a constant rather than the rule the screens use.
    """
    from app.models import Observation, Patient
    from app.utils.red_flags import assess

    with clinic["app"].app_context():
        baby = Patient(full_name="رضيع", date_of_birth=datetime.utcnow().date())
        hot = Observation(temperature_c=39.2)
        assert assess(baby, hot, "")["level"] == "urgent"
        cool = Observation(temperature_c=36.8)
        assert assess(baby, cool, "")["level"] is None


# ------------------------------------------------------ what is overdue ----
def test_the_next_reading_is_counted_from_the_last_one_taken():
    from app.models import ObservationOrder, due_at

    started = datetime(2026, 9, 3, 8, 0)
    order = ObservationOrder(every_minutes=15, started_at=started)
    # Nothing taken yet: counted from the order, so the *first* missed reading
    # is visible rather than the second.
    assert due_at(order, None) == started + timedelta(minutes=15)
    # A round taken late moves the next one — "every fifteen minutes", not
    # "at :00 :15 :30 :45".
    late = datetime(2026, 9, 3, 8, 20)
    assert due_at(order, late) == late + timedelta(minutes=15)


def test_a_round_is_due_before_it_is_late():
    from app.models import ObservationOrder
    from app.utils.observations import DUE, LATE, OK, state

    started = datetime(2026, 9, 3, 8, 0)
    order = ObservationOrder(every_minutes=60, started_at=started)

    assert state(order, started, started + timedelta(minutes=30))["level"] == OK
    assert state(order, started, started + timedelta(minutes=61))["level"] == DUE
    # A quarter of an hour past the hour is late for an hourly round.
    assert state(order, started, started + timedelta(minutes=76))["level"] == LATE


def test_lateness_is_measured_against_the_interval_not_a_fixed_number():
    """Three minutes late is late for a quarter-hourly round and nothing at
    all for a four-hourly one, so one fixed grace cannot serve both."""
    from app.models import lateness_grace

    assert lateness_grace(15) < lateness_grace(60)
    # And it stops growing, on purpose: an eight-hourly order that could drift
    # by two hours and still read as punctual would make the board a decoration.
    assert lateness_grace(480) == lateness_grace(240) == 15
    # Never zero, or a round would be late the instant it came due and the
    # board would be red all day.
    assert lateness_grace(15) >= 1


def test_a_stopped_order_stops_asking():
    from app.models import ObservationOrder
    from app.utils.observations import OK, state

    started = datetime(2026, 9, 3, 8, 0)
    order = ObservationOrder(every_minutes=15, started_at=started,
                             stopped_at=datetime(2026, 9, 3, 9, 0))
    verdict = state(order, started, datetime(2026, 9, 3, 18, 0))
    assert verdict["level"] == OK
    assert verdict["due_at"] is None


# ------------------------------------------------------------ the module ---
def test_the_module_is_off_until_a_clinic_asks_for_it(clinic):
    """A single-doctor outpatient clinic must not find a ward screen in its
    sidebar after an upgrade — the same rule as dentistry and the panels."""
    from app.utils.facility import OPT_IN_MODULES

    assert MODULE in OPT_IN_MODULES
    page = clinic["sign_in"]("boss").get("/observations/")
    assert page.status_code == 404


def test_a_clinic_that_says_it_runs_an_emergency_gets_the_rounds(clinic):
    """The wizard, not a second switch to find afterwards.

    A clinic that ticks "emergency" or "incubators" and then cannot record a
    second temperature has been sold a department that does not work. This is
    the same gap that has been found six times in this project under
    different names: the thing is built, and nothing leads to it.
    """
    from app.utils.facility import apply_facility, derive_modules, module_enabled

    for capability in ("emergency_care", "nicu", "icu", "ward", "observation",
                       "day_care"):
        assert MODULE in derive_modules([capability]), capability

    with clinic["app"].app_context():
        assert not module_enabled(MODULE)
        apply_facility("hospital", "مستشفى", ["emergency_care"],
                       derive_modules(["emergency_care"]))
        clinic["db"].session.commit()
        assert module_enabled(MODULE)


def test_a_clinic_that_only_sees_outpatients_does_not_get_them(clinic):
    """The other half, and the one that keeps the promise: a paediatric
    clinic running the wizard must come out of it with no ward screen."""
    from app.utils.facility import apply_facility, derive_modules, module_enabled

    caps = ["general_consultation", "followup", "vaccination"]
    with clinic["app"].app_context():
        apply_facility("single_doctor", "عيادة", caps, derive_modules(caps))
        clinic["db"].session.commit()
        assert not module_enabled(MODULE)


def test_the_board_answers_once_the_module_is_on(rounds_on):
    page = rounds_on["sign_in"]("boss").get("/observations/")
    assert page.status_code == 200


def test_the_nurse_can_reach_it_and_reception_cannot(rounds_on):
    """Whoever holds the thermometer is who this was built for; whoever books
    the appointments has no business in a clinical chart."""
    from app.models.permissions import role_modules

    assert MODULE in role_modules("nursing")
    assert MODULE not in role_modules("reception")


# ------------------------------------------------ recording and ordering ---
def _order_and_record(client, patient_id, **fields):
    client.post(f"/observations/patient/{patient_id}/order",
                data={"every_minutes": "15"}, follow_redirects=True)
    return client.post(f"/observations/patient/{patient_id}/record",
                       data=fields, follow_redirects=True)


def test_a_second_reading_is_possible_at_all(rounds_on):
    """The whole point, stated as plainly as it can be: two temperatures for
    one child on one day, which the clinic's own vitals table forbids."""
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, temperature_c="38.2")
    client.post(f"/observations/patient/{child}/record",
                data={"temperature_c": "38.9"}, follow_redirects=True)

    with rounds_on["app"].app_context():
        rows = Observation.query.filter_by(patient_id=child).all()
        assert len(rows) == 2
        assert sorted(r.temperature_c for r in rows) == [38.2, 38.9]


def test_a_reading_records_who_took_it_and_when(rounds_on):
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, spo2="94")

    with rounds_on["app"].app_context():
        row = Observation.query.filter_by(patient_id=child).first()
        assert row.recorded_by == rounds_on["ids"]["admin"]
        assert row.taken_at is not None
        assert row.order_id is not None


def test_an_empty_reading_is_refused(rounds_on):
    """A round where nothing was measured must not be saveable: it would
    silence the lateness warning while nobody had touched the child, which is
    the one failure this whole table exists to prevent."""
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "60"}, follow_redirects=True)
    client.post(f"/observations/patient/{child}/record",
                data={"note": "   "}, follow_redirects=True)

    with rounds_on["app"].app_context():
        assert Observation.query.filter_by(patient_id=child).count() == 0


def test_a_note_alone_is_a_reading(rounds_on):
    """"Sleeping, breathing comfortably" is an observation. Refusing it would
    make the nurse invent a number to be allowed to write it down."""
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, note="نايم ومرتاح")

    with rounds_on["app"].app_context():
        assert Observation.query.filter_by(patient_id=child).count() == 1


def test_a_change_of_oxygen_support_is_a_reading(rounds_on):
    """Not a measurement and still an observation: "moved on to CPAP at four"
    is a thing somebody saw by going to the child, which is the round."""
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, oxygen_support="cpap")

    with rounds_on["app"].app_context():
        row = Observation.query.filter_by(patient_id=child).one()
        assert row.oxygen_support == "cpap"


@pytest.mark.parametrize("field,rubbish", [("oxygen_support", "teleportation"),
                                           ("avpu", "Z")])
def test_a_choice_nobody_offers_is_dropped_and_the_numbers_kept(
        rounds_on, field, rubbish):
    """A select that arrives with something not on the list was not filled in
    by a nurse. The reading beside it is real, and losing a temperature to a
    bad dropdown would be the worse of the two failures.

    Both selects, because they are validated separately and the first version
    of this test checked only one of them — the mutation that let any letter
    through as a level of consciousness passed it without a mark.
    """
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, temperature_c="37.6", **{field: rubbish})

    with rounds_on["app"].app_context():
        row = Observation.query.filter_by(patient_id=child).one()
        assert getattr(row, field) is None
        assert row.temperature_c == 37.6


def test_a_level_of_consciousness_from_the_list_is_kept(rounds_on):
    """The other half of the rule above: a real answer goes in. Written
    because "drop what is not on the list" is one mutation away from "drop
    everything", and a test for the refusal alone cannot tell the two apart.
    """
    from app.models import Observation

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, avpu="V")

    with rounds_on["app"].app_context():
        assert Observation.query.filter_by(patient_id=child).one().avpu == "V"


def test_the_time_typed_is_read_as_the_clinic_s_own_clock(rounds_on):
    """A nurse typing 03:10 means ten past three **here**.

    Stored as UTC, like every other moment in the program. Reading the typed
    value as UTC is the mistake that has already cost this codebase four money
    reports, and on a rounds chart it would file every reading three hours out
    and then report the round as missed.
    """
    from app.models import Observation
    from app.utils.clock import to_utc

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "60"}, follow_redirects=True)
    client.post(f"/observations/patient/{child}/record",
                data={"taken_at": "2026-09-03T03:10", "temperature_c": "37.1"},
                follow_redirects=True)

    with rounds_on["app"].app_context():
        row = Observation.query.filter_by(patient_id=child).first()
        assert row.taken_at == to_utc(datetime(2026, 9, 3, 3, 10))


def test_changing_the_interval_keeps_the_old_order_on_file(rounds_on):
    """Afterwards somebody asks whether the child was being watched closely
    enough *at the time*, and an order edited in place cannot answer that."""
    from app.models import ObservationOrder

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "15"}, follow_redirects=True)
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "60"}, follow_redirects=True)

    with rounds_on["app"].app_context():
        orders = ObservationOrder.query.filter_by(patient_id=child).all()
        assert len(orders) == 2
        running = [o for o in orders if o.is_running]
        assert len(running) == 1 and running[0].every_minutes == 60
        stopped = [o for o in orders if not o.is_running]
        assert stopped[0].every_minutes == 15 and stopped[0].stopped_by


def test_stopping_the_rounds_keeps_them_on_file(rounds_on):
    """Stopped, never deleted — the same rule a withdrawn consent follows."""
    from app.models import ObservationOrder

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "30"}, follow_redirects=True)
    with rounds_on["app"].app_context():
        order_id = ObservationOrder.query.filter_by(patient_id=child).first().id

    client.post(f"/observations/order/{order_id}/stop", follow_redirects=True)
    with rounds_on["app"].app_context():
        row = ObservationOrder.query.get(order_id)
        assert row is not None and not row.is_running


def test_an_interval_nobody_offers_is_refused(rounds_on):
    """The list is fixed. "Every 37 minutes" is not an instruction anybody
    gives — it is a typo that would then drive a lateness alarm all shift."""
    from app.models import ObservationOrder

    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    client.post(f"/observations/patient/{child}/order",
                data={"every_minutes": "37"}, follow_redirects=True)
    with rounds_on["app"].app_context():
        assert ObservationOrder.query.filter_by(patient_id=child).count() == 0


def test_a_nurse_records_but_does_not_reorder(rounds_on):
    """Changing quarter-hourly observations to four-hourly is overruling an
    instruction, and the doctor who gave it would never know."""
    from app.models import ObservationOrder, User

    with rounds_on["app"].app_context():
        nurse = User(username="sister", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        rounds_on["db"].session.add(nurse)
        rounds_on["db"].session.commit()

    client = rounds_on["sign_in"]("sister")
    child = rounds_on["ids"]["child"]
    refused = client.post(f"/observations/patient/{child}/order",
                          data={"every_minutes": "240"})
    assert refused.status_code == 403
    with rounds_on["app"].app_context():
        assert ObservationOrder.query.filter_by(patient_id=child).count() == 0

    # And the reading itself goes through.
    client.post(f"/observations/patient/{child}/record",
                data={"temperature_c": "37.4"}, follow_redirects=True)
    from app.models import Observation
    with rounds_on["app"].app_context():
        assert Observation.query.filter_by(patient_id=child).count() == 1


# ------------------------------------------------------------- the board ---
def test_the_board_puts_the_overdue_child_first(rounds_on):
    from app.models import Observation, ObservationOrder
    from app.utils.observations import LATE, board

    with rounds_on["app"].app_context():
        from app.models import Patient

        other = Patient(patient_number="P2", full_name="طفلة",
                        gender="female",
                        date_of_birth=datetime(2024, 1, 1).date(),
                        is_active=True)
        rounds_on["db"].session.add(other)
        rounds_on["db"].session.flush()

        now = datetime.utcnow()
        # Measured a minute ago, hourly: not due.
        fine = ObservationOrder(patient_id=rounds_on["ids"]["child"],
                                every_minutes=60,
                                started_at=now - timedelta(hours=3))
        # Measured two hours ago, hourly: an hour late.
        overdue = ObservationOrder(patient_id=other.id, every_minutes=60,
                                   started_at=now - timedelta(hours=3))
        rounds_on["db"].session.add_all([fine, overdue])
        rounds_on["db"].session.flush()
        rounds_on["db"].session.add_all([
            Observation(patient_id=fine.patient_id, order_id=fine.id,
                        taken_at=now - timedelta(minutes=1), spo2=98),
            Observation(patient_id=other.id, order_id=overdue.id,
                        taken_at=now - timedelta(hours=2), spo2=97),
        ])
        rounds_on["db"].session.commit()

        rows = board(now)
        assert [r["patient"].id for r in rows] == [other.id,
                                                   rounds_on["ids"]["child"]]
        assert rows[0]["state"]["level"] == LATE
        assert rows[0]["state"]["minutes_late"] == 60


def test_the_board_does_not_ask_once_per_child(rounds_on):
    """A ward with thirty children under observation costs what two cost.

    Written as a **comparison between two sizes** rather than a ceiling on
    one, after the first attempt guessed a number and failed on a board that
    was doing nothing wrong. A ceiling has to be chosen, and a wrong choice
    either fails honest code or passes a loop that happens to be cheap; the
    difference between five children and twenty-five is not a guess. A query
    per child shows up here as twenty extra statements and nothing else does.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.models import Observation, ObservationOrder, Patient
    from app.utils.observations import board

    def add_children(count, offset):
        now = datetime.utcnow()
        for i in range(count):
            child = Patient(patient_number=f"B{offset + i:03d}",
                            full_name=f"طفل {offset + i}", gender="male",
                            date_of_birth=datetime(2024, 1, 1).date(),
                            is_active=True)
            rounds_on["db"].session.add(child)
            rounds_on["db"].session.flush()
            order = ObservationOrder(patient_id=child.id, every_minutes=60,
                                     started_at=now - timedelta(hours=2))
            rounds_on["db"].session.add(order)
            rounds_on["db"].session.flush()
            rounds_on["db"].session.add(
                Observation(patient_id=child.id, order_id=order.id,
                            taken_at=now - timedelta(minutes=30), spo2=97))
        rounds_on["db"].session.commit()

    def cost():
        statements = []

        def record(conn, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            rows = board()
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        return len(rows), len(statements)

    with rounds_on["app"].app_context():
        add_children(5, 0)
        # Once through first, so that neither measurement is the one paying
        # for the clinic's settings to be read for the first time.
        board()
        five_rows, five_queries = cost()
        add_children(20, 100)
        many_rows, many_queries = cost()

    assert (five_rows, many_rows) == (5, 25)
    assert many_queries == five_queries, (
        f"{five_queries} queries for 5 children and {many_queries} for 25 — "
        "something is querying inside the loop")


# ------------------------------------------------------------ the screen ---
def test_the_chart_shows_the_readings_it_holds(rounds_on):
    """The screen, not the table: a reading saved and nowhere visible is the
    shape of bug this project has now met six times."""
    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    _order_and_record(client, child, temperature_c="38.4", spo2="93",
                      note="متعب شوية")

    page = client.get(f"/observations/patient/{child}").get_data(as_text=True)
    assert "38.4" in page and "93" in page and "متعب شوية" in page
    # And the form that took it is on the same screen, at the top, because the
    # tablet at the bedside opens this to write.
    assert f'action="/observations/patient/{child}/record"' in page


def test_a_reading_outside_the_range_for_the_age_is_marked(rounds_on):
    """The colour comes from ``vital_bands`` — the same table the visit screen
    is handed. A saturation of 88% must not read like any other number in the
    column, and a normal one must not be painted as though it were abnormal:
    a screen where everything is red is a screen nobody reads by the second
    day. Two children, because one child's chart would hold both readings and
    the second assertion could not be made at all.
    """
    from app.models import Patient

    client = rounds_on["sign_in"]("boss")
    sick = rounds_on["ids"]["child"]
    with rounds_on["app"].app_context():
        well_child = Patient(patient_number="P9", full_name="طفلة", gender="female",
                             date_of_birth=datetime(2024, 1, 1).date(),
                             is_active=True)
        rounds_on["db"].session.add(well_child)
        rounds_on["db"].session.commit()
        well = well_child.id

    _order_and_record(client, sick, spo2="88")
    _order_and_record(client, well, spo2="99")

    # The rendered attribute, not the bare word: the class is also named in
    # the page's own `<style>` block, and three tests in this suite have
    # already been fooled by matching a class name that appears there.
    bad = client.get(f"/observations/patient/{sick}").get_data(as_text=True)
    assert "88" in bad and 'class="ob-bad"' in bad

    good = client.get(f"/observations/patient/{well}").get_data(as_text=True)
    assert "99" in good
    assert 'class="ob-bad"' not in good and 'class="ob-warn"' not in good


def test_the_nurse_is_told_the_order_exists_even_though_it_is_not_theirs(
        rounds_on):
    """Rule seven, which this project has already paid for once: a control
    somebody cannot use still has to say it is there, or nobody ever learns
    the program can do it. The nurse sees who orders the rounds instead of an
    empty card."""
    from app.i18n import t
    from app.models import User

    with rounds_on["app"].app_context():
        nurse = User(username="sister2", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        rounds_on["db"].session.add(nurse)
        rounds_on["db"].session.commit()
    # `t` resolves the language from the request, so the phrase is read the
    # way a screen reads it rather than out of the JSON by hand — a test that
    # opened the file itself would still pass with the key unwired.
    with rounds_on["app"].test_request_context("/"):
        expected = t("observations.doctor_orders")

    page = rounds_on["sign_in"]("sister2").get(
        f"/observations/patient/{rounds_on['ids']['child']}").get_data(as_text=True)
    assert expected in page
    # And no offer they cannot take up.
    assert 'name="every_minutes"' not in page


def test_the_child_s_file_reaches_the_rounds_when_they_are_on(rounds_on):
    """The other direction. The board answers "who is overdue"; a nurse
    looking at one child needs to get to their chart from the file, and a
    child with no order yet is on no list at all."""
    client = rounds_on["sign_in"]("boss")
    child = rounds_on["ids"]["child"]
    page = client.get(f"/patients/{child}").get_data(as_text=True)
    assert f'href="/observations/patient/{child}"' in page


def test_the_child_s_file_says_nothing_about_rounds_when_they_are_off(clinic):
    """A ward button on an outpatient file is furniture — and rule one:
    a module that is off is absent, not disabled."""
    client = clinic["sign_in"]("boss")
    child = clinic["ids"]["child"]
    page = client.get(f"/patients/{child}").get_data(as_text=True)
    assert "/observations/" not in page
