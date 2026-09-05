"""The operating theatres, and the stop nobody made.

``HOSPITAL_PLAN.md`` ٤-ج is unusually blunt about what matters here:
*"اللي بيخليها «بشكل ذكي» مش الجدول نفسه — ده الجزء السهل — ده إن قايمة الفحص
قبل العملية تكون هي قلب الشاشة مش ورقة جنبها."* So the schedule is checked
briefly and the checklist at length, which is the same ratio the screen uses.

Four things are asserted here that a theatre module can be built without, and
each of them is the difference between a checklist and a poster:

1. **A stop that nobody ran leaves no row**, and the program names it. The
   same shape as the observation nobody took and the round nobody walked.
2. **A stop signed with items unticked is stored with those items named.** A
   green tick over four of seven would be the program manufacturing a
   signature — which is worse than no checklist at all, because the record
   then says the check was done.
3. **Starting a case whose sign-in is missing is refused.** The one hard
   refusal in the module.
4. **Finishing is never refused for a missing sign-out.** Refusing would
   leave the child in theatre for ever in the program's own telling; the gap
   is shown instead, and goes on being shown.

And the money, which is the part that has been quietly missing from every
module in this phase until somebody looked: an operation is a ``Service``, it
lands on the **stay's one bill** beside the nights and the doses, and the
share is read against the **surgeon** rather than the admitting doctor.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A ward with a priced night, two theatres, and a priced operation."""
    from app.models import Service, Setting, User
    from app.models.place import Bed, Space, Unit
    from app.models.theatre import Theatre
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        for module in ("observations", "beds", "ward", "theatres"):
            Setting.set(f"mod_enabled:{module}", "1")

        surgeon = User(username="surgeon", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        nurse = User(username="scrub", full_name="ممرضة العمليات",
                     role="nursing", is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add_all([surgeon, nurse])

        night = Service(name="ليلة داخلي", category="other", price=500)
        # 30% to whoever operated — the number the surgeon test turns on.
        operation = Service(name="استئصال زائدة", category="procedure",
                            price=4000, commission_type="percent",
                            commission_value=30, is_active=True)
        clinic["db"].session.add_all([night, operation])
        clinic["db"].session.flush()

        unit = Unit(name="الداخلي", kind="ward", rate_service_id=night.id)
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        clinic["db"].session.add(Bed(space_id=space.id, name="د١"))

        clinic["db"].session.add_all([
            Theatre(name="غرفة عمليات ١", sort_order=1),
            Theatre(name="غرفة عمليات ٢", sort_order=2)])
        clinic["db"].session.commit()

        clinic["bed"] = Bed.query.first().id
        clinic["surgeon"] = surgeon.id
        clinic["nurse"] = nurse.id
        clinic["operation_service"] = operation.id
        clinic["rooms"] = [r.id for r in
                           Theatre.query.order_by(Theatre.sort_order).all()]
    return clinic


# ------------------------------------------------------------- helpers -----
def _child(clinic, name):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"T{name}", full_name=name,
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=1500))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, days_ago=2):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(clinic["bed"]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        clinic["db"].session.commit()
        return row.id


def _book(clinic, patient_id, room=0, admission_id=None, priced=True,
          on_date=None, start=None, surgeon=True):
    from app.models import Patient
    from app.models.theatre import Theatre
    from app.utils import theatres

    with clinic["app"].app_context():
        row = theatres.book(
            Patient.query.get(patient_id),
            clinic["db"].session.get(Theatre, clinic["rooms"][room]),
            "استئصال زائدة", on_date=on_date,
            admission_id=admission_id, start_time=start,
            surgeon_id=clinic["surgeon"] if surgeon else None,
            service_id=clinic["operation_service"] if priced else None)
        clinic["db"].session.commit()
        return row.id


def _sign(clinic, operation_id, stop, items=None):
    from app.models.theatre import CHECK_ITEMS, Operation
    from app.utils import theatres

    with clinic["app"].app_context():
        row = theatres.sign(clinic["db"].session.get(Operation, operation_id),
                            stop,
                            items=(CHECK_ITEMS[stop] if items is None
                                   else items))
        clinic["db"].session.commit()
        return row.id


def _state(clinic, operation_id):
    from app.models.theatre import Operation
    from app.utils import theatres

    with clinic["app"].app_context():
        row = clinic["db"].session.get(Operation, operation_id)
        safety = theatres.safety(row)
        return {"status": row.status,
                "started": row.started_at is not None,
                "finished": row.finished_at is not None,
                "billed": row.invoice_item_id is not None,
                "done": list(safety["done"]),
                "next": safety["next"],
                "missed": {k: list(v) for k, v in safety["missed"].items()},
                "ready": safety["ready"], "closed": safety["closed"]}


def _charge(clinic, admission_id):
    from app.models.admission import Admission
    from app.utils import bed_billing

    with clinic["app"].app_context():
        return bed_billing.charge(
            clinic["db"].session.get(Admission, admission_id))


def _bill(clinic, admission_id):
    from app.models.invoice import Invoice

    with clinic["app"].app_context():
        row = Invoice.query.filter_by(admission_id=admission_id).one()
        return {"total": row.total, "lines": len(row.items),
                "descriptions": [i.description for i in row.items],
                "prices": [i.unit_price for i in row.items],
                "doctors": [i.doctor_id for i in row.items],
                "commissions": [i.commission_amount for i in row.items]}


# =========================================== the stop nobody made ===========
def test_the_program_names_the_stop_that_was_never_made(hospital):
    """The missing row is the finding.

    Not "the checklist is incomplete" — *which* stop, because a case with no
    time-out is one where nobody stopped before the first cut, and that is a
    different sentence from a missing sign-out.
    """
    operation = _book(hospital, _child(hospital, "ندى"))

    assert _state(hospital, operation)["next"] == "sign_in"

    _sign(hospital, operation, "sign_in")
    assert _state(hospital, operation)["next"] == "time_out"

    _sign(hospital, operation, "time_out")
    state = _state(hospital, operation)
    assert state["next"] == "sign_out"
    assert state["done"] == ["sign_in", "time_out"]
    assert not state["closed"]


def test_a_stop_signed_short_keeps_what_was_not_ticked(hospital):
    """**The heart of it.** A stop signed with three of seven ticked is stored
    as exactly that, with the four named.

    A program that recorded only "signed" would turn a half-done check into a
    signature saying it was done — the one failure a safety checklist exists
    to prevent, manufactured by the software meant to prevent it.
    """
    operation = _book(hospital, _child(hospital, "سلمى"))
    _sign(hospital, operation, "sign_in",
          items=["identity", "consent", "allergy"])

    state = _state(hospital, operation)
    # Signed — the stop happened and the case may start.
    assert "sign_in" in state["done"]
    assert state["ready"]
    # And short, with the missing items named rather than counted.
    assert set(state["missed"]["sign_in"]) == {
        "site_marked", "airway", "anaesthesia_check", "pulse_oximeter"}


def test_an_unknown_item_cannot_be_smuggled_into_a_signature(hospital):
    """Only this stop's own items count as confirmed.

    A form that posted "counts_correct" at the sign-in would otherwise have
    produced a signature naming a check nobody performs before anaesthesia.
    """
    operation = _book(hospital, _child(hospital, "جنى"))
    _sign(hospital, operation, "sign_in",
          items=["identity", "counts_correct", "made_up"])

    from app.models.theatre import Operation

    with hospital["app"].app_context():
        row = hospital["db"].session.get(Operation, operation)
        assert row.check_for("sign_in").items == ["identity"]


def test_signing_the_same_stop_again_updates_it(hospital):
    """One sign-off per stop.

    Two screens running the checklist in the same minute is exactly how a stop
    ends up signed twice and nobody can say which signature was real.
    """
    from app.models.theatre import Operation, SafetyCheck

    operation = _book(hospital, _child(hospital, "لينا"))
    _sign(hospital, operation, "sign_in", items=["identity"])
    _sign(hospital, operation, "sign_in", items=["identity", "consent"])

    with hospital["app"].app_context():
        rows = SafetyCheck.query.filter_by(operation_id=operation).all()
        assert len(rows) == 1
        assert set(rows[0].items) == {"identity", "consent"}
        assert len(hospital["db"].session.get(Operation, operation).checks) == 1


# =============================================== the one refusal ============
def test_a_case_cannot_start_before_the_team_has_signed_in(hospital):
    """The single place in this module where the answer to a request is no."""
    from app.models.theatre import Operation
    from app.utils import theatres

    operation = _book(hospital, _child(hospital, "مريم"))

    with hospital["app"].app_context():
        with pytest.raises(theatres.NotSafeYet):
            theatres.start(hospital["db"].session.get(Operation, operation))
        hospital["db"].session.rollback()

    state = _state(hospital, operation)
    assert state["status"] == "scheduled"
    assert not state["started"]


def test_the_screen_refuses_it_too_and_says_which_stop(hospital):
    """The refusal reaches the person pressing the button.

    A rule enforced only in a utility module is a rule the screen can walk
    around, and this is the one rule that must not be walked around.
    """
    child = _child(hospital, "هنا")
    operation = _book(hospital, child)
    client = hospital["sign_in"]("boss")

    page = client.post(f"/theatres/operation/{operation}/start",
                       follow_redirects=True)

    assert page.status_code == 200
    assert _state(hospital, operation)["status"] == "scheduled"
    # And the screen keeps saying it, rather than showing a live-looking
    # button that answers no.
    assert b"data-blocked" in page.data


def test_once_signed_in_the_case_starts(hospital):
    """The refusal is about the missing stop, not about starting."""
    operation = _book(hospital, _child(hospital, "ملك"))
    _sign(hospital, operation, "sign_in")

    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)

    state = _state(hospital, operation)
    assert state["status"] == "in_theatre"
    assert state["started"]


