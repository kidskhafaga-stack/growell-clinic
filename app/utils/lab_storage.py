"""A tube kept after its result, found again, and thrown away — GAHAR DAS.20.

(ج) *criteria for specimen storage*, (هـ) *the defined retention time of
patient samples*, (و) *specimens' disposal*; evidence 5 *the procedure … is
implemented* and evidence 6 *required specimens are easily retrieved*.

* **Where** is the laboratory's list (`Lookup` domain ``sample_store``) —
  its fridges and racks, in its words; until it writes one, the place is
  typed.
* **How long** is the laboratory's figure: per test (``Investigation
  .keep_days``), else its general one (:data:`KEEP_SETTING`). A tube with
  neither has no day to go on — kept, and never called due. The program does
  not invent a retention time.
* **Found** by the tube's code or by the child — name, file number, phone,
  mother — the same search as everywhere else.
* **Thrown away** by somebody, on a day; before its day only with a reason.
"""
from datetime import datetime, time, timedelta

from app.extensions import db

PLACES_DOMAIN = "sample_store"
KEEP_SETTING = "lab_keep_days"


class StorageError(ValueError):
    """A refusal with a key the screen can name (``lab_storage.err_<key>``)."""


# ------------------------------------------------------------ the places --
def places():
    from app.models import Lookup

    return (Lookup.query.filter_by(domain=PLACES_DOMAIN, is_active=True)
            .order_by(Lookup.sort_order, Lookup.id).all())


def add_place(name):
    from app.models import Lookup
    from app.utils.lookups import make_key

    name = (name or "").strip()[:80]
    if not name:
        raise StorageError("need_place")
    existing = (Lookup.query.filter_by(domain=PLACES_DOMAIN)
                .filter(Lookup.name_ar == name).first())
    if existing is not None:
        existing.is_active = True
        return existing
    row = Lookup(domain=PLACES_DOMAIN, key=make_key(name, PLACES_DOMAIN),
                 name_ar=name, is_active=True)
    db.session.add(row)
    return row


def retire_place(row):
    """Off the list — a tube put there last week still names it."""
    if row is None or row.domain != PLACES_DOMAIN:
        raise StorageError("not_a_place")
    row.is_active = False
    return row


def place_label(store):
    from app.models import Lookup

    if store is None:
        return ""
    if store.place_key:
        row = Lookup.query.filter_by(domain=PLACES_DOMAIN,
                                     key=store.place_key).first()
        label = row.name_ar if row is not None else store.place_key
        return f"{label} — {store.place_text}" if store.place_text else label
    return store.place_text or ""


