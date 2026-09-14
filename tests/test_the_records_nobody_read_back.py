"""Reading the records back — GAHAR IMT.09.

> The hospital shall develop and implement a policy and procedures that assess
> the content and the completeness of a patient's medical record that
> addresses at least the following:
> a) Random sampling and selecting approximately **5%** of patient's medical
>    records · b) a representative sample of **all services** · c) of **all
>    disciplines/staff** · d) **involvement of representatives** of all
>    disciplines who make entries · e) **completeness and legibility** of
>    entries · f) review occurs **at least quarterly**.

**The one rule the module is built on: it invents no definition of a complete
record.** Every check it runs is a fact the program already derives for one of
its own screens against a standard already implemented here — a stay with no
discharge summary is ACT.15's finding, an unsigned sign-out is what the
theatre list has always drawn. The review samples, and writes down what those
existing answers said on the day.

That is not a detail of the implementation, it is the whole licence to do this
at all: a program that invented its own completeness rule would be auditing a
clinic against something nobody agreed to. And the standard puts people in the
room for the judging — (d) asks for representatives of the disciplines that
make entries — so findings here are **observations**, never verdicts.

Five things this suite pins:

* **Frozen.** A review is what was found *on the day*. Re-deriving it later
  would rewrite March's findings as June's records were fixed, and a clinic
  that corrected twelve files would end up with evidence it had never found
  any — the opposite of what evidence 4 asks it to show.
* **A clean file is still a sampled file.** Recording only the files with
  findings would make the sample look like the findings, and a clean quarter
  would read as a quarter nobody reviewed.
* **The denominator is stored**, so "approximately 5%" is checkable rather
  than claimed.
* **The sample covers every kind of entry and every person making them**
  (b, c), and overshoots the 5% rather than dropping a discipline to hit it.
* **Never run is not overdue.** A clinic that has not started is not a clinic
  in breach since the beginning of time.
"""
import os
import random
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
        from app.models.theatre import Theatre
        from app.utils.clock import local_today

        for module in ("beds", "theatres", "reports", "visits", "patients"):
            Setting.set("mod_enabled:%s" % module, "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        nurse = User(username="nurse", full_name="الممرضة", role="nurse",
                     is_active=True)
        nurse.set_password("secret")
        unit = Unit(name="العنبر", kind="ward")
        room = Theatre(name="غرفة ١")
        db.session.add_all([boss, nurse, unit, room])
        db.session.flush()
        space = Space(unit_id=unit.id, name="أوضة ١")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير ١")
        db.session.add(bed)
        db.session.flush()
        kids = []
        for n in range(1, 21):
            kid = Patient(patient_number="P%s" % n, full_name="طفل %s" % n,
                          gender="male", is_active=True,
                          date_of_birth=local_today() - timedelta(days=900))
            db.session.add(kid)
            kids.append(kid)
        db.session.commit()
        ids = {"boss": boss.id, "nurse": nurse.id, "bed": bed.id,
               "theatre": room.id, "kids": [k.id for k in kids]}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _today(ctx):
    from app.utils.clock import local_today
    return local_today()


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _visit(ctx, kid_index=0, doctor=None, diagnosis=None, day=None):
    from app.models.diagnosis import Diagnosis
    from app.models.visit import Visit

    row = Visit(patient_id=ctx["ids"]["kids"][kid_index],
                doctor_id=doctor or ctx["ids"]["boss"],
                visit_date=day or _today(ctx))
    ctx["db"].session.add(row)
    ctx["db"].session.flush()
    if diagnosis:
        ctx["db"].session.add(Diagnosis(visit_id=row.id, title=diagnosis))
    ctx["db"].session.commit()
    return row


def _stay(ctx, kid_index=0, discharge=True, summary=None):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as ward
    from app.utils import discharge_summary as ds

    row = ward.admit(ctx["db"].session.get(Patient, ctx["ids"]["kids"][kid_index]),
                     ctx["db"].session.get(Bed, ctx["ids"]["bed"]),
                     user=_boss(ctx), reason="سبب",
                     when=datetime.utcnow() - timedelta(days=2))
    ctx["db"].session.commit()
    if discharge:
        ward.discharge(row, "home", user=_boss(ctx))
        ctx["db"].session.commit()
    if summary:
        ds.write(row, user=_boss(ctx), **summary)
        ctx["db"].session.commit()
    return row


