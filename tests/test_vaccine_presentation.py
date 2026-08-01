"""Reading a vaccination record: four shelves, and a card per course.

Two requests, both about presentation and both explicitly *not* about the rule:

**Item 11** — *"the ordering of the vaccine suggestions: courses that have
started in one list and ones that never started in another — not a change to
the rule."* Fifteen identical cards down a page read as fifteen equally urgent
things, and the one a doctor needs first (the course this child is already
halfway through) sits next to one due in four years.

**Item 6** — *"a card per vaccine, dose rows with the date and the doctor and
the record, a progress bar (1/2, 4/4), and counters at the top."* The
certificate was one flat table of every dose in date order, so the three doses
of a course sat pages apart and "did they finish the pneumococcal?" could only
be answered by reading the whole page and counting.

Both are pure functions over the plan :func:`patient_plan` already builds, and
the first test in each half is the one that says so: nothing here computes a
due date, a status or an interval. That restraint is the feature — a grouping
that quietly re-derived a status would be a second opinion about a child's
schedule, kept in a different file from the first.
"""
import inspect
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _dose(number, status, given=None, doctor=None, lot=None):
    return {"dose_number": number, "status": status, "given_date": given,
            "age_label": "", "due_date": None, "lot_number": lot,
            "doctor": doctor, "outside": False, "outside_place": None}


class _Vac:
    def __init__(self, name):
        self.name = name

    def display_name(self, lang="ar"):
        return self.name


def _item(name, doses):
    return {"vaccine": _Vac(name), "brand": _Vac(name + " brand"),
            "locked": False, "doses": doses,
            "done": sum(1 for d in doses if d["status"] == "done"),
            "total": len(doses)}


# ================================================== item 11 — the shelves ===
def test_the_grouping_derives_nothing(clinic):
    """The request said "not a change to the rule", and the way to hold that is
    to keep the function unable to break it: it reads statuses, it never works
    one out. A grouping that re-derived a due date would be a second opinion
    about a child's schedule living in a different file from the first."""
    from app.utils import vaccines

    source = inspect.getsource(vaccines.group_plan)
    for derived in ("add_months", "timedelta", "min_interval", "_status",
                    "due_date"):
        assert derived not in source, derived


def test_a_half_finished_course_comes_first(clinic):
    """The thing a doctor is looking for when they open the page."""
    from app.utils.vaccines import group_plan

    plan = [
        _item("لسه بدري", [_dose(1, "upcoming")]),
        _item("بدأ وناقص", [_dose(1, "done", "2026-01-01"), _dose(2, "due")]),
    ]
    groups = group_plan(plan)
    assert groups[0][0] == "started"
    assert groups[0][1][0]["vaccine"].name == "بدأ وناقص"


def test_a_finished_course_is_not_in_the_started_list(clinic):
    """"Started" means owed. A completed course in that list is a task that
    isn't one, and a list with tasks that aren't tasks stops being read."""
    from app.utils.vaccines import group_plan

    plan = [_item("خلص", [_dose(1, "done", "2026-01-01"),
                          _dose(2, "done", "2026-03-01")])]
    keys = dict(group_plan(plan))
    assert "started" not in keys
    assert len(keys["complete"]) == 1


def test_a_course_never_started_but_due_now_is_its_own_shelf(clinic):
    from app.utils.vaccines import group_plan

    plan = [_item("جاهز", [_dose(1, "due"), _dose(2, "upcoming")])]
    keys = dict(group_plan(plan))
    assert [c["vaccine"].name for c in keys["ready"]] == ["جاهز"]


def test_an_overdue_course_counts_as_ready_not_later(clinic):
    """Overdue is the strongest form of "you can give this now". Filing it
    under not-yet-due would hide exactly the one that has waited longest."""
    from app.utils.vaccines import group_plan

    plan = [_item("متأخر", [_dose(1, "overdue")])]
    assert dict(group_plan(plan)).get("ready")


def test_a_course_not_due_yet_is_last_and_closed(clinic):
    from app.utils.vaccines import group_plan, OPEN_GROUPS

    plan = [_item("بدري", [_dose(1, "upcoming")])]
    groups = group_plan(plan)
    assert groups[-1][0] == "later"
    assert "later" not in OPEN_GROUPS
    assert "complete" not in OPEN_GROUPS


