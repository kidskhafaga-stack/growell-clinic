"""Working out which dose an imported vaccination was.

The old export carries no dose column at all. The only ordering available is
the date, so the numbers have to be inferred — and the obvious way to do it is
wrong in a way that matters.

**Number per vaccine, not per brand.** In the real export, patient 1080 had
Synflorix (PCV 10) three times and then **Prevenar (PCV 13)**. Those are the
same vaccine — pneumococcal — in two brands. Numbered per brand, that fourth
dose becomes "dose 1", and the schedule then chases the child for doses they
have already had. Ten patients in that one file had both brands, and 188 of the
283 vaccinated patients repeat a brand at all, so this is most files rather
than an edge case.

**And the count cannot be right on its own.** The file holds what happened *at
this clinic*. A dose given elsewhere — the reported case is "two here, one
outside, and the booster here" — leaves a gap that nothing in the data can see,
so every inferred number is a starting point the doctor can correct in the
patient's file, not a fact. What is inferred here is offered, and what the
clinic knows overrides it.
"""


def number_doses(rows):
    """Assign a dose number to each imported vaccination row.

    ``rows`` are dicts carrying at least ``patient_id``, ``vaccine_id`` and
    ``service_date``. Rows with no vaccine are left alone — a consultation has
    no dose number, and inventing one would put a number on the screen that
    means nothing.

    Returns the same list, each vaccination row gaining ``dose_number``.
    Ordering is by date, then by time when the file gave one, then by the
    source row: two doses of different vaccines on the same day are common, and
    a stable order is what makes a re-import produce the same numbers rather
    than a reshuffle.
    """
    grouped = {}
    for row in rows:
        vaccine_id = row.get("vaccine_id")
        if not vaccine_id or not row.get("patient_id"):
            continue
        grouped.setdefault((row["patient_id"], vaccine_id), []).append(row)

    for course in grouped.values():
        course.sort(key=_order)
        for index, row in enumerate(course, start=1):
            row["dose_number"] = index
    return rows


def _order(row):
    """A stable order for one patient's course of one vaccine."""
    from datetime import date, time

    return (
        row.get("service_date") or date.min,
        row.get("service_time") or time.min,
        str(row.get("source_row") or ""),
    )


def beyond_schedule(rows, schedule_lengths):
    """Rows whose inferred number goes past the vaccine's known dose count.

    These are boosters, extra doses, or a course this clinic simply gave more
    of than the standard schedule lists. They are **flagged, never refused**: a
    boosted child is a real child, and an importer that dropped the fourth dose
    of a three-dose schedule would be deleting history to protect a table.

    ``schedule_lengths`` is ``{vaccine_id: how many doses the schedule has}``.
    """
    out = []
    for row in rows:
        expected = schedule_lengths.get(row.get("vaccine_id"))
        if expected and (row.get("dose_number") or 0) > expected:
            out.append(row)
    return out


def schedule_lengths():
    """``{vaccine_id: doses in its longest schedule}``.

    The longest, because a vaccine can carry several templates — PCV13 has a
    catch-up schedule with fewer doses than its routine one — and a dose is
    only "beyond the schedule" if it is beyond every schedule the vaccine has.
    """
    from app.extensions import db
    from app.models import VaccineScheduleDose, VaccineScheduleTemplate

    rows = (db.session.query(VaccineScheduleTemplate.vaccine_id,
                             VaccineScheduleTemplate.id,
                             db.func.count(VaccineScheduleDose.id))
            .join(VaccineScheduleDose,
                  VaccineScheduleDose.template_id == VaccineScheduleTemplate.id)
            .group_by(VaccineScheduleTemplate.vaccine_id,
                      VaccineScheduleTemplate.id).all())
    longest = {}
    for vaccine_id, _template_id, count in rows:
        longest[vaccine_id] = max(longest.get(vaccine_id, 0), count)
    return longest