# ========================================= and the one thing never refused ==
def test_finishing_is_never_refused_for_a_missing_sign_out(hospital):
    """A gap that is visible beats a refusal that gets worked around.

    Refusing to record that the operation ended would leave this child in
    theatre for ever in the program's own telling — and the ward would go on
    expecting them back.
    """
    operation = _book(hospital, _child(hospital, "روان"))
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)

    page = client.post(f"/theatres/operation/{operation}/finish",
                       data={"findings": "زائدة ملتهبة"},
                       follow_redirects=True)

    state = _state(hospital, operation)
    assert state["status"] == "done"
    assert state["finished"]
    assert not state["closed"]
    # And the gap is on the screen, not only in the flash that scrolls away.
    assert b"data-no-signout" in page.data


def test_the_missing_sign_out_keeps_being_said_afterwards(hospital):
    """Not once. A warning shown on the redirect and gone on the next load is
    a warning nobody acts on."""
    operation = _book(hospital, _child(hospital, "تالة"))
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    page = client.get(f"/theatres/operation/{operation}")

    assert b"data-no-signout" in page.data


# ================================================== the day's list ==========
def test_the_day_is_room_by_room_in_time_order(hospital):
    """What a theatre list is for: "what is theatre two doing at eleven"."""
    from app.utils.clock import local_today

    today = local_today()
    # Booked 9:30, then 8:00, then 11:00 — so the right answer matches neither
    # the order they were booked in nor its reverse. Booked in order, insertion
    # order and time order agree and this test would pass either way; booked
    # simply backwards, reverse-id order agrees with it and still would.
    middle = _book(hospital, _child(hospital, "أ"), room=0, on_date=today,
                   start=time(9, 30))
    early = _book(hospital, _child(hospital, "ب"), room=0, on_date=today,
                  start=time(8, 0))
    late = _book(hospital, _child(hospital, "ح"), room=0, on_date=today,
                 start=time(11, 0))
    other = _book(hospital, _child(hospital, "ج"), room=1, on_date=today,
                  start=time(9, 0))

    with hospital["app"].app_context():
        from app.utils import theatres

        rooms = theatres.day(today)
        listed = [[c["operation"].id for c in room["operations"]]
                  for room in rooms]

    assert listed == [[early, middle, late], [other]]


