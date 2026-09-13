"""Counting what goes in, and what comes back — GAHAR SAS.09 · GSR.17.

> The accuracy of counting sponges, needles, and instruments pre- and
> post-procedure is verified.
>
> Missing sponges, suture reels, needles, blades, towels, or instruments
> inside the patient's body act as a foreign body and cause serious morbidity …
> which necessitate reopening the patient and could reach up to mortality.

**What the program had was a tick.** ``counts_correct`` was an ordinary box on
the sign-out stop of the WHO checklist, and anybody could tick it walking
past. One box: no numbers, no second person, no three moments, and nothing at
all about what happens when the numbers disagree — which is the one moment
this standard exists for.

It is taken out the same way the consent, the site, the identity and the
imaging were: **the item is derived from a record of something that
happened.** And it is an item that was *already there* — deriving an existing
one is safe, adding one would make every checklist ever signed read as short.

Six things this suite pins:

* **Expected and found, never one number.** The standard is about the
  *difference*; a program holding one number threw the comparison away before
  anybody looked.
* **Two people, and the second is the control.** Evidence 2 says the second
  *"acts as a witness for the first one"*. A witness who is the counter is
  refused — and refused by raising, because a return value a caller can ignore
  would let a one-person count through.
* **The middle count may happen more than once** — the intent says at the
  closure of *each body space*.
* **A miscount outranks a short record.** Four sponges against three is not
  incomplete paperwork.
* **Closed out means somebody wrote what happened**, not that the numbers were
  made to agree.
* **A case nobody counted does not tick**, which is the whole point.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def theatre():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        boss = User(username="boss", full_name="الجرّاح", role="admin",
                    is_active=True)
        boss.set_password("secret")
        nurse = User(username="nurse", full_name="الممرضة", role="nurse",
                     is_active=True)
        nurse.set_password("secret")
        room = Theatre(name="غرفة ١")
        db.session.add_all([boss, nurse, room])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="استئصال زائدة", on_date=local_today(),
                         surgeon_id=boss.id, status="scheduled")
        db.session.add(case)
        db.session.commit()
        ids = {"boss": boss.id, "nurse": nurse.id, "case": case.id,
               "kid": kid.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _case(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["case"])


def _who(ctx, key):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"][key])


def _count(ctx, moment="pre", sponge=(4, 4), **more):
    """One counting event, by the nurse with the surgeon witnessing."""
    from app.utils import surgical_counts as counts

    items = {"sponge": sponge}
    items.update(more)
    row = counts.record(_case(ctx), moment, items,
                        counted_by=_who(ctx, "nurse"),
                        witnessed_by=_who(ctx, "boss"))
    ctx["db"].session.commit()
    return row


def _all_three(ctx):
    for moment in ("pre", "intra", "post"):
        _count(ctx, moment)


# ------------------------------------------------ expected against found --
def test_a_count_holds_both_numbers_not_one(theatre):
    """The standard is about the **difference** between what went in and what
    came back. One column called «count» throws the comparison away before
    anybody looks at it."""
    with theatre["app"].app_context():
        row = _count(theatre, sponge=(4, 3))
        item = row.items[0]
        assert item.expected == 4
        assert item.found == 3
        assert item.agrees is False
        assert item.missing == 1


def test_an_extra_item_nobody_expected_is_also_wrong(theatre):
    """``missing`` is signed on purpose: something on the trolley that nobody
    put there is its own kind of wrong and must not read as a clean count."""
    with theatre["app"].app_context():
        row = _count(theatre, sponge=(3, 4))
        assert row.items[0].agrees is False
        assert row.items[0].missing == -1


def test_a_count_that_agrees_agrees(theatre):
    with theatre["app"].app_context():
        row = _count(theatre, sponge=(4, 4), needle=(2, 2))
        assert row.agrees is True
        assert row.short == []


def test_only_the_items_the_standard_names_are_stored(theatre):
    """The vocabulary is the handbook's — sponges, needles, instruments,
    towels, blades, sutures. A screen posting something else is a bug in the
    screen, not a new kind of swab."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = counts.record(_case(theatre), "pre",
                            {"sponge": (2, 2), "made_up": (9, 9)},
                            counted_by=_who(theatre, "nurse"),
                            witnessed_by=_who(theatre, "boss"))
        theatre["db"].session.commit()
        assert [i.item for i in row.items] == ["sponge"]


