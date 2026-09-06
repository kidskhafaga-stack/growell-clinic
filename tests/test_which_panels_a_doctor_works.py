"""Ticking, in the doctor's own settings, which specialty panels they work.

Asked for directly: *"فى اعدادت الدكتور نقدر نعلم ايه القوالب الى تظهر للطبيب
ده"* — and, in the same breath, *"ممكن يشتغل اكثر من تخصص خلى بالك"*. So it is
a list of ticks and not a menu: a doctor working general paediatrics with a
gastroenterology interest follows the same children, and a control that made
them pick one would make them pick again on the next visit.

**One of them opens first.** *"يا هيه الديفولت يا نخلى الديفولت بتاع الطبيب ده
حجات الجهاز الهضمى بس"* — a neurologist who works only neurology opens that
screen forty times a day, and passing through anything else is forty clicks a
day. So the ticks say what exists and one radio says what opens.

**Unticking is not deleting.** The single most important property here. A
setting about what to ask next is not a licence to edit finished visits: a
panel taken off a doctor's list leaves every reading recorded under it exactly
where it was, and the visits that hold them keep showing them.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """The module on, and an admin looking at the doctor's setup screen."""
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        clinic["ids"]["doctor"] = visit.doctor_id
        db.session.get(User, visit.doctor_id).specialty_panels = None
        db.session.commit()
    clinic["url"] = f"/users/doctors/{clinic['ids']['doctor']}"
    return clinic


def _doctor(desk):
    from app.extensions import db
    from app.models import User

    return db.session.get(User, desk["ids"]["doctor"])


def _set(desk, **form):
    return desk["sign_in"]("boss").post(
        f"{desk['url']}/panels", data=form, follow_redirects=True)


# --------------------------------------------------------------- the screen

def test_the_setup_screen_offers_every_panel(desk):
    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    assert 'name="panel_cardiology"' in page
    assert 'name="panel_dentistry"' in page
    assert 'name="panel_default"' in page, "nothing says which one opens first"


def test_it_is_not_there_when_the_clinic_does_not_work_specialties(desk):
    """A setting for a module nobody uses is a question with no consequences,
    and a screen full of those is how a clinic learns to skip the screen."""
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    assert 'name="panel_cardiology"' not in page
    assert 'name="panel_default"' not in page


def test_the_rest_of_the_doctors_setup_is_untouched_by_it(desk):
    """The card is an addition. The name, the licence and the paper it prints
    on are what this screen was for and still are."""
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    assert 'name="specialty"' in page and 'name="license_no"' in page


# ---------------------------------------------------------------- the saving

def test_two_panels_are_stored_as_two(desk):
    _set(desk, panel_cardiology="1", panel_dentistry="1")

    with desk["app"].app_context():
        from app.utils import panels

        assert panels.for_doctor(_doctor(desk)) == ["cardiology", "dentistry"]


def test_ticking_nothing_is_a_real_answer(desk):
    """The common case, and it has to survive a save rather than being read as
    "they forgot"."""
    _set(desk, panel_cardiology="1")
    _set(desk)                                     # everything unticked

    with desk["app"].app_context():
        from app.utils import panels

        assert panels.for_doctor(_doctor(desk)) == []
        assert _doctor(desk).specialty_panel is None


def test_the_radio_decides_which_one_opens(desk):
    _set(desk, panel_cardiology="1", panel_dentistry="1",
         panel_default="dentistry")

    with desk["app"].app_context():
        from app.utils import panels

        assert panels.default_for_doctor(_doctor(desk)) == "dentistry"


def test_a_default_they_do_not_work_is_not_stored(desk):
    """A stale form — the panel was unticked in one browser tab and chosen as
    the default in another. Storing it would leave a doctor opening every day
    on a panel that is not on their screen."""
    _set(desk, panel_cardiology="1", panel_default="dentistry")

    with desk["app"].app_context():
        from app.utils import panels

        # Not stored, and not swapped for a different one either: the form
        # said something impossible, so the answer is "nothing chosen" rather
        # than a panel nobody asked for.
        assert _doctor(desk).specialty_panel is None
        assert panels.default_for_doctor(_doctor(desk)) == ""


def test_a_panel_no_catalogue_describes_is_ignored(desk):
    _set(desk, panel_cardiology="1", panel_astrology="1")

    with desk["app"].app_context():
        assert _doctor(desk).specialty_panels == "cardiology"


def test_only_an_admin_may_set_them(desk):
    """Which panels a clinic's doctors work is a setup question."""
    assert desk["sign_in"]("doc").post(
        f"{desk['url']}/panels", data={"panel_cardiology": "1"}
    ).status_code in (302, 403)

    with desk["app"].app_context():
        assert _doctor(desk).specialty_panels in (None, "")


# ------------------------------------------------------- unticking is not rm

