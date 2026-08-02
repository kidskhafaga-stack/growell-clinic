"""The device studies in a patient's file, arranged so they can be read.

Reported twice. First: *"in the patient file — the studies, echo, audiometry,
these are all studies and they have to be inside the file."* Then, deciding
where they belong: *"fine, inside Procedures — but it gets added to the medical
file as its own tab, and organised."*

Two different questions, and they were both being answered by one list:

* **doing** one is a procedure, so it lives in the visit under Procedures;
* **reading** them back is a history, and a history is read *per device*.
  "How has this child's spirometry gone?" is the question, and answering it
  from a flat date-ordered list means picking the spirometry rows out of the
  echoes by eye.

So the file groups by device, newest first inside each group, and each group
carries its own count and its latest date — because the thing somebody wants
off the shelf is usually "the most recent echo" and it should not take reading
to find it.

The out-of-range count travels with each row. A study with three values outside
their normal range and a study with none look identical when all a row shows is
a date and a device, and the one that matters is the one nobody clicks.
"""
from datetime import date

# A study with no date must not crash the sort or float to the top: it sorts
# oldest, which is where an undated record belongs.
_MIN_DATE = date.min


def _out_of_range(study):
    """How many measured values fell outside their normal range."""
    return sum(1 for v in getattr(study, "values", [])
               if getattr(v, "flag", None) in ("low", "high"))


def study_row(study, lang="ar"):
    return {
        "study": study,
        "id": study.id,
        "date": study.study_date,
        "device": study.device,
        "device_name": (study.device.display_name(lang) if study.device else ""),
        "values": len(getattr(study, "values", [])),
        "out_of_range": _out_of_range(study),
        "conclusion": (study.conclusion or "").strip() or None,
        "visit_id": study.visit_id,
        "performer": (study.performer.display_name(lang)
                      if getattr(study, "performer", None) else None),
    }


def patient_studies(patient, lang="ar"):
    """``{"groups": [...], "total": n, "flagged": n}`` for the file's tab.

    Grouped by device and newest first — inside each group and between them, so
    the device seen most recently comes first. A file where the ordering came
    from the device catalogue would put a machine last used two years ago above
    the one used this morning.
    """
    rows = [study_row(s, lang) for s in getattr(patient, "device_studies", [])]
    rows.sort(key=lambda r: (r["date"] or _MIN_DATE, r["id"]), reverse=True)

    groups = {}
    for row in rows:
        key = row["device"].id if row["device"] else 0
        bucket = groups.setdefault(key, {
            "device": row["device"],
            "name": row["device_name"] or "—",
            "rows": [],
        })
        bucket["rows"].append(row)

    ordered = sorted(groups.values(),
                     key=lambda g: (g["rows"][0]["date"] or _MIN_DATE),
                     reverse=True)
    for group in ordered:
        group["count"] = len(group["rows"])
        group["latest"] = group["rows"][0]["date"]
        group["flagged"] = sum(1 for r in group["rows"] if r["out_of_range"])
    return {
        "groups": ordered,
        "total": len(rows),
        "flagged": sum(1 for r in rows if r["out_of_range"]),
        "devices": len(ordered),
    }
