"""A clinic that said it does dentistry, and got a paediatric price list.

Ticking a specialty in the setup wizard is meant to bring the base services
that specialty bills for — that is what every other capability does, and it is
why the clinic can take money on its first afternoon instead of typing a
catalogue first.

Dentistry was added as a module without being added to that map. So a
paediatric dental clinic finished the wizard and had no filling, no crown, no
extraction and no scale-and-polish to charge for — and, because the fallback
fires when *no* ticked capability matched, a clinic that ticked dentistry and
nothing else was handed the paediatric core instead: a consultation, a
nebulizer session and a vaccination fee, in a practice that does none of them.

The list is paediatric dentistry, not general dentistry. A five-year-old has
no implants and no bridges; what they have is pulpotomies, stainless steel
crowns and space maintainers, and those are the rows a screen should not make
somebody scroll past adult prosthetics to reach.
"""
import pytest


@pytest.fixture
def owner(clinic):
    from app.models import User

    with clinic["app"].app_context():
        user = User.query.filter_by(username="boss").first()
        user.is_super_admin = True
        clinic["db"].session.commit()
    return clinic["sign_in"]("boss")


def _codes(clinic):
    from app.models import Service

    with clinic["app"].app_context():
        return {c for (c,) in Service.query.with_entities(Service.code).all() if c}


def _seed(clinic, caps):
    from app.utils.services import seed_services_for_caps

    with clinic["app"].app_context():
        seed_services_for_caps(caps)
        clinic["db"].session.commit()


# --------------------------------------------------------------- the list ---
def test_a_dental_clinic_gets_dental_services(clinic):
    _seed(clinic, ["dentistry"])
    codes = _codes(clinic)
    assert any(code.startswith("SVC-DENT-") for code in codes), \
        "a dental clinic finished setup with nothing dental to charge for"


def test_it_can_bill_the_work_a_plan_is_made_of(clinic):
    """The four things a paediatric treatment plan is actually built from.

    Named individually rather than counted, because "some dental services
    exist" is satisfied by a list that cannot price a single visit.
    """
    from app.models import Service

    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        names = " ".join(s.name for s in Service.query.all())
    for what in ("حشو", "خلع", "تلبيس", "بتر عصب"):
        assert what in names, f"nothing to charge for {what}"


def test_it_is_paediatric_dentistry(clinic):
    """A general dental list carries implants, bridges and dentures. A child
    has none of them, and every row on the screen is a row somebody reads past
    to reach the one they want."""
    from app.models import Service

    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        names = " ".join(s.name for s in Service.query.all())
    for adult in ("زرع", "جسر", "طقم"):
        assert adult not in names

    # And the ones that only exist because the patient is a child. Named one
    # by one: "there is something called تلبيس" was true of the aesthetic
    # crown by itself, so losing the stainless steel one — the crown a
    # paediatric clinic actually fits — passed unnoticed.
    assert "حافظ مسافة" in names       # space maintainer
    assert "بتر عصب" in names          # pulpotomy — the paediatric pulp treatment
    assert "تلبيسة ستانلس" in names    # the stainless steel crown itself


def test_a_baby_tooth_and_an_adult_one_are_priced_apart(clinic):
    """Mixed dentition is the paediatric case, and the two are not the same
    job: a filling in a tooth with two years left is not the filling that has
    to last a lifetime. One row for both would make every plan in a mixed
    mouth wrong in one direction or the other.

    Asserted on the two rows, not on the word لبني — that word is also in the
    pulpectomy and the extraction, so a version of this that searched for it
    passed with the primary filling deleted outright.
    """
    from app.models import Service

    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        primary = Service.query.filter_by(code="SVC-DENT-FILLP").first()
        permanent = Service.query.filter_by(code="SVC-DENT-FILL").first()
        assert primary is not None and permanent is not None
        assert primary.price != permanent.price


def test_a_purely_dental_clinic_is_not_handed_the_paediatric_core(clinic):
    """The second half of the bug, and the one that would have been missed.

    The fallback fires when *no* ticked capability matched anything. With
    dentistry absent from the map, a clinic that ticked it and nothing else
    matched nothing — so it was given the paediatric core: a consultation, a
    nebulizer session and a vaccination fee, in a practice that does none of
    them.
    """
    _fresh_install(clinic)
    _seed(clinic, ["dentistry"])
    codes = _codes(clinic)
    assert "SVC-NEB" not in codes
    assert "SVC-VACFEE" not in codes
    assert any(c.startswith("SVC-DENT-") for c in codes)