def test_a_cancelled_case_stays_on_the_list(hospital):
    """A morning where two of six were called off is a fact about that
    morning. Dropping them makes the list agree with itself and disagree with
    the day."""
    from app.models.theatre import Operation
    from app.utils import theatres
    from app.utils.clock import local_today

    today = local_today()
    operation = _book(hospital, _child(hospital, "د"), on_date=today)
    with hospital["app"].app_context():
        theatres.cancel(hospital["db"].session.get(Operation, operation),
                        reason="الطفل سخن")
        hospital["db"].session.commit()

        listed = [c["operation"].id
                  for room in theatres.day(today) for c in room["operations"]]

    assert operation in listed
    assert _state(hospital, operation)["status"] == "cancelled"


def test_yesterdays_list_is_not_todays(hospital):
    """The date is the clinic's own, and the list is a day."""
    from app.utils.clock import local_today

    today = local_today()
    yesterday = today - timedelta(days=1)
    old = _book(hospital, _child(hospital, "هـ"), on_date=yesterday)
    new = _book(hospital, _child(hospital, "و"), on_date=today)

    with hospital["app"].app_context():
        from app.utils import theatres

        assert [c["operation"].id for room in theatres.day(today)
                for c in room["operations"]] == [new]
        assert [c["operation"].id for room in theatres.day(yesterday)
                for c in room["operations"]] == [old]


