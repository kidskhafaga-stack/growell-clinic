"""Sixty alerts asked for, two that actually run, and a screen that says which.

The survey's fourth question per specialty is *"متى ينبّهك البرنامج من نفسه؟"*
and the answers name sixty alerts. They are not one kind of thing, and the
temptation is to treat them as one — declare six headings under each panel and
let a doctor assume something is watching.

**That would be worse than having no alerts at all.** A heading that looks like
a safety net and is not one is the failure this whole file exists to prevent.
So every alert is classified by what it actually needs, the classification is in
the catalogue where a person can read it, and the screen shows what *ran*.

| need | meaning | count |
|---|---|---|
| `overdue` | a date the program already holds | 12 |
| `trend` | a comparison between two visits | 21 |
| `number` | a threshold the **clinic** must set | 11 |
| `cross_check` | a medicines / allergy / vaccine knowledge base | 13 |
| `doctor` | something only a person can notice | 3 |

**Why `number` does not fire.** The survey refuses to supply thresholds — its
own cardiology answer is *"لا يوجد رقم موحّد لـSpO2 أو EF لكل مرض قلبي"* — and
this program does not invent clinical numbers. An alert that fired on a figure
nobody chose would be the program making a clinical claim, which is the line
`ai_discuss` and `clinical_rules` were both written to hold.

**Why "not implemented" shows nothing rather than an all-clear.** "We did not
look" and "we looked and it is fine" are different answers, and a screen that
merged them would be the more dangerous of the two.
"""
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIRED = 'data-panel-alerts="'
WAITING = 'data-alerts-waiting="'


