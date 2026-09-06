"""The specialty alerts, and the number a clinic had nowhere to write.

The survey asked every specialty *"متى ينبّهك البرنامج من نفسه؟"* and a hundred
and three alerts came back. Twenty-two of them are a **threshold** — HbA1c
above a figure, saturation below one, ferritin over a limit — and the survey
refuses to supply the figure: its own answer for cardiology is *"لا يوجد رقم
موحّد"*.

This program does not invent clinical numbers, so those alerts were declared
and dormant. That was right. What was wrong is what happened next: **there was
nowhere for a clinic to write its figure down**, so they stayed dormant for
ever. A feature built and no door to it.

Two halves, and neither is any use alone:

* the **catalogue** says what each alert watches — a lab result by its own
  stable code, a vital sign, a reading the panel takes, the child's age, or an
  order that never came back. It contains no clinical number and never will;
* the **clinic** says when to worry, on a screen of its own, and that number
  is a row in their database that an update never touches.

And the honesty rule the module was built on still holds throughout: an alert
with no number behind it does not fire, and a screen never merges *"we did not
look"* with *"we looked and it is fine"*.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def specialty(clinic):
    """A clinic with the panels module on and the test catalogue seeded."""
    from app.models import Setting
    from app.utils.investigations import seed_investigations

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        clinic["db"].session.commit()
        seed_investigations()
    return clinic


def _set_number(specialty, panel, code, value, active="1"):
    return specialty["sign_in"]("boss").post("/panels/alerts/set", data={
        "panel_key": panel, "alert_code": code,
        "threshold": "" if value is None else str(value),
        "is_active": active}, follow_redirects=True)


def _lab_result(specialty, code, value, days_ago=0):
    """A resulted test on this child, as the lab or the visit screen writes."""
    from app.models import Investigation, Visit, VisitInvestigation
    from app.utils.clock import local_today

    with specialty["app"].app_context():
        test = Investigation.query.filter_by(code=code).first()
        assert test is not None, f"no seeded investigation for {code}"
        visit = Visit(patient_id=specialty["ids"]["child"],
                      doctor_id=specialty["ids"]["doctor"],
                      visit_date=local_today() - timedelta(days=days_ago))
        specialty["db"].session.add(visit)
        specialty["db"].session.flush()
        row = VisitInvestigation(
            visit_id=visit.id, patient_id=specialty["ids"]["child"],
            investigation_id=test.id, kind="lab", name=test.name_ar,
            status="resulted", result_value=value,
            resulted_at=datetime.utcnow() - timedelta(days=days_ago))
        specialty["db"].session.add(row)
        specialty["db"].session.commit()
        return row.id


def _fired(specialty, keys):
    from app.utils import panel_alerts

    with specialty["app"].app_context():
        return {a["code"] for a in
                panel_alerts.evaluate(specialty["ids"]["child"], keys)}


# ===================== nothing fires without a clinic's number ==============
def test_a_threshold_alert_is_dormant_until_somebody_writes_a_number(specialty):
    """**Where this started, and where a fresh install stays.** The reading is
    there, the alert is declared, and the program says nothing — because
    nobody has told it what "too high" means for their children."""
    _lab_result(specialty, "hba1c", 11.0)

    assert _fired(specialty, ["endocrinology"]) == set()


def test_writing_the_number_is_what_arms_it(specialty):
    """The door that did not exist."""
    _lab_result(specialty, "hba1c", 11.0)

    _set_number(specialty, "endocrinology", "hba1c_high", 8)

    assert "hba1c_high" in _fired(specialty, ["endocrinology"])


def test_the_number_is_the_clinics_and_a_reading_under_it_says_nothing(specialty):
    """Two clinics, two answers, and neither is the program's opinion."""
    _lab_result(specialty, "hba1c", 7.4)

    _set_number(specialty, "endocrinology", "hba1c_high", 8)
    assert _fired(specialty, ["endocrinology"]) == set()

    _set_number(specialty, "endocrinology", "hba1c_high", 7)
    assert "hba1c_high" in _fired(specialty, ["endocrinology"])


