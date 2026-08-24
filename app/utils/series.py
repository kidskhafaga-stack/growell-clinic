"""Every number this child has, drawn against the date it was taken.

Asked directly: *"عايز يبقى في رسم بالزيارات"*. The lab curves already existed;
this is the rest of the answer, and it has three parts.

**One curve per reading, not one per screen it was typed on.** A child's EF is
recorded in two places — the echo report the machine produced, and the
cardiology panel on the visit screen. Those are not two measurements. Drawing
them as two curves would put the same child's heart on two lines that disagree
because one of them is missing half the points. So the catalogue says which
device field means the same thing as which panel field (``from_study``), and
they land in one bucket. Where nothing says they are the same, they stay apart:
the program never decides two readings are the same reading.

**Time on the x-axis, not visit number.** This is the part worth arguing about.
A child seen twice in one week and then again a year later has three visits, and
spacing them evenly draws a fall over twelve months as the same slope as a fall
over four days. The sparkline positions each point by its date for exactly that
reason — the gaps are half of what a curve says.

**And it still refuses to convert units or invent a band.** Two readings in
different units are two curves, the reference band is drawn only from what the
report itself stated, and a reading whose report stated no range simply has
none — which in paediatrics is most of them, on purpose.
"""
from datetime import datetime, time

from app.utils import lab_series, panels


