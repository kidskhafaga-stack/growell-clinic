"""Charges offered at the desk for things the clinic does not have.

Reported from a screenshot of the booking screen: the extra-services list on a
paediatric clinic was offering **حضّانة (يوم) at 1500**, **رعاية مركزة (يوم) at
2000** and **إقامة داخلية (يوم) at 800**. That clinic has no incubators, no
intensive care and no beds — those modules are switched off, and pressing their
cards had been answering 404.

**And this is not the same bug as those cards.** A card that 404s wastes a
press. A ticked extra is copied onto the collect screen as a **priced line**,
so the family is billed 1500 for a night in an incubator the clinic does not
own. Nobody is protected by the module being off: the money path here is the
ordinary one, and it works perfectly.

The fix is not a guess. **The program shipped these services itself** — the
seed table in ``app/utils/services.py`` is keyed by capability, with stable
codes — so "this row is an incubator day" is a fact it wrote down rather than a
word matched in a name. What it must never do is overrule the clinic, and the
two limits below are what these tests spend most of their length on:

* a service **the clinic created** is never hidden — no shipped code, no opinion
* a clinic that has **never said** what it offers keeps everything it had
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

#: What the screenshot showed, and what none of them can do.
CANNOT_DO = ("SVC-NICU", "SVC-ICU", "SVC-WARD")


@pytest.fixture()
def clinic():
    """A paediatric clinic that said it does consultations, whose price list
    somehow carries the whole inpatient set — which is the reported state."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting
        from app.utils.services import seed_services_for_caps

        Setting.set("facility_capabilities",
                    '["general_consultation", "followup"]')
        seed_services_for_caps(["general_consultation", "followup",
                                "nicu", "icu", "ward", "dentistry"])
        db.session.commit()
    return {"app": app, "db": db}


def _offered(clinic):
    from app.blueprints.appointments.routes import _bookable_services

    with clinic["app"].test_request_context("/"):
        return {s.code for s in _bookable_services()}


def _say(clinic, caps):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("facility_capabilities", caps)
        clinic["db"].session.commit()


# --------------------------------------------------------- the reported bug --
def test_a_clinic_with_no_incubators_is_not_offered_an_incubator_day(clinic):
    offered = _offered(clinic)
    for code in CANNOT_DO:
        assert code not in offered, f"{code} is still on the booking screen"


def test_what_it_does_do_is_untouched(clinic):
    """The half that matters more. A fix that emptied the list would pass the
    test above and cost the clinic every extra it books."""
    offered = _offered(clinic)
    assert "SVC-KASHF" in offered
    assert offered, "the extras list is empty — nothing can be booked at all"


def test_switching_the_capability_on_brings_it_back(clinic):
    """It is gated on what the clinic says it does, so saying it does it is
    the whole of the remedy — no re-seeding, no support call."""
    assert "SVC-NICU" not in _offered(clinic)
    _say(clinic, '["general_consultation", "nicu"]')
    assert "SVC-NICU" in _offered(clinic)


def test_a_service_shipped_for_several_capabilities_needs_only_one(clinic):
    """The consultant's round ships with the incubators, intensive care and
    the ward. A hospital running only a ward still rounds on it."""
    _say(clinic, '["general_consultation", "ward"]')
    assert "SVC-ROUND" in _offered(clinic)


# ------------------------------------------------- the limits, which matter --
def test_a_service_the_clinic_wrote_itself_is_never_hidden(clinic):
    """**No shipped code, no opinion.** A clinic that added its own row knows
    what it sells, and a program that quietly stopped offering it would be
    overruling somebody who was right."""
    from app.models import Service

    with clinic["app"].app_context():
        clinic["db"].session.add(Service(
            name="جلسة علاج طبيعي", code="OURS-1", price=250, is_active=True))
        clinic["db"].session.commit()
    assert "OURS-1" in _offered(clinic)


def test_a_service_with_no_code_at_all_is_never_hidden(clinic):
    """Rows from before codes existed, and rows typed in a hurry. Absence of
    evidence is not evidence, and a blank code is absence."""
    from app.models import Service

    with clinic["app"].app_context():
        row = Service(name="حاجة من غير كود", price=100, is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        rid = row.id
    with clinic["app"].test_request_context("/"):
        from app.blueprints.appointments.routes import _bookable_services

        assert rid in {s.id for s in _bookable_services()}


def test_a_clinic_that_never_ran_the_wizard_keeps_everything(clinic):
    """**The upgrade-safety case, and the trap this project keeps meeting.**

    An empty capability list means "nobody has been asked", not "this clinic
    does nothing" — one empty value standing for two different facts. Read the
    wrong way it would hide the whole extras list on every clinic that has not
    run the setup wizard, which is most of them.
    """
    _say(clinic, "")
    offered = _offered(clinic)
    for code in CANNOT_DO:
        assert code in offered, "an unconfigured clinic lost a service it had"


def test_an_unreadable_capability_setting_keeps_everything_too(clinic):
    """Same reasoning, one step further out: a value the program cannot parse
    is not a clinic saying no."""
    _say(clinic, "{not json")
    assert "SVC-NICU" in _offered(clinic)


# ------------------------------------------------- where the harm actually is --
def test_the_charge_is_what_this_is_about_not_the_list(clinic):
    """A ticked extra becomes a priced line on the collect screen. Asserted so
    the reason for the fix is written next to the fix — this was never about a
    tidy list."""
    from app.models import Service

    with clinic["app"].app_context():
        night = Service.query.filter_by(code="SVC-NICU").first()
        assert night is not None and night.price == 1500, (
            "the seeded incubator day is what would have been billed")


# ----------------------------------------------------------- the seed table --
def test_every_shipped_capability_service_is_covered(clinic):
    """The map is built from the seed table rather than kept beside it, so a
    service added there tomorrow is gated without anybody remembering this
    file. Asserted, because "it is derived" is a claim like any other."""
    from app.utils.services import CAPABILITY_SERVICES, shipped_for_capabilities

    bound = shipped_for_capabilities()
    for cap, rows in CAPABILITY_SERVICES.items():
        for row in rows:
            code = row[0]
            assert code in bound or _is_core(code), (
                f"{code} is shipped for {cap} and is bound to nothing")


def _is_core(code):
    from app.utils.services import CORE_SERVICES

    return code in {r[0] for r in CORE_SERVICES}


def test_a_service_every_clinic_gets_is_bound_to_nothing(clinic):
    """The lab and the echo appear both in the core set and under a
    capability. Core wins: a service every clinic is given is not evidence
    that the clinic does anything in particular."""
    from app.utils.services import shipped_for_capabilities

    bound = shipped_for_capabilities()
    assert "SVC-LAB" not in bound
    assert "SVC-KASHF" not in bound
