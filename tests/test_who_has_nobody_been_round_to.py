"""The wards and intensive care — and the question only they ask.

Emergency is read in minutes: *who do I look at first*. A ward is read in
days, and its morning question is a different one — **who has nobody been
round to** — which no table in the program could answer, because a round that
did not happen leaves no row behind. Same shape as a missed observation, and
the reason ``RoundNote`` exists at all.

What is tested here, in the order it matters:

1. **The gate.** Both modules off until a clinic says it runs one, both
   switched on by the wizard capability that names them, both reachable by
   the people who do the work and by nobody else. Six times in this project
   something was built and nothing led to it.
2. **The blank round is refused.** A note with no trend would clear "nobody
   has been round today" without anybody going near the child — the flag
   going quiet exactly when it is telling the truth. This is the same rule
   the empty observation is refused by, and it is the test this file exists
   for.
3. **Today is the clinic's today.** A round walked at one in the morning in
   Cairo is stored at 23:00 UTC *yesterday*. Asking the question against UTC
   midnight would call it yesterday's round and flag a child who had just
   been seen. Four money reports have already been fixed for this.
4. **The round is a tie-breaker, never a level.** An unrounded child sorts
   ahead of a rounded one — and behind anybody the program reads as worse,
   because an administrative gap must not jump a clinical one.
5. **The action lives on ``beds``, not on ``ward``.** Three department
   screens post to it and a clinic may run any one of them alone. Hanging it
   off the ward would have given a nursery with no wards a 404 on the round
   it walks every morning.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A hospital with a ward, an intensive care bay and a nursery."""
    from app.models import Setting
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        for module in ("observations", "beds", "ward", "icu", "nicu",
                       "emergency"):
            Setting.set(f"mod_enabled:{module}", "1")

        for key, kind, space_kind, beds in (
                ("ward", "ward", "room", ["د١", "د٢", "د٣"]),
                ("icu", "icu", "bay", ["ع١", "ع٢"]),
                ("nicu", "nicu", "bay", ["ح١"]),
                ("er", "emergency", "partition", ["ط١"])):
            unit = Unit(name=f"قسم {key}", kind=kind)
            clinic["db"].session.add(unit)
            clinic["db"].session.flush()
            space = Space(unit_id=unit.id, name=f"حيّز {key}", kind=space_kind)
            clinic["db"].session.add(space)
            clinic["db"].session.flush()
            for order, name in enumerate(beds):
                clinic["db"].session.add(
                    Bed(space_id=space.id, name=name, sort_order=order))
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
    return clinic


def _child(clinic, name, born_days=900):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"W{name}", full_name=name,
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=born_days))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, bed_name, minutes_ago=600):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        admission = place.admit(
            Patient.query.get(patient_id),
            Bed.query.get(clinic["beds"][bed_name]),
            when=datetime.utcnow() - timedelta(minutes=minutes_ago))
        clinic["db"].session.commit()
        return admission.id


def _observe(clinic, patient_id, minutes_ago=5, every=240, **readings):
    from app.models.observation import Observation, ObservationOrder

    with clinic["app"].app_context():
        order = (ObservationOrder.query
                 .filter_by(patient_id=patient_id, stopped_at=None).first())
        if order is None:
            order = ObservationOrder(
                patient_id=patient_id, every_minutes=every,
                started_at=datetime.utcnow() - timedelta(hours=20))
            clinic["db"].session.add(order)
            clinic["db"].session.flush()
        clinic["db"].session.add(Observation(
            patient_id=patient_id, order_id=order.id,
            taken_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            **readings))
        clinic["db"].session.commit()


def _round(clinic, admission_id, trend="stable", **form):
    """Write a round the way the screen does — through the route."""
    client = clinic["sign_in"]("doc")
    return client.post(f"/beds/admission/{admission_id}/round",
                       data={"trend": trend, **form}, follow_redirects=True)


def _notes(clinic, admission_id):
    from app.models.round_note import RoundNote

    with clinic["app"].app_context():
        return RoundNote.query.filter_by(admission_id=admission_id).all()


