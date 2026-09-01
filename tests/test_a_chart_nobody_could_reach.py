"""The dentistry work was all built, and no screen pointed at any of it.

Reported after looking for it: *"الاسنان لسه مش شايف شكل الشغل والخريطة بتاعت
الاسنان الدائمة والاسنان البنية ومش عارف الفلو بيتعمل ازاي وبيظهر فين فى
الزيارة"*.

Every screen existed. The chart with both dentitions, the per-tooth history,
the plans list, the plan with its items and its deposit — all of it worked,
and **nothing in the program linked to a single one of them**. The patient
file had no teeth tab. The consultation screen, where a dentist actually
stands, had no way through. The module's own landing page lists the children
who already have a plan, so a dentist seeing a new child had no route in at
all.

This is the fourth time this pattern has been found in this program, which is
why the last two tests below are about the pattern and not about teeth.
"""
import pytest


@pytest.fixture
def dental(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


def _file(kit):
    return kit["sign_in"]("doc").get(
        f"/patients/{kit['ids']['child']}").get_data(as_text=True)


def _room(kit):
    return kit["sign_in"]("doc").get(
        f"/visits/{kit['ids']['visit']}/record").get_data(as_text=True)


# ------------------------------------------------- a door on the file -------
def test_the_patient_file_has_a_teeth_tab(dental):
    """The **button**, not the panel.

    This first asserted `tab==='dental'` anywhere on the page — which the
    panel carries too, in its own `x-show`. Deleting the tab button left the
    panel behind and the test passed, so it proved nothing about the thing
    that was actually missing. Mutation testing caught it.
    """
    page = _file(dental)
    assert "tab='dental'" in page, "there is no button that switches to it"
    assert "patients.tab_dental" not in page, "untranslated key on the screen"
    assert "الأسنان" in page


def test_the_tab_leads_to_the_chart(dental):
    page = _file(dental)
    assert f"/dentistry/patient/{dental['ids']['child']}" in page


def test_the_chart_it_points_at_actually_opens(dental):
    """A link is only a door if something answers behind it."""
    answer = dental["sign_in"]("doc").get(
        f"/dentistry/patient/{dental['ids']['child']}")
    assert answer.status_code == 200


def test_the_chart_shows_both_dentitions(dental):
    """*"الاسنان الدائمة والاسنان البنية"*. Between six and twelve a child has
    both, and a chart showing one of them is showing half a mouth."""
    page = dental["sign_in"]("doc").get(
        f"/dentistry/patient/{dental['ids']['child']}").get_data(as_text=True)
    assert "dental.permanent" not in page and "dental.primary" not in page
    # An upper-right permanent central incisor and its primary predecessor.
    assert "11" in page and "51" in page


# ------------------------------------------- and a door in the room ---------
def test_the_consultation_screen_reaches_the_chart(dental):
    """Where a dentist is actually standing. The panel records the history and
    the risk; the teeth themselves are next door."""
    page = _room(dental)
    assert f"/dentistry/patient/{dental['ids']['child']}" in page


def test_neither_door_exists_when_the_clinic_does_not_do_dentistry(clinic):
    """The module is off by default because a paediatric clinic is not a
    dental one — and an empty tab labelled "teeth" on every file is
    furniture."""
    for page in (_file(clinic), _room(clinic)):
        assert "/dentistry/patient/" not in page
    assert "tab==='dental'" not in _file(clinic)


# ------------------------------------------------------ the summary ---------
def test_the_tab_says_what_is_on_file(dental):
    from app.models.dental import ToothFinding

    with dental["app"].app_context():
        ToothFinding.record(patient_id=dental["ids"]["child"], tooth=54,
                            condition="caries", surface="occlusal")
        dental["db"].session.commit()

    page = _file(dental)
    body = page[page.index("tab==='dental'"):]
    assert "dental.teeth_recorded" not in body


def test_a_child_with_nothing_recorded_is_told_where_to_start(dental):
    """An empty panel that says nothing looks like a broken tab."""
    page = _file(dental)
    assert "dental.no_plans" not in page      # translated
    assert "مفيش خطة علاج" in page or "No treatment plan" in page


# --------------------------------------------- the pattern, not the teeth ---
def test_every_screen_a_module_owns_can_be_reached_from_somewhere():
    """The fourth instance of this in one program, so it gets a guard.

    For each blueprint that has a per-patient screen, some other template must
    link to it. A module whose screens are only reachable by typing the address
    is a module nobody uses — and the symptom is always the same sentence:
    "it's built, but where is it?"
    """
    import os
    import re

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    templates = os.path.join(root, "app", "templates")

    linked = set()
    for folder, _dirs, files in os.walk(templates):
        for name in files:
            if not name.endswith(".html"):
                continue
            body = open(os.path.join(folder, name), encoding="utf-8").read()
            here = os.path.basename(folder)
            for endpoint in re.findall(r"url_for\(\s*['\"]([a-z_]+\.[a-z_]+)",
                                       body):
                # A screen linking to itself is not a way in.
                if not endpoint.startswith(here + "."):
                    linked.add(endpoint)

    # The per-patient screens, which is the kind that was unreachable.
    #
    # Landing pages are deliberately not checked here: the sidebar reaches
    # them through `MODULE_ENDPOINTS`, so the endpoint name never appears as a
    # literal in any template and this search cannot see it. They have their
    # own guard — `test_a_link_that_goes_nowhere` — which resolves the map,
    # opens every page and fails on a dead link. Asserting them here would be
    # asserting something this check cannot prove.
    for endpoint in ("dentistry.chart",):
        assert endpoint in linked, (
            f"{endpoint} is not linked from any screen outside its own "
            "module — it can only be reached by typing the address")
