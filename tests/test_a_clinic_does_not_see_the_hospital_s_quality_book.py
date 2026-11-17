"""A clinic does not see a hospital's quality book — and can switch it.

The owner, from a single-doctor clinic's screen, with «الشكاوى · بلّغ عن حادثة
· الحوادث · تحليل الأسباب · مكافحة العدوى» circled in the side menu:

    «الجزء ده باين ليه فى العيادة ده شغل بتاع مستشفيات؟ وليه مش بيان فى
    المديولز؟»

They were tied to a capability and to nothing else, so they showed at every
facility, and nothing in «الموديولز المفعّلة» could switch them off. Now they
are three parts (``utils/facility.FACILITY_PARTS``):

* **complaints** — on unless switched off (clinics take complaints too);
* **quality** (incidents, root causes, committees, guidelines) and **ipc**
  (infection control, hand hygiene) — a hospital's: on a configured copy
  that never said, they follow the wards. Ticking a ward, an ICU, an NICU,
  an emergency room or a theatre switches them on.

And off means off: no door, no link, no bell, and the address answers 404.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

DOORS = ("data-nav-incident-report", "data-nav-incidents", "data-nav-rca",
         "data-nav-ipc")


@pytest.fixture()
def single_doctor(clinic):
    """The owner's case: the wizard run for a single-doctor clinic."""
    from app.utils import facility

    with clinic["app"].app_context():
        caps = facility.default_caps_for("single_doctor")
        facility.apply_facility("single_doctor", "عيادة", caps,
                                facility.derive_modules(caps))
        clinic["db"].session.commit()
    return clinic


def _page(c, url="/dashboard", who="boss"):
    return c["sign_in"](who).get(url).get_data(as_text=True)


def test_a_single_doctor_clinic_sees_no_hospital_quality_screens(single_doctor):
    page = _page(single_doctor)
    for mark in DOORS:
        assert mark not in page, mark
    # The complaints book stays — clinics take complaints too.
    assert "data-nav-complaints" in page and "data-topbar-complaint" in page
    boss = single_doctor["sign_in"]("boss")
    for url in ("/incidents/report", "/incidents/", "/quality/rca",
                "/infection-control/", "/hand-hygiene/"):
        assert boss.get(url).status_code == 404, url


def test_the_three_are_in_the_module_switches(single_doctor):
    from app.models import User

    # The setup screen is the owner's (`owner_required`).
    with single_doctor["app"].app_context():
        User.query.filter_by(username="boss").one().is_super_admin = True
        single_doctor["db"].session.commit()
    page = _page(single_doctor, "/settings/setup")
    for part in ("complaints", "quality", "ipc"):
        assert f'name="modules" value="{part}"' in page, part


def test_switching_them_is_the_clinic_s_choice(single_doctor):
    from app.utils import facility

    with single_doctor["app"].app_context():
        caps = facility.capabilities()
        mods = set(facility.derive_modules(caps)) | {"quality", "ipc"}
        mods.discard("complaints")
        facility.apply_facility("single_doctor", "عيادة", caps, sorted(mods))
        single_doctor["db"].session.commit()
    page = _page(single_doctor)
    for mark in DOORS:
        assert mark in page, mark
    assert "data-nav-complaints" not in page
    assert "data-topbar-complaint" not in page
    assert single_doctor["sign_in"]("boss").get("/complaints/") \
        .status_code == 404


def test_a_hospital_service_brings_them(clinic):
    from app.utils import facility

    for cap in ("ward", "icu", "nicu", "emergency_care", "surgery"):
        assert {"quality", "ipc"} <= set(facility.derive_modules([cap])), cap
    assert "complaints" in facility.derive_modules(["general_consultation"])


def test_a_hospital_that_never_said_keeps_them(clinic):
    """A configured copy that predates the switch follows its wards: a
    hospital with beds keeps its quality book, a clinic without does not."""
    from app.models import Setting
    from app.utils import facility

    with clinic["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:beds", "1")
        clinic["db"].session.commit()
        assert facility.module_enabled("quality")
        assert facility.module_enabled("ipc")
        Setting.set("mod_enabled:beds", "0")
        clinic["db"].session.commit()
    with clinic["app"].app_context():
        assert not facility.module_enabled("quality")
        assert not facility.module_enabled("ipc")
        assert facility.module_enabled("complaints")


def test_the_spill_button_follows_quality(single_doctor):
    """Found in the review: the hazardous-materials screen still linked
    «report a spill» to the incidents book that answers 404 here."""
    page = single_doctor["sign_in"]("boss").get("/facility/hazmat")
    assert page.status_code == 200
    assert "/incidents/" not in page.get_data(as_text=True)