FULL_SUMMARY = {"diagnosis": "أ", "findings": "ب", "condition": "ج",
                "diet": "د", "medicines": "هـ", "followup": "و"}


def _operation(ctx, kid_index=0, status="done", surgeon=None, sign_out=False):
    from app.models.theatre import Operation, SafetyCheck

    row = Operation(patient_id=ctx["ids"]["kids"][kid_index],
                    theatre_id=ctx["ids"]["theatre"], procedure="عملية",
                    on_date=_today(ctx), status=status,
                    surgeon_id=surgeon or ctx["ids"]["boss"])
    ctx["db"].session.add(row)
    ctx["db"].session.flush()
    if sign_out:
        from app.models.theatre import CHECK_ITEMS

        # Every item ticked. A sign-out signed with nothing confirmed is
        # genuinely short and `checklist_short` would fire on it — correctly,
        # but it would mask whichever check the caller was actually testing.
        ctx["db"].session.add(SafetyCheck(
            operation_id=row.id, stop="sign_out", by_id=ctx["ids"]["boss"],
            confirmed=",".join(CHECK_ITEMS["sign_out"])))
    ctx["db"].session.commit()
    return row


# ------------------------------------------------------ the population ----
def test_a_period_nobody_wrote_in_has_nothing_to_sample(clinic):
    """And a review of nought files is said out loud rather than passing as a
    clean quarter — the worst evidence this screen could produce."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        assert review.population(today - timedelta(days=30), today) == []


def test_the_pool_is_the_files_written_in_during_the_period(clinic):
    """An interpretation the standard leaves open, so it is stored and shown:
    reviewing the same untouched file every quarter tells nobody anything."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        _visit(clinic, 1)
        # Files written in outside the period are not in this pool — **both
        # sides of it**. Testing only the early one leaves the later bound
        # unmeasured, which is how a report for last quarter quietly picks up
        # this quarter's work.
        _visit(clinic, 2, day=today - timedelta(days=400))
        _visit(clinic, 3, day=today + timedelta(days=40))

        pool = review.population(today - timedelta(days=30), today)
        assert set(pool) == {clinic["ids"]["kids"][0], clinic["ids"]["kids"][1]}


def test_stays_and_operations_count_as_entries_too(clinic):
    """A child who was only ever admitted has a record to review."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _stay(clinic, 3)
        _operation(clinic, 4)
        pool = review.population(today - timedelta(days=30), today)
        assert clinic["ids"]["kids"][3] in pool
        assert clinic["ids"]["kids"][4] in pool


# ------------------------------------------------------- the checks -------
def test_every_check_names_the_standard_it_came_from(clinic):
    """Never this program. A finding that could not cite a standard would be
    the program auditing a clinic against a rule of its own."""
    from app.utils import record_review as review

    for key, standard, _fn in review.CHECKS:
        assert standard, key
        assert review.STANDARD_OF[key] == standard


def test_a_stay_with_no_discharge_summary_is_seen(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        stay = _stay(clinic, 0)
        assert review.look("admission", stay) == ["stay_no_summary"]


def test_a_short_discharge_summary_is_seen_as_short_not_as_missing(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        stay = _stay(clinic, 0, summary=dict(FULL_SUMMARY, condition=""))
        assert review.look("admission", stay) == ["summary_short"]


def test_a_complete_summary_raises_nothing(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        stay = _stay(clinic, 0, summary=FULL_SUMMARY)
        assert review.look("admission", stay) == []


def test_a_stay_still_running_is_not_asked_for_its_summary(clinic):
    """A child still in a bed has not been discharged, and a finding that can
    never be cleared is not a finding."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        stay = _stay(clinic, 0, discharge=False)
        assert review.look("admission", stay) == []


