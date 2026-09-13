"""The results this case waits on — and the word carrying all the weight.

GAHAR SAS.06 (هـ) asks for the results of the **required** investigations
before the child goes in. ``VisitInvestigation`` was already here, with a
bench flow, a sample, a number and a range. What was missing was one link: no
order knew which operation it belonged to, so the checklist's «الأشعة معروضة»
was a box somebody ticked, and a lab result nobody had read was invisible to
the screen where somebody decides whether this child is ready.

**The program does not decide which tests a procedure requires.** Naming them
is a clinical judgement, and inventing one here is the failure the vaccine
tables exist to avoid. So a person attaches the orders and the program reads
the answer off them.

That also rules out the shortcut that looks equivalent and is not: reading
every outstanding order on the child's file. A ferritin somebody asked for
last month would then hold up this morning's appendix.

Four decisions this file pins down:

* **Five states, not a boolean.** ``unasked`` · ``not_needed`` ·
  ``none_named`` · ``waiting`` · ``ready``. *Nobody asked* and *waiting on
  nothing* are two different mornings, and "yes, and nothing named" is half an
  answer that must look like one.
* **No new checklist item.** ``imaging_ready`` was already on the time-out, and
  it is the same question. Adding an item would make every checklist ever
  signed read as short — a record rewritten by a release.
* **The imaging box ticks when there is nothing to show.** A case with no
  imaging has none to display; painting it red on every appendicectomy teaches
  people to stop reading the colour. It only withholds the tick where imaging
  was ordered *for this case* and is not back.
* **Detaching never deletes.** The order is a request somebody really made,
  and being on the wrong case is not a reason to lose it.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def surgical():
    """A child with a case booked, and a second child to prove the fence."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User, Visit
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        surgeon = User(username="cutter", full_name="د. الجرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        room = Theatre(name="غرفة ١", sort_order=1)
        db.session.add_all([surgeon, room])
        db.session.flush()

        ids = {"surgeon": surgeon.id, "room": room.id}
        for key, name in (("child", "طفل الحالة"), ("other", "طفل تاني")):
            kid = Patient(patient_number=f"P-{key}", full_name=name,
                          gender="male", is_active=True,
                          date_of_birth=local_today() - timedelta(days=1500))
            db.session.add(kid)
            db.session.flush()
            visit = Visit(patient_id=kid.id, doctor_id=surgeon.id,
                          visit_date=local_today())
            db.session.add(visit)
            db.session.flush()
            ids[key] = kid.id
            ids[key + "_visit"] = visit.id

        case = Operation(patient_id=ids["child"], theatre_id=room.id,
                         procedure="استئصال زائدة", on_date=local_today(),
                         surgeon_id=surgeon.id, status="scheduled")
        # A **second case on the same child** — a staged procedure, which is
        # ordinary in paediatric surgery. It exists so that "an order already
        # attached to another case" is a state a test can build: without it,
        # the fence around ``workup_choices`` could be removed and nothing
        # failed.
        second = Operation(patient_id=ids["child"], theatre_id=room.id,
                           procedure="مرحلة تانية",
                           on_date=local_today() + timedelta(days=14),
                           surgeon_id=surgeon.id, status="scheduled")
        db.session.add_all([case, second])
        db.session.commit()
        ids["case"], ids["second"] = case.id, second.id

    def sign_in(username="cutter"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _order(ctx, kind="lab", name="صورة دم", resulted=False, who="child"):
    from app.models.visit import VisitInvestigation

    with ctx["app"].app_context():
        row = VisitInvestigation(visit_id=ctx["ids"][who + "_visit"],
                                 patient_id=ctx["ids"][who], kind=kind,
                                 name=name, status="requested")
        if resulted:
            row.result_text = "طبيعي"
            row.status = "resulted"
        ctx["db"].session.add(row)
        ctx["db"].session.commit()
        return row.id


def _case(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["case"])


def _get(ctx, order_id):
    from app.models.visit import VisitInvestigation
    return ctx["db"].session.get(VisitInvestigation, order_id)


# ------------------------------------------------------------ five states --
def test_a_case_nobody_has_asked_about_reads_as_unasked(surgical):
    """Every case booked before this column. Not the same as needing
    nothing — which is the whole reason the column is nullable."""
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "unasked"


def test_waiting_on_nothing_is_a_recorded_answer(surgical):
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        theatre.set_workup(_case(surgical), False)
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "not_needed"


def test_unasked_and_not_needed_are_not_the_same_state(surgical):
    """**The pair this file exists for.** One NULL standing for both is the
    bug this program keeps finding, and here the difference is a child
    anaesthetised before anybody read a result."""
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "unasked"
        theatre.set_workup(_case(surgical), False)
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "not_needed"


def test_yes_with_nothing_named_is_half_an_answer_and_looks_like_one(surgical):
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        theatre.set_workup(_case(surgical), True)
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "none_named"


def test_an_attached_order_with_no_result_is_waiting(surgical):
    from app.utils import theatres as theatre

    order = _order(surgical)
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "waiting"


def test_it_is_ready_only_when_every_one_of_them_is_back(surgical):
    """One result back out of two is not ready, and that is the case the
    whole item exists for."""
    from app.utils import theatres as theatre

    done = _order(surgical, name="صورة دم", resulted=True)
    pending = _order(surgical, name="وظائف كبد")
    with surgical["app"].app_context():
        case = _case(surgical)
        theatre.link_investigation(case, _get(surgical, done))
        theatre.link_investigation(case, _get(surgical, pending))
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "waiting"

    with surgical["app"].app_context():
        _get(surgical, pending).result_text = "طبيعي"
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "ready"


# ----------------------------------------------- only this case's orders --
def test_another_order_on_the_same_child_does_not_hold_the_case_up(surgical):
    """**The shortcut that looks equivalent.** Reading every outstanding order
    on the file would have a ferritin from last month hold up this morning's
    appendix."""
    from app.utils import theatres as theatre

    attached = _order(surgical, name="صورة دم", resulted=True)
    _order(surgical, name="فيريتين")          # ordered, never attached
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, attached))
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "ready"
        assert len(theatre.workup_orders(_case(surgical))) == 1


