"""The child's header in the file's design on every screen with a child at
the top — the emergency attendance, the stay, the growth chart and the
vaccinations (asked: «اعمل نفس الشكل في صفحة الطوارئ وفى كل حته بيظهر فيها»)
— and the picture's shape as the clinic's own choice, round unless it says
otherwise (asked: «نفّذ الاتنين والافتراضي دائرية»)."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _allergic(c):
    from app.models import Patient

    with c["app"].app_context():
        child = c["db"].session.get(Patient, c["ids"]["child"])
        child.allergies = "بنسلين"
        child.chronic_diseases = "ربو"
        c["db"].session.commit()


def _between(page, start, end):
    a = page.index(start)
    return page[a:page.index(end, a)]


def test_the_emergency_attendance(clinic):
    from app.models import EmergencyVisit, Setting

    _allergic(clinic)
    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        row = EmergencyVisit(patient_id=clinic["ids"]["child"], arrival="ambulance",
                             arrived_at=datetime.utcnow() - timedelta(minutes=20),
                             level="2", urgent=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        rid = row.id
    page = clinic["sign_in"]("doc").get(f"/emergency/attendance/{rid}").get_data(as_text=True)
    head = _between(page, "data-er-header", "data-er-actions")
    for piece in ("ph2-logo", "patient-avatar", "data-er-allergy", "بنسلين", "data-er-chronic",
                  'data-er-level', "ph2-urgent"):
        assert piece in head, piece
    actions = page[page.index("data-er-actions"):]
    actions = actions[:actions.index("</details>")]
    for door in ("data-seen-form", "data-write-visit", "data-to-family-paper",
                 "data-to-wristband", "/emergency/register"):
        assert door in actions, door
    first = actions[:actions.index("data-write-visit")]
    assert "data-seen-form" in first and "btn-primary" in first, \
        "not yet seen: «the doctor saw the child» is the first button"


def test_the_stay(clinic):
    from app.models import Setting
    from app.models.admission import Admission

    _allergic(clinic)
    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        stay = Admission(patient_id=clinic["ids"]["child"], reason="التهاب رئوي",
                         admitted_at=datetime.utcnow() - timedelta(days=1))
        clinic["db"].session.add(stay)
        clinic["db"].session.commit()
        sid = stay.id
    page = clinic["sign_in"]("boss").get(f"/beds/admission/{sid}").get_data(as_text=True)
    head = _between(page, "data-stay-hero", "</section>")
    for piece in ("ph2-logo", "patient-avatar", "data-stay-allergy", "data-stay-length",
                  "data-stay-mrp", 'data-stay-consent="missing"', "التهاب رئوي"):
        assert piece in head, piece
    actions = head[head.index("data-stay-actions"):]
    assert actions.index("data-stay-arrest") < actions.index("data-file-more"), \
        "the arrest button is never under a menu"
    assert "data-to-wristband" in actions[actions.index("data-file-more"):]


def test_the_growth_chart_and_the_vaccinations(clinic):
    _allergic(clinic)
    doc = clinic["sign_in"]("doc")
    growth = doc.get(f"/growth/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-growth-header" in growth and "ph2-logo" in growth
    vacc = doc.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-vacc-header" in vacc and "data-vacc-allergy" in vacc
    assert "/certificate" in _between(vacc, "data-vacc-header", "The agreed plan")


def test_the_picture_is_round_until_the_clinic_says_otherwise(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    assert 'data-avatar="round"' in boss.get("/dashboard").get_data(as_text=True)
    settings = boss.get("/settings/").get_data(as_text=True)
    assert "data-avatar-shape-setting" in settings
    boss.post("/settings/", data={"avatar_shape": "rounded", "active_tab": "logo"})
    with clinic["app"].app_context():
        assert Setting.get("avatar_shape") == "rounded"
    assert 'data-avatar="rounded"' in boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    boss.post("/settings/", data={"avatar_shape": "", "active_tab": "logo"})
    assert 'data-avatar="round"' in boss.get("/dashboard").get_data(as_text=True)


def test_the_boy_s_and_girl_s_ring_survives_the_new_header():
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "css", "theme.css"),
               encoding="utf-8").read()
    assert ".ph2 img.patient-avatar.gender-male { border: 3px solid #3b82f6; }" in css
    assert ".ph2 img.patient-avatar.gender-female { border: 3px solid #ec4899; }" in css
    radius = css[css.index(".ph2 .patient-avatar.lg {"):]
    radius = radius[:radius.index("}")]
    assert "border-radius" not in radius, "the header follows the clinic's choice, round by default"
    assert ':root[data-avatar="rounded"] .patient-avatar' in css