def test_clearing_the_number_disarms_it_again(specialty):
    """A clinic that thinks better of a figure has to be able to take it
    back, and taking it back must actually stop the warning."""
    _lab_result(specialty, "hba1c", 11.0)
    _set_number(specialty, "endocrinology", "hba1c_high", 8)
    assert "hba1c_high" in _fired(specialty, ["endocrinology"])

    _set_number(specialty, "endocrinology", "hba1c_high", None)

    assert _fired(specialty, ["endocrinology"]) == set()


def test_switching_it_off_keeps_the_number(specialty):
    """Silencing an alert for a month should not make somebody remember what
    it was set to."""
    from app.models import PanelAlertRule

    _lab_result(specialty, "hba1c", 11.0)
    _set_number(specialty, "endocrinology", "hba1c_high", 8)
    _set_number(specialty, "endocrinology", "hba1c_high", 8, active="0")

    assert _fired(specialty, ["endocrinology"]) == set()
    with specialty["app"].app_context():
        row = PanelAlertRule.query.filter_by(panel_key="endocrinology",
                                             alert_code="hba1c_high").one()
        assert row.threshold == 8
        assert not row.is_active


# ===================== the four comparisons ================================
def test_a_below_alert_fires_under_the_number_not_over_it(specialty):
    """Direction is in the catalogue, not in the reader's head: ANC *below*
    the figure, HbA1c *above* it, and the same screen sets both."""
    _lab_result(specialty, "anc", 400)

    _set_number(specialty, "oncology", "anc_low", 500)

    assert "anc_low" in _fired(specialty, ["oncology"])


def test_a_below_alert_is_silent_above_the_number(specialty):
    _lab_result(specialty, "anc", 1500)

    _set_number(specialty, "oncology", "anc_low", 500)

    assert _fired(specialty, ["oncology"]) == set()


def test_an_overdue_alert_counts_the_months_since_the_last_one(specialty):
    """"No HbA1c since" is a date the program already holds — the clinic only
    says how many months is too many."""
    _lab_result(specialty, "hba1c", 7.0, days_ago=240)

    _set_number(specialty, "endocrinology", "no_hba1c", 6)

    assert "no_hba1c" in _fired(specialty, ["endocrinology"])


def test_a_recent_test_is_not_overdue(specialty):
    _lab_result(specialty, "hba1c", 7.0, days_ago=20)

    _set_number(specialty, "endocrinology", "no_hba1c", 6)

    assert _fired(specialty, ["endocrinology"]) == set()


def test_never_having_had_the_test_is_the_strongest_case_of_overdue(specialty):
    """Not "overdue by nothing". A child the specialty follows *by* a test who
    has never had one is exactly who this alert is for, and reporting silence
    would hide them behind the ones who are merely late."""
    _set_number(specialty, "endocrinology", "no_hba1c", 6)

    assert "no_hba1c" in _fired(specialty, ["endocrinology"])


def test_an_ordered_test_that_never_came_back_fires_after_the_days_set(specialty):
    """A culture asked for and no result. The wait is the reading."""
    from app.models import Investigation, VisitInvestigation

    with specialty["app"].app_context():
        test = Investigation.query.filter_by(code="urine_culture").first()
        assert test is not None
        specialty["db"].session.add(VisitInvestigation(
            visit_id=specialty["ids"]["visit"],
            patient_id=specialty["ids"]["child"],
            investigation_id=test.id, kind="lab", name=test.name_ar,
            status="requested",
            created_at=datetime.utcnow() - timedelta(days=9)))
        specialty["db"].session.commit()

    _set_number(specialty, "infectious", "culture_pending", 5)

    assert "culture_pending" in _fired(specialty, ["infectious"])


