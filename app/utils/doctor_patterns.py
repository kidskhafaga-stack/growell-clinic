"""«عادتك مع التشخيص ده» — a doctor's own habits, SMART_PATTERNS_PLAN ج-٣.

Counted once a day from the clinics' visits of the last 18 months: for each
diagnosis a doctor wrote, how many of those visits had each test
(``VisitInvestigation.investigation_id``) and each medicine
(``VisitMedication.drug_id`` and the lines of the visit's prescriptions).

* **«عادتك»** — 10 visits or more with the diagnosis, and the item in 60 %
  of them (both the clinic's to change, the owner's decision of 23 Nov);
  an item in 30 % of them is shown faded, «أحياناً».
* The diagnosis as written first; when its code has too few visits, its
  three-character category.
* A doctor with too few visits of a diagnosis sees **«زملاءك في القسم»** —
  the clinics' doctors together, a count and a share, never a name.
* **Only the doctor sees his own habits**: the strip is drawn on the visit
  he is the doctor of, from his own rows. No screen compares doctors.

What the strip does is the doctor's press, through the screen's own forms:
a test goes through ordering a test, a medicine through writing a medicine
— so the allergy and interaction checks run as always. A medicine carries
its usual frequency and duration; **its dose is never copied** from another
child: it is worked out from this child's weight today (``dosing.py``), and
left empty for the doctor where there is no rule. «مش عايز ده» hides an item
from that doctor for that diagnosis for good, and what is shown, taken and
refused is counted, so whether the strip helps is a number.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.extensions import db

WINDOW_DAYS = 548                 # 18 months
MIN_VISITS = 10
HABIT_SHARE = 60
SOMETIMES_SHARE = 30
CHANNELS_LEFT_OUT = ("emergency", "lab")
KEY_MIN_VISITS = "habits:min_visits"
KEY_SHARE = "habits:share"
TICK = "habits:computed_on"


# ------------------------------------------------------------ thresholds --
def thresholds():
    """``(min_visits, habit_share)`` — the clinic's, else 10 and 60 %."""
    from app.models import Setting

    def _int(key, default, low, high):
        try:
            value = int(Setting.get(key, "") or default)
        except ValueError:
            return default
        return value if low <= value <= high else default

    return (_int(KEY_MIN_VISITS, MIN_VISITS, 3, 500),
            _int(KEY_SHARE, HABIT_SHARE, SOMETIMES_SHARE + 1, 100))


def set_thresholds(min_visits, share):
    """The administrator's change; a word, or a number out of range, is
    left as it was. True when something was saved."""
    from app.models import Setting

    saved = False
    for key, raw, low, high in ((KEY_MIN_VISITS, min_visits, 3, 500),
                                (KEY_SHARE, share, SOMETIMES_SHARE + 1, 100)):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if low <= value <= high:
            Setting.set(key, str(value))
            saved = True
    return saved


def _keys(code):
    """The diagnosis as written, then its category — ``J06.9`` → ``J06``."""
    code = (code or "").strip().upper()
    if not code:
        return ()
    head = code.split(".")[0][:3]
    return (code,) if head == code else (code, head)


# ----------------------------------------------------------- the counting --
def _visits(since, today):
    """The clinics' visits from ``since`` to yesterday — today's are still
    being written."""
    from app.models import Visit

    return dict(Visit.query
                .filter(Visit.visit_date >= since, Visit.visit_date < today,
                        Visit.channel.notin_(CHANNELS_LEFT_OUT))
                .with_entities(Visit.id, Visit.doctor_id))


def _diagnoses(visit_ids):
    from app.models import Diagnosis

    out = defaultdict(set)
    for vid, code in (Diagnosis.query.filter(Diagnosis.visit_id.in_(visit_ids))
                      .with_entities(Diagnosis.visit_id, Diagnosis.code)):
        out[vid].update(_keys(code))
    return out


