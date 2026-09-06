"""Two warnings about topical steroids, and neither of them forbids anything.

Asked for in one line: *«مدة قصوى على الكورتيزون الموضعي، وتنبيه لو اتكتب
كورتيزون + مضاد فطريات مع بعض»*.

The harm is not a doctor choosing wrongly. It is a tube with no end date on
it. A steroid cream written for a nappy rash improves it, the rash returns,
the box gets re-dispensed, and nine months later a child has thinned skin on
an occluded area — and every single prescription in that chain was reasonable.
So the two checks here are about **when it stops**, not about what to use.

**The half that needs no number.** A topical corticosteroid with nothing
written in the duration box. There is no figure to argue about: the finding is
that nothing says when to stop. The family is read off the ATC code the
reference already carries — D07 *is* the topical corticosteroids — so an
ingredient added next year is covered the day it is added, with no list to
keep in step.

**The half that has one, where one is printed.** Hydrocortisone 1% sold over
the counter says seven days on the carton. That is the only course limit this
program ships, and every other topical steroid is deliberately empty: the
labels do not agree on a figure and inventing one would be the same fault as
inventing a concentration. The clinic sets its own from the screen.

**And the pair.** A topical steroid with a topical antifungal is prescribed
every day and is often right. It is not treated as an error and the panel is
not red — a red box on a correct prescription teaches a doctor to close the
box without reading it. What it says is which half has to stop.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ---------------------------------------------- reading a written duration

@pytest.mark.parametrize("written,days", [
    ("5d", 5), ("2w", 14), ("1m", 30),
    ("يوم واحد", 1), ("يومين", 2), ("٥ أيام", 5), ("١٥ يوم", 15),
    ("أسبوع", 7), ("أسبوعين", 14), ("٣ أسابيع", 21),
    ("شهر", 30), ("شهرين", 60),
    ("حتى التحسن", None), ("when needed", None), ("", None), (None, None),
])
def test_a_written_duration_in_days_or_nothing(written, days):
    """"Nothing" is a distinct answer from zero, and it is the one the whole
    check is built on."""
    from app.utils.rx_shorthand import duration_days

    assert duration_days(written) == days


@pytest.mark.parametrize("count", [1, 2, 3, 5, 10, 11, 15, 30])
@pytest.mark.parametrize("unit,factor", [("d", 1), ("w", 7), ("m", 30)])
def test_it_reads_back_exactly_what_the_screen_writes(count, unit, factor):
    """The property that matters, and the reason the two functions live in one
    file: the screen expands shorthand on save, so «٥ أيام» is what is stored
    and what this has to read. Tested against its own inverse rather than
    against a list of examples somebody thought of.
    """
    from app.utils.rx_shorthand import duration_days, expand_duration

    assert duration_days(expand_duration(f"{count}{unit}")) == count * factor


# -------------------------------------------------------- the two findings

@pytest.fixture()
def shelf(clinic):
    from app.utils.drugbook_seed import seed_drugbook

    with clinic["app"].app_context():
        seed_drugbook()
        clinic["db"].session.commit()
    return clinic


def _generic(fx, name):
    from app.models import GenericDrug

    return GenericDrug.query.filter_by(name_en=name).first()


def test_a_steroid_with_no_end_date_is_the_finding(shelf):
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        steroid = _generic(shelf, "Hydrocortisone (topical)")
        assert course_warnings(steroid, "") == ["no_end_date"]
        assert course_warnings(steroid, None) == ["no_end_date"]
        assert course_warnings(steroid, "حتى التحسن") == ["no_end_date"]


def test_a_steroid_with_an_end_date_is_not(shelf):
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        assert course_warnings(_generic(shelf, "Hydrocortisone (topical)"),
                               "٥ أيام") == []


def test_the_printed_limit_is_checked_where_one_is_printed(shelf):
    """Seven days on the hydrocortisone carton. Ten days is past it."""
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        steroid = _generic(shelf, "Hydrocortisone (topical)")
        assert steroid.max_course_days == 7
        assert course_warnings(steroid, "١٠ أيام") == ["course_too_long"]
        assert course_warnings(steroid, "٧ أيام") == []


def test_a_steroid_with_no_printed_limit_still_needs_an_end_date(shelf):
    """The reason the two halves are separate. Betamethasone ships no figure —
    the labels do not agree on one and this program does not invent it — and a
    tube of it with no end date is exactly as open-ended as any other."""
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        potent = _generic(shelf, "Betamethasone (topical)")
        assert potent.max_course_days is None
        assert course_warnings(potent, "") == ["no_end_date"]
        assert course_warnings(potent, "٣٠ يوم") == []


def test_nothing_else_in_the_reference_is_asked_for_an_end_date(shelf):
    """A three-day amoxicillin course with the duration box empty is an
    ordinary thing. Firing on every drug would make the warning furniture."""
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        for name in ("Amoxicillin", "Paracetamol", "Zinc oxide (topical)",
                     "Clotrimazole (topical)"):
            assert course_warnings(_generic(shelf, name), "") == [], name


def test_the_family_is_read_off_the_code_not_off_a_list(shelf):
    """Every topical corticosteroid in the reference carries a D07 code, which
    is what the check reads — so one added next year is covered the day it is
    added, and no list has to be kept in step with the seed."""
    from app.models import GenericDrug
    from app.utils.rx_safety import course_warnings

    with shelf["app"].app_context():
        family = [g for g in GenericDrug.query.all()
                  if (g.atc_code or "").startswith("D07")]
        assert len(family) >= 3, "the topical steroids lost their ATC codes"
        for generic in family:
            assert course_warnings(generic, "") == ["no_end_date"], \
                generic.name_en


# ------------------------------------------------------------- the pair

def test_a_steroid_and_an_antifungal_together_are_named(shelf):
    from app.utils.rx_safety import steroid_with_antifungal

    with shelf["app"].app_context():
        steroid = _generic(shelf, "Hydrocortisone (topical)")
        fungus = _generic(shelf, "Clotrimazole (topical)")
        other = _generic(shelf, "Paracetamol")
        assert steroid_with_antifungal([steroid, fungus]) is True
        assert steroid_with_antifungal([steroid, other]) is False
        assert steroid_with_antifungal([fungus, other]) is False
        assert steroid_with_antifungal([]) is False


def test_the_pair_is_found_through_any_brand_of_either(shelf):
    """Matched on the ingredient, so Cortizone with Canesten is the same
    finding as hydrocortisone with clotrimazole."""
    from app.models import Drug
    from app.utils.rx_safety import check

    with shelf["app"].app_context():
        cortizone = Drug.query.filter_by(trade_name="Cortizone").first()
        canesten = Drug.query.filter_by(trade_name="Canesten").first()
        result = check([{"name": cortizone.trade_name, "drug": cortizone},
                        {"name": canesten.trade_name, "drug": canesten}])
        assert result["steroid_with_antifungal"] is True
        assert result["has_warnings"] is True


# ------------------------------------------------------ through the screen

def test_the_check_endpoint_carries_both(shelf):
    from app.models import Drug

    with shelf["app"].app_context():
        cortizone = Drug.query.filter_by(trade_name="Cortizone").first().id
        canesten = Drug.query.filter_by(trade_name="Canesten").first().id

    page = shelf["sign_in"]("doc").get(
        f"/prescriptions/interactions/check?ids={cortizone},{canesten}"
        "&durations=|")
    body = page.get_json()
    assert body["steroid_with_antifungal"] is True
    assert "no_end_date" in body["lines"][0]["warnings"]


def test_a_duration_on_the_line_clears_the_finding(shelf):
    from app.models import Drug

    with shelf["app"].app_context():
        cortizone = Drug.query.filter_by(trade_name="Cortizone").first().id

    page = shelf["sign_in"]("doc").get(
        f"/prescriptions/interactions/check?ids={cortizone}"
        "&durations=%D9%A5%20%D8%A3%D9%8A%D8%A7%D9%85")
    assert page.get_json()["lines"][0]["warnings"] == []


def test_a_caller_that_sends_no_durations_is_unchanged(shelf):
    """Every other screen calls this endpoint without them, and an update is
    not allowed to change what those screens show.

    It is also the honest answer: **an empty duration and a caller that has
    never heard of the field are two different facts.** Only the first one is
    "nobody wrote an end date", and treating the second as though it were
    would put the warning on every screen in the program.
    """
    from app.models import Drug

    with shelf["app"].app_context():
        cortizone = Drug.query.filter_by(trade_name="Cortizone").first().id

    body = shelf["sign_in"]("doc").get(
        f"/prescriptions/interactions/check?ids={cortizone}").get_json()
    assert body["lines"][0]["warnings"] == []


def test_the_screen_sends_the_durations_and_says_both_findings(shelf):
    page = shelf["sign_in"]("doc").get(
        "/prescriptions/new").get_data(as_text=True)
    assert "durations=" in page, "the screen never sends what it wrote"
    assert '"no_end_date"' in page and '"course_too_long"' in page
    assert "steroidPair" in page


def test_the_duration_field_re_runs_the_check(shelf):
    """The warning is *about* that field. Without this it would only ever be
    computed from the value the line had when the drug was chosen — which is
    empty, always, so the finding would never clear."""
    page = shelf["sign_in"]("doc").get(
        "/prescriptions/new").get_data(as_text=True)
    field = page.split('name="item_duration"')[1][:260]
    assert "checkInteractions()" in field


# ------------------------------------------ reaching a clinic that has one

def test_the_limit_reaches_a_clinic_that_installed_before_it_existed(shelf):
    """`seed_generics` skips an ingredient that already exists — which is what
    makes it safe to re-run, and is why a figure added later needs its own
    fill. This is the same bug as "the reference stopped growing", one field
    down."""
    from app.utils.drugbook_seed import fill_course_limits

    db = shelf["db"]
    with shelf["app"].app_context():
        steroid = _generic(shelf, "Hydrocortisone (topical)")
        steroid.max_course_days = None          # a clinic from before
        db.session.commit()

        assert fill_course_limits() == 1
        db.session.commit()
        assert _generic(shelf, "Hydrocortisone (topical)").max_course_days == 7


def test_a_clinic_that_set_its_own_keeps_it(shelf):
    """Fill-only, like everything else in this seed: ours goes in where there
    is nothing, and never over a decision somebody made."""
    from app.utils.drugbook_seed import fill_course_limits

    db = shelf["db"]
    with shelf["app"].app_context():
        steroid = _generic(shelf, "Hydrocortisone (topical)")
        steroid.max_course_days = 10
        db.session.commit()

        assert fill_course_limits() == 0
        db.session.commit()
        assert _generic(shelf, "Hydrocortisone (topical)").max_course_days == 10
