"""A result written analyte by analyte, read against the child's own range.

Asked as *«البرنامج يطلع النتيجة ويعرفها ويفهمها ويفهما للطبيب»*. What is held
here:

* what is typed is a number or words, and a comma is never guessed at;
* the range is chosen for this child — age on the day of the sample, and sex
  — and **only an approved range calls a value high or low**; a draft is a
  reference and flags nothing; no range is no flag, never «normal»;
* critical is the laboratory's limit, strictly beyond it;
* the range a value was read against is copied onto it, so approving a new
  sheet next month does not re-read last month's result;
* a critical value reaches the doctors who answer for the child, stays until
  one of them says they read it, and a correction takes it away;
* a test the laboratory has not broken down is answered as it always was,
  and a clinic's screens are exactly as they were.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def bench(clinic):
    """The lab module on, a CBC made of haemoglobin and platelets, and a CRP
    made of one analyte. Haemoglobin has an approved range with critical
    limits for the fixture's boy (born 2025-01-01) and a draft for girls;
    platelets only a draft."""
    from app.models import (Investigation, LabAnalyte, LabRange,
                            LabTestAnalyte, Setting)

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        cbc = Investigation(name_ar="صورة دم", name_en="CBC", kind="lab",
                            tat_max=60)
        crp = Investigation(name_ar="بروتين سي", name_en="CRP", kind="lab")
        plain = Investigation(name_ar="تحليل بول", kind="lab")
        hb = LabAnalyte(name="Hemoglobin", unit="g/dL")
        plt = LabAnalyte(name="Platelets", unit="x10^9/L")
        crp_a = LabAnalyte(name="CRP", unit="mg/L")
        db.session.add_all([cbc, crp, plain, hb, plt, crp_a])
        db.session.flush()
        db.session.add_all([
            LabTestAnalyte(investigation_id=cbc.id, analyte_id=hb.id, sort_order=0),
            LabTestAnalyte(investigation_id=cbc.id, analyte_id=plt.id, sort_order=1),
            LabTestAnalyte(investigation_id=crp.id, analyte_id=crp_a.id, sort_order=0),
        ])
        approved = datetime.utcnow() - timedelta(days=1)
        db.session.add_all([
            # A wide band for everybody, and a narrower one for boys aged one
            # to two: the boy's must win.
            LabRange(analyte_id=hb.id, age_from_days=0, age_to_days=None,
                     sex="all", low=9.0, high=16.0, approved_at=approved,
                     age_label="all ages"),
            LabRange(analyte_id=hb.id, age_from_days=365, age_to_days=730,
                     sex="male", low=10.5, high=13.5, critical_low=7.0,
                     critical_high=20.0, approved_at=approved,
                     age_label="1-<2 years", source="Lab book"),
            LabRange(analyte_id=hb.id, age_from_days=365, age_to_days=730,
                     sex="female", low=10.0, high=13.0, age_label="1-<2 years"),
            LabRange(analyte_id=plt.id, age_from_days=0, sex="all",
                     low=150, high=450, age_label="all"),
            LabRange(analyte_id=crp_a.id, age_from_days=0, sex="all",
                     low=0, high=5, approved_at=approved, age_label="all"),
        ])
        db.session.commit()
        clinic.update(cbc=cbc.id, crp=crp.id, plain=plain.id, hb=hb.id,
                      plt=plt.id, crp_a=crp_a.id)
    return clinic


def _order(bench, test="cbc", collected_minutes_ago=None):
    from app.models import VisitInvestigation

    with bench["app"].app_context():
        now = datetime.utcnow()
        row = VisitInvestigation(
            visit_id=bench["ids"]["visit"], patient_id=bench["ids"]["child"],
            investigation_id=bench[test], kind="lab", name=test,
            status="requested", ordered_by=bench["ids"]["doctor"])
        if collected_minutes_ago is not None:
            row.collected_at = now - timedelta(minutes=collected_minutes_ago)
            row.status = "collected"
        bench["db"].session.add(row)
        bench["db"].session.commit()
        return row.id


def _post(bench, order_id, who="boss", **values):
    data = {f"a_{bench[k]}": v for k, v in values.items()}
    return bench["sign_in"](who).post(f"/labs/order/{order_id}/result",
                                      data=data)


def _row(bench, order_id):
    from app.models import VisitInvestigation

    return bench["db"].session.get(VisitInvestigation, order_id)


@pytest.fixture(autouse=True)
def _fresh_cache():
    from app.utils import lab_results

    lab_results.invalidate()
    yield
    lab_results.invalidate()


# ============================================================ typing ====
@pytest.mark.parametrize("raw, want", [
    ("12.5", (12.5, None)), ("١٢٫٥", (12.5, None)), (" 7 ", (7.0, None)),
    (".5", (0.5, None)), ("12,5", (None, "12,5")), ("Negative", (None, "Negative")),
    ("<0.5", (None, "<0.5")), ("+++", (None, "+++")), ("", (None, None)),
])
def test_a_number_or_words_and_a_comma_is_not_guessed(raw, want):
    from app.utils.lab_results import parse

    assert parse(raw) == want


# ============================================================ judging ===
def test_only_an_approved_range_calls_a_value_anything():
    from app.models import LabRange
    from app.utils.lab_results import judge

    draft = LabRange(low=10, high=13, kind="interval")
    assert judge(5, draft) is None, "a draft flagged a value"
    ok = LabRange(low=10, high=13, kind="interval",
                  critical_low=7, critical_high=20, approved_at=datetime.utcnow())
    assert judge(9.9, ok) == "low"
    assert judge(13.1, ok) == "high"
    assert judge(10, ok) == "normal" and judge(13, ok) == "normal"
    # Strictly beyond the laboratory's limit.
    assert judge(7, ok) == "low" and judge(6.9, ok) == "critical_low"
    assert judge(20, ok) == "high" and judge(20.1, ok) == "critical_high"
    assert judge(None, ok) is None
    cutoff = LabRange(high=100, kind="cutoff", approved_at=datetime.utcnow())
    assert judge(150, cutoff) is None, "a guideline was used as a usual range"


def test_the_range_is_this_childs(bench):
    """The boy's own band before everybody's; a girl gets the girls' row;
    and the age is the day of the sample, not today."""
    from app.models import LabAnalyte
    from app.utils.lab_results import references

    with bench["app"].app_context():
        hb = bench["db"].session.get(LabAnalyte, bench["hb"])
        approved, draft = references(hb, 400, "male")
        assert (approved.low, approved.high) == (10.5, 13.5)
        assert draft is None
        approved, draft = references(hb, 400, "female")
        assert (approved.low, approved.high) == (9.0, 16.0)
        assert (draft.low, draft.high) == (10.0, 13.0)
        approved, _ = references(hb, 800, "male")
        assert (approved.low, approved.high) == (9.0, 16.0)


def test_a_narrow_band_is_preferred_to_a_wide_one():
    from app.models import LabAnalyte, LabRange
    from app.utils.lab_results import references

    now = datetime.utcnow()
    wide = LabRange(id=1, age_from_days=0, age_to_days=None, sex="all",
                    low=1, high=9, approved_at=now)
    narrow = LabRange(id=2, age_from_days=365, age_to_days=730, sex="all",
                      low=3, high=5, approved_at=now)
    analyte = LabAnalyte(name="X", ranges=[narrow, wide])
    assert references(analyte, 400, "male")[0] is narrow
    analyte = LabAnalyte(name="X", ranges=[wide, narrow])
    assert references(analyte, 400, "male")[0] is narrow
    assert references(analyte, 800, "male")[0] is wide


def test_the_age_is_counted_on_the_day_of_the_sample(bench):
    from app.models import Patient
    from app.utils.lab_results import age_days

    with bench["app"].app_context():
        child = bench["db"].session.get(Patient, bench["ids"]["child"])
        drawn = datetime(2025, 6, 1, 10, 0)
        assert age_days(child, drawn) == (date(2025, 6, 1) - date(2025, 1, 1)).days


# ============================================================ the bench ==
def test_a_cbc_is_answered_line_by_line(bench):
    order = _order(bench, collected_minutes_ago=10)
    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-by-analyte" in page
    assert f'name="a_{bench["hb"]}"' in page and f'name="a_{bench["plt"]}"' in page
    assert 'data-ref="approved"' in page and 'data-ref="draft"' in page

    resp = _post(bench, order, hb="9.8", plt="90")
    assert resp.status_code == 302
    with bench["app"].app_context():
        row = _row(bench, order)
        values = {v.analyte.name: v for v in row.analyte_values}
        assert row.status == "resulted" and row.resulted_by == bench["ids"]["admin"]
        assert values["Hemoglobin"].flag == "low"
        assert (values["Hemoglobin"].ref_low, values["Hemoglobin"].ref_high) == (10.5, 13.5)
        # Ninety platelets is outside the draft, and a draft calls nothing.
        assert values["Platelets"].flag is None
        assert values["Platelets"].range_approved is False
        # …but it is still printed beside the value, as the draft it is.
        assert (values["Platelets"].ref_low, values["Platelets"].ref_high) == (150, 450)
        assert row.analytes_resulted == 2 and row.abnormal_count == 1
        assert row.critical_at is None
        # A CBC has no one number that is «the» result.
        assert row.result_value is None

    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert 'data-flag="low"' in page


def test_a_range_approved_later_does_not_rewrite_an_old_result(bench):
    from app.models import LabRange

    order = _order(bench, collected_minutes_ago=10)
    _post(bench, order, hb="11")
    with bench["app"].app_context():
        boy = LabRange.query.filter_by(analyte_id=bench["hb"], sex="male").one()
        boy.low = 11.5
        bench["db"].session.commit()
        value = _row(bench, order).analyte_values[0]
        assert value.flag == "normal" and value.ref_low == 10.5


def test_a_blank_box_clears_its_value_and_all_blank_is_unanswered(bench):
    order = _order(bench, collected_minutes_ago=10)
    _post(bench, order, hb="11", plt="200")
    _post(bench, order, hb="11", plt="")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert [v.analyte.name for v in row.analyte_values] == ["Hemoglobin"]
        assert row.analytes_resulted == 1
    _post(bench, order, hb="", plt="")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.analyte_values == [] and row.analytes_resulted is None
        # Back to where the sample is, not to «nobody drew it».
        assert row.status == "collected" and row.resulted_at is None


def test_words_are_kept_and_flag_nothing(bench):
    order = _order(bench, collected_minutes_ago=10)
    _post(bench, order, hb="haemolysed")
    with bench["app"].app_context():
        value = _row(bench, order).analyte_values[0]
        assert value.value is None and value.text == "haemolysed"
        assert value.flag is None


def test_a_single_analyte_test_keeps_its_number_where_the_curves_read_it(bench):
    order = _order(bench, test="crp", collected_minutes_ago=10)
    _post(bench, order, crp_a="12")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert (row.result_value, row.result_unit) == (12.0, "mg/L")
        assert (row.result_low, row.result_high) == (0, 5)
        assert row.out_of_range is True
    _post(bench, order, crp_a="")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.result_value is None and row.result_low is None


def test_a_draft_range_never_reaches_the_curve(bench):
    """One analyte with only a draft: the number is mirrored, the band is
    not — a curve's band is a claim about what is usual."""
    from app.models import Investigation, LabTestAnalyte

    with bench["app"].app_context():
        only_plt = Investigation(name_ar="صفائح", kind="lab")
        bench["db"].session.add(only_plt)
        bench["db"].session.flush()
        bench["db"].session.add(LabTestAnalyte(investigation_id=only_plt.id,
                                               analyte_id=bench["plt"]))
        bench["db"].session.commit()
        bench["only_plt"] = only_plt.id
    order = _order(bench, test="only_plt", collected_minutes_ago=10)
    _post(bench, order, plt="90")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.result_value == 90
        assert row.result_low is None and row.result_high is None
        assert row.out_of_range is None


