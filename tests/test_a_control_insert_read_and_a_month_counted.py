"""نشرة الكنترول بيقراها المساعد — وحد بيراجع؛ وأرقام الشهر بتتحسب قبل المراجعة.

* القراية مقفولة لحد ما المستشفى تفتح مفتاحها؛
* المساعد بيرجّع اقتراحات في فورم، و**مفيش حاجة بتتحفظ** غير السطور اللي
  حد علّم عليها، من نفس باب الكنترول اللي بيتكتب بالإيد؛
* الـ SD بيتاخد بس لو مطبوع — مدى مطبوع ما بيتحولش لـ SD؛
* أرقام الشهر لكل كنترول (n، المتوسط، SD، CV، الانحراف عن الهدف) حساب
  بس، من غير حكم.
"""
import io
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
       b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")

REPLY = {"lot": "45720", "expiry": "2027-03-31", "rows": [
    {"analyte": "Glucose", "level": "Level 1", "mean": 92.5, "sd": 3.1, "unit": "mg/dL"},
    {"analyte": "Creatinine", "level": "Level 1", "mean": "0.82", "unit": "mg/dL"},
    {"analyte": "Mystery", "level": "Level 2", "mean": "not a number"},
]}


def _ai(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        for k, v in (("ai_enabled", "1"), ("ai_provider", "claude"),
                     ("ai_api_key", "test-key"), ("ai_model", "test-model"),
                     ("ai_lab_insert", "1" if on else "0")):
            Setting.set(k, v)
        c["db"].session.commit()


@pytest.fixture()
def posted(monkeypatch):
    sent = []

    class _Resp:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        sent.append({"url": url, "json": json})
        import json as _j
        return _Resp({"content": [{"type": "text", "text": _j.dumps(REPLY)}]})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


@pytest.fixture()
def analytes(lab):
    from app.models import LabAnalyte

    with lab["app"].app_context():
        g = LabAnalyte(name="Glucose", unit="mg/dL")
        cr = LabAnalyte(name="Creat", aliases="Creatinine; CREA", unit="mg/dL")
        lab["db"].session.add_all([g, cr])
        lab["db"].session.commit()
        lab["glu"], lab["cre"] = g.id, cr.id
    return lab


def _upload(c):
    return c["sign_in"]("boss").post(
        "/labs/quality/insert",
        data={"instrument": "Cobas c311", "insert": (io.BytesIO(PNG), "Lyphochek.png")},
        content_type="multipart/form-data")


def test_off_until_switched_on(analytes, posted):
    _ai(analytes, on=False)
    page = analytes["sign_in"]("boss").get("/labs/quality").get_data(as_text=True)
    assert "data-insert-read" not in page
    _upload(analytes)
    assert posted == []


def test_read_into_a_form_and_nothing_saved(analytes, posted):
    from app.models import QcMaterial

    _ai(analytes)
    page = analytes["sign_in"]("boss").get("/labs/quality").get_data(as_text=True)
    assert "data-insert-read" in page
    form = _upload(analytes).get_data(as_text=True)
    assert len(posted) == 1
    assert "Cobas c311" in json.dumps(posted[0]["json"])
    assert 'data-insert-row="0"' in form and 'data-insert-row="1"' in form
    assert 'data-insert-row="2"' not in form, "a mean that is not a number is dropped"
    assert "data-insert-no-sd" in form, "no SD printed, none made up"
    assert 'value="45720"' in form and 'value="2027-03-31"' in form
    # The alias found the laboratory's creatinine.
    assert f'<option value="{analytes["cre"]}" selected' in form
    with analytes["app"].app_context():
        assert QcMaterial.query.count() == 0, "shown is not saved"


def test_only_the_ticked_lines_are_saved_through_the_ordinary_door(analytes, posted):
    from app.models import QcMaterial

    _ai(analytes)
    base = {"count": "2", "name_all": "Lyphochek", "lot_all": "45720",
            "expiry_all": "2027-03-31",
            "printed_0": "Glucose", "analyte_id_0": str(analytes["glu"]), "level_0": "Level 1",
            "target_mean_0": "92.5", "target_sd_0": "3.1", "unit_0": "mg/dL",
            "printed_1": "Creatinine", "analyte_id_1": str(analytes["cre"]), "level_1": "Level 1",
            "target_mean_1": "0.82", "target_sd_1": "", "unit_1": "mg/dL"}
    boss = analytes["sign_in"]("boss")
    # Ticking the line with no SD is refused — all or nothing — and the form comes back.
    back = boss.post("/labs/quality/insert/save", data={**base, "take": ["0", "1"]})
    assert back.status_code == 200 and "data-insert-form" in back.get_data(as_text=True)
    with analytes["app"].app_context():
        assert QcMaterial.query.count() == 0
    boss.post("/labs/quality/insert/save", data={**base, "take": ["0"]})
    with analytes["app"].app_context():
        rows = QcMaterial.query.all()
        assert len(rows) == 1
        m = rows[0]
        assert (m.target_mean, m.target_sd, m.lot_number, str(m.expiry_date)) == (92.5, 3.1, "45720", "2027-03-31")
        assert m.analyte_id == analytes["glu"] and "Lyphochek" in m.name


def test_the_month_is_counted_not_judged(lab):
    from app.models import QcMaterial, QcRun
    from app.utils import lab_quality

    with lab["app"].app_context():
        m = QcMaterial(name="Glucose control", level="L1", target_mean=100, target_sd=5)
        lab["db"].session.add(m)
        lab["db"].session.flush()
        for v, ok in ((98, True), (102, True), (104, True), (120, False)):
            lab["db"].session.add(QcRun(material_id=m.id, value=v, accepted=ok,
                                        run_at=datetime(2026, 9, 10)))
        lab["db"].session.add(QcRun(material_id=m.id, value=500, accepted=True,
                                    run_at=datetime(2026, 10, 1)))
        lab["db"].session.commit()
        stats = lab_quality.month_stats("2026-09")
        assert len(stats) == 1
        s = stats[0]
        assert s["n"] == 4 and s["mean"] == pytest.approx(106.0)
        assert s["sd"] == pytest.approx(9.661, rel=1e-3)
        assert s["cv"] == pytest.approx(9.114, rel=1e-3)
        assert s["bias"] == pytest.approx(6.0)
        assert s["rejected"] == 1 and s["no_action"] == 1
        assert lab_quality.month_stats("not a month") == []
    page = lab["sign_in"]("boss").get("/labs/quality").get_data(as_text=True)
    assert 'data-month-stats="2026-09"' in page