# ------------------------------------------------------------- the gate ----
@pytest.mark.parametrize("module,path", [("ward", "/ward/"), ("icu", "/icu/")])
def test_the_department_is_off_until_a_clinic_says_it_has_one(clinic, module,
                                                              path):
    """A paediatric clinic that upgrades does not wake up running a ward."""
    from app.utils.facility import OPT_IN_MODULES

    assert module in OPT_IN_MODULES
    assert clinic["sign_in"]("boss").get(path).status_code == 404


@pytest.mark.parametrize("capability,module", [("ward", "ward"),
                                               ("icu", "icu")])
def test_the_wizard_switches_it_on_for_a_clinic_that_says_it_runs_one(
        clinic, capability, module):
    """The capability existed for a year with nothing behind it: a hospital
    ticked "ward", got the bed board, and had nowhere that answered the ward's
    own question. Ticking it now switches the screen on with it."""
    from app.utils.facility import (apply_facility, derive_modules,
                                    module_enabled)

    assert module in derive_modules([capability])
    with clinic["app"].app_context():
        assert not module_enabled(module)
        apply_facility("hospital", "مستشفى", [capability],
                       derive_modules([capability]))
        clinic["db"].session.commit()
        assert module_enabled(module)
        # And its two foundations with it — a ward that cannot hold a bed or
        # record a second temperature is not a ward.
        assert module_enabled("observations") and module_enabled("beds")


def test_the_people_who_walk_the_round_can_reach_it_and_the_desk_cannot(
        hospital):
    from app.models.permissions import role_modules

    for module in ("ward", "icu"):
        assert module in role_modules("doctor")
        assert module in role_modules("nursing")
        assert module not in role_modules("reception")
        assert module not in role_modules("accountant")


@pytest.mark.parametrize("kind,path", [("ward", "/ward/"), ("icu", "/icu/")])
def test_a_department_with_nothing_built_says_so(hospital, kind, path):
    """Rule one at its most literal: an empty screen reads as a module that
    does not work. It names what to build and links to where."""
    from app.i18n import t
    from app.models.place import Unit

    with hospital["app"].app_context():
        Unit.query.filter_by(kind=kind).delete()
        hospital["db"].session.commit()

    with hospital["app"].test_request_context("/"):
        sentence = t(f"dept.no_unit_{kind}")

    page = hospital["sign_in"]("boss").get(path).get_data(as_text=True)
    assert sentence in page
    assert "/beds/setup" in page