def test_a_booking_with_no_procedure_is_refused(hospital):
    """"An operation" is not something a theatre list can be read from, and
    the name is the one thing nobody can supply later from the record."""
    from app.models import Patient
    from app.models.theatre import Operation, Theatre
    from app.utils import theatres

    child = _child(hospital, "ز")
    with hospital["app"].app_context():
        with pytest.raises(ValueError):
            theatres.book(Patient.query.get(child),
                          hospital["db"].session.get(
                              Theatre, hospital["rooms"][0]), "   ")
        hospital["db"].session.rollback()
        assert Operation.query.count() == 0


# ================================================== the money ===============
def test_a_finished_operation_lands_on_the_stays_one_bill(hospital):
    """One account for the admission.

    Not a bed bill, a pharmacy bill and a theatre bill for the same three
    days — the family gets one, which is the rule the drugs already follow.
    """
    child = _child(hospital, "ح")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")

    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    result = _charge(hospital, admission)

    assert result["operations"] == 1
    bill = _bill(hospital, admission)
    # Two nights at 500 and one operation at 4000, on one invoice.
    assert bill["total"] == 2 * 500 + 4000
    assert any("استئصال زائدة" in d for d in bill["descriptions"])


def test_the_share_is_read_against_the_surgeon_not_the_admitting_doctor(hospital):
    """The person who did the operation is the person it is owed to.

    The stay was admitted under one doctor and operated on by another, and
    reading the share off the invoice's doctor would pay the wrong one — a
    mistake nobody notices until the month's payouts are argued over.
    """
    from app.models.service import DoctorServiceCommission

    with hospital["app"].app_context():
        # The surgeon is on a different rate for this operation. Without an
        # override both doctors take 30% and the test passes either way.
        hospital["db"].session.add(DoctorServiceCommission(
            doctor_id=hospital["surgeon"],
            service_id=hospital["operation_service"],
            commission_type="percent", commission_value=50))
        hospital["db"].session.commit()

    child = _child(hospital, "ط")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    _charge(hospital, admission)

    bill = _bill(hospital, admission)
    # 50% of 4000 — the surgeon's rate, not the service's default 30%.
    assert 2000.0 in bill["commissions"]
    # And the line says whose it is, so repricing the bill from the cash list
    # later works the share out at the surgeon's rate rather than handing it
    # back to the doctor the invoice belongs to.
    assert hospital["surgeon"] in bill["doctors"]


def test_the_same_operation_is_never_charged_twice(hospital):
    """Pressing the button again charges nothing, because the case carries
    the invoice line it went onto — the nights use a unique night for the
    same job."""
    child = _child(hospital, "ي")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    first = _charge(hospital, admission)
    second = _charge(hospital, admission)

    assert first["operations"] == 1
    assert second["operations"] == 0
    assert _bill(hospital, admission)["total"] == 2 * 500 + 4000
    assert _state(hospital, operation)["billed"]