def _moment(value):
    """A date or a datetime as a datetime, so points can be sorted together.

    A study carries a date and a lab result a timestamp; comparing them raw
    raises, and a chart that crashed on a child who had both would be a chart
    that works only on demo data.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _aliases():
    """``{device field name (casefolded): (panel field code, field)}``.

    Built from the catalogue, so the link between "الكسر القذفي (EF)" on an echo
    report and ``ef_pct`` on the cardiology panel is data and not code.

    Matching is by name, and that is a real limitation stated plainly: a clinic
    that renames the field on its own device breaks the link, and the panel goes
    back to asking for the number. A link that broke *silently into a wrong
    join* would be worse; this one breaks into the previous behaviour.
    """
    out = {}
    for meta in panels.all_panels().values():
        for field in meta.get("fields", []):
            for name in field.get("from_study") or []:
                out.setdefault((name or "").strip().casefold(), field)
    return out


def _study_points(patient_id, alias, lang="ar"):
    """Numeric readings from device studies — echo, spirometry, audiometry."""
    from app.models import DeviceStudy, DeviceStudyValue

    rows = (DeviceStudyValue.query
            .join(DeviceStudy, DeviceStudyValue.study_id == DeviceStudy.id)
            .filter(DeviceStudy.patient_id == patient_id,
                    DeviceStudyValue.value_num.isnot(None))
            .order_by(DeviceStudy.study_date, DeviceStudy.id,
                      DeviceStudyValue.id)
            .all())

    out = []
    for row in rows:
        field = alias.get((row.name or "").strip().casefold())
        # Under the panel's code when the catalogue says they are the same
        # reading, so the doctor's entry and the machine's join one line.
        key = f"panel:{field['code']}" if field else f"study:{(row.name or '').casefold()}"
        name = (field.get(f"label_{lang}") or field.get("label_ar")) if field else row.name
        out.append((key, name, (row.unit or "").strip(), {
            "date": _moment(row.study.study_date),
            "value": row.value_num,
            "low": row.normal_low,
            "high": row.normal_high,
            "out_of_range": row.out_of_range,
            "visit_id": row.study.visit_id,
            "source": "study",
        }))
    return out


def _panel_points(patient_id, lang="ar"):
    """Numeric readings typed into a specialty panel on a visit screen."""
    from app.models import Measurement

    rows = (Measurement.query
            .filter(Measurement.patient_id == patient_id,
                    Measurement.value_num.isnot(None))
            .order_by(Measurement.recorded_at, Measurement.id)
            .all())

    labels = {}
    for meta in panels.all_panels().values():
        for field in meta.get("fields", []):
            labels.setdefault(field["code"], field)

    out = []
    for row in rows:
        field = labels.get(row.code) or {}
        name = field.get(f"label_{lang}") or field.get("label_ar") or row.code
        out.append((f"panel:{row.code}", name, (row.unit or "").strip(), {
            "date": _moment(row.recorded_at),
            "value": row.value_num,
            # A panel field carries no reference range: the catalogue states
            # none, because the survey's own answer for cardiology was that
            # there is no single number for every heart condition.
            "low": None, "high": None, "out_of_range": None,
            "visit_id": row.visit_id,
            "source": "panel",
        }))
    return out


def _offsets(points):
    """Give every point its place on a time axis, as ``0.0``–``1.0``.

    Computed here rather than in the template because it is the part with an
    opinion in it: the x of a point is *when it was taken*, not which number of
    reading it is. Spacing points evenly draws a fall over twelve months with
    the same slope as a fall over four days, and the gaps are half of what a
    curve says.

    Points that share a date share an x — they were taken on the same day, and
    nudging them apart would be the chart inventing an interval.
    """
    dates = [p.get("date") for p in points]
    if not points or any(d is None for d in dates):
        # No usable dates: fall back to even spacing rather than drawing
        # nothing, and the value list under the curve still carries the truth.
        last = max(len(points) - 1, 1)
        for index, point in enumerate(points):
            point["offset"] = index / last
        return points
    span = (dates[-1] - dates[0]).total_seconds()
    for point, moment in zip(points, dates):
        point["offset"] = (((moment - dates[0]).total_seconds() / span)
                           if span > 0 else 0.5)
    return points


def curves_for(patient_id, lang="ar"):
    """Every reading with two or more numbers behind it, as curves.

    Returns ``[{key, name, unit, sources, points}]`` — the same shape the lab
    curves already use, so one drawing macro covers all of them. Ordered by how
    much there is to see, because that is the order a page is scanned in.

    One reading is a fact, not a trend, and a chart of one point is a chart
    inviting somebody to draw a line through it. Those are answered by
    :func:`app.utils.lab_series.latest_values` instead.
    """
    alias = _aliases()
    groups = {}

    for source in (_study_points(patient_id, alias, lang),
                   _panel_points(patient_id, lang)):
        for key, name, unit, point in source:
            # The unit is part of the identity, never a label on it: joining
            # two units would need a conversion this module does not do.
            bucket = groups.setdefault((key, unit), {
                "key": key, "unit": unit or None, "name": name,
                "sources": set(), "points": [],
            })
            bucket["points"].append(point)
            bucket["sources"].add(point["source"])

    out = []
    for bucket in groups.values():
        if len(bucket["points"]) < 2:
            continue
        # Sorted after merging, because two sources arrive in two orders and a
        # curve drawn in the order rows were read is a curve drawn wrong.
        bucket["points"].sort(key=lambda p: (p["date"] or datetime.min))
        bucket["sources"] = sorted(bucket["sources"])
        _offsets(bucket["points"])
        out.append(bucket)

    # The labs come already grouped and already correct; they only need the
    # fields the merged shape carries.
    for lab in lab_series.series_for(patient_id, lang):
        for point in lab["points"]:
            point["date"] = _moment(point.get("date"))
            point.setdefault("source", "lab")
        lab["sources"] = ["lab"]
        _offsets(lab["points"])
        out.append(lab)

    out.sort(key=lambda g: (-len(g["points"]), g["name"]))
    return out


def last_study_readings_everywhere(patient_id, lang="ar"):
    """``{field code: reading}`` across *every* panel in the catalogue.

    The visit screen offers all the panels at once now, so the "last echo"
    hint has to exist for whichever one the doctor picks — and asking per
    panel would be one query per specialty on a screen opened forty times a
    day. Field codes are unique across the catalogue, so one dictionary holds
    them all without a key per panel.
    """
    merged = {}
    for meta in panels.all_panels().values():
        merged.update(last_study_readings(patient_id, meta, lang))
    return merged


def last_study_readings(patient_id, meta, lang="ar"):
    """The most recent device reading for each panel field that has one.

    Returns ``{field code: {value, unit, date, name}}``, for showing beside the
    box rather than inside it. **Shown and not filled in, deliberately** — the
    vitals a panel reads were taken by the nurse minutes ago, but an echo was
    done whenever it was done, and an EF from three months back presented as
    today's reading is the program stating something nobody measured.
    """
    from app.models import DeviceStudy, DeviceStudyValue

    wanted = {}
    for field in (meta or {}).get("fields", []):
        for name in field.get("from_study") or []:
            wanted[(name or "").strip().casefold()] = field
    if not wanted or not patient_id:
        return {}

    rows = (DeviceStudyValue.query
            .join(DeviceStudy, DeviceStudyValue.study_id == DeviceStudy.id)
            .filter(DeviceStudy.patient_id == patient_id,
                    DeviceStudyValue.value_num.isnot(None))
            .order_by(DeviceStudy.study_date, DeviceStudy.id,
                      DeviceStudyValue.id)
            .all())

    out = {}
    for row in rows:                      # oldest first, so the last one wins
        field = wanted.get((row.name or "").strip().casefold())
        if field is None:
            continue
        out[field["code"]] = {
            "value": row.value_num,
            "unit": row.unit or field.get("unit"),
            "date": row.study.study_date,
            "name": row.name,
            "study_id": row.study_id,
        }
    return out