# ------------------------------------------------------------- how long --
def default_days():
    from app.models import Setting

    raw = (Setting.get(KEEP_SETTING) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def set_default_days(value):
    from app.models import Setting

    raw = str(value or "").strip()
    number = int(raw) if raw.isdigit() and 0 < int(raw) <= 3650 else None
    Setting.set(KEEP_SETTING, str(number) if number else "")
    return number


def days_for(orders):
    """The longest figure among the tests on the tube — a tube is kept as long
    as its longest-kept test needs it — or the laboratory's general one."""
    figures = [o.investigation.keep_days for o in orders
               if o.investigation is not None and o.investigation.keep_days]
    return max(figures) if figures else default_days()


# -------------------------------------------------------------- the tube --
def tube(code):
    """Every order on this tube, by its code, or ``[]``."""
    from app.models import VisitInvestigation

    code = (code or "").strip().upper()
    if not code:
        return []
    return (VisitInvestigation.query
            .filter(db.func.upper(VisitInvestigation.sample_code) == code,
                    VisitInvestigation.kind == "lab")
            .order_by(VisitInvestigation.id).all())


def current(code):
    """Where this tube is now — its open row — or ``None``."""
    from app.models import SpecimenStore

    code = (code or "").strip().upper()
    if not code:
        return None
    return (SpecimenStore.query
            .filter(db.func.upper(SpecimenStore.sample_code) == code)
            .order_by(SpecimenStore.id.desc()).first())


def store(code, place_key=None, place_text=None, user=None, at=None):
    """Put the tube away — or move it, when it is already kept. The caller
    commits. Only a tube with a result: one still on the bench is not
    stored, it is being worked on."""
    from app.models import SpecimenStore
    from app.utils.clock import to_local

    orders = tube(code)
    if not orders:
        raise StorageError("unknown")
    if not any(o.status == "resulted" for o in orders):
        raise StorageError("not_done")
    key = (place_key or "").strip() or None
    if key is not None and key not in {p.key for p in places()}:
        key = None
    text = (place_text or "").strip()[:80] or None
    if key is None and text is None:
        raise StorageError("need_place")
    row = current(code)
    if row is not None and row.disposed_at is not None:
        raise StorageError("disposed")
    if row is None:
        moment = at or datetime.utcnow()
        days = days_for(orders)
        row = SpecimenStore(
            sample_code=orders[0].sample_code, patient_id=orders[0].patient_id,
            stored_at=moment, stored_by=getattr(user, "id", None),
            keep_until=(to_local(moment).date() + timedelta(days=days))
            if days else None)
        db.session.add(row)
    row.place_key, row.place_text = key, text
    db.session.flush()
    return row


def dispose(row, user=None, note=None, today=None):
    """Thrown away. Before its day — or with no day written — only with a
    reason: the tube may be the one a doctor asks for tomorrow."""
    from app.utils.clock import local_today

    if row is None:
        raise StorageError("unknown")
    if row.disposed_at is not None:
        raise StorageError("disposed")
    note = (note or "").strip()[:200] or None
    today = today or local_today()
    early = row.keep_until is None or today < row.keep_until
    if early and not note:
        raise StorageError("need_early_reason")
    row.disposed_at = datetime.utcnow()
    row.disposed_by = getattr(user, "id", None)
    row.disposed_note = note
    return row


# ------------------------------------------------------------- the lists --
def waiting(days=7, limit=200):
    """Tubes with a result in the last days and nowhere recorded — one entry
    per tube: ``{"code", "orders", "patient"}``, newest first."""
    from app.models import SpecimenStore, VisitInvestigation

    since = datetime.utcnow() - timedelta(days=days)
    stored = {c.upper() for (c,) in db.session.query(
        SpecimenStore.sample_code).all()}
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.kind == "lab",
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.sample_code.isnot(None),
                    VisitInvestigation.sent_at.is_(None),
                    VisitInvestigation.resulted_at >= since)
            .order_by(VisitInvestigation.resulted_at.desc()).all())
    out, seen = [], {}
    for row in rows:
        code = row.sample_code.upper()
        if code in stored:
            continue
        if code not in seen:
            seen[code] = {"code": row.sample_code, "orders": [],
                          "patient": row.patient}
            out.append(seen[code])
        seen[code]["orders"].append(row)
        if len(out) >= limit:
            break
    return out


def kept(limit=500):
    from app.models import SpecimenStore

    return (SpecimenStore.query.filter(SpecimenStore.disposed_at.is_(None))
            .order_by(SpecimenStore.stored_at.desc()).limit(limit).all())


def due(today=None):
    """Kept past their day — the ones to throw away, oldest first."""
    from app.models import SpecimenStore
    from app.utils.clock import local_today

    today = today or local_today()
    return (SpecimenStore.query
            .filter(SpecimenStore.disposed_at.is_(None),
                    SpecimenStore.keep_until.isnot(None),
                    SpecimenStore.keep_until <= today)
            .order_by(SpecimenStore.keep_until, SpecimenStore.id).all())


def find(q, limit=50):
    """By the tube's code, or by the child — the search used everywhere."""
    from app.models import Patient, SpecimenStore
    from app.utils.patients import apply_patient_search

    q = (q or "").strip()
    if not q:
        return []
    ids = [pid for (pid,) in apply_patient_search(
        db.session.query(Patient.id), q).limit(200).all()]
    clause = db.func.upper(SpecimenStore.sample_code).like(f"%{q.upper()}%")
    if ids:
        clause = db.or_(clause, SpecimenStore.patient_id.in_(ids))
    return (SpecimenStore.query.filter(clause)
            .order_by(SpecimenStore.stored_at.desc()).limit(limit).all())


def register(start, end):
    """Kept and thrown away between two clinic days."""
    from app.models import SpecimenStore
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    stored = (SpecimenStore.query
              .filter(SpecimenStore.stored_at >= since,
                      SpecimenStore.stored_at <= until).count())
    gone = (SpecimenStore.query
            .filter(SpecimenStore.disposed_at >= since,
                    SpecimenStore.disposed_at <= until)
            .order_by(SpecimenStore.disposed_at.desc()).all())
    return {"stored": stored, "disposed": gone}
