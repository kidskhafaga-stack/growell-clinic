"""The case history a specialist writes once, not every visit.

Asked for after the panels were built: *"الأطباء ساعات بتبقى عايزة تكتب التاريخ
المرضى للحالة بالذات فى التخصصات"*. The panels record measurements — a number
per box, per visit — and there was nowhere to write the story the numbers belong
to. A specialist would have been typing it into the visit notes every time, or
not writing it at all.

**Per patient, not per visit, and that is the whole design.** A case history is
written once and edited when it changes. Retyping it at every visit is exactly
the *"الطبيب ما يكتبش كتير"* this program keeps being told to avoid, and it is
also how a history becomes three slightly different histories. It appears on
the next visit already written.

**Per specialty, because it is not one history.** The endocrinologist's account
of this child — when the diabetes started, which regimen, which admissions — is
not the dentist's account of the same child. One shared box would be either a
fight over whose text it is, or a page nobody reads.

**And it costs few keystrokes**, because the same quick-phrase codes the
examination box uses work here: a code plus a space becomes a sentence.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

BOX = 'data-panel-history="'


@pytest.fixture()
def desk(clinic):
    """A visit whose id is deliberately **not** the patient's id.

    In the base fixture the first child and the first visit are both row 1, so
    a bug that stored the history against `visit.id` instead of
    `visit.patient_id` was invisible: the two numbers were the same. A mutation
    that made exactly that substitution passed every test in this file. Two
    spare visits push the ids apart so the confusion has somewhere to show.
    """
    from app.extensions import db
    from app.models import Setting, User, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        first = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, first.doctor_id).specialty_panels = \
            "endocrinology,dentistry"
        for _ in range(2):
            db.session.add(Visit(patient_id=clinic["ids"]["child"],
                                 doctor_id=first.doctor_id,
                                 visit_date=local_today()))
        db.session.flush()
        later = (Visit.query.filter_by(patient_id=clinic["ids"]["child"])
                 .order_by(Visit.id.desc()).first())
        clinic["ids"]["visit"] = later.id
        assert later.id != clinic["ids"]["child"], \
            "the ids still collide, so this fixture proves nothing"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _page(kit):
    return kit["sign_in"]("boss").get(kit["url"]).get_data(as_text=True)


def _save(kit, **form):
    data = {"chief_complaint": "متابعة", "specialty_panel": "endocrinology"}
    data.update(form)
    return kit["sign_in"]("boss").post(kit["url"], data=data,
                                       follow_redirects=True)


# --------------------------------------------------------------- it exists ---

def test_each_panel_has_a_place_to_write_the_history(desk):
    page = _page(desk)

    assert f'{BOX}endocrinology"' in page
    assert f'{BOX}dentistry"' in page


def test_writing_it_keeps_it(desk):
    from app.models import PanelHistory

    _save(desk, panel_history_endocrinology="بدأ السكر في سن ٤، على مضخة منذ سنة")

    with desk["app"].app_context():
        rows = PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"]).all()
        assert len(rows) == 1
        assert rows[0].panel == "endocrinology"
        assert "مضخة" in rows[0].text
        assert rows[0].updated_by == desk["ids"]["admin"]


def test_and_it_is_already_written_on_the_next_visit(desk):
    """The point of storing it against the patient. A history retyped every
    visit is a history that becomes three slightly different histories."""
    from app.extensions import db
    from app.models import Visit
    from app.utils.clock import local_today

    _save(desk, panel_history_endocrinology="بدأ السكر في سن ٤")

    with desk["app"].app_context():
        later = Visit(patient_id=desk["ids"]["child"],
                      doctor_id=desk["ids"]["doctor"],
                      visit_date=local_today())
        db.session.add(later)
        db.session.commit()
        later_id = later.id

    page = desk["sign_in"]("boss").get(
        f"/visits/{later_id}/record").get_data(as_text=True)
    assert "بدأ السكر في سن ٤" in page, \
        "the history is not on the next visit, so it has to be retyped"


def test_two_specialties_keep_two_histories(desk):
    """The endocrinologist's account of this child is not the dentist's."""
    from app.models import PanelHistory

    _save(desk, panel_history_endocrinology="سكر نوع أول",
          panel_history_dentistry="تسوّس متكرر ورضاعة ليلية")

    with desk["app"].app_context():
        rows = {r.panel: r.text for r in PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"]).all()}
    assert rows["endocrinology"] == "سكر نوع أول"
    assert rows["dentistry"] == "تسوّس متكرر ورضاعة ليلية"


def test_editing_it_replaces_rather_than_piles_up(desk):
    from app.models import PanelHistory

    _save(desk, panel_history_endocrinology="أول نسخة")
    _save(desk, panel_history_endocrinology="النسخة المصححة")

    with desk["app"].app_context():
        rows = PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"], panel="endocrinology").all()
        assert len(rows) == 1
        assert rows[0].text == "النسخة المصححة"


def test_clearing_it_removes_the_row(desk):
    """"Has this specialty written anything" stays a question the data answers
    by itself, instead of one that has to look inside an empty string."""
    from app.models import PanelHistory

    _save(desk, panel_history_endocrinology="نص")
    _save(desk, panel_history_endocrinology="   ")

    with desk["app"].app_context():
        assert PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"]).count() == 0


# ------------------------------------------------------ and it is guarded ---

def test_a_panel_this_doctor_does_not_work_cannot_be_written(desk):
    """The same rule the readings follow: the writable list is worked out on
    the server and the form is answers, not permissions."""
    from app.models import PanelHistory

    _save(desk, panel_history_cardiology="نص من فورم مصنوع")

    with desk["app"].app_context():
        assert PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"], panel="cardiology").count() == 0


def test_a_panel_no_catalogue_describes_is_ignored(desk):
    from app.models import PanelHistory

    _save(desk, panel_history_astrology="نص")

    with desk["app"].app_context():
        assert PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"], panel="astrology").count() == 0


def test_a_clinic_without_the_module_has_no_box(desk):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    assert BOX not in _page(desk)


def test_switching_the_module_off_does_not_erase_what_was_written(desk):
    """Off means not asked, never erased — the rule the readings already
    follow, and a history is worth more than a reading."""
    from app.models import PanelHistory, Setting

    _save(desk, panel_history_endocrinology="قصة طويلة")

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()
    _save(desk, chief_complaint="متابعة تانية")

    with desk["app"].app_context():
        rows = PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"]).all()
        assert len(rows) == 1 and rows[0].text == "قصة طويلة"


def test_unticking_the_panel_does_not_erase_it_either(desk):
    from app.extensions import db
    from app.models import PanelHistory, User, Visit

    _save(desk, panel_history_endocrinology="قصة طويلة")

    with desk["app"].app_context():
        visit = db.session.get(Visit, desk["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "dentistry"
        db.session.commit()
    _save(desk, chief_complaint="متابعة تانية")

    with desk["app"].app_context():
        assert PanelHistory.query.filter_by(
            patient_id=desk["ids"]["child"], panel="endocrinology").count() == 1


def test_the_doctors_own_shorthand_works_in_it(desk):
    """*"الطبيب ما يكتبش كتير"*. The codes that turn three keystrokes into a
    paragraph on the examination box work here too — a long history should not
    cost a long typing session."""
    page = _page(desk)
    box = page[page.index(BOX) - 400:page.index(BOX) + 400]
    assert "expand(" in box, "the quick-phrase codes do not work in the history"
