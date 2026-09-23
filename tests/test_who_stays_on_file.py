"""Who the archive takes, and who it leaves alone.

Asked for from the clinic: *"الارشفه موجود شرط خامل … ممكن نضيف الى عمره
يزيد عن سن معين واستثناء اشخاص بعينهم … علشان الناس الى عندها امراض مزمنة …
وينفع استدعائه طبعاً فى اي وقت"*.

Two ways onto the list (no visits for N years, or reaching an age the clinic
sets) and two ways off it (a file marked «ما يتأرشفش», or — when the clinic
turns it on — a chronic condition on file). Both new rules start off: an
update must change nothing for a running clinic.
"""
from datetime import date, timedelta

import pytest


def _born(years_ago, today, days=0):
    """A birthday exactly ``years_ago`` years before ``today``, then
    ``days`` further back (positive) or forward (negative)."""
    return today.replace(year=today.year - years_ago) - timedelta(days=days)


@pytest.fixture
def roster(clinic):
    """The fixture's child (seen today), plus a young adult seen today."""
    from app.models import Patient, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        today = local_today()
        grown = Patient(patient_number="P2", full_name="شاب", gender="male",
                        date_of_birth=_born(18, today), is_active=True)
        db.session.add(grown)
        db.session.flush()
        db.session.add(Visit(patient_id=grown.id, doctor_id=clinic["ids"]["doctor"],
                             visit_date=today))
        db.session.commit()
        clinic["ids"]["grown"] = grown.id
    return clinic


def _set(clinic, **values):
    from app.models import Setting

    with clinic["app"].app_context():
        for key, value in values.items():
            Setting.set(key, value)
        clinic["db"].session.commit()


def _lists(clinic):
    from app.utils.archiving import review

    with clinic["app"].app_context():
        lists = review()
        return ({row["patient"].id: row["why"] for row in lists["due"]},
                {row["patient"].id: row["kept"] for row in lists["kept"]})


def _patient(clinic, key, **changes):
    from app.models import Patient

    with clinic["app"].app_context():
        p = clinic["db"].session.get(Patient, clinic["ids"][key])
        for name, value in changes.items():
            setattr(p, name, value)
        clinic["db"].session.commit()


# ------------------------------------------------ nothing changes by itself --
def test_an_update_archives_nobody_new(roster):
    """No age set: an adult seen today is not on the list. The rule exists
    only once the clinic typed an age."""
    due, kept = _lists(roster)
    assert due == {} and kept == {}


@pytest.mark.parametrize("raw", ["", "0", "-4", "abc", "  "])
def test_a_blank_or_nonsense_age_is_off(roster, raw):
    _set(roster, archive_age_years=raw)
    due, _kept = _lists(roster)
    assert roster["ids"]["grown"] not in due


# -------------------------------------------------------------- the age ----
def test_reaching_the_age_puts_a_file_on_the_list(roster):
    """Seen today, and still on the list — that is the whole point of the
    age rule. The child is not."""
    _set(roster, archive_age_years="18")
    due, _kept = _lists(roster)
    assert due == {roster["ids"]["grown"]: "aged_out"}


def test_the_day_before_the_birthday_is_not_the_age(roster):
    from app.utils.clock import local_today

    with roster["app"].app_context():
        today = local_today()
    _patient(roster, "grown", date_of_birth=_born(18, today, days=-1))
    _set(roster, archive_age_years="18")
    due, _kept = _lists(roster)
    assert roster["ids"]["grown"] not in due


def test_a_file_that_meets_both_is_listed_once_as_inactive(roster):
    from app.models import Visit
    from app.utils.clock import local_today

    with roster["app"].app_context():
        for v in Visit.query.filter_by(patient_id=roster["ids"]["grown"]):
            v.visit_date = local_today() - timedelta(days=365 * 5)
        roster["db"].session.commit()
    _set(roster, archive_age_years="18")
    due, _kept = _lists(roster)
    assert due[roster["ids"]["grown"]] == "inactive"


