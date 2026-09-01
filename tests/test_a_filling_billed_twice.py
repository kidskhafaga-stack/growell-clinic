"""Two ways to charge for a filling, and nothing joining them.

A dental plan raises **one invoice for the agreed total** when the family
accepts it. A procedure added to a visit goes on that visit's own bill. Both
are correct on their own, and a child on a plan that includes a filling on 55
— whose dentist then adds "filling, primary tooth" to the visit that did it —
is billed for that filling twice, with the program silent both times.

**A warning, not a refusal.** It can genuinely be extra work: a second tooth
found on the day, a repair, something agreed there and then. The dentist is
the one who knows which. A block would have them delete the plan line to get
past it, which loses the record of what the family agreed to — trading a
double charge for a missing agreement.

And nothing here fires in a clinic that does not do dentistry, where a
service on a visit is the only way it was ever billed.
"""
import pytest


@pytest.fixture
def dental(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


def _service(clinic, name="حشو سن لبني"):
    from app.models import Service

    with clinic["app"].app_context():
        svc = Service(name=name, category="procedure", price=600)
        clinic["db"].session.add(svc)
        clinic["db"].session.commit()
        return svc.id


def _accepted_plan(clinic, service_id, tooth=55, status="accepted"):
    from app.models import TreatmentPlan, TreatmentPlanItem

    with clinic["app"].app_context():
        plan = TreatmentPlan(patient_id=clinic["ids"]["child"], title="خطة",
                             status=status)
        clinic["db"].session.add(plan)
        clinic["db"].session.flush()
        clinic["db"].session.add(TreatmentPlanItem(
            plan_id=plan.id, tooth=tooth, service_id=service_id,
            description="حشو", price=600))
        clinic["db"].session.commit()
        return plan.id


def _add_to_visit(clinic, service_id):
    return clinic["sign_in"]("doc").post(
        f"/visits/{clinic['ids']['visit']}/services",
        data={"service_id": service_id, "quantity": "1"},
        follow_redirects=True).get_data(as_text=True)


# ------------------------------------------------------------ it warns -----
def test_it_says_the_plan_already_covers_this(dental):
    svc = _service(dental)
    _accepted_plan(dental, svc)
    page = _add_to_visit(dental, svc)
    assert "خطة علاج مقبولة" in page


def test_it_names_the_tooth(dental):
    """"Something is on a plan" sends a dentist reading three plans. The
    filling on 55 is the one they need to look at.

    Asserted on the tooth *inside the warning*, not anywhere on the page —
    "55" appears in prices, dates and other teeth, so the loose version passed
    with the tooth dropped from the message entirely.
    """
    svc = _service(dental)
    _accepted_plan(dental, svc, tooth=55)
    page = _add_to_visit(dental, svc)
    assert "حشو سن لبني — 55" in page


def test_the_procedure_is_still_added(dental):
    """A warning, not a refusal. It can be extra work outside the plan, and
    blocking it would have somebody delete the plan line to get past — losing
    the record of what the family agreed to."""
    from app.models import VisitService

    svc = _service(dental)
    _accepted_plan(dental, svc)
    _add_to_visit(dental, svc)
    with dental["app"].app_context():
        assert VisitService.query.filter_by(service_id=svc).count() == 1


# --------------------------------------------------- and when it must not --
def test_a_draft_plan_does_not_warn(dental):
    """A draft has billed nobody. Warning about it would be warning about
    money that does not exist, which teaches people to click past warnings."""
    svc = _service(dental)
    _accepted_plan(dental, svc, status="draft")
    assert "خطة علاج مقبولة" not in _add_to_visit(dental, svc)


def test_a_dropped_item_does_not_warn(dental):
    """Taken off the plan before it happened, so the plan is not billing for
    it."""
    from app.models import TreatmentPlanItem

    svc = _service(dental)
    _accepted_plan(dental, svc)
    with dental["app"].app_context():
        item = TreatmentPlanItem.query.filter_by(service_id=svc).first()
        item.status = "dropped"
        dental["db"].session.commit()
    assert "خطة علاج مقبولة" not in _add_to_visit(dental, svc)


def test_a_different_service_does_not_warn(dental):
    """The plan covers a filling; this visit did an extraction. Warning on
    any dental service at all would be a warning nobody reads."""
    on_plan = _service(dental, "حشو سن لبني")
    _accepted_plan(dental, on_plan)
    other = _service(dental, "خلع سن لبني")
    assert "خطة علاج مقبولة" not in _add_to_visit(dental, other)


def test_another_childs_plan_does_not_warn(dental):
    """Plans belong to children, not to the clinic."""
    from app.models import Patient, TreatmentPlan, TreatmentPlanItem
    from datetime import date

    svc = _service(dental)
    with dental["app"].app_context():
        other = Patient(patient_number="999", full_name="طفل تاني",
                        date_of_birth=date(2023, 1, 1), gender="female")
        dental["db"].session.add(other)
        dental["db"].session.flush()
        plan = TreatmentPlan(patient_id=other.id, status="accepted")
        dental["db"].session.add(plan)
        dental["db"].session.flush()
        dental["db"].session.add(TreatmentPlanItem(
            plan_id=plan.id, tooth=55, service_id=svc, description="حشو",
            price=600))
        dental["db"].session.commit()
    assert "خطة علاج مقبولة" not in _add_to_visit(dental, svc)


def test_a_clinic_without_dentistry_never_sees_it(clinic):
    """Where a service on a visit is the only way it was ever billed, there
    is no second charge to warn about."""
    svc = _service(clinic)
    _accepted_plan(clinic, svc)
    assert "خطة علاج مقبولة" not in _add_to_visit(clinic, svc)