def _catalogue():
    with open(os.path.join(HERE, "..", "app", "data", "specialty_panels.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["panels"]


@pytest.fixture()
def desk(clinic):
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "endocrinology"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _page(kit, who="boss"):
    return kit["sign_in"](who).get(kit["url"]).get_data(as_text=True)


def _missed_appointment(kit, days_ago, status="scheduled"):
    from datetime import time

    from app.models import Appointment
    from app.utils.clock import local_today

    with kit["app"].app_context():
        kit["db"].session.add(Appointment(
            patient_id=kit["ids"]["child"], doctor_id=kit["ids"]["doctor"],
            appt_date=local_today() - timedelta(days=days_ago),
            appt_time=time(10, 0), status=status))
        kit["db"].session.commit()


# ---------------------------------------------------------- what is declared ---

#: The eleven the survey covers. The rest of the catalogue is proposed from
#: published practice rather than transcribed from a doctor's ticks, and each
#: of those carries a `_source_ar` saying so — a difference in provenance that
#: matters more than any difference in shape, and one a test should not blur.
FROM_THE_SURVEY = [
    "endocrinology", "cardiology", "pulmonology", "neurology", "developmental",
    "nephrology", "gastroenterology", "haematology", "neonatology",
    "ophthalmology", "dentistry",
]


#: The sixty the survey actually named, by panel and by code. Written out
#: rather than counted, because a total is the wrong assertion: it goes red
#: when a panel legitimately *gains* an alert — which it did, when dentistry
#: was given the general-anaesthetic ones — and stays green if a survey alert
#: is swapped for something else. What must hold is that none of these is
#: lost; adding beside them is allowed and expected.
SURVEY_ALERTS = {
    "endocrinology": ['hba1c_high', 'hypo_freq', 'growth_stop', 'no_hba1c', 'bp_high', 'late'],
    "cardiology": ['spo2_low', 'wt_gain', 'ef_drop', 'penicillin_late', 'inr_out', 'defect_grows'],
    "pulmonology": ['systemic_steroids', 'er', 'control_loss', 'high_ics', 'contraindicated'],
    "neurology": ['seizures_inc', 'lost_skill', 'hc_cross', 'lft_high', 'dose_low', 'drug_level_old'],
    "developmental": ['lost_skill', 'wt_drop', 'delay_age', 'no_improvement', 'lost_followup'],
    "nephrology": ['bp_high', 'egfr_drop', 'new_relapse', 'steroid_toxicity', 'renal_dose'],
    "gastroenterology": ['wt_drop', 'no_wt_gain', 'lft_high', 'ttg_high', 'gluten_rx'],
    "haematology": ['ferritin_high', 'hb_low', 'tx_late', 'spleen_big', 'g6pd_rx'],
    "neonatology": ['low_wt', 'rop_due', 'wrong_vaccine', 'hc_fast', 'no_hearing'],
    "ophthalmology": ['amblyopia_stuck', 'refraction_fast', 'preterm_rop_due', 'iop_high', 'long_term_steroid', 'never_examined'],
    "dentistry": ['fluoride_due', 'new_caries_despite_followup', 'heart_defect_prophylaxis', 'penicillin_allergy', 'gum_hyperplasia_risk', 'no_visit_since_one'],
}


def test_no_alert_the_survey_asked_for_has_been_lost():
    """The survey's sixty, each by name. A count would go red on a legitimate
    addition and green on a silent substitution."""
    panels = _catalogue()
    missing = []
    for key, wanted in SURVEY_ALERTS.items():
        have = {a["code"] for a in panels[key].get("alerts") or []}
        missing += [f"{key}.{c}" for c in wanted if c not in have]

    assert not missing, "these were in the survey and are gone: " + ", ".join(missing)
    assert sum(len(v) for v in SURVEY_ALERTS.values()) == 60


def test_the_proposed_panels_say_they_are_proposed():
    """The provenance is the whole difference. A panel nobody ticked must not
    look like one somebody did."""
    panels = _catalogue()
    proposed = [k for k in panels if k not in FROM_THE_SURVEY]
    assert proposed, "no proposed panels found, so this proves nothing"
    for key in proposed:
        assert panels[key].get("_source_ar"), \
            f"{key} is not in the survey and does not say where it came from"
        assert panels[key].get("alerts"), f"{key} declares no alerts at all"


def test_every_alert_says_what_it_needs():
    known = {"number", "trend", "overdue", "cross_check", "doctor"}
    for key, panel in _catalogue().items():
        for alert in panel.get("alerts") or []:
            assert alert.get("needs") in known, \
                f"{key}.{alert.get('code')} does not say what it needs"


def test_no_alert_carries_a_threshold():
    """The survey refuses to supply one and so does this. A number here would
    be the program making a clinical claim nobody made."""
    for key, panel in _catalogue().items():
        for alert in panel.get("alerts") or []:
            for value in alert.values():
                assert not isinstance(value, (int, float)) or isinstance(value, bool), \
                    f"{key}.{alert['code']} carries a number: {value}"


def test_an_alert_marked_live_is_actually_implemented():
    """A `live` flag with nothing behind it would be the exact lie this file
    exists to prevent — a heading that looks like a safety net."""
    from app.utils.panel_alerts import LIVE

    for key, panel in _catalogue().items():
        for alert in panel.get("alerts") or []:
            if alert.get("live"):
                assert alert["code"] in LIVE, \
                    f"{key}.{alert['code']} is marked live and nothing evaluates it"


def test_and_everything_implemented_is_marked_live():
    """The other direction: a check that runs but is not declared would never
    be reached, because `evaluate` only looks at what the catalogue flags."""
    from app.utils.panel_alerts import LIVE

    flagged = {a["code"] for p in _catalogue().values()
               for a in p.get("alerts") or [] if a.get("live")}
    assert set(LIVE) == flagged, \
        f"implemented but not declared: {set(LIVE) - flagged}"


# ------------------------------------------------------------- what runs ---

def test_a_missed_follow_up_fires(desk):
    """The one alert in the whole survey that needs no number and no new data:
    the appointment is in the file and the day went past."""
    from app.utils import panel_alerts

    _missed_appointment(desk, days_ago=40)

    with desk["app"].app_context():
        fired = panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"])

    assert [f["code"] for f in fired] == ["late"]
    assert fired[0]["detail"]["days"] == 40


@pytest.mark.parametrize("status", ["completed", "in_progress"])
def test_an_appointment_the_child_attended_does_not(desk, status):
    from app.utils import panel_alerts

    _missed_appointment(desk, days_ago=40, status=status)

    with desk["app"].app_context():
        assert panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"]) == []


def test_nor_does_one_the_clinic_cancelled(desk):
    """Cancelled is not missed. Somebody called off the appointment, which is
    an answer and not a silence."""
    from app.utils import panel_alerts

    _missed_appointment(desk, days_ago=40, status="cancelled")

    with desk["app"].app_context():
        assert panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"]) == []


def test_a_no_show_does(desk):
    """Marked as missed is still missed — the point is the child did not come,
    not whether the desk got round to marking it."""
    from app.utils import panel_alerts

    _missed_appointment(desk, days_ago=15, status="no_show")

    with desk["app"].app_context():
        fired = panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"])
    assert fired, "a marked no-show is not counted as a missed follow-up"


def test_a_future_appointment_is_not_late(desk):
    from app.utils import panel_alerts

    _missed_appointment(desk, days_ago=-7)

    with desk["app"].app_context():
        assert panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"]) == []


def test_it_is_read_against_the_clinics_today(desk):
    """The comparison that put three hours of every night's shifts on the wrong
    day was this one done carelessly. `local_today`, not the server's."""
    import inspect

    from app.utils import panel_alerts

    source = inspect.getsource(panel_alerts._overdue_followup)
    assert "local_today" in source
    assert "date.today" not in source


def test_an_alert_that_is_not_implemented_returns_nothing_at_all(desk):
    """Not an all-clear. "We did not look" and "we looked and it is fine" are
    different answers."""
    from app.utils import panel_alerts

    with desk["app"].app_context():
        fired = panel_alerts.evaluate(desk["ids"]["child"], ["endocrinology"])
        codes = {f["code"] for f in fired}
        assert "hba1c_high" not in codes and "bp_high" not in codes


# --------------------------------------------------------------- on screen ---

def test_the_screen_shows_what_fired(desk):
    _missed_appointment(desk, days_ago=40)

    page = _page(desk)

    assert FIRED in page, "a fired alert is not on the consultation screen"


def test_and_shows_nothing_when_nothing_fired(desk):
    assert FIRED not in _page(desk)


def test_an_owner_is_told_what_the_rest_are_waiting_for(desk):
    """A clinic that has never written its numbers down is one settings screen
    away from eleven more alerts, and nothing anywhere said so."""
    page = _page(desk)

    assert WAITING in page
    assert "رقم من العيادة" in page or "clinic's number" in page


def test_a_doctor_mid_consultation_is_not(desk):
    """The same correction the diagnosis suggestion needed: a note about a
    screen they cannot open is an interruption, not information."""
    assert WAITING not in _page(desk, "doc")


def test_a_clinic_without_the_module_gets_none_of_it(desk):
    from app.models import Setting

    _missed_appointment(desk, days_ago=40)
    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    page = _page(desk)
    assert FIRED not in page and WAITING not in page


# ------------------------------------- an alert with nothing to feed it ---

# What each alert reads, where the reading is a panel field or a vital rather
# than a lab test. Written down here because the catalogue cannot infer it and
# because the gap it catches is invisible otherwise: an alert about intraocular
# pressure, sitting under a panel with no box to record intraocular pressure,
# looks exactly like a working alert until somebody waits for it.
NEEDS_A_READING = {
    "iop_high": "iop",
    "amblyopia_stuck": "patch_hours",
    "refraction_fast": "refraction_sph",
    "ef_drop": "ef_pct",
    "hb_low": "hb_pre_transfusion",
    "spleen_big": "spleen_cm",
    "seizures_inc": "seizures_per_month",
    "hc_cross": "head_circ_cm",
    "hc_fast": "head_circ_cm",
    "control_loss": "act_score",
    "spo2_low": "spo2",
    "egfr_drop": None,        # a lab test, checked by the chart-list tests
    "hypo_freq": "hypo_episodes",
    "no_wt_gain": "weight_kg",
    "wt_drop": "weight_kg",
    "wt_gain": "weight_kg",
    "low_wt": "weight_kg",
}


def test_no_alert_watches_something_the_panel_cannot_record():
    """The gap this found, and it was a real one.

    Ophthalmology asked to be warned when intraocular pressure goes over the
    clinic's limit, and when amblyopia has not improved after the patching
    period — and the panel recorded neither pressure nor patching hours.
    Neurology asked to be warned when head circumference crosses a centile and
    did not read head circumference. Those alerts could never fire, whatever
    number a clinic set, and nothing on any screen would have said so.

    An alert is a promise about data. This checks the data exists.
    """
    panels = _catalogue()
    broken = []
    for key, panel in panels.items():
        available = {f["code"] for f in panel.get("fields") or []}
        available |= set(panel.get("reads") or [])
        for alert in panel.get("alerts") or []:
            wanted = NEEDS_A_READING.get(alert["code"])
            if wanted and wanted not in available:
                broken.append(f"{key}.{alert['code']} needs '{wanted}'")

    assert not broken, (
        "these alerts watch a reading their panel never records, so they can "
        "never fire: " + "; ".join(broken))


def test_that_check_is_looking_at_something():
    """Guarding the guard: an empty map would make the test above vacuous."""
    panels = _catalogue()
    codes = {a["code"] for p in panels.values() for a in p.get("alerts") or []}
    checked = [c for c in NEEDS_A_READING if c in codes]
    assert len(checked) > 10, f"only {len(checked)} alerts are checked this way"
