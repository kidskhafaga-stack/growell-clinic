"""A form the clinic draws itself — ``FORM_BUILDER_PLAN.md``.

The program had seven small editors, each shut on one thing, and none that
let a clinic make a form of its own. What is held here:

* designing is ``forms_design`` (the administrator), not everybody;
* the fields: a heading, text, a number with unit and range, a date,
  yes/no, one or several choices — Arabic and English, required or not, in
  order;
* a field's key never changes; a field with answers is hidden, not deleted;
  an option somebody picked cannot be taken out, and keeps its key when the
  list is reordered;
* filling checks the required boxes, the range, the date and the options,
  and saves nothing otherwise; a visit form needs this child's visit;
* each entry keeps the shape it was filled on, and reads and prints so;
* the clinical audience needs the medical file, the desk audience does not;
* «the stay» is offered only where the wards are;
* the numbers: yes/no, each option, the mean, least and greatest; CSV;
* the doors: the file, the visit and settings.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def drawn(clinic):
    """A clinical form on the child's file: a heading, a number in range,
    yes/no (required), one choice and several."""
    from app.extensions import db
    from app.models import User
    from app.utils import custom_forms as cf

    with clinic["app"].app_context():
        boss = db.session.get(User, clinic["ids"]["admin"])
        form = cf.new_form({"name_ar": "متابعة الربو", "place": "patient",
                            "audience": "clinical"}, boss)
        db.session.flush()
        cf.add_field(form, {"type": "heading", "label_ar": "الأعراض"})
        cf.add_field(form, {"type": "number", "label_ar": "ذروة التدفق",
                            "unit": "L/min", "min": "50", "max": "800"})
        cf.add_field(form, {"type": "yesno", "label_ar": "صحيان بالليل",
                            "required": "1"})
        cf.add_field(form, {"type": "choice", "label_ar": "المستوى",
                            "options_ar": "مسيطر\nجزئي\nغير مسيطر"})
        cf.add_field(form, {"type": "multi", "label_ar": "المحفزات",
                            "options_ar": "تراب\nبرد\nدخان"})
        db.session.commit()
        clinic["form"] = form.id
    return clinic


def _fill(c, who="doc", **answers):
    data = {"patient_id": c["ids"]["child"]}
    data.update({f"a_{k}": v for k, v in answers.items()})
    return c["sign_in"](who).post(f"/forms/{c['form']}/fill", data=data)


def _entries(c):
    from app.models import FormEntry

    with c["app"].app_context():
        return [(e.form_version, e.answers) for e in
                FormEntry.query.order_by(FormEntry.id)]


def _form(c):
    from app.extensions import db
    from app.models import CustomForm

    with c["app"].app_context():
        f = db.session.get(CustomForm, c["form"])
        return {"version": f.version, "fields": f.fields}


# --------------------------------------------------------------- design ---
def test_only_a_designer_draws(drawn):
    assert drawn["sign_in"]("doc").get(f"/forms/{drawn['form']}") \
        .status_code == 403
    resp = drawn["sign_in"]("doc").post("/forms/new",
                                        data={"name_ar": "س"})
    assert resp.status_code == 403
    page = drawn["sign_in"]("boss").get(f"/forms/{drawn['form']}") \
        .get_data(as_text=True)
    assert 'data-fields="5"' in page
    for kind in ("heading", "number", "yesno", "choice", "multi"):
        assert f':{kind}"' in page


def test_the_boxes_are_checked_and_nothing_saved_otherwise(drawn):
    # f3 (yes/no) is required.
    _fill(drawn, f2="120")
    # Out of range.
    _fill(drawn, f2="1000", f3="yes")
    # An option that does not exist.
    _fill(drawn, f3="yes", f4="o9")
    assert _entries(drawn) == []
    resp = _fill(drawn, f2="320", f3="no", f4="o2", f5=["o1", "o3"])
    assert resp.status_code == 302
    [(version, answers)] = _entries(drawn)
    assert answers == {"f2": 320.0, "f3": "no", "f4": "o2",
                       "f5": ["o1", "o3"]}


def test_clinical_needs_the_file_desk_does_not(drawn):
    from app.extensions import db
    from app.models import CustomForm

    assert _fill(drawn, who="desk", f3="yes").status_code == 403
    with drawn["app"].app_context():
        db.session.get(CustomForm, drawn["form"]).audience = "desk"
        db.session.commit()
    assert _fill(drawn, who="desk", f3="yes").status_code == 302


def test_an_answered_field_hides_and_an_unanswered_one_goes(drawn):
    _fill(drawn, f3="yes", f4="o1")
    boss = drawn["sign_in"]("boss")
    boss.post(f"/forms/{drawn['form']}", data={"action": "hide", "key": "f3"})
    boss.post(f"/forms/{drawn['form']}", data={"action": "hide", "key": "f5"})
    fields = {f["key"]: f for f in _form(drawn)["fields"]}
    assert fields["f3"]["hidden"] is True        # answered: kept, hidden
    assert "f5" not in fields                    # never answered: gone
    # The key is never reused.
    boss.post(f"/forms/{drawn['form']}", data={
        "action": "add", "type": "text", "label_ar": "ملاحظات"})
    assert [f["key"] for f in _form(drawn)["fields"]][-1] == "f6"


def test_a_picked_option_stays_and_keeps_its_key(drawn):
    _fill(drawn, f3="yes", f4="o2")          # «جزئي»
    boss = drawn["sign_in"]("boss")
    # Taking «جزئي» out is refused.
    boss.post(f"/forms/{drawn['form']}", data={
        "action": "field", "key": "f4", "label_ar": "المستوى",
        "options_ar": "مسيطر\nغير مسيطر"})
    assert [o["ar"] for o in _form(drawn)["fields"][3]["options"]] == \
        ["مسيطر", "جزئي", "غير مسيطر"]
    # Reordered, with one added: «جزئي» keeps o2, the new one gets o4.
    boss.post(f"/forms/{drawn['form']}", data={
        "action": "field", "key": "f4", "label_ar": "المستوى",
        "options_ar": "جزئي\nمسيطر\nغير مسيطر\nمش معروف"})
    opts = {o["ar"]: o["key"] for o in _form(drawn)["fields"][3]["options"]}
    assert opts == {"جزئي": "o2", "مسيطر": "o1", "غير مسيطر": "o3",
                    "مش معروف": "o4"}


def test_an_entry_keeps_the_shape_it_was_filled_on(drawn):
    from app.models import FormEntry

    _fill(drawn, f2="200", f3="yes")
    before = _form(drawn)["version"]
    drawn["sign_in"]("boss").post(f"/forms/{drawn['form']}", data={
        "action": "field", "key": "f2", "label_ar": "PEF بعد التعديل",
        "unit": "L/min"})
    assert _form(drawn)["version"] == before + 1
    with drawn["app"].app_context():
        entry = FormEntry.query.one()
        assert entry.form_version == before
        entry_id = entry.id
    page = drawn["sign_in"]("doc").get(f"/forms/entry/{entry_id}") \
        .get_data(as_text=True)
    assert "ذروة التدفق" in page and "PEF بعد التعديل" not in page
    assert "200 L/min" in page
    printed = drawn["sign_in"]("doc").get(
        f"/forms/entry/{entry_id}/print").get_data(as_text=True)
    assert f'data-form-print="{entry_id}"' in printed and "ذروة التدفق" in printed


def test_a_visit_form_needs_this_childs_visit(drawn):
    from app.extensions import db
    from app.models import CustomForm

    with drawn["app"].app_context():
        db.session.get(CustomForm, drawn["form"]).place = "visit"
        db.session.commit()
    _fill(drawn, f3="yes")
    assert _entries(drawn) == []
    resp = drawn["sign_in"]("doc").post(f"/forms/{drawn['form']}/fill", data={
        "patient_id": drawn["ids"]["child"], "visit_id": drawn["ids"]["visit"],
        "a_f3": "yes"})
    assert resp.status_code == 302 and len(_entries(drawn)) == 1
    record = drawn["sign_in"]("doc").get(
        f"/visits/{drawn['ids']['visit']}/record").get_data(as_text=True)
    assert "data-to-forms" in record


def test_the_stay_only_where_the_wards_are(drawn):
    from app.models import Setting
    from app.utils import custom_forms as cf

    with drawn["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        drawn["db"].session.commit()
        assert "admission" not in cf.places_offered()
    page = drawn["sign_in"]("boss").get("/forms/").get_data(as_text=True)
    assert 'value="admission"' not in page


def test_the_numbers_count_each_field(drawn):
    _fill(drawn, f2="200", f3="yes", f4="o1", f5=["o1"])
    _fill(drawn, f2="400", f3="no", f4="o1", f5=["o1", "o2"])
    _fill(drawn, f3="yes")
    page = drawn["sign_in"]("doc").get(f"/forms/{drawn['form']}/summary") \
        .get_data(as_text=True)
    assert "data-form-total>3<" in page
    assert 'data-sum="f3:yes">2<' in page and 'data-sum="f3:no">1<' in page
    assert 'data-sum="f4:o1">2<' in page and 'data-sum="f5:o1">2<' in page
    assert "300.0" in page                      # the mean of 200 and 400
    csv = drawn["sign_in"]("doc").get(
        f"/forms/{drawn['form']}/summary.csv").get_data(as_text=True)
    assert "ذروة التدفق" in csv and "نعم" in csv and "مسيطر" in csv


def test_the_doors(drawn):
    boss = drawn["sign_in"]("boss")
    settings = boss.get("/settings/").get_data(as_text=True)
    assert "data-to-form-builder" in settings
    profile = drawn["sign_in"]("doc").get(
        f"/patients/{drawn['ids']['child']}").get_data(as_text=True)
    assert "data-to-forms" in profile
    here = drawn["sign_in"]("doc").get(
        f"/forms/patient/{drawn['ids']['child']}").get_data(as_text=True)
    assert f'data-fill="{drawn["form"]}"' in here
    # Reception reaches the file but not a clinical form.
    desk = drawn["sign_in"]("desk").get(
        f"/forms/patient/{drawn['ids']['child']}").get_data(as_text=True)
    assert 'data-forms-here="0"' in desk
