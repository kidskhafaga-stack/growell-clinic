"""A tissue that came out of a child, and where it went — GAHAR SAS.10.

*"Surgically removed tissue is sent for pathological examination unless
present in the list of exempted tissues."* Four pieces of evidence:

1. a clear pathway for every removed tissue;
2. a list of exempted tissue — **the hospital's**, empty until it writes it;
3. labelled (date and time, patient identification, tissue) and sent;
4. the result in the record within **the hospital's** time frame.

And one witness that was already in the record: the operative report's (g),
*"any removed specimen, or not"*. A report that says yes over a case with no
specimen is a tissue with no pathway.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def case(clinic):
    from app.models import Operation, Setting, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        room = Theatre(name="غرفة ١", is_active=True)
        db.session.add(room)
        db.session.flush()
        op = Operation(patient_id=clinic["ids"]["child"], theatre_id=room.id,
                       procedure="استئصال لوز", status="done",
                       on_date=local_today(),
                       surgeon_id=clinic["ids"]["doctor"])
        db.session.add(op)
        db.session.commit()
        clinic["ids"]["op"] = op.id
    return clinic


def _op(case):
    from app.models import Operation

    return case["db"].session.get(Operation, case["ids"]["op"])


def _specimen(case, tissue="لوزتين", at=None):
    from app.utils import pathology

    with case["app"].app_context():
        row = pathology.record(_op(case), tissue, at=at)
        case["db"].session.commit()
        return row.id


def _row(case, sid):
    from app.models import Specimen

    return case["db"].session.get(Specimen, sid)


def _state(case, sid, **kw):
    from app.utils import pathology

    with case["app"].app_context():
        return pathology.state(_row(case, sid), **kw)


def _list(case, *names):
    from app.utils import pathology

    with case["app"].app_context():
        keys = [pathology.add_exempt(n) for n in names]
        case["db"].session.commit()
        return [k.key for k in keys]


def _days(case, n):
    from app.models import Setting
    from app.utils import pathology

    with case["app"].app_context():
        Setting.set(pathology.DAYS_SETTING, str(n))
        case["db"].session.commit()


# ------------------------------------------------------------ pathway ----
def test_a_new_specimen_is_waiting_to_be_sent(case):
    assert _state(case, _specimen(case)) == "to_send"


def test_a_tissue_with_no_name_is_refused(case):
    from app.utils import pathology

    with case["app"].app_context(), pytest.raises(ValueError):
        pathology.record(_op(case), "  ")


def test_sending_needs_the_label(case):
    """EOC 3: the sender confirms the label is on the container — a specimen
    the lab cannot match to a child is what the label exists to prevent."""
    from app.utils import pathology

    sid = _specimen(case)
    with case["app"].app_context():
        with pytest.raises(ValueError):
            pathology.send(_row(case, sid), "المعمل المركزي", labelled=False)
        pathology.send(_row(case, sid), "المعمل المركزي", labelled=True)
        case["db"].session.commit()
    assert _state(case, sid) == "sent"


def test_the_result_closes_the_pathway(case):
    from app.utils import pathology

    sid = _specimen(case)
    with case["app"].app_context():
        row = _row(case, sid)
        pathology.send(row, "معمل", labelled=True)
        pathology.record_result(row, "التهاب مزمن، لا خلايا خبيثة")
        case["db"].session.commit()
    assert _state(case, sid) == "resulted"


def test_a_result_for_a_specimen_nobody_sent_is_refused(case):
    from app.utils import pathology

    sid = _specimen(case)
    with case["app"].app_context(), pytest.raises(ValueError):
        pathology.record_result(_row(case, sid), "نتيجة")


@pytest.mark.parametrize("shift", [timedelta(hours=-2), timedelta(days=2)])
def test_a_result_dated_before_sending_or_in_the_future_is_refused(case, shift):
    """Either would change the length the time frame is measured on."""
    from app.utils import pathology

    sid = _specimen(case)
    with case["app"].app_context():
        row = _row(case, sid)
        sent = datetime.utcnow() - timedelta(hours=1)
        pathology.send(row, "معمل", labelled=True, at=sent)
        with pytest.raises(ValueError):
            pathology.record_result(row, "نتيجة",
                                    on=(sent + shift if shift.days < 0
                                        else datetime.utcnow() + shift))


# -------------------------------------------------------- the exempt list ----
def test_nothing_is_exempt_until_the_hospital_writes_its_list(case):
    """EOC 2 — the program does not decide which tissue needs no pathologist."""
    from app.utils import pathology

    sid = _specimen(case, "جلدة الطهارة")
    with case["app"].app_context(), pytest.raises(ValueError):
        pathology.exempt(_row(case, sid), "item")


def test_an_exemption_is_taken_from_the_list(case):
    from app.utils import pathology

    key, = _list(case, "جلدة الطهارة")
    sid = _specimen(case, "جلدة الطهارة")
    with case["app"].app_context():
        pathology.exempt(_row(case, sid), key, note="اتصرفت حسب السياسة")
        case["db"].session.commit()
        assert pathology.exempt_label(_row(case, sid).exempt_key) == "جلدة الطهارة"
    assert _state(case, sid) == "exempt"


def test_a_retired_line_exempts_nothing_new_but_names_the_old(case):
    """Off the list, not deleted: last year's exemption still says which
    line allowed it."""
    from app.models import Lookup
    from app.utils import pathology

    key, = _list(case, "زايدة")
    old = _specimen(case, "زايدة")
    with case["app"].app_context():
        pathology.exempt(_row(case, old), key)
        line = Lookup.query.filter_by(key=key, domain="exempt_tissue").one()
        pathology.retire_exempt(line)
        case["db"].session.commit()
        assert pathology.exempt_label(_row(case, old).exempt_key) == "زايدة"
    new = _specimen(case, "زايدة")
    with case["app"].app_context(), pytest.raises(ValueError):
        pathology.exempt(_row(case, new), key)


def test_a_sent_specimen_cannot_then_be_exempted(case):
    from app.utils import pathology

    key, = _list(case, "جلدة الطهارة")
    sid = _specimen(case)
    with case["app"].app_context():
        pathology.send(_row(case, sid), "معمل", labelled=True)
        with pytest.raises(ValueError):
            pathology.exempt(_row(case, sid), key)


def test_only_an_administrator_writes_the_list(case):
    from app.models import Lookup

    case["sign_in"]("doc").post("/theatres/pathology/exempt",
                                data={"name": "جلدة الطهارة"})
    with case["app"].app_context():
        assert Lookup.query.filter_by(domain="exempt_tissue").count() == 0
    case["sign_in"]("boss").post("/theatres/pathology/exempt",
                                 data={"name": "جلدة الطهارة"})
    with case["app"].app_context():
        assert Lookup.query.filter_by(domain="exempt_tissue").count() == 1


# ----------------------------------------------------------- the time ----
def test_nothing_is_late_until_the_hospital_sets_the_time_frame(case):
    from app.utils import pathology

    sid = _specimen(case)
    with case["app"].app_context():
        pathology.send(_row(case, sid), "معمل", labelled=True,
                       at=datetime.utcnow() - timedelta(days=60))
        case["db"].session.commit()
    assert _state(case, sid) == "sent"


@pytest.mark.parametrize("raw", ["0", "-3", "abc", ""])
def test_a_zero_or_nonsense_time_frame_is_no_time_frame(case, raw):
    """A number nobody meant is not the hospital's time frame."""
    from app.models import Setting
    from app.utils import pathology

    with case["app"].app_context():
        Setting.set(pathology.DAYS_SETTING, raw)
        case["db"].session.commit()
        assert pathology.result_days() is None