def test_a_test_nobody_broke_down_is_answered_as_it_always_was(bench):
    order = _order(bench, test="plain", collected_minutes_ago=10)
    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-by-analyte" not in page and 'name="result_value"' in page
    bench["sign_in"]("boss").post(f"/labs/order/{order}/result",
                                  data={"result_value": "3", "result_low": "1",
                                        "result_high": "2"})
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.status == "resulted" and row.result_value == 3
        assert row.analyte_values == [] and row.analytes_resulted is None


# ======================================================= critical values ==
def test_a_critical_value_reaches_the_childs_doctor_and_stays_until_read(bench):
    from app.models import ActivityLog
    from app.utils.notifications import get_notifications
    from app.models import User

    order = _order(bench, collected_minutes_ago=10)
    resp = _post(bench, order, hb="6.5")
    assert resp.status_code == 302
    with bench["app"].test_request_context():
        row = _row(bench, order)
        assert row.critical_at is not None and row.critical_seen_at is None
        doc = bench["db"].session.get(User, bench["ids"]["doctor"])
        desk = bench["db"].session.get(User, bench["ids"]["desk"])
        assert any(n["key"] == "lab_critical" for n in get_notifications(doc))
        assert not any(n["key"] == "lab_critical" for n in get_notifications(desk))
        assert ActivityLog.query.filter_by(action="lab.critical",
                                           entity_id=order).count() == 1

    doctor = bench["sign_in"]("doc")
    listed = doctor.get("/labs/critical").get_data(as_text=True)
    assert f'data-critical-row="{order}"' in listed and "data-mine" in listed
    page = doctor.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-critical-unread" in page and "data-critical-read-btn" in page

    assert doctor.post(f"/labs/order/{order}/critical-read").status_code == 302
    with bench["app"].test_request_context():
        row = _row(bench, order)
        assert row.critical_seen_by == bench["ids"]["doctor"]
        doc = bench["db"].session.get(User, bench["ids"]["doctor"])
        assert not any(n["key"] == "lab_critical" for n in get_notifications(doc))
        assert ActivityLog.query.filter_by(action="lab.critical_read").count() == 1
    assert "data-none-critical" in doctor.get("/labs/critical").get_data(as_text=True)


