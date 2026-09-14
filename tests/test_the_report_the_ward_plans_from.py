"""What happened in the room, written before the child leaves it — SAS.08.

> Surgical or invasive procedure details are recorded **immediately after the
> procedure** … **before the patient leaves the procedural unit**. Planning
> for postoperative care depends on findings and special events that occurred
> during the procedure, as **failure to report these events markedly
> compromises patient care**.
>
> a) start and end time · b) all staff including anaesthesia ·
> c) **pre- and post-procedure diagnoses** · d) the procedure with details and
> findings · e) implants **including the batch number** · f) **the occurrence
> of complications or not** · g) **any removed specimen or not** ·
> h) estimated blood loss and/or transfused blood · i) signature of the
> performing physician.

**Five of the nine were already in the record**, and the program does not ask
a surgeon to type them twice: the two stamps, the surgeon and anaesthetist and
team, the procedure and findings, and every implant with its lot number —
element (e)'s *"including the batch number"* was answered by work done for
SAS.06 (ز) and SAS.11 long before this standard was read.

Five things this suite pins:

* **«or not» is the standard writing this program's own rule down.** Elements
  (f) and (g) ask for the occurrence of complications *or not*, and a specimen
  *or not*. A blank is not "there were none"; it is nobody having said.
* **Two diagnoses, because they can differ** — and the standard asks that the
  discrepancy itself be documented. One field could not carry one.
* **A zero is an answer.** Blood loss of nought is real and common; only
  ``None`` is an absence, and checking for falsiness would erase the
  difference.
* **Written and signed are two events**, because in a real theatre the
  registrar writes while the surgeon scrubs out.
* **Late is the standard's own word**, measured against the moment it names —
  the child leaving the unit — and not an interval this program invented.
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
        boss = User(username="boss", full_name="د. الجرّاح", role="admin",
                    is_active=True)
        boss.set_password("secret")
        gas = User(username="gas", full_name="د. التخدير", role="doctor",
                   is_active=True)
        gas.set_password("secret")
        room = Theatre(name="غرفة ١")
        db.session.add_all([boss, gas, room])
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=900))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="استئصال زائدة", on_date=local_today(),
                         surgeon_id=boss.id, anaesthetist_id=gas.id,
                         team="ممرضة التخدير، الأدوات",
                         started_at=datetime(2026, 5, 1, 9, 0),
                         finished_at=datetime(2026, 5, 1, 10, 30),
                         findings="زائدة ملتهبة، اتشالت، الجرح اتقفل طبقات",
                         status="done")
        db.session.add(case)
        db.session.commit()
        ids = {"boss": boss.id, "gas": gas.id, "case": case.id, "kid": kid.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _case(ctx):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"]["case"])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _filled(html, letter):
    """Whether the card shows element ``letter`` as answered.

    Read off the badge rather than matched as one string: the two attributes
    sit on separate lines in the template, and an assertion needing them
    adjacent would be about the whitespace.
    """
    import re

    marker = 'data-element="%s"' % letter
    assert marker in html, "element %s is not on the card" % letter
    found = re.search(r'data-filled="(yes|no)"', html.split(marker, 1)[1])
    assert found, "element %s has no filled state" % letter
    return found.group(1)


FULL = {"pre_diagnosis": "التهاب زائدة حاد",
        "post_diagnosis": "التهاب زائدة حاد مع التهاب بريتوني موضعي",
        "complications": False, "specimen": True,
        "specimen_note": "الزائدة، راحت الباثولوجي",
        "blood_loss_ml": 30}


def _write(ctx, **over):
    from app.utils import operative_report as report

    fields = dict(FULL)
    fields.update(over)
    row = report.write(_case(ctx), user=_boss(ctx), **fields)
    ctx["db"].session.commit()
    return row


# ------------------------------------------- what the record already holds
def test_five_of_the_nine_are_never_asked_for(theatre):
    """«المهم الطبيب ميكتبش كتير». The stamps, the staff, the procedure and
    the implants are all in the record, and a second copy would be a second
    answer that drifts."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        written = {e["key"] for e in report.assemble(_case(theatre))
                   if e["written"]}
        derived = {e["key"] for e in report.assemble(_case(theatre))
                   if not e["written"]}
        assert written == {"diagnoses", "complications", "specimen", "blood"}
        assert derived == {"times", "staff", "procedure", "implants",
                           "signature"}


