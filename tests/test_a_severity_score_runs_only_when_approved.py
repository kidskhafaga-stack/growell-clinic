"""مقاييس الخطورة — المحرك مقفول لحد ما المقياس يتعتمد (HOSPITAL_PLAN.md ت-٦ب).

The numbers in this file are **made up for the test** — a two-reading
equation and a two-reading points table that belong to no published score.
The program ships none; a hospital enters a real one from its paper.

* the lines are read, and a bad line is named by its number;
* a reading not measured takes the paper's value and is listed; a required
  one missing stops the score — nothing is guessed;
* a score runs only with its source, its licence, enough worked examples all
  reproduced, and a named approver; an approved version is frozen;
* a unit uses a score from a day; a child is scored inside the window only,
  and keeps that score when the unit changes;
* the board: deaths, expected, SMR, its 95% interval, the VLAD line;
* who may, and only with intensive or neonatal care.
"""
import math
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

INPUTS = ("a | القراءة أ | reading a | number | u | value | 0.5 | 0\n"
          "b | القراءة ب | reading b | yesno |  | value | 1.0 | ")


def _p(a, b, intercept=-2.0):
    return 1 / (1 + math.exp(-(intercept + 0.5 * a + b)))


EXAMPLES = "\n".join(f"a={a}, b={b} => p={_p(a, b):.6f}" for a, b in ((0, 0), (2, 1), (4, 0)))


def _modules(fx, **on):
    from app.models import Setting

    with fx["app"].app_context():
        for name, value in on.items():
            Setting.set(f"mod_enabled:{name}", "1" if value else "0")
        fx["db"].session.commit()


@pytest.fixture()
def unit(clinic):
    """An intensive care unit with one bed."""
    from app.models.place import Bed, Space, Unit

    _modules(clinic, beds=True, icu=True)
    db = clinic["db"]
    with clinic["app"].app_context():
        u = Unit(name="العناية", kind="icu")
        db.session.add(u)
        db.session.flush()
        s = Space(unit_id=u.id, name="غرفة", kind="room")
        db.session.add(s)
        db.session.flush()
        b = Bed(space_id=s.id, name="icu1", sort_order=1)
        db.session.add(b)
        db.session.commit()
        clinic["bed"] = b.id
    return clinic


def _stay(fx, hours_ago=2, outcome=None, left_hours_ago=None):
    from app.models import Admission, BedStay

    db = fx["db"]
    with fx["app"].app_context():
        came = datetime.utcnow() - timedelta(hours=hours_ago)
        adm = Admission(patient_id=fx["ids"]["child"], admitted_at=came)
        if left_hours_ago is not None:
            adm.discharged_at = datetime.utcnow() - timedelta(hours=left_hours_ago)
            adm.outcome = outcome or "home"
        db.session.add(adm)
        db.session.flush()
        db.session.add(BedStay(admission_id=adm.id, bed_id=fx["bed"], since=came))
        db.session.commit()
        return adm.id, came


def _draft(fx, client, key="test_eq", examples=EXAMPLES, licence=True):
    from app.models import SeverityScore

    client.post("/severity/new", data={"key": key, "name_ar": "مقياس تجريبي", "kind": "equation"})
    with fx["app"].app_context():
        sid = SeverityScore.query.filter_by(key=key).first().id
    client.post(f"/severity/{sid}", data={
        "name_ar": "مقياس تجريبي", "source": "أرقام مخترعة للاختبار — مش مقياس منشور",
        "licence_holder": "اختبار" if licence else "", "licence_ref": "T-1" if licence else "",
        "window_before_h": "1", "window_after_h": "1", "intercept": "-2", "tolerance": "0.0001",
        "inputs": INPUTS, "examples": examples})
    return sid


def _get(fx, sid):
    from app.models import SeverityScore

    with fx["app"].app_context():
        return fx["db"].session.get(SeverityScore, sid)