def test_the_stays_doctor_and_whoever_is_on_now_are_told_too(bench, monkeypatch):
    """Not only the doctor who ordered it: the stay's responsible doctor, and
    the doctors the rota has on right now — the ones who can walk to the bed
    at three in the morning."""
    from app.models import Admission, User
    from app.utils import lab_results

    with bench["app"].app_context():
        db = bench["db"]
        people = {}
        for key in ("mrp", "night", "home"):
            row = User(username=key, full_name=key, role="doctor", is_active=True)
            row.set_password("secret")
            db.session.add(row)
            people[key] = row
        db.session.flush()
        stay = Admission(patient_id=bench["ids"]["child"],
                         doctor_id=people["mrp"].id)
        db.session.add(stay)
        db.session.commit()
        ids = {k: v.id for k, v in people.items()}
        stay_id = stay.id
    order = _order(bench, collected_minutes_ago=10)
    with bench["app"].app_context():
        _row(bench, order).admission_id = stay_id
        bench["db"].session.commit()
    monkeypatch.setattr(lab_results, "_on_duty_now", lambda: {ids["night"]})
    _post(bench, order, hb="25")
    with bench["app"].app_context():
        def told(key):
            return order in lab_results.critical_for(
                bench["db"].session.get(User, ids[key]))
        assert told("mrp") and told("night")
        assert not told("home"), "a doctor off the rota was told"