# ----------------------------------------------------------- «ما يتأرشفش» --
def test_an_exempt_file_is_kept_and_says_why(roster):
    _set(roster, archive_age_years="18")
    _patient(roster, "grown", archive_exempt=True)
    due, kept = _lists(roster)
    assert roster["ids"]["grown"] not in due
    assert kept == {roster["ids"]["grown"]: "exempt"}


def test_the_sweep_leaves_an_exempt_file_alone(roster):
    from app.models import Patient
    from app.utils.archiving import auto_archive

    _set(roster, archive_age_years="18")
    _patient(roster, "grown", archive_exempt=True)
    with roster["app"].app_context():
        assert auto_archive() == 0
        assert roster["db"].session.get(Patient, roster["ids"]["grown"]).is_active


def test_the_sweep_takes_the_aged_out_file(roster):
    from app.models import Patient
    from app.utils.archiving import auto_archive

    _set(roster, archive_age_years="18")
    with roster["app"].app_context():
        assert auto_archive() == 1
        p = roster["db"].session.get(Patient, roster["ids"]["grown"])
        assert not p.is_active and p.archive_reason == "auto"
        assert roster["db"].session.get(Patient, roster["ids"]["child"]).is_active


def test_lifting_an_exemption_writes_no_not_nobody(roster):
    """Somebody decided. ``False`` is that decision; ``None`` is a file
    nobody was ever asked about."""
    from app.models import Patient, User
    from app.utils.archiving import exempt

    with roster["app"].app_context():
        db = roster["db"]
        p = db.session.get(Patient, roster["ids"]["grown"])
        boss = db.session.get(User, roster["ids"]["admin"])
        exempt(p, user=boss)
        exempt(p, user=boss, on=False)
        db.session.commit()
        assert p.archive_exempt is False
        assert p.archive_exempt_by == boss.id
        assert p.archive_exempt_at is not None
    _set(roster, archive_age_years="18")
    due, _kept = _lists(roster)
    assert roster["ids"]["grown"] in due


# ------------------------------------------------------------- chronic -----
def _chronic_by(clinic, source):
    """Give the grown patient a chronic condition in one of the three places
    a file says it."""
    from app.models import Patient, PatientMedication, PatientProblem

    with clinic["app"].app_context():
        db = clinic["db"]
        pid = clinic["ids"]["grown"]
        if source == "box":
            db.session.get(Patient, pid).chronic_diseases = "ربو شعبي"
        elif source == "problem":
            db.session.add(PatientProblem(patient_id=pid, title="صرع",
                                          status="active"))
        elif source == "medicine":
            db.session.add(PatientMedication(patient_id=pid, name="Depakine"))
        db.session.commit()


@pytest.mark.parametrize("source", ["box", "problem", "medicine"])
def test_a_chronic_condition_is_spared_when_the_clinic_says_so(roster, source):
    _chronic_by(roster, source)
    _set(roster, archive_age_years="18", archive_spare_chronic="1")
    due, kept = _lists(roster)
    assert roster["ids"]["grown"] not in due
    assert kept == {roster["ids"]["grown"]: "chronic"}


@pytest.mark.parametrize("source", ["box", "problem", "medicine"])
def test_chronic_is_not_spared_until_turned_on(roster, source):
    """Off by default: turning it on stops the sweep taking files it took
    yesterday, and that is the clinic's call."""
    _chronic_by(roster, source)
    _set(roster, archive_age_years="18")
    due, _kept = _lists(roster)
    assert roster["ids"]["grown"] in due


def test_what_is_over_is_not_chronic(roster):
    """A resolved problem, a stopped medicine and a blank box say nothing
    about now."""
    from app.models import Patient, PatientMedication, PatientProblem

    with roster["app"].app_context():
        db = roster["db"]
        pid = roster["ids"]["grown"]
        db.session.get(Patient, pid).chronic_diseases = "   "
        db.session.add(PatientProblem(patient_id=pid, title="التهاب رئوي",
                                      status="resolved"))
        db.session.add(PatientMedication(patient_id=pid, name="Augmentin",
                                         stopped_on=date(2024, 1, 1)))
        db.session.commit()
    _set(roster, archive_age_years="18", archive_spare_chronic="1")
    due, kept = _lists(roster)
    assert roster["ids"]["grown"] in due
    assert kept == {}


