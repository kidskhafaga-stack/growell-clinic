"""One test, read across every visit — the thing a number was added for.

Every specialty in the survey asks the same question in its own words:
*"تحاليل تريد رؤيتها كمنحنى"*. HbA1c for the endocrinologist, ferritin for the
haematologist, eGFR for the nephrologist, INR for the cardiologist, drug levels
for the neurologist. Twelve lists of tests, one feature underneath them.

It could not be built while a result was prose, and that is all that was in
the way — the drawing half has existed for years in the growth charts.

**What a series is grouped by.**

By the catalogue entry where there is one, and by the name where there is not.
Both, because a clinic types a test in free text as often as it picks it from
the list, and a curve that silently dropped every hand-typed HbA1c would be a
feature that works on demo data and not on a register.

**What it refuses to do.**

It does not convert units. Two ferritins recorded in different units are two
series here, not one line with a jump in it — an unmarked conversion is how a
chart tells a confident lie. And it never guesses a reference band: the band
is drawn only from what the report itself said, per point, and a point whose
report gave no range simply has none.
"""
from app.extensions import db
from app.models import VisitInvestigation


def _key(row):
    """What makes two results the same test.

    The catalogue id when the test came from the catalogue; the name otherwise.
    Prefixed so a numeric id can never collide with a name.
    """
    if row.investigation_id:
        return f"id:{row.investigation_id}"
    return f"name:{(row.name or '').strip().casefold()}"


def series_for(patient_id, lang="ar"):
    """Every numeric result this patient has, grouped into curves.

    Returns a list of ``{key, name, unit, points}`` ordered by how much there
    is to see — the tests with the longest history first, because that is the
    order a doctor scans a page in. Each point is ``{date, value, low, high,
    out_of_range, visit_id}``, oldest first.

    Only tests with **two or more** numeric results are returned. A single
    reading is a fact, not a trend, and a chart of one point is a chart that
    invites a line to be drawn through it.
    """
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == patient_id,
                    VisitInvestigation.result_value.isnot(None))
            .order_by(VisitInvestigation.resulted_at,
                      VisitInvestigation.created_at,
                      VisitInvestigation.id)
            .all())

    groups = {}
    for row in rows:
        # The unit is part of the identity, not a label on it. Two ferritins in
        # different units are two curves; joining them would need a conversion
        # this module deliberately does not do.
        key = (_key(row), (row.result_unit or "").strip())
        bucket = groups.setdefault(key, {
            "key": key[0], "unit": key[1] or None,
            "name": row.display_name(lang), "points": [],
        })
        bucket["points"].append({
            "date": (row.resulted_at or row.created_at),
            "value": row.result_value,
            "low": row.result_low,
            "high": row.result_high,
            "out_of_range": row.out_of_range,
            "visit_id": row.visit_id,
        })

    out = [g for g in groups.values() if len(g["points"]) >= 2]
    out.sort(key=lambda g: (-len(g["points"]), g["name"]))
    return out


def latest_values(patient_id, lang="ar"):
    """The most recent numeric result of each test — including the ones with
    only one reading, which :func:`series_for` leaves out.

    A different question from a curve and worth answering separately: "what is
    his ferritin?" is asked far more often than "show me his ferritin over
    time", and the answer to the first exists from the very first result.
    """
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == patient_id,
                    VisitInvestigation.result_value.isnot(None))
            .order_by(VisitInvestigation.resulted_at,
                      VisitInvestigation.created_at,
                      VisitInvestigation.id)
            .all())
    latest = {}
    for row in rows:                       # ordered oldest first, so last wins
        latest[(_key(row), (row.result_unit or "").strip())] = row
    return sorted(
        ({"name": r.display_name(lang), "value": r.result_value,
          "unit": r.result_unit, "low": r.result_low, "high": r.result_high,
          "out_of_range": r.out_of_range,
          "date": (r.resulted_at or r.created_at), "visit_id": r.visit_id}
         for r in latest.values()),
        key=lambda d: d["name"])
