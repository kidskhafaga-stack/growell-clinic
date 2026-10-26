"""«عدّل التخصص» (ASSESSMENTS_PLAN.md ق-١).

Asked by the clinic's owner: *«ليه فى شاشة التخصصات دي مش بنقدر نضيف بند فى
التخصص نشيل بند ونقل بنقيس ايه وبنقيسه ازاي بحيث البرنامج يفهمه صح؟»*

* a field is added with its type, unit, sensible range, decimal places and
  «how it is measured», and the visit screen asks it and saves it — refusing a
  number outside the range and rounding to the places;
* a catalogue field is hidden (not asked, not saved, its readings kept and
  still named), renamed, moved; the catalogue file itself never changes;
* an option a reading was taken with cannot be removed;
* a clinic field with readings is hidden instead of deleted, and survives
  «back to the original»;
* a number may carry an alert, which then waits on the clinic's figure;
* only an admin edits, and only with the module on.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, _readings, _save, desk)

_CATALOGUE = os.path.join(os.path.dirname(__file__), "..", "app", "data", "specialty_panels.json")


def _edit(desk, key="cardiology", who="boss", **form):
    form.setdefault("code", "")
    return desk["sign_in"](who).post(f"/panels/{key}/edit", data=form, follow_redirects=True)


def _panel(desk, key="cardiology"):
    from app.utils import panels

    with desk["app"].test_request_context():
        return panels.panel(key)


def _codes(meta, part="fields"):
    return [f["code"] for f in meta.get(part, [])]


def _own(desk, key="cardiology"):
    return [f for f in _panel(desk, key)["fields"] + _panel(desk, key).get("hidden_fields", [])
            if f.get("own")]


def test_the_door_and_the_screen(desk):
    _module(desk, True)
    page = desk["sign_in"]("boss").get("/panels/").get_data(as_text=True)
    assert 'data-to-panel-edit="cardiology"' in page
    page = desk["sign_in"]("boss").get("/panels/cardiology/edit").get_data(as_text=True)
    assert 'data-edit-field="ef_pct"' in page and "data-add-field" in page
    assert "data-panel-default" in page
    assert desk["sign_in"]("boss").get("/panels/nothing/edit").status_code == 404


def test_only_an_admin_and_only_with_the_module(desk):
    _module(desk, False)
    assert desk["sign_in"]("boss").get("/panels/cardiology/edit").status_code in (403, 404)
    _module(desk, True)
    assert desk["sign_in"]("doc").get("/panels/cardiology/edit").status_code in (302, 403)
    before = open(_CATALOGUE, encoding="utf-8").read()
    _edit(desk, who="doc", do="hide", code="ef_pct")
    assert "ef_pct" in _codes(_panel(desk))
    assert open(_CATALOGUE, encoding="utf-8").read() == before


def test_a_number_the_clinic_adds_is_asked_ranged_and_rounded(desk):
    _module(desk, True)
    _edit(desk, do="add", label_ar="محيط الذراع", label_en="Arm circumference", type="number",
          unit="cm", min="5", max="40", decimals="1", how_ar="بالمتر الشريطي في نص الذراع",
          chart="1")
    own = _own(desk)
    assert len(own) == 1
    code = own[0]["code"]
    assert code == "c_cardiology_1" and own[0]["type"] == "number"
    page = _page(desk)
    assert f'name="m_{code}"' in page and f'data-how="{code}"' in page
    assert "بالمتر الشريطي في نص الذراع" in page

    _save(desk, specialty_panel="cardiology", **{f"m_{code}": "١٢٫٣٤"})
    assert _readings(desk)[code].value_num == 12.3, "rounded to the clinic's one place"

    page = _save(desk, specialty_panel="cardiology", **{f"m_{code}": "123"}).get_data(as_text=True)
    assert _readings(desk)[code].value_num == 12.3, "a number outside the range is not written"
    assert "برّه المدى المعقول" in page


def test_hidden_is_not_asked_not_saved_and_keeps_its_name(desk):
    from app.models import Measurement
    from app.utils import panels

    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_ef_pct="60")
    assert _readings(desk)["ef_pct"].value_num == 60
    _edit(desk, do="hide", code="ef_pct")
    meta = _panel(desk)
    assert "ef_pct" not in _codes(meta) and "ef_pct" in _codes(meta, "hidden_fields")
    assert 'name="m_ef_pct"' not in _page(desk)
    _save(desk, specialty_panel="cardiology", m_ef_pct="")
    assert _readings(desk)["ef_pct"].value_num == 60, "a hidden field's reading is never erased"
    with desk["app"].test_request_context():
        assert panels.field_labels()["ef_pct"]["label_ar"]
        assert Measurement.query.filter_by(code="ef_pct").count() == 1
    _edit(desk, do="show", code="ef_pct")
    assert 'name="m_ef_pct"' in _page(desk)


def test_renamed_and_moved_over_a_catalogue_that_stays(desk):
    _module(desk, True)
    before = open(_CATALOGUE, encoding="utf-8").read()
    _edit(desk, do="field", code="ef_pct", label_ar="الكسر القذفي للعيادة", label_en="EF (clinic)",
          unit="%", min="5", max="90", decimals="0", chart="1")
    meta = _panel(desk)
    ef = next(f for f in meta["fields"] if f["code"] == "ef_pct")
    assert ef["label_ar"] == "الكسر القذفي للعيادة" and ef["max"] == 90
    assert "الكسر القذفي للعيادة" in _page(desk)
    order = [c for c in _codes(meta) if next(f for f in meta["fields"] if f["code"] == c)["type"] != "flag"]
    second = order[1]
    _edit(desk, do="up", code=second)
    order2 = [c for c in _codes(_panel(desk)) if c in order]
    assert order2[0] == second and order2[1] == order[0]
    assert open(_CATALOGUE, encoding="utf-8").read() == before, "the catalogue file is never written"


def test_an_option_with_readings_stays(desk):
    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_nyha_ross="II")
    page = _edit(desk, do="field", code="nyha_ross", label_ar="درجة القصور",
                 options="I\nIII\nIV").get_data(as_text=True)
    assert "عليه قراءات" in page
    assert "II" in next(f for f in _panel(desk)["fields"] if f["code"] == "nyha_ross")["options"]
    _edit(desk, do="field", code="nyha_ross", label_ar="درجة القصور", options="I\nII\nIII\nIV\nغير محدد")
    assert "غير محدد" in next(f for f in _panel(desk)["fields"] if f["code"] == "nyha_ross")["options"]


def test_a_clinic_field_with_readings_is_hidden_not_deleted_and_survives_reset(desk):
    _module(desk, True)
    _edit(desk, do="add", label_ar="ملاحظة الإيكو", type="text")
    _edit(desk, do="add", label_ar="مش هتتملي", type="yesno")
    used, empty = [f["code"] for f in _own(desk)]
    assert next(f for f in _own(desk) if f["code"] == empty)["options"] == ["نعم", "لأ"]
    _save(desk, specialty_panel="cardiology", **{f"m_{used}": "ارتجاع بسيط"})
    assert _readings(desk)[used].value_text == "ارتجاع بسيط"

    page = _edit(desk, do="remove", code=used).get_data(as_text=True)
    assert "استخبت بدل ما تتمسح" in page
    assert used in _codes(_panel(desk), "hidden_fields")
    _edit(desk, do="remove", code=empty)
    assert empty not in [f["code"] for f in _own(desk)]

    _edit(desk, do="hide", code="ef_pct")
    _edit(desk, do="reset")
    meta = _panel(desk)
    assert "ef_pct" in _codes(meta)
    assert used in _codes(meta, "hidden_fields"), "a field holding readings outlives the reset"
    _edit(desk, do="add", label_ar="خانة جديدة", type="date")
    fresh = [f["code"] for f in _own(desk) if f["label_ar"] == "خانة جديدة"]
    assert fresh and fresh[0] not in (used, empty), "a code is never reused"


def test_a_number_may_carry_an_alert_that_waits_for_the_figure(desk):
    from app.utils import panel_alerts

    _module(desk, True)
    _edit(desk, do="add", label_ar="ضغط الشريان الرئوي", type="number", unit="mmHg", alert="1", chart="1")
    code = _own(desk)[0]["code"]
    with desk["app"].test_request_context():
        alerts = {a["code"]: a for a in panel_alerts.watchable("cardiology")}
        assert f"{code}_above" in alerts and f"{code}_below" in alerts
        assert alerts[f"{code}_above"]["watches"] == {"source": "panel", "of": code, "when": "above"}
        assert panel_alerts.armed("cardiology", f"{code}_above") is None, "nothing fires before a figure"
    page = desk["sign_in"]("boss").get("/panels/alerts").get_data(as_text=True)
    assert "ضغط الشريان الرئوي" in page


def test_a_number_not_drawn_stays_off_the_curves(desk):
    from app.utils import series

    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_ef_pct="55")
    with desk["app"].test_request_context():
        assert any(p[0] == "panel:ef_pct" for p in series._panel_points(desk["ids"]["child"]))
    _edit(desk, do="field", code="ef_pct", label_ar="EF", unit="%")
    with desk["app"].test_request_context():
        assert not any(p[0] == "panel:ef_pct" for p in series._panel_points(desk["ids"]["child"]))


def test_bad_input_is_refused_with_a_reason(desk):
    _module(desk, True)
    assert "أقل رقم أكبر من أعلى رقم" in _edit(desk, do="add", label_ar="س", type="number",
                                               min="10", max="2").get_data(as_text=True)
    assert "اختيارين على الأقل" in _edit(desk, do="add", label_ar="س", type="choice",
                                          options="واحد").get_data(as_text=True)
    assert "اختار نوع الخانة" in _edit(desk, do="add", label_ar="س", type="photo").get_data(as_text=True)
    assert _own(desk) == []
    with desk["app"].app_context():
        from app.models import Setting

        raw = Setting.get("panel_edit:cardiology")
        assert raw is None or not json.loads(raw).get("added")
