"""The anaesthetic half: the look in the anaesthetic room, and the plan.

Two things the standard the clinic works to asks for by name, and the program
had neither. From `docs/gahar/SAS_theatres_matrix.md`, built from the
handbook the clinic uploaded:

> *"A qualified anesthesiologist performs pre-anesthesia and **pre-induction**
> assessment and plans for anesthesia care."* — SAS.16

**EOC 5 — the second assessment.** Two looks, not one: «ما قبل التخدير» days
ahead, and «ما قبل الاستحثاث» immediately before the anaesthetic. The program
had the first, and for the second it had a checklist box somebody ticked on
the way past — the same defect the consent item had, in the next seat.

**EOC 2 — the plan, with six named elements.** The program had a verdict and a
box of free text, which is a note and not a plan: it cannot say whether the
airway was thought about, and an auditor reading it a year later cannot
either.

What these hold:

**The headings are the standard's; every word under them is the
anaesthetist's.** A program that filled in a dose would be inventing a
clinical number, which this one does not do.

**"Stale" is a state.** An assessment from yesterday is not an assessment made
immediately before induction, and counting it would have the record claim
somebody looked at this child this morning.

**And a third review kind is not a third thing for the pre-op queue to wait
for.** The queue clears days ahead; a pre-induction assessment cannot be made
days ahead. One list had been quietly doing both jobs.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def suite(clinic):
    """A theatre and a case listed for today."""
    from app.models import Operation, Patient, Setting, Theatre, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:theatres", "1")
        gas = User(username="gas", full_name="د. مخدّر", role="doctor",
                   is_active=True)
        gas.set_password("secret")
        room = Theatre(name="غرفة ١", is_active=True)
        kid = Patient(patient_number="A-1", full_name="طفل تخدير",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1200))
        clinic["db"].session.add_all([gas, room, kid])
        clinic["db"].session.flush()

        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="استئصال لوز", on_date=local_today(),
                         anaesthetist_id=gas.id, status="scheduled")
        clinic["db"].session.add(case)
        clinic["db"].session.commit()
        clinic["ids"] = {"case": case.id, "gas": gas.id, "kid": kid.id}
    return clinic


def _case(suite):
    from app.models import Operation

    return suite["db"].session.get(Operation, suite["ids"]["case"])


# ------------------------------------------- the look in the anaesthetic room --
def test_with_nothing_recorded_there_is_no_assessment(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        assert theatres.pre_induction_state(_case(suite)) == "none"
        assert theatres.pre_induction_ok(_case(suite)) is False


def test_an_assessment_made_today_counts(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.review(_case(suite), "pre_induction", "fit")
        suite["db"].session.commit()
        assert theatres.pre_induction_state(_case(suite)) == "done"


def test_yesterdays_assessment_is_stale_not_an_assessment(suite):
    """**The one a boolean would hide.** The standard asks for a look
    *immediately before induction*. A case put off to the next day has one
    that was true yesterday, and counting it would have the record claim
    somebody looked at this child this morning."""
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.review(_case(suite), "pre_induction", "fit",
                        at=datetime.utcnow() - timedelta(days=1))
        suite["db"].session.commit()
        assert theatres.pre_induction_state(_case(suite)) == "stale"
        assert theatres.pre_induction_ok(_case(suite)) is False


def test_fit_with_conditions_is_still_an_assessment(suite):
    """"Fit, once the chest is clear" is a look that was made and a condition
    that was named — which is the whole reason that verdict exists.

    Asserted all the way to the checklist, not only to the state: a mutation
    that accepted the state and then demanded a bare ``fit`` before ticking
    the box slipped past a test that stopped at the first.
    """
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.review(case, "pre_induction", "conditions",
                        note="بعد ما الصدر يصفى")
        suite["db"].session.commit()
        assert theatres.pre_induction_state(case) == "done"
        assert theatres.pre_induction_ok(case) is True
        row = theatres.sign(case, SIGN_IN, items=["identity"], user=None)
        suite["db"].session.commit()
        assert "anaesthesia_check" in row.items


def test_not_fit_is_named_as_such(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.review(_case(suite), "pre_induction", "unfit",
                        note="التهاب صدر")
        suite["db"].session.commit()
        assert theatres.pre_induction_state(_case(suite)) == "unfit"
        assert theatres.pre_induction_ok(_case(suite)) is False


# ------------------------------------------------ the item is read, not ticked --
def test_the_anaesthetic_tick_cannot_say_yes_when_nothing_does(suite):
    """The consent defect in the next seat: a box ticked on the way past,
    where the standard asks for an assessment."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        row = theatres.sign(_case(suite), SIGN_IN,
                            items=["identity", "anaesthesia_check", "airway"],
                            user=None)
        suite["db"].session.commit()
        assert "anaesthesia_check" not in row.items
        assert "anaesthesia_check" in row.missed
        assert "airway" in row.items       # the ordinary ones are untouched