def test_a_count_with_nothing_counted_is_refused(theatre):
    """A row holding no items would make the state read «ok» for a case nobody
    counted — the tick again, wearing a table."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        assert counts.record(_case(theatre), "pre", {},
                             counted_by=_who(theatre, "nurse"),
                             witnessed_by=_who(theatre, "boss")) is None
        assert counts.record(_case(theatre), "pre", {"made_up": (1, 1)},
                             counted_by=_who(theatre, "nurse"),
                             witnessed_by=_who(theatre, "boss")) is None


def test_an_unknown_moment_is_refused(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        assert counts.record(_case(theatre), "afterwards", {"sponge": (1, 1)},
                             counted_by=_who(theatre, "nurse"),
                             witnessed_by=_who(theatre, "boss")) is None


# ------------------------------------------------------- two people -------
def test_one_person_counting_alone_is_refused(theatre):
    """**Evidence 2 is the control, not paperwork**: the second person *"acts
    as a witness for the first one"*, and one person counting alone is the
    practice this standard was written against."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        with pytest.raises(counts.NotTwoPeople):
            counts.record(_case(theatre), "pre", {"sponge": (1, 1)},
                          counted_by=_who(theatre, "nurse"))
        with pytest.raises(counts.NotTwoPeople):
            counts.record(_case(theatre), "pre", {"sponge": (1, 1)},
                          witnessed_by=_who(theatre, "boss"))


def test_a_witness_who_is_the_counter_is_refused(theatre):
    """A signature by one person twice is one person, whatever the form says."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        with pytest.raises(counts.NotTwoPeople):
            counts.record(_case(theatre), "pre", {"sponge": (1, 1)},
                          counted_by=_who(theatre, "nurse"),
                          witnessed_by=_who(theatre, "nurse"))


def test_the_refusal_raises_rather_than_returning(theatre):
    """A caller that could ignore a return value would be able to record a
    one-person count without noticing — which is why this is an exception and
    the empty-items refusal is not."""
    from app.utils import surgical_counts as counts
    from app.models.surgical_count import SurgicalCount

    with theatre["app"].app_context():
        with pytest.raises(counts.NotTwoPeople):
            counts.record(_case(theatre), "pre", {"sponge": (1, 1)},
                          counted_by=_who(theatre, "nurse"),
                          witnessed_by=_who(theatre, "nurse"))
        theatre["db"].session.rollback()
        assert SurgicalCount.query.count() == 0


def test_both_people_are_recorded_by_name(theatre):
    with theatre["app"].app_context():
        row = _count(theatre)
        assert row.counted_by == theatre["ids"]["nurse"]
        assert row.witnessed_by == theatre["ids"]["boss"]


# --------------------------------------------------------- the states -----
def test_a_case_nobody_counted(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        assert counts.state(_case(theatre)) == "unasked"
        assert counts.counts_ok(_case(theatre)) is False
        assert counts.state(None) == "unasked"


def test_a_case_counted_at_only_one_moment_is_short(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _count(theatre, "pre")
        assert counts.state(_case(theatre)) == "short"
        assert counts.missing_moments(_case(theatre)) == ["intra", "post"]
        assert counts.counts_ok(_case(theatre)) is False


def test_all_three_moments_and_every_number_agreeing_is_ok(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _all_three(theatre)
        assert counts.state(_case(theatre)) == "ok"
        assert counts.missing_moments(_case(theatre)) == []
        assert counts.counts_ok(_case(theatre)) is True


def test_the_middle_count_may_happen_more_than_once(theatre):
    """*"during the closure of **each body space**"* — a case that enters two
    cavities counts twice in the middle, and that is not a duplicate."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _count(theatre, "pre")
        _count(theatre, "intra")
        _count(theatre, "intra")
        _count(theatre, "post")
        assert len(counts.at_moment(_case(theatre), "intra")) == 2
        assert counts.state(_case(theatre)) == "ok"


