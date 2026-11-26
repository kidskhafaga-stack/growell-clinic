"""الحضّانات بمقياسين، كل واحد لوحده — HOSPITAL_PLAN.md ت-٦ب.

The hospital decided on 26 Nov 2026, after reading the NICU/PICU scoring
dossier: the incubators score a child with SNAPPE-II **and** CRIB-II, each
on its own; intensive care with PIM3; never one for the other's unit. The
numbers here are **made up for the test** — they belong to no published
score; the program ships none.

* a score is written for one kind of unit and may run only after it says
  which; the other kind of unit is refused it;
* a unit runs two scores side by side: two forms, two results, never one in
  place of the other, and one may be written without the other;
* a child outside the group the paper built the score on is «not
  computable», with the reason, and nothing is written;
* a reading may be one of several options, each with its own coefficient or
  points (PIM3's diagnosis groups are of this shape);
* stopping one score leaves the other running; the board shows one score at
  a time.
"""
import math
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_severity_score_runs_only_when_approved import (  # noqa: E402
    EXAMPLES, _draft, _modules)

# A made-up points score with a choice: weight bands and a «group».
POINTS = ("w | الوزن | weight | number | g | ..999=4; 1000..=0 | \n"
          "grp | المجموعة | group | choice |  | low=0; mid=3; high=7 | ")
POINT_EXAMPLES = "w=800, grp=low => points=4\nw=1200, grp=mid => points=3\nw=900, grp=high => points=11"


@pytest.fixture()
def incubators(clinic):
    """An incubator unit with one bed, a newborn in it since half an hour."""
    from app.models import Admission, BedStay
    from app.models.place import Bed, Space, Unit

    _modules(clinic, beds=True, nicu=True, icu=True)
    db = clinic["db"]
    with clinic["app"].app_context():
        u = Unit(name="الحضّانات", kind="nicu")
        db.session.add(u)
        db.session.flush()
        s = Space(unit_id=u.id, name="غرفة", kind="room")
        db.session.add(s)
        db.session.flush()
        b = Bed(space_id=s.id, name="n1", sort_order=1)
        db.session.add(b)
        db.session.flush()
        came = datetime.utcnow() - timedelta(minutes=30)
        adm = Admission(patient_id=clinic["ids"]["child"], admitted_at=came)
        db.session.add(adm)
        db.session.flush()
        db.session.add(BedStay(admission_id=adm.id, bed_id=b.id, since=came))
        db.session.commit()
        clinic["ids"].update(stay=adm.id)
        clinic["came"] = came
    return clinic


def _points(fx, client, key, applies=""):
    from app.models import SeverityScore

    client.post("/severity/new", data={"key": key, "name_ar": key, "kind": "points",
                                       "unit_kind": "nicu"})
    with fx["app"].app_context():
        sid = SeverityScore.query.filter_by(key=key).first().id
    client.post(f"/severity/{sid}", data={
        "name_ar": key, "unit_kind": "nicu", "source": "أرقام مخترعة للاختبار",
        "licence_holder": "اختبار", "licence_ref": "T-1", "window_before_h": "1",
        "window_after_h": "12", "applies_if": applies, "inputs": POINTS,
        "examples": POINT_EXAMPLES})
    client.post(f"/severity/{sid}/activate", data={"note": "راجعته على الورقة"})
    return sid


