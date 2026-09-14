"""A child was admitted, and their file never said so.

Everything on this screen was already in the database and already hanging off
the right child — the stay, the beds they moved through, the operation, the
ward rounds. What was missing was **a way in**.

``beds.open_admission`` answers *where is this child now*, which is a ward
question. Once the child went home, their stay was reachable only by already
knowing its id: the file's tabs had no stay in them, and the "comprehensive"
medical report had none either. So a doctor seeing the child again could not
learn from the record that they had ever been admitted.

The program had said this was wrong in its own words before it was built.
``Admission``'s docstring quotes ``HOSPITAL_PLAN.md`` ٨:

    «ملف الطفل واحد. لو الطفل اتنوّم، التنويم بيظهر في نفس الملف.»

And GAHAR IMT.08 asks for it twice — the record's contents are standardized
(evidence 4), and it is *available when needed by a healthcare professional*
(evidence 5). A stay nobody can reach is neither.

Four things this suite pins:

* **A closed stay is on the file.** The open one always was; the closed one is
  the whole finding.
* **The tab is absent when there is nothing in it**, like the imported-history
  tab beside it — a "stays" tab on the file of a child who was never admitted
  is furniture, and most files are those.
* **The beds are listed in the order they happened.** A stay carries its beds
  rather than one ``bed_id`` precisely so a move reads as one stay in two
  places, and that is the internal-movement record.
* **The operations of the stay hang under the stay.** The link has existed
  since the theatres module was built and nothing read it from this side.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.place import Bed, Space, Unit
        from app.utils.clock import local_today

        Setting.set("mod_enabled:beds", "1")
        Setting.set("mod_enabled:theatres", "1")
        Setting.set("mod_enabled:patients", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        unit = Unit(name="العنبر", kind="ward")
        db.session.add_all([boss, unit])
        db.session.flush()
        space = Space(unit_id=unit.id, name="أوضة ١")
        room2 = Space(unit_id=unit.id, name="العزل")
        db.session.add_all([space, room2])
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير ١")
        other = Bed(space_id=room2.id, name="سرير ٢")
        db.session.add_all([bed, other])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        never = Patient(patient_number="P2", full_name="طفلة", gender="female",
                        is_active=True,
                        date_of_birth=local_today() - timedelta(days=700))
        db.session.add_all([kid, never])
        db.session.commit()
        ids = {"boss": boss.id, "kid": kid.id, "never": never.id,
               "bed": bed.id, "other": other.id}

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _kid(ctx, which="kid"):
    from app.models import Patient
    return ctx["db"].session.get(Patient, ctx["ids"][which])


def _bed(ctx, which="bed"):
    from app.models import Bed
    return ctx["db"].session.get(Bed, ctx["ids"][which])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _card(html, stay_id):
    """The one stay's card, and nothing else on the file.

    Anchored on ``data-stay`` rather than on the tab panel: the point of most
    of these assertions is that a thing is under **this** stay, and a search
    over the whole page would pass on the copy of it further up the file.
    """
    marker = 'data-stay="%s"' % stay_id
    assert marker in html, "no card for stay %s" % stay_id
    rest = html.split(marker, 1)[1]
    return rest.split("data-stay=", 1)[0]


def _a_stay(ctx, days_ago=10, nights=3, reason="التهاب رئوي"):
    """One finished stay, ``days_ago`` days back."""
    from app.utils import beds as ward

    stay = ward.admit(_kid(ctx), _bed(ctx), user=_boss(ctx), reason=reason,
                      when=datetime.utcnow() - timedelta(days=days_ago))
    ctx["db"].session.commit()
    ward.discharge(stay, "home", user=_boss(ctx), note="اتحسّن وخرج",
                   when=datetime.utcnow() - timedelta(days=days_ago - nights))
    ctx["db"].session.commit()
    return stay


# ------------------------------------------------ the helper --------------
def test_a_child_who_was_never_admitted_has_no_stays(clinic):
    from app.utils import beds as ward

    with clinic["app"].app_context():
        assert ward.stays_for(clinic["ids"]["never"]) == []


def test_a_finished_stay_is_found_which_is_the_whole_point(clinic):
    """``open_admission`` returns ``None`` the moment the child goes home —
    and that was the only question the program could ask."""
    from app.utils import beds as ward

    with clinic["app"].app_context():
        stay = _a_stay(clinic)
        assert ward.open_admission(clinic["ids"]["kid"]) is None
        assert [s.id for s in ward.stays_for(clinic["ids"]["kid"])] == [stay.id]


def test_open_and_closed_stays_come_back_together_newest_first(clinic):
    """A record that showed only the finished ones, or only the live one,
    would be a different half of the same gap."""
    from app.utils import beds as ward

    with clinic["app"].app_context():
        old = _a_stay(clinic, days_ago=40)
        recent = _a_stay(clinic, days_ago=10)
        live = ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()

        rows = ward.stays_for(clinic["ids"]["kid"])
        assert [s.id for s in rows] == [live.id, recent.id, old.id]
        assert [s.is_open for s in rows] == [True, False, False]


def test_one_childs_stays_only(clinic):
    from app.utils import beds as ward

    with clinic["app"].app_context():
        _a_stay(clinic)
        assert ward.stays_for(clinic["ids"]["never"]) == []


def test_the_beds_a_stay_passed_through_come_with_it(clinic):
    """A stay carries its beds rather than one ``bed_id``, so a child moved
    into isolation reads as **one stay in two places** — which is the
    internal-movement record, not a detail."""
    from app.utils import beds as ward

    with clinic["app"].app_context():
        stay = ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        ward.move(stay, _bed(clinic, "other"), user=_boss(clinic))
        clinic["db"].session.commit()

        row = ward.stays_for(clinic["ids"]["kid"])[0]
        assert [bs.bed.name for bs in row.stays] == ["سرير ١", "سرير ٢"]


# ------------------------------------------------ through the file --------
def test_the_file_of_a_child_never_admitted_has_no_stays_tab(clinic):
    """A tab labelled «الإقامات» on a file with nothing behind it is
    furniture — the same rule the imported-history tab beside it keeps, and
    most of a paediatric clinic's files are this one."""
    with clinic["app"].app_context():
        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["never"]).get_data(as_text=True)
        assert 'data-tab="stays"' not in html


