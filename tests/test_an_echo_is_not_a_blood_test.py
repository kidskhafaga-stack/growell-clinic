"""The lab's own screen was listing echocardiograms.

> «ليه ركويست الايكو موجود فى المعمل ؟»

Reported with a photo of `/labs/`: two `إيكو قلب ECHO` rows sitting in the rack
beside the blood counts, each waiting 18,391 minutes, each offering «افتح».

Everything about that screen is about a **sample**. It is called «المعمل», its
icon is a pipette, its two counters are «to draw» and «to run», and the comment
over its own stylesheet says drawing blood and running a sample are done by two
different people. An echo has no tube.

So this is not a list that looked untidy. It was a list that:

* counted scans under «to collect», giving the bench a number it could not
  work to;
* offered «the sample was taken» on a row where that can never be true, and
  `collect()` would have written a **sample code and a collection time** onto
  an echocardiogram — a record of something that did not happen;
* and, on the other side, left imaging with nowhere of its own at all.

The cause was one default: `worklist(kind=None)` — every kind — on a screen
that is one of the two kinds.

**The fix is not to filter them out and stop.** An order nobody can see is an
order nobody does. Imaging gets its own screen and, because a scan is not a
sample, its own event: `performed_at`, not `collected_at`.

**And not a fourth state.** `collected` already means "it is under way and
nobody has answered yet", which is exactly as true of a scan that has been
done. The note above ``INVESTIGATION_STATUSES`` records what adding a state
cost last time: four screens that ask *has this been answered* would each have
had to learn a new word, and an order would have vanished from every one of
them.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def rack():
    """A blood count and an echo, both ordered, both unanswered."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User, Visit
        from app.models.visit import VisitInvestigation
        from app.utils.clock import local_today

        Setting.set("mod_enabled:labs", "1")
        tech = User(username="tech", full_name="فنّي المعمل", role="admin",
                    is_active=True)
        tech.set_password("secret")
        db.session.add(tech)
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="أحمد السيد", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.flush()
        visit = Visit(patient_id=kid.id, doctor_id=tech.id,
                      visit_date=local_today())
        db.session.add(visit)
        db.session.flush()

        blood = VisitInvestigation(visit_id=visit.id, patient_id=kid.id,
                                   kind="lab", name="صورة دم كاملة",
                                   status="requested")
        echo = VisitInvestigation(visit_id=visit.id, patient_id=kid.id,
                                  kind="imaging", name="إيكو قلب ECHO",
                                  status="requested")
        db.session.add_all([blood, echo])
        db.session.commit()
        ids = {"tech": tech.id, "kid": kid.id, "visit": visit.id,
               "blood": blood.id, "echo": echo.id}

    def sign_in(username="tech"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _order(ctx, which):
    from app.models.visit import VisitInvestigation
    return ctx["db"].session.get(VisitInvestigation, ctx["ids"][which])


# --------------------------------------------- the rack is the lab's own --
def test_the_bench_list_is_the_lab_only(rack):
    """The bug in the photo."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        names = [r.name for r in bench.worklist()]

    assert "صورة دم كاملة" in names
    assert "إيكو قلب ECHO" not in names, \
        "the lab's rack is still listing scans"


def test_the_benchs_counters_are_the_labs_own(rack):
    """A bench told it has two to draw, one of which is an echo, has been
    given a number it cannot work to."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        assert bench.counts()["to_collect"] == 1


def test_asking_for_both_still_gets_both(rack):
    """The default changed; the capability did not. A caller that genuinely
    wants the whole table can still say so."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        names = [r.name for r in bench.worklist(kind=None)]

    assert len(names) == 2


def test_the_lab_screen_does_not_show_the_echo(rack):
    """From the screen's own side, which is where it was seen."""
    with rack["app"].app_context():
        html = rack["sign_in"]().get("/labs/").get_data(as_text=True)

    assert "صورة دم كاملة" in html
    assert "إيكو قلب ECHO" not in html


# --------------------------------- a scan has no tube, and cannot pretend --
def test_collecting_a_scan_is_refused(rack):
    """**The dangerous one.** Before this, `collect()` would have written a
    sample code and a collection time onto an echocardiogram — a record of a
    thing that did not happen, on a child's file, in the clinic's own words.
    """
    from app.utils import labs as bench

    with rack["app"].app_context():
        echo = _order(rack, "echo")
        with pytest.raises(ValueError):
            bench.collect(echo, user=None)

        rack["db"].session.rollback()
        echo = _order(rack, "echo")
        assert echo.sample_code is None
        assert echo.collected_at is None
        assert echo.status == "requested", "the refused order moved anyway"


def test_the_screen_refuses_it_too(rack):
    """A guard in the util that the route walks straight past is not a
    guard."""
    with rack["app"].app_context():
        answer = rack["sign_in"]().post(
            "/labs/order/%s/collect" % rack["ids"]["echo"],
            follow_redirects=True)

        echo = _order(rack, "echo")
        assert echo.collected_at is None, \
            "the screen stamped a sample time on a scan"
        assert echo.sample_code is None
        assert answer.status_code in (200, 302, 403, 404)


def test_performing_a_blood_test_is_refused_the_same_way(rack):
    """Both directions. A one-sided guard is half a rule, and the half that
    is missing is the one somebody eventually walks through."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        with pytest.raises(ValueError):
            bench.perform(_order(rack, "blood"), user=None)


# ----------------------------------------- the scan's own event and state --
def test_a_performed_scan_carries_its_own_stamp(rack):
    """`performed_at`, not `collected_at` — the whole reason the column
    exists."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        echo = _order(rack, "echo")
        bench.perform(echo, user=None, at=datetime(2026, 9, 14, 10, 0))
        rack["db"].session.commit()

        echo = _order(rack, "echo")
        assert echo.performed_at == datetime(2026, 9, 14, 10, 0)
        assert echo.collected_at is None, "a scan was given a collection time"
        assert echo.sample_code is None


def test_a_performed_scan_is_still_unanswered(rack):
    """**The shared state, and why it is shared.** Every screen outside the
    bench asks «has this been answered», never «which stage is it at» — so a
    scan that has been done has to stay in the open set, exactly as a drawn
    sample does."""
    from app.models.visit import INVESTIGATION_OPEN
    from app.utils import labs as bench

    with rack["app"].app_context():
        bench.perform(_order(rack, "echo"), user=None)
        rack["db"].session.commit()

        echo = _order(rack, "echo")
        assert echo.status in INVESTIGATION_OPEN
        assert echo.status != "resulted"


def test_there_is_no_fourth_state(rack):
    """Named so the next person reads the note before adding one. The last
    new state cost four screens; this one was not needed at all."""
    from app.models.visit import INVESTIGATION_STATUSES

    assert INVESTIGATION_STATUSES == ["requested", "collected", "resulted"]


def test_one_reader_for_the_middle_event_whichever_kind(rack):
    """A screen showing both — the doctor's own file view — should not have to
    know which column belongs to which kind."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        bench.perform(_order(rack, "echo"), user=None,
                      at=datetime(2026, 9, 14, 10, 0))
        bench.collect(_order(rack, "blood"), user=None,
                      at=datetime(2026, 9, 14, 11, 0))
        rack["db"].session.commit()

        assert bench.done_at(_order(rack, "echo")) == datetime(2026, 9, 14, 10, 0)
        assert bench.done_at(_order(rack, "blood")) == datetime(2026, 9, 14, 11, 0)
        assert bench.done_at(None) is None


def test_a_scan_that_has_not_been_done_has_no_time(rack):
    from app.utils import labs as bench

    with rack["app"].app_context():
        assert bench.done_at(_order(rack, "echo")) is None


# ------------------------------------------ the scans got their own room --

def test_the_imaging_screen_lists_the_scan_and_not_the_blood(rack):
    with rack["app"].app_context():
        html = rack["sign_in"]().get("/imaging/").get_data(as_text=True)

    assert "إيكو قلب ECHO" in html
    assert "صورة دم كاملة" not in html


def test_there_is_a_door_to_it_from_the_rack(rack):
    """**An order nobody can see is an order nobody does.** Filtering the
    scans out of the lab and stopping there would have been the worse bug, so
    the link — and the count — sit where the person who used to see them in
    that list will look."""
    with rack["app"].app_context():
        html = rack["sign_in"]().get("/labs/").get_data(as_text=True)

    assert "data-to-imaging" in html, "the scans have no door"
    assert "/imaging/" in html


def test_the_door_carries_the_count_so_nothing_goes_quiet(rack):
    """One outstanding echo, said on the lab screen even though the lab
    screen no longer lists it."""
    with rack["app"].app_context():
        html = rack["sign_in"]().get("/labs/").get_data(as_text=True)

    marker = html.split("data-to-imaging", 1)[1][:400]
    assert ">1<" in marker, "the door does not say how many are waiting"


def test_and_a_door_back(rack):
    with rack["app"].app_context():
        html = rack["sign_in"]().get("/imaging/").get_data(as_text=True)

    assert "data-to-lab" in html


def test_the_scan_screen_offers_done_not_drawn(rack):
    """The words are the point. A scan is performed; it is never drawn."""
    from app.i18n import translate as t

    with rack["app"].app_context():
        html = rack["sign_in"]().get("/imaging/").get_data(as_text=True)

        assert t("imaging.mark_done") in html
        assert "data-not-done" in html
        assert t("lab.needs_sample") not in html, \
            "the scan screen is asking somebody to draw a sample"


def test_marking_it_done_through_the_screen(rack):
    from app.utils import labs as bench

    with rack["app"].app_context():
        rack["sign_in"]().post(
            "/imaging/order/%s/performed" % rack["ids"]["echo"],
            follow_redirects=True)

        echo = _order(rack, "echo")
        assert echo.performed_at is not None
        assert echo.collected_at is None, "the screen stamped a sample time"
        assert echo.sample_code is None
        assert echo.status == "collected"
        assert bench.done_at(echo) == echo.performed_at


def test_the_screen_will_not_perform_a_blood_test(rack):
    """Somebody on the wrong screen, refused and told which."""
    with rack["app"].app_context():
        rack["sign_in"]().post(
            "/imaging/order/%s/performed" % rack["ids"]["blood"],
            follow_redirects=True)

        blood = _order(rack, "blood")
        assert blood.performed_at is None
        assert blood.status == "requested"


def test_a_done_scan_moves_to_the_waiting_for_a_report_count(rack):
    """The two jobs, in this room's own words."""
    from app.utils import labs as bench

    with rack["app"].app_context():
        assert bench.counts(bench.IMAGING) == {"to_collect": 1, "to_run": 0}

        bench.perform(_order(rack, "echo"), user=None)
        rack["db"].session.commit()

        assert bench.counts(bench.IMAGING) == {"to_collect": 0, "to_run": 1}
        # ...and the lab's own numbers never moved.
        assert bench.counts(bench.LAB) == {"to_collect": 1, "to_run": 0}


def test_the_scan_screen_is_behind_the_same_module_as_the_lab(rack):
    """**Deliberately not a module of its own.** A new module ships *off*, so
    one here would have hidden every outstanding scan from every clinic
    already running — the exact failure this screen undoes."""
    from app.models import Setting

    with rack["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        rack["db"].session.commit()

        answer = rack["sign_in"]().get("/imaging/", follow_redirects=False)

    assert answer.status_code in (302, 403, 404), \
        "the scan screen is open on a clinic with the module switched off"


# =====================================================================
# And then: a chest film is not an echo either.
#
# > «الاشعة العادية غير الايكو واللترا سونت وال eeg و ال ECG خد بالك بس»
#
# One room along from the first bug. A film is taken in radiology and reported
# by a radiologist; a sonar, an echo, an ECG and an EEG are done by the
# treating team — the clinic room, cardiology, neurophysiology. The person on
# the X-ray machine is not the echo list's cover.
#
# `diagnostic` is a **third kind**, and the note above INVESTIGATION_STATUSES
# is the reason this section is as long as it is: a new value in a shared
# vocabulary does not make screens learn it. Everything that asked
# `kind == "imaging"` to mean *not a lab test* had to be found.


@pytest.fixture()
def three_rooms(rack):
    """A blood count, a chest film and an echo — one order each."""
    from app.models.visit import VisitInvestigation

    with rack["app"].app_context():
        film = VisitInvestigation(visit_id=rack["ids"]["visit"],
                                  patient_id=rack["ids"]["kid"],
                                  kind="imaging", name="أشعة صدر",
                                  status="requested")
        rack["db"].session.add(film)
        rack["db"].session.commit()
        rack["ids"]["film"] = film.id
        # the echo from the base fixture moves to its real room
        echo = _order(rack, "echo")
        echo.kind = "diagnostic"
        rack["db"].session.commit()
    return rack


def test_the_two_rooms_do_not_read_each_others_lists(three_rooms):
    from app.utils import labs as bench

    with three_rooms["app"].app_context():
        radiology = [r.name for r in bench.worklist(kind=bench.IMAGING)]
        studies = [r.name for r in bench.worklist(kind=bench.DIAGNOSTIC)]

    assert radiology == ["أشعة صدر"]
    assert studies == ["إيكو قلب ECHO"]


def test_each_room_has_its_own_screen(three_rooms):
    with three_rooms["app"].app_context():
        client = three_rooms["sign_in"]()
        xray = client.get("/imaging/").get_data(as_text=True)
        studies = client.get("/imaging/diagnostics").get_data(as_text=True)

    assert "أشعة صدر" in xray and "إيكو قلب ECHO" not in xray
    assert "إيكو قلب ECHO" in studies and "أشعة صدر" not in studies


def test_each_room_carries_a_door_to_the_other_with_its_count(three_rooms):
    """Splitting a list must never be the thing that makes an order go
    quiet."""
    with three_rooms["app"].app_context():
        client = three_rooms["sign_in"]()
        xray = client.get("/imaging/").get_data(as_text=True)
        studies = client.get("/imaging/diagnostics").get_data(as_text=True)

    for html in (xray, studies):
        assert "data-to-other" in html
        marker = html.split("data-to-other", 1)[1][:420]
        assert ">1<" in marker, "the door does not say how many are waiting"


def test_the_rack_has_a_door_to_both(three_rooms):
    with three_rooms["app"].app_context():
        html = three_rooms["sign_in"]().get("/labs/").get_data(as_text=True)

    assert "data-to-imaging" in html
    assert "data-to-diagnostics" in html


def test_a_study_is_performed_not_drawn_either(three_rooms):
    """Both rooms are on the same side of the rule: nothing here has a tube."""
    from app.utils import labs as bench

    with three_rooms["app"].app_context():
        with pytest.raises(ValueError):
            bench.collect(_order(three_rooms, "echo"), user=None)
        three_rooms["db"].session.rollback()

        bench.perform(_order(three_rooms, "echo"), user=None)
        bench.perform(_order(three_rooms, "film"), user=None)
        three_rooms["db"].session.commit()

        assert _order(three_rooms, "echo").performed_at is not None
        assert _order(three_rooms, "film").performed_at is not None
        assert _order(three_rooms, "echo").collected_at is None


def test_done_lands_back_in_the_room_it_was_pressed_in(three_rooms):
    with three_rooms["app"].app_context():
        answer = three_rooms["sign_in"]().post(
            "/imaging/order/%s/performed" % three_rooms["ids"]["echo"])

    assert "/imaging/diagnostics" in answer.headers.get("Location", "")


# ------------------------------- what a third value costs, paid explicitly --
def test_the_printed_prescription_still_carries_both(three_rooms):
    """**The one that would have gone unnoticed.** `Prescription.imaging()` is
    what prints on the paper the family walks out with. It asked for
    `kind == "imaging"` exactly, so adding a third kind would have silently
    dropped every echo and ECG off the printout."""
    from app.models import NOT_A_SAMPLE
    from app.models.prescription import Prescription, PrescriptionInvestigation

    with three_rooms["app"].app_context():
        rx = Prescription(patient_id=three_rooms["ids"]["kid"],
                          doctor_id=three_rooms["ids"]["tech"])
        three_rooms["db"].session.add(rx)
        three_rooms["db"].session.flush()
        for kind, name in (("imaging", "أشعة صدر"), ("diagnostic", "إيكو")):
            three_rooms["db"].session.add(PrescriptionInvestigation(
                prescription_id=rx.id, kind=kind, name=name))
        three_rooms["db"].session.commit()

        printed = [x.name for x in rx.imaging()]

    assert printed == ["أشعة صدر", "إيكو"], \
        "a study dropped off the printed prescription"
    assert set(NOT_A_SAMPLE) == {"imaging", "diagnostic"}


def test_a_doctor_can_actually_order_one(three_rooms):
    """A kind the order box does not offer is a kind nobody can ask for."""
    from app.i18n import translate as t

    with three_rooms["app"].app_context():
        html = three_rooms["sign_in"]().get(
            "/visits/%s/record" % three_rooms["ids"]["visit"]).get_data(as_text=True)

        assert 'value="diagnostic"' in html, \
            "the order box offers no way to ask for an ECG"
        assert t("rx.inv_diagnostic") in html


# ------------------------------------- the move of a clinic's own records --
def test_the_seeded_studies_move_and_the_films_stay(three_rooms):
    """A clinic that upgrades finds its echoes where the echo team looks."""
    from app.models import Investigation
    from app.utils.investigations import move_diagnostics_out_of_radiology

    with three_rooms["app"].app_context():
        db = three_rooms["db"]
        db.session.add_all([
            Investigation(name_ar="إيكو على القلب", kind="imaging",
                          category="قلب", is_active=True),
            Investigation(name_ar="موجات صوتية على البطن", kind="imaging",
                          category="سونار", is_active=True),
            Investigation(name_ar="أشعة صدر", kind="imaging",
                          category="أشعة عادية", is_active=True),
        ])
        db.session.commit()

        assert move_diagnostics_out_of_radiology() == 2

        kinds = {i.name_ar: i.kind for i in Investigation.query.all()}
        assert kinds["إيكو على القلب"] == "diagnostic"
        assert kinds["موجات صوتية على البطن"] == "diagnostic"
        assert kinds["أشعة صدر"] == "imaging", "a film was moved out of radiology"


def test_the_move_leaves_a_clinics_own_words_alone(three_rooms):
    """**It moves only the program's own vocabulary.** A category somebody
    typed is theirs, and guessing at it refiles a catalogue on an assumption
    nobody made — which here hides a child's outstanding order on a screen
    that department never opens."""
    from app.models import Investigation
    from app.utils.investigations import move_diagnostics_out_of_radiology

    with three_rooms["app"].app_context():
        three_rooms["db"].session.add(
            Investigation(name_ar="إيكو بتاعنا", kind="imaging",
                          category="قسم القلب عندنا", is_active=True))
        three_rooms["db"].session.commit()

        move_diagnostics_out_of_radiology()

        row = Investigation.query.filter_by(name_ar="إيكو بتاعنا").first()
        assert row.kind == "imaging", "somebody else's category was guessed at"


def test_the_orders_move_with_their_catalogue_row(three_rooms):
    """An order carries its own `kind` as a snapshot, so it would keep
    pointing at radiology after the catalogue moved — and it is followed by
    `investigation_id`, never by a name that merely looks similar."""
    from app.models import Investigation
    from app.models.visit import VisitInvestigation
    from app.utils.investigations import move_diagnostics_out_of_radiology

    with three_rooms["app"].app_context():
        db = three_rooms["db"]
        cat = Investigation(name_ar="إيكو على القلب", kind="imaging",
                            category="قلب", is_active=True)
        db.session.add(cat)
        db.session.flush()
        linked = VisitInvestigation(visit_id=three_rooms["ids"]["visit"],
                                    patient_id=three_rooms["ids"]["kid"],
                                    investigation_id=cat.id, kind="imaging",
                                    name="إيكو على القلب", status="requested")
        free = VisitInvestigation(visit_id=three_rooms["ids"]["visit"],
                                  patient_id=three_rooms["ids"]["kid"],
                                  kind="imaging", name="إيكو على القلب",
                                  status="requested")
        db.session.add_all([linked, free])
        db.session.commit()
        ids = (linked.id, free.id)

        move_diagnostics_out_of_radiology()

        moved = db.session.get(VisitInvestigation, ids[0])
        typed = db.session.get(VisitInvestigation, ids[1])
        assert moved.kind == "diagnostic"
        assert typed.kind == "imaging", \
            "a free-typed order was moved on the strength of its name"


def test_the_move_is_idempotent(three_rooms):
    """It runs on every upgrade. A second pass must find nothing."""
    from app.models import Investigation
    from app.utils.investigations import move_diagnostics_out_of_radiology

    with three_rooms["app"].app_context():
        three_rooms["db"].session.add(
            Investigation(name_ar="إيكو على القلب", kind="imaging",
                          category="قلب", is_active=True))
        three_rooms["db"].session.commit()

        assert move_diagnostics_out_of_radiology() == 1
        assert move_diagnostics_out_of_radiology() == 0


def test_ecg_and_eeg_are_in_the_catalogue_at_all(three_rooms):
    """They were in no catalogue anywhere, so a doctor who wanted one had to
    free-type it and it reached no worklist under a name anything could group
    by."""
    from app.models import Investigation
    from app.utils.investigations import seed_investigations

    with three_rooms["app"].app_context():
        seed_investigations()

        rows = {i.name_en: i for i in Investigation.query.all()}
        assert "ECG" in rows and rows["ECG"].kind == "diagnostic"
        assert "EEG" in rows and rows["EEG"].kind == "diagnostic"
        assert rows["Chest X-ray"].kind == "imaging"
        assert rows["Echocardiography"].kind == "diagnostic"