def test_all_nine_elements_in_the_standards_order(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        assert [e["letter"] for e in report.assemble(_case(theatre))] == \
            list("abcdefghi")


def test_the_times_come_off_the_stamps_the_theatre_already_makes(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        stamps = report.times(_case(theatre))
        assert stamps["start"] == datetime(2026, 5, 1, 9, 0)
        assert stamps["end"] == datetime(2026, 5, 1, 10, 30)
        filled = {e["key"]: e["filled"] for e in report.assemble(_case(theatre))}
        assert filled["times"] is True


def test_half_the_times_does_not_answer_element_a(theatre):
    """The standard asks for *"time of start **and** time of the end"*. A case
    that went in and whose finish nobody stamped has answered neither: the
    length of the procedure — which is what the ward reads it for — cannot be
    had from one end.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        case = _case(theatre)
        case.finished_at = None
        theatre["db"].session.commit()
        filled = {e["key"]: e["filled"] for e in report.assemble(_case(theatre))}
        assert filled["times"] is False

        case = _case(theatre)
        case.started_at, case.finished_at = None, datetime(2026, 5, 1, 10, 30)
        theatre["db"].session.commit()
        filled = {e["key"]: e["filled"] for e in report.assemble(_case(theatre))}
        assert filled["times"] is False


def test_everybody_the_record_names_including_anaesthesia(theatre):
    """Element (b) says *"including anesthesia"* by name."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        roles = {p["role"] for p in report.staff(_case(theatre))}
        assert roles == {"surgeon", "anaesthetist", "team"}


def test_the_free_text_team_is_carried_whole_not_split(theatre):
    """A program splitting a sentence on commas would invent people. The
    standard asks for the names; it does not ask the program to parse them."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        team = [p for p in report.staff(_case(theatre)) if p["role"] == "team"]
        assert team[0]["name"] == "ممرضة التخدير، الأدوات"


def test_a_case_with_nobody_named_says_so(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _case(theatre)
        row.surgeon_id = row.anaesthetist_id = None
        row.team = None
        theatre["db"].session.commit()
        assert report.staff(_case(theatre)) == []
        filled = {e["key"]: e["filled"] for e in report.assemble(_case(theatre))}
        assert filled["staff"] is False


def test_the_implants_bring_their_batch_numbers(theatre):
    """Element (e) asks for the details *"including the batch number"* — and
    that was answered for SAS.06 (ز) months before this standard was read."""
    from app.utils import operative_report as report
    from app.utils import theatres as theatres_util

    with theatre["app"].app_context():
        item = theatres_util.add_implant(_case(theatre), "شبكة",
                                         lot="L-77", manufacturer="صانع")
        theatre["db"].session.flush()
        theatres_util.record_implanted(item, lot="L-77", user=_boss(theatre))
        theatre["db"].session.commit()

        got = report.implants(_case(theatre))
        assert [i.lot for i in got] == ["L-77"]
        filled = {e["key"]: e["filled"] for e in report.assemble(_case(theatre))}
        assert filled["implants"] is True


def test_a_clinic_without_a_theatre_has_no_implants_to_list(theatre):
    """The facility shapes the file. A place that does not run a theatre is
    not shown an implants line on anything — and the helper says so itself
    rather than trusting that only the theatre screen will ever call it.

    **The implant is put in first.** The first draft of this test just turned
    the switch off on a case that had no implants at all, so it passed against
    a helper with no gate in it whatsoever — the same hollow guard that had to
    be rewritten for the facility-shaping suite.
    """
    from app.models import Setting
    from app.utils import operative_report as report
    from app.utils import theatres as theatres_util

    with theatre["app"].app_context():
        item = theatres_util.add_implant(_case(theatre), "شبكة", lot="L-77")
        theatre["db"].session.flush()
        theatres_util.record_implanted(item, lot="L-77", user=_boss(theatre))
        theatre["db"].session.commit()
        # There is something to hide.
        assert [i.lot for i in report.implants(_case(theatre))] == ["L-77"]

        Setting.set("mod_enabled:theatres", "0")
        theatre["db"].session.commit()
        assert report.implants(_case(theatre)) == []


def test_an_implant_that_was_only_prepared_is_not_in_the_report(theatre):
    """The report says what went *into* the child. An implant opened on the
    trolley and not used is a different fact — the one `OperationImplant`
    keeps apart on purpose."""
    from app.utils import operative_report as report
    from app.utils import theatres as theatres_util

    with theatre["app"].app_context():
        theatres_util.add_implant(_case(theatre), "شبكة", lot="L-77")
        theatre["db"].session.commit()
        assert report.implants(_case(theatre)) == []


# --------------------------------------------------- «or not» ------------
def test_no_complications_and_nobody_asked_are_different_answers(theatre):
    """**The standard writes this program's own rule into element (f)**: *the
    occurrence of complications **or not***."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _write(theatre, complications=None)
        assert row.complications is None
        assert "complications" in report.missing(_case(theatre))

        row = _write(theatre, complications=False)
        assert row.complications is False
        assert "complications" not in report.missing(_case(theatre))


def test_a_specimen_or_not_is_the_same_three_states(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _write(theatre, specimen=None)
        assert "specimen" in report.missing(_case(theatre))
        row = _write(theatre, specimen=False)
        assert row.specimen is False
        assert "specimen" not in report.missing(_case(theatre))


def test_the_notes_say_what_and_what_was_done(theatre):
    """The intent asks for both: *"Complications … recorded, along with the
    actions taken to manage them."*"""
    with theatre["app"].app_context():
        row = _write(theatre, complications=True,
                     complications_note="نزيف من المساريقا، اتربط")
        assert row.complications is True
        assert row.complications_note == "نزيف من المساريقا، اتربط"


# ------------------------------------------------- two diagnoses ---------
def test_both_diagnoses_are_kept_because_they_can_differ(theatre):
    """*"any similarity or discrepancy in the patient diagnoses before and
    after the procedure should be documented and clarified"* — a single field
    could not carry a discrepancy at all."""
    with theatre["app"].app_context():
        row = _write(theatre)
        assert row.pre_diagnosis == "التهاب زائدة حاد"
        assert row.post_diagnosis != row.pre_diagnosis


def test_a_diagnosis_of_spaces_is_not_a_diagnosis(theatre):
    """``blanks`` is the model's own definition of «answered», and it has to
    hold for **any** row — not only rows that came through :func:`write`,
    which strips. A record restored from a backup, or written by a later
    caller, must not have a space read as a pre-procedure diagnosis.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _write(theatre)
        row.pre_diagnosis = "   "
        theatre["db"].session.commit()
        assert "pre_diagnosis" in report.missing(_case(theatre))
        assert report.state(_case(theatre)) == "short"


def test_a_missing_post_diagnosis_leaves_the_element_unanswered(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre, post_diagnosis="")
        assert "post_diagnosis" in report.missing(_case(theatre))
        element = next(e for e in report.assemble(_case(theatre))
                       if e["letter"] == "c")
        assert element["filled"] is False


# ------------------------------------------------------ the numbers ------
def test_a_blood_loss_of_zero_is_an_answer(theatre):
    """**The trap this is written against**: checking falsiness would make
    "no measurable blood loss" and "nobody looked" the same row."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _write(theatre, blood_loss_ml=0)
        assert row.blood_loss_ml == 0
        assert "blood_loss_ml" not in report.missing(_case(theatre))


def test_no_blood_loss_written_is_an_absence(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre, blood_loss_ml=None)
        assert "blood_loss_ml" in report.missing(_case(theatre))


def test_a_negative_number_is_nobody_measured_not_nought(theatre):
    """**Clamping to nought would have been the worse bug.** Nought is a real
    answer here — «no measurable blood loss» — so a typo filed as nought is a
    measurement nobody took, sitting in the record looking like one somebody
    did. Unanswered is the truth, and it leaves (h) blank on the card so
    somebody goes back to the box.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre, blood_loss_ml=-50, transfused_units=-1)
        row = report.for_operation(_case(theatre))
        assert row.blood_loss_ml is None
        assert row.transfused_units is None
        assert "blood_loss_ml" in report.missing(_case(theatre))
        assert report.state(_case(theatre)) == "short"


def test_the_screen_will_not_file_a_negative_as_nought(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        theatre["sign_in"]().post(
            "/theatres/operation/%s/report" % theatre["ids"]["case"],
            data={"pre_diagnosis": "زائدة", "post_diagnosis": "زائدة",
                  "complications": "no", "specimen": "no",
                  "blood_loss_ml": "-50"},
            follow_redirects=True)
        assert report.for_operation(_case(theatre)).blood_loss_ml is None


def test_what_was_lost_and_what_went_back_in_are_two_numbers(theatre):
    """And both are different from the blood *reserved before* the case
    (SAS.06 و), which lives on the operation and means something else."""
    with theatre["app"].app_context():
        row = _write(theatre, blood_loss_ml=400, transfused_units=2)
        assert row.blood_loss_ml == 400
        assert row.transfused_units == 2
        assert _case(theatre).blood_units is None    # a different fact


# -------------------------------------------------------- the states ----
def test_the_four_words_and_no_others(theatre):
    """``STATES`` is the card's whole vocabulary, so it is pinned against what
    :func:`state` can actually answer — a constant nothing reads is a promise
    nobody keeps, and a fifth word appearing in one and not the other is a
    badge the template has no branch for.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        seen = {report.state(_case(theatre))}                     # none
        _write(theatre, blood_loss_ml=None)
        seen.add(report.state(_case(theatre)))                    # short
        _write(theatre)
        seen.add(report.state(_case(theatre)))                    # unsigned
        report.sign(_case(theatre), user=_boss(theatre))
        theatre["db"].session.commit()
        seen.add(report.state(_case(theatre)))                    # complete
        assert seen == set(report.STATES)
        assert len(report.STATES) == 4


def test_a_case_with_no_report(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        assert report.for_operation(_case(theatre)) is None
        assert report.state(_case(theatre)) == "none"
        assert report.state(None) == "none"


def test_a_case_with_no_report_is_missing_all_five(theatre):
    """**Nothing written is not nothing missing.** The blank case owes the
    standard every written element, and a :func:`missing` that answered ``[]``
    for it would put an empty list on the registrar's screen — the same list
    a finished report shows — right where the report does not exist at all.
    """
    from app.models.operative_report import OperativeReport
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        assert report.missing(_case(theatre)) == list(OperativeReport.WRITTEN)
        assert report.missing(None) == list(OperativeReport.WRITTEN)
        assert len(OperativeReport.WRITTEN) == 5


def test_a_report_with_a_blank_element_is_short(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre, blood_loss_ml=None)
        assert report.state(_case(theatre)) == "short"


def test_a_full_report_nobody_signed_is_unsigned_not_short(theatre):
    """**Its own word.** Element (i) is one of the nine, so an unsigned report
    is not complete — but calling it «short» would send the registrar back to
    boxes that are already filled."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        assert report.missing(_case(theatre)) == []
        assert report.state(_case(theatre)) == "unsigned"


def test_signed_and_full_is_complete(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        report.sign(_case(theatre), user=_boss(theatre))
        theatre["db"].session.commit()
        assert report.state(_case(theatre)) == "complete"


# ------------------------------------------------------ writing & signing
def test_correcting_a_report_edits_the_one_that_exists(theatre):
    """One procedure, one report. A second row would be a second account of
    the same operation with nothing to say which the ward read."""
    from app.models.operative_report import OperativeReport
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        _write(theatre, post_diagnosis="تشخيص متعدّل")
        assert OperativeReport.query.count() == 1
        assert report.for_operation(_case(theatre)).post_diagnosis == \
            "تشخيص متعدّل"


def test_a_stray_keyword_cannot_reach_the_stamps(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = report.write(_case(theatre), user=_boss(theatre),
                           signed_at=datetime(2020, 1, 1), operation_id=99,
                           written_at=datetime(2020, 1, 1), signed_by=99,
                           **FULL)
        theatre["db"].session.commit()
        assert row.signed_at is None
        assert row.signed_by is None
        assert row.operation_id == theatre["ids"]["case"]
        # **Every** stamp, not only the signature. A mutation left
        # ``written_at`` in the accepted list once, and this test passed
        # through it: it only named the two keywords it happened to think of.
        # ``written_at`` is what «late» is measured from.
        assert row.written_at > datetime(2024, 1, 1)


def test_signing_is_stamped_once(theatre):
    """A second press is somebody pressing twice, and moving the stamp loses
    when the surgeon actually put their name to it."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        report.sign(_case(theatre), user=_boss(theatre),
                    at=datetime(2026, 5, 1, 11, 0))
        theatre["db"].session.commit()
        assert report.sign(_case(theatre), user=_boss(theatre)) is None
        assert report.for_operation(_case(theatre)).signed_at == \
            datetime(2026, 5, 1, 11, 0)


def test_signing_a_report_nobody_wrote_is_refused(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        assert report.sign(_case(theatre), user=_boss(theatre)) is None


def test_writing_and_signing_in_one_breath(theatre):
    """The backref trap, twice learned — and **held on one object**.

    ``write`` reads ``operation.operative_report`` to see whether a report
    exists, which caches ``None`` on that operation. Adding the new row by
    foreign key alone would leave that cache standing, so every later reader
    *in the same request* — ``state``, ``assemble``, ``sign`` — would go on
    believing the case has no report. Constructing through the relationship is
    what clears it.

    The case is deliberately fetched **once** and passed to both calls, the
    way a request holds it: re-fetching between them hides the bug, because
    the flush that the second fetch provokes expires the stale attribute and
    the reload then finds the row. That is how the first draft of this test
    passed against a broken ``write``.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        case = _case(theatre)
        report.write(case, user=_boss(theatre), **FULL)
        # No commit, no second query — this is the same instant.
        assert report.for_operation(case) is not None
        assert report.state(case) == "unsigned"
        assert report.sign(case, user=_boss(theatre)) is not None
        theatre["db"].session.commit()
        assert report.state(_case(theatre)) == "complete"


# --------------------------------------------------------- the timing ---
def test_a_report_written_after_the_child_left_the_unit(theatre):
    """EOC 1 names the event — *"before leaving the procedural unit"* — so the
    program compares against the moment it already records and invents no
    interval of its own."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _case(theatre)
        row.discharged_at = datetime(2026, 5, 1, 12, 0)
        theatre["db"].session.commit()
        written = _write(theatre)
        written.written_at = datetime(2026, 5, 1, 15, 0)
        theatre["db"].session.commit()
        assert report.late(_case(theatre)) is True


def test_a_report_written_while_the_child_was_still_in(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _case(theatre)
        row.discharged_at = datetime(2026, 5, 1, 12, 0)
        theatre["db"].session.commit()
        written = _write(theatre)
        written.written_at = datetime(2026, 5, 1, 10, 45)
        theatre["db"].session.commit()
        assert report.late(_case(theatre)) is False


def test_written_as_the_child_left_is_not_late(theatre):
    """The standard's word is **before** leaving, so the boundary belongs to
    the theatre. A report stamped at the same moment the child left was not
    written after them, and the comparison is strictly «after» rather than
    «not before» — the difference is one late flag on a report that met the
    standard.
    """
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        left = datetime(2026, 5, 1, 12, 0)
        row = _case(theatre)
        row.discharged_at = left
        theatre["db"].session.commit()
        written = _write(theatre)
        written.written_at = left
        theatre["db"].session.commit()
        assert report.late(_case(theatre)) is False


def test_a_case_still_in_the_unit_is_not_late(theatre):
    """Unanswerable is not «on time»: a child who has not left cannot have
    been left behind."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        assert report.late(_case(theatre)) is None
        assert report.late(None) is None


def test_the_queue_of_finished_cases_with_no_report(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        assert [o.id for o in report.unwritten()] == [theatre["ids"]["case"]]
        _write(theatre)
        assert report.unwritten() == []


def test_a_case_still_in_theatre_is_not_on_the_queue(theatre):
    """A report is owed *after* the procedure, and a list counting cases that
    have not finished could never be cleared."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        row = _case(theatre)
        row.status = "in_theatre"
        theatre["db"].session.commit()
        assert report.unwritten() == []


# --------------------------------------------------------- the screen ---
def test_the_case_screen_says_no_report(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert 'data-report-state="none"' in html
        assert t("op_report.not_written") in html


def test_the_screen_shows_what_the_record_already_answers(theatre):
    """So a surgeon can see at a glance that (a), (b) and (e) need nothing
    from them."""
    with theatre["app"].app_context():
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert "data-report-derived" in html
        # (b) — including anaesthesia, which the standard names by name.
        assert "د. التخدير" in html
        # Every element carries its letter, and the derived ones are marked as
        # answered rather than asked for.
        for letter in "abcdefghi":
            assert 'data-element="%s"' % letter in html
        assert _filled(html, "a") == "yes"      # the two stamps
        assert _filled(html, "b") == "yes"      # the staff
        assert _filled(html, "c") == "no"       # nobody has written one yet


def test_writing_the_report_through_the_screen(theatre):
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        theatre["sign_in"]().post(
            "/theatres/operation/%s/report" % theatre["ids"]["case"],
            data={"pre_diagnosis": "زائدة", "post_diagnosis": "زائدة ملتهبة",
                  "complications": "no", "specimen": "yes",
                  "specimen_note": "الزائدة", "blood_loss_ml": "30"},
            follow_redirects=True)
        row = report.for_operation(_case(theatre))
        assert row.complications is False
        assert row.specimen is True
        assert row.blood_loss_ml == 30
        assert report.state(_case(theatre)) == "unsigned"


def test_the_screen_keeps_nobody_said_as_nobody_said(theatre):
    """The select's empty option must not land as «no» — the whole point of
    element (f) being «or not»."""
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        theatre["sign_in"]().post(
            "/theatres/operation/%s/report" % theatre["ids"]["case"],
            data={"pre_diagnosis": "زائدة", "post_diagnosis": "زائدة",
                  "complications": "", "specimen": "", "blood_loss_ml": "0"},
            follow_redirects=True)
        row = report.for_operation(_case(theatre))
        assert row.complications is None
        assert row.specimen is None
        # …and the zero did land.
        assert row.blood_loss_ml == 0


def test_the_screen_says_how_many_are_blank(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/report" % theatre["ids"]["case"],
            data={"pre_diagnosis": "زائدة"},
            follow_redirects=True).get_data(as_text=True)
        assert t("op_report.saved_short", n=4) in html
        assert 'data-report-state="short"' in html


def test_the_screen_says_a_full_report_is_still_waiting_for_a_signature(theatre):
    """Element (i) on the card, in its own word.

    The registrar has filled every box and the surgeon has not put their name
    to it. A card that said «complete» there would tell the theatre the
    standard was met by the one thing nobody had done yet — and a card that
    said «short» would send them back to boxes that are already full.
    """
    from app.i18n import translate as t

    with theatre["app"].app_context():
        _write(theatre)
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert 'data-report-state="unsigned"' in html
        assert t("op_report.unsigned") in html
        assert 'data-report-state="complete"' not in html
        assert "data-report-signed" not in html
        # …and (i) is the only element the card shows as unanswered.
        assert _filled(html, "i") == "no"
        assert _filled(html, "c") == "yes"


def test_signing_through_the_screen(theatre):
    from app.i18n import translate as t
    from app.utils import operative_report as report

    with theatre["app"].app_context():
        _write(theatre)
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/report/sign" % theatre["ids"]["case"],
            follow_redirects=True).get_data(as_text=True)
        assert t("op_report.signed") in html
        assert "data-report-signed" in html
        assert report.state(_case(theatre)) == "complete"


def test_the_screen_refuses_to_sign_nothing(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        html = theatre["sign_in"]().post(
            "/theatres/operation/%s/report/sign" % theatre["ids"]["case"],
            follow_redirects=True).get_data(as_text=True)
        assert t("op_report.nothing_to_sign") in html


def test_the_screen_says_a_report_was_written_late(theatre):
    from app.i18n import translate as t

    with theatre["app"].app_context():
        row = _case(theatre)
        row.discharged_at = datetime(2026, 5, 1, 12, 0)
        theatre["db"].session.commit()
        written = _write(theatre)
        written.written_at = datetime(2026, 5, 1, 15, 0)
        theatre["db"].session.commit()
        html = theatre["sign_in"]().get(
            "/theatres/operation/%s" % theatre["ids"]["case"]).get_data(as_text=True)
        assert "data-report-late" in html
        assert t("op_report.late") in html
