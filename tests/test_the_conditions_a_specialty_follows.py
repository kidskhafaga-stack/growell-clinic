"""The conditions a specialty follows, on the child's list in one press —
and without an ICD code, on purpose.

The survey's third question per specialty is *"الحالات التي تتابعها على المدى
الطويل"*, and the answers name ninety-three of them across eleven specialties:
type 1 diabetes and congenital adrenal hyperplasia for the endocrinologist,
thalassaemia and G6PD for the haematologist, retinopathy of prematurity for two
different specialties at once. `PatientProblem` has been able to hold them —
with `icd_code`, `status`, `onset_date` and `resolved_date` — for months.
Nothing offered them.

**The decision worth defending is that no code is attached.**

The obvious move is to look each condition up in the loaded ICD table and store
what comes back. It was tried, on the real table with all 71,704 entries, and
what comes back is wrong often enough to be dangerous:

| asked for | the table's first answer | what it actually is |
|---|---|---|
| Type 1 diabetes mellitus | `E10.10` | type 1 **with ketoacidosis** — not `E10.9` |
| Epilepsy | `G40.001` | a specific localisation-related variant — not `G40.909` |
| Nephrotic syndrome | `N04.0` | with minor glomerular abnormality — not `N04.9` |
| Strabismus | `H49.881` | a specific palsy — not `H50.9` |
| Coeliac disease, sickle cell disease, iron deficiency anaemia | nothing | the bundled table is the US clinical modification and spells them the other way |

A wrong code on a child's problem list is worse than no code. It is a clinical
claim nobody made, and it travels — into reports, into insurance, into the next
doctor's reading of the file. So the chip fills the name and the doctor attaches
the code through the ICD search already in that form, which knows the spelling.
That is the same rule the assistant follows for diagnoses: **the program owns
the codes, and a suggestion is a name.**
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# Matched on the attribute, not the class: `.chart-tests` is a CSS rule in the
# same template. Four tests in this suite have been fooled that way already.
STRIP = 'data-conditions="'


def _catalogue():
    with open(os.path.join(HERE, "..", "app", "data", "specialty_panels.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["panels"]


@pytest.fixture()
def desk(clinic):
    from app.extensions import db
    from app.models import Setting, User, Visit

    with clinic["app"].app_context():
        Setting.set("mod_enabled:panels", "1")
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        db.session.get(User, visit.doctor_id).specialty_panels = "endocrinology"
        db.session.commit()
    clinic["url"] = f"/visits/{clinic['ids']['visit']}/record"
    return clinic


def _page(kit):
    return kit["sign_in"]("boss").get(kit["url"]).get_data(as_text=True)


# ------------------------------------------------------------- the catalogue ---

def test_every_specialty_carries_the_conditions_it_follows():
    panels = _catalogue()
    for key in ("endocrinology", "cardiology", "pulmonology", "neurology",
                "developmental", "nephrology", "gastroenterology",
                "haematology", "neonatology", "ophthalmology", "dentistry"):
        assert panels[key].get("conditions"), f"{key} follows no conditions"


def test_every_condition_is_named_in_both_languages():
    for key, panel in _catalogue().items():
        for row in panel.get("conditions") or []:
            assert row.get("label_ar") and row.get("label_en"), \
                f"{key}.{row.get('code')} is missing a name"


def test_no_condition_carries_an_icd_code():
    """The whole point. A code here would be a clinical claim nobody made."""
    for key, panel in _catalogue().items():
        for row in panel.get("conditions") or []:
            assert "icd" not in " ".join(row.keys()).lower(), \
                f"{key}.{row['code']} carries a code"


def test_the_same_condition_may_appear_under_two_specialties():
    """Retinopathy of prematurity is followed by the neonatologist and by the
    ophthalmologist, and enuresis by the nephrologist and the developmental
    clinic. Unlike a *measurement* code, which must be unique because two
    inputs with one name break the form, a condition is a fact about the child
    that two specialists can both be watching."""
    panels = _catalogue()
    neo = {r["code"] for r in panels["neonatology"]["conditions"]}
    eye = {r["code"] for r in panels["ophthalmology"]["conditions"]}
    assert "rop" in neo and "rop" in eye


def test_the_icd_lookup_really_is_unreliable_for_these(clinic):
    """The evidence behind the decision, kept executable rather than only
    written down. If a future ICD table resolves these correctly, this test
    fails and the decision is worth revisiting — which is the point."""
    from app.utils import icd

    with clinic["app"].app_context():
        if not icd.coverage().get("10", {}).get("full"):
            pytest.skip("no full ICD table loaded, so nothing to distrust")

        top = icd.search_icd("Type 1 diabetes mellitus", limit=1)
        assert top, "the table answers nothing at all for a common condition"
        assert top[0]["code"] != "E10.9", (
            "the table now resolves type 1 diabetes to the unspecified code; "
            "attaching codes automatically may be worth revisiting")


# ---------------------------------------------------------- on the screen ---

def test_the_panel_offers_them(desk):
    page = _page(desk)

    assert STRIP in page, "the panel does not offer the conditions it follows"
    assert "السكر النوع الأول" in page


def test_pressing_one_puts_it_on_the_childs_problem_list(desk):
    import re

    from app.models import PatientProblem

    page = _page(desk)
    # A button naming the hidden form at the foot of the page, not a form of
    # its own — a form inside the consultation form ended it early in the
    # browser and cost a doctor their Save. See `test_a_form_inside_a_form.py`.
    chip = re.search(
        r'<button[^>]*form="panelProblemForm"[^>]*value="([^"]+)"[^>]*>'
        r'(?:(?!</button>).)*السكر النوع الأول', page, re.S)
    assert chip, "no one-press control for that condition is on the screen"

    desk["sign_in"]("boss").post(
        f"/patients/{desk['ids']['child']}/problems",
        data={"condition": chip.group(1),
              "visit_id": desk["ids"]["visit"]},
        follow_redirects=True)

    with desk["app"].app_context():
        rows = PatientProblem.query.filter_by(
            patient_id=desk["ids"]["child"]).all()
        assert len(rows) == 1
        assert rows[0].title == "السكر النوع الأول"
        assert rows[0].icd_code is None, \
            "a code was attached, and nothing in the program knows it is right"


def test_it_comes_back_to_the_consultation_and_not_to_the_patient_file(desk):
    """The doctor is mid-visit and the child is in the room. A redirect to the
    patient file is a redirect out of the consultation."""
    import re

    page = _page(desk)
    # The chip is a button that names the hidden form at the foot of the page;
    # that form carries the visit id, which is what brings the doctor back.
    chip = re.search(
        r'<button[^>]*form="panelProblemForm"[^>]*value="([^"]+)"', page)
    assert chip, "no condition chip on the screen"
    back = re.search(
        r'id="panelProblemForm".*?name="visit_id" value="(\d+)"', page, re.S)
    assert back, "the chip's form does not carry the way back"

    reply = desk["sign_in"]("boss").post(
        f"/patients/{desk['ids']['child']}/problems",
        data={"condition": chip.group(1), "visit_id": back.group(1)})

    assert reply.status_code in (301, 302)
    assert f"/visits/{desk['ids']['visit']}/record" in reply.headers["Location"]


def test_a_visit_belonging_to_another_child_is_not_a_way_back(desk):
    """The return is a visit id and never a URL, and the id is checked against
    this patient's own visits — otherwise the form would name an address."""
    from app.extensions import db
    from app.models import Patient, Visit
    from app.utils.clock import local_today

    with desk["app"].app_context():
        other = Patient(patient_number="P9", full_name="طفل تاني", gender="male",
                        date_of_birth=local_today(), is_active=True)
        db.session.add(other)
        db.session.flush()
        theirs = Visit(patient_id=other.id, doctor_id=desk["ids"]["doctor"],
                       visit_date=local_today())
        db.session.add(theirs)
        db.session.commit()
        theirs_id = theirs.id

    reply = desk["sign_in"]("boss").post(
        f"/patients/{desk['ids']['child']}/problems",
        data={"title": "حاجة", "visit_id": theirs_id})

    assert f"/visits/{theirs_id}/record" not in reply.headers["Location"], \
        "a visit belonging to another child was accepted as the way back"
    assert f"/patients/{desk['ids']['child']}" in reply.headers["Location"]


def test_a_condition_already_on_the_list_is_marked_and_not_offered_twice(desk):
    from app.models import PatientProblem

    with desk["app"].app_context():
        desk["db"].session.add(PatientProblem(
            patient_id=desk["ids"]["child"], title="السكر النوع الأول"))
        desk["db"].session.commit()

    page = _page(desk)
    assert "disabled" in page.split(STRIP)[1][:4000], \
        "a condition already on the file is offered again as if it were new"


def test_a_clinic_without_the_module_is_offered_none_of_it(desk):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("mod_enabled:panels", "0")
        desk["db"].session.commit()

    assert STRIP not in _page(desk)