def test_an_operation_alone_is_enough_to_raise_the_stays_bill(hospital):
    """A stay that owes no night yet and no dose at all.

    The child was admitted this morning — nothing owes a night until tomorrow —
    and was operated on at noon. If the posting only looks for nights and
    doses it returns "nothing due" and the operation is never charged, on this
    admission or any later one.
    """
    child = _child(hospital, "نص")
    admission = _admit(hospital, child, days_ago=0)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    result = _charge(hospital, admission)

    assert result["periods"] == 0
    assert result["operations"] == 1
    assert _bill(hospital, admission)["total"] == 4000


def test_an_operation_nobody_priced_never_reaches_a_bill(hospital):
    """The price is the switch, here as everywhere.

    A hospital that does not bill for theatre time, or has not decided what
    this one costs yet, books it, does it, and is charged nothing — the same
    rule as a bed with no rate on it.
    """
    child = _child(hospital, "ك")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission, priced=False)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    result = _charge(hospital, admission)

    assert result["operations"] == 0
    assert _bill(hospital, admission)["total"] == 2 * 500


def test_a_cancelled_case_owes_nothing(hospital):
    """A morning that was called off is not a bill."""
    from app.models.theatre import Operation
    from app.utils import theatres

    child = _child(hospital, "ل")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    with hospital["app"].app_context():
        theatres.cancel(hospital["db"].session.get(Operation, operation))
        hospital["db"].session.commit()

    result = _charge(hospital, admission)

    assert result["operations"] == 0
    assert _bill(hospital, admission)["total"] == 2 * 500


def test_a_case_still_on_the_table_is_not_billed(hospital):
    """It has not happened yet."""
    child = _child(hospital, "م")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)

    result = _charge(hospital, admission)

    assert result["operations"] == 0
    assert _bill(hospital, admission)["total"] == 2 * 500


def test_a_day_case_is_booked_without_inventing_a_stay(hospital):
    """A child comes in, is operated on, and goes home.

    Refusing the booking until somebody invents an admission would put a
    fictional stay in their file — so the stay is nullable, and this is what
    that nullability is for.
    """
    from app.models.theatre import Operation

    child = _child(hospital, "ن")
    operation = _book(hospital, child)

    with hospital["app"].app_context():
        assert hospital["db"].session.get(Operation,
                                          operation).admission_id is None


# ================================================== the doors ===============
def test_the_module_off_means_the_theatre_list_is_absent(hospital):
    """Not an empty screen. A hospital that admits children and operates on
    none of them must not find a theatre list after an update."""
    from app.models import Setting

    with hospital["app"].app_context():
        Setting.set("mod_enabled:theatres", "0")
        hospital["db"].session.commit()

    client = hospital["sign_in"]("boss")
    assert client.get("/theatres/").status_code == 404
    assert client.get("/theatres/setup").status_code == 404


def test_the_stay_screen_is_the_second_door_into_theatre(hospital):
    """A child already in a bed is booked from where their nurse is standing.

    One door would have hidden the other kind of case — the gap this program
    has now found seven times.
    """
    child = _child(hospital, "س")
    admission = _admit(hospital, child)
    client = hospital["sign_in"]("boss")

    page = client.get(f"/beds/admission/{admission}")

    assert b"data-theatre" in page.data
    assert b"/theatres/book" in page.data


def test_the_stay_screen_says_nothing_about_theatre_when_it_is_off(hospital):
    """A module off is a module absent — not a disabled button."""
    from app.models import Setting

    child = _child(hospital, "ع")
    admission = _admit(hospital, child)
    with hospital["app"].app_context():
        Setting.set("mod_enabled:theatres", "0")
        hospital["db"].session.commit()

    page = hospital["sign_in"]("boss").get(f"/beds/admission/{admission}")

    assert b"data-theatre" not in page.data


