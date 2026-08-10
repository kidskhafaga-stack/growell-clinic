"""The family that stopped coming — the one message a person has to press.

Every other message this program sends answers something: a booking, a missed
visit, a rating, a failed send. This one answers nothing — *nothing happened*
is the whole point — so it goes to families who are not currently talking to
the clinic. That is the only kind of message that can turn the clinic's number
into unasked-for mail, and a number that becomes that gets blocked; then the
vaccination reminder does not arrive either.

**The archiving interaction is the part that would have shipped as a mystery.**
The program already retires a file after ``archive_inactive_years`` of no
visits. Set the recall window past that and the list is empty forever — not
because nothing qualifies, but because everything that qualifies has already
left the roster. An empty screen with no explanation reads exactly like a
broken feature, so the screen says it.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TYPE = "patient_recall"


@pytest.fixture()
def lapsed(clinic):
    """A clinic that sends, with one family last seen two years ago."""
    with clinic["app"].app_context():
        from app.models import MessageTemplate, Patient, Setting, Visit
        from app.utils.clock import local_today
        from app.utils.whatsapp import seed_system_templates
        db = clinic["db"]

        seed_system_templates()
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
        tpl.send_mode, tpl.is_active = "auto", True

        child = db.session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01012345678"
        # The fixture's visit is today; move it back two years.
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.visit_date = local_today() - timedelta(days=730)
        db.session.commit()
    return clinic


def _sent(clinic):
    from app.models import MessageLog
    return MessageLog.query.filter_by(template_type=TYPE).all()


# --- who is on the list ----------------------------------------------------

def test_a_family_two_years_away_is_on_the_list(lapsed):
    """The gap: nothing here ever reached them."""
    with lapsed["app"].app_context():
        from app.utils.recall import candidates
        rows = candidates()
        assert len(rows) == 1
        assert rows[0][0].id == lapsed["ids"]["child"]


def test_the_clinic_decides_how_long_is_too_long(lapsed):
    """A practice seeing well children yearly and one following chronic asthma
    have different answers, and neither is the program's to pick."""
    from app.models import Setting
    from app.utils.recall import after_months, candidates

    with lapsed["app"].app_context():
        Setting.set("recall_after_months", "36")
        lapsed["db"].session.commit()
        assert after_months() == 36
        assert candidates() == [], "a two-year gap counted against a three-year rule"

        Setting.set("recall_after_months", "6")
        lapsed["db"].session.commit()
        assert len(candidates()) == 1


@pytest.mark.parametrize("raw,months", [
    ("", 12), ("nonsense", 12), ("0", 1), ("-4", 1), ("900", 60),
])
def test_a_mistyped_window_cannot_message_the_whole_register(lapsed, raw, months):
    """Zero months means "everybody who ever came", which is the campaign this
    module exists to make impossible to send by accident."""
    from app.models import Setting
    from app.utils.recall import after_months

    with lapsed["app"].app_context():
        Setting.set("recall_after_months", raw)
        lapsed["db"].session.commit()
        assert after_months() == months


def test_the_cutoff_counts_calendar_months_not_thirty_day_blocks(lapsed):
    """"A year since we saw them" should mean the same date, not eleven days
    early — the difference decides who is on a list of hundreds."""
    from app.utils.recall import cutoff

    with lapsed["app"].app_context():
        assert cutoff(12, date(2026, 8, 10)) == date(2025, 8, 10)
        assert cutoff(3, date(2026, 1, 15)) == date(2025, 10, 15)
        # The 31st of a month whose target has no 31st.
        assert cutoff(1, date(2026, 3, 31)) == date(2026, 2, 28)


# --- and who is not --------------------------------------------------------

def test_an_archived_file_is_never_recalled(lapsed):
    """The clinic has already decided that patient is off its books.

    Messaging them anyway is the program quietly overruling that.
    """
    with lapsed["app"].app_context():
        from app.models import Patient
        from app.utils.recall import candidates
        db = lapsed["db"]

        child = db.session.get(Patient, lapsed["ids"]["child"])
        child.is_active = False
        db.session.commit()
        assert candidates() == [], "an archived family was queued for a message"


