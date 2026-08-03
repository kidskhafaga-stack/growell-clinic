"""Matching an old export's rows against what this clinic already has.

Two jobs, and both are shaped by the size of the file rather than by taste.

**Bulk, once.** A real export is 9,908 rows. Resolving the patient one row at a
time is ten thousand round trips to the database; on the clinic's own PC that
is the difference between an import that finishes while somebody watches and
one they assume has hung. Everything here loads a dictionary first and then
walks the rows in memory.

**Compare, don't duplicate.** A clinic re-uploads: because it added a few
months, because it corrected something in the old program, or because it cannot
remember whether it already did. Every row is sorted into one of four, and only
the first is written:

``new``      — not seen before.
``same``     — already imported, identical. Skipped. This is the normal state
               of a second upload, not an error.
``changed``  — already imported and **different**. Shown with the difference,
               and the clinic decides. This is what separates an import that
               compares from one that overwrites reviewed history.
``rejected`` — no such patient, no date, no service name. Refused with a reason.
"""
from app.utils.history_import import normalise_arabic, source_key

NEW = "new"
SAME = "same"
CHANGED = "changed"
REJECTED = "rejected"
OUT_OF_RANGE = "out_of_range"


def patient_index():
    """``{normalised file number: patient id}`` for every patient, in one query.

    Both the clinic's own file number and the legacy reference are indexed,
    because an old export names patients by whichever the previous program
    used, and after a patient import the legacy one is what carries across.
    """
    from app.extensions import db
    from app.models import Patient

    rows = db.session.query(Patient.id, Patient.patient_number,
                            Patient.reference_number).all()
    index = {}
    for pid, number, reference in rows:
        for value in (reference, number):
            key = normalise_arabic(value)
            # First writer wins, and the reference is offered first: it is the
            # column that holds "what the old program called them".
            if key and key not in index:
                index[key] = pid
    return index


def doctor_index():
    """``{normalised name: user id}`` for everyone who sees patients."""
    from app.utils.appointments import list_doctors

    index = {}
    for user in list_doctors():
        for value in (user.full_name, user.full_name_en, user.username):
            key = normalise_arabic(value)
            if key and key not in index:
                index[key] = user.id
    return index


def doctor_key(record):
    """Which doctor one row belongs to — by the source's own code when it has one.

    The plan called this out and the sample proves it: a name is typed several
    ways across ten years ("احمد جمال" / "أحمد جمال قنديل"), and grouping by the
    text would offer the clinic the same person three times and then create
    three users out of them. The code is one value per person.
    """
    code = (record.get("doctor_code") or "").strip()
    if code:
        return f"c:{normalise_arabic(code)}"
    name = (record.get("doctor_name") or "").strip()
    return f"n:{normalise_arabic(name)}" if name else ""


def doctor_entries(records, limit=300):
    """One row per doctor in the file, with every spelling it used.

    ``[{key, code, value, names, rows}]``, commonest first. ``value`` is the
    longest spelling met — the full name is the one worth showing and the one
    worth creating a user from.
    """
    out = {}
    for record in records:
        key = doctor_key(record)
        if not key:
            continue
        name = (record.get("doctor_name") or "").strip()
        entry = out.setdefault(key, {
            "key": key, "code": (record.get("doctor_code") or "").strip(),
            "value": name, "names": [], "rows": 0})
        entry["rows"] += 1
        if name and name not in entry["names"]:
            entry["names"].append(name)
        if len(name) > len(entry["value"]):
            entry["value"] = name
    return sorted(out.values(), key=lambda e: -e["rows"])[:limit]


def existing_keys():
    """``{source key: row}`` for everything already imported, in one query.

    Loaded whole rather than asked per row for the same reason as the patients
    — and the values are the few fields a re-upload can disagree about, so
    "changed" can be decided without going back to the database.
    """
    from app.extensions import db
    from app.models import ImportedService

    rows = db.session.query(
        ImportedService.source_key, ImportedService.id,
        ImportedService.service_date, ImportedService.price,
        ImportedService.source_name).all()
    return {key: {"id": rid, "date": when, "price": price, "name": name}
            for key, rid, when, price, name in rows if key}


def _differs(record, existing):
    """Whether a re-uploaded row disagrees with the one already stored."""
    if existing["date"] != record.get("service_date"):
        return True
    if round(existing["price"] or 0, 2) != round(record.get("price") or 0, 2):
        return True
    return (normalise_arabic(existing["name"])
            != normalise_arabic(record.get("service_name")))