def test_the_day_screen_draws_where_each_checklist_stands(hospital):
    """The three dots, readable from across the room. This is the only thing
    on the day screen that is not a fact about the timetable, and it is
    deliberately the loudest."""
    from app.utils.clock import local_today

    child = _child(hospital, "ف")
    operation = _book(hospital, child, on_date=local_today())
    _sign(hospital, operation, "sign_in", items=["identity"])

    page = hospital["sign_in"]("boss").get("/theatres/")

    assert b'data-stop="sign_in"' in page.data
    # Signed short, which is neither "done" nor "not signed" — and the screen
    # has to be able to say the third thing.
    assert b'data-state="short"' in page.data
    assert b'data-state="none"' in page.data


def test_the_case_screen_names_the_unticked_items(hospital):
    """Not a count on its own: which ones."""
    child = _child(hospital, "ص")
    operation = _book(hospital, child)
    _sign(hospital, operation, "sign_in", items=["identity", "consent"])

    page = hospital["sign_in"]("boss").get(f"/theatres/operation/{operation}")

    assert b"data-short" in page.data
    # On the item itself. `op-missed` alone also matches the stylesheet, so
    # this passed with every label unmarked — found by breaking it on purpose.
    assert b"op-item op-missed" in page.data


def test_a_nurse_may_run_the_checklist(hospital):
    """The scrub nurse runs it more often than anybody.

    Leaving them out would mean the one stop nobody may skip gets signed by
    borrowing a doctor's login, which is how a signature stops meaning
    anything.
    """
    child = _child(hospital, "ق")
    operation = _book(hospital, child)
    client = hospital["sign_in"]("scrub")

    page = client.post(f"/theatres/operation/{operation}/sign",
                       data={"stop": "sign_in", "item": ["identity",
                                                         "consent"]},
                       follow_redirects=True)

    from app.models.theatre import Operation

    assert page.status_code == 200
    assert _state(hospital, operation)["ready"]
    # And what they ticked reached the record. Asserting only that the stop
    # exists would pass with the form's items thrown away — a signature over
    # an empty checklist.
    with hospital["app"].app_context():
        row = hospital["db"].session.get(Operation, operation)
        assert set(row.check_for("sign_in").items) == {"identity", "consent"}


def test_the_signature_carries_who_signed_it(hospital):
    """A checklist that says the checks were done and not who did them is a
    checklist nobody can ask about afterwards."""
    from app.models.theatre import Operation

    child = _child(hospital, "ر")
    operation = _book(hospital, child)
    hospital["sign_in"]("scrub").post(
        f"/theatres/operation/{operation}/sign",
        data={"stop": "sign_in", "item": ["identity"]}, follow_redirects=True)

    with hospital["app"].app_context():
        row = hospital["db"].session.get(Operation, operation)
        assert row.check_for("sign_in").by_id == hospital["nurse"]


def test_the_room_is_taken_out_of_use_never_deleted(hospital):
    """What was done in this room last month is a thing a hospital reports
    on, and a room that vanishes takes its cases with it."""
    from app.models.theatre import Theatre

    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/room/{hospital['rooms'][1]}/toggle",
                data={"note": "التكييف واقف"}, follow_redirects=True)

    with hospital["app"].app_context():
        row = hospital["db"].session.get(Theatre, hospital["rooms"][1])
        assert row is not None
        assert not row.is_active
        assert row.note == "التكييف واقف"
        # And it is off the day's list, which is what "out of use" means.
        from app.utils import theatres
        assert len(theatres.day(date.today())) == 1


# ================================== the day case, and its bill ==============
def _day_case(hospital, name):
    """A child operated on and sent home the same day — no stay anywhere."""
    child = _child(hospital, name)
    operation = _book(hospital, child)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)
    return child, operation


def _desk_form(hospital, operation_id, price="4000"):
    return {
        "doctor_id": hospital["ids"]["doctor"], "discount_id": "none",
        "line_service_id": [str(hospital["operation_service"])],
        "line_desc": ["استئصال زائدة"], "line_price": [price],
        "line_qty": ["1"], "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
        "line_op_id": [str(operation_id)],
    }


