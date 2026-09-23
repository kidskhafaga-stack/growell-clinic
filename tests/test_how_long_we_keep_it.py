"""`IMT.07` — how long each type of document is kept, and the destruction log.

*"Retention time for each type of document … Data destruction procedures"*;
the surveyor *"may review the list of retention time for different types of
information"* and *"may observe the record/logbook of document destruction"*.

The rules this file holds the screen to:

* **The period is the clinic's number.** Every type starts unset and says so;
  the program invents no default.
* **It counts, it never deletes.** "312 prescriptions are past their period"
  and nothing more — there is no path from this screen to removing a record.
* **The log is only ever added to.**
"""
from datetime import date, datetime, timedelta

import pytest

from app.utils.clock import local_today


def _years_ago(n, today=None, days=0):
    today = today or local_today()
    return today.replace(year=today.year - n) - timedelta(days=days)


def _overview(clinic):
    from app.utils import retention

    with clinic["app"].app_context():
        return {row["key"]: row for row in retention.overview()}


def _rule(clinic, doc_type, years, basis=None):
    from app.utils import retention

    with clinic["app"].app_context():
        retention.set_rule(doc_type, years, basis=basis)
        clinic["db"].session.commit()


# ------------------------------------------------------- nobody said yet ----
def test_every_type_starts_unset(clinic):
    """No invented periods: a number nobody chose would read as policy."""
    rows = _overview(clinic)
    from app.utils.retention import DOC_TYPES

    assert list(rows) == list(DOC_TYPES)
    for row in rows.values():
        assert row["years"] is None
        assert row["past"] is None, row["key"]


def test_the_screen_says_how_many_are_unset(clinic):
    from app.utils.retention import DOC_TYPES

    page = clinic["sign_in"]("boss").get("/users/retention").get_data(as_text=True)
    assert "data-retention-unset" in page
    assert page.count("data-years-unset") == len(DOC_TYPES)


# ---------------------------------------------------------- setting one ----
def test_a_period_is_saved_with_its_reference_and_who(clinic):
    from app.models import RetentionRule

    boss = clinic["sign_in"]("boss")
    boss.post("/users/retention/rule/visits",
              data={"years": "25", "basis": "قانون ١٥٤ لسنة ٢٠١٩"})
    with clinic["app"].app_context():
        rule = RetentionRule.query.filter_by(doc_type="visits").one()
        assert rule.years == 25
        assert rule.basis == "قانون ١٥٤ لسنة ٢٠١٩"
        assert rule.set_by == clinic["ids"]["admin"]
        assert rule.set_at is not None


def test_blank_clears_to_unset_not_zero(clinic):
    _rule(clinic, "visits", 10)
    _rule(clinic, "visits", "")
    row = _overview(clinic)["visits"]
    assert row["years"] is None and row["past"] is None


@pytest.mark.parametrize("raw", ["0", "101", "-3", "abc", "2.5"])
def test_a_nonsense_period_is_refused_and_nothing_changes(clinic, raw):
    from app.models import RetentionRule

    _rule(clinic, "visits", 10)
    reply = clinic["sign_in"]("boss").post(
        "/users/retention/rule/visits", data={"years": raw},
        follow_redirects=True)
    assert reply.status_code == 200
    with clinic["app"].app_context():
        assert RetentionRule.query.filter_by(doc_type="visits").one().years == 10


def test_an_unknown_type_is_refused(clinic):
    from app.models import RetentionRule

    clinic["sign_in"]("boss").post("/users/retention/rule/everything",
                                   data={"years": "1"})
    with clinic["app"].app_context():
        assert RetentionRule.query.count() == 0


# ------------------------------------------------------------- counting ----
def test_past_counts_only_what_is_older_than_the_period(clinic):
    """The fixture's visit is today; add one just inside the period and one
    just outside it."""
    from app.models import Visit

    with clinic["app"].app_context():
        db = clinic["db"]
        for when in (_years_ago(10), _years_ago(10, days=1)):
            db.session.add(Visit(patient_id=clinic["ids"]["child"],
                                 doctor_id=clinic["ids"]["doctor"],
                                 visit_date=when))
        db.session.commit()
    _rule(clinic, "visits", 10)
    row = _overview(clinic)["visits"]
    assert row["total"] == 3
    assert row["past"] == 1
    assert row["oldest"] == _years_ago(10, days=1)


def test_a_datetime_column_counts_the_same_way(clinic):
    from app.models import ActivityLog

    with clinic["app"].app_context():
        db = clinic["db"]
        old = datetime.combine(_years_ago(6), datetime.min.time())
        db.session.add(ActivityLog(action="x", created_at=old))
        db.session.add(ActivityLog(action="y"))
        db.session.commit()
    _rule(clinic, "activity", 5)
    row = _overview(clinic)["activity"]
    assert row["past"] == 1
    assert row["oldest"] == _years_ago(6)


def test_an_open_stay_never_passes_its_period(clinic):
    """A stay is counted from its discharge. One still open has not started
    its clock — however long ago the child came in."""
    from app.models import Admission

    with clinic["app"].app_context():
        db = clinic["db"]
        long_ago = datetime.combine(_years_ago(30), datetime.min.time())
        db.session.add(Admission(patient_id=clinic["ids"]["child"],
                                 admitted_at=long_ago))
        db.session.add(Admission(patient_id=clinic["ids"]["child"],
                                 admitted_at=long_ago,
                                 discharged_at=long_ago + timedelta(days=3)))
        db.session.commit()
    _rule(clinic, "admissions", 10)
    row = _overview(clinic)["admissions"]
    assert row["total"] == 1
    assert row["past"] == 1


