"""The visit screen's header in the file's design (asked: «اقتراح ب — كل
التنبيهات جوه الرأس، واللوجو في الخلفية»).

The allergy, the long illnesses, this visit's vital-sign reading and the
problem list moved from four cards above the work into the header — the
allergy first and red. The program's mark sits faint in the empty corner.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _record(clinic):
    from app.models import Patient, PatientProblem, VitalSigns

    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.allergies = "بنسلين"
        child.chronic_diseases = "ربو"
        clinic["db"].session.add(PatientProblem(patient_id=child.id, title="ربو", icd_code="J45",
                                                status="active"))
        clinic["db"].session.add(VitalSigns(visit_id=clinic["ids"]["visit"], weight_kg=9.5,
                                            temperature_c=39.6))
        clinic["db"].session.commit()
    return clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)


def test_everything_the_doctor_must_see_is_in_the_header_and_the_allergy_first(clinic):
    page = _record(clinic)
    header = page[page.index("data-visit-header"):page.index("data-visit-actions")]
    for part in ("data-visit-allergy", "data-visit-chronic", "data-red-flag", "data-visit-problems",
                 "data-visit-weight"):
        assert part in header, part
    assert header.index("data-visit-allergy") < header.index("data-visit-chronic") < header.index("data-red-flag")
    assert "بنسلين" in header and "(J45)" in header
    # Said once: the old cards below the header are gone.
    assert page.count("بنسلين") == page[page.index("data-visit-header"):].count("بنسلين")
    assert "alert-banner" not in page[page.index("data-visit-actions"):page.index("data-visit-actions") + 4000]


def test_the_program_s_mark_is_faint_and_behind(clinic):
    page = _record(clinic)
    assert "img/brand/pediapro-mark.png" in page[page.index("data-visit-header"):page.index("data-visit-actions")]
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "css", "theme.css"),
               encoding="utf-8").read()
    rule = css[css.index(".ph2-waves .ph2-logo {"):]
    rule = rule[:rule.index("}")]
    assert "opacity: 0.12" in rule
    assert ':root[data-theme="dark"] .ph2 .vs-red' in css


def test_the_file_carries_the_same_mark(clinic):
    page = clinic["sign_in"]("doc").get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    header = page[page.index("data-file-header"):page.index("data-file-actions")]
    assert "img/brand/pediapro-mark.png" in header