def test_a_finished_stay_shows_on_the_file(clinic):
    """**The finding itself.** Before this the child's file said nothing about
    having been admitted at all."""
    from app.i18n import translate as t

    with clinic["app"].app_context():
        stay = _a_stay(clinic)
        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert 'data-tab="stays"' in html
        assert t("patients.tab_stays") in html
        # The stay itself, reachable — the id was the only way in before.
        assert "/beds/admission/%s" % stay.id in html
        assert "التهاب رئوي" in html
        # How it ended, in the clinic's own words rather than a timestamp.
        assert t("beds.outcome_home") in html
        assert "اتحسّن وخرج" in html


def test_the_file_says_where_the_child_was(clinic):
    from app.utils import beds as ward

    with clinic["app"].app_context():
        stay = ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        ward.move(stay, _bed(clinic, "other"), user=_boss(clinic))
        clinic["db"].session.commit()

        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert "العنبر" in html
        assert "أوضة ١" in html and "العزل" in html
        assert "سرير ١" in html and "سرير ٢" in html


def test_a_stay_still_running_says_so_rather_than_looking_finished(clinic):
    """An open stay with no end date and no outcome would read as a stay that
    ended and nobody wrote down how."""
    from app.i18n import translate as t
    from app.utils import beds as ward

    with clinic["app"].app_context():
        ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert "data-stay-open" in html
        assert t("beds.still_in") in html


def test_the_operation_done_during_a_stay_hangs_under_that_stay(clinic):
    """``Operation.admission_id`` has existed since the theatres module was
    built and nothing read it from the file's side — so a stay and the
    operation done in it were two unrelated entries in a child's record."""
    from app.models.theatre import Operation, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        stay = _a_stay(clinic)
        room = Theatre(name="غرفة ١")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        case = Operation(patient_id=clinic["ids"]["kid"], theatre_id=room.id,
                         procedure="استئصال زائدة", on_date=local_today(),
                         admission_id=stay.id, status="done")
        clinic["db"].session.add(case)
        clinic["db"].session.commit()

        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        # In the stay's own card, not only in the list further up the file.
        card = _card(html, stay.id)
        assert "استئصال زائدة" in card
        assert "/theatres/operation/%s" % case.id in card