def test_another_childs_order_cannot_be_attached(surgical):
    """Somebody else's result in front of the person deciding whether *this*
    child is ready is the worst thing this screen could do."""
    from app.utils import theatres as theatre

    theirs = _order(surgical, who="other", name="صورة دم")
    with surgical["app"].app_context():
        assert theatre.link_investigation(_case(surgical),
                                          _get(surgical, theirs)) is None
        surgical["db"].session.commit()
        assert _get(surgical, theirs).operation_id is None


def test_another_childs_order_is_not_even_offered(surgical):
    from app.utils import theatres as theatre

    mine = _order(surgical, name="صورة دم")
    theirs = _order(surgical, who="other", name="صورة دم")
    with surgical["app"].app_context():
        offered = {o.id for o in theatre.workup_choices(_case(surgical))}
        assert mine in offered
        assert theirs not in offered


def test_an_order_already_on_another_case_is_not_offered(surgical):
    """**Caught by measurement.** Two cases on one child is ordinary — a
    staged procedure — and without the fence the second case's screen would
    offer the first case's order and quietly take it, so the first case would
    stop waiting on a result nobody had read."""
    from app.models.theatre import Operation
    from app.utils import theatres as theatre

    order = _order(surgical, name="صورة دم")
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        surgical["db"].session.commit()

        second = surgical["db"].session.get(Operation, surgical["ids"]["second"])
        offered = {o.id for o in theatre.workup_choices(second)}
        assert order not in offered, "the other case's order was on offer"
        # And it is still on its own case's list.
        assert [o.id for o in theatre.workup_orders(_case(surgical))] == [order]


def test_attaching_answers_the_question_too(surgical):
    """An attached order beside a NULL flag would have the screen say nobody
    asked while an order sits there waiting."""
    from app.utils import theatres as theatre

    order = _order(surgical)
    with surgical["app"].app_context():
        assert _case(surgical).workup_needed is None
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        surgical["db"].session.commit()
        assert _case(surgical).workup_needed is True


def test_detaching_keeps_the_order(surgical):
    """It is a real request somebody made. The wrong case is not a reason to
    lose it."""
    from app.utils import theatres as theatre

    order = _order(surgical)
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        surgical["db"].session.commit()
        theatre.unlink_investigation(_get(surgical, order))
        surgical["db"].session.commit()
        assert _get(surgical, order) is not None
        assert _get(surgical, order).operation_id is None
        assert theatre.workup_state(_case(surgical)) == "none_named"