def test_an_answered_culture_is_not_pending(specialty):
    from app.models import Investigation, VisitInvestigation

    with specialty["app"].app_context():
        test = Investigation.query.filter_by(code="urine_culture").first()
        specialty["db"].session.add(VisitInvestigation(
            visit_id=specialty["ids"]["visit"],
            patient_id=specialty["ids"]["child"],
            investigation_id=test.id, kind="lab", name=test.name_ar,
            status="resulted", result_text="لا نمو",
            resulted_at=datetime.utcnow(),
            created_at=datetime.utcnow() - timedelta(days=9)))
        specialty["db"].session.commit()

    _set_number(specialty, "infectious", "culture_pending", 5)

    assert _fired(specialty, ["infectious"]) == set()


def test_an_age_alert_reads_the_childs_own_age(specialty):
    """"Never had their sight checked and is older than the age you set" needs
    no new data at all — the birthday is in the file."""
    from app.models import Patient
    from app.utils.clock import local_today

    with specialty["app"].app_context():
        child = specialty["db"].session.get(Patient, specialty["ids"]["child"])
        child.date_of_birth = local_today() - timedelta(days=365 * 6)
        specialty["db"].session.commit()

    _set_number(specialty, "ophthalmology", "never_examined", 48)

    assert "never_examined" in _fired(specialty, ["ophthalmology"])


def test_a_vital_sign_alert_reads_the_last_one_taken(specialty):
    """Saturation is a vital, not a cardiology reading — three specialties
    asked for it, which is the argument for it belonging to none of them."""
    from app.models import VitalSigns

    with specialty["app"].app_context():
        specialty["db"].session.add(VitalSigns(
            visit_id=specialty["ids"]["visit"], spo2=88))
        specialty["db"].session.commit()

    _set_number(specialty, "cardiology", "spo2_low", 92)

    assert "spo2_low" in _fired(specialty, ["cardiology"])


def test_a_panel_reading_alert_reads_what_the_panel_took(specialty):
    """The specialty's own measurement, from the visit screen."""
    from app.models import Measurement

    with specialty["app"].app_context():
        specialty["db"].session.add(Measurement(
            patient_id=specialty["ids"]["child"],
            visit_id=specialty["ids"]["visit"], panel="infectious",
            code="fever_days", value_num=9))
        specialty["db"].session.commit()

    _set_number(specialty, "infectious", "fever_long", 5)

    assert "fever_long" in _fired(specialty, ["infectious"])


# ===================== the honesty rules ===================================
def test_only_alerts_the_program_can_answer_get_a_box(specialty):
    """An alert whose reading we do not hold would collect a number and change
    nothing — which is worse than saying plainly that it waits on something
    else."""
    from app.utils import panel_alerts

    with specialty["app"].app_context():
        offered = {a["code"] for a in panel_alerts.watchable("cardiology")}
        declared = {a["code"] for a in panel_alerts.declared("cardiology")}

    assert "spo2_low" in offered
    # Declared, real, and not answerable from what this program holds.
    assert "penicillin_late" in declared
    assert "penicillin_late" not in offered


def test_an_alert_nobody_can_answer_cannot_be_armed_by_posting_at_it(specialty):
    """A posted pair that names no answerable alert would sit in the table for
    ever, arming nothing and appearing on no screen."""
    from app.models import PanelAlertRule

    _set_number(specialty, "cardiology", "penicillin_late", 30)
    _set_number(specialty, "cardiology", "made_up_alert", 30)

    with specialty["app"].app_context():
        assert PanelAlertRule.query.count() == 0


def test_what_is_still_waiting_stops_counting_once_it_is_armed(specialty):
    """The number on the screen has to go down as somebody works through it,
    or the screen reads as incomplete for ever."""
    from app.utils import panel_alerts

    with specialty["app"].app_context():
        before = panel_alerts.waiting(["endocrinology"])

    _set_number(specialty, "endocrinology", "hba1c_high", 8)

    with specialty["app"].app_context():
        after = panel_alerts.waiting(["endocrinology"])

    assert after.get("number", 0) == before.get("number", 0) - 1