def _orders(visit_ids):
    """``{visit_id: {(kind, item_id): (frequency, duration)}}``."""
    from app.models import (Prescription, PrescriptionItem, VisitInvestigation,
                            VisitMedication)

    out = defaultdict(dict)
    for vid, inv in (VisitInvestigation.query
                     .filter(VisitInvestigation.visit_id.in_(visit_ids),
                             VisitInvestigation.investigation_id.isnot(None))
                     .with_entities(VisitInvestigation.visit_id,
                                    VisitInvestigation.investigation_id)):
        out[vid][("test", inv)] = (None, None)
    for vid, drug, freq, dur in (VisitMedication.query
                                 .filter(VisitMedication.visit_id.in_(visit_ids),
                                         VisitMedication.drug_id.isnot(None))
                                 .with_entities(VisitMedication.visit_id,
                                                VisitMedication.drug_id,
                                                VisitMedication.frequency,
                                                VisitMedication.duration)):
        out[vid][("drug", drug)] = (freq, dur)
    for vid, drug, freq, dur in (PrescriptionItem.query
                                 .join(Prescription,
                                       Prescription.id == PrescriptionItem.prescription_id)
                                 .filter(Prescription.visit_id.in_(visit_ids),
                                         PrescriptionItem.drug_id.isnot(None))
                                 .with_entities(Prescription.visit_id,
                                                PrescriptionItem.drug_id,
                                                PrescriptionItem.frequency,
                                                PrescriptionItem.duration)):
        # The prescription is the last word on a medicine written in the room.
        if ("drug", drug) not in out[vid] or freq or dur:
            out[vid][("drug", drug)] = (freq, dur)
    return out


def _names(items):
    from app.models import Drug, Investigation

    tests = {i for k, i in items if k == "test"}
    drugs = {i for k, i in items if k == "drug"}
    out = {}
    if tests:
        for row in Investigation.query.filter(Investigation.id.in_(tests)):
            out[("test", row.id)] = row.name_ar or row.name_en or "—"
    if drugs:
        for row in Drug.query.filter(Drug.id.in_(drugs)):
            out[("drug", row.id)] = row.label()
    return out


def _usual(values):
    seen = Counter(v.strip() for v in values if v and v.strip())
    return seen.most_common(1)[0][0] if seen else None