def _when(fx, minutes=10):
    from app.utils.clock import to_local

    with fx["app"].app_context():
        return to_local(fx["came"] + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


def _yesterday():
    from app.utils.clock import local_today

    return (local_today() - timedelta(days=1)).isoformat()


# ------------------------------------------------------------- a choice --
def test_a_reading_may_be_one_of_several_options():
    from app.utils import severity

    rows, bad = severity.parse_inputs(POINTS, "points")
    assert not bad and rows[1]["options"] == {"low": 0.0, "mid": 3.0, "high": 7.0}
    assert severity.inputs_text(rows, "points").splitlines()[1] == \
        "grp | المجموعة | group | choice |  | low=3; mid=3; high=7 | ".replace("low=3", "low=0")
    score = {"kind": "points", "inputs": rows}
    assert severity.compute(score, {"w": 800.0, "grp": "high"})["points"] == 11
    assert severity.compute(score, {"w": 800.0, "grp": "other"})["error"] == "option"
    assert severity.compute(score, {"w": 800.0})["error"] == "required", "never guessed"

    eq, bad = severity.parse_inputs(
        "a | أ | a | number |  | value | 0.5 | \n"
        "dx | التشخيص | group | choice |  | value | none=0; risk=1.2; high=2 | none", "equation")
    assert not bad
    got = severity.compute({"kind": "equation", "inputs": eq, "intercept": -2.0}, {"a": 2.0})
    assert got["missing"] == ["dx"] and abs(got["probability"] - 1 / (1 + math.exp(1.0))) < 1e-12

    _rows, bad = severity.parse_inputs("g | ج | g | choice |  | only=1 | ", "points")
    assert bad == [(1, "options")], "one option is not a choice"
    _rows, bad = severity.parse_inputs("g | ج | g | choice |  | a=1; b=2 | c", "points")
    assert bad == [(1, "option")], "«if not measured» names one of them"
    ex, bad = severity.parse_examples(POINT_EXAMPLES)
    assert not bad and ex[2]["values"] == {"w": 900.0, "grp": "high"}
    assert severity.examples_text(ex).splitlines()[2].startswith("w=900, grp=high")


# --------------------------------------------------------- one unit each --
def test_a_score_names_its_unit_and_the_other_is_refused_it(incubators):
    from app.models import SeverityScore, SeverityUnitChoice
    from app.utils import severity

    boss = incubators["sign_in"]("boss")
    sid = _draft(incubators, boss, key="test_icu_only", unit_kind="")
    with incubators["app"].app_context():
        assert "unit" in severity.blockers(incubators["db"].session.get(SeverityScore, sid)), \
            "no unit, no running"
    icu = _draft(incubators, boss, key="test_picu", unit_kind="icu")
    boss.post(f"/severity/{icu}/activate", data={"note": "ok"})
    page = boss.get("/severity/").get_data(as_text=True)
    nicu_card = page.split('data-unit="nicu"')[1].split("</section>")[0]
    assert f'value="{icu}"' not in nicu_card, "PIM3's kind is not offered to the incubators"
    back = boss.post("/severity/unit/nicu", data={"score_id": icu, "since": _yesterday()},
                     follow_redirects=True).get_data(as_text=True)
    assert "مكتوب لوحدة تانية" in back
    with incubators["app"].app_context():
        assert SeverityUnitChoice.query.filter_by(unit_kind="nicu").count() == 0


# ---------------------------------------------------- two, side by side --
def test_the_incubators_run_two_scores_each_on_its_own(incubators):
    from app.models import SeverityRecord
    from app.utils import severity

    boss = incubators["sign_in"]("boss")
    a = _points(incubators, boss, "test_snappe")
    b = _points(incubators, boss, "test_crib")
    for sid in (a, b):
        boss.post("/severity/unit/nicu", data={"score_id": sid, "since": _yesterday()})
    with incubators["app"].app_context():
        assert [s.key for s in severity.choices("nicu")] == ["test_crib", "test_snappe"], \
            "the second is added beside the first, not in its place"
    stay = incubators["ids"]["stay"]
    page = boss.get(f"/severity/admission/{stay}/nicu").get_data(as_text=True)
    assert 'data-severity-form="test_snappe"' in page and 'data-severity-form="test_crib"' in page
    assert "data-apart" in page

    boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_snappe", "measured_at": _when(incubators), "v_w": "800", "v_grp": "high"})
    page = boss.get(f"/severity/admission/{stay}/nicu").get_data(as_text=True)
    assert 'data-severity-done="test_snappe"' in page and 'data-severity-form="test_crib"' in page, \
        "one may show without the other"

    boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_crib", "measured_at": _when(incubators), "v_w": "1200", "v_grp": "mid"})
    again = boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_snappe", "measured_at": _when(incubators, 20), "v_w": "1200", "v_grp": "low"},
        follow_redirects=True).get_data(as_text=True)
    assert "اتسجل قبل كده" in again or "data-severity-done" in again
    with incubators["app"].app_context():
        got = {r.score_key: r.points for r in SeverityRecord.query.filter_by(admission_id=stay)}
        assert got == {"test_snappe": 11.0, "test_crib": 3.0}, "two results, never added or replaced"