def test_the_catalogue_holds_no_clinical_number(specialty):
    """The rule the whole design rests on, checked against the file itself: it
    says what to look at and never what is too much."""
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "app", "data",
                        "specialty_panels.json")
    with open(path, encoding="utf-8") as fh:
        panels = json.load(fh)["panels"]

    for key, meta in panels.items():
        for alert in meta.get("alerts") or []:
            watches = alert.get("watches") or {}
            assert set(watches) <= {"source", "of", "when"}, (
                f"{key}.{alert['code']} carries more than what it watches")
            for value in watches.values():
                assert not isinstance(value, (int, float)), (
                    f"{key}.{alert['code']} ships a number")


def test_every_watched_alert_names_a_source_the_reader_knows(specialty):
    """A catalogue entry the reader cannot answer would be a box on the screen
    that silently never fires — the exact failure this replaced."""
    from app.utils import panel_alerts, panels

    known_sources = {"lab", "vital", "panel", "age_months", "order"}
    known_whens = {"above", "below", "since", "pending"}
    for key in panels.all_panels():
        for alert in panel_alerts.watchable(key):
            watches = alert["watches"]
            assert watches["source"] in known_sources, alert["code"]
            assert watches["when"] in known_whens, alert["code"]


def test_a_watched_lab_code_exists_in_the_seeded_catalogue(specialty):
    """A code that answers to no test would arm an alert that reads nothing."""
    from app.models import Investigation
    from app.utils import panel_alerts, panels

    with specialty["app"].app_context():
        codes = {row.code for row in Investigation.query.all() if row.code}
        for key in panels.all_panels():
            for alert in panel_alerts.watchable(key):
                watches = alert["watches"]
                if watches["source"] != "lab":
                    continue
                for code in watches["of"].split(","):
                    assert code.strip() in codes, f"{key}.{alert['code']}"


def test_a_watched_panel_reading_is_a_field_that_panel_actually_takes(specialty):
    """Same rule for the panel's own measurements: watching a code the panel
    never asks for is a box that reads nothing for ever."""
    from app.utils import panel_alerts, panels

    for key in panels.all_panels():
        fields = {f["code"] for f in (panels.panel(key).get("fields") or [])}
        for alert in panel_alerts.watchable(key):
            watches = alert["watches"]
            if watches["source"] == "panel":
                assert watches["of"] in fields, f"{key}.{alert['code']}"


# ===================== the doors ===========================================
def test_the_screen_is_the_owners(specialty):
    """It decides when a clinic gets warned."""
    assert specialty["sign_in"]("doc").get("/panels/alerts").status_code == 403


def test_the_module_off_means_the_screen_is_absent(specialty):
    from app.models import Setting

    with specialty["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        specialty["db"].session.commit()

    assert specialty["sign_in"]("boss").get("/panels/alerts").status_code == 404


def test_the_panels_screen_leads_to_the_numbers(specialty):
    """Without a link from somewhere, the screen exists and nothing reaches
    it — which is the whole failure it was built to fix."""
    page = specialty["sign_in"]("boss").get("/panels/")

    assert b"/panels/alerts" in page.data


def test_the_screen_says_what_each_alert_watches(specialty):
    """Nobody should have to guess which reading their number is compared
    against."""
    page = specialty["sign_in"]("boss").get("/panels/alerts")

    assert page.status_code == 200
    assert b"data-watches" in page.data
    assert b'data-alert="hba1c_high"' in page.data


def test_the_screen_says_what_is_still_waiting_on_something_else(specialty):
    """A clinic filling in four numbers has to be told the other nine are not
    a setting they are missing."""
    page = specialty["sign_in"]("boss").get("/panels/alerts")

    assert b"data-waiting" in page.data