def test_a_miscount_outranks_a_short_record(theatre):
    """A case missing its post-closure count **and** holding four sponges
    against three is not «incomplete paperwork» — it is the event this
    standard exists for, and the word on the screen has to be that one."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _count(theatre, "pre", sponge=(4, 3))
        assert counts.missing_moments(_case(theatre)) == ["intra", "post"]
        assert counts.state(_case(theatre)) == "miscount"


def test_a_miscount_keeps_the_case_from_ticking(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _count(theatre, "pre")
        _count(theatre, "intra")
        _count(theatre, "post", sponge=(4, 3))
        assert counts.counts_ok(_case(theatre)) is False


# ------------------------------------------------- managing a miscount ----
def test_a_miscount_is_open_until_somebody_writes_what_happened(theatre):
    """**Closed out means somebody wrote what happened**, not that the numbers
    were made to agree. A sponge found on the floor and one found on an X-ray
    are both resolutions; a blank is neither."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        assert counts.open_miscounts(_case(theatre)) == [row]

        counts.handle_miscount(row, resolution="اتلاقت على الأرض تحت الترابيزة")
        theatre["db"].session.commit()
        assert counts.open_miscounts(_case(theatre)) == []


def test_whitespace_already_in_the_record_does_not_close_a_miscount(theatre):
    """The second half of the same rule, and it needs its own test because
    ``handle_miscount`` strips on the way in — so nothing going through the
    screen can reach the check with spaces in it. A row written by an import,
    or straight to the table, can.
    """
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        row.resolution = "   \n  "
        theatre["db"].session.commit()
        assert counts.open_miscounts(_case(theatre)) == [row]
        assert counts.state(_case(theatre)) == "miscount"


def test_the_numbers_are_not_edited_to_make_them_agree(theatre):
    """Resolving does not rewrite the count. What was found stays what was
    found — a record that could be corrected into agreement is a record that
    proves nothing."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        counts.handle_miscount(row, resolution="اتلاقت")
        theatre["db"].session.commit()
        assert row.items[0].found == 3
        assert row.agrees is False


def test_each_step_has_three_states_not_two(theatre):
    """*Nobody has said* and *it was decided against* are different answers,
    and at the moment a sponge is unaccounted for they are opposite ones."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        assert row.recounted is None and row.imaging is None

        counts.handle_miscount(row, recounted=True, imaging=False)
        theatre["db"].session.commit()
        assert row.recounted is True
        assert row.imaging is False      # decided against, not unanswered


def test_leaving_a_step_out_of_the_call_does_not_write_no(theatre):
    """The trap the three-state rule exists to avoid: a call that omits a
    field must not silently record «no»."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        counts.handle_miscount(row, recounted=True)
        theatre["db"].session.commit()
        assert row.recounted is True
        assert row.imaging is None


def test_reporting_is_stamped_once(theatre):
    """*"and report the miscount"*. Reporting twice is somebody chasing, and
    moving the stamp loses when the incident actually reached whoever collects
    them — the number evidence 5 monitors."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        assert row.reported is False
        counts.report(row, user=_who(theatre, "boss"),
                      at=datetime(2026, 5, 1, 12, 0))
        theatre["db"].session.commit()
        assert row.reported is True
        assert counts.report(row, user=_who(theatre, "boss")) is None
        assert row.reported_at == datetime(2026, 5, 1, 12, 0)


