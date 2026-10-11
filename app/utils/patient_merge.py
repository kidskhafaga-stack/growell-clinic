"""Two files for one child, made one — see ``models/patient_merge``.

* :func:`candidates` — pairs that look like one child: the same birthday and
  the same name once Arabic spellings are folded, or the same birthday and
  the same phone or national number. A list to look at, never an action.
* :func:`preview` — what a merge would move, what would be left, and what
  stops it or should give a person pause.
* :func:`merge` — moves every row that points at the dropped file onto the
  kept one, fills the kept file's empty fields from the dropped one (adds to
  allergies, chronic diseases and notes rather than choosing between them),
  archives the dropped file, and writes down every row and every field.
* :func:`undo` — puts back exactly what :func:`merge` wrote down.

Only the admin merges: two files becoming one is not a desk decision.
"""
import json
from datetime import datetime

from app.extensions import db

#: Fields of the kept file filled from the dropped one only where empty.
FILL = ("full_name_en", "national_id", "own_phone", "blood_type", "birth_weight_kg",
        "gestation_weeks", "gestation_days", "birth_time", "photo", "baseline_spo2",
        "reference_number")
#: Text a child must never lose — added to, never chosen between.
ADD = ("allergies", "chronic_diseases", "notes")

#: Tables a merge does not move: its own record.
_SKIP = {"patient_merges"}


class MergeError(ValueError):
    """A refusal with a locale key (``pmerge.err_<key>``)."""


def may_merge(user):
    return bool(user is not None and getattr(user, "is_admin", False))


# ---------------------------------------------------------------- tables ---
def patient_columns():
    """Every ``(table, column)`` that points at a patient — read from the
    database's own description, so a table added later is included."""
    out = []
    for t in db.metadata.tables.values():
        if t.name in _SKIP:
            continue
        for c in t.columns:
            if any(fk.column.table.name == "patients" for fk in c.foreign_keys):
                out.append((t, c))
    return out


def _unique_with(table, column):
    """The other columns of a unique constraint this column is part of —
    a row the kept file already has its own of cannot move."""
    import sqlalchemy as sa

    for con in table.constraints:
        if isinstance(con, sa.UniqueConstraint) and column.name in {c.name for c in con.columns}:
            return [c for c in con.columns if c.name != column.name]
    return None


def _rows(table, column, patient_id):
    return [r[0] for r in db.session.execute(
        db.select(table.c.id).where(column == patient_id).order_by(table.c.id))]


def _split(table, column, keep_id, drop_id):
    """``(movable ids, left ids)`` for this column."""
    ids = _rows(table, column, drop_id)
    if not ids:
        return [], []
    others = _unique_with(table, column)
    if not others:
        return ids, []
    have = {tuple(r) for r in db.session.execute(
        db.select(*others).where(column == keep_id))}
    move, left = [], []
    for row in db.session.execute(db.select(table.c.id, *others).where(table.c.id.in_(ids))):
        (left if tuple(row[1:]) in have else move).append(row[0])
    return move, left


# ------------------------------------------------------------ candidates ---
def _fold(name):
    from app.utils.history_import import normalise_arabic

    return " ".join(normalise_arabic(name).split())


def _digits(v):
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    return d[-9:] if len(d) >= 7 else None


def candidates(limit=50):
    """``[(older, newer, why)]`` — active files that look like one child."""
    from app.models import Patient

    rows = (Patient.query.filter(Patient.is_active.is_(True))
            .with_entities(Patient.id, Patient.full_name, Patient.date_of_birth,
                           Patient.own_phone, Patient.national_id).all())
    by_dob = {}
    for r in rows:
        by_dob.setdefault(r.date_of_birth, []).append(r)
    pairs = []
    for group in by_dob.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                why = None
                if _fold(a.full_name) and _fold(a.full_name) == _fold(b.full_name):
                    why = "name"
                elif a.national_id and a.national_id.strip() == (b.national_id or "").strip():
                    why = "national_id"
                elif _digits(a.own_phone) and _digits(a.own_phone) == _digits(b.own_phone):
                    why = "phone"
                if why:
                    lo, hi = sorted((a.id, b.id))
                    pairs.append((lo, hi, why))
        if len(pairs) >= limit:
            break
    ids = {i for p in pairs for i in p[:2]}
    files = {p.id: p for p in Patient.query.filter(Patient.id.in_(ids or [0]))}
    return [(files[a], files[b], why) for a, b, why in pairs[:limit]]


# --------------------------------------------------------------- preview ---
def preview(keep, drop):
    """``{counts: [(table, n)], left: [(table, n)], blockers: [...],
    warnings: [...]}``."""
    from app.utils import beds

    blockers, warnings = [], []
    if keep is None or drop is None:
        blockers.append("missing")
        return {"counts": [], "left": [], "blockers": blockers, "warnings": warnings}
    if keep.id == drop.id:
        blockers.append("same")
    if drop.archive_reason == "merged" or keep.archive_reason == "merged":
        blockers.append("already")
    if beds.open_admission(keep.id) and beds.open_admission(drop.id):
        blockers.append("two_stays")
    if keep.date_of_birth != drop.date_of_birth:
        warnings.append("dob")
    if (keep.gender or "") != (drop.gender or ""):
        warnings.append("gender")
    if keep.family_id and drop.family_id and keep.family_id != drop.family_id:
        warnings.append("family")
    counts, left = [], []
    if not blockers:
        for table, column in patient_columns():
            move, stay = _split(table, column, keep.id, drop.id)
            if move:
                counts.append((table.name, len(move)))
            if stay:
                left.append((table.name, len(stay)))
    return {"counts": counts, "left": left, "blockers": blockers, "warnings": warnings}