def test_exempt_is_named_before_chronic(roster):
    """A person decided; that is the reason worth showing."""
    _chronic_by(roster, "box")
    _patient(roster, "grown", archive_exempt=True)
    _set(roster, archive_age_years="18", archive_spare_chronic="1")
    _due, kept = _lists(roster)
    assert kept == {roster["ids"]["grown"]: "exempt"}


def test_chronic_costs_three_queries_not_three_per_file(roster):
    from sqlalchemy import event

    from app.utils.archiving import chronic_ids

    with roster["app"].app_context():
        engine = roster["db"].engine
        seen = []

        def count(*_a, **_k):
            seen.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            chronic_ids(range(1, 200))
        finally:
            event.remove(engine, "before_cursor_execute", count)
    assert len(seen) == 3


# ------------------------------------------------------ recall any time ----
def test_a_recalled_file_past_the_age_stays_recalled(roster):
    """Nobody gets younger: without this the next sweep archives the file
    somebody just brought back."""
    from app.models import Patient
    from app.utils.archiving import auto_archive

    _set(roster, archive_age_years="18")
    with roster["app"].app_context():
        auto_archive()
    boss = roster["sign_in"]("boss")
    reply = boss.post(f"/patients/{roster['ids']['grown']}/restore",
                      follow_redirects=True)
    assert reply.status_code == 200
    with roster["app"].app_context():
        assert auto_archive() == 0
        p = roster["db"].session.get(Patient, roster["ids"]["grown"])
        assert p.is_active and p.archive_exempt is True
        assert p.archive_exempt_by == roster["ids"]["admin"]


def test_a_plain_recall_marks_nothing(roster):
    """Under the age, a restore is just a restore — as it always was."""
    from app.models import Patient
    from app.utils.archiving import archive_patient, restore_patient

    with roster["app"].app_context():
        p = roster["db"].session.get(Patient, roster["ids"]["grown"])
        archive_patient(p)
        assert restore_patient(p) is True
        assert p.archive_exempt is None


# ------------------------------------------------------------ on screen ----
def test_the_policy_form_saves_the_age_and_the_chronic_switch(roster):
    from app.models import Setting

    boss = roster["sign_in"]("boss")
    boss.post("/patients/archive/settings",
              data={"years": "3", "age_years": "19", "spare_chronic": "1"})
    with roster["app"].app_context():
        assert Setting.get("archive_age_years") == "19"
        assert Setting.get("archive_spare_chronic") == "1"
    boss.post("/patients/archive/settings", data={"years": "3", "age_years": ""})
    with roster["app"].app_context():
        assert Setting.get("archive_age_years") == ""
        assert Setting.get("archive_spare_chronic") == "0"


def test_the_screen_shows_why_and_who_was_kept(roster):
    _set(roster, archive_age_years="18")
    boss = roster["sign_in"]("boss")
    page = boss.get("/patients/archive").get_data(as_text=True)
    assert f'data-archive-due="{roster["ids"]["grown"]}"' in page
    assert "data-archive-kept" not in page

    boss.post(f"/patients/{roster['ids']['grown']}/archive-exempt",
              data={"on": "1"})
    page = boss.get("/patients/archive").get_data(as_text=True)
    assert f'data-archive-kept="{roster["ids"]["grown"]}"' in page
    assert f'data-archive-due="{roster["ids"]["grown"]}"' not in page


def test_exempting_from_the_file_is_logged(roster):
    from app.models import ActivityLog, Patient

    boss = roster["sign_in"]("boss")
    page = boss.get(f"/patients/{roster['ids']['grown']}").get_data(as_text=True)
    assert 'data-archive-exempt="0"' in page
    boss.post(f"/patients/{roster['ids']['grown']}/archive-exempt",
              data={"on": "1"})
    page = boss.get(f"/patients/{roster['ids']['grown']}").get_data(as_text=True)
    assert 'data-archive-exempt="1"' in page
    with roster["app"].app_context():
        assert roster["db"].session.get(Patient, roster["ids"]["grown"]).archive_exempt
        assert ActivityLog.query.filter_by(
            action="patient.archive_exempt",
            entity_id=roster["ids"]["grown"]).count() == 1