def test_a_resolved_miscount_is_still_a_miscount_in_the_record(theatre):
    """It stops being *open*; it does not stop having happened. Evidence 5
    monitors the reported data, and a theatre whose resolved miscounts
    vanished would have nothing to monitor."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        counts.handle_miscount(row, resolution="اتلاقت")
        theatre["db"].session.commit()
        assert row.agrees is False
        assert counts.miscounts() == [row]


# ------------------------------------------------------ the signature ----
def test_the_physician_signs_the_record(theatre):
    """Evidence 3: *"the performing physician signs the record"*."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _all_three(theatre)
        assert counts.signed(_case(theatre)) is False
        counts.sign(_case(theatre), user=_who(theatre, "boss"))
        theatre["db"].session.commit()
        assert counts.signed(_case(theatre)) is True
        assert _case(theatre).counts_signed_by == theatre["ids"]["boss"]


def test_signing_an_empty_record_is_refused(theatre):
    """A signature under a record nobody wrote is the false green tick again,
    wearing a name."""
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        assert counts.sign(_case(theatre), user=_who(theatre, "boss")) is None
        assert counts.signed(_case(theatre)) is False


# ---------------------------------------------- the box that used to lie --
def test_the_checklist_item_is_derived_not_ticked(theatre):
    """The whole point. `counts_correct` was an ordinary box on the sign-out;
    it now reads off the counts, and a form that posts it is ignored."""
    from app.models.theatre import SIGN_OUT
    from app.utils import theatres as theatres_util
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        assert counts.COUNTS_ITEM in theatres_util.derived_items()
        row = theatres_util.sign(_case(theatre), SIGN_OUT,
                                 items=["counts_correct", "procedure_recorded"],
                                 user=_who(theatre, "boss"))
        theatre["db"].session.commit()
        # Posted by hand and not believed — nobody counted anything.
        assert "counts_correct" not in row.items
        assert "procedure_recorded" in row.items


def test_the_item_ticks_itself_once_the_counting_is_done(theatre):
    from app.models.theatre import SIGN_OUT
    from app.utils import theatres as theatres_util

    with theatre["app"].app_context():
        _all_three(theatre)
        row = theatres_util.sign(_case(theatre), SIGN_OUT, items=[],
                                 user=_who(theatre, "boss"))
        theatre["db"].session.commit()
        assert "counts_correct" in row.items


def test_no_new_checklist_item_was_invented(theatre):
    """`missed` computes against the current item list, so a **new** item
    would make every checklist ever signed read as short. This derives one
    that was already there."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, SIGN_OUT, TIME_OUT

    every = set(CHECK_ITEMS[SIGN_IN]) | set(CHECK_ITEMS[TIME_OUT]) \
        | set(CHECK_ITEMS[SIGN_OUT])
    assert "counts_correct" in every
    for invented in ("counts", "sponge_count", "count_done", "instruments"):
        assert invented not in every


# ---------------------------------------------------------- monitoring ---
def test_the_theatre_can_see_its_miscounts_over_a_period(theatre):
    """Evidence 5 — the program counts; what to do about it is the theatre's."""
    from app.utils import surgical_counts as counts
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        _count(theatre, "pre")                        # agrees
        bad = _count(theatre, "post", sponge=(4, 3), needle=(2, 1))
        today = local_today()
        summary = counts.miscount_summary(today, today)
        assert summary["miscounts"] == 1
        assert summary["cases"] == 1
        assert summary["reported"] == 0
        assert {r["item"] for r in summary["by_item"]} == {"sponge", "needle"}

        counts.report(bad, user=_who(theatre, "boss"))
        theatre["db"].session.commit()
        assert counts.miscount_summary(today, today)["reported"] == 1