def test_counting_deletes_nothing(clinic):
    from app.models import Visit

    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(Visit(patient_id=clinic["ids"]["child"],
                             doctor_id=clinic["ids"]["doctor"],
                             visit_date=_years_ago(40)))
        db.session.commit()
    _rule(clinic, "visits", 1)
    boss = clinic["sign_in"]("boss")
    page = boss.get("/users/retention").get_data(as_text=True)
    assert 'data-past="1"' in page
    with clinic["app"].app_context():
        assert Visit.query.count() == 2


def _queries(clinic):
    from sqlalchemy import event

    from app.utils import retention

    with clinic["app"].app_context():
        engine = clinic["db"].engine
        seen = []

        def count(*_a, **_k):
            seen.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            retention.overview()
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(seen)


def test_one_query_per_type_however_much_is_on_file(clinic):
    """A clinic with a hundred thousand visits opens this page as fast as one
    with ten: the count, the oldest and the past are one row per type — plus
    the rules and the clinic's clock, once each."""
    from app.models import Visit
    from app.utils import retention

    for key in retention.DOC_TYPES:
        _rule(clinic, key, 5)
    before = _queries(clinic)
    with clinic["app"].app_context():
        db = clinic["db"]
        for n in range(60):
            db.session.add(Visit(patient_id=clinic["ids"]["child"],
                                 doctor_id=clinic["ids"]["doctor"],
                                 visit_date=_years_ago(n % 12)))
        db.session.commit()
    assert _queries(clinic) == before
    assert before <= len(retention.DOC_TYPES) + 2


# ------------------------------------------------------ the logbook ----
def _log(clinic, **form):
    data = {"done_on": local_today().isoformat(), "doc_type": "other",
            "what": "ملفات ورق زيارات ٢٠١٠", "method": "تقطيع"}
    data.update(form)
    return clinic["sign_in"]("boss").post("/users/retention/destroyed",
                                          data=data, follow_redirects=True)


def test_a_destruction_is_logged_with_who(clinic):
    from app.models import ActivityLog, RecordDestruction

    reply = _log(clinic, witness="أ. سامية")
    page = reply.get_data(as_text=True)
    assert "data-destroyed=" in page
    with clinic["app"].app_context():
        row = RecordDestruction.query.one()
        assert row.witness == "أ. سامية"
        assert row.recorded_by == clinic["ids"]["admin"]
        assert ActivityLog.query.filter_by(action="retention.destroyed").count() == 1


@pytest.mark.parametrize("field", ["what", "method", "done_on"])
def test_a_line_without_the_essentials_is_refused(clinic, field):
    from app.models import RecordDestruction

    _log(clinic, **{field: ""})
    with clinic["app"].app_context():
        assert RecordDestruction.query.count() == 0


def test_a_future_date_is_refused(clinic):
    from app.models import RecordDestruction

    _log(clinic, done_on=(local_today() + timedelta(days=1)).isoformat())
    with clinic["app"].app_context():
        assert RecordDestruction.query.count() == 0


def test_an_unknown_type_is_refused_in_the_log(clinic):
    from app.models import RecordDestruction

    _log(clinic, doc_type="patients")
    with clinic["app"].app_context():
        assert RecordDestruction.query.count() == 0


def test_the_log_has_no_door_out(clinic):
    """Added to, never edited or removed: the only routes on this screen are
    the page, a period, and a new line."""
    rules = {rule.endpoint for rule in clinic["app"].url_map.iter_rules()
             if rule.endpoint.startswith("users.retention")}
    assert rules == {"users.retention", "users.retention_rule",
                     "users.retention_destroyed"}


# ------------------------------------------------------------ who ----
@pytest.mark.parametrize("who", ["doc", "desk", "acct"])
def test_only_the_admin_opens_it(clinic, who):
    from app.models import RecordDestruction, RetentionRule

    client = clinic["sign_in"](who)
    assert client.get("/users/retention").status_code in (302, 403)
    client.post("/users/retention/rule/visits", data={"years": "3"})
    client.post("/users/retention/destroyed",
                data={"done_on": date.today().isoformat(), "doc_type": "other",
                      "what": "x", "method": "y"})
    with clinic["app"].app_context():
        assert RetentionRule.query.count() == 0
        assert RecordDestruction.query.count() == 0


def test_it_is_reached_from_the_users_screen(clinic):
    page = clinic["sign_in"]("boss").get("/users/").get_data(as_text=True)
    assert "/users/retention" in page


def test_the_page_prints_with_a_header(clinic):
    page = clinic["sign_in"]("boss").get("/users/retention").get_data(as_text=True)
    assert 'class="print-only"' in page
    assert "data-never-deletes" in page


def test_wiping_the_data_keeps_the_periods_and_the_log(clinic):
    """«امسح البيانات» starts the work over. It does not unmake the fact
    that paper was destroyed, nor the clinic's policy."""
    from app.models import RecordDestruction, RetentionRule
    from app.utils import wipe

    _rule(clinic, "visits", 10)
    _log(clinic)
    with clinic["app"].app_context():
        assert "retention_rules" not in wipe.wiped_tables()
        assert "record_destructions" not in wipe.wiped_tables()
        wipe.wipe()
        clinic["db"].session.commit()
        assert RetentionRule.query.count() == 1
        assert RecordDestruction.query.count() == 1
