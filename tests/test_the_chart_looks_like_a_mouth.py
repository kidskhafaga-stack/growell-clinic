"""The arch, the surfaces that exist, and interceptive orthodontics.

Three things reported together while looking at the chart.

**"ليه رسمة الاسنان مش بشكل الفك"** — a row of teeth is a list; a mouth is a
curve. A dentist finds a tooth by where it sits in the arch before they read
its number, which is the same reason the crowns are drawn as crowns.

**"وليه مش بتتسجل"** — the surface dropdown offered all six faces whatever
tooth was chosen, so picking a front tooth and then "occlusal" produced a save
the server refused (correctly: an incisor has no biting table) and a red flash
that is easy to miss. The screen now offers only the faces that tooth has.

**Interceptive orthodontics**, which is where a paediatric clinic actually
acts: the existing `occlusion` field describes the bite, and describing is not
intercepting. Interception means acting at the right age, and the window
closes as the child grows.
"""
import json
import os

import pytest

from app.models.dental import ALL_TEETH, SURFACES, WHOLE_TOOTH, surfaces_of

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def chart(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


def _page(kit):
    return kit["sign_in"]("doc").get(
        f"/dentistry/patient/{kit['ids']['child']}").get_data(as_text=True)


def _offsets(page):
    import re

    return [float(v) for v in re.findall(r"translateY\((-?[\d.]+)px\)", page)]


# ------------------------------------------------------------- the arch ----
def test_every_tooth_sits_on_a_curve(chart):
    offsets = _offsets(_page(chart))
    assert len(offsets) == len(ALL_TEETH)
    assert len(set(offsets)) > 4, "every tooth is at the same height — a row"


def test_the_curve_is_deepest_at_the_back(chart):
    """A jaw is gentle in front and turns hardest at the molars. A straight
    ramp would be a diagonal line, not an arch."""
    offsets = [abs(v) for v in _offsets(_page(chart))]
    assert max(offsets) > 10
    assert min(offsets) < 1


def test_the_two_jaws_curve_towards_each_other(chart):
    """Upper opens downward, lower upward — together they make the shape of a
    mouth rather than two unrelated lines."""
    offsets = _offsets(_page(chart))
    assert any(v > 5 for v in offsets), "no arch bends one way"
    assert any(v < -5 for v in offsets), "no arch bends the other"


def test_an_arch_never_wraps_onto_a_second_line(chart):
    """Half a jaw sitting under the other half is not an arch. It scrolls
    instead."""
    page = _page(chart)
    assert "flex-wrap:nowrap" in page
    assert "overflow-x:auto" in page


# --------------------------------------------- only the faces that exist ---
def test_the_screen_is_given_the_faces_of_each_tooth(chart):
    page = _page(chart)
    assert 'id="dentalSurfaces"' in page
    assert 'x-for="s in (SURFACES[tooth] || [])"' in page


def test_a_front_tooth_is_not_offered_a_biting_table(chart):
    """The reported bug, at its root. An incisor has no occlusal surface, and
    offering one produced a save the server refused."""
    page = _page(chart)
    start = page.index('id="dentalSurfaces"')
    blob = json.loads(page[page.index(">", start) + 1:page.index("</script>", start)])
    assert "occlusal" not in blob["byTooth"]["11"]
    assert "incisal" in blob["byTooth"]["11"]
    assert "occlusal" in blob["byTooth"]["16"]


def test_the_screen_and_the_server_read_the_same_list(chart):
    """Two lists would drift, and the drift is invisible until somebody picks
    the face that only one of them believes in."""
    page = _page(chart)
    start = page.index('id="dentalSurfaces"')
    blob = json.loads(page[page.index(">", start) + 1:page.index("</script>", start)])
    for tooth in ALL_TEETH:
        expected = [s for s in surfaces_of(tooth) if s != WHOLE_TOOTH]
        assert blob["byTooth"][str(tooth)] == expected, tooth


def test_every_face_has_a_name_on_the_screen(chart):
    page = _page(chart)
    start = page.index('id="dentalSurfaces"')
    blob = json.loads(page[page.index(">", start) + 1:page.index("</script>", start)])
    for surface in SURFACES:
        assert blob["names"].get(surface), surface
        assert not blob["names"][surface].startswith("dental."), surface


def test_the_server_still_refuses_a_face_the_tooth_does_not_have(chart):
    """The screen stopping the offer does not make the check optional — a
    request does not have to come from this screen."""
    from app.models.dental import ToothFinding

    chart["sign_in"]("doc").post(
        f"/dentistry/patient/{chart['ids']['child']}/record",
        data={"tooth": 11, "condition": "caries", "surface": "occlusal"},
        follow_redirects=True)
    with chart["app"].app_context():
        assert ToothFinding.query.count() == 0


def test_a_face_the_tooth_does_have_is_still_recorded(chart):
    from app.models.dental import ToothFinding

    chart["sign_in"]("doc").post(
        f"/dentistry/patient/{chart['ids']['child']}/record",
        data={"tooth": 11, "condition": "caries", "surface": "mesial"},
        follow_redirects=True)
    with chart["app"].app_context():
        assert ToothFinding.query.count() == 1


# ------------------------------------------- interceptive orthodontics -----
def _dental_fields():
    with open(os.path.join(HERE, "..", "app", "data",
                           "specialty_panels.json"), encoding="utf-8") as fh:
        return {f["code"]: f
                for f in json.load(fh)["panels"]["dentistry"]["fields"]}


@pytest.mark.parametrize("code", [
    "crossbite_site", "overjet_mm", "molar_relation",
    "ortho_decision", "ortho_review"])
def test_the_panel_asks_the_interceptive_questions(code):
    assert code in _dental_fields()


def test_the_crossbite_says_where_it_is(): 
    """"Crossbite" alone does not say, and where it is decides what is done:
    a posterior one in a child is the classic interceptive case."""
    options = _dental_fields()["crossbite_site"]["options"]
    assert any("أمامي" in o for o in options)
    assert sum(1 for o in options if "خلفي" in o) >= 3


def test_the_overjet_is_a_number_and_not_a_description():
    """The decision turns on a number: a large overjet leaves the front teeth
    exposed to fracture, which is a referral on its own."""
    field = _dental_fields()["overjet_mm"]
    assert field["type"] == "number"
    assert field.get("unit") == "mm"


def test_there_is_a_decision_and_a_date_for_it():
    """What makes this interceptive rather than descriptive. Interception
    means acting at the right age; a finding with no decision is an
    observation, and the window closes while the child grows."""
    fields = _dental_fields()
    assert fields["ortho_decision"]["type"] == "choice"
    assert any("تحويل" in o for o in fields["ortho_decision"]["options"])
    assert fields["ortho_review"]["type"] == "date"


def test_it_did_not_replace_what_was_already_asked():
    """The habits are often the cause — a thumb, a bottle, mouth breathing —
    and these sit beside them rather than instead of them."""
    fields = _dental_fields()
    for kept in ("occlusion", "sucking_habit", "mouth_breathing",
                 "cooperation", "fluoride"):
        assert kept in fields


def test_it_cost_no_python():
    """The file's own promise: adding to a panel is data. If this ever needs
    code, the next specialty costs a release.

    **Rewritten twice, and both wrong turns are worth recording.**

    The first version ran `git diff HEAD -- app/utils/panels.py`, which compares
    the *working tree* to the last commit — so it failed for anybody with
    unfinished work in that file, which is exactly how it failed: a full suite
    run caught the tree mid-edit and reported a defect in a commit that was
    clean. A test that goes red because somebody is typing is a test that gets
    ignored.

    The second attempt asserted that no module names `"dentistry"` as a string.
    That is false by design and the suite said so immediately: dentistry is a
    *module* as well as a panel, so it is named in the permissions list, the
    nav endpoints, the price rules and the handbook, all legitimately.

    What is actually promised is narrower and checkable: the panel's **fields**
    are data. `overjet_mm`, `cooperation`, `crossbite_site` and the rest come
    out of a JSON file, and no Python decides anything by their names. Adding
    a field is then an edit to that file — which is the claim — while the
    module around dentistry stays free to exist in code.
    """
    import ast

    codes = set(_dental_fields())
    assert len(codes) > 10, "the catalogue is empty, so this proves nothing"

    root = os.path.join(HERE, "..", "app")
    named = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in codes:
                    named.append(f"{os.path.relpath(path, root)}:{node.lineno} "
                                 f"\"{node.value}\"")

    assert not named, (
        "a dental panel field is named in code, so adding one needs a "
        "release: " + ", ".join(named))


def test_the_new_fields_reach_the_visit_screen(chart):
    """Data is only data if the renderer already understands it.

    Two switches are needed to see them, and they are separate on purpose:
    dentistry is the chart and the plans, panels is whether the consultation
    screen carries specialty fields at all. This test wants the fields, so it
    turns on both and puts the dentist on the panel.
    """
    from app.extensions import db
    from app.models import Setting, User, Visit

    with chart["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, chart["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "dentistry"
        db.session.commit()

    page = chart["sign_in"]("doc").get(
        f"/visits/{chart['ids']['visit']}/record").get_data(as_text=True)
    for code in ("crossbite_site", "overjet_mm", "ortho_decision",
                 "ortho_review"):
        assert f'name="m_{code}"' in page, code


# ----------------------------------------------------------- the guide -----
def _section(key):
    from app.utils.handbook import SECTIONS

    return next(s for s in SECTIONS if s["key"] == key)


def _text(key, lang=0):
    return " ".join(line[lang] for line in _section(key)["lines"])


def test_the_guide_says_how_to_reach_the_chart():
    """The module shipped with every screen working and nothing linking to
    them. A guide that describes what a chart does and not how to open it
    teaches the wrong half."""
    ar = _text("dentistry")
    assert "تاب" in ar and "أسنان" in ar
    en = _text("dentistry", 1)
    assert "Teeth" in en and "tab" in en


def test_the_guide_walks_the_plan_from_start_to_finish():
    """The pieces were each described and the order was not. "How do I make a
    plan" is a question about the sequence."""
    ar = _text("dentistry")
    for step in ("الخريطة", "ضيف للخطة", "قبول", "العربون"):
        assert step in ar, step


def test_the_guide_covers_interceptive_orthodontics():
    ar = _text("dentistry")
    assert "التقويم الاعتراضي" in ar
    assert "المراجعة" in ar, "a decision with no review date is not a decision"


def test_the_guide_covers_the_diagnosis_suggestion():
    """A suggestion the doctor cannot find is a switch the clinic pays for and
    nobody uses."""
    ar = _text("visits")
    assert "اقترح تشخيصات" in ar or "اقتراح التشخيص" in ar
    assert "الكود" in ar, "it must say where the code comes from"


def test_every_line_of_the_guide_is_in_both_languages():
    """A handbook half-translated is a handbook that teaches one of the two
    people who open it."""
    from app.utils.handbook import SECTIONS

    for section in SECTIONS:
        for line in section["lines"]:
            assert len(line) == 2, section["key"]
            assert line[0].strip() and line[1].strip(), section["key"]


def test_the_dentistry_guide_reaches_the_screen(chart):
    page = chart["sign_in"]("doc").get("/guide?all=1").get_data(as_text=True)
    assert "التقويم الاعتراضي" in page or "Interceptive" in page