def test_a_miscount_outside_the_period_is_not_counted(theatre):
    from app.utils import surgical_counts as counts
    from app.utils.clock import local_today

    with theatre["app"].app_context():
        _count(theatre, "post", sponge=(4, 3))
        today = local_today()
        assert counts.miscount_summary(today, today)["miscounts"] == 1
        gone = today + timedelta(days=30)
        assert counts.miscount_summary(gone, gone)["miscounts"] == 0
        older = today - timedelta(days=30)
        assert counts.miscount_summary(older, older)["miscounts"] == 0


# ------------------------------------------------------- the screen ------
def test_the_case_screen_says_nobody_counted(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert 'data-count-state="unasked"' in html
        assert t("counts.nobody_counted") in html


def test_recording_a_count_through_the_screen(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        theatre["sign_in"]().post(
            "/theatres/operation/%s/count" % theatre["ids"]["case"],
            data={"moment": "pre", "witness_id": theatre["ids"]["nurse"],
                  "expected_sponge": 4, "found_sponge": 4},
            follow_redirects=True)
        rows = counts.counts_for(_case(theatre))
        assert len(rows) == 1
        assert rows[0].items[0].expected == 4


def test_the_screen_refuses_a_witness_who_is_the_counter(theatre):
    from app.i18n import translate as t
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/count" % theatre["ids"]["case"],
            data={"moment": "pre", "witness_id": theatre["ids"]["boss"],
                  "expected_sponge": 4, "found_sponge": 4},
            follow_redirects=True).get_data(as_text=True)
        assert t("counts.needs_two_people") in html
        assert counts.counts_for(_case(theatre)) == []


def test_the_screen_refuses_a_count_with_no_numbers(theatre):
    """A form submitted with every box empty is somebody pressing the button,
    not a count — and a row holding no items would make the state read «ok»
    for a case nobody counted."""
    from app.i18n import translate as t
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/count" % theatre["ids"]["case"],
            data={"moment": "pre", "witness_id": theatre["ids"]["nurse"]},
            follow_redirects=True).get_data(as_text=True)
        assert t("counts.needs_numbers") in html
        assert counts.counts_for(_case(theatre)) == []
        assert counts.state(_case(theatre)) == "unasked"


def test_the_screen_shows_both_numbers_and_the_miscount(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        _count(theatre, "post", sponge=(4, 3))
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert 'data-count-state="miscount"' in html
        assert t("counts.miscount") in html
        # Found over expected, both of them.
        assert "3/4" in html
        # And the card asking what was done about it.
        assert "data-open-miscount" in html


def test_handling_a_miscount_through_the_screen(theatre):
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        theatre["sign_in"]().post(
            "/theatres/count/%s/miscount" % row.id,
            data={"recounted": "yes", "imaging": "no",
                  "resolution": "اتلاقت في الشاش المستعمل", "report": "1"},
            follow_redirects=True)
        assert row.recounted is True
        assert row.imaging is False
        assert row.reported is True
        assert counts.open_miscounts(_case(theatre)) == []


def test_the_screen_keeps_nobody_said_as_nobody_said(theatre):
    """The select's empty option must not land as «no»."""
    with theatre["app"].app_context():
        row = _count(theatre, "post", sponge=(4, 3))
        theatre["sign_in"]().post(
            "/theatres/count/%s/miscount" % row.id,
            data={"recounted": "", "imaging": "", "resolution": "لسه بندوّر"},
            follow_redirects=True)
        assert row.recounted is None
        assert row.imaging is None


def test_signing_through_the_screen(theatre):
    from app.i18n import translate as t
    from app.utils import surgical_counts as counts

    with theatre["app"].app_context():
        _all_three(theatre)
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/count/sign" % theatre["ids"]["case"],
            follow_redirects=True).get_data(as_text=True)
        assert t("counts.signed") in html
        assert "data-count-signed" in html
        assert counts.signed(_case(theatre)) is True


def test_the_screen_refuses_to_sign_an_empty_record(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/count/sign" % theatre["ids"]["case"],
            follow_redirects=True).get_data(as_text=True)
        assert t("counts.nothing_to_sign") in html