def test_it_ticks_itself_when_the_assessment_is_there(suite):
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.review(_case(suite), "pre_induction", "fit")
        row = theatres.sign(_case(suite), SIGN_IN, items=["identity"],
                            user=None)
        suite["db"].session.commit()
        assert "anaesthesia_check" in row.items


def test_a_stale_assessment_does_not_tick_it(suite):
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.review(_case(suite), "pre_induction", "fit",
                        at=datetime.utcnow() - timedelta(days=2))
        row = theatres.sign(_case(suite), SIGN_IN,
                            items=["anaesthesia_check"], user=None)
        suite["db"].session.commit()
        assert "anaesthesia_check" in row.missed


def test_it_refuses_nothing(suite):
    """A hospital may proceed; the program records rather than blocks. What it
    will not do is call the gap a green tick."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.sign(case, SIGN_IN, items=["identity"], user=None)
        suite["db"].session.commit()
        theatres.start(case, user=None)
        suite["db"].session.commit()
        assert case.status == "in_theatre"
        assert "anaesthesia_check" in theatres.safety(case)["missed"][SIGN_IN]


# ------------------------------------------ a third kind is not a third queue --
def test_the_preop_queue_does_not_wait_for_the_anaesthetic_room(suite):
    """**The error the suite caught.** ``REVIEW_KINDS`` had been doing two
    jobs — naming every kind, and naming what the pre-op queue waits for.
    Adding a third kind to the first changed the second, and the queue stopped
    clearing: a pre-induction assessment cannot be made days ahead."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.review(case, "surgeon", "fit")
        theatres.review(case, "anaesthesia", "fit")
        suite["db"].session.commit()
        assert theatres.unreviewed() == []


def test_the_two_lists_say_different_things(suite):
    from app.models import PREOP_KINDS, REVIEW_KINDS

    assert "pre_induction" in REVIEW_KINDS
    assert "pre_induction" not in PREOP_KINDS
    assert set(PREOP_KINDS) < set(REVIEW_KINDS)