def test_only_a_doctor_says_they_read_it(bench):
    order = _order(bench, collected_minutes_ago=10)
    _post(bench, order, hb="25")
    # The admin in the fixture does not see patients.
    resp = bench["sign_in"]("boss").post(f"/labs/order/{order}/critical-read")
    assert resp.status_code == 403
    with bench["app"].app_context():
        assert _row(bench, order).critical_seen_at is None


def test_a_corrected_typo_takes_the_alarm_with_it(bench):
    from app.models import ActivityLog

    order = _order(bench, collected_minutes_ago=10)
    _post(bench, order, hb="1.2")
    _post(bench, order, hb="12")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert row.critical_at is None and row.abnormal_count is None
        # And the log still says it was there.
        assert ActivityLog.query.filter_by(action="lab.critical").count() == 1


def test_the_stay_and_the_visit_show_the_lines(bench):
    order = _order(bench, collected_minutes_ago=10)
    visit = bench["ids"]["visit"]
    before = bench["sign_in"]("doc").get(f"/visits/{visit}/record")
    assert before.status_code == 200
    assert "data-analyte-values" not in before.get_data(as_text=True)
    _post(bench, order, hb="9.8", plt="200")
    after = bench["sign_in"]("doc").get(f"/visits/{visit}/record").get_data(as_text=True)
    assert f'data-analyte-values="{order}"' in after and 'data-flag="low"' in after


# ================================================================ late ====
def test_a_sample_past_its_time_says_so(bench):
    from app.utils.lab_results import late

    slow = _order(bench, collected_minutes_ago=90)
    fresh = _order(bench, collected_minutes_ago=10)
    undrawn = _order(bench)
    no_figure = _order(bench, test="crp", collected_minutes_ago=600)
    with bench["app"].app_context():
        assert late(_row(bench, slow)) is True
        assert late(_row(bench, fresh)) is False
        assert late(_row(bench, undrawn)) is None
        assert late(_row(bench, no_figure)) is None
    rack = bench["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert rack.count("data-late") == 1 and "data-to-critical" in rack


# ============================================================ the doors ==
def test_nothing_of_it_without_the_lab_module(bench):
    from app.models import Setting

    order = _order(bench, collected_minutes_ago=10)
    with bench["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        bench["db"].session.commit()
    client = bench["sign_in"]("doc")
    assert client.get("/labs/critical").status_code == 404
    assert client.post(f"/labs/order/{order}/critical-read").status_code == 404
