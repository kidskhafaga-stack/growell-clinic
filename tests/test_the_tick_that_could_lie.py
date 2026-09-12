"""The consent item on the surgical checklist, answered by the document.

Reported in one sentence, and it names the whole defect:

> «الإقرارات موجودة وموقّعة من ولي الأمر، بس بند «الموافقة» في الـ checklist
> بيتعلّم بالإيد حتى لو مفيش إقرار متسجّل»

Consents were built, signed, scanned and withdrawable. The surgical checklist
was built, with three stops and a refusal to start without the first. And
between them: a tick. The one item on that list a family's signature is
supposed to answer was a box anybody could check, and a checklist that can say
a family consented when nothing does is worse than no checklist — it produces
a signed record saying it was verified.

Four decisions:

**The item is read, not taken.** ``sign`` drops it from whatever the form
posted and answers it from the record, in both directions: ticked when a
signed standing consent is linked even if nobody thought to tick it, dropped
when none is however firmly somebody did.

**Linked by a person, never matched by the program.** It does not know what
the guardian was told, and deciding that a «procedure» consent from March
covers September's tonsillectomy would manufacture exactly the false green
tick this removes.

**Five states, not a boolean.** none · unsigned · withdrawn · expired ·
linked. They are five different conversations at the theatre door, and a
boolean tells whoever is holding the knife that something is wrong without
saying what.

**And it refuses nothing.** The stop can still be signed — a hospital may
proceed and this program records rather than blocks — but the gap then shows
as a finding instead of a green tick.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def suite(clinic):
    """A theatre, a child, and a case waiting to be signed in."""
    from app.models import Operation, Patient, Setting, Theatre, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        Setting.set("mod_enabled:theatres", "1")
        surgeon = User(username="surg", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        room = Theatre(name="غرفة ١", is_active=True)
        kid = Patient(patient_number="C-1", full_name="طفل إقرار",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1400))
        clinic["db"].session.add_all([surgeon, room, kid])
        clinic["db"].session.flush()

        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="استئصال لوز", on_date=local_today(),
                         surgeon_id=surgeon.id, status="scheduled")
        clinic["db"].session.add(case)
        clinic["db"].session.commit()
        clinic["ids"] = {"kid": kid.id, "case": case.id, "room": room.id,
                         "surgeon": surgeon.id}
    return clinic


def _consent(suite, signed=True, withdrawn=False, valid_until=None,
             ctype="procedure", patient_id=None, signed_date=None):
    from app.models import Consent
    from app.utils.clock import local_today

    with suite["app"].app_context():
        row = Consent(patient_id=patient_id or suite["ids"]["kid"],
                      consent_type=ctype, guardian_name="والد الطفل",
                      signed_date=signed_date or local_today(),
                      valid_until=valid_until)
        if signed:
            row.signature_file = "sig.png"
            row.signature_kind = "paper"
            row.signature_at = datetime.utcnow()
        if withdrawn:
            row.withdrawn_at = datetime.utcnow()
            row.withdrawn_reason = "غيّروا رأيهم"
        suite["db"].session.add(row)
        suite["db"].session.commit()
        return row.id


def _case(suite):
    from app.models import Operation

    return suite["db"].session.get(Operation, suite["ids"]["case"])


def _link(suite, consent_id):
    with suite["app"].app_context():
        _case(suite).consent_id = consent_id
        suite["db"].session.commit()


# ------------------------------------------------------------ five states --
def test_no_consent_at_all_reads_as_none(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "none"
        assert theatres.consent_ok(_case(suite)) is False


def test_a_consent_nobody_signed_is_not_a_consent(suite):
    """A row carrying a guardian's name and nothing else is a claim that
    somebody agreed. The signature is the only part of it that is evidence."""
    from app.utils import theatres

    _link(suite, _consent(suite, signed=False))
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "unsigned"


def test_a_withdrawn_consent_reads_as_withdrawn(suite):
    from app.utils import theatres

    _link(suite, _consent(suite, withdrawn=True))
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "withdrawn"


def test_an_expired_consent_is_judged_against_the_day_of_the_operation(suite):
    """A case reviewed a week later must read as it read on the morning it
    happened — not against the day somebody opened the screen."""
    from app.utils import theatres
    from app.utils.clock import local_today

    _link(suite, _consent(suite,
                          valid_until=local_today() - timedelta(days=1)))
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "expired"

        # Same document, a case that happened while it still stood.
        case = _case(suite)
        case.on_date = local_today() - timedelta(days=3)
        suite["db"].session.commit()
        assert theatres.consent_state(case) == "linked"


def test_a_consent_with_no_expiry_recorded_stands(suite):
    """Every consent signed before the column has NULL there, and treating
    that as expired would retroactively invalidate documents that were valid
    when they were taken."""
    from app.utils import theatres

    _link(suite, _consent(suite, valid_until=None))
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "linked"


def test_a_signed_standing_consent_reads_as_linked(suite):
    from app.utils import theatres
    from app.utils.clock import local_today

    _link(suite, _consent(suite,
                          valid_until=local_today() + timedelta(days=30)))
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "linked"
        assert theatres.consent_ok(_case(suite)) is True


# -------------------------------------------- the item is read, not taken --
def test_the_tick_cannot_say_yes_when_nothing_does(suite):
    """**The defect, in one test.** Somebody ticks the box with no consent on
    file, and the checklist must not agree with them."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        row = theatres.sign(_case(suite), SIGN_IN,
                            items=["identity", "consent", "allergy"],
                            user=None)
        suite["db"].session.commit()
        assert "consent" not in row.items
        assert "consent" in row.missed
        # …and what was genuinely ticked is untouched.
        assert "identity" in row.items and "allergy" in row.items


