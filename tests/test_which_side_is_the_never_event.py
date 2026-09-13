"""The last two hand-ticked items on the sign-in: the site, and the blood.

From `docs/gahar/SAS_theatres_matrix.md`, built from the handbook the clinic
uploaded. SAS.06 asks for eight things to be **verified** before the child
goes in, and the matrix's own verdict on what the program had:

> «الـ checklist عندنا بتغطّي (أ) و(ج) و(د) **كخانات بتتعلّم بالإيد**،
> والبرنامج **ما بيتحقّقش من ولا واحدة منهم** … والبند بيقول نفس الحاجة
> بالحرف: *"preoperative **verification**"*»

(ج) was closed when the consent box learned to read the consent. These are
(د) and (و).

**(د) — the site, and this is the never-event.** A box saying «مكان الجراحة
اتعلّم» with no record of *which* site is precisely how a wrong-side operation
ends up with a signature saying it was verified. So the box is answered from a
recorded marking: a side, a place, a name and a time.

**``not_applicable`` is a real answer and the commonest one on a children's
list.** A tonsillectomy has no side. Leaving it out would have people picking
"left" to get past the screen — which is worse than the box it replaced,
because it manufactures a wrong fact instead of an empty one.

**(و) — the blood.** Two facts and not one: whether this case needs blood is
the surgeon's decision, and whether it is in the fridge is the bank's answer.
A single flag would make «محدش سأل» and «مش محتاج» the same, on the one
question where the difference is a child bleeding while somebody telephones.

**And no new checklist item was added**, deliberately: ``missed`` is computed
against the current item list, so adding one would make every checklist ever
signed read as short. Deriving an item that already exists touches only what
is signed from now on.
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
        surgeon = User(username="surg", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        room = Theatre(name="غرفة ١", is_active=True)
        kid = Patient(patient_number="S-1", full_name="طفل عملية",
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=1100))
        clinic["db"].session.add_all([surgeon, room, kid])
        clinic["db"].session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="فتق إربي", on_date=local_today(),
                         surgeon_id=surgeon.id, status="scheduled")
        clinic["db"].session.add(case)
        clinic["db"].session.commit()
        clinic["ids"] = {"case": case.id, "surg": surgeon.id}
    return clinic


def _case(suite):
    from app.models import Operation

    return suite["db"].session.get(Operation, suite["ids"]["case"])


def _user(suite):
    from app.models import User

    return suite["db"].session.get(User, suite["ids"]["surg"])


# ------------------------------------------------------------- the site --
def test_with_nothing_recorded_no_site_is_marked(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        assert theatres.site_state(_case(suite)) == "none"
        assert theatres.site_ok(_case(suite)) is False


def test_a_recorded_side_with_a_name_against_it_is_a_marking(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.mark_site(case, "right", _user(suite), note="الجهة اليمنى")
        suite["db"].session.commit()
        assert theatres.site_state(case) == "marked"
        assert case.site_side == "right"
        assert case.site_note == "الجهة اليمنى"
        assert case.site_marked_by == suite["ids"]["surg"]
        assert case.site_marked_at is not None


def test_not_applicable_counts_as_marked(suite):
    """**The commonest answer on a children's list.** A tonsillectomy has no
    side, and somebody recording that is somebody who considered the question.
    Refusing it would leave people picking "left" to get past the screen."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.mark_site(case, "not_applicable", _user(suite))
        suite["db"].session.commit()
        assert theatres.site_state(case) == "marked"
        assert theatres.site_ok(case) is True


def test_a_side_with_nobody_against_it_is_a_note_not_a_marking(suite):
    """The whole difference between this and the box it replaced is that
    somebody's name is on it."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        case.site_side = "left"          # written straight onto the row
        suite["db"].session.commit()
        assert theatres.site_state(case) == "none"


def test_a_side_nothing_recognises_is_refused(suite):
    """A free-typed side would put the checklist's answer beyond anything the
    program can read — the tick it replaced, wearing a different hat."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        assert theatres.mark_site(case, "شمال شوية", _user(suite)) is None
        assert theatres.mark_site(case, "", _user(suite)) is None
        suite["db"].session.commit()
        assert theatres.site_state(case) == "none"


def test_the_screen_refuses_it_too(suite):
    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/site",
        data={"site_note": "من غير ناحية"}, follow_redirects=True)
    with suite["app"].app_context():
        assert _case(suite).site_side is None

    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/site",
        data={"side": "left", "site_note": "الفتق الشمال"},
        follow_redirects=True)
    with suite["app"].app_context():
        case = _case(suite)
        assert case.site_side == "left"
        assert case.site_marked_by is not None