def test_the_sidebar_has_a_way_in(hospital):
    """The recurring failure in this project, and the one worth a test of its
    own: a screen built, wired and tested that nothing links to."""
    page = hospital["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert 'href="/ward/"' in page
    assert 'href="/icu/"' in page


# ------------------------------------------------------- the blank round ---
def test_a_round_with_no_trend_is_refused(hospital):
    """**The test this file exists for.**

    A saved-but-empty note would clear "nobody has been round today" off the
    board without anybody having gone near the child — the flag going quiet
    exactly when it was right. Same refusal as the empty observation, and the
    words say why rather than just "invalid".
    """
    from app.i18n import t

    child = _child(hospital, "بدون")
    admission = _admit(hospital, child, "د١")

    page = _round(hospital, admission, trend="").get_data(as_text=True)

    assert _notes(hospital, admission) == []
    with hospital["app"].test_request_context("/"):
        assert t("rounds.needs_trend") in page


def test_words_alone_are_not_a_round(hospital):
    """A paragraph with no trend on it is still refused. The board reads the
    trend, so a note without one is a round the screen cannot show — and it
    would clear the flag all the same."""
    child = _child(hospital, "كلام")
    admission = _admit(hospital, child, "د١")

    _round(hospital, admission, trend="",
           assessment="الحالة كويسة", plan="نكمل نفس العلاج")

    assert _notes(hospital, admission) == []


def test_a_trend_nobody_offered_is_refused(hospital):
    """Only the three. A fourth value typed into the form would be stored and
    then rendered through `t('rounds.trend_' ~ trend)`, which has nothing to
    say about it."""
    child = _child(hospital, "غريب")
    admission = _admit(hospital, child, "د١")

    _round(hospital, admission, trend="dying")

    assert _notes(hospital, admission) == []


def test_a_round_that_says_something_is_kept_whole(hospital):
    from app.utils.clock import local_today

    child = _child(hospital, "تمام")
    admission = _admit(hospital, child, "د١")

    _round(hospital, admission, trend="improving",
           assessment="الحرارة نزلت", plan="نوقف المضاد بكرة",
           expected_discharge=(local_today() + timedelta(days=2)).isoformat())

    with hospital["app"].app_context():
        from app.models.round_note import RoundNote
        note = RoundNote.query.filter_by(admission_id=admission).one()
        assert note.trend == "improving"
        assert note.assessment == "الحرارة نزلت"
        assert note.plan == "نوقف المضاد بكرة"
        assert note.expected_discharge == local_today() + timedelta(days=2)
        assert note.patient_id == child
        # Who wrote it, because "the registrar saw him" and "nobody knows"
        # are different facts to whoever reads this on Friday.
        assert note.by_id is not None


def test_the_board_stops_asking_once_somebody_has_been(hospital):
    from app.i18n import t

    child = _child(hospital, "اتشاف")
    admission = _admit(hospital, child, "د١")

    client = hospital["sign_in"]("doc")
    with hospital["app"].test_request_context("/"):
        nagging = t("rounds.not_today")

    before = client.get("/ward/").get_data(as_text=True)
    assert nagging in before

    _round(hospital, admission, trend="stable")

    after = client.get("/ward/").get_data(as_text=True)
    assert nagging not in after
    assert 'data-round="done"' in after


# ------------------------------------------------ the clinic's own clock ---
def test_a_round_walked_after_midnight_in_cairo_is_todays(hospital):
    """The mistake four money reports were fixed for.

    A round at 01:00 in Cairo is stored at 23:00 UTC *yesterday*. Asked
    against UTC midnight, it is yesterday's round — so the board would nag
    about a child somebody had just been to see, at the one hour of the night
    when being wrong costs most.
    """
    from app.utils import rounds as ward_round
    from app.utils.clock import local_today, to_utc

    child = _child(hospital, "بليل")
    admission = _admit(hospital, child, "د١")

    with hospital["app"].app_context():
        # One minute past midnight, the clinic's own clock.
        at = to_utc(datetime.combine(local_today(), time(0, 1)))
        ward_round.record(
            hospital["db"].session.get(
                __import__("app.models.admission", fromlist=["Admission"]).Admission,
                admission),
            "stable", at=at)
        hospital["db"].session.commit()

        assert admission in ward_round.done_today([admission])


def test_yesterdays_round_does_not_count_as_todays(hospital):
    """The other side of it. A test that only proves midnight is inside the
    window would pass just as well with no window at all."""
    from app.utils import rounds as ward_round
    from app.utils.clock import local_today, to_utc

    child = _child(hospital, "امبارح")
    admission = _admit(hospital, child, "د١")

    with hospital["app"].app_context():
        from app.models.admission import Admission

        at = to_utc(datetime.combine(local_today() - timedelta(days=1),
                                     time(23, 59)))
        ward_round.record(hospital["db"].session.get(Admission, admission),
                          "stable", at=at)
        hospital["db"].session.commit()

        assert ward_round.done_today([admission]) == set()


def test_the_hour_a_round_was_walked_is_not_the_hour_it_was_typed(hospital):
    """Two clocks, like the observation. The doctor walks at nine and writes
    it up at eleven; a board that asks "was this child seen today" has to ask
    about the first of those, and the file has to carry both."""
    from app.utils.clock import local_now, to_utc

    child = _child(hospital, "اتأخر")
    admission = _admit(hospital, child, "د١")

    walked = (local_now() - timedelta(hours=2)).replace(second=0,
                                                        microsecond=0)
    _round(hospital, admission, trend="stable",
           at=walked.strftime("%Y-%m-%dT%H:%M"))

    with hospital["app"].app_context():
        from app.models.round_note import RoundNote
        note = RoundNote.query.filter_by(admission_id=admission).one()
        assert note.at == to_utc(walked.replace(tzinfo=None))
        assert note.recorded_at > note.at


# ---------------------------------------------------------- the ordering ---
def test_nobody_has_been_round_to_this_one_sorts_first(hospital):
    """At the same clinical level, the child nobody has seen comes up the
    list. It is the whole reason a ward manager opens this screen."""
    from app.utils import department

    seen = _child(hospital, "متشاف")
    unseen = _child(hospital, "متشافش")
    seen_stay = _admit(hospital, seen, "د١", minutes_ago=2000)
    _admit(hospital, unseen, "د٢", minutes_ago=100)
    for patient in (seen, unseen):
        _observe(hospital, patient, temperature_c=37.0, pulse_bpm=100)
    _round(hospital, seen_stay, trend="stable")

    with hospital["app"].app_context():
        names = [r["patient"].full_name for r in department.live("ward")]
    # The seen child has been here twenty times longer, so wait-time alone
    # would have put them first.
    assert names[0] == "متشافش"


def test_a_worse_child_still_outranks_an_unrounded_one(hospital):
    """The round is a tie-breaker and never a level. An administrative gap
    must not jump in front of a clinical one — a stable child nobody has
    written about is not more urgent than one whose last reading the program
    reads as bad."""
    from app.utils import department

    ill = _child(hospital, "تعبان")
    quiet = _child(hospital, "هادي")
    ill_stay = _admit(hospital, ill, "د١", minutes_ago=100)
    _admit(hospital, quiet, "د٢", minutes_ago=100)

    _observe(hospital, ill, temperature_c=41.0, pulse_bpm=190, spo2=88)
    _observe(hospital, quiet, temperature_c=37.0, pulse_bpm=100, spo2=99)
    # And the ill one has been rounded, the quiet one has not — so anything
    # that ranked the round above the reading would put them the wrong way up.
    _round(hospital, ill_stay, trend="worse")

    with hospital["app"].app_context():
        rows = department.live("ward")
        assert rows[0]["patient"].full_name == "تعبان"
        assert rows[0]["level"] in ("urgent", "watch")


def test_emergency_is_never_nagged_about_a_round(hospital):
    """A child is in emergency for hours and the stay ends in a decision.
    "Not seen today" would light up every trolley in the place the moment it
    filled, which is how a flag stops being read."""
    from app.utils import department
    from app.utils import rounds as ward_round

    child = _child(hospital, "طوارئ")
    _admit(hospital, child, "ط١", minutes_ago=40)

    assert not ward_round.kind_has_rounds("emergency")
    with hospital["app"].app_context():
        assert department.live("emergency")[0]["round"] is None
        assert 'data-round="none"' not in (
            hospital["sign_in"]("boss").get("/emergency/").get_data(as_text=True))


def test_the_incubators_are_rounded_like_a_ward(hospital):
    """A nursery does a round every morning. The list of departments without
    one names emergency, not everything that is not a ward."""
    from app.utils import department

    child = _child(hospital, "حضّانة", born_days=2)
    _admit(hospital, child, "ح١", minutes_ago=100)

    with hospital["app"].app_context():
        assert department.live("nicu")[0]["round"] is not None


# ------------------------------------------------ where the action lives ---
def test_a_nursery_with_no_ward_can_still_write_a_round(hospital):
    """The gate bug this route was moved to avoid.

    Three department screens post to one address. Put it behind `ward` and a
    clinic running only a nursery gets 404 on the round it walks every
    morning — "a module off is a module absent", aimed at its own feature.
    """
    from app.models import Setting

    with hospital["app"].app_context():
        Setting.set("mod_enabled:ward", "0")
        Setting.set("mod_enabled:icu", "0")
        hospital["db"].session.commit()

    child = _child(hospital, "بدون_داخلي", born_days=2)
    admission = _admit(hospital, child, "ح١")

    client = hospital["sign_in"]("doc")
    assert client.get("/ward/").status_code == 404
    assert client.post(f"/beds/admission/{admission}/round",
                       data={"trend": "stable"}).status_code in (302, 200)
    assert len(_notes(hospital, admission)) == 1


def test_the_round_form_posts_to_the_beds_address_from_every_board(hospital):
    child = _child(hospital, "شكل")
    _admit(hospital, child, "د١")
    page = hospital["sign_in"]("doc").get("/ward/").get_data(as_text=True)
    assert "/beds/admission/" in page and "/round" in page
    # Three buttons and nothing to type: a round is one press, because the
    # doctor is standing at a bed with eight more to see.
    for trend in ("improving", "stable", "worse"):
        assert f'value="{trend}"' in page


# ----------------------------------------------- when do they go home -------
def test_the_newest_answer_wins_and_the_older_one_survives(hospital):
    """Written on the round rather than on the stay, so that changing it
    leaves a trail: "we said Thursday on Monday and Saturday on Wednesday" is
    the history, and one column on the admission would overwrite it."""
    from app.utils import rounds as ward_round
    from app.utils.clock import local_today

    child = _child(hospital, "خروج")
    admission = _admit(hospital, child, "د١")

    thursday = local_today() + timedelta(days=3)
    saturday = local_today() + timedelta(days=5)

    with hospital["app"].app_context():
        from app.models.admission import Admission
        from app.models.round_note import RoundNote

        stay = hospital["db"].session.get(Admission, admission)
        ward_round.record(stay, "stable", expected_discharge=thursday,
                          at=datetime.utcnow() - timedelta(days=2))
        ward_round.record(stay, "worse", expected_discharge=saturday,
                          at=datetime.utcnow())
        hospital["db"].session.commit()

        assert ward_round.state([admission])[admission][
            "expected_discharge"] == saturday
        assert {n.expected_discharge for n in
                RoundNote.query.filter_by(admission_id=admission)} == {
                    thursday, saturday}


def test_a_note_typed_later_about_an_earlier_round_does_not_win(hospital):
    """Newest by when the round *happened*, not by when it reached the

    keyboard. The registrar writes up the seven o'clock round at noon, after
    the consultant's nine o'clock one is already in — and it is the nine
    o'clock answer that stands. Ordering by the typing time would quietly
    reinstate the earlier decision.
    """
    from app.utils import rounds as ward_round
    from app.utils.clock import local_today

    child = _child(hospital, "متأخر_كتابة")
    admission = _admit(hospital, child, "د١")
    early = local_today() + timedelta(days=9)
    later = local_today() + timedelta(days=1)

    with hospital["app"].app_context():
        from app.models.admission import Admission

        stay = hospital["db"].session.get(Admission, admission)
        # The nine o'clock round, typed first.
        ward_round.record(stay, "improving", expected_discharge=later,
                          at=datetime.utcnow() - timedelta(hours=2))
        hospital["db"].session.commit()
        # The seven o'clock round, typed after it.
        ward_round.record(stay, "worse", expected_discharge=early,
                          at=datetime.utcnow() - timedelta(hours=4))
        hospital["db"].session.commit()

        standing = ward_round.state([admission])[admission]
        assert standing["last"].trend == "improving"
        assert standing["expected_discharge"] == later


def test_the_expected_date_shows_on_the_board(hospital):
    from app.utils import rounds as ward_round
    from app.utils.clock import local_today

    child = _child(hospital, "متوقع")
    admission = _admit(hospital, child, "د١")
    home = local_today() + timedelta(days=4)

    with hospital["app"].app_context():
        from app.models.admission import Admission
        ward_round.record(hospital["db"].session.get(Admission, admission),
                          "stable", expected_discharge=home)
        hospital["db"].session.commit()

    page = hospital["sign_in"]("doc").get("/ward/").get_data(as_text=True)
    # The badge on the card, not merely the date somewhere on the page: the
    # round form prefills the same value into its date box, so asserting on
    # the digits alone passed with the badge deleted. Found by breaking it.
    assert "data-expected" in page
    badge = page.split("data-expected", 1)[1][:200]
    assert home.isoformat() in badge


def test_a_round_with_no_date_does_not_invent_one(hospital):
    """An expected discharge nobody typed is not a plan. Defaulting it to
    today would put a discharge date into the record that no clinician ever
    said out loud."""
    child = _child(hospital, "بدون_تاريخ")
    admission = _admit(hospital, child, "د١")

    _round(hospital, admission, trend="stable", expected_discharge="")

    with hospital["app"].app_context():
        from app.models.round_note import RoundNote
        assert RoundNote.query.filter_by(
            admission_id=admission).one().expected_discharge is None


# ------------------------------------------------------------ the stay -----
def test_the_stay_screen_shows_the_rounds_newest_first(hospital):
    from app.utils import rounds as ward_round

    child = _child(hospital, "تاريخ")
    admission = _admit(hospital, child, "د١")

    with hospital["app"].app_context():
        from app.models.admission import Admission
        stay = hospital["db"].session.get(Admission, admission)
        ward_round.record(stay, "worse", assessment="أول يوم",
                          at=datetime.utcnow() - timedelta(days=1))
        ward_round.record(stay, "improving", assessment="تاني يوم",
                          at=datetime.utcnow())
        hospital["db"].session.commit()

    page = hospital["sign_in"]("doc").get(
        f"/beds/admission/{admission}").get_data(as_text=True)
    assert page.index("تاني يوم") < page.index("أول يوم")


def test_a_child_readmitted_reads_as_one_story(hospital):
    """The note carries a patient of its own so a child who comes back in
    March reads as one thread rather than two unrelated ones."""
    from app.utils import beds as place
    from app.utils import rounds as ward_round

    child = _child(hospital, "رجع")
    first = _admit(hospital, child, "د١")

    with hospital["app"].app_context():
        from app.models.admission import Admission

        stay = hospital["db"].session.get(Admission, first)
        ward_round.record(stay, "stable", assessment="الإقامة الأولى")
        place.discharge(stay, "home")
        hospital["db"].session.commit()

    second = _admit(hospital, child, "د١", minutes_ago=10)
    with hospital["app"].app_context():
        from app.models.admission import Admission

        ward_round.record(hospital["db"].session.get(Admission, second),
                          "worse", assessment="الإقامة التانية")
        hospital["db"].session.commit()

        assert len(ward_round.for_patient(child)) == 2


# ------------------------------------------------------------- the cost ----
def test_a_full_ward_costs_what_an_empty_one_costs(hospital):
    """Size comparison rather than a guessed ceiling.

    The rounds are two queries for the department however many children are
    in it. Written as a loop they would be two per child, which is invisible
    on the four-bed ward a developer tests with and is the whole morning on a
    real one.
    """
    from app.models.place import Bed, Space, Unit
    from app.utils import rounds as ward_round

    with hospital["app"].app_context():
        unit = Unit.query.filter_by(kind="ward").first()
        space = Space.query.filter_by(unit_id=unit.id).first()
        for n in range(20):
            hospital["db"].session.add(
                Bed(space_id=space.id, name=f"ك{n}", sort_order=50 + n))
        hospital["db"].session.commit()
        hospital["beds"] = {b.name: b.id for b in Bed.query.all()}

    stays = []
    for n in range(20):
        kid = _child(hospital, f"كتير{n}")
        stays.append(_admit(hospital, kid, f"ك{n}"))
    for stay in stays:
        _round(hospital, stay, trend="stable")

    from app.extensions import db

    def count(ids):
        seen = []
        from sqlalchemy import event

        with hospital["app"].app_context():
            engine = db.engine

            def record(conn, cursor, statement, params, ctx, many):
                seen.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                ward_round.state(ids)
            finally:
                event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    assert count(stays[:4]) == count(stays)


# --------------------------------------------------------- said in both -----
def test_every_word_on_the_screen_exists_in_both_languages(hospital):
    import json

    from app.i18n import t

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        ar = json.load(fh)
    with open("app/i18n/locales/en.json", encoding="utf-8") as fh:
        en = json.load(fh)

    for key in ("today_q", "not_today", "trend_improving", "trend_stable",
                "trend_worse", "more", "assessment", "plan",
                "expected_discharge", "at", "saved", "needs_trend",
                "history", "none_yet", "by"):
        assert key in ar["rounds"] and key in en["rounds"]
        assert ar["rounds"][key] != en["rounds"][key]

    for group in ("ward", "icu"):
        assert ar["nav"][group] and en["nav"][group]
        assert ar[group]["sub"] and en[group]["sub"]

    with hospital["app"].test_request_context("/"):
        assert not t("rounds.trend_stable").startswith("rounds.")


def test_the_guide_explains_both_departments(hospital):
    """A screen nobody was told about is a screen nobody opens — the same
    reason the handbook is filtered by role rather than written once."""
    from app.utils.handbook import SECTIONS, modules_without_a_section

    assert modules_without_a_section() == []
    keys = {s["key"] for s in SECTIONS}
    assert {"ward", "icu"} <= keys
    for section in SECTIONS:
        if section["key"] in ("ward", "icu"):
            assert section["module"] == section["key"]
            assert len(section["lines"]) >= 3
