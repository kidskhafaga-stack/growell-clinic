"""مدى التقدم أو التأخر (ASSESSMENTS_PLAN.md ت-٥).

The owner: *«التقييمات والتقارير محتاجة حاجة ديناميك وشكل حلو ومدى التقدم أو
التأخر»*.

* the developmental age per domain against the child's real age that day:
  the gap in months and the ratio — arithmetic, no cut-off;
* since the last approved assessment of the kind: months gained against
  months lived;
* every score beside the same tool's earlier ones, and which way the change
  is **as the scale is built** — lower is better on a symptom count, higher
  on a standard score; a field the catalogue gives no direction shows the
  change only;
* drawn on the assessment, the child's progress page, the printed report
  and the family's page.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_an_assessment_the_specialist_writes import neuro  # noqa: E402,F401


class _F(dict):
    def getlist(self, k):
        v = self.get(k)
        return v if isinstance(v, list) else ([v] if v else [])


def _done(c, kind, on, data):
    """An approved assessment of the test child (born 2025-01-01) on ``on``."""
    from app.models import Patient, User
    from app.utils import assessments as asm

    with c["app"].test_request_context():
        db = c["db"]
        child = db.session.get(Patient, c["ids"]["child"])
        psy = db.session.get(User, c["psy"])
        doc = db.session.get(User, c["ids"]["doctor"])
        row = asm.start(child, kind, psy, on=on)
        asm.save(row, _F(data), psy)
        row.assessed_on = on
        asm.send_for_review(row, psy)
        asm.approve(row, doc)
        db.session.commit()
        return row.id


def _get(c, aid, call):
    from app.models import Assessment
    from app.utils import assessments as asm

    with c["app"].test_request_context():
        return getattr(asm, call)(c["db"].session.get(Assessment, aid))


def test_behind_or_ahead_of_the_real_age(neuro):
    aid = _done(neuro, "development", date(2026, 1, 1),
                {"age_ages_gross_motor": "12", "age_ages_expressive": "9", "age_ages_cognitive": "13.5"})
    dev = _get(neuro, aid, "development")
    assert dev["chrono"] == 12
    rows = {r["key"]: r for r in dev["rows"]}
    assert rows["gross_motor"]["gap"] == 0 and rows["gross_motor"]["ratio"] == 100
    assert rows["expressive"]["gap"] == -3 and rows["expressive"]["ratio"] == 75
    assert rows["cognitive"]["gap"] == 1.5 and rows["cognitive"]["ratio"] == 112


def test_months_gained_against_months_lived(neuro):
    _done(neuro, "development", date(2026, 1, 1), {"age_ages_expressive": "9", "age_ages_gross_motor": "12"})
    aid = _done(neuro, "development", date(2026, 7, 1), {"age_ages_expressive": "12", "age_ages_gross_motor": "18"})
    prog = _get(neuro, aid, "progress")
    assert prog["elapsed"] == 6 and prog["since"] == date(2026, 1, 1)
    rows = {r["key"]: r for r in prog["rows"]}
    assert rows["expressive"]["gained"] == 3 and rows["expressive"]["rate"] == 50
    assert rows["gross_motor"]["gained"] == 6 and rows["gross_motor"]["rate"] == 100


def test_which_way_a_score_moved_as_the_scale_is_built(neuro):
    _done(neuro, "adhd", date(2026, 1, 1), {"use_vanderbilt_parent": "1", "t_vanderbilt_parent_inattentive": "8",
                                           "use_wisc5": "1", "t_wisc5_fsiq": "90", "t_wisc5_vci": "88"})
    aid = _done(neuro, "adhd", date(2026, 6, 1), {"use_vanderbilt_parent": "1", "t_vanderbilt_parent_inattentive": "5",
                                                 "use_wisc5": "1", "t_wisc5_fsiq": "84", "t_wisc5_vci": "88"})
    tr = {(t["tool"], t["field"]["key"]): t for t in _get(neuro, aid, "trends")}
    assert tr[("vanderbilt_parent", "inattentive")]["delta"] == -3
    assert tr[("vanderbilt_parent", "inattentive")]["direction"] == "better", "fewer symptoms"
    assert tr[("wisc5", "fsiq")]["direction"] == "worse", "a lower standard score"
    assert tr[("wisc5", "vci")]["direction"] == "same"
    assert len(tr[("vanderbilt_parent", "inattentive")]["points"]) == 2


def test_a_score_used_under_another_kind_is_the_same_line(neuro):
    _done(neuro, "development", date(2026, 1, 1), {"use_vineland3": "1", "t_vineland3_abc": "70"})
    aid = _done(neuro, "autism", date(2026, 7, 1), {"use_vineland3": "1", "t_vineland3_abc": "76"})
    tr = {(t["tool"], t["field"]["key"]): t for t in _get(neuro, aid, "trends")}
    assert tr[("vineland3", "abc")]["prev"] == 70 and tr[("vineland3", "abc")]["direction"] == "better"


def test_it_is_drawn_everywhere_the_assessment_is_read(neuro):
    from app.utils import assessment_share

    _done(neuro, "development", date(2026, 1, 1), {"age_ages_expressive": "9", "use_asq3": "1", "t_asq3_communication": "30"})
    aid = _done(neuro, "development", date(2026, 7, 1), {"age_ages_expressive": "12", "use_asq3": "1", "t_asq3_communication": "45"})
    doc = neuro["sign_in"]("doc")
    page = doc.get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-dev-bars" in page and 'data-dev-progress="expressive"' in page
    assert 'data-trend-chip="better"' in page
    page = doc.get(f"/assessments/patient/{neuro['ids']['child']}").get_data(as_text=True)
    assert 'data-progress-kind="development"' in page and 'data-trend="asq3.communication"' in page
    assert "data-dev-bars" in doc.get(f"/assessments/{aid}/report").get_data(as_text=True)
    from app.models import Assessment

    with neuro["app"].test_request_context():
        sheet = assessment_share.sheet(neuro["db"].session.get(Assessment, aid), "ar")
    assert "data-sheet-ages" in sheet and "data-sheet-trends" in sheet


def test_the_age_box_takes_months_in_range(neuro):
    from app.models import Assessment

    psy = neuro["sign_in"]("psy")
    reply = psy.post(f"/assessments/patient/{neuro['ids']['child']}/new", data={"kind": "language"})
    aid = int(reply.headers["Location"].rstrip("/").split("/")[-1])
    page = psy.get(f"/assessments/{aid}").get_data(as_text=True)
    assert 'data-age-field="receptive"' in page and "data-chrono" in page
    psy.post(f"/assessments/{aid}/save", data={"age_ages_receptive": "٢٤"})
    with neuro["app"].app_context():
        assert neuro["db"].session.get(Assessment, aid).answers["ages"] == {"receptive": 24}
    psy.post(f"/assessments/{aid}/save", data={"age_ages_receptive": "999"})
    with neuro["app"].app_context():
        assert neuro["db"].session.get(Assessment, aid).answers["ages"] == {"receptive": 24}, "out of range refused"


def test_no_approved_assessment_says_so(neuro):
    page = neuro["sign_in"]("doc").get(f"/assessments/patient/{neuro['ids']['child']}").get_data(as_text=True)
    assert "data-progress-empty" in page
