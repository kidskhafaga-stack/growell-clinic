"""المراجع من نشرة الكيت — المساعد بينقل المطبوع، وحد بيراجع، ومدير المعمل بيوافق.

* القراية مقفولة لحد ما المستشفى تفتح مفتاحها، وبتحتاج مكونات التحليل الأول؛
* المساعد بيرجّع اقتراحات في فورم جنب مكونات التحليل، و**مفيش حاجة بتتحفظ**
  غير السطور المعلّم عليها؛
* السطر بوحدة غير وحدة المكوّن ما بيتعلّمش ولا بيتحفظ — البرنامج مش بيحوّل؛
  والسن اللي البرنامج مش فاهمه بيتقال؛
* اللي بيتحفظ **مسودة** مكتوب عليها «Kit insert»، وما بتحكمش على نتيجة لحد
  الموافقة، ولما تتوافق بتحل محل المراجع القديمة المعتمدة.
"""
import io
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_control_insert_read_and_a_month_counted import PNG, _ai  # noqa: E402

REPLY = {"kit": "BIL-T Gen.3", "lot": "L889",
         "advice": "Each laboratory should establish its own reference ranges.",
         "rows": [
             {"analyte": "Bilirubin total", "group": "1-12 months", "sex": "all",
              "low": 0.2, "high": 1.2, "unit": "mg/dL"},
             {"analyte": "Bilirubin total", "group": "1-12 months", "sex": "all",
              "low": 3.4, "high": 20.5, "unit": "µmol/L"},
             {"analyte": "Bilirubin direct", "group": "Children", "low": None, "high": 0.3,
              "unit": "mg/dL"},
             {"analyte": "Mystery", "group": "all", "low": "n/a"}]}


@pytest.fixture()
def posted(monkeypatch):
    sent = []

    class _Resp:
        ok = True
        status_code = 200
        text = ""

        def json(self):
            return {"content": [{"type": "text", "text": json.dumps(REPLY)}]}

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        sent.append({"url": url, "json": json})
        return _Resp()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


@pytest.fixture()
def lab(clinic):
    from app.models import Investigation, LabAnalyte, LabRange, LabTestAnalyte, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        test = Investigation(name_ar="نسبة الصفراء", name_en="Bilirubin", kind="lab")
        empty = Investigation(name_ar="تحليل جديد", kind="lab")
        tb = LabAnalyte(name="Total Bilirubin", aliases="Bilirubin total; T.Bil", unit="mg/dL")
        db_ = LabAnalyte(name="Direct Bilirubin", aliases="Bilirubin direct", unit="mg/dL")
        db.session.add_all([test, empty, tb, db_])
        db.session.flush()
        db.session.add_all([LabTestAnalyte(investigation_id=test.id, analyte_id=tb.id, sort_order=1),
                            LabTestAnalyte(investigation_id=test.id, analyte_id=db_.id, sort_order=2)])
        old = LabRange(analyte_id=tb.id, age_from_days=30, age_to_days=365, age_label="1-12 months",
                       low=0.1, high=1.0, source="old sheet", approved_at=datetime.utcnow())
        db.session.add(old)
        db.session.commit()
        clinic["ids"].update(test=test.id, empty=empty.id, tb=tb.id, dbil=db_.id, old=old.id)
    return clinic


def _upload(c, test_id):
    return c["sign_in"]("boss").post(
        f"/labs/tests/{test_id}/insert",
        data={"instrument": "Cobas c311", "insert": (io.BytesIO(PNG), "bil.png")},
        content_type="multipart/form-data")


def test_off_until_switched_on_and_needs_components(lab, posted):
    _ai(lab, on=False)
    page = lab["sign_in"]("boss").get(f"/labs/tests/{lab['ids']['test']}/ranges").get_data(as_text=True)
    assert 'data-kit-insert="off"' in page
    _upload(lab, lab["ids"]["test"])
    _ai(lab)
    _upload(lab, lab["ids"]["empty"])
    assert posted == [], "off, or a test with no components: nothing is asked"


def test_proposals_beside_the_components_and_only_the_ticked_saved_as_drafts(lab, posted):
    from app.models import LabRange
    from app.utils import lab_hand

    _ai(lab)
    ids = lab["ids"]
    page = lab["sign_in"]("boss").get(f"/labs/tests/{ids['test']}/ranges").get_data(as_text=True)
    assert 'data-kit-insert="on"' in page
    form = _upload(lab, ids["test"]).get_data(as_text=True)
    assert len(posted) == 1 and "Cobas c311" in json.dumps(posted[0]["json"])
    assert "data-kit-advice" in form, "the insert's own advice is shown"
    assert 'data-kit-row="2"' in form and 'data-kit-row="3"' not in form, "no figure, no row"
    assert "data-kit-unit-differs" in form and "data-kit-age-unread" in form
    with lab["app"].app_context():
        assert LabRange.query.count() == 1, "nothing saved by being shown"
    boss = lab["sign_in"]("boss")
    rows = {"count": "3", "kit_all": "BIL-T Gen.3", "lot_all": "L889"}
    for i, (aid, age, low, high, unit) in enumerate((
            (ids["tb"], "1-12 months", "0.2", "1.2", "mg/dL"),
            (ids["tb"], "1-12 months", "3.4", "20.5", "µmol/L"),
            (ids["dbil"], "18 years+", "", "0.3", "mg/dL"))):
        rows.update({f"analyte_id_{i}": str(aid), f"age_{i}": age, f"sex_{i}": "all",
                     f"low_{i}": low, f"high_{i}": high, f"unit_{i}": unit,
                     f"printed_{i}": "x"})
    # The µmol/L line ticked: refused whole, nothing saved.
    boss.post(f"/labs/tests/{ids['test']}/insert/save", data={**rows, "take": ["0", "1"]})
    with lab["app"].app_context():
        assert LabRange.query.count() == 1
    boss.post(f"/labs/tests/{ids['test']}/insert/save", data={**rows, "take": ["0", "2"]})
    with lab["app"].app_context():
        new = LabRange.query.filter(LabRange.id != ids["old"]).all()
        assert len(new) == 2 and all(not r.approved and not r.manual for r in new)
        assert all(r.source.startswith("Kit insert · BIL-T Gen.3 · lot L889") for r in new)
        assert {(r.low, r.high) for r in new} == {(0.2, 1.2), (None, 0.3)}
        # Approved: the kit's ranges replace the old sheet's.
        from app.models import Investigation, User
        lab_hand.approve(lab["db"].session.get(Investigation, ids["test"]),
                         lab["db"].session.get(User, lab["ids"]["boss"]) if "boss" in lab["ids"] else None)
        lab["db"].session.commit()
        assert lab["db"].session.get(LabRange, ids["old"]) is None
        assert LabRange.query.filter(LabRange.approved_at.isnot(None)).count() == 2
