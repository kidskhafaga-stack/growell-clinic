"""Two things a fresh copy got wrong, both spotted from the setup screen.

> «انا دلوقتى اختر الحجات دي — ليه الأدوية والروشتة مش متعلّمة؟ بديهي لو
> دكتور واحد وعنده عيادة هيحتاج أكيد الروشتة والأدوية … وطبعاً "Growell
> clinic" هيبقى مش حلو، خليها بأسم البرنامج»

**١ — the wizard switched the prescription writer off.**

``prescriptions`` is not an opt-in specialty. It ships *on*, like the rest of
the paediatric core. But the enabled set is computed as
``BASE_MODULES`` + whatever the ticked capabilities bring, and it was in
neither — so a single-doctor clinic ticking "general consultation" and
pressing Start **lost the screen its doctor uses every visit**.

Not a missing tick: a working feature turned off by the screen that exists to
set the program up. And writing a prescription is not a specialty — it is
what a consultation *is*. The pharmacy capability is the other question and
stays where it is: a counter, a queue and a handover are a clinic dispensing
its own medicines, which a clinic whose families fill outside does not do —
while still writing the paper.

**٢ — every fresh copy came up wearing one particular clinic's sign.**

``clinic_name`` defaulted to «GROWELL CLINIC». That is a customer, not the
program: the software is PediaPro, and `product_name` already says so. So a
new install printed somebody else's name on its receipts until whoever set it
up noticed.

And the fix must rename nobody: the seeder only writes a key that is missing,
so a clinic that has set its own name keeps it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def fresh():
    """A database with nothing in it — the state a new install starts from."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
    return {"app": app, "db": db}


# ------------------------------------- the writer the wizard switched off --
def test_a_single_doctor_clinic_keeps_its_prescriptions(fresh):
    """**The report, reproduced.** Tick what a one-doctor clinic ticks, press
    Start, and the screen the doctor uses every visit must still be there."""
    from app.utils.facility import derive_modules

    with fresh["app"].app_context():
        # What the wizard writes when Start is pressed on the screen in the
        # report: the four clinical services a one-doctor clinic ticks.
        enabled = derive_modules(["general_consultation", "followup",
                                  "vaccination", "growth_monitoring"])
        assert "prescriptions" in enabled


def test_writing_one_is_not_a_specialty(fresh):
    """It is in the base set, so **every** facility keeps it — not only the
    ones that happen to tick something that drags it along."""
    from app.utils.facility import BASE_MODULES, derive_modules

    assert "prescriptions" in BASE_MODULES
    with fresh["app"].app_context():
        # The barest possible clinic: one capability, nothing else.
        assert "prescriptions" in derive_modules(["general_consultation"])
        # …and even one that ticked nothing at all.
        assert "prescriptions" in derive_modules([])


def test_it_is_not_an_opt_in_module(fresh):
    """Which is what made the old behaviour a *loss*: the module ships on, so
    the wizard was not declining to add it — it was taking it away."""
    from app.utils.facility import OPT_IN_MODULES

    assert "prescriptions" not in OPT_IN_MODULES


def test_the_pharmacy_counter_is_still_its_own_decision(fresh):
    """The two are different questions and stay different. A clinic whose
    families fill their prescriptions outside writes them and dispenses
    nothing."""
    from app.utils.facility import derive_modules

    with fresh["app"].app_context():
        writes_only = derive_modules(["general_consultation"])
        assert "prescriptions" in writes_only
        assert "pharmacy" not in writes_only

        dispenses = derive_modules(["general_consultation", "pharmacy"])
        assert "pharmacy" in dispenses


def test_a_hospital_keeps_it_too(fresh):
    from app.utils.facility import FACILITY_TYPES, derive_modules

    with fresh["app"].app_context():
        assert "prescriptions" in derive_modules(
            FACILITY_TYPES["hospital"]["caps"])


# --------------------------------------------- whose name is on the door --
def test_a_fresh_copy_wears_the_programs_name(fresh):
    """«GROWELL CLINIC» is a customer. The software is PediaPro, and
    `product_name` already said so."""
    from app.cli import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["clinic_name"] == "PediaPro"
    assert DEFAULT_SETTINGS["clinic_name_ar"] == "PediaPro"
    assert "GROWELL" not in str(DEFAULT_SETTINGS.values()).upper()


def test_seeding_renames_nobody(fresh):
    """The whole risk of this change, and the thing that makes it safe: a
    clinic that has set its own name must keep it."""
    from app.cli import _ensure_default_settings
    from app.models import Setting

    with fresh["app"].app_context():
        Setting.set("clinic_name", "عيادة الدكتور خفاجة")
        fresh["db"].session.commit()

        _ensure_default_settings()
        fresh["db"].session.commit()
        assert Setting.query.filter_by(
            key="clinic_name").first().value == "عيادة الدكتور خفاجة"


def test_the_default_only_fills_what_is_missing(fresh):
    from app.cli import _ensure_default_settings
    from app.models import Setting

    with fresh["app"].app_context():
        # Read the row, not ``Setting.get`` — that caches per request, so
        # asking before and after in one context answers from the first read.
        assert Setting.query.filter_by(key="clinic_name").first() is None
        _ensure_default_settings()
        fresh["db"].session.commit()
        assert Setting.query.filter_by(
            key="clinic_name").first().value == "PediaPro"