def test_a_day_case_is_offered_at_the_desk(hospital):
    """**Otherwise the module bills admitted children and nobody else.**

    A day case has no stay to hang a bill off, so the desk is the only place
    its money can be raised — and until it was offered there, an operation on
    a child who went home the same day was recorded, charted, and charged to
    nobody at all.
    """
    child, operation = _day_case(hospital, "دي")

    page = hospital["sign_in"]("boss").get(f"/finance/collect/{child}")

    # The line the screen was filled with, not the empty hidden field that
    # sits in the markup for every line whether or not one exists.
    assert f'"op_id": {operation}'.encode() in page.data
    assert "استئصال زائدة".encode() in page.data
    # And the screen carries it into the form it submits. The checkout rebuilds
    # every line from a fixed list of fields, so a line the server filled in
    # correctly can still arrive at the till with the operation forgotten —
    # which it did, and the bill was collected while the case stayed unbilled.
    assert b"op_id:l.op_id" in page.data


def test_the_desk_says_nothing_about_theatre_when_the_module_is_off(hospital):
    """A module off is a module absent — on the busiest screen in the clinic
    as everywhere else. And the collection screen is opened for every patient
    of every clinic, including the ones that will never own a theatre."""
    from app.models import Setting

    child, _ = _day_case(hospital, "قف")
    with hospital["app"].app_context():
        Setting.set("mod_enabled:theatres", "0")
        hospital["db"].session.commit()

    page = hospital["sign_in"]("boss").get(f"/finance/collect/{child}")

    assert page.status_code == 200
    assert b'"op_id"' not in page.data


def test_collecting_a_day_case_stamps_it_so_it_never_comes_back(hospital):
    """The same stamp the nights and the doses use. Without it the case would
    be offered again at every visit for the rest of the child's life."""
    child, operation = _day_case(hospital, "خت")
    client = hospital["sign_in"]("boss")

    client.post(f"/finance/collect/{child}",
                data=_desk_form(hospital, operation), follow_redirects=True)

    assert _state(hospital, operation)["billed"]
    again = client.get(f"/finance/collect/{child}")
    # No operation line left to fill the screen with. Asserted on the line's
    # own marker rather than on the procedure's name, which also appears in
    # the "add a service" picker on every checkout in the clinic.
    assert b'"op_id"' not in again.data


def test_the_desk_line_is_owed_to_the_surgeon(hospital):
    """The invoice belongs to one doctor and the operation was done by
    another. The share follows the knife."""
    from app.models.invoice import InvoiceItem
    from app.models.service import DoctorServiceCommission

    with hospital["app"].app_context():
        hospital["db"].session.add(DoctorServiceCommission(
            doctor_id=hospital["surgeon"],
            service_id=hospital["operation_service"],
            commission_type="percent", commission_value=50))
        hospital["db"].session.commit()

    child, operation = _day_case(hospital, "جر")
    hospital["sign_in"]("boss").post(
        f"/finance/collect/{child}", data=_desk_form(hospital, operation),
        follow_redirects=True)

    with hospital["app"].app_context():
        line = InvoiceItem.query.filter(
            InvoiceItem.doctor_id.isnot(None)).one()
        assert line.doctor_id == hospital["surgeon"]
        # 50% of 4000 — the surgeon's rate, not the invoice doctor's 30%.
        assert line.commission_amount == 2000.0


def test_an_admitted_childs_operation_is_not_offered_at_the_desk(hospital):
    """It belongs to the stay's one bill. Offering it here as well would bill
    the same knife twice."""
    child = _child(hospital, "من")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    page = client.get(f"/finance/collect/{child}")

    assert b'"op_id"' not in page.data


