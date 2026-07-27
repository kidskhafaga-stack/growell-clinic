"""The result came back — now somebody has to be told, and be able to answer.

Before this, a film the mother sent was filed correctly on the child's record
and tied to the order it answered, and then waited. The doctor only met it by
opening that child's visit, and the child is not coming in today — which was
the whole point of ordering it in the program rather than on paper.

Two lists, both of which exist because nobody watches a screen all day: what
has come back and not been read, and which conversations are about to fall
out of the free-reply window.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 300


@pytest.fixture()
def desk(clinic, tmp_path):
    """A clinic where the family has a phone and files can be written."""
    static = tmp_path / "static"
    (static / "uploads" / "patient_docs").mkdir(parents=True)
    clinic["app"].static_folder = str(static)

    with clinic["app"].app_context():
        from app.models import Family, Parent, Patient

        family = Family(family_name="عائلة")
        clinic["db"].session.add(family)
        clinic["db"].session.flush()
        clinic["db"].session.add(Parent(family_id=family.id, full_name="الأم",
                                        relation="mother", phone="01000000001"))
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.family_id = family.id
        clinic["db"].session.commit()
    return clinic


def _order(desk, name="أشعة صدر", kind="imaging"):
    doctor = desk["sign_in"]("doc")
    doctor.post(f"/visits/{desk['ids']['visit']}/investigations",
                data={"name_ar": name, "kind": kind}, follow_redirects=True)
    return doctor


def _family_sends(desk, text="أشعة الصدر", phone="01000000001"):
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    original = wa_media.download
    wa_media.download = lambda m, cfg=None: (PNG, "image/png")
    try:
        with desk["app"].app_context():
            result = handle_inbound({"from_phone": phone, "text": text,
                                     "media": {"id": "m1"}}, "meta")
            desk["db"].session.commit()
            return result
    finally:
        wa_media.download = original


def _waiting(desk, doctor_id=None):
    from app.utils.results_inbox import arrived_unread

    with desk["app"].app_context():
        return arrived_unread(doctor_id=doctor_id)


# ------------------------------------------------ what is waiting to be read --
def test_an_order_still_out_with_the_family_is_on_nobodys_list(desk):
    """Asked for and not yet answered is not "waiting to be read" — it is
    waiting on the patient, and putting it here would bury the real ones."""
    _order(desk)
    assert _waiting(desk) == []


def test_a_result_that_arrived_is_waiting_to_be_read(desk):
    _order(desk)
    _family_sends(desk)
    waiting = _waiting(desk)
    assert len(waiting) == 1
    assert waiting[0]["patient"].id == desk["ids"]["child"]
    assert waiting[0]["files"], "the film itself has to be on the row"


def test_reading_it_takes_it_off_the_list(desk):
    """The only way off. Anything else and the list becomes a thing people
    stop believing."""
    doctor = _order(desk)
    _family_sends(desk)
    order_id = _waiting(desk)[0]["order"].id

    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": "التهاب شعبي"}, follow_redirects=True)
    assert _waiting(desk) == []


def test_the_longest_wait_comes_first(desk):
    """A film that arrived three days ago is more urgent than one from an
    hour ago, and a list ordered by "newest" hides exactly that."""
    from app.models import PatientAttachment

    doctor = _order(desk, "أشعة صدر", "imaging")
    doctor.post(f"/visits/{desk['ids']['visit']}/investigations",
                data={"name_ar": "صورة دم", "kind": "lab"},
                follow_redirects=True)
    _family_sends(desk, "أشعة")
    _family_sends(desk, "تحليل")

    with desk["app"].app_context():
        oldest = (PatientAttachment.query
                  .order_by(PatientAttachment.id).first())
        oldest.created_at = datetime.utcnow() - timedelta(days=3)
        desk["db"].session.commit()

    waiting = _waiting(desk)
    assert len(waiting) == 2
    assert waiting[0]["waiting_hours"] > waiting[1]["waiting_hours"]


def test_a_doctor_sees_the_films_they_asked_for(desk):
    """A paediatrician with four colleagues wants their own list."""
    _order(desk)
    _family_sends(desk)

    assert len(_waiting(desk, doctor_id=desk["ids"]["doctor"])) == 1
    assert _waiting(desk, doctor_id=desk["ids"]["admin"]) == []


# --------------------------------------------------------------- the bell --
def test_the_bell_says_a_result_is_waiting(desk):
    from app.utils.notifications import invalidate

    _order(desk)
    _family_sends(desk)
    with desk["app"].app_context():
        invalidate()
        from app.utils.results_inbox import arrived_count
        assert arrived_count() == 1

    doctor = desk["sign_in"]("doc")
    body = doctor.get("/", follow_redirects=True).get_data(as_text=True)
    assert "نتايج وصلت" in body, "the bell says nothing about it"


def test_the_bell_is_quiet_when_nothing_is_waiting(desk):
    from app.utils.notifications import invalidate

    _order(desk)
    with desk["app"].app_context():
        invalidate()
    doctor = desk["sign_in"]("doc")
    body = doctor.get("/", follow_redirects=True).get_data(as_text=True)
    assert "نتايج وصلت" not in body


# -------------------------------------------------------------- the screen --
def test_the_screen_lists_it_with_the_film_and_the_chat(desk):
    """Everything needed to deal with one, on its row: what was asked for,
    the file, and the family's conversation — because the answer to "the film
    is here" is usually something the doctor has to say to them."""
    doctor = _order(desk)
    _family_sends(desk)

    body = doctor.get("/visits/results").get_data(as_text=True)
    assert "أشعة صدر" in body
    assert "طفل" in body
    assert f"/messages/inbox/p{desk['ids']['child']}" in body, "no way to reply"
    assert "uploads/patient_docs/" in body, "the film itself is not reachable"