# ----------------------------------------------------------------- merge ---
def _jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def merge(keep, drop, user, reason=None):
    from app.models import PatientMerge

    if not may_merge(user):
        raise MergeError("not_allowed")
    check = preview(keep, drop)
    if check["blockers"]:
        raise MergeError(check["blockers"][0])
    if not (reason or "").strip():
        raise MergeError("need_reason")

    moved, left = {}, {}
    for table, column in patient_columns():
        move, stay = _split(table, column, keep.id, drop.id)
        key = f"{table.name}.{column.name}"
        if move:
            db.session.execute(table.update().where(table.c.id.in_(move))
                               .values({column.name: keep.id}))
            moved[key] = move
        if stay:
            left[key] = stay

    fields = {}
    for f in FILL:
        mine, theirs = getattr(keep, f), getattr(drop, f)
        if (mine is None or mine == "") and theirs not in (None, ""):
            fields[f] = _jsonable(mine)
            setattr(keep, f, theirs)
    for f in ADD:
        mine = (getattr(keep, f) or "").strip()
        theirs = (getattr(drop, f) or "").strip()
        if theirs and theirs not in mine:
            fields[f] = getattr(keep, f)
            stamp = f"[#{drop.patient_number}]"
            setattr(keep, f, (mine + "\n" if mine else "") + f"{stamp} {theirs}")
    if not keep.family_id and drop.family_id:
        fields["family_id"] = None
        keep.family_id = drop.family_id

    state = {"is_active": drop.is_active, "archived_at": _jsonable(drop.archived_at),
             "archive_reason": drop.archive_reason}
    drop.is_active = False
    drop.archived_at = datetime.utcnow()
    drop.archive_reason = "merged"
    drop.merged_into = keep.id

    row = PatientMerge(keep_id=keep.id, drop_id=drop.id, drop_number=drop.patient_number,
                       drop_name=drop.full_name, reason=reason.strip(),
                       moved=json.dumps(moved), left=json.dumps(left),
                       fields=json.dumps(fields), drop_state=json.dumps(state),
                       merged_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    db.session.expire_all()
    return row


def undo(row, user):
    """Put back what :func:`merge` wrote down. Rows the kept file gained
    after the merge stay where they are — they were never the dropped file's."""
    from app.models import Patient

    if not may_merge(user):
        raise MergeError("not_allowed")
    if row.is_undone:
        raise MergeError("already_undone")
    by_name = dict(db.metadata.tables)
    for key, ids in json.loads(row.moved or "{}").items():
        tname, cname = key.split(".", 1)
        table = by_name.get(tname)
        if table is None or not ids:
            continue
        column = table.c[cname]
        db.session.execute(table.update()
                           .where(table.c.id.in_(ids), column == row.keep_id)
                           .values({cname: row.drop_id}))
    keep = db.session.get(Patient, row.keep_id)
    drop = db.session.get(Patient, row.drop_id)
    for f, before in json.loads(row.fields or "{}").items():
        if f in ("birth_time",) and before:
            from datetime import time
            before = time.fromisoformat(before)
        setattr(keep, f, before)
    state = json.loads(row.drop_state or "{}")
    drop.is_active = bool(state.get("is_active", True))
    drop.archived_at = (datetime.fromisoformat(state["archived_at"])
                        if state.get("archived_at") else None)
    drop.archive_reason = state.get("archive_reason")
    drop.merged_into = None
    row.undone_by = getattr(user, "id", None)
    row.undone_at = datetime.utcnow()
    db.session.flush()
    db.session.expire_all()
    return row


#: The records a person recognises by name on the preview; the rest are
#: counted together.
NAMED = ("visits", "appointments", "invoices", "prescriptions", "patient_vaccines",
         "visit_investigations", "admissions", "emergency_visits", "operations",
         "growth_records", "patient_attachments", "conversations")


def summary(counts):
    """``([(table, n)] for the named ones, n of everything else)``."""
    named = [(tname, n) for tname, n in counts if tname in NAMED]
    named.sort(key=lambda x: NAMED.index(x[0]))
    return named, sum(n for tname, n in counts if tname not in NAMED)


def history(limit=50):
    from app.models import PatientMerge

    return (PatientMerge.query.order_by(PatientMerge.merged_at.desc(), PatientMerge.id.desc())
            .limit(limit).all())


def moved_total(row):
    return sum(len(v) for v in json.loads(row.moved or "{}").values())


__all__ = ["MergeError", "NAMED", "candidates", "history", "may_merge", "merge",
           "moved_total", "patient_columns", "preview", "summary", "undo"]