# ----------------------------------------------------------------- reading --
def test_the_lines_are_read_and_a_bad_line_is_named():
    from app.utils import severity

    rows, bad = severity.parse_inputs(INPUTS, "equation")
    assert not bad and [r["code"] for r in rows] == ["a", "b"]
    assert rows[0]["missing"] == 0 and rows[1]["missing"] is None
    _rows, bad = severity.parse_inputs(INPUTS + "\nc | ج | c | number | u | cube | 1 | ", "equation")
    assert bad == [(3, "transform")]
    rows, bad = severity.parse_inputs("w | الوزن | weight | number | g | ..999=4; 1000..=0 | \n"
                                      "s | ذكر | male | yesno | | yes=1 | 0", "points")
    assert not bad and rows[0]["bands"] == [[None, 999.0, 4.0], [1000.0, None, 0.0]]
    assert severity.inputs_text(rows, "points").splitlines()[1].startswith("s | ذكر")
    ex, bad = severity.parse_examples("a=١, b=0 => p=0.2\nnonsense")
    assert ex[0]["values"] == {"a": 1.0, "b": 0.0} and bad == [(2, "shape")]


def test_an_unmeasured_reading_takes_the_papers_value_and_a_required_one_stops_it():
    from app.utils import severity

    inputs, _ = severity.parse_inputs(INPUTS, "equation")
    score = {"kind": "equation", "inputs": inputs, "intercept": -2.0}
    got = severity.compute(score, {"b": 1.0})
    assert got["missing"] == ["a"] and abs(got["probability"] - _p(0, 1)) < 1e-12
    assert severity.compute(score, {"a": 3.0})["error"] == "required"


def test_points_with_the_papers_line_to_a_probability():
    from app.utils import severity

    inputs, _ = severity.parse_inputs("w | الوزن | weight | number | g | ..999=4; 1000..=0 | \n"
                                      "s | ذكر | male | yesno | | yes=1 | 0", "points")
    score = {"kind": "points", "inputs": inputs, "intercept": -3.0, "slope": 0.5}
    got = severity.compute(score, {"w": 800.0, "s": 1.0})
    assert got["points"] == 5 and abs(got["probability"] - 1 / (1 + math.exp(-(-3 + 2.5)))) < 1e-12


# --------------------------------------------------------------- the gate --
def test_the_score_runs_only_when_every_guard_is_met(unit):
    boss = unit["sign_in"]("boss")
    sid = _draft(unit, boss, licence=False)
    row = _get(unit, sid)
    assert row.test_ok and row.status == "draft"
    page = boss.get(f"/severity/{sid}").get_data(as_text=True)
    assert 'data-need="licence"' in page and "data-activate" not in page
    boss.post(f"/severity/{sid}/activate", data={"note": "راجعته"})
    assert _get(unit, sid).status == "draft", "no licence, no running"

    wrong = EXAMPLES.replace(f"{_p(4, 0):.6f}", "0.9")
    sid2 = _draft(unit, boss, key="test_wrong", examples=wrong)
    row = _get(unit, sid2)
    assert not row.test_ok and any(not d["ok"] for d in row.test_detail)
    boss.post(f"/severity/{sid2}/activate", data={"note": "راجعته"})
    assert _get(unit, sid2).status == "draft", "an example it cannot reproduce keeps it locked"

    sid3 = _draft(unit, boss, key="test_two", examples="\n".join(EXAMPLES.splitlines()[:2]))
    assert "examples" in __import__("app.utils.severity", fromlist=["x"]).blockers(_get(unit, sid3))

    sid4 = _draft(unit, boss, key="test_ok")
    page = boss.get(f"/severity/{sid4}").get_data(as_text=True)
    assert "data-activate" in page
    boss.post(f"/severity/{sid4}/activate", data={"note": "راجعته على الورقة"})
    row = _get(unit, sid4)
    assert row.status == "active" and row.approved_by == unit["ids"]["admin"] and row.approval_note
    assert boss.post(f"/severity/{sid4}", data={"inputs": INPUTS}).status_code == 409, \
        "an approved version is frozen"
    boss.post(f"/severity/{sid4}/version")
    from app.models import SeverityScore

    with unit["app"].app_context():
        v2 = SeverityScore.query.filter_by(key="test_ok", version=2).first()
        assert v2.status == "draft" and v2.inputs == row.inputs


