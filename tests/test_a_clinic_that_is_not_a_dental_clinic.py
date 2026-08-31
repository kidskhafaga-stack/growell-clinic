"""Dentistry as a module, and what a clinic that has not asked for it sees.

Asked for in one sentence: *"خليه مديول يتحمل بكل حاجته... ولو مش متعلّم
يتعامل مع العيادة ولا يقبل دفعة مقدمة، لكن لو متعلّم يبدأ بالتعامل إن دي
عيادة أسنان أطفال."*

**Off is the default, and that is a deviation worth stating.** Every other
module in this program is on until the setup wizard runs — which is right for
the paediatric core, because it is what the program was before the wizard
existed and a clinic upgrading into it must not lose screens it used
yesterday. A specialty is the opposite case. A paediatric clinic is not a
dental clinic, and switching dentistry on for every existing clinic because
the module now exists would put a tooth chart on their patients' files and a
dental price list in their books without anybody asking for either.

So this one runs the other way: nothing until somebody says so. Which is also
what makes "off" testable at all — every address answers 404, not an empty
screen that looks like a feature nobody finished.
"""
import pytest


def _switch(clinic, on):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1" if on else "0")
        clinic["db"].session.commit()


@pytest.fixture
def boss(clinic):
    return clinic["sign_in"]("boss")


# ------------------------------------------------------------------- off ----
def test_a_fresh_clinic_is_not_a_dental_clinic(clinic, boss):
    """Nothing switched either way. Every other module would be on here."""
    reply = boss.get(f"/dentistry/patient/{clinic['ids']['child']}")
    assert reply.status_code == 404


def test_the_module_reads_as_off_before_anybody_chooses(clinic):
    """The setting itself, so the reason for the 404 is the rule and not a
    missing route."""
    from app.utils.facility import module_enabled

    with clinic["app"].app_context():
        assert module_enabled("dentistry") is False


def test_every_other_module_still_defaults_to_on(clinic):
    """The deviation is dentistry's alone. Turning the default round for
    everything would take screens away from clinics that are using them."""
    from app.utils.facility import module_enabled

    with clinic["app"].app_context():
        for module in ("visits", "vaccinations", "finance", "reports"):
            assert module_enabled(module) is True, module


def test_recording_a_finding_is_refused_while_it_is_off(clinic, boss):
    """Not only the reading screens. A clinic that has not asked for this
    must not be able to write into its patients' files through an address
    somebody guessed."""
    reply = boss.post(f"/dentistry/patient/{clinic['ids']['child']}/tooth/55",
                      data={"condition": "caries", "surface": "occlusal"})
    assert reply.status_code == 404

    from app.models import ToothFinding

    with clinic["app"].app_context():
        assert ToothFinding.query.count() == 0


def test_it_is_not_in_the_sidebar_when_it_is_off(clinic, boss):
    """A link to a 404 is worse than no link."""
    page = boss.get("/").get_data(as_text=True)
    assert "/dentistry/" not in page


# -------------------------------------------------------------------- on ----
def test_switching_it_on_opens_the_chart(clinic, boss):
    _switch(clinic, True)
    reply = boss.get(f"/dentistry/patient/{clinic['ids']['child']}")
    assert reply.status_code == 200


def test_switching_it_back_off_closes_it_again(clinic, boss):
    """A clinic that tried it and decided against it gets its old program
    back, not a screen it has to learn to ignore."""
    _switch(clinic, True)
    assert boss.get(
        f"/dentistry/patient/{clinic['ids']['child']}").status_code == 200
    _switch(clinic, False)
    assert boss.get(
        f"/dentistry/patient/{clinic['ids']['child']}").status_code == 404


def test_the_chart_draws_both_dentitions(clinic, boss):
    """Between six and twelve a child has both sets at once. A chart showing
    one of them is showing half a mouth, for exactly the ages this clinic
    sees most."""
    _switch(clinic, True)
    page = boss.get(
        f"/dentistry/patient/{clinic['ids']['child']}").get_data(as_text=True)
    assert "16" in page          # permanent first molar
    assert "55" in page          # the baby molar above it


# --------------------------------------------------- setting it up at all ---
def test_a_clinic_can_say_it_does_dentistry(clinic):
    """The capability the wizard offers, and the module it turns on. A
    module with no way to reach the switch is a module nobody has."""
    from app.utils.facility import (ALL_CAPABILITIES, CAPABILITY_MODULES,
                                    TEMPLATES)

    assert "dentistry" in ALL_CAPABILITIES
    assert "dentistry" in CAPABILITY_MODULES["dentistry"]
    assert "pediatric_dental_clinic" in TEMPLATES


def test_choosing_that_preset_switches_the_module_on(clinic):
    """End to end through the wizard's own function, rather than trusting
    the table above to be wired to anything."""
    from app.models import Setting
    from app.utils.facility import (TEMPLATES, apply_facility,
                                    derive_modules, module_enabled)

    preset = TEMPLATES["pediatric_dental_clinic"]
    with clinic["app"].app_context():
        apply_facility(preset["type"], "عيادة أسنان أطفال", preset["caps"],
                       derive_modules(preset["caps"]))
        clinic["db"].session.commit()
        assert Setting.get("mod_enabled:dentistry") == "1"
        assert module_enabled("dentistry") is True
