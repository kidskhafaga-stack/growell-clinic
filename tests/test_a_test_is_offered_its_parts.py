"""تحليل اسمه معروف بيتعرض عليه مكوناته — أسماء ووحدات، من غير ولا رقم.

Asked as *«معنديش كل تحليل مكوناته ايه؟ هل ممكن احنا ندرجها؟»*:

* «تحليل بول كامل» بيتعرض عليه الفحص الظاهري والكيميائي والميكروسكوبي، وما
  بيتضافش حاجة غير لما حد يدوس حفظ، واللي اتشالت علامته ما بيتضافش؛
* المكوّن اللي المعمل عنده باسم تاني (Hb) بيتربط هو نفسه بمراجعه؛
* الصفراء غير المباشرة بتتحسب لوحدها لما الكلية والمباشرة يكونوا موجودين؛
* «مزرعة بول» مش تحليل بول — الاسم لازم يطابق كله؛
* **ولا رقم**: الملف نفسه ما فيهوش ولا مرجع، والمكونات بتتضاف من غير مراجع.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def lab(clinic):
    from app.models import Investigation, LabAnalyte, LabRange, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        rows = {
            "urine": Investigation(name_ar="تحليل بول كامل", kind="lab", is_active=True),
            "culture": Investigation(name_ar="مزرعة بول", name_en="Urine culture", kind="lab", is_active=True),
            "cbc": Investigation(name_ar="صورة دم", name_en="Complete Blood Count (CBC)", kind="lab", is_active=True),
            "bili": Investigation(name_ar="نسبة الصفراء", kind="lab", is_active=True),
            "tbil": Investigation(name_ar="صفراء كلية", name_en="Total Bilirubin", kind="lab", is_active=True),
        }
        hb = LabAnalyte(name="Hb", aliases="Hemoglobin; HGB", unit="g/dL")
        db.session.add_all(list(rows.values()) + [hb])
        db.session.flush()
        db.session.add(LabRange(analyte_id=hb.id, age_from_days=365, age_label="1 year+",
                                low=11.0, high=14.5, source="sheet"))
        db.session.commit()
        clinic["ids"].update({k: v.id for k, v in rows.items()}, hb=hb.id)
    return clinic


def test_the_list_holds_names_and_units_and_never_a_figure():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "data", "lab_panel_parts.json")
    data = json.load(open(path, encoding="utf-8"))
    allowed = {"name", "name_ar", "unit", "group", "formula", "inputs"}
    for panel in data["panels"]:
        for part in panel["parts"]:
            assert set(part) <= allowed, (panel["key"], part)
            assert not any(isinstance(v, (int, float)) for v in part.values())


def test_a_urine_analysis_is_offered_its_parts_and_only_the_ticked_are_added(lab):
    from app.models import Investigation, LabRange

    boss = lab["sign_in"]("boss")
    tid = lab["ids"]["urine"]
    page = boss.get(f"/labs/tests/{tid}/ranges").get_data(as_text=True)
    assert 'data-parts-offer="urine"' in page
    for group in ("physical", "chemical", "microscopic"):
        assert f'data-parts-group="{group}"' in page
    with lab["app"].app_context():
        assert not lab["db"].session.get(Investigation, tid).analyte_links, "nothing until saved"
    from app.utils import lab_parts
    names = [p["name"] for p in lab_parts.panels()[0]["parts"]]
    keep = [i for i, n in enumerate(names) if n != "Urine Yeast"]
    data = {"part": [str(i) for i in keep], f"unit_{names.index('Urine Pus Cells')}": "/HPF"}
    boss.post(f"/labs/tests/{tid}/parts", data=data)
    with lab["app"].app_context():
        test = lab["db"].session.get(Investigation, tid)
        got = [link.analyte.name for link in test.analyte_links]
        assert "Urine Yeast" not in got and len(got) == len(names) - 1
        assert "Urine Glucose" in got and "Glucose" not in got, "urine glucose is not blood glucose"
        pus = next(l.analyte for l in test.analyte_links if l.analyte.name == "Urine Pus Cells")
        assert pus.unit == "/HPF" and pus.name_ar
        assert LabRange.query.filter(LabRange.analyte_id.in_(
            [l.analyte_id for l in test.analyte_links])).count() == 0, "no figure came with them"
    page = boss.get(f"/labs/tests/{tid}/ranges").get_data(as_text=True)
    assert 'data-part-state="on"' in page and 'data-part-state="new"' in page, "only Yeast is left"


def test_an_analyte_the_lab_has_is_linked_and_indirect_bilirubin_is_calculated(lab):
    from app.models import Investigation, LabAnalyte

    boss = lab["sign_in"]("boss")
    page = boss.get(f"/labs/tests/{lab['ids']['cbc']}/ranges").get_data(as_text=True)
    assert 'data-parts-offer="cbc"' in page and 'data-part-state="reuse"' in page
    boss.post(f"/labs/tests/{lab['ids']['cbc']}/parts", data={"part": ["0", "1"]})
    boss.post(f"/labs/tests/{lab['ids']['bili']}/parts", data={"part": ["0", "1", "2"]})
    with lab["app"].app_context():
        cbc = lab["db"].session.get(Investigation, lab["ids"]["cbc"])
        assert cbc.analyte_links[0].analyte_id == lab["ids"]["hb"], "the lab's own Hb, not a copy"
        assert LabAnalyte.query.filter(lab["db"].func.lower(LabAnalyte.name) == "hemoglobin").count() == 0
        ind = LabAnalyte.query.filter_by(name="Indirect Bilirubin").one()
        assert ind.formula == "indirect_bili"
    page = boss.get(f"/labs/tests/{lab['ids']['cbc']}/ranges").get_data(as_text=True)
    assert "1 year+" in page, "the linked analyte came with its ranges"


def test_only_a_whole_name_is_a_known_test(lab):
    boss = lab["sign_in"]("boss")
    for key in ("culture", "tbil"):
        page = boss.get(f"/labs/tests/{lab['ids'][key]}/ranges").get_data(as_text=True)
        assert "data-parts-offer" not in page, key
    listing = boss.get("/labs/tests").get_data(as_text=True)
    assert listing.count("data-parts-known") == 3, "urine, CBC and bilirubin"