def _fresh_install(clinic):
    """No services at all — which is the only state the fallback fires in.

    The test fixture builds a working paediatric clinic, services included, so
    a version of this test without this line passed while the bug was still
    there: `Service.query.first()` was not None, the fallback never ran, and
    the test reported on a branch it had not reached.
    """
    from app.models import Service

    with clinic["app"].app_context():
        Service.query.delete()
        clinic["db"].session.commit()


def test_a_paediatric_clinic_gets_no_dental_prices(clinic):
    """The other direction. Dentistry is opt-in precisely so a paediatric
    clinic is not handed a dental price list nobody asked for."""
    _seed(clinic, ["general_consultation", "vaccination"])
    assert not any(c.startswith("SVC-DENT-") for c in _codes(clinic))


def test_running_the_wizard_twice_does_not_double_the_price_list(clinic):
    """Re-running setup is how a clinic adds a specialty later, so it happens.

    Counted in **rows**, not in distinct codes. The first version of this test
    compared sets of codes and passed with the de-duplication taken out
    altogether — a set collapses the duplicates it was supposed to be
    detecting, so the clinic would have had two of every filling and the test
    would have reported it clean.
    """
    from app.models import Service

    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        first = Service.query.count()
    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        assert Service.query.count() == first
        # Uncoded rows are excluded: a clinic types its own services in on
        # the services screen and those have no code at all, which is not the
        # duplication this is looking for.
        codes = [c for (c,) in Service.query.with_entities(Service.code).all() if c]
    assert len(codes) == len(set(codes)), "a service code appears twice"


# ------------------------------------------------- through the real screen --
def test_the_wizard_seeds_them(clinic, owner):
    """Asserted through the form somebody actually fills in, because the map
    is only worth anything if the wizard reaches it."""
    owner.post("/settings/setup",
               data={"facility_type": "single_doctor",
                     "facility_name": "عيادة أسنان الأطفال",
                     "capabilities": ["dentistry"]},
               follow_redirects=True)
    assert any(c.startswith("SVC-DENT-") for c in _codes(clinic))


def test_they_can_be_put_on_a_treatment_plan(clinic):
    """The end of the thread this started at: a plan line priced from the
    clinic's own catalogue, so the commission, the reports and the invoice all
    behave the way they do for everything else this clinic sells."""
    from app.models import Service, Setting, TreatmentPlan

    _seed(clinic, ["dentistry"])
    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
        crown = Service.query.filter(Service.code.like("SVC-DENT-%"),
                                     Service.name.contains("تلبيس")).first()
        assert crown is not None
        price = crown.price

    boss = clinic["sign_in"]("boss")
    boss.post(f"/dentistry/patient/{clinic['ids']['child']}/plans/new",
              data={"title": "خطة"}, follow_redirects=True)
    with clinic["app"].app_context():
        plan_id = TreatmentPlan.query.order_by(TreatmentPlan.id.desc()).first().id
    boss.post(f"/dentistry/plan/{plan_id}/item",
              data={"tooth": "55", "description": crown_name(clinic),
                    "price": str(price)}, follow_redirects=True)
    with clinic["app"].app_context():
        plan = clinic["db"].session.get(TreatmentPlan, plan_id)
        assert plan.total == price


def crown_name(clinic):
    from app.models import Service

    with clinic["app"].app_context():
        return Service.query.filter(
            Service.code.like("SVC-DENT-%"),
            Service.name.contains("تلبيس")).first().name


# ------------------------------- the fallback this sits next to -------------
def test_a_clinic_that_ticked_nothing_still_gets_a_price_list(clinic):
    """Untested before this file existed, and worth pinning while I am here.

    The fallback is what stops a clinic finishing setup with an empty
    catalogue and a reception desk that cannot bill the first patient. It
    fires only when no ticked capability matched *and* there are no services
    at all, so it is invisible on any database that has been used.
    """
    from app.models import Service

    _fresh_install(clinic)
    _seed(clinic, [])
    with clinic["app"].app_context():
        assert Service.query.count() > 0
    assert "SVC-KASHF" in _codes(clinic)


def test_the_fallback_does_not_overwrite_a_clinics_own_catalogue(clinic):
    """A clinic that has built its own list keeps it. The fallback is for an
    empty install, not a correction anybody asked for."""
    _seed(clinic, [])          # the fixture's clinic already has services
    assert "SVC-KASHF" not in _codes(clinic)