# ------------------------------------------ the checklist item, and no more --
def test_no_checklist_item_was_added(surgical):
    """``missed`` is computed against the **current** item list, so adding one
    would make every checklist ever signed read as short."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, TIME_OUT

    assert "workup" not in CHECK_ITEMS[TIME_OUT]
    assert "workup" not in CHECK_ITEMS[SIGN_IN]
    assert "labs" not in CHECK_ITEMS[TIME_OUT]
    # The item it reads is the one that was already there.
    assert "imaging_ready" in CHECK_ITEMS[TIME_OUT]


def test_the_imaging_item_is_read_from_the_record(surgical):
    from app.models.theatre import TIME_OUT
    from app.utils import theatres as theatre

    order = _order(surgical, kind="imaging", name="أشعة بطن")
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        row = theatre.sign(_case(surgical), TIME_OUT,
                           items=["imaging_ready", "antibiotic"], user=None)
        surgical["db"].session.commit()
        assert not row.has("imaging_ready"), \
            "the box said the imaging was up while it was still pending"
        assert row.has("antibiotic")
        assert "imaging_ready" in row.missed


def test_it_ticks_itself_once_the_imaging_is_back(surgical):
    from app.models.theatre import TIME_OUT
    from app.utils import theatres as theatre

    order = _order(surgical, kind="imaging", name="أشعة بطن", resulted=True)
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        row = theatre.sign(_case(surgical), TIME_OUT, items=[], user=None)
        surgical["db"].session.commit()
        assert row.has("imaging_ready")


def test_a_case_with_no_imaging_still_ticks(surgical):
    """**The one derived item that ticks when nothing is recorded.** A case
    with no imaging has none to display, and a red item on every
    appendicectomy teaches people to stop reading the colour."""
    from app.models.theatre import TIME_OUT
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "unasked"
        row = theatre.sign(_case(surgical), TIME_OUT, items=[], user=None)
        surgical["db"].session.commit()
        assert row.has("imaging_ready")
        assert "imaging_ready" not in row.missed


def test_a_pending_lab_does_not_withhold_the_imaging_tick(surgical):
    """The item says «الأشعة معروضة». Making it answer for the labs too would
    have it mean more than its name says — and the lab half is recorded and
    shown on the card instead."""
    from app.models.theatre import TIME_OUT
    from app.utils import theatres as theatre

    order = _order(surgical, kind="lab", name="وظائف كبد")
    with surgical["app"].app_context():
        theatre.link_investigation(_case(surgical), _get(surgical, order))
        row = theatre.sign(_case(surgical), TIME_OUT, items=[], user=None)
        surgical["db"].session.commit()
        assert row.has("imaging_ready")
        # And the whole-case answer still says a result is outstanding.
        assert theatre.workup_state(_case(surgical)) == "waiting"


def test_the_derived_items_are_five_now(surgical):
    """The guard that made this change visible: it failed the moment
    ``imaging_ready`` joined the set, which is exactly when somebody should
    look at every test posting checklist items by hand."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, TIME_OUT
    from app.utils import theatres as theatre

    derived = set(theatre.derived_items())
    assert derived == {"identity", "site_marked", "consent",
                       "anaesthesia_check", "imaging_ready"}
    assert set(CHECK_ITEMS[SIGN_IN]) - derived == {
        "allergy", "airway", "pulse_oximeter"}
    assert set(CHECK_ITEMS[TIME_OUT]) - derived == {
        "team_introduced", "patient_site_procedure", "antibiotic",
        "critical_steps", "anticipated_blood_loss"}


# --------------------------------------------------------- on the screen --
def test_the_card_shows_the_state_and_the_childs_orders(surgical):
    from app.i18n import t

    _order(surgical, name="صورة دم")
    _order(surgical, name="فيريتين", resulted=True)
    html = surgical["sign_in"]().get(
        f"/theatres/operation/{surgical['ids']['case']}").get_data(as_text=True)
    assert "صورة دم" in html and "فيريتين" in html
    with surgical["app"].test_request_context("/"):
        assert t("theatre.workup_unasked") in html
        # The point of showing the orders: which answers are not back.
        assert t("theatre.workup_pending") in html
        assert t("theatre.workup_resulted") in html