def test_past_the_time_frame_is_late(case):
    from app.utils import pathology

    _days(case, 7)
    sid = _specimen(case)
    with case["app"].app_context():
        pathology.send(_row(case, sid), "معمل", labelled=True,
                       at=datetime.utcnow() - timedelta(days=8))
        case["db"].session.commit()
    assert _state(case, sid) == "late"


def test_within_the_time_frame_is_not(case):
    from app.utils import pathology

    _days(case, 7)
    sid = _specimen(case)
    with case["app"].app_context():
        pathology.send(_row(case, sid), "معمل", labelled=True,
                       at=datetime.utcnow() - timedelta(days=6))
        case["db"].session.commit()
    assert _state(case, sid) == "sent"


# -------------------------------------------------- the report as witness --
def test_a_report_that_says_tissue_came_out_with_none_recorded(case):
    from app.models import OperativeReport
    from app.utils import pathology

    with case["app"].app_context():
        case["db"].session.add(OperativeReport(
            operation_id=case["ids"]["op"], specimen=True,
            written_at=datetime.utcnow()))
        case["db"].session.commit()
        assert [o.id for o in pathology.untracked()] == [case["ids"]["op"]]
    page = case["sign_in"]("boss").get(
        f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert "data-specimen-untracked" in page
    _specimen(case)
    with case["app"].app_context():
        assert pathology.untracked() == []


# ------------------------------------------------------------- screens ----
def test_the_whole_path_from_the_case_screen(case):
    boss = case["sign_in"]("boss")
    op = case["ids"]["op"]
    boss.post(f"/theatres/operation/{op}/specimen", data={"tissue": "لوزتين"})
    page = boss.get(f"/theatres/operation/{op}").get_data(as_text=True)
    assert 'data-specimen-state="to_send"' in page
    from app.models import Specimen

    with case["app"].app_context():
        sid = Specimen.query.one().id
    boss.post(f"/theatres/specimen/{sid}/send", data={"lab": "معمل"})
    assert _state(case, sid) == "to_send", "sent without the label"
    boss.post(f"/theatres/specimen/{sid}/send", data={"lab": "معمل", "labelled": "1"})
    assert _state(case, sid) == "sent"
    boss.post(f"/theatres/specimen/{sid}/result", data={"result": "حميد"})
    page = boss.get(f"/theatres/operation/{op}").get_data(as_text=True)
    assert 'data-specimen-state="resulted"' in page
    assert "حميد" in page


def test_the_label_carries_the_three_things(case):
    """Date and time, the child's identity, the tissue — and two
    identifiers for the child, because a name alone is shared."""
    sid = _specimen(case, "لوزتين")
    page = case["sign_in"]("boss").get(
        f"/theatres/specimen/{sid}/label").get_data(as_text=True)
    for mark in ("data-label-name", "data-label-file", "data-label-taken",
                 "data-label-tissue"):
        assert mark in page
    assert "P1" in page and "لوزتين" in page


def test_the_board_puts_the_late_one_first(case):
    from app.utils import pathology

    _days(case, 5)
    fresh, old = _specimen(case, "أ"), _specimen(case, "ب")
    with case["app"].app_context():
        pathology.send(_row(case, fresh), "معمل", labelled=True,
                       at=datetime.utcnow() - timedelta(days=1))
        pathology.send(_row(case, old), "معمل", labelled=True,
                       at=datetime.utcnow() - timedelta(days=9))
        case["db"].session.commit()
        waiting = pathology.board()["waiting"]
    assert [w["specimen"].id for w in waiting] == [old, fresh]
    page = case["sign_in"]("boss").get("/theatres/pathology").get_data(as_text=True)
    assert f'data-waiting="{old}" data-waiting-state="late"' in page


def test_the_board_says_when_there_is_no_time_frame(case):
    page = case["sign_in"]("boss").get("/theatres/pathology").get_data(as_text=True)
    assert "data-days-unset" in page
    assert "data-exempt-empty" in page


def test_the_theatre_list_has_a_door_to_it(case):
    page = case["sign_in"]("boss").get("/theatres/").get_data(as_text=True)
    assert "/theatres/pathology" in page