def test_a_made_up_operation_id_stamps_nothing(hospital):
    """A posted id is a number anybody can type, and this one marks an
    operation paid for."""
    from app.models.theatre import Operation

    other, waiting = _day_case(hospital, "غر")
    child, operation = _day_case(hospital, "طب")
    # The form claims to be paying for somebody else's case.
    form = _desk_form(hospital, operation)
    form["line_op_id"] = [str(waiting)]

    hospital["sign_in"]("boss").post(f"/finance/collect/{child}", data=form,
                                     follow_redirects=True)

    with hospital["app"].app_context():
        # Not this child's patient, so it was never in the offered set and
        # nothing was stamped.
        assert hospital["db"].session.get(
            Operation, waiting).invoice_item_id is None


# ================================== the file ================================
def test_the_childs_file_carries_their_operations(hospital):
    """Where an operation history belongs.

    Without this a day case appeared only on one date's theatre list — a
    screen nobody opens again six months later — and the child's own file said
    nothing about the fact that somebody had operated on them.
    """
    child, operation = _day_case(hospital, "مل")

    page = hospital["sign_in"]("boss").get(f"/patients/{child}")

    assert b"data-operations" in page.data
    assert f"/theatres/operation/{operation}".encode() in page.data


def test_the_file_says_nothing_about_theatre_when_the_module_is_off(hospital):
    """A module off is a module absent, in the file as everywhere else."""
    from app.models import Setting

    child, _ = _day_case(hospital, "نو")
    with hospital["app"].app_context():
        Setting.set("mod_enabled:theatres", "0")
        hospital["db"].session.commit()

    page = hospital["sign_in"]("boss").get(f"/patients/{child}")

    assert b"data-operations" not in page.data


# ================================== correcting the booking ==================
def test_a_case_booked_with_nobody_on_it_can_be_given_a_surgeon(hospital):
    """**The one-way door.** A case is put on the list before anybody knows
    who is operating — the clerk books "Tuesday, theatre two" and the morning
    meeting settles the rest. Set only at booking, an operation with no
    surgeon and no service could never be given either, so it could never be
    billed and the share could never reach anybody.
    """
    from app.models.theatre import Operation

    child = _child(hospital, "بد")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission, priced=False,
                      surgeon=False)

    hospital["sign_in"]("boss").post(
        f"/theatres/operation/{operation}/edit",
        data={"procedure": "استئصال زائدة",
              "service_id": hospital["operation_service"],
              "surgeon_id": hospital["surgeon"]}, follow_redirects=True)

    with hospital["app"].app_context():
        row = hospital["db"].session.get(Operation, operation)
        assert row.service_id == hospital["operation_service"]
        assert row.surgeon_id == hospital["surgeon"]

    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)

    # And now it reaches a bill, which is the whole point of being able to
    # correct it.
    assert _charge(hospital, admission)["operations"] == 1


def test_a_charged_case_keeps_what_its_bill_was_built_from(hospital):
    """Changing the service after the invoice line exists would leave a charge
    on a family's account that nothing on this screen accounts for."""
    from app.models.theatre import Operation

    child = _child(hospital, "مق")
    admission = _admit(hospital, child)
    operation = _book(hospital, child, admission_id=admission)
    _sign(hospital, operation, "sign_in")
    client = hospital["sign_in"]("boss")
    client.post(f"/theatres/operation/{operation}/start", follow_redirects=True)
    client.post(f"/theatres/operation/{operation}/finish", follow_redirects=True)
    _charge(hospital, admission)

    client.post(f"/theatres/operation/{operation}/edit",
                data={"procedure": "استئصال زائدة بالمنظار",
                      "service_id": "", "surgeon_id": ""},
                follow_redirects=True)

    with hospital["app"].app_context():
        row = hospital["db"].session.get(Operation, operation)
        # The price basis is locked...
        assert row.service_id == hospital["operation_service"]
        assert row.surgeon_id == hospital["surgeon"]
        # ...and the record of what was actually done is not.
        assert row.procedure == "استئصال زائدة بالمنظار"


def test_the_edit_form_opens_itself_when_something_is_missing(hospital):
    """A case with no surgeon on it is the one a screen should not make
    somebody go looking for."""
    child = _child(hospital, "فت")
    operation = _book(hospital, child, priced=False, surgeon=False)

    page = hospital["sign_in"]("boss").get(f"/theatres/operation/{operation}")

    assert b"<details open" in page.data