def test_stopping_one_leaves_the_other_and_the_board_takes_one_at_a_time(incubators):
    from app.models import Admission, SeverityRecord
    from app.utils import severity
    from app.utils.clock import local_today

    boss = incubators["sign_in"]("boss")
    a = _points(incubators, boss, "test_snappe")
    b = _points(incubators, boss, "test_crib")
    for sid in (a, b):
        boss.post("/severity/unit/nicu", data={"score_id": sid, "since": _yesterday()})
    boss.post("/severity/unit/nicu", data={"stop_key": "test_crib", "since": local_today().isoformat()})
    with incubators["app"].app_context():
        assert [s.key for s in severity.choices("nicu")] == ["test_snappe"]
        assert [s.key for s in severity.choices("nicu", on=local_today() - timedelta(days=1))] == \
            ["test_crib", "test_snappe"], "a child who came yesterday keeps both"
        db = incubators["db"]
        stay = db.session.get(Admission, incubators["ids"]["stay"])
        stay.discharged_at, stay.outcome = datetime.utcnow(), "home"
        for key, sid, p in (("test_snappe", a, 0.2), ("test_crib", b, 0.6)):
            db.session.add(SeverityRecord(admission_id=stay.id, patient_id=stay.patient_id,
                                          unit_kind="nicu", score_id=sid, score_key=key,
                                          entered_at=incubators["came"], measured_at=incubators["came"],
                                          values={}, missing=[], probability=p))
        db.session.commit()
        assert severity.board("nicu", score_key="test_snappe")["expected"] == 0.2
        assert severity.board("nicu", score_key="test_crib")["expected"] == 0.6
    page = boss.get("/severity/board?unit=nicu&score=test_crib").get_data(as_text=True)
    assert "data-score-tabs" in page and 'score=test_snappe' in page
    assert '<span class="v">0.6</span>' in page, "never 0.8 — the two are not added"


# ------------------------------------------------------ who it applies to --
def test_a_child_outside_the_papers_group_is_not_computable(incubators):
    from app.models import SeverityRecord
    from app.utils import severity

    rules, bad = severity.parse_applies("bw 500..1500\nga ..32\nnonsense")
    assert rules == [["bw", 500.0, 1500.0], ["ga", None, 32.0]] and bad == [(3, "applies")]
    assert severity.applies_text(rules) == "bw 500..1500\nga ..32"

    boss = incubators["sign_in"]("boss")
    sid = _points(incubators, boss, "test_small", applies="bw 500..1500")
    boss.post("/severity/unit/nicu", data={"score_id": sid, "since": _yesterday()})
    stay = incubators["ids"]["stay"]
    page = boss.get(f"/severity/admission/{stay}/nicu").get_data(as_text=True)
    assert 'data-applies-input="bw"' in page and "data-applies" in page

    out = boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_small", "measured_at": _when(incubators), "a_bw": "2400",
        "v_w": "800", "v_grp": "low"}, follow_redirects=True).get_data(as_text=True)
    assert "مش قابل للحساب" in out
    out = boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_small", "measured_at": _when(incubators), "v_w": "800",
        "v_grp": "low"}, follow_redirects=True).get_data(as_text=True)
    assert "ناقص قراءة" in out
    with incubators["app"].app_context():
        assert SeverityRecord.query.count() == 0, "nothing is written for a child it does not fit"
    boss.post(f"/severity/admission/{stay}/nicu", data={
        "score_key": "test_small", "measured_at": _when(incubators), "a_bw": "900",
        "v_w": "900", "v_grp": "low"})
    with incubators["app"].app_context():
        row = SeverityRecord.query.one()
        assert (row.points, row.values["bw"]) == (4.0, 900.0), "kept with the result"


def test_a_definition_keeps_its_unit_and_group_in_a_new_version(incubators):
    from app.models import SeverityScore

    boss = incubators["sign_in"]("boss")
    sid = _points(incubators, boss, "test_small", applies="bw 500..1500")
    boss.post(f"/severity/{sid}/version")
    with incubators["app"].app_context():
        v2 = SeverityScore.query.filter_by(key="test_small", version=2).one()
        assert (v2.unit_kind, v2.applies_if) == ("nicu", [["bw", 500.0, 1500.0]])
    page = boss.get(f"/severity/{sid}").get_data(as_text=True)
    assert "data-score-unit" in page and "data-choice-help" in page


def test_the_examples_are_the_guard_still(incubators):
    """A choice score is held to its worked examples like any other."""
    from app.models import SeverityScore

    boss = incubators["sign_in"]("boss")
    wrong = POINT_EXAMPLES.replace("points=11", "points=12")
    boss.post("/severity/new", data={"key": "test_wrong", "name_ar": "x", "kind": "points",
                                     "unit_kind": "nicu"})
    with incubators["app"].app_context():
        sid = SeverityScore.query.filter_by(key="test_wrong").one().id
    boss.post(f"/severity/{sid}", data={"name_ar": "x", "unit_kind": "nicu", "inputs": POINTS,
                                        "examples": wrong, "source": "x", "licence_holder": "x",
                                        "licence_ref": "x", "window_before_h": "1",
                                        "window_after_h": "1"})
    with incubators["app"].app_context():
        assert not incubators["db"].session.get(SeverityScore, sid).test_ok
    assert EXAMPLES  # the equation examples stay as they were
