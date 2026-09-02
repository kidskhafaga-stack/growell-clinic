"""A module a clinic has not ticked shows nothing, anywhere.

Asked for as the single most important thing about the whole specialty layer:
*"بس فى حاجه لو عيادة مش معلمه المديول ما تظهرش دى اهم حاجه"*.

**Why a module and not a setting.** A setting hides a control; a module removes
the ground it stood on. A general paediatric practice should not have a
specialty section on its consultation screen at all — not an empty picker, not
a greyed-out control, not a heading with nothing under it. Every one of those
is a question the clinic has already answered by not ticking the box, asked
again forty times a day.

**Two switches, not one, and they answer different questions.** The module says
whether this clinic works specialties. The doctor's own list says which panels
stand on that ground. A clinic can tick the module and have a doctor who works
none — a general paediatrician in a mixed practice — and that doctor's screen
is the ordinary visit, unchanged. Asked for in those words: *"فى اعدادت الدكتور
نقدر نعلم ايه القوالب الى تظهر للطبيب ده"*.

**Off means not asked, never erased.** The hardest part, and the one worth the
most tests here. A clinic that switches the module off is not shown the fields,
so it answers none of them — and an empty form must not be read as "the doctor
cleared every box". Readings taken while the module was on stay in the file and
come back when it is switched on again.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A doctor who works cardiology and dentistry, in a clinic where the
    module is *off* — each test switches on what it needs."""
    from app.extensions import db
    from app.models import User, Visit

    with clinic["app"].app_context():
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        doctor = db.session.get(User, visit.doctor_id)
        doctor.specialty_panels = "cardiology,dentistry"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _module(desk, on, key="panels"):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set(f"mod_enabled:{key}", "1" if on else "0")
        desk["db"].session.commit()


def _page(desk):
    return desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)


def _save(desk, **form):
    data = {"chief_complaint": "متابعة"}
    data.update(form)
    return desk["sign_in"]("boss").post(desk["url"], data=data,
                                        follow_redirects=True)


def _readings(desk):
    from app.models import Measurement

    with desk["app"].app_context():
        return {m.code: m for m in
                Measurement.query.filter_by(visit_id=desk["ids"]["visit"]).all()}


# ------------------------------------------------------------- off by default

def test_a_new_clinic_has_it_off(desk):
    """Nobody is opted in by a version arriving. A clinic upgrading into the
    release that added panels must not find a specialty section on its visit
    screen the next morning."""
    from app.utils.facility import OPT_IN_MODULES, module_enabled

    assert "panels" in OPT_IN_MODULES
    with desk["app"].app_context():
        assert module_enabled("panels") is False


def test_off_means_the_section_is_not_there(desk):
    """Not empty, not disabled — absent."""
    _module(desk, False)

    page = _page(desk)

    assert 'name="m_ef_pct"' not in page, "a panel's fields are still rendered"
    assert 'name="specialty_panel"' not in page, "the picker is still there"
    assert "panelBox(" not in page, "the section is still on the page"


def test_on_but_this_doctor_works_none_is_also_absent(desk):
    """The second switch. A general paediatrician in a clinic that does work
    specialties sees the ordinary visit and nothing else."""
    from app.extensions import db
    from app.models import User, Visit

    _module(desk, True)
    with desk["app"].app_context():
        visit = db.session.get(Visit, desk["ids"]["visit"])
        doctor = db.session.get(User, visit.doctor_id)
        doctor.specialty_panels = None
        doctor.specialty_panel = None
        db.session.commit()

    page = _page(desk)

    assert "panelBox(" not in page
    assert 'name="m_ef_pct"' not in page


def test_only_this_doctors_panels_are_offered(desk):
    """A cardiologist who does not do teeth is not shown a dentistry chip."""
    from app.extensions import db
    from app.models import User, Visit

    _module(desk, True)
    with desk["app"].app_context():
        visit = db.session.get(Visit, desk["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "cardiology"
        db.session.commit()

    page = _page(desk)

    assert 'data-panel-key="cardiology"' in page
    assert 'data-panel-key="dentistry"' not in page, \
        "a panel this doctor does not work is on their screen"
    assert 'name="m_overjet_mm"' not in page, \
        "its fields are in the form even though the chip is not"


def test_the_visit_screen_still_works_with_the_module_off(desk):
    """The point of the whole design: a panel is a layer, not the screen. With
    it off the consultation is unchanged — complaint, examination, vitals."""
    _module(desk, False)

    page = _page(desk)

    assert 'name="chief_complaint"' in page
    assert 'name="clinical_exam"' in page
    assert 'name="weight_kg"' in page and 'name="bp_systolic"' in page


# ---------------------------------------------------- off is not a delete key

def test_switching_it_off_does_not_erase_what_was_recorded(desk):
    """The bug this test exists to stop. With the module off the fields are
    not on the screen, so the form carries none of them — and a save that read
    that as "every box was cleared" would delete a specialist's readings
    because an admin unticked a checkbox."""
    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_ef_pct="58")
    assert _readings(desk)["ef_pct"].value_num == 58.0

    _module(desk, False)
    _save(desk, chief_complaint="متابعة تانية")

    rows = _readings(desk)
    assert "ef_pct" in rows, "switching the module off deleted a reading"
    assert rows["ef_pct"].value_num == 58.0


def test_the_visit_keeps_saying_which_panel_it_used(desk):
    """Same rule for the stamp on the visit. A visit recorded under cardiology
    still says so after the clinic stops working specialties — otherwise the
    file loses the one word that explains where its readings came from."""
    from app.extensions import db
    from app.models import Visit

    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_ef_pct="58")

    _module(desk, False)
    _save(desk, chief_complaint="متابعة تانية")

    with desk["app"].app_context():
        assert db.session.get(Visit, desk["ids"]["visit"]).specialty_panel \
            == "cardiology"


def test_and_it_all_comes_back_when_it_is_switched_on_again(desk):
    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_ef_pct="58")
    _module(desk, False)
    _save(desk, chief_complaint="متابعة تانية")
    _module(desk, True)

    page = _page(desk)

    assert 'value="58.0"' in page or 'value="58"' in page


def test_a_crafted_post_cannot_write_a_panel_into_a_clinic_that_is_off(desk):
    """The form is gone from the screen; the address is not. A request that
    posts panel fields anyway writes nothing."""
    _module(desk, False)

    _save(desk, specialty_panel="cardiology", m_ef_pct="58")

    assert _readings(desk) == {}, \
        "a clinic with the module off has a panel reading in its file"


# --------------------------------------------------------- the admin's screen

def test_the_panels_screen_is_not_reachable_when_the_module_is_off(desk):
    _module(desk, False)
    assert desk["sign_in"]("boss").get("/panels/").status_code == 404


def test_and_is_reachable_by_an_admin_when_it_is_on(desk):
    _module(desk, True)
    assert desk["sign_in"]("boss").get("/panels/").status_code == 200


def test_a_doctor_does_not_get_the_panels_screen(desk):
    """It is a setup question — which panels this clinic has and who works
    them — not a consulting-room one."""
    _module(desk, True)
    assert desk["sign_in"]("doc").get("/panels/").status_code in (302, 403)