def test_the_screen_attaches_what_was_ticked(surgical):
    from app.utils import theatres as theatre

    order = _order(surgical, name="صورة دم")
    surgical["sign_in"]().post(
        f"/theatres/operation/{surgical['ids']['case']}/workup",
        data={"needed": "yes", "order": [order]}, follow_redirects=True)
    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "waiting"
        assert _get(surgical, order).operation_id == surgical["ids"]["case"]


def test_unticking_one_detaches_it_without_deleting_it(surgical):
    from app.utils import theatres as theatre

    order = _order(surgical, name="صورة دم")
    client = surgical["sign_in"]()
    client.post(f"/theatres/operation/{surgical['ids']['case']}/workup",
                data={"needed": "yes", "order": [order]}, follow_redirects=True)
    client.post(f"/theatres/operation/{surgical['ids']['case']}/workup",
                data={"needed": "yes"}, follow_redirects=True)
    with surgical["app"].app_context():
        assert _get(surgical, order) is not None
        assert _get(surgical, order).operation_id is None
        assert theatre.workup_state(_case(surgical)) == "none_named"


def test_answering_no_detaches_what_was_attached(surgical):
    """"Waiting on nothing" with an order still attached is a contradiction,
    and the answer somebody just gave wins."""
    from app.utils import theatres as theatre

    order = _order(surgical, name="صورة دم")
    client = surgical["sign_in"]()
    client.post(f"/theatres/operation/{surgical['ids']['case']}/workup",
                data={"needed": "yes", "order": [order]}, follow_redirects=True)
    client.post(f"/theatres/operation/{surgical['ids']['case']}/workup",
                data={"needed": "no"}, follow_redirects=True)
    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "not_needed"
        assert _get(surgical, order) is not None
        assert _get(surgical, order).operation_id is None


def test_answering_no_wins_over_orders_posted_with_it(surgical):
    """**Caught by measurement.** The form can send both: the tick boxes are
    not cleared when somebody picks "no", so a contradictory submission —
    *waiting on nothing, and here are the things it waits on* — is one click
    away. The answer they just gave wins, and the orders go back to being the
    child's."""
    from app.utils import theatres as theatre

    order = _order(surgical, name="صورة دم")
    surgical["sign_in"]().post(
        f"/theatres/operation/{surgical['ids']['case']}/workup",
        data={"needed": "no", "order": [order]}, follow_redirects=True)
    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "not_needed"
        assert _get(surgical, order).operation_id is None
        assert _get(surgical, order) is not None


def test_the_imaging_row_is_not_offered_as_something_to_tick(surgical):
    """**Caught by measurement.** ``sign`` drops a posted ``imaging_ready``
    either way, so leaving the row tickable changed no stored data and every
    test stayed green — it only made the screen lie, showing a box that invites
    the habit this replaced."""
    from app.i18n import t

    html = surgical["sign_in"]().get(
        f"/theatres/operation/{surgical['ids']['case']}").get_data(as_text=True)
    assert 'name="item" value="imaging_ready"' not in html,         "the imaging box is posted like an ordinary tick"
    with surgical["app"].test_request_context("/"):
        assert t("theatre.workup_read_only") in html


def test_a_blank_answer_from_the_screen_is_refused(surgical):
    """Not read as "waiting on nothing". The screen's half of the two-facts
    rule."""
    from app.utils import theatres as theatre

    surgical["sign_in"]().post(
        f"/theatres/operation/{surgical['ids']['case']}/workup",
        data={"needed": ""}, follow_redirects=True)
    with surgical["app"].app_context():
        assert theatre.workup_state(_case(surgical)) == "unasked"


def test_set_workup_refuses_a_missing_answer(surgical):
    from app.utils import theatres as theatre

    with surgical["app"].app_context():
        assert theatre.set_workup(_case(surgical), None) is None
        surgical["db"].session.commit()
        assert theatre.workup_state(_case(surgical)) == "unasked"


def test_the_columns_are_registered_for_a_clinic_already_running(surgical):
    from app.utils.schema import ADDITIONS

    pairs = {(t, c) for t, c, _ in ADDITIONS}
    assert ("operations", "workup_needed") in pairs
    assert ("visit_investigations", "operation_id") in pairs
