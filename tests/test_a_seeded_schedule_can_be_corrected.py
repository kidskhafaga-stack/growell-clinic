"""A schedule the program seeded is one the clinic can correct.

Reported from a clinic looking at a screen full of seeded pneumococcal
schedules: *"ليه مش بقدر أعدل على البيانات المزروعة وفيه حاجات مش متعلّم عليها
أصلاً بوستر؟ وازاي أغيّر البياخد منين المعلومة؟"* — and all three parts of that
question had the same answer, which is that the screen offered two verbs.

**Add a row and delete a row.** So changing "2 months" to "3" meant deleting the
row and typing it again, which also loses its place in the course unless the
dose number is retyped too. Faced with that, what a clinic actually does is
leave a schedule it believes is wrong exactly where it is — and the seeded bands
arrive labelled *"للمراجعة"* precisely because they are expected to need it.

**Nothing could ever tick a booster.** `booster_required` was settable only
while *adding* a row. Nothing the seeder writes ticks it, so the column read "—"
all the way down and no amount of clicking could change that.

**And the source could not be changed**, which is the one that matters most: a
clinic that follows the CDC where the catalogue seeded the manufacturer's label
was reading a claim about provenance it had no way to correct. The route to do
it had been written — and no screen called it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def schedule(clinic):
    """A seeded-looking schedule: four doses, no booster ticked anywhere."""
    from app.extensions import db
    from app.models import Vaccine, VaccineScheduleDose, VaccineScheduleTemplate

    with clinic["app"].app_context():
        vaccine = Vaccine.query.filter_by(code="PCV").one()
        tpl = VaccineScheduleTemplate(
            vaccine_id=vaccine.id, code="STD", source="manufacturer",
            label="الجدول القياسي", needs_review=True)
        db.session.add(tpl)
        db.session.flush()
        for number, age in ((1, 2), (2, 4), (3, 6), (4, 12)):
            db.session.add(VaccineScheduleDose(
                template_id=tpl.id, dose_number=number,
                recommended_age_months=age,
                min_interval_days=28 if number > 1 else None))
        db.session.commit()
        clinic["vaccine_id"] = vaccine.id
        clinic["tpl_id"] = tpl.id
        clinic["dose_ids"] = [d.id for d in tpl.doses]
    return clinic


def _doses(schedule):
    from app.extensions import db
    from app.models import VaccineScheduleTemplate

    with schedule["app"].app_context():
        tpl = db.session.get(VaccineScheduleTemplate, schedule["tpl_id"])
        return {d.dose_number: d for d in tpl.doses}


def _tpl(schedule):
    from app.extensions import db
    from app.models import VaccineScheduleTemplate

    with schedule["app"].app_context():
        return db.session.get(VaccineScheduleTemplate, schedule["tpl_id"])


def _edit_dose(schedule, dose_id, **form):
    return schedule["sign_in"]("boss").post(
        f"/vaccinations/manage/schedules/dose/{dose_id}/edit",
        data=form, follow_redirects=True)


# ------------------------------------------------- correcting a dose row

def test_a_seeded_dose_can_be_corrected_in_place(schedule):
    """Without this the only way to change an age is to delete the row and
    build it again — which is how a wrong schedule survives being noticed."""
    first = schedule["dose_ids"][0]

    _edit_dose(schedule, first, dose_number="1", recommended_age_months="3",
               min_interval_days="30", max_interval_days="90")

    dose = _doses(schedule)[1]
    assert dose.recommended_age_months == 3
    assert dose.min_interval_days == 30 and dose.max_interval_days == 90


def test_a_booster_can_finally_be_ticked(schedule):
    """The column read "—" all the way down because `booster_required` could
    only ever be set while *adding* a row, and nothing seeded ticks it."""
    last = schedule["dose_ids"][-1]
    assert _doses(schedule)[4].booster_required is False

    _edit_dose(schedule, last, dose_number="4", recommended_age_months="12",
               booster_required="1")

    assert _doses(schedule)[4].booster_required is True


def test_and_unticked_again(schedule):
    """A checkbox posts nothing when it is off. Reading that as "leave it as it
    was" would make a tick permanent — which is the same trap the screen was
    already in, one layer down."""
    last = schedule["dose_ids"][-1]
    _edit_dose(schedule, last, dose_number="4", booster_required="1")
    assert _doses(schedule)[4].booster_required is True

    _edit_dose(schedule, last, dose_number="4")

    assert _doses(schedule)[4].booster_required is False


def test_emptying_a_box_clears_the_number(schedule):
    """"No maximum interval" is a real statement about a schedule. An editor
    that could only ever add numbers could not express it."""
    second = schedule["dose_ids"][1]
    assert _doses(schedule)[2].min_interval_days == 28

    _edit_dose(schedule, second, dose_number="2", recommended_age_months="4",
               min_interval_days="")

    assert _doses(schedule)[2].min_interval_days is None


def test_the_row_keeps_its_place_unless_the_number_is_changed(schedule):
    """The whole reason delete-and-retype was a bad answer: a dose that loses
    its number stops being the second dose of the course."""
    second = schedule["dose_ids"][1]

    _edit_dose(schedule, second, dose_number="2", recommended_age_months="5")

    doses = _doses(schedule)
    assert sorted(doses) == [1, 2, 3, 4]
    assert doses[2].recommended_age_months == 5


def test_a_dose_number_left_blank_does_not_wipe_it(schedule):
    """A missing number is a form that did not say, not a request for dose
    zero — and a dose numbered zero is not in any course."""
    second = schedule["dose_ids"][1]

    _edit_dose(schedule, second, recommended_age_months="5")

    assert 2 in _doses(schedule)


def test_correcting_a_schedule_is_written_down(schedule):
    """Who changed a clinical rule and when. The dose-recording screen already
    logs every other change to a course."""
    from app.models import ActivityLog

    _edit_dose(schedule, schedule["dose_ids"][0], dose_number="1",
               recommended_age_months="3")

    with schedule["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="vaccine.schedule_dose_edit").count() == 1


# --------------------------------------------- and where it came from

def test_the_source_can_be_changed(schedule):
    """The part that matters most. A clinic following the CDC where the
    catalogue seeded the manufacturer's label was reading a claim about
    provenance it had no way to correct."""
    schedule["sign_in"]("boss").post(
        f"/vaccinations/manage/schedules/{schedule['tpl_id']}/edit",
        data={"source": "cdc", "is_active": "1"}, follow_redirects=True)

    assert _tpl(schedule).source == "cdc"


def test_an_invented_source_is_refused(schedule):
    """The badge on the screen is a claim about a reference. It may only ever
    be one of the ones the engine knows."""
    schedule["sign_in"]("boss").post(
        f"/vaccinations/manage/schedules/{schedule['tpl_id']}/edit",
        data={"source": "whatever-i-typed", "is_active": "1"},
        follow_redirects=True)

    assert _tpl(schedule).source == "manufacturer"


def test_correcting_a_label_does_not_switch_the_schedule_off(schedule):
    """`is_active` is read as a checkbox, so a form that forgot to carry it
    would retire a working schedule every time somebody fixed a typo."""
    page = schedule["sign_in"]("boss").get(
        f"/vaccinations/manage/vaccine/{schedule['vaccine_id']}/schedules"
    ).get_data(as_text=True)

    assert 'name="is_active"' in page, \
        "the edit form does not carry is_active — saving it would retire the schedule"


# ------------------------------------------------------ on the screen

def test_the_screen_offers_more_than_add_and_delete(schedule):
    """The gap itself: `template_edit` had been written and no template ever
    called it, so the only verb the header offered was delete."""
    page = schedule["sign_in"]("boss").get(
        f"/vaccinations/manage/vaccine/{schedule['vaccine_id']}/schedules"
    ).get_data(as_text=True)

    for dose_id in schedule["dose_ids"]:
        assert f"/schedules/dose/{dose_id}/edit" in page, \
            f"dose {dose_id} has no way to be corrected"
    assert f"/schedules/{schedule['tpl_id']}/edit" in page, \
        "the schedule's own source and label cannot be corrected"


def test_every_dose_box_is_bound_to_its_own_row(schedule):
    """A `<form>` may not span table cells, so the inputs are joined to their
    row by `form=`. Getting that wrong would post one row's numbers under
    another row's id — silently, and into a clinical rule."""
    page = schedule["sign_in"]("boss").get(
        f"/vaccinations/manage/vaccine/{schedule['vaccine_id']}/schedules"
    ).get_data(as_text=True)

    for dose_id in schedule["dose_ids"]:
        assert f'form="dose{dose_id}"' in page
        assert f'id="dose{dose_id}"' in page