# ------------------------------------------------------------- the six of them --
def test_the_plan_has_the_six_the_standard_names(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        plan = theatres.write_plan(
            _case(suite), None,
            kind="general",
            induction="بروبوفول ٢ مجم/كجم وريدي — ٨:٠٥",
            airway="أنبوبة ٤٫٥ مع بالون",
            fluids="عجز ٣٠٠ · صيانة ٦٠/س · ميزان +١٠٠ · رينجر",
            given_during="فنتانيل ١ ميكروجرام/كجم — ٨:٢٠",
            events="مفيش")
        suite["db"].session.commit()

        assert plan.kind == "general"
        assert "بروبوفول" in plan.induction
        assert "٤٫٥" in plan.airway
        assert "رينجر" in plan.fluids
        assert "فنتانيل" in plan.given_during
        assert plan.events == "مفيش"
        assert plan.missing == []
        assert plan.is_planned is True


def test_the_four_that_belong_before_the_case_are_the_ones_counted(suite):
    """The last two are an account of what happened, so an empty one before
    induction is not a gap — and a screen that called it one would be crying
    wolf on every case."""
    from app.utils import theatres

    with suite["app"].app_context():
        plan = theatres.write_plan(_case(suite), None, kind="general",
                                   induction="بروبوفول", airway="أنبوبة",
                                   fluids="رينجر")
        suite["db"].session.commit()
        assert plan.given_during is None and plan.events is None
        assert plan.missing == []


def test_what_nobody_wrote_is_named_not_counted(suite):
    """Six empty boxes and a green tick is the checklist problem in another
    shape."""
    from app.utils import theatres

    with suite["app"].app_context():
        plan = theatres.write_plan(_case(suite), None, kind="general",
                                   induction="بروبوفول")
        suite["db"].session.commit()
        assert plan.missing == ["airway", "fluids"]
        assert plan.is_planned is False


def test_whitespace_is_not_an_answer(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        plan = theatres.write_plan(_case(suite), None, kind="general",
                                   induction="   ", airway="أنبوبة",
                                   fluids="رينجر")
        suite["db"].session.commit()
        assert plan.induction is None
        assert "induction" in plan.missing


def test_blank_means_blank_whoever_wrote_the_row(suite):
    """``missing`` is the model's own contract, not a courtesy of one writer.

    ``write_plan`` trims to ``None``, so a mutation reading ``is None``
    instead of stripping passed everywhere — until something else writes the
    row. An import, a correction by hand, or the next writer somebody adds is
    exactly that something else.
    """
    from app.models import AnaesthesiaPlan

    with suite["app"].app_context():
        row = AnaesthesiaPlan(operation_id=suite["ids"]["case"],
                              kind="general", induction="بروبوفول",
                              airway="   ", fluids="\n\t ")
        suite["db"].session.add(row)
        suite["db"].session.commit()
        assert row.missing == ["airway", "fluids"]
        assert row.is_planned is False


def test_a_kind_of_anaesthetic_nothing_recognises_is_not_stored(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        plan = theatres.write_plan(_case(suite), None, kind="مخترع",
                                   induction="بروبوفول")
        suite["db"].session.commit()
        assert plan.kind is None
        assert "kind" in plan.missing


def test_writing_it_again_corrects_the_one_plan(suite):
    """A second plan would leave two accounts of the same anaesthetic and no
    way to say which was followed."""
    from app.models import AnaesthesiaPlan
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.write_plan(case, None, kind="general", induction="أول")
        suite["db"].session.commit()
        theatres.write_plan(case, None, kind="regional", induction="تاني")
        suite["db"].session.commit()

        assert AnaesthesiaPlan.query.count() == 1
        plan = theatres.plan_for(_case(suite))
        assert plan.kind == "regional" and plan.induction == "تاني"


def test_a_case_with_no_plan_says_so(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        assert theatres.plan_for(_case(suite)) is None


# ------------------------------------------------------------------ the screen --
def test_the_screen_draws_both(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.write_plan(_case(suite), None, kind="general",
                            induction="بروبوفول")
        suite["db"].session.commit()

    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{suite['ids']['case']}").get_data(as_text=True)
    assert "بروبوفول" in page
    assert "مفيش تقييم قبل الاستحثاث" in page      # the state, named
    assert "ناقص في الخطة" in page                 # and the gaps, named


def test_the_plan_saves_from_the_screen(suite):
    from app.utils import theatres

    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/plan",
        data={"kind": "general", "induction": "بروبوفول ٢ مجم/كجم",
              "airway": "أنبوبة ٤٫٥", "fluids": "رينجر"},
        follow_redirects=True)
    with suite["app"].app_context():
        plan = theatres.plan_for(_case(suite))
        assert plan is not None and plan.is_planned