def test_unticking_a_panel_keeps_every_reading_taken_under_it(desk):
    from app.extensions import db
    from app.models import Measurement

    _set(desk, panel_cardiology="1")
    with desk["app"].app_context():
        db.session.add(Measurement(patient_id=desk["ids"]["child"],
                                   visit_id=desk["ids"]["visit"],
                                   code="ef_pct", panel="cardiology",
                                   value_num=47.0, unit="%"))
        db.session.commit()

    _set(desk, panel_dentistry="1")                # cardiology taken away

    with desk["app"].app_context():
        row = Measurement.query.filter_by(visit_id=desk["ids"]["visit"],
                                          code="ef_pct").first()
        assert row is not None, "a reading was deleted by a settings change"
        assert row.value_num == 47.0


def test_and_the_visit_that_holds_them_still_shows_them(desk):
    """Kept from the visit screen's side as well. A reading in the file that
    no screen will show is a reading that is gone in every way that matters.
    """
    from app.extensions import db
    from app.models import Measurement, Visit

    _set(desk, panel_cardiology="1")
    with desk["app"].app_context():
        db.session.add(Measurement(patient_id=desk["ids"]["child"],
                                   visit_id=desk["ids"]["visit"],
                                   code="ef_pct", panel="cardiology",
                                   value_num=47.0, unit="%"))
        db.session.get(Visit, desk["ids"]["visit"]).specialty_panel = "cardiology"
        db.session.commit()

    _set(desk, panel_dentistry="1")

    page = desk["sign_in"]("boss").get(
        f"/visits/{desk['ids']['visit']}/record").get_data(as_text=True)

    assert 'value="47.0"' in page or 'value="47"' in page, \
        "the visit stopped showing a reading it still holds"


# ------------------------------------------------- the admin screen leads there

def test_the_panels_screen_leads_to_where_it_is_changed(desk):
    """A screen that reports a state and makes you go and find where to edit
    it is half a screen. The answer to "who is on this panel" is nearly always
    followed by changing it."""
    _set(desk, panel_cardiology="1")

    page = desk["sign_in"]("boss").get("/panels/").get_data(as_text=True)

    assert f"/users/doctors/{desk['ids']['doctor']}" in page, \
        "the doctor's name on the panels screen goes nowhere"


# --------------------------------------------- "opens on" is clearable now ---

def test_opens_on_is_a_checkbox_and_not_a_radio(desk):
    """Reported as *"عايزها اتشيك مش يا ده يا ده"*. The rule is still one-of —
    a script unticks the others — but a radio cannot be **unset**, so a clinic
    that ticked one by mistake had no way back to "no preference" short of
    reloading the page."""
    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    assert 'type="checkbox" class="opens-on" name="panel_default"' in page
    assert 'type="radio" name="panel_default"' not in page


def test_clearing_it_means_no_preference_and_stays_cleared(desk):
    """"No preference" is a real answer, and it means **none** — not the first
    panel they happen to work.

    This test used to assert the opposite, and the opposite was the bug.
    Reported in these words: *"كل ما اشيل العلامة بعد الحفظ يرجعها تاني"*. A
    doctor who works newborn care unticked "opens automatically", saved, and
    the tick came straight back, because clearing it fell through to the first
    ticked panel — so the box could be ticked and never unticked.

    Working a panel and opening every visit on it are two different
    statements. The first says what this doctor does; the second says what
    their screen should assume about the child in front of them, and for a
    general paediatrician with a neonatology interest the honest answer is
    nothing at all.
    """
    _set(desk, panel_cardiology="1", panel_dentistry="1")

    with desk["app"].app_context():
        from app.utils import panels

        assert _doctor(desk).specialty_panel is None
        assert panels.default_for_doctor(_doctor(desk)) == ""


def test_choosing_one_still_sticks(desk):
    """The other half, and the guard against fixing this by never storing it:
    a doctor who does want to open on a panel says so once and it holds."""
    _set(desk, panel_cardiology="1", panel_dentistry="1",
         panel_default="dentistry")

    with desk["app"].app_context():
        from app.utils import panels

        assert _doctor(desk).specialty_panel == "dentistry"
        assert panels.default_for_doctor(_doctor(desk)) == "dentistry"


def test_and_it_can_be_cleared_again_afterwards(desk):
    """Ticked on Monday, cleared on Tuesday, and Tuesday wins. This is the
    exact sequence that used to be impossible."""
    _set(desk, panel_cardiology="1", panel_default="cardiology")
    _set(desk, panel_cardiology="1")

    with desk["app"].app_context():
        assert _doctor(desk).specialty_panels == "cardiology"
        assert _doctor(desk).specialty_panel is None


def test_two_sent_at_once_is_handled_rather_than_refused(desk):
    """A browser running no script can post both boxes. The route takes the
    last and checks it, so the worst case is a doctor opening on a panel they
    do work — not a crash and not a stored panel they do not."""
    from werkzeug.datastructures import MultiDict

    reply = desk["sign_in"]("boss").post(
        f"{desk['url']}/panels",
        data=MultiDict([("panel_cardiology", "1"), ("panel_dentistry", "1"),
                        ("panel_default", "cardiology"),
                        ("panel_default", "dentistry")]),
        follow_redirects=True)
    assert reply.status_code == 200

    with desk["app"].app_context():
        from app.utils import panels

        assert panels.default_for_doctor(_doctor(desk)) == "dentistry"
