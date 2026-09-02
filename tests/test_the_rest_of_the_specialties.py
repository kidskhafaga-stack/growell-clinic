"""Nine more specialties, and not one line of Python to add them.

The catalogue's own promise from the day it was written: *"إضافة تخصص =
إضافة هنا، من غير أي تعديل برمجي"*. This is the first time that promise has
been tested at scale — cardiology and dentistry were built alongside the
mechanism, so of course they fitted it. Nine panels added afterwards, by
editing one JSON file, is the claim.

**Where the content comes from, and where it stops.** Each panel's fields are
the options a doctor actually ticked under `measured_every_visit` in the
specialties survey — `questions.ts` for the questions, the answers workbook for
the ticks. Not a guess, and not everything the survey asks: the survey also
asks for control numbers, curves and alerts, and those need things the program
cannot store yet (a numeric lab result, a coded problem list). A panel that
promised them would be a screen collecting answers nobody can act on.

**No panel stores a threshold.** The survey's own answer for paediatric blood
pressure is *"لا تستخدم رقمًا ثابتًا لكل الأعمار"*, and for dental caries it
refuses a fixed count in favour of risk assessment. So the panels carry
readings and the program keeps the judgement — the same division the vital
bands and the clinical rules already follow.

**And no panel asks for something the program can work out.** BMI, growth
velocity, a blood-pressure percentile, a preterm's corrected age: every one of
those is a function of numbers already in the file, and a box a doctor types it
into is a second answer able to disagree with the first. They are absent on
purpose, and each panel says so in its own note.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# The survey's own specialty ids, from `specialtySections` in questions.ts.
# `other` is the free-text escape hatch and is not a panel.
FROM_THE_SURVEY = [
    "endocrinology", "cardiology", "pulmonology", "neurology", "developmental",
    "nephrology", "gastroenterology", "haematology", "neonatology",
    "ophthalmology", "dentistry",
]


def _catalogue():
    with open(os.path.join(HERE, "..", "app", "data", "specialty_panels.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _panels():
    return _catalogue()["panels"]


# ------------------------------------------------------------- all of them ---

def test_every_specialty_the_survey_asked_about_has_a_panel():
    missing = [key for key in FROM_THE_SURVEY if key not in _panels()]
    assert not missing, f"the survey asked about these and nothing answers: {missing}"


def test_the_two_that_existed_are_untouched_by_the_nine():
    """Adding must not cost what was already there — the same rule the dental
    panel was held to when it arrived beside cardiology."""
    panels = _panels()
    assert {"cardiology", "dentistry"} <= set(panels)
    assert any(f["code"] == "ef_pct" for f in panels["cardiology"]["fields"])
    assert any(f["code"] == "cooperation" for f in panels["dentistry"]["fields"])


def test_no_python_anywhere_names_one_of_the_new_specialties():
    """The claim, stated so it stays true rather than pinned to a commit.

    "Data, not code" means the program does not know what a nephrologist is.
    Nine specialties arrived by editing one JSON file, and if that is real then
    no Python file mentions any of them — no branch, no import, no special
    case. Checked this way rather than by diffing against a baseline sha,
    because a baseline drifts and this does not: the day somebody writes
    `if panel == "neurology"`, the promise is broken whatever the diff says.

    `cardiology` and `dentistry` are excluded because they legitimately appear
    in prose — they are the worked examples in the docstrings that explain the
    mechanism, and in `app/utils/cardio.py`, which computes two published
    subtractions and is a clinical calculator rather than a panel branch.
    """
    import ast

    new_ones = {k for k in FROM_THE_SURVEY if k not in ("cardiology", "dentistry")}
    root = os.path.join(HERE, "..", "app")
    named = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            # String *constants* only. Prose is not a branch: several
            # docstrings use these specialties as the worked example — a
            # neurologist who works only neurology is how `default_for_doctor`
            # explains itself — and the handbook names them in the guidance it
            # prints. What would break the promise is one of them appearing as
            # a value the program compares against or looks up.
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in new_ones:
                        named.append(
                            f"{os.path.relpath(path, root)}:{node.lineno} "
                            f"\"{node.value}\"")

    assert not named, (
        "adding a specialty was supposed to need no code, and this code names "
        "one: " + ", ".join(named))


# --------------------------------------------------------- each one is sane ---

@pytest.mark.parametrize("key", FROM_THE_SURVEY)
def test_a_panel_is_well_formed(key):
    panel = _panels()[key]
    assert panel.get("name_ar") and panel.get("name_en")
    assert panel.get("icon")
    assert panel.get("fields"), f"{key} asks for nothing"
    for field in panel["fields"]:
        assert field["type"] in ("number", "choice", "date"), field["code"]
        assert field.get("label_ar") and field.get("label_en"), field["code"]
        if field["type"] == "choice":
            assert field.get("options"), f"{field['code']} offers no choices"


def test_no_two_panels_name_the_same_field():
    """Not tidiness — the screen renders every panel at once, so two panels
    sharing a code would put two inputs with one name in one form. The browser
    posts both and the server reads the first, so typing into the second panel
    would be silently thrown away.

    It is also why the haematology panel does not carry its own Tanner stage:
    the survey ticks puberty under both endocrinology and haematology, one
    measurement is one code, and it lives with the panel whose control number
    depends on it.
    """
    seen = {}
    clashes = []
    for key, panel in _panels().items():
        for field in panel.get("fields", []):
            if field["code"] in seen:
                clashes.append(f"{field['code']} in {seen[field['code']]} and {key}")
            seen[field["code"]] = key
    assert not clashes, "; ".join(clashes)


def test_nothing_is_asked_that_the_vitals_already_hold():
    """A second weight box means two weights for one visit and no way to know
    which is the real one. The vitals are *read*, never re-asked."""
    vitals = {"weight_kg", "height_cm", "head_circ_cm", "pulse_bpm",
              "resp_rate", "spo2", "temperature_c", "bp_systolic",
              "bp_diastolic", "blood_pressure"}
    asked = []
    for key, panel in _panels().items():
        for field in panel.get("fields", []):
            if field["code"] in vitals:
                asked.append(f"{key}.{field['code']}")
    assert not asked, f"these are vital signs and a panel asks for them: {asked}"


def test_no_panel_stores_a_number_the_program_can_work_out():
    """BMI, growth velocity, a BP percentile, a corrected age. Each is a
    function of what is already in the file, and a typed copy is a second
    answer able to disagree with the first — the same reason the cardiology
    gradient is computed at render and never stored."""
    derived = ("bmi", "growth_velocity", "corrected_age", "bp_percentile",
               "percentile", "z_score")
    stored = []
    for key, panel in _panels().items():
        for field in panel.get("fields", []):
            if any(part in field["code"] for part in derived):
                stored.append(f"{key}.{field['code']}")
    assert not stored, f"these are derivable and should not be boxes: {stored}"


def test_no_panel_carries_a_clinical_threshold():
    """The survey refuses to invent one — *"لا يوجد رقم موحّد"* — and so does
    this. Thresholds live in the clinical rules, where a clinic can see them
    and change them."""
    # The fields and their keys, not the prose around them: the notes in this
    # file discuss thresholds at length precisely because it holds none, and a
    # scan of the whole document would fail on its own explanation.
    named = []
    for key, panel in _panels().items():
        for field in panel.get("fields", []):
            words = " ".join([field["code"]] + list(field.keys())).lower()
            for word in ("threshold", "cutoff", "cut_off", "target_value",
                         "normal_max", "normal_min", "upper_limit"):
                if word in words:
                    named.append(f"{key}.{field['code']} ({word})")
    assert not named, f"the catalogue carries a threshold: {named}"


# --------------------------------------------------------- on a real screen ---

@pytest.fixture()
def desk(clinic):
    """A doctor who works every panel, in a clinic that has the module on."""
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = \
            ",".join(_panels())
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def test_every_field_of_every_panel_is_on_the_visit_screen(desk):
    """Rendered, not merely catalogued. The screen puts every panel in the
    form at once so choosing one costs no round trip — which means a field
    that does not render is a field nobody can ever fill in."""
    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)

    for key, panel in _panels().items():
        assert f'data-panel-key="{key}"' in page, f"no chip for {key}"
        for field in panel.get("fields", []):
            assert f'name="m_{field["code"]}"' in page, \
                f"{key}.{field['code']} is in the catalogue and not on the screen"


def test_a_reading_from_each_new_panel_survives_a_save(desk):
    """One number per panel, saved in one visit, each stamped with its own
    panel — the multi-panel save doing what it was built for, across nine
    specialties it has never seen."""
    from app.models import Measurement

    one_each = {}
    for key, panel in _panels().items():
        number = next((f for f in panel["fields"] if f["type"] == "number"), None)
        if number:
            one_each[f"m_{number['code']}"] = "3"

    data = {"chief_complaint": "متابعة", "specialty_panel": "endocrinology"}
    data.update(one_each)
    desk["sign_in"]("boss").post(desk["url"], data=data, follow_redirects=True)

    with desk["app"].app_context():
        rows = {m.code: m for m in Measurement.query.filter_by(
            visit_id=desk["ids"]["visit"]).all()}

    for name in one_each:
        code = name[2:]
        assert code in rows, f"{code} was posted and not written"
        assert rows[code].value_num == 3.0
        assert rows[code].panel, f"{code} was stored with no panel on it"