def refresh(today=None):
    """Count everything again; the rows before are replaced. Returns how
    many patterns were kept."""
    from app.models import OrderPattern
    from app.utils.clock import local_today

    today = today or local_today()
    min_visits, _share = thresholds()
    visits = _visits(today - timedelta(days=WINDOW_DAYS), today)
    ids = list(visits)
    dx, orders = {}, {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        dx.update(_diagnoses(chunk))
        orders.update(_orders(chunk))

    # (doctor or None, dx key) → visits, and → item → [(freq, dur)]
    counts = Counter()
    items = defaultdict(lambda: defaultdict(list))
    for vid, keys in dx.items():
        for owner in (visits[vid], None):
            for key in keys:
                counts[(owner, key)] += 1
                for item, written in orders.get(vid, {}).items():
                    items[(owner, key)][item].append(written)

    kept = []
    for group, n in counts.items():
        if n < min_visits:
            continue
        for item, written in items[group].items():
            share = 100.0 * len(written) / n
            if share >= SOMETIMES_SHARE:
                kept.append((group, item, n, len(written), round(share, 1), written))
    names = _names({item for _g, item, *_ in kept})
    now = datetime.utcnow()
    OrderPattern.query.delete()
    for (owner, key), (kind, item_id), n, seen, share, written in kept:
        db.session.add(OrderPattern(
            doctor_id=owner, dx_key=key, kind=kind, item_id=item_id,
            name=names.get((kind, item_id), "—")[:200],
            frequency=_usual(w[0] for w in written) if kind == "drug" else None,
            duration=_usual(w[1] for w in written) if kind == "drug" else None,
            visits=n, seen=seen, share=share, computed_at=now))
    return len(kept)


def maybe_refresh(today=None):
    """From the heartbeat: once a day, by one server process only."""
    from app.models import Setting
    from app.utils.clock import local_today

    today = (today or local_today()).isoformat()
    last = Setting._read(TICK)
    if last == today:
        return False
    if not Setting.swap(TICK, last, today):
        db.session.rollback()
        return False
    db.session.commit()
    try:
        refresh()
        db.session.commit()
    except Exception:  # noqa: BLE001 — tomorrow's count tries again
        db.session.rollback()
        return False
    return True


# ------------------------------------------------------- on the visit ----
def _dose(drug, patient):
    """This child's dose from today's weight, or ``None`` — never a dose
    another child had."""
    from app.utils.dosing import age_months_of, calculate, latest_weight

    generic = getattr(drug, "generic", None)
    if drug is None or generic is None or patient is None:
        return None
    result = calculate(generic, weight_kg=latest_weight(patient),
                       age_months=age_months_of(patient), product=drug)

    def _n(v):
        return f"{v:g}"

    if result.get("ml"):
        if result.get("ml_max") and result["ml_max"] != result["ml"]:
            return f"{_n(result['ml'])}–{_n(result['ml_max'])} ml"
        return f"{_n(result['ml'])} ml"
    if result.get("dose_mg"):
        if result.get("dose_mg_max") and result["dose_mg_max"] != result["dose_mg"]:
            return f"{_n(result['dose_mg'])}–{_n(result['dose_mg_max'])} mg"
        return f"{_n(result['dose_mg'])} mg"
    return None


def _refused(doctor_id):
    from app.models import SuggestionFeedback

    return {(r.dx_key, r.kind, r.item_id) for r in
            SuggestionFeedback.query.filter_by(doctor_id=doctor_id, action="never")
            .with_entities(SuggestionFeedback.dx_key, SuggestionFeedback.kind,
                           SuggestionFeedback.item_id)}


def _rows(owner, key):
    from app.models import OrderPattern

    q = OrderPattern.query.filter(OrderPattern.dx_key == key)
    q = q.filter(OrderPattern.doctor_id.is_(None) if owner is None
                 else OrderPattern.doctor_id == owner)
    return q.order_by(OrderPattern.share.desc(), OrderPattern.name).all()


def for_visit(visit, user):
    """The strip for this visit, or ``[]``. Drawn only for the visit's own
    doctor, from his own habits first — never another doctor's by name."""
    from app.models import Drug

    if visit is None or user is None or visit.doctor_id != getattr(user, "id", None):
        return []
    _min, share = thresholds()
    have = ({("test", i.investigation_id) for i in visit.investigations if i.investigation_id}
            | {("drug", m.drug_id) for m in visit.medications if m.drug_id})
    refused = _refused(user.id)
    shown, out = set(), []
    for dx in visit.diagnoses:
        keys = _keys(dx.code)
        if not keys or keys[0] in {g["dx_key"] for g in out}:
            continue
        found = None
        for owner, source in ((user.id, "mine"), (None, "colleagues")):
            for key in keys:
                rows = _rows(owner, key)
                if rows:
                    found = (source, key, rows)
                    break
            if found:
                break
        if not found:
            continue
        source, key, rows = found
        items = []
        for row in rows:
            item = (row.kind, row.item_id)
            if item in have or item in shown or (key, row.kind, row.item_id) in refused:
                continue
            shown.add(item)
            entry = {"kind": row.kind, "item_id": row.item_id, "name": row.name,
                     "share": round(row.share), "seen": row.seen,
                     "habit": row.share >= share,
                     "frequency": row.frequency, "duration": row.duration, "dose": None}
            if row.kind == "drug":
                entry["dose"] = _dose(db.session.get(Drug, row.item_id), visit.patient)
            items.append(entry)
        if not items:
            continue
        habit_drugs = [i for i in items if i["kind"] == "drug" and i["habit"]]
        out.append({"dx_key": key, "title": dx.display_title(), "source": source,
                    "visits": rows[0].visits, "items": items,
                    "offer_preset": (source == "mine" and len(habit_drugs) >= 2
                                     and not _has_preset(user.id, key))})
    return out


def _has_preset(doctor_id, key):
    from app.models import RxPreset

    return RxPreset.query.filter(RxPreset.doctor_id == doctor_id,
                                 RxPreset.is_active.is_(True),
                                 RxPreset.note == _preset_note(key)).first() is not None


def _preset_note(key):
    return f"habits:{key}"


# --------------------------------------------------------- the measuring --
def _feedback(user_id, visit_id, key, kind, item_id, action):
    from app.models import SuggestionFeedback

    db.session.add(SuggestionFeedback(doctor_id=user_id, visit_id=visit_id, dx_key=key[:12],
                                      kind=kind, item_id=item_id, action=action))


def note_shown(visit, user, groups):
    """Each item counted once per visit as shown."""
    from app.models import SuggestionFeedback

    if not groups:
        return
    before = {(r.kind, r.item_id) for r in SuggestionFeedback.query
              .filter_by(visit_id=visit.id, action="shown")
              .with_entities(SuggestionFeedback.kind, SuggestionFeedback.item_id)}
    added = False
    for g in groups:
        for i in g["items"]:
            if (i["kind"], i["item_id"]) not in before:
                _feedback(user.id, visit.id, g["dx_key"], i["kind"], i["item_id"], "shown")
                added = True
    if added:
        db.session.commit()


def note_taken(visit, user, form, kind, item_id):
    """Called by the add-a-test and add-a-medicine routes: the press came
    from the strip when the form carries ``habit_dx``."""
    key = (form.get("habit_dx") or "").strip()
    if key and item_id and user is not None:
        _feedback(user.id, visit.id, key, kind, item_id, "taken")


def refuse(visit, user, key, kind, item_id):
    if kind not in ("test", "drug") or not key:
        return False
    _feedback(user.id, visit.id, key, kind, item_id, "never")
    return True


def usage(doctor_id=None, days=90):
    """``{shown, taken, never, taken_pct}`` — one doctor's, or the clinic's
    together (never doctor by doctor)."""
    from app.models import SuggestionFeedback

    q = SuggestionFeedback.query.filter(
        SuggestionFeedback.at >= datetime.utcnow() - timedelta(days=days))
    if doctor_id is not None:
        q = q.filter(SuggestionFeedback.doctor_id == doctor_id)
    counts = Counter(a for (a,) in q.with_entities(SuggestionFeedback.action))
    shown = counts.get("shown", 0)
    return {"shown": shown, "taken": counts.get("taken", 0), "never": counts.get("never", 0),
            "taken_pct": round(100.0 * counts.get("taken", 0) / shown) if shown else None}


def mine(doctor_id):
    """A doctor's own habits, by diagnosis — his screen, no one else's."""
    from app.models import Diagnosis, OrderPattern

    _min, share = thresholds()
    rows = (OrderPattern.query.filter(OrderPattern.doctor_id == doctor_id)
            .order_by(OrderPattern.dx_key, OrderPattern.share.desc()).all())
    groups = {}
    for r in rows:
        g = groups.setdefault(r.dx_key, {"dx_key": r.dx_key, "visits": r.visits, "items": []})
        g["items"].append({"kind": r.kind, "name": r.name, "share": round(r.share),
                           "habit": r.share >= share, "frequency": r.frequency,
                           "duration": r.duration})
    titles = {}
    if groups:
        for code, title in (Diagnosis.query.filter(Diagnosis.code.in_(list(groups)))
                            .with_entities(Diagnosis.code, Diagnosis.title)):
            titles.setdefault((code or "").upper(), title)
    # A category with the same visits as one code under it says nothing new.
    for key in [k for k in groups if "." not in k]:
        if any(k != key and k.startswith(key) and g["visits"] == groups[key]["visits"]
               for k, g in groups.items()):
            del groups[key]
    for key, g in groups.items():
        g["title"] = titles.get(key, "")
    return sorted(groups.values(), key=lambda g: -g["visits"])


def save_preset(visit, user, key, lang="ar"):
    """«تحب تحفظها روشتة جاهزة؟» — the doctor's own habitual medicines with
    this diagnosis as a ready prescription, on his press. Doses are left for
    each child's weight. Returns the preset or ``None``."""
    from app.models import RxPreset, RxPresetItem

    _min, share = thresholds()
    rows = [r for r in _rows(user.id, key) if r.kind == "drug" and r.share >= share]
    if len(rows) < 2 or _has_preset(user.id, key):
        return None
    title = next((d.display_title(lang) for d in visit.diagnoses
                  if key in _keys(d.code)), key)
    preset = RxPreset(name=title[:120], note=_preset_note(key), diagnosis=title[:200],
                      doctor_id=user.id, is_shared=False, is_active=True)
    for r in rows:
        preset.items.append(RxPresetItem(drug_id=r.item_id, drug_name=r.name,
                                         frequency=r.frequency, duration=r.duration))
    db.session.add(preset)
    return preset