def test_an_operation_with_no_sign_out_is_seen(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        case = _operation(clinic, 0, sign_out=False)
        assert "operation_no_signout" in review.look("operation", case)


def test_an_operation_that_was_signed_out_is_not(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        case = _operation(clinic, 0, sign_out=True)
        assert "operation_no_signout" not in review.look("operation", case)


def test_a_case_still_in_theatre_is_not_asked_for_its_sign_out(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        case = _operation(clinic, 0, status="in_theatre")
        assert "operation_no_signout" not in review.look("operation", case)


def test_a_stop_signed_with_items_unticked_is_seen(clinic):
    """``safety()['missed']`` is the answer the case screen already draws: a
    checklist completed with gaps is not a completed checklist."""
    from app.models.theatre import SafetyCheck
    from app.utils import record_review as review

    with clinic["app"].app_context():
        case = _operation(clinic, 0)
        clinic["db"].session.add(SafetyCheck(operation_id=case.id,
                                             stop="sign_out",
                                             by_id=clinic["ids"]["boss"]))
        clinic["db"].session.commit()
        seen = review.look("operation", case)
        assert "checklist_short" in seen
        # And it is not reported as an unsigned sign-out, because it is signed.
        assert "operation_no_signout" not in seen


def test_an_operation_with_no_consent_linked_is_seen(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        case = _operation(clinic, 0, sign_out=True)
        assert review.look("operation", case) == ["operation_no_consent"]


def test_an_operation_with_a_signed_consent_linked_raises_nothing(clinic):
    """The other half, and it needs saying: a check that fired on every case
    would be reporting the whole theatre list as a gap, which is worse than
    not checking at all."""
    from app.models import Consent
    from app.utils import record_review as review
    from app.utils import theatres as theatre

    with clinic["app"].app_context():
        case = _operation(clinic, 0, sign_out=True)
        # Signed means a signature on file — `has_signature` reads the file,
        # not a flag — and standing on the day of the operation.
        consent = Consent(patient_id=clinic["ids"]["kids"][0],
                          consent_type="procedure", statement="إقرار",
                          guardian_name="ولي الأمر",
                          signed_date=_today(clinic),
                          signature_file="sig.png")
        clinic["db"].session.add(consent)
        clinic["db"].session.flush()
        case.consent_id = consent.id
        clinic["db"].session.commit()
        assert theatre.consent_state(case) == "linked"
        assert review.look("operation", case) == []


def test_a_visit_with_no_diagnosis_is_seen(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        assert review.look("visit", _visit(clinic, 0)) == ["visit_no_diagnosis"]
        assert review.look("visit", _visit(clinic, 1, diagnosis="نزلة")) == []


def test_a_check_only_looks_at_the_kind_of_entry_it_is_about(clinic):
    """The stay checks must not fire on an operation and back again — six
    checks over three kinds is six chances to cross the wires."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        stay = _stay(clinic, 0)
        case = _operation(clinic, 1, sign_out=True)
        visit = _visit(clinic, 2)
        assert review.look("admission", stay) == ["stay_no_summary"]
        assert review.look("operation", case) == ["operation_no_consent"]
        assert review.look("visit", visit) == ["visit_no_diagnosis"]


# ------------------------------------------------------- the sample -------
def test_the_sample_is_about_five_per_cent(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(20):
            _visit(clinic, n, diagnosis="نزلة")
        # Twenty files, all the same shape: one entry kind, one doctor. So
        # the stratification asks for one and 5% asks for one.
        drawn = review.draw(today - timedelta(days=30), today,
                            rng=random.Random(1))
        assert len(drawn) == 1


def test_the_sample_covers_every_kind_of_entry(clinic):
    """(b) «a representative sample of all services». A sample that omits a
    service is not representative of all services."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(2, 20):
            _visit(clinic, n, diagnosis="نزلة")
        _stay(clinic, 0)
        _operation(clinic, 1)

        drawn = review.draw(today - timedelta(days=30), today,
                            rng=random.Random(7))
        kinds = set()
        for patient_id in drawn:
            kinds.update(k for k, _e in review.entries_for(
                patient_id, today - timedelta(days=30), today))
        assert kinds == {"visit", "admission", "operation"}


def test_the_sample_covers_every_person_making_entries(clinic):
    """(c) «a representative sample of all disciplines/staff»."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(10):
            _visit(clinic, n, doctor=clinic["ids"]["boss"], diagnosis="نزلة")
        # One visit by somebody else, in one file, among twenty.
        _visit(clinic, 15, doctor=clinic["ids"]["nurse"], diagnosis="نزلة")

        drawn = review.draw(today - timedelta(days=30), today,
                            rng=random.Random(3))
        assert clinic["ids"]["kids"][15] in drawn


def test_covering_everybody_beats_hitting_the_number(clinic):
    """Stratification overshoots the 5% rather than dropping a discipline:
    «approximately 5%» is a floor to aim at, and (b) and (c) are not satisfied
    by a sample that hit the number by leaving somebody out."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        # Four files, four different doctors — 5% of four is one.
        from app.models import User

        doctors = [clinic["ids"]["boss"], clinic["ids"]["nurse"]]
        for extra in ("ثالث", "رابع"):
            person = User(username=extra, full_name=extra, role="doctor",
                          is_active=True)
            person.set_password("secret")
            clinic["db"].session.add(person)
            clinic["db"].session.flush()
            doctors.append(person.id)
        clinic["db"].session.commit()
        for n, who in enumerate(doctors):
            _visit(clinic, n, doctor=who, diagnosis="نزلة")

        drawn = review.draw(today - timedelta(days=30), today,
                            rng=random.Random(5))
        assert len(drawn) == 4      # not 1


def test_an_empty_pool_draws_nothing_rather_than_failing(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        assert review.draw(today - timedelta(days=30), today) == []


# ------------------------------------------------------- running it -------
def test_a_round_writes_down_the_pool_and_the_sample(clinic):
    """«Approximately 5%» is a claim a surveyor checks, and a review that
    recorded only the sample would leave them no way to."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(20):
            _visit(clinic, n, diagnosis="نزلة")
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        assert row.population == 20
        assert row.sampled == len(row.items)
        assert row.percent == round(100.0 * row.sampled / 20, 1)


def test_a_file_with_nothing_wrong_is_still_a_sampled_file(clinic):
    """The point of the items table. Recording only the files with findings
    would make the sample look like the findings, and a clean quarter would
    read as a quarter nobody reviewed."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(20):
            _visit(clinic, n, diagnosis="نزلة")   # nothing to find
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        assert row.sampled >= 1
        assert review.clean_files(row) == row.sampled
        assert review.summarise(row) == []


def test_the_findings_are_frozen_at_the_moment_of_the_review(clinic):
    """**The exception to «derived over stored», and it earns it.** Re-deriving
    a March review in June would rewrite it as the gaps were filled, and a
    clinic that corrected twelve records would end up with evidence it had
    never found any."""
    from app.utils import discharge_summary as ds
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        stay = _stay(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        found = review.summarise(row)
        assert {f["check"] for f in found} == {"stay_no_summary"}

        # The gap is fixed afterwards — and March still says what March found.
        ds.write(stay, user=_boss(clinic), **FULL_SUMMARY)
        clinic["db"].session.commit()
        assert ds.state(stay) == "complete"
        assert {f["check"] for f in review.summarise(row)} == {"stay_no_summary"}


def test_a_finding_remembers_which_entry_and_which_day(clinic):
    """So it reads without a join to a row somebody may have corrected."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        stay = _stay(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        finding = row.items[0].findings[0]
        assert finding.entry_kind == "admission"
        assert finding.entry_id == stay.id
        assert finding.entry_on == stay.admitted_at.date()


def test_the_summary_counts_by_check_commonest_first(clinic):
    """What evidence 3 hands the leaders: not six hundred rows, but which
    gaps and how many."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(3):
            _stay(clinic, n)                       # three missing summaries
        _visit(clinic, 5)                          # one missing diagnosis
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), percent=100, rng=random.Random(1))
        clinic["db"].session.commit()
        counts = {f["check"]: f["count"] for f in review.summarise(row)}
        assert counts["stay_no_summary"] == 3
        assert counts["visit_no_diagnosis"] == 1
        assert [f["count"] for f in review.summarise(row)][0] == 3


# ---------------------------------------------- who, the leaders, the fix -
def test_who_took_part_is_recorded_once_each(clinic):
    """(d). A review that counted somebody twice would read as two disciplines
    where there is one."""
    from app.models import User
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        nurse = clinic["db"].session.get(User, clinic["ids"]["nurse"])
        assert review.add_member(row, _boss(clinic), discipline="طب") is not None
        assert review.add_member(row, nurse, discipline="تمريض") is not None
        assert review.add_member(row, _boss(clinic)) is None
        clinic["db"].session.commit()
        assert len(row.members) == 2
        assert {m.discipline for m in row.members} == {"طب", "تمريض"}


def test_telling_the_leaders_is_stamped_once(clinic):
    """Evidence 3. When they were told is the evidence, and a boolean could
    not carry it."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        assert row.reported is False
        review.report_to_leaders(row, user=_boss(clinic),
                                 at=datetime(2026, 4, 1, 9, 0))
        clinic["db"].session.commit()
        assert row.reported is True
        assert review.report_to_leaders(row, user=_boss(clinic)) is None
        assert row.reported_at == datetime(2026, 4, 1, 9, 0)


def test_an_empty_corrective_action_is_refused(clinic):
    """A blank box and «we looked and nothing needed doing» are different
    answers, and one of them is a decision somebody made."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        assert review.record_action(row, "   ", user=_boss(clinic)) is None
        assert row.action is None
        assert review.record_action(row, "اتعمل تدريب", user=_boss(clinic))
        clinic["db"].session.commit()
        assert row.action == "اتعمل تدريب"
        assert row.action_at is not None


# ------------------------------------------------------- the cadence ------
def test_a_clinic_that_has_never_reviewed_is_not_overdue(clinic):
    """Not «in breach since the beginning of time» — a clinic that has not
    started, and the screen says so in those words."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        assert review.next_due() is None
        assert review.overdue() is False


def test_the_next_one_is_due_a_quarter_after_the_last(clinic):
    """(f) «at least quarterly» — the standard's own floor, and the program
    states no stricter one."""
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        review.run(start=today - timedelta(days=30), end=today,
                   user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        assert review.next_due() == today + timedelta(days=review.QUARTER_DAYS)
        assert review.overdue(today=today) is False
        assert review.overdue(
            today=today + timedelta(days=review.QUARTER_DAYS + 1)) is True


# ------------------------------------------------------- the screens ------
def test_the_screen_says_a_clinic_has_never_reviewed(clinic):
    from app.i18n import translate as t

    with clinic["app"].app_context():
        html = clinic["sign_in"]().get(
            "/reports/record-review").get_data(as_text=True)
        assert 'data-due="never"' in html
        assert t("record_review.never_run") in html


def test_running_a_round_from_the_screen_records_it(clinic):
    from app.models.record_review import RecordReview

    with clinic["app"].app_context():
        today = _today(clinic)
        for n in range(20):
            _visit(clinic, n, diagnosis="نزلة")
        clinic["sign_in"]().post(
            "/reports/record-review/run",
            data={"start": (today - timedelta(days=30)).isoformat(),
                  "end": today.isoformat()}, follow_redirects=True)
        row = RecordReview.query.one()
        assert row.population == 20
        assert row.sampled >= 1


def test_an_empty_period_says_so_rather_than_passing_as_clean(clinic):
    """A round of nought files that looked like a pass would be the worst
    evidence this screen could produce."""
    from app.i18n import translate as t

    with clinic["app"].app_context():
        today = _today(clinic)
        html = clinic["sign_in"]().post(
            "/reports/record-review/run",
            data={"start": (today - timedelta(days=30)).isoformat(),
                  "end": today.isoformat()},
            follow_redirects=True).get_data(as_text=True)
        # The flash, which says something the round screen does not — the
        # screen's own empty-sample line carries the other phrase, so
        # asserting that one would pass even with the flash deleted.
        assert t("record_review.drew_nothing") in html


def test_the_round_screen_shows_the_denominator_and_the_findings(clinic):
    from app.i18n import translate as t
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _stay(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), percent=100, rng=random.Random(1))
        clinic["db"].session.commit()
        html = clinic["sign_in"]().get(
            "/reports/record-review/%s" % row.id).get_data(as_text=True)
        assert 'data-population>1<' in html
        assert 'data-sampled>1<' in html
        assert 'data-finding="stay_no_summary"' in html
        # And the standard it came from, on the row.
        assert "ACT.15" in html
        assert t("record_review.check_stay_no_summary") in html


def test_the_round_screen_says_a_clean_sample_is_clean(clinic):
    from app.i18n import translate as t
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0, diagnosis="نزلة")
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), percent=100, rng=random.Random(1))
        clinic["db"].session.commit()
        html = clinic["sign_in"]().get(
            "/reports/record-review/%s" % row.id).get_data(as_text=True)
        assert t("record_review.nothing_found") in html
        assert "data-clean-file" in html
        assert 'data-clean>1<' in html


def test_the_leaders_and_the_action_go_through_the_screen(clinic):
    from app.i18n import translate as t
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        client = clinic["sign_in"]()

        html = client.post("/reports/record-review/%s/action" % row.id,
                           data={"action": "اتعمل تدريب للفريق",
                                 "legibility": "كله متكتوب"},
                           follow_redirects=True).get_data(as_text=True)
        assert "data-action-at" in html
        assert row.legibility_note == "كله متكتوب"

        html = client.post("/reports/record-review/%s/reported" % row.id,
                           follow_redirects=True).get_data(as_text=True)
        assert t("record_review.reported") in html
        assert "data-reported" in html


def test_an_empty_action_is_refused_through_the_screen_but_legibility_is_kept(
        clinic):
    """(e) is a person's judgement and is saved whatever else happens —
    including on its own."""
    from app.i18n import translate as t
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        html = clinic["sign_in"]().post(
            "/reports/record-review/%s/action" % row.id,
            data={"action": "  ", "legibility": "خط اليد في الورق المصوّر وحش"},
            follow_redirects=True).get_data(as_text=True)
        assert t("record_review.action_needs_words") in html
        assert row.action is None
        assert row.legibility_note == "خط اليد في الورق المصوّر وحش"


def test_who_took_part_goes_through_the_screen(clinic):
    from app.utils import record_review as review

    with clinic["app"].app_context():
        today = _today(clinic)
        _visit(clinic, 0)
        row = review.run(start=today - timedelta(days=30), end=today,
                         user=_boss(clinic), rng=random.Random(1))
        clinic["db"].session.commit()
        html = clinic["sign_in"]().post(
            "/reports/record-review/%s/member" % row.id,
            data={"user_id": clinic["ids"]["nurse"], "discipline": "تمريض"},
            follow_redirects=True).get_data(as_text=True)
        assert "data-member" in html
        assert "تمريض" in html


def test_the_review_is_admin_only(clinic):
    """It reads every file in the sample by name."""
    with clinic["app"].app_context():
        reply = clinic["sign_in"]("nurse").get("/reports/record-review")
        assert reply.status_code in (302, 403, 404)


def test_the_reports_hub_leads_an_admin_there(clinic):
    """A card that leads to a refusal is a dead switch."""
    with clinic["app"].app_context():
        html = clinic["sign_in"]().get("/reports/").get_data(as_text=True)
        assert "/reports/record-review" in html


def test_a_non_admin_who_can_read_reports_is_not_shown_the_card(clinic):
    """**The guard the admin-only route needs on the card.** A role can be
    given the reports module without being an admin, and for that person the
    hub opens while this one screen does not — so a card drawn for them would
    be a door onto a refusal.
    """
    from app.models import Role, User

    with clinic["app"].app_context():
        role = Role(name="quality", label_ar="جودة", is_admin=False,
                    modules="reports")
        clinic["db"].session.add(role)
        person = User(username="quality", full_name="الجودة", role="quality",
                      is_active=True)
        person.set_password("secret")
        clinic["db"].session.add(person)
        clinic["db"].session.commit()

        reply = clinic["sign_in"]("quality").get("/reports/")
        assert reply.status_code == 200          # the hub is theirs
        assert "/reports/record-review" not in reply.get_data(as_text=True)


def test_the_reports_hub_is_shut_to_everybody_else(clinic):
    """**Its own app context, and that is not tidiness.** The permission
    lookup is cached per request on ``g``, and Flask's test client reuses the
    app context this test already holds — so a second sign-in inside one
    context inherits the *first* user's cached answer and a nurse is waved
    through as the admin. It cannot happen in the running program, where every
    request gets its own context; it happens here, and a test that signed two
    people in under one context would be asserting nothing.
    """
    with clinic["app"].app_context():
        reply = clinic["sign_in"]("nurse").get("/reports/")
        assert reply.status_code != 200
        assert "/reports/record-review" not in reply.get_data(as_text=True)