def test_an_operation_from_another_stay_does_not_leak_into_this_one(clinic):
    """Two stays a year apart, each with its own theatre case. Filtering on
    the wrong thing would put both under both."""
    from app.models.theatre import Operation, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        first = _a_stay(clinic, days_ago=400, reason="الإقامة القديمة")
        second = _a_stay(clinic, days_ago=10, reason="الإقامة الجديدة")
        room = Theatre(name="غرفة ١")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        for stay, name in ((first, "عملية قديمة"), (second, "عملية جديدة")):
            clinic["db"].session.add(
                Operation(patient_id=clinic["ids"]["kid"], theatre_id=room.id,
                          procedure=name, on_date=local_today(),
                          admission_id=stay.id, status="done"))
        clinic["db"].session.commit()

        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        # Each case in its own stay's card, and in neither other.
        old_card, new_card = _card(html, first.id), _card(html, second.id)
        assert "عملية قديمة" in old_card and "عملية جديدة" not in old_card
        assert "عملية جديدة" in new_card and "عملية قديمة" not in new_card
        # And each card is the stay it says it is.
        assert "الإقامة القديمة" in old_card
        assert "الإقامة الجديدة" in new_card


def test_the_ward_rounds_of_a_stay_are_counted_on_it(clinic):
    """The thread through a stay. A file that showed the stay but not that
    anybody walked round it says less than the ward board does."""
    from app.i18n import translate as t
    from app.models.round_note import RoundNote

    with clinic["app"].app_context():
        stay = _a_stay(clinic)
        for _ in range(3):
            clinic["db"].session.add(
                RoundNote(admission_id=stay.id, patient_id=clinic["ids"]["kid"],
                          by_id=clinic["ids"]["boss"], trend="same"))
        clinic["db"].session.commit()

        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert t("beds.rounds_written", n=3) in html


def test_a_clinic_with_no_ward_never_sees_the_tab(clinic):
    """A module switched off is a module absent, not a dead tab — the same
    rule `_ward_context` already kept for the free-bed line."""
    with clinic["app"].app_context():
        from app.models import Setting

        _a_stay(clinic)
        Setting.set("mod_enabled:beds", "0")
        clinic["db"].session.commit()
        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert 'data-tab="stays"' not in html


def test_a_stay_written_up_late_still_sorts_by_when_it_happened(clinic):
    """**The order is the stay's, not the typist's.**

    A nurse writes up yesterday's admission this morning, so the row with the
    higher id is the *older* stay. Sorted by id — which reads correctly in
    every fixture where the two agree — that stay would jump to the top of the
    file and the record would say the child's most recent admission was the
    one before last.
    """
    from app.utils import beds as ward

    with clinic["app"].app_context():
        # Entered first, happened last.
        recent = _a_stay(clinic, days_ago=5, nights=1, reason="الأحدث")
        older = _a_stay(clinic, days_ago=30, nights=2, reason="الأقدم")
        assert older.id > recent.id      # the fixture is doing its job

        rows = ward.stays_for(clinic["ids"]["kid"])
        assert [s.id for s in rows] == [recent.id, older.id]

        html = clinic["sign_in"]().get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)
        assert html.index("الأحدث") < html.index("الأقدم")


# ------------------------------------- and the sheet that leaves the building
def _report(ctx):
    return ctx["sign_in"]().get(
        "/patients/%s/report" % ctx["ids"]["kid"]).get_data(as_text=True)


def test_the_medical_report_carries_the_stays(clinic):
    """It called itself comprehensive and had demographics, problems, growth,
    vaccinations, visits and drugs — a complete account of a child who has
    never been admitted, and a misleading one about a child who has. This is
    the form the record most often leaves the building in."""
    from app.i18n import translate as t

    with clinic["app"].app_context():
        stay = _a_stay(clinic, reason="التهاب رئوي")
        html = _report(clinic)
        assert t("report.stays") in html
        assert "التهاب رئوي" in html
        assert t("beds.outcome_home") in html
        # **Both ends of it.** With only the admission date printed, a stay of
        # three nights and a stay of three weeks read the same on the paper.
        assert str(stay.admitted_at.date()) in html
        assert str(stay.discharged_at.date()) in html
        assert stay.admitted_at.date() != stay.discharged_at.date()


def test_the_report_says_where_the_child_was(clinic):
    """The units, each named once. A child moved from the bay to isolation was
    in two places on one stay, and printing only the last says they were never
    in the first."""
    from app.models.place import Space, Unit
    from app.utils import beds as ward

    with clinic["app"].app_context():
        from app.models import Bed

        isolation = Unit(name="العزل العام", kind="icu")
        clinic["db"].session.add(isolation)
        clinic["db"].session.flush()
        room = Space(unit_id=isolation.id, name="أوضة العزل")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        far = Bed(space_id=room.id, name="سرير العزل")
        clinic["db"].session.add(far)
        clinic["db"].session.commit()

        stay = ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        ward.move(stay, far, user=_boss(clinic))
        clinic["db"].session.commit()

        html = _report(clinic)
        assert "العنبر" in html
        assert "العزل العام" in html