def test_a_child_is_scored_inside_the_window_and_keeps_the_score(unit):
    from app.models import SeverityRecord
    from app.utils.clock import local_today

    boss = unit["sign_in"]("boss")
    sid = _draft(unit, boss)
    boss.post(f"/severity/{sid}/activate", data={"note": "ok"})
    adm, came = _stay(unit, hours_ago=0.5)
    page = boss.get(f"/severity/admission/{adm}/icu").get_data(as_text=True)
    assert "data-severity-locked" in page, "no score chosen for the unit: locked"
    boss.post("/severity/unit/icu", data={"score_id": sid, "since": (local_today() - timedelta(days=1)).isoformat()})
    assert 'data-to-severity="icu"' in boss.get(f"/beds/admission/{adm}").get_data(as_text=True)

    from app.utils.clock import to_local
    with unit["app"].app_context():
        late = to_local(came + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        inside = to_local(came + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M")
    page = boss.post(f"/severity/admission/{adm}/icu", data={"measured_at": late, "v_a": "2", "v_b": "1"},
                     follow_redirects=True).get_data(as_text=True)
    assert "برّه نافذة المقياس" in page
    boss.post(f"/severity/admission/{adm}/icu", data={"measured_at": inside, "v_b": "1"})
    with unit["app"].app_context():
        rec = SeverityRecord.query.filter_by(admission_id=adm).one()
        assert rec.score_id == sid and rec.missing == ["a"]
        assert abs(rec.probability - _p(0, 1)) < 1e-9

    sid2 = _draft(unit, boss, key="test_other")
    boss.post(f"/severity/{sid2}/activate", data={"note": "ok"})
    boss.post("/severity/unit/icu", data={"score_id": sid2, "since": local_today().isoformat()})
    with unit["app"].app_context():
        assert SeverityRecord.query.filter_by(admission_id=adm).one().score_id == sid, \
            "the unit's new score rewrites nothing"


# -------------------------------------------------------------- the board --
def test_the_board_counts_deaths_against_expected(unit):
    from app.models import SeverityRecord
    from app.utils import severity

    boss = unit["sign_in"]("boss")
    sid = _draft(unit, boss)
    boss.post(f"/severity/{sid}/activate", data={"note": "ok"})
    probs = [0.1, 0.2, 0.3, 0.4]
    died = [False, True, False, True]
    db = unit["db"]
    for p, d in zip(probs, died):
        adm, came = _stay(unit, hours_ago=48, outcome="died" if d else "home", left_hours_ago=2)
        with unit["app"].app_context():
            db.session.add(SeverityRecord(admission_id=adm, patient_id=unit["ids"]["child"], unit_kind="icu",
                                          score_id=sid, entered_at=came, measured_at=came,
                                          values={}, missing=[], probability=p))
            db.session.commit()
    with unit["app"].test_request_context():
        b = severity.board("icu")
    assert b["n"] == 4 and b["observed"] == 2 and b["expected"] == 1.0 and b["smr"] == 2.0
    low, high = severity.interval(2, 1.0)
    assert (b["low"], b["high"]) == (low, high) and low < 2.0 < high
    assert [y for _d, y in b["vlad"]] == [0.1, -0.7, -0.4, -1.0]
    assert b["few"] is True
    page = boss.get("/severity/board?unit=icu").get_data(as_text=True)
    assert 'data-kpi="smr"' in page and "data-vlad" in page and "data-few" in page
    assert "data-disclaimer" in page


def test_the_interval_reads_right():
    from app.utils import severity

    low, high = severity.interval(0, 2.0)
    assert low == 0.0 and high > 1
    low, high = severity.interval(20, 20.0)
    assert low < 1 < high
    assert severity.interval(3, 0) == (None, None)


# ----------------------------------------------------------- who and where --
def test_who_may_and_only_with_intensive_care(unit):
    boss, doc = unit["sign_in"]("boss"), unit["sign_in"]("doc")
    assert doc.get("/severity/").status_code == 403
    assert boss.get("/severity/").status_code == 200
    assert 'data-to-severity-board' in boss.get("/reports/hospital?preset=30").get_data(as_text=True)
    _modules(unit, icu=False)
    assert boss.get("/severity/").status_code == 404
    assert boss.get("/severity/board").status_code == 404