def test_empty_shelves_get_no_heading(clinic):
    """A heading over nothing is a section a reader has to check to discover
    is empty."""
    from app.utils.vaccines import group_plan

    plan = [_item("بدري", [_dose(1, "upcoming")])]
    assert [k for k, _ in group_plan(plan)] == ["later"]


def test_no_vaccine_is_lost_or_duplicated(clinic):
    """The safest possible property, and the one a grouping gets wrong: every
    vaccine lands on exactly one shelf."""
    from app.utils.vaccines import group_plan

    plan = [
        _item("A", [_dose(1, "done", "2026-01-01"), _dose(2, "due")]),
        _item("B", [_dose(1, "done", "2026-01-01")]),
        _item("C", [_dose(1, "due")]),
        _item("D", [_dose(1, "upcoming")]),
    ]
    landed = [c["vaccine"].name for _, items in group_plan(plan) for c in items]
    assert sorted(landed) == ["A", "B", "C", "D"]


def test_the_screen_renders_the_shelves(clinic):
    doc = clinic["sign_in"]("doc")
    reply = doc.get(f"/vaccinations/{clinic['ids']['child']}")
    assert reply.status_code == 200
    body = reply.get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        # At least one heading, whichever shelf this child happens to be on.
        assert any(t("vaccinations.group_" + key) in body
                   for key in ("started", "ready", "complete", "later"))


# ============================================= item 6 — the certificate =====
def test_the_certificate_lists_only_what_was_given(clinic):
    """A certificate says what a child had. What they are due is the optional
    schedule table, and running the two together is how a certificate comes to
    imply a dose that was never given."""
    from app.utils.vaccines import certificate_cards

    plan = [
        _item("اتاخد", [_dose(1, "done", "2026-01-01")]),
        _item("ماتاخدش", [_dose(1, "due"), _dose(2, "upcoming")]),
    ]
    assert [c["vaccine"].name for c in certificate_cards(plan)] == ["اتاخد"]


def test_a_card_carries_its_own_progress(clinic):
    """"2/3" is the whole question in two characters. Reading it off a flat
    table meant finding three rows scattered through forty."""
    from app.utils.vaccines import certificate_cards

    plan = [_item("كورس", [_dose(1, "done", "2026-01-01"),
                           _dose(2, "done", "2026-03-01"),
                           _dose(3, "due")])]
    card = certificate_cards(plan)[0]
    assert (card["given"], card["total"]) == (2, 3)
    assert card["complete"] is False


def test_a_complete_course_says_so(clinic):
    from app.utils.vaccines import certificate_cards

    plan = [_item("كورس", [_dose(1, "done", "2026-01-01"),
                           _dose(2, "done", "2026-03-01")])]
    assert certificate_cards(plan)[0]["complete"] is True


def test_the_counters_count_the_record(clinic):
    from app.utils.vaccines import certificate_cards, certificate_totals

    plan = [
        _item("A", [_dose(1, "done", "2024-02-01"), _dose(2, "done", "2024-06-01")]),
        _item("B", [_dose(1, "done", "2026-01-05")]),
    ]
    totals = certificate_totals(certificate_cards(plan))
    assert totals["doses"] == 3
    assert totals["vaccines"] == 2
    assert totals["complete"] == 2


def test_years_is_the_span_of_the_record_not_the_age_of_the_child(clinic):
    """A certificate reading "5 years" for a five-year-old with one dose on it
    would be describing the child while appearing to describe the record."""
    from app.utils.vaccines import certificate_cards, certificate_totals

    plan = [_item("A", [_dose(1, "done", "2024-11-01"),
                        _dose(2, "done", "2026-01-01")])]
    assert certificate_totals(certificate_cards(plan))["years"] == 3


def test_a_single_year_record_covers_one_year_not_none(clinic):
    """Off-by-one on an inclusive span, printed on paper handed to a family."""
    from app.utils.vaccines import certificate_cards, certificate_totals

    plan = [_item("A", [_dose(1, "done", "2026-01-01"),
                        _dose(2, "done", "2026-08-01")])]
    assert certificate_totals(certificate_cards(plan))["years"] == 1


