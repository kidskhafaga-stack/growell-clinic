"""Managing implantable devices — GAHAR SAS.11, the rest of the system.

*"The hospital has a system for managing implantable devices, including
recall."* What every case touches was already here — the implant confirmed
in the room, and what went into the child with its batch number, with a
screen that finds children by batch. These tests hold the system around it:

* evidence 2, (a), (b) — the hospital's list, each entry with its primary
  source and who approved it. Empty until the hospital writes it.
* (c) — who fitted it: the hospital's staff or the company's representative.
* (e), (g) — adverse events and malfunctions, and where each was reported.
* (h) — the hospital's discharge instructions, and when the family got them.
* evidence 5, (f) — a recall is the work of reaching every family, inside a
  time frame the hospital sets.
* the intent — *"every patient with an implantable device should be easily
  identified"*: on the child's own file.

Nothing refuses a case. What is missing is named where it is missing.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def case(clinic):
    from app.models import Operation, Setting, Theatre
    from app.utils import theatres as theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        room = Theatre(name="غرفة ١", is_active=True)
        db.session.add(room)
        db.session.flush()
        op = Operation(patient_id=clinic["ids"]["child"], theatre_id=room.id,
                       procedure="تثبيت كسر", status="scheduled",
                       on_date=local_today(),
                       surgeon_id=clinic["ids"]["doctor"])
        db.session.add(op)
        db.session.flush()
        plate = theatre.add_implant(op, "شريحة تيتانيوم", manufacturer="Synthes")
        spare = theatre.add_implant(op, "شريحة مقاس أكبر")
        db.session.flush()
        theatre.record_implanted(plate, lot="LOT-42",
                                 at=datetime.utcnow() - timedelta(days=30))
        db.session.commit()
        clinic["ids"].update(op=op.id, plate=plate.id, spare=spare.id,
                             room=room.id)
    return clinic


def _get(case, model, key):
    return case["db"].session.get(model, case["ids"][key])


def _plate(case, key="plate"):
    from app.models.theatre import OperationImplant

    return _get(case, OperationImplant, key)


def _user(case, key="doctor"):
    from app.models import User

    return _get(case, User, key)


# ---------------------------------------------------- the hospital's list ----
def test_the_list_starts_empty_and_says_so(case):
    page = case["sign_in"]("boss").get("/theatres/implants").get_data(as_text=True)
    assert "data-list-empty" in page


def test_only_an_administrator_writes_the_list(case):
    from app.models import ImplantDevice

    case["sign_in"]("doc").post("/theatres/implants",
                                data={"action": "add", "name": "شريحة"})
    with case["app"].app_context():
        assert ImplantDevice.query.count() == 0
    case["sign_in"]("boss").post("/theatres/implants",
                                 data={"action": "add", "name": "شريحة",
                                       "manufacturer": "Synthes",
                                       "supplier": "الشركة المصرية للمستلزمات"})
    with case["app"].app_context():
        row = ImplantDevice.query.one()
        assert row.approved_by == case["ids"]["admin"]
        assert row.supplier == "الشركة المصرية للمستلزمات"


def test_one_device_is_one_row(case):
    """Two rows for one device split its children between them."""
    from app.models import ImplantDevice
    from app.utils import implants

    with case["app"].app_context():
        first = implants.add_device("شريحة", manufacturer="Synthes")
        case["db"].session.commit()
        implants.retire_device(first)
        again = implants.add_device(" شريحة ", manufacturer="synthes")
        case["db"].session.commit()
        assert again.id == first.id and again.is_active
        assert ImplantDevice.query.count() == 1


def test_the_same_device_typed_in_another_case_is_the_same_row(case):
    from app.utils import implants

    with case["app"].app_context():
        first = implants.add_device("Titanium Elastic Nail", manufacturer="Synthes")
        case["db"].session.commit()
        assert implants.add_device("titanium elastic NAIL",
                                   manufacturer="SYNTHES").id == first.id


def test_a_retired_device_is_kept_but_not_offered(case):
    from app.utils import implants

    with case["app"].app_context():
        row = implants.add_device("شريحة")
        case["db"].session.commit()
        implants.retire_device(row)
        case["db"].session.commit()
        assert implants.catalogue() == []
        assert implants.catalogue(active_only=False) == [row]


def test_picking_from_the_list_takes_the_lists_words(case):
    from app.models.theatre import OperationImplant
    from app.utils import implants

    with case["app"].app_context():
        device = implants.add_device("مسمار داخل النخاع", manufacturer="Stryker")
        case["db"].session.commit()
        device_id = device.id
    case["sign_in"]("doc").post(
        f"/theatres/operation/{case['ids']['op']}/implants",
        data={"new_device": device_id, "new_name": "مسمار"})
    with case["app"].app_context():
        row = OperationImplant.query.filter_by(device_id=device_id).one()
        assert (row.name, row.manufacturer) == ("مسمار داخل النخاع", "Stryker")
        assert not implants.off_list(row)
        assert implants.off_list(_plate(case))


def test_by_hand_is_allowed_and_said(case):
    page = case["sign_in"]("doc").get(
        f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert "data-off-list" in page


# ------------------------------------------------------------- (c) who ----
def test_who_fitted_it(case):
    op, plate = case["ids"]["op"], case["ids"]["plate"]
    case["sign_in"]("doc").post(
        f"/theatres/operation/{op}/implants",
        data={f"tech_{plate}": "م. سامح", f"tech_from_{plate}": "yes"})
    with case["app"].app_context():
        row = _plate(case)
        assert (row.technician, row.technician_external) == ("م. سامح", True)


def test_no_name_means_nobody_said(case):
    from app.utils import implants

    with case["app"].app_context():
        row = implants.record_technician(_plate(case), "  ", external=False)
        assert (row.technician, row.technician_external) == (None, None)


# -------------------------------------------- (h) going home with it ----
def test_instructions_only_for_what_went_in(case):
    from app.utils import implants

    with case["app"].app_context(), pytest.raises(ValueError):
        implants.give_instructions(_plate(case, "spare"))


def test_instructions_given_once_and_the_first_moment_stands(case):
    from app.utils import implants

    with case["app"].app_context():
        first = datetime.utcnow() - timedelta(hours=3)
        implants.give_instructions(_plate(case), at=first)
        implants.give_instructions(_plate(case))
        assert _plate(case).instructions_given_at == first
        assert not implants.instructions_missing(_plate(case))


def test_the_case_shows_the_hospitals_words_and_takes_the_tick(case):
    from app.utils import implants

    with case["app"].app_context():
        device = implants.add_device("شريحة", instructions="الجرح ناشف ٤٨ ساعة")
        case["db"].session.flush()
        _plate(case).device_id = device.id
        case["db"].session.commit()
    doc = case["sign_in"]("doc")
    url = f"/theatres/operation/{case['ids']['op']}"
    page = doc.get(url).get_data(as_text=True)
    assert "الجرح ناشف ٤٨ ساعة" in page
    assert 'data-instructions="missing"' in page
    doc.post(url + "/implants", data={f"told_{case['ids']['plate']}": "yes"})
    assert 'data-instructions="given"' in doc.get(url).get_data(as_text=True)


# ------------------------------------------------ (e)+(g) events ----
@pytest.mark.parametrize("key, kind, words", [
    ("spare", "adverse", "احمرار"),       # not in a child
    ("plate", "broken", "احمرار"),        # not a kind
    ("plate", "adverse", "  "),           # nothing said
])
def test_what_an_event_cannot_be(case, key, kind, words):
    from app.utils import implants

    with case["app"].app_context(), pytest.raises(ValueError):
        implants.record_event(_plate(case, key), kind, words)


def test_an_event_waits_until_it_is_reported(case):
    from app.models import ImplantEvent

    doc = case["sign_in"]("doc")
    doc.post(f"/theatres/implant/{case['ids']['plate']}/event",
             data={"kind": "malfunction", "description": "المسمار اتكسر"})
    page = doc.get("/theatres/implants").get_data(as_text=True)
    assert "data-unreported" in page and "المسمار اتكسر" in page
    with case["app"].app_context():
        event_id = ImplantEvent.query.one().id
    doc.post(f"/theatres/implant-event/{event_id}/report",
             data={"reported_to": "هيئة الدواء المصرية", "reference": "MD-1"})
    page = doc.get("/theatres/implants").get_data(as_text=True)
    assert "data-unreported" not in page
    with case["app"].app_context():
        row = case["db"].session.get(ImplantEvent, event_id)
        assert row.reported and row.reported_by == case["ids"]["doctor"]


@pytest.mark.parametrize("to, shift", [
    ("", timedelta(0)),                      # to nobody
    ("الهيئة", timedelta(hours=2)),          # in the future
    ("الهيئة", -timedelta(days=2)),          # before the event
])
def test_a_report_that_could_not_be_true(case, to, shift):
    from app.utils import implants

    with case["app"].app_context():
        now = datetime.utcnow()
        event = implants.record_event(_plate(case), "adverse", "حرارة",
                                      now=now - timedelta(hours=1))
        case["db"].session.flush()
        with pytest.raises(ValueError):
            implants.report_event(event, to, at=now + shift, now=now)


# ------------------------------------------------------------ recall ----
def _recall(case, **terms):
    from app.utils import implants

    with case["app"].app_context():
        row = implants.open_recall("إشعار سحب تشغيلة", **(terms or {"lot": "LOT-42"}))
        case["db"].session.commit()
        return row.id


def _r(case, rid):
    from app.models import ImplantRecall

    return case["db"].session.get(ImplantRecall, rid)


@pytest.mark.parametrize("notice, terms", [
    ("", {"lot": "LOT-42"}), ("إشعار", {}), ("إشعار", {"lot": "  "})])
def test_a_recall_needs_words_and_something_to_search(case, notice, terms):
    from app.utils import implants

    with case["app"].app_context(), pytest.raises(ValueError):
        implants.open_recall(notice, **terms)


def test_a_search_becomes_a_recall(case):
    from app.models import ImplantRecall

    boss = case["sign_in"]("boss")
    page = boss.get("/theatres/implants/recall?lot=LOT-42").get_data(as_text=True)
    assert "data-open-recall" in page
    reply = boss.post("/theatres/implants/recall/open",
                      data={"notice": "سحب LOT-42", "lot": "LOT-42"})
    with case["app"].app_context():
        rid = ImplantRecall.query.one().id
    assert reply.headers["Location"].endswith(f"/theatres/implants/recall/{rid}")
    page = boss.get(f"/theatres/implants/recall/{rid}").get_data(as_text=True)
    assert f'data-recall-child="{case["ids"]["plate"]}" data-state="not_tried"' in page


def test_a_child_recorded_after_the_recall_opened_is_not_missed(case):
    from app.models import Operation
    from app.utils import implants
    from app.utils import theatres as theatre

    rid = _recall(case)
    with case["app"].app_context():
        op = _get(case, Operation, "op")
        late = theatre.add_implant(op, "شريحة تانية")
        case["db"].session.flush()
        theatre.record_implanted(late, lot="LOT-42")
        case["db"].session.commit()
        assert len(implants.affected(_r(case, rid))) == 2


def test_reached_not_reached_and_nobody_tried(case):
    from app.utils import implants

    rid = _recall(case)
    with case["app"].app_context():
        recall, plate = _r(case, rid), _plate(case)
        assert implants.contact_state(recall, plate) == "not_tried"
        implants.record_contact(recall, plate, "not_reached")
        case["db"].session.commit()
        assert implants.contact_state(recall, plate) == "not_reached"
        implants.record_contact(recall, plate, "reached")
        case["db"].session.commit()
        assert implants.contact_state(recall, plate) == "reached"
        assert implants.outstanding(recall) == []


def test_the_time_frame_is_the_hospitals_and_late_is_named(case):
    from app.utils import implants

    rid = _recall(case)
    with case["app"].app_context():
        recall, plate = _r(case, rid), _plate(case)
        later = recall.opened_at + timedelta(hours=30)
        # No time frame written: nothing can be late.
        assert implants.deadline(recall) is None
        assert implants.contact_state(recall, plate, now=later) == "not_tried"
        implants.set_recall_hours(24)
        case["db"].session.commit()
        assert implants.contact_state(recall, plate, now=later) == "late"
        # Reached, but only after the time frame — the audit sees it.
        implants.record_contact(recall, plate, "reached", now=later)
        case["db"].session.commit()
        assert implants.contact_state(recall, plate, now=later) == "late"
        assert implants.outstanding(recall, now=later) == []


def test_reached_inside_the_time_frame_is_reached(case):
    from app.utils import implants

    rid = _recall(case)
    with case["app"].app_context():
        implants.set_recall_hours(24)
        recall, plate = _r(case, rid), _plate(case)
        implants.record_contact(recall, plate, "reached",
                                now=recall.opened_at + timedelta(hours=2))
        case["db"].session.commit()
        assert implants.contact_state(
            recall, plate, now=recall.opened_at + timedelta(hours=30)) == "reached"


@pytest.mark.parametrize("stored", ["0", "-5", "يوم"])
def test_a_stored_time_frame_that_is_not_one_reads_as_unset(case, stored):
    """Written by hand into the settings, or by an older copy — read as
    "the hospital has not said", never as a deadline already passed."""
    from app.models import Setting
    from app.utils import implants

    with case["app"].app_context():
        Setting.set("implant_recall_hours", stored)
        case["db"].session.commit()
        assert implants.recall_hours() is None


@pytest.mark.parametrize("value", ["0", "-3", "يوم", "2.5"])
def test_a_time_frame_that_is_not_one(case, value):
    from app.utils import implants

    with case["app"].app_context(), pytest.raises(ValueError):
        implants.set_recall_hours(value)


def test_only_an_administrator_sets_the_time_frame(case):
    from app.utils import implants

    case["sign_in"]("doc").post("/theatres/implants",
                                data={"action": "hours", "hours": "24"})
    with case["app"].app_context():
        assert implants.recall_hours() is None
    case["sign_in"]("boss").post("/theatres/implants",
                                 data={"action": "hours", "hours": "24"})
    with case["app"].app_context():
        assert implants.recall_hours() == 24
    case["sign_in"]("boss").post("/theatres/implants",
                                 data={"action": "hours", "hours": ""})
    with case["app"].app_context():
        assert implants.recall_hours() is None


def test_a_contact_for_a_child_not_on_the_recall_is_refused(case):
    from app.utils import implants

    rid = _recall(case, lot="OTHER")
    with case["app"].app_context(), pytest.raises(ValueError):
        implants.record_contact(_r(case, rid), _plate(case), "reached")


def test_closing_with_families_unreached_needs_the_reason(case):
    from app.utils import implants

    rid = _recall(case)
    with case["app"].app_context():
        recall = _r(case, rid)
        with pytest.raises(ValueError):
            implants.close_recall(recall)
        implants.close_recall(recall, note="الأسرة سافرت ومفيش رقم")
        case["db"].session.commit()
        assert recall.closed_at is not None
        # And once closed, nothing more is written against it.
        with pytest.raises(ValueError):
            implants.record_contact(recall, _plate(case), "reached")


def test_closing_once_everyone_is_reached_needs_no_reason(case):
    from app.utils import implants

    rid = _recall(case)
    with case["app"].app_context():
        recall = _r(case, rid)
        implants.record_contact(recall, _plate(case), "reached")
        implants.close_recall(recall)
        case["db"].session.commit()
        assert recall.closed_at is not None


def test_the_recall_screen_takes_a_call(case):
    rid = _recall(case)
    boss = case["sign_in"]("boss")
    boss.post(f"/theatres/implants/recall/{rid}/contact",
              data={"implant_id": case["ids"]["plate"], "outcome": "reached",
                    "note": "الأم ردّت"})
    page = boss.get(f"/theatres/implants/recall/{rid}").get_data(as_text=True)
    assert 'data-state="reached"' in page and "الأم ردّت" in page
    listing = boss.get("/theatres/implants").get_data(as_text=True)
    assert f'data-recall="{rid}"' in listing


# ------------------------------------------------ easily identified ----
def test_the_childs_file_says_what_is_inside(case):
    page = case["sign_in"]("boss").get(
        f"/patients/{case['ids']['child']}").get_data(as_text=True)
    assert "data-implants-in" in page and "LOT-42" in page
    # The size prepared and not used is not in the child.
    assert "شريحة مقاس أكبر" not in page


def test_a_child_with_nothing_inside_has_no_banner(case):
    from app.models.theatre import OperationImplant

    with case["app"].app_context():
        _plate(case).implanted_at = None
        case["db"].session.commit()
        assert OperationImplant.query.filter(
            OperationImplant.implanted_at.isnot(None)).count() == 0
    page = case["sign_in"]("boss").get(
        f"/patients/{case['ids']['child']}").get_data(as_text=True)
    assert "data-implants-in" not in page


def test_the_theatre_list_has_a_door_to_the_system(case):
    page = case["sign_in"]("boss").get("/theatres/").get_data(as_text=True)
    assert "/theatres/implants" in page
