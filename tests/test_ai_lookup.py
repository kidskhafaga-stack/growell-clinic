"""Asking the program about a child, and getting the register's answer.

The clinic wanted to ask the program anything in it: *"when did so-and-so last
come"*, *"what vaccines has he had"*, *"I need a report for this case addressed
to the school"*.

Those look like one feature and are two, and the split is the whole design.

**The first two are facts.** A visit date and a list of doses are rows. There
is a correct answer and the program is already holding it. Routing them through
a language model converts a certainty into a paraphrase, and a paraphrased date
arrives with exactly the same confidence as a true one — which is how a parent
gets told their child had a vaccine they did not have. So nothing in the lookup
path calls a provider. It reads the register, and when it cannot find the
person it says so instead of choosing which Ahmed was meant.

**The third is language**, and that is the one worth a model — but writing
*from* these rows rather than from its own impression of the conversation. So
the same fact sheet is what gets handed over, under an instruction that names
the record as the only source.

The tests below are mostly about what the lookup refuses to do.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def register(clinic):
    """Three children, two of whom share a first name, and a visit history."""
    with clinic["app"].app_context():
        from app.models import Diagnosis, Patient, User, Visit
        db = clinic["db"]
        ids = {}
        for number, name in (("P-A", "عمر محمد السيد"),
                             ("P-B", "عمر أحمد فؤاد"),
                             ("P-C", "سلمى محمد السيد")):
            person = Patient(patient_number=number, full_name=name,
                             gender="male", date_of_birth=date(2023, 2, 1),
                             is_active=True)
            db.session.add(person)
            db.session.flush()
            ids[number] = person.id

        omar = db.session.get(Patient, ids["P-A"])
        omar.allergies = "بنسلين"
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        for days, complaint in ((90, "كحة"), (30, "حرارة"), (5, "متابعة نمو")):
            visit = Visit(patient_id=omar.id, doctor_id=doctor.id,
                          visit_date=date.today() - timedelta(days=days),
                          chief_complaint=complaint)
            db.session.add(visit)
            db.session.flush()
            db.session.add(Diagnosis(visit_id=visit.id, title="نزلة شعبية",
                                     dx_type="final"))
        db.session.commit()
        clinic["people"] = ids
    return clinic


def test_a_shared_first_name_is_never_resolved_for_you(register):
    """The refusal this feature is built around.

    "عمر" is two children here and would be forty in a real register. A lookup
    that quietly returns the first one will eventually read out the wrong
    child's vaccinations to somebody who has no way to tell — and it will do it
    in the confident voice of a computer. Choosing is a human's job and costs
    one click.
    """
    with register["app"].app_context():
        from app.utils import ai_lookup
        found = ai_lookup.find_patients("عمر")
        assert len(found) == 2
        assert {p.patient_number for p in found} == {"P-A", "P-B"}


def test_nobody_matching_is_an_answer(register):
    """"No record" is true, useful, and better than the nearest name."""
    with register["app"].app_context():
        from app.utils import ai_lookup
        assert ai_lookup.find_patients("زززز") == []


def test_a_one_letter_search_is_not_the_whole_register(register):
    """A stray keystroke must not return everybody and look like a match."""
    with register["app"].app_context():
        from app.utils import ai_lookup
        assert ai_lookup.find_patients("ع") == []
        assert ai_lookup.find_patients("") == []


def test_when_they_last_came_is_a_date_from_the_register(register):
    """The first question the clinic asked for, answered exactly."""
    with register["app"].app_context():
        from app.models import Patient
        from app.utils import ai_lookup
        omar = register["db"].session.get(Patient, register["people"]["P-A"])
        data = ai_lookup.facts(omar)
        assert data["visits_total"] == 3
        assert data["last_visit"].visit_date == date.today() - timedelta(days=5)
        assert data["days_since_last"] == 5


def test_a_child_who_has_never_attended_is_said_so_not_left_blank(register):
    """An empty field reads as "unknown"; this has to read as "never came"."""
    with register["app"].app_context():
        from app.models import Patient
        from app.utils import ai_lookup
        never = register["db"].session.get(Patient, register["people"]["P-C"])
        data = ai_lookup.facts(never)
        assert data["visits_total"] == 0
        assert data["last_visit"] is None
        assert data["days_since_last"] is None


def test_the_lookup_calls_no_provider(register):
    """The property that makes the answers trustworthy, asserted directly.

    With ``chat`` replaced by something that fails loudly, the whole lookup
    still works. That is what lets this screen stay useful with the assistant
    switched off, on a clinic with no key and no credit — and it is why a date
    from here cannot be a plausible invention.
    """
    with register["app"].app_context():
        from app.models import Patient
        from app.utils import ai, ai_lookup

        original = ai.chat

        def forbidden(*args, **kwargs):
            raise AssertionError("the lookup must not call a provider")

        ai.chat = forbidden
        try:
            omar = register["db"].session.get(Patient, register["people"]["P-A"])
            data = ai_lookup.facts(omar)
            assert data["visits_total"] == 3
            assert ai_lookup.find_patients("سلمى")
        finally:
            ai.chat = original


def test_the_screen_shows_the_choice_rather_than_picking(register):
    """The refusal above, as the doctor meets it."""
    body = (register["sign_in"]("doc").get("/ai/lookup?q=عمر")
            .get_data(as_text=True))
    assert "مين فيهم؟" in body
    assert "P-A" in body and "P-B" in body


def test_an_unambiguous_name_goes_straight_to_the_answer(register):
    """One match is not a choice, and making somebody click it is friction."""
    body = (register["sign_in"]("doc").get("/ai/lookup?q=سلمى")
            .get_data(as_text=True))
    assert "مين فيهم؟" not in body
    assert "مجاش قبل كده" in body


def test_the_screen_says_where_its_answers_come_from(register):
    """Because the page lives under a menu called "artificial intelligence".

    Somebody reading a date on this screen has every reason to assume a model
    produced it. The subtitle exists to say otherwise, and it is load-bearing
    rather than decorative: it is the difference between a date the clinic
    acts on and a date it double-checks.
    """
    body = (register["sign_in"]("doc").get("/ai/lookup?q=سلمى")
            .get_data(as_text=True))
    assert "من دفاتر العيادة نفسها" in body


def test_the_fact_sheet_handed_to_the_model_carries_the_prohibition(register):
    """What the letter-writing request is allowed to be built from.

    "Write a report for the school" is the request most likely to tempt a model
    into rounding a date or supplying a plausible dose. The instruction is
    stated as a prohibition, not a preference, and the record is named as the
    only source.
    """
    with register["app"].app_context():
        from app.models import Patient
        from app.utils import ai_lookup
        omar = register["db"].session.get(Patient, register["people"]["P-A"])
        sheet = ai_lookup.fact_sheet(ai_lookup.facts(omar))
        assert "Visits on record: 3" in sheet
        assert "بنسلين" in sheet
        assert "never estimate, infer or fill in" in ai_lookup.SYSTEM
        assert "Answer only from it" in ai_lookup.SYSTEM


def test_anonymising_removes_the_name_from_what_is_sent(register):
    """The clinic's privacy switch has to reach this path too.

    The fact sheet is a new way for a record to leave the building, so it
    honours the same setting the older patient summary did — otherwise turning
    anonymisation on would quietly stop covering everything.
    """
    with register["app"].app_context():
        from app.models import Patient
        from app.utils import ai_lookup
        omar = register["db"].session.get(Patient, register["people"]["P-A"])
        data = ai_lookup.facts(omar)
        hidden = ai_lookup.fact_sheet(data, anonymize=True)
        shown = ai_lookup.fact_sheet(data, anonymize=False)
        assert "عمر محمد السيد" not in hidden
        assert "P-A" not in hidden
        assert "عمر محمد السيد" in shown


def test_the_assistant_is_not_offered_when_sharing_is_switched_off(register):
    """Reading a record here and posting it to a vendor are different acts.

    The lookup itself keeps working — it never left the building — but the
    button that would carry this child into a chat is absent, and the screen
    says why rather than leaving somebody hunting for it.
    """
    body = (register["sign_in"]("doc").get("/ai/lookup?q=سلمى")
            .get_data(as_text=True))
    assert "اسأل المساعد عن الحالة دي" not in body
    assert "مشاركة بيانات المرضى مقفولة" in body