def test_a_recall_window_past_the_archive_window_says_so(lapsed):
    """The empty list nobody could explain.

    Archiving retires a file after N years; a recall window at or past that
    selects nobody, because everything that old has already gone. Without this
    the screen is empty and looks broken.
    """
    from app.models import Setting
    from app.utils.recall import archive_conflict

    with lapsed["app"].app_context():
        Setting.set("archive_inactive_years", "3")
        Setting.set("recall_after_months", "12")
        lapsed["db"].session.commit()
        assert archive_conflict() is False

        Setting.set("recall_after_months", "36")
        lapsed["db"].session.commit()
        assert archive_conflict() is True

    body = lapsed["sign_in"]("boss").get("/messages/recall").data.decode()
    assert "أطول من مدة الأرشفة" in body


def test_a_family_that_opted_out_is_not_on_the_list(lapsed):
    """They asked not to be messaged. That is the whole of the answer."""
    with lapsed["app"].app_context():
        from app.models import Patient
        from app.utils.recall import candidates
        db = lapsed["db"]

        db.session.get(Patient, lapsed["ids"]["child"]).wa_opt_out = True
        db.session.commit()
        assert candidates() == []


def test_a_file_that_never_had_a_visit_is_not_lapsed(lapsed):
    """It is a file somebody opened and never used.

    "We have not seen you since…" about a visit that never happened reads as a
    mistake, because it is one.
    """
    with lapsed["app"].app_context():
        from datetime import datetime

        from app.models import Patient
        from app.utils.recall import candidates
        db = lapsed["db"]

        never = Patient(patient_number="P-NEVER", full_name="ملف فاضي",
                        gender="female", date_of_birth=date(2020, 1, 1),
                        is_active=True, own_phone="01099999999",
                        created_at=datetime(2020, 1, 1))
        db.session.add(never)
        db.session.commit()

        ids = [p.id for p, _ in candidates()]
        assert never.id not in ids


def test_nobody_is_recalled_twice_in_six_months(lapsed):
    """One message is an offer. The second is the clinic nagging.

    And the button is one somebody presses, so it *will* be pressed twice.
    """
    boss = lapsed["sign_in"]("boss")
    boss.post("/messages/recall/send", follow_redirects=True)

    with lapsed["app"].app_context():
        assert len(_sent(lapsed)) == 1
        from app.utils.recall import candidates
        assert candidates() == [], "the family is still on the list after sending"

    boss.post("/messages/recall/send", follow_redirects=True)
    with lapsed["app"].app_context():
        assert len(_sent(lapsed)) == 1, "a second press sent a second message"


# --- how it is sent --------------------------------------------------------

def test_it_is_a_list_somebody_presses_not_a_sweep_that_runs(lapsed):
    """Nothing schedules this and nothing fires it.

    Every other type in the hub can be automatic; this one reaches families who
    are not talking to the clinic, and that is not a thing to leave running.
    """
    from app.utils import recall

    source = open(recall.__file__, encoding="utf-8").read()
    for scheduler in ("scheduled_at", "dispatch_due", "delay_hours"):
        assert scheduler not in source, (
            f"the recall module reaches for {scheduler} — it is meant to be "
            "sent by a person")


def test_sending_obeys_the_cap_the_clinic_already_set(lapsed):
    """No cap of its own.

    The daily cap covers all messages; a second quieter limit under it would
    disagree with the one the clinic set the first time either changed.
    """
    import re

    from app.utils import recall

    source = open(recall.__file__, encoding="utf-8").read()
    # Code only: the module's own prose explains *why* there is no per-type
    # cap, and a plain substring search matched that explanation and passed
    # for the wrong reason.
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    code = re.sub(r'(?s)""".*?"""', "", code)
    assert "daily_cap" not in code, "the recall grew a second, quieter cap"
    # …and it goes through the ordinary send path, which is where the cap,
    # the window and the opt-out live.
    assert "wa.send(" in code


def test_the_message_neither_hurries_nor_blames(lapsed):
    """A family that stopped coming may have moved, or changed doctor, or have
    a well child. The clinic knows none of it."""
    from app.models import TEMPLATE_DEFAULTS

    body = TEMPLATE_DEFAULTS[TYPE]
    for wrong in ("للأسف", "لازم", "إهمال", "متأخر", "خطر"):
        assert wrong not in body
    assert "{date}" in body and "{clinic}" in body


def test_the_screen_shows_the_families_and_their_last_visit(lapsed):
    """A list of names with no dates is a list nobody can sanity-check."""
    body = lapsed["sign_in"]("boss").get("/messages/recall").data.decode()
    with lapsed["app"].app_context():
        from app.models import Patient
        from app.utils.clock import local_today
        name = lapsed["db"].session.get(
            Patient, lapsed["ids"]["child"]).display_name("ar")
        seen = (local_today() - timedelta(days=730)).isoformat()
    assert name in body
    assert seen in body