def test_the_tick_cannot_say_the_site_is_marked_when_nothing_does(suite):
    """The never-event box: ticked by hand, it says a verification happened
    that nobody did."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        row = theatres.sign(_case(suite), SIGN_IN,
                            items=["airway", "site_marked", "allergy"],
                            user=None)
        suite["db"].session.commit()
        assert "site_marked" not in row.items
        assert "site_marked" in row.missed
        assert "allergy" in row.items       # the ordinary ones are untouched


def test_it_ticks_itself_once_the_site_is_recorded(suite):
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.mark_site(case, "right", _user(suite))
        row = theatres.sign(case, SIGN_IN, items=["airway"], user=None)
        suite["db"].session.commit()
        assert "site_marked" in row.items


def test_it_refuses_nothing(suite):
    """A hospital may proceed; the program records rather than blocks."""
    from app.models.theatre import SIGN_IN
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.sign(case, SIGN_IN, items=["airway"], user=None)
        suite["db"].session.commit()
        theatres.start(case, user=None)
        suite["db"].session.commit()
        assert case.status == "in_theatre"
        assert "site_marked" in theatres.safety(case)["missed"][SIGN_IN]


# -------------------------------------------------------------- the blood --
def test_nobody_asked_is_not_none_needed(suite):
    """**The pair that matters.** On this question the difference is a child
    bleeding while somebody telephones."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        assert theatres.blood_state(case) == "unasked"
        theatres.set_blood(case, False)
        suite["db"].session.commit()
        assert theatres.blood_state(case) == "not_needed"


def test_needing_blood_is_not_having_it(suite):
    """Saying blood is needed does not put it in the fridge."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.set_blood(case, True, units=2)
        suite["db"].session.commit()
        assert theatres.blood_state(case) == "ordered"
        assert case.blood_units == 2

        theatres.set_blood(case, True, units=2, reserved=True,
                           user=_user(suite))
        suite["db"].session.commit()
        assert theatres.blood_state(case) == "reserved"
        assert case.blood_reserved_by == suite["ids"]["surg"]


def test_un_needing_blood_clears_the_confirmation(suite):
    """A reservation that outlived the decision it was made for is a
    reservation nobody checked."""
    from app.utils import theatres

    with suite["app"].app_context():
        case = _case(suite)
        theatres.set_blood(case, True, units=2, reserved=True,
                           user=_user(suite))
        suite["db"].session.commit()
        theatres.set_blood(case, False)
        suite["db"].session.commit()
        assert case.blood_reserved_at is None
        assert case.blood_reserved_by is None
        assert theatres.blood_state(case) == "not_needed"


def test_the_screen_refuses_a_blank_blood_answer(suite):
    """Blank read as "no" would make «محدش سأل» and «مش محتاج» one sentence."""
    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/blood",
        data={"units": "2"}, follow_redirects=True)
    with suite["app"].app_context():
        assert _case(suite).blood_needed is None

    suite["sign_in"]("boss").post(
        f"/theatres/operation/{suite['ids']['case']}/blood",
        data={"needed": "yes", "units": "2", "reserved": "1"},
        follow_redirects=True)
    with suite["app"].app_context():
        from app.utils import theatres

        assert theatres.blood_state(_case(suite)) == "reserved"


# ------------------------------------------------ no new item, on purpose --
def test_no_checklist_item_was_added(suite):
    """``missed`` is computed against the **current** item list, so adding one
    would make every checklist ever signed read as short — a record rewritten
    by a release. Deriving an item that already exists touches only what is
    signed from now on."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, TIME_OUT

    assert set(CHECK_ITEMS[SIGN_IN]) == {
        "identity", "site_marked", "consent", "allergy", "airway",
        "anaesthesia_check", "pulse_oximeter"}
    assert "blood" not in CHECK_ITEMS[SIGN_IN]
    assert "blood" not in CHECK_ITEMS[TIME_OUT]


def test_a_stop_signed_before_any_of_this_still_reads_as_it_did(suite):
    """What was stored as confirmed stays confirmed. The derivation changes
    what a *new* signature means, never what an old one said."""
    from app.models.theatre import SIGN_IN, SafetyCheck
    from app.utils import theatres

    with suite["app"].app_context():
        # A row as an older release would have left it.
        row = SafetyCheck(operation_id=suite["ids"]["case"], stop=SIGN_IN,
                          confirmed="identity,site_marked,consent",
                          at=datetime.utcnow())
        suite["db"].session.add(row)
        suite["db"].session.commit()
        assert "site_marked" in row.items
        assert "site_marked" not in row.missed
        assert theatres.site_state(_case(suite)) == "none"   # and truly none


# ------------------------------------------------------------- the screen --
def test_the_screen_draws_both(suite):
    from app.utils import theatres

    with suite["app"].app_context():
        theatres.mark_site(_case(suite), "right", _user(suite),
                           note="الفتق اليمين")
        theatres.set_blood(_case(suite), True, units=1)
        suite["db"].session.commit()

    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{suite['ids']['case']}").get_data(as_text=True)
    assert "الفتق اليمين" in page
    assert "يمين" in page
    assert "مطلوب ولسه ما اتأكّدش" in page