def test_the_tick_says_yes_when_the_record_does_even_unticked(suite):
    """Read in both directions: a nurse who signs the stop without touching
    that box has not thereby unsaid a consent the file holds."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    _link(suite, _consent(suite))
    with suite["app"].app_context():
        row = theatres.sign(_case(suite), SIGN_IN, items=["identity"],
                            user=None)
        suite["db"].session.commit()
        assert "consent" in row.items
        assert "consent" not in row.missed


def test_an_unsigned_consent_does_not_tick_it(suite):
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    _link(suite, _consent(suite, signed=False))
    with suite["app"].app_context():
        row = theatres.sign(_case(suite), SIGN_IN, items=["consent"],
                            user=None)
        suite["db"].session.commit()
        assert "consent" in row.missed


def test_the_stop_is_still_signable_and_the_case_still_starts(suite):
    """**It refuses nothing.** A hospital may proceed; this program records
    rather than blocks. What it will not do is call the gap a green tick."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.sign(case, SIGN_IN, items=["identity", "consent"], user=None)
        suite["db"].session.commit()
        theatres.start(case, user=None)
        suite["db"].session.commit()
        assert case.status == "in_theatre"
        assert "consent" in theatres.safety(case)["missed"][SIGN_IN]


def test_the_other_stops_are_untouched(suite):
    """Only the item a signature answers is read from the record; the rest of
    the checklist is the team's own to tick."""
    from app.models.theatre import TIME_OUT
    from app.utils import theatres

    with suite["app"].app_context():
        row = theatres.sign(_case(suite), TIME_OUT,
                            items=["team_introduced", "antibiotic"],
                            user=None)
        suite["db"].session.commit()
        assert set(row.items) == {"team_introduced", "antibiotic"}


# ------------------------------------------------------------- the linking --
def test_the_program_never_guesses_which_document_covers_the_case(suite):
    """A signed «procedure» consent sitting on the file changes nothing until
    somebody says it covers *this* case: the program does not know what the
    guardian was told."""
    from app.utils import theatres

    _consent(suite)                      # on file, signed, and unlinked
    with suite["app"].app_context():
        assert theatres.consent_state(_case(suite)) == "none"


def test_the_picker_shows_the_unsigned_ones_too(suite):
    """Hiding them would turn a visible problem into an empty list — the
    person linking has to see that the document is unsigned."""
    from app.utils import theatres

    good = _consent(suite)
    bare = _consent(suite, signed=False)
    gone = _consent(suite, withdrawn=True)
    with suite["app"].app_context():
        offered = {c.id for c in theatres.consent_choices(_case(suite))}
        assert good in offered and bare in offered
        assert gone not in offered      # withdrawn is not a choice


def test_another_childs_consent_cannot_be_linked(suite):
    """A posted id is a number anybody can type, and this one answers a
    surgical safety item."""
    from app.models import Patient
    from app.utils.clock import local_today

    with suite["app"].app_context():
        other = Patient(patient_number="C-2", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=900))
        suite["db"].session.add(other)
        suite["db"].session.commit()
        other_id = other.id
    theirs = _consent(suite, patient_id=other_id)

    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/consent",
        data={"consent_id": str(theirs)}, follow_redirects=True)
    with suite["app"].app_context():
        assert _case(suite).consent_id is None


def test_linking_and_unlinking_from_the_screen(suite):
    from app.utils import theatres

    mine = _consent(suite)
    client = suite["sign_in"]("boss")
    client.post(f"/theatres/operation/{suite['ids']['case']}/consent",
                data={"consent_id": str(mine)}, follow_redirects=True)
    with suite["app"].app_context():
        assert _case(suite).consent_id == mine
        assert theatres.consent_state(_case(suite)) == "linked"

    client.post(f"/theatres/operation/{suite['ids']['case']}/consent",
                data={"consent_id": ""}, follow_redirects=True)
    with suite["app"].app_context():
        assert _case(suite).consent_id is None


def test_the_screen_says_which_of_the_five_it_is(suite):
    """A boolean would tell whoever is holding the knife that something is
    wrong without telling them what."""
    _link(suite, _consent(suite, signed=False))
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{suite['ids']['case']}").get_data(as_text=True)
    assert "من غير توقيع" in page

    _link(suite, _consent(suite))
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{suite['ids']['case']}").get_data(as_text=True)
    assert "مربوط وموقّع" in page


def test_a_child_with_no_consents_gets_told_so(suite):
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{suite['ids']['case']}").get_data(as_text=True)
    assert "مفيش إقرارات في ملف الطفل" in page
