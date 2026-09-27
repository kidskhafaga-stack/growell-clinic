"""البيانات التجريبية على الأقسام المفتوحة — قسم قسم.

اتطلبت كده: *«بيبص على الأقسام المفتوحة ويتعامل عليها، يحمّل فيها بيانات
تجريبية لاختبارها»*.

اللي بيتمسك هنا:

* **القسم المقفول ما بيتحمّلش**: عيادة من غير أسرّة ما بتتبنيش لها
  مستشفى، ومن غير عمليات ما بيتحجزش فيها عملية؛
* **القسم المفتوح بياخد نصيبه**، بأدوات البرنامج نفسها؛
* **قسم اتفتح بعدين بياخد نصيبه بعدين** — من غير ما العيادة تتحمّل تاني؛
* **قسم مالقاش حاجة يتبني عليها بيستنى**: صيدلية العنابر من غير طفل
  داخل ما بتتعلّمش إنها اتحمّلت؛
* **وكل ده بيتشال بـ«امسح التجريبية بس»**، العيادة والأقسام مع بعض،
  وبعدها ينفع يتحمّل من الأول.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HOSPITAL = ("beds", "ward", "icu", "observations", "labs", "pharmacy",
            "theatres", "dentistry", "duty")


def _switch(clinic, *modules, on=True):
    from app.extensions import db
    from app.models import Setting

    with clinic["app"].app_context():
        for module in modules:
            Setting.set(f"mod_enabled:{module}", "1" if on else "0")
        db.session.commit()


def _load(clinic):
    from app.utils import demo_sections

    with clinic["app"].app_context():
        return demo_sections.load()


def _count(clinic, model_name, **where):
    import app.models as models

    with clinic["app"].app_context():
        model = getattr(models, model_name)
        return model.query.filter_by(**where).count()


def _state(clinic):
    from app.utils import demo_sections

    with clinic["app"].app_context():
        return demo_sections.seeded(), demo_sections.missing()


# ------------------------------------------------------------ a clinic ----
def test_a_clinic_without_beds_gets_no_hospital(clinic):
    result = _load(clinic)
    assert set(result["sections"]) == {"clinic"}
    assert result["patients"] > 0
    for model in ("Unit", "Admission", "Operation", "TreatmentPlan", "Duty",
                  "ObservationOrder"):
        assert _count(clinic, model) == 0, model
    assert _state(clinic) == ({"clinic"}, [])


def test_loading_again_loads_nothing(clinic):
    _load(clinic)
    from app.models import Patient

    with clinic["app"].app_context():
        before = Patient.query.count()
    assert _load(clinic)["skipped"] is True
    with clinic["app"].app_context():
        assert Patient.query.count() == before


# ------------------------------------------------------------ a hospital ----
def test_every_open_section_gets_its_share(clinic):
    _switch(clinic, *HOSPITAL)
    result = _load(clinic)
    assert set(result["sections"]) == {"clinic", "wards", "observations",
                                       "labs", "pharmacy", "theatres",
                                       "dentistry", "duty"}
    assert _count(clinic, "Admission") >= 1
    assert _count(clinic, "ObservationOrder") >= 1
    assert _count(clinic, "VisitInvestigation", status="requested") >= 1
    assert _count(clinic, "MedicationOrder") >= 1
    assert _count(clinic, "ChartReview") == 1
    assert _count(clinic, "Operation") == 1
    assert _count(clinic, "TreatmentPlan") == 1
    assert _count(clinic, "Duty") == 1
    assert _state(clinic)[1] == []


def test_only_the_open_departments_are_built(clinic):
    """Intensive care open, the incubators not: no incubators."""
    from app.models import Unit

    _switch(clinic, "beds", "icu")
    _load(clinic)
    with clinic["app"].app_context():
        kinds = {u.kind for u in Unit.query.all()}
    assert kinds == {"icu"}


def test_a_section_opened_later_gets_its_share_later(clinic):
    from app.models import Patient

    _load(clinic)
    with clinic["app"].app_context():
        patients = Patient.query.count()
    _switch(clinic, "theatres")
    assert _state(clinic)[1] == ["theatres"]
    result = _load(clinic)
    assert set(result["sections"]) == {"theatres"}
    assert _count(clinic, "Operation") == 1
    with clinic["app"].app_context():
        assert Patient.query.count() == patients     # the clinic, not again


def test_a_section_with_nothing_to_build_on_waits(clinic):
    """The ward pharmacy with no child in a bed has nothing to review — it
    is not marked done, and takes its share once the beds are open."""
    _switch(clinic, "pharmacy")
    result = _load(clinic)
    assert "pharmacy" not in result["sections"]
    assert "pharmacy" in _state(clinic)[1]
    _switch(clinic, "beds", "ward")
    result = _load(clinic)
    assert {"wards", "pharmacy"} <= set(result["sections"])
    assert _count(clinic, "MedicationOrder") >= 1


# ------------------------------------------------------------ removing ----
def test_removing_takes_every_section_with_it(clinic):
    from app.extensions import db
    from app.utils import demo_trace

    _switch(clinic, *HOSPITAL)
    _load(clinic)
    with clinic["app"].app_context():
        removed, kept = demo_trace.remove()
        db.session.commit()
    assert kept == {}
    for model in ("Admission", "Operation", "TreatmentPlan", "Duty",
                  "ObservationOrder", "MedicationOrder", "Unit"):
        assert _count(clinic, model) == 0, model
    seeded, missing = _state(clinic)
    assert seeded == set()
    assert missing[0] == "clinic"
    # And it can all be loaded again.
    assert "clinic" in _load(clinic)["sections"]


def test_the_manifest_keeps_the_clinic_when_a_section_is_added(clinic):
    from app.utils import demo_trace

    _load(clinic)
    with clinic["app"].app_context():
        patients = set(demo_trace.manifest()["patients"])
    _switch(clinic, "dentistry")
    _load(clinic)
    with clinic["app"].app_context():
        plan = demo_trace.manifest()
        assert set(plan["patients"]) == patients
        assert plan.get("dental_plans")


# ------------------------------------------------------------ the screen ----
def _owner(clinic):
    from app.extensions import db
    from app.models import Setting, User

    with clinic["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        boss.is_super_admin = True
        # Otherwise every screen sends the owner to the facility setup, and
        # the page read below would be the redirect.
        Setting.set("facility_configured", "1")
        db.session.commit()
    return clinic["sign_in"]("boss")


def test_the_screen_offers_the_sections_still_missing(clinic):
    client = _owner(clinic)
    client.post("/settings/data/seed-demo")
    reply = client.get("/settings/data")
    assert reply.status_code == 200
    page = reply.get_data(as_text=True)
    assert "data-demo-missing" not in page
    _switch(clinic, "theatres")
    page = client.get("/settings/data").get_data(as_text=True)
    assert 'data-demo-missing="theatres"' in page
    client.post("/settings/data/seed-demo")
    assert _count(clinic, "Operation") == 1