def test_a_unit_the_child_went_back_to_is_named_once(clinic):
    """Bay → isolation → bay is three bed-stays in two units. Printing the
    unit per bed-stay would put the first one twice and read as three."""
    from app.utils import beds as ward

    with clinic["app"].app_context():
        stay = ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        ward.move(stay, _bed(clinic, "other"), user=_boss(clinic))
        clinic["db"].session.commit()
        ward.move(stay, _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()

        html = _report(clinic)
        # Both beds are in the same unit here, so it is named exactly once.
        section = html.split("<!-- Stays in hospital -->", 1)[1]
        section = section.split("<!-- Operations -->", 1)[0]
        assert section.count("العنبر") == 1


def test_a_stay_with_no_bed_on_it_prints_a_dash_not_a_blank_cell(clinic):
    """A stay whose bed rows are gone — an import, a bed deleted under it — is
    a stay whose place nobody can state. An empty cell in a printed table
    reads as a column the printer clipped; a dash says the program looked and
    had no answer."""
    from app.models.admission import Admission

    with clinic["app"].app_context():
        clinic["db"].session.add(
            Admission(patient_id=clinic["ids"]["kid"], reason="بدون سرير",
                      admitted_at=datetime.utcnow() - timedelta(days=2),
                      discharged_at=datetime.utcnow(), outcome="home"))
        clinic["db"].session.commit()

        html = _report(clinic)
        section = html.split("<!-- Stays in hospital -->", 1)[1]
        row = section.split("بدون سرير", 1)[1].split("</tr>", 1)[0]
        assert "—" in row


def test_a_stay_still_running_is_not_given_an_outcome_on_the_report(clinic):
    """A dash in the outcome column would read as a stay that ended and
    nobody wrote down how."""
    from app.i18n import translate as t
    from app.utils import beds as ward

    with clinic["app"].app_context():
        ward.admit(_kid(clinic), _bed(clinic), user=_boss(clinic))
        clinic["db"].session.commit()
        html = _report(clinic)
        assert t("beds.still_in") in html


def test_the_medical_report_carries_the_operations(clinic):
    """Day cases and inpatient ones together: «what has been done to this
    child» is one question, and a day-case circumcision belongs to no stay at
    all."""
    from app.i18n import translate as t
    from app.models.theatre import Operation, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        stay = _a_stay(clinic)
        room = Theatre(name="غرفة ١")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        clinic["db"].session.add_all([
            Operation(patient_id=clinic["ids"]["kid"], theatre_id=room.id,
                      procedure="استئصال زائدة", on_date=local_today(),
                      admission_id=stay.id, status="done"),
            # No stay behind this one — the child came in and went home.
            Operation(patient_id=clinic["ids"]["kid"], theatre_id=room.id,
                      procedure="ختان", on_date=local_today(), status="done"),
        ])
        clinic["db"].session.commit()

        html = _report(clinic)
        assert t("report.operations") in html
        assert "استئصال زائدة" in html
        assert "ختان" in html


def test_the_surgical_history_on_the_report_is_not_truncated(clinic):
    """Ten recent visits is a labelled sample of an outpatient history. Ten of
    fourteen operations is a surgical history that reads complete and is
    not."""
    from app.models.theatre import Operation, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        room = Theatre(name="غرفة ١")
        clinic["db"].session.add(room)
        clinic["db"].session.flush()
        for n in range(14):
            clinic["db"].session.add(
                Operation(patient_id=clinic["ids"]["kid"], theatre_id=room.id,
                          procedure="إجراء رقم %s" % n,
                          on_date=local_today() - timedelta(days=n),
                          status="done"))
        clinic["db"].session.commit()

        html = _report(clinic)
        for n in range(14):
            assert "إجراء رقم %s" % n in html


def test_a_clinic_with_no_ward_prints_no_stays_heading(clinic):
    """A module off is a module absent, not an empty heading on the paper."""
    from app.i18n import translate as t

    with clinic["app"].app_context():
        from app.models import Setting

        _a_stay(clinic)
        Setting.set("mod_enabled:beds", "0")
        clinic["db"].session.commit()
        html = _report(clinic)
        assert t("report.stays") not in html


def test_a_child_never_admitted_prints_no_stays_heading(clinic):
    """The heading appears because there is something under it."""
    from app.i18n import translate as t

    with clinic["app"].app_context():
        html = clinic["sign_in"]().get(
            "/patients/%s/report" % clinic["ids"]["never"]).get_data(as_text=True)
        assert t("report.stays") not in html
        assert t("report.operations") not in html