def date_span(records):
    """What the file actually covers: first date, last date, rows per year.

    Read off the file rather than asked for. A clinic uploading ten years of
    history does not know its own export's first date to the day, and being
    made to type one before seeing anything is how somebody picks a range that
    quietly excludes 2016.
    """
    dates = [r["service_date"] for r in records if r.get("service_date")]
    if not dates:
        return {"first": None, "last": None, "years": []}
    per_year = {}
    for value in dates:
        per_year[value.year] = per_year.get(value.year, 0) + 1
    return {
        "first": min(dates), "last": max(dates),
        "years": [{"year": y, "rows": n} for y, n in sorted(per_year.items())],
    }


def classify(records, patients=None, seen=None, start=None, end=None):
    """Sort every parsed row into new / same / changed / rejected.

    Returns ``(records, counts)`` — each record gains ``_state``, ``_patient_id``
    and, when it is not new, ``_was``. The list is annotated in place rather
    than split, so the preview can show them in file order: an accountant
    checking a row against their old program is reading down the page.

    ``start`` and ``end`` narrow the import to part of the file. Both default to
    the whole of it, which is the case that needs no thought: a clinic moving
    off its old program wants everything, and having to state that is a step
    that only exists to be got wrong. A row outside the range is set aside
    rather than rejected — nothing is wrong with it, it simply was not asked
    for, and calling that an error would bury the rows that really are broken.

    ``patients`` and ``seen`` are injectable so the preview and the import can
    share one pair of queries instead of running four.
    """
    patients = patient_index() if patients is None else patients
    seen = existing_keys() if seen is None else seen

    counts = {NEW: 0, SAME: 0, CHANGED: 0, REJECTED: 0, OUT_OF_RANGE: 0}
    # Keys met earlier *in this same file*, so a file that repeats a row does
    # not import it twice on its very first upload.
    in_file = set()

    for record in records:
        reason = None
        if not record.get("service_date"):
            reason = "no_date"
        elif not (record.get("service_name") or "").strip():
            reason = "no_service"

        pid = patients.get(normalise_arabic(record.get("patient_code")))
        if reason is None and pid is None:
            reason = "no_patient"

        record["_patient_id"] = pid
        if reason:
            record["_state"] = REJECTED
            record["_reason"] = reason
            counts[REJECTED] += 1
            continue

        # Checked after the row is known to be sound, so a row that is both
        # broken and outside the range is reported as broken — that is the
        # thing the clinic has to act on.
        when = record["service_date"]
        if (start and when < start) or (end and when > end):
            record["_state"] = OUT_OF_RANGE
            counts[OUT_OF_RANGE] += 1
            continue

        key = source_key(record)
        record["_key"] = key
        existing = seen.get(key)
        if existing is None and key in in_file:
            existing = {"date": record.get("service_date"),
                        "price": record.get("price"),
                        "name": record.get("service_name"), "id": None}

        if existing is None:
            record["_state"] = NEW
            in_file.add(key)
            counts[NEW] += 1
        elif _differs(record, existing):
            record["_state"] = CHANGED
            record["_was"] = existing
            counts[CHANGED] += 1
        else:
            record["_state"] = SAME
            counts[SAME] += 1
    return records, counts


def missing_patient_codes(records, limit=200):
    """The codes that have no patient here, with a name and a row count.

    Listed rather than counted: "412 rows rejected" tells a clinic nothing, and
    the fix — import those patients first — needs to know *which*.
    """
    out = {}
    for record in records:
        if record.get("_state") != REJECTED or record.get("_reason") != "no_patient":
            continue
        code = (record.get("patient_code") or "").strip()
        entry = out.setdefault(code, {"code": code,
                                      "name": record.get("patient_name") or "",
                                      "rows": 0})
        entry["rows"] += 1
        if not entry["name"]:
            entry["name"] = record.get("patient_name") or ""
    return sorted(out.values(), key=lambda e: -e["rows"])[:limit]


def distinct_values(records, key, limit=300):
    """Every distinct value of one column, with how often it appears.

    This is what makes the mapping screens short: 9,908 rows carry 27 service
    names and 3 client categories, so the clinic confirms 30 decisions instead
    of ten thousand.
    """
    counts = {}
    for record in records:
        value = (record.get(key) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    rows = [{"value": v, "rows": n} for v, n in counts.items()]
    return sorted(rows, key=lambda e: -e["rows"])[:limit]