def test_an_empty_record_counts_to_zero_rather_than_failing(clinic):
    from app.utils.vaccines import certificate_totals

    totals = certificate_totals([])
    assert totals == {"doses": 0, "vaccines": 0, "years": 0,
                      "first": None, "last": None, "complete": 0}


# ------------------------------------------------- what a dose row carries --
def test_a_dose_carries_the_doctor_who_gave_it(clinic):
    """Asked for by name. A row saying only "given" leaves the family to
    remember which clinic, which is what the paper is for."""
    from app.models import PatientVaccine
    from app.utils.vaccines import patient_plan

    ids = clinic["ids"]
    with clinic["app"].app_context():
        from app.models import Patient
        clinic["db"].session.add(PatientVaccine(
            patient_id=ids["child"], vaccine_id=ids["pcv"],
            brand_id=ids["brand"], dose_number=1, given_date=date.today(),
            doctor_id=ids["doctor"], lot_number="LOT-9", event_type="given"))
        clinic["db"].session.commit()

        plan = patient_plan(clinic["db"].session.get(Patient, ids["child"]))
        rows = [d for item in plan for d in item["doses"] if d["given_date"]]
        assert rows and rows[0]["doctor"], "the certificate cannot name a doctor"
        assert rows[0]["lot_number"] == "LOT-9"


def test_a_dose_given_elsewhere_is_marked_as_such(clinic):
    """Attributing a dose given at a government unit to a doctor here would be
    this clinic certifying something it did not do."""
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import patient_plan

    ids = clinic["ids"]
    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=ids["child"], vaccine_id=ids["opv"],
            brand_id=ids["gov_brand"], dose_number=1,
            given_date=date.today() - timedelta(days=30),
            given_outside=True, outside_place="وحدة صحية",
            event_type="given"))
        clinic["db"].session.commit()

        plan = patient_plan(clinic["db"].session.get(Patient, ids["child"]))
        rows = [d for item in plan for d in item["doses"] if d["outside"]]
        assert rows and rows[0]["outside_place"] == "وحدة صحية"


# ------------------------------------------------------------ the printout --
@pytest.fixture()
def carded(clinic):
    from app.models import PatientVaccine

    ids = clinic["ids"]
    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=ids["child"], vaccine_id=ids["pcv"],
            brand_id=ids["brand"], dose_number=1, given_date=date.today(),
            doctor_id=ids["doctor"], lot_number="LOT-9", event_type="given"))
        clinic["db"].session.commit()
    return clinic


def test_the_certificate_prints(carded):
    doc = carded["sign_in"]("doc")
    reply = doc.get(f"/vaccinations/{carded['ids']['child']}/certificate")
    assert reply.status_code == 200
    body = reply.get_data(as_text=True)
    assert "cert-card" in body and "cert-bar" in body
    assert "LOT-9" in body


def test_the_certificate_still_prints_with_the_schedule(carded):
    doc = carded["sign_in"]("doc")
    assert doc.get(f"/vaccinations/{carded['ids']['child']}/certificate",
                   query_string={"schedule": "1"}).status_code == 200


def test_a_course_is_never_split_across_a_page(carded):
    """Half a course on page two reads as a different, shorter course."""
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, "vaccinations", "certificate.html"),
              encoding="utf-8") as fh:
        body = fh.read()
    assert "break-inside:avoid" in body
    assert "page-break-inside:avoid" in body


def test_the_progress_survives_a_black_and_white_printer(carded):
    """The bar is colour on paper usually printed in mono, so the "1/1" beside
    it is the copy that has to carry the meaning on its own."""
    doc = carded["sign_in"]("doc")
    body = doc.get(f"/vaccinations/{carded['ids']['child']}/certificate"
                   ).get_data(as_text=True)
    assert "cert-count" in body
    assert "1/1" in body or "/1" in body


def test_a_child_with_no_doses_still_gets_a_certificate(clinic):
    """It says nothing has been given, which is a true and useful thing for a
    piece of paper to say — and an error page is not."""
    doc = clinic["sign_in"]("doc")
    reply = doc.get(f"/vaccinations/{clinic['ids']['child']}/certificate")
    assert reply.status_code == 200
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.no_given") in reply.get_data(as_text=True)