def test_the_screen_says_so_plainly_when_there_is_nothing(desk):
    doctor = desk["sign_in"]("doc")
    body = doctor.get("/visits/results").get_data(as_text=True)
    assert "مفيش نتايج مستنية" in body


def test_recording_the_result_from_the_screen_clears_it(desk):
    doctor = _order(desk)
    _family_sends(desk)
    order_id = _waiting(desk)[0]["order"].id

    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": "سليم"}, follow_redirects=True)
    body = doctor.get("/visits/results").get_data(as_text=True)
    assert "مفيش نتايج مستنية" in body


# ------------------------------------------------- the window that closes --
def _on_the_api(desk):
    """Put the clinic on the WhatsApp Business API.

    The 24-hour window is that API's rule. A clinic sending click-to-send
    links has no window at all, and correctly has no countdown either — so
    these tests have to say which of the two this clinic is.
    """
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        desk["db"].session.commit()


def _write_in(desk, hours_ago):
    """The family wrote this long ago — which is what starts the clock."""
    from app.models import MessageLog

    _on_the_api(desk)

    with desk["app"].app_context():
        log = MessageLog(direction="in", provider="meta",
                         to_phone="201000000001", body="فين النتيجة؟",
                         status="received", patient_id=desk["ids"]["child"])
        desk["db"].session.add(log)
        desk["db"].session.flush()
        log.created_at = datetime.utcnow() - timedelta(hours=hours_ago)
        desk["db"].session.commit()


def _closing(desk):
    from app.utils.results_inbox import closing_windows

    with desk["app"].app_context():
        return closing_windows()


def test_a_window_with_hours_left_is_not_urgent_yet(desk):
    _write_in(desk, hours_ago=1)
    assert _closing(desk) == []


def test_a_window_about_to_shut_is_urgent(desk):
    """After twenty-four hours the reply stops being free and can only go as
    an approved template. Nobody is watching the inbox at eleven at night,
    which is when that happens."""
    _write_in(desk, hours_ago=23)
    urgent = _closing(desk)
    assert len(urgent) == 1
    assert urgent[0]["hours_left"] <= 2


def test_a_window_already_shut_is_not_on_the_urgent_list(desk):
    """Nothing to hurry for any more — it belongs to the approved-template
    path, not to a countdown."""
    _write_in(desk, hours_ago=30)
    assert _closing(desk) == []


def test_the_closing_one_is_first_in_the_inbox(desk):
    """A thread with forty minutes left is more urgent than one that has
    waited longer but has a day in hand."""
    from app.models import MessageLog, Patient
    from app.utils.inbox import conversations

    with desk["app"].app_context():
        other = Patient(patient_number="P9", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2024, 1, 1),
                        is_active=True)
        desk["db"].session.add(other)
        desk["db"].session.flush()
        # Waiting far longer, but its window has a day left.
        older = MessageLog(direction="in", provider="meta",
                           to_phone="201555555555", body="سؤال قديم",
                           status="received", patient_id=other.id)
        desk["db"].session.add(older)
        desk["db"].session.flush()
        older.created_at = datetime.utcnow() - timedelta(hours=5)
        desk["db"].session.commit()

    _write_in(desk, hours_ago=23)          # newer, but nearly out of time

    with desk["app"].app_context():
        threads = conversations(only_open=True)
        assert threads[0]["closing"] is True
        assert threads[0]["key"] == f"p{desk['ids']['child']}"


def test_the_bell_counts_the_closing_windows(desk):
    from app.utils.notifications import invalidate

    _write_in(desk, hours_ago=23)
    with desk["app"].app_context():
        invalidate()
    body = desk["sign_in"]("boss").get("/", follow_redirects=True).get_data(as_text=True)
    assert "نافذة الرد" in body


def test_the_bell_and_the_list_cannot_disagree(desk):
    """Both read the same rule from the same place. Two copies of "closing
    soon" is how a bell says three and the screen shows one."""
    from app.utils.inbox import conversations
    from app.utils.results_inbox import closing_windows

    _write_in(desk, hours_ago=23)
    with desk["app"].app_context():
        counted = len(closing_windows())
        listed = sum(1 for c in conversations(only_open=True) if c["closing"])
        assert counted == listed == 1
