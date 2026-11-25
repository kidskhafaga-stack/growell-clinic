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
CHANNELS_LEFT_OUT = ("emergency", "lab", "ward")
KEY_MIN_VISITS = "habits:min_visits"
KEY_SHARE = "habits:share"
TICK = "habits:computed_on"
#: The departments counted from stays, by the unit of the child's bed.
STAY_DEPTS = ("ward", "icu", "nicu")


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
def _visits(since, today, dept="clinic"):
    """The department's visits from ``since`` to yesterday — today's are
    still being written. An emergency attendance's diagnosis lives on its
    own encounter, ``channel="emergency"``."""
    from app.models import Visit

    q = Visit.query.filter(Visit.visit_date >= since, Visit.visit_date < today)
    q = (q.filter(Visit.channel == "emergency") if dept == "emergency"
         else q.filter(Visit.channel.notin_(CHANNELS_LEFT_OUT)))
    return dict(q.with_entities(Visit.id, Visit.doctor_id))


def _diagnoses(visit_ids):
    from app.models import Diagnosis

    out = defaultdict(set)
    for vid, code in (Diagnosis.query.filter(Diagnosis.visit_id.in_(visit_ids))
                      .with_entities(Diagnosis.visit_id, Diagnosis.code)):
        out[vid].update(_keys(code))
    return out


def _tests(visit_ids, out):
    from app.models import VisitInvestigation

    for vid, inv in (VisitInvestigation.query
                     .filter(VisitInvestigation.visit_id.in_(visit_ids),
                             VisitInvestigation.investigation_id.isnot(None))
                     .with_entities(VisitInvestigation.visit_id,
                                    VisitInvestigation.investigation_id)):
        out[vid][("test", inv)] = (None, None, None)


def _orders_er(visit_ids):
    """The emergency department's: tests on the encounter, and what our
    doctors wrote on the attendance — not a cancelled line, not an outside
    doctor's paper. ``{visit_id: {(kind, item_id): (None, None, route)}}``."""
    from app.models import EmergencyOrder, EmergencyVisit
    from app.models.emergency_order import OUTSIDE_RX

    out = defaultdict(dict)
    _tests(visit_ids, out)
    for vid, drug, route in (EmergencyOrder.query
                             .join(EmergencyVisit,
                                   EmergencyVisit.id == EmergencyOrder.emergency_visit_id)
                             .filter(EmergencyVisit.visit_id.in_(visit_ids),
                                     EmergencyOrder.drug_id.isnot(None),
                                     EmergencyOrder.cancelled_at.is_(None),
                                     EmergencyOrder.source != OUTSIDE_RX)
                             .with_entities(EmergencyVisit.visit_id, EmergencyOrder.drug_id,
                                            EmergencyOrder.route)):
        out[vid][("drug", drug)] = (None, None, route)
    return out


def _orders(visit_ids):
    """``{visit_id: {(kind, item_id): (frequency, duration, route)}}``."""
    from app.models import Prescription, PrescriptionItem, VisitMedication

    out = defaultdict(dict)
    _tests(visit_ids, out)
    for vid, drug, freq, dur in (VisitMedication.query
                                 .filter(VisitMedication.visit_id.in_(visit_ids),
                                         VisitMedication.drug_id.isnot(None))
                                 .with_entities(VisitMedication.visit_id,
                                                VisitMedication.drug_id,
                                                VisitMedication.frequency,
                                                VisitMedication.duration)):
        out[vid][("drug", drug)] = (freq, dur, None)
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
            out[vid][("drug", drug)] = (freq, dur, None)
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


def departments():
    """The clinics always; the emergency department and the ward where they
    run (ج-٤)."""
    from app.utils.facility import module_enabled

    out = ["clinic"]
    if module_enabled("emergency"):
        out.append("emergency")
    if module_enabled("beds"):
        out.append("ward")
    # Intensive care and the incubators, each its own habits (ج-٤ ج): a
    # neonate's orders are not a ward child's.
    for dept in ("icu", "nicu"):
        if module_enabled(dept):
            out.append(dept)
    # The sentences a reporter usually writes for each kind of study (ج-٤ د).
    if module_enabled("imaging"):
        out.append("imaging")
    return tuple(out)


def _setting_of(dept):
    from app.utils import care_setting

    return {"ward": care_setting.INPATIENT, "icu": care_setting.ICU,
            "nicu": care_setting.NICU}[dept]


def dept_of_stay(admission):
    """``ward``, ``icu`` or ``nicu`` — the unit of the child's bed."""
    from app.utils import care_setting

    return {care_setting.INPATIENT: "ward", care_setting.ICU: "icu",
            care_setting.NICU: "nicu"}.get(care_setting.of_admission(admission))


def _ward(since, today, dept="ward"):
    """The ward's stays admitted from ``since`` to yesterday and ended, in a
    ward bed
    (intensive care and the incubators are their own part, later): the
    diagnosis on the stay's encounter, the tests the stay owns, and the
    standing orders — each drug with its usual interval and route.
    ``(owners, dx, orders)`` keyed by the stay."""
    from app.models import Admission, MedicationOrder, VisitInvestigation
    from app.utils import care_setting
    from app.utils.med_board import utc

    start, end = utc(since, today - timedelta(days=1))
    # A stay still open is still being written: only the ones that ended.
    stays = [a for a in Admission.query.filter(Admission.admitted_at >= start,
                                               Admission.admitted_at < end,
                                               Admission.discharged_at.isnot(None))
             if a.visit_id and care_setting.of_admission(a) == _setting_of(dept)]
    owners = {a.id: a.doctor_id or (a.visit.doctor_id if a.visit else None) for a in stays}
    visit_of = {a.id: a.visit_id for a in stays}
    by_visit = defaultdict(list)
    for a in stays:
        by_visit[a.visit_id].append(a.id)
    dx, orders = {}, defaultdict(dict)
    ids = list(owners)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for vid, keys in _diagnoses([visit_of[a] for a in chunk]).items():
            for aid in by_visit[vid]:
                dx[aid] = keys
        for aid, inv in (VisitInvestigation.query
                         .filter(VisitInvestigation.admission_id.in_(chunk),
                                 VisitInvestigation.investigation_id.isnot(None))
                         .with_entities(VisitInvestigation.admission_id,
                                        VisitInvestigation.investigation_id)):
            orders[aid][("test", inv)] = (None, None, None)
        for aid, drug, every, prn, route in (
                MedicationOrder.query
                .filter(MedicationOrder.admission_id.in_(chunk),
                        MedicationOrder.drug_id.isnot(None))
                .with_entities(MedicationOrder.admission_id, MedicationOrder.drug_id,
                               MedicationOrder.every_hours, MedicationOrder.is_prn,
                               MedicationOrder.route)):
            often = "prn" if prn else (str(every) if every else None)
            orders[aid][("drug", drug)] = (often, None, route)
    return owners, dx, orders


def refresh(today=None):
    """Count everything again, department by department; the rows before
    are replaced. Returns how many patterns were kept."""
    from app.models import OrderPattern

    OrderPattern.query.delete()
    return sum(_refresh_dept(dept, today) for dept in departments())


def _refresh_dept(dept, today=None):
    from app.models import OrderPattern
    from app.utils.clock import local_today

    if dept == "imaging":
        return _refresh_imaging(today or local_today())

    today = today or local_today()
    min_visits, _share = thresholds()
    since = today - timedelta(days=WINDOW_DAYS)
    if dept in STAY_DEPTS:
        visits, dx, orders = _ward(since, today, dept)
    else:
        visits = _visits(since, today, dept)
        ids = list(visits)
        dx, orders = {}, {}
        read = _orders_er if dept == "emergency" else _orders
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            dx.update(_diagnoses(chunk))
            orders.update(read(chunk))

    # (doctor or None, dx key) → visits, and → item → [(freq, dur)]
    counts = Counter()
    items = defaultdict(lambda: defaultdict(list))
    for vid, keys in dx.items():
        for owner in ((visits[vid], None) if visits.get(vid) is not None else (None,)):
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
    for (owner, key), (kind, item_id), n, seen, share, written in kept:
        db.session.add(OrderPattern(
            dept=dept, doctor_id=owner, dx_key=key, kind=kind, item_id=item_id,
            name=names.get((kind, item_id), "—")[:200],
            frequency=_usual(w[0] for w in written) if kind == "drug" else None,
            duration=_usual(w[1] for w in written) if kind == "drug" else None,
            route=_usual(w[2] for w in written) if kind == "drug" else None,
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


def _rows(owner, key, dept="clinic"):
    from sqlalchemy import or_

    from app.models import OrderPattern

    q = OrderPattern.query.filter(OrderPattern.dx_key == key)
    q = q.filter(OrderPattern.dept == dept if dept != "clinic"
                 else or_(OrderPattern.dept == "clinic", OrderPattern.dept.is_(None)))
    q = q.filter(OrderPattern.doctor_id.is_(None) if owner is None
                 else OrderPattern.doctor_id == owner)
    return q.order_by(OrderPattern.share.desc(), OrderPattern.name).all()


def for_visit(visit, user):
    """The strip for this visit, or ``[]``. Drawn only for the visit's own
    doctor, from his own habits first — never another doctor's by name."""
    if visit is None or user is None or visit.doctor_id != getattr(user, "id", None):
        return []
    # An emergency or ward encounter's strip is on its attendance or stay
    # page, where the department's own orders are written.
    if visit.channel in ("emergency", "ward"):
        return []
    have = ({("test", i.investigation_id) for i in visit.investigations if i.investigation_id}
            | {("drug", m.drug_id) for m in visit.medications if m.drug_id})
    return _suggest(visit, user, "clinic", have)


def for_attendance(attendance, user):
    """The strip on an emergency attendance (ج-٤): the diagnosis written on
    its encounter, the habits of the doctor looking at it — any of our
    doctors on the shift, each his own — and nothing already written for
    this child here."""
    from app.utils import emergency_orders as eo

    visit = getattr(attendance, "visit", None)
    if visit is None or not visit.diagnoses or not eo.is_doctor(user):
        return []
    have = ({("test", i.investigation_id) for i in visit.investigations if i.investigation_id}
            | {("drug", o.drug_id) for o in eo.for_attendance(attendance)
               if o.drug_id and o.cancelled_at is None})
    return _suggest(visit, user, "emergency", have)


def for_stay(admission, user):
    """The strip on a stay (ج-٤): the ward's, intensive care's or the
    incubators' habits by the unit of the child's bed; the diagnosis written
    on the stay's encounter, the habits of the doctor looking at it — each
    his own — and nothing the stay already has running or ordered."""
    from app.models import VisitInvestigation
    from app.utils import emergency_orders as eo

    visit = getattr(admission, "visit", None)
    if (admission is None or not admission.is_open or visit is None or not visit.diagnoses
            or not eo.is_doctor(user)):
        return []
    dept = dept_of_stay(admission)
    if dept not in departments():
        return []
    have = ({("drug", o.drug_id) for o in admission.medication_orders
             if o.drug_id and o.is_running}
            | {("test", inv) for (inv,) in VisitInvestigation.query
               .filter(VisitInvestigation.admission_id == admission.id,
                       VisitInvestigation.investigation_id.isnot(None))
               .with_entities(VisitInvestigation.investigation_id)})
    return _suggest(visit, user, dept, have)


def _suggest(visit, user, dept, have):
    from app.models import Drug

    _min, share = thresholds()
    refused = _refused(user.id)
    shown, out = set(), []
    for dx in visit.diagnoses:
        keys = _keys(dx.code)
        if not keys or keys[0] in {g["dx_key"] for g in out}:
            continue
        found = None
        for owner, source in ((user.id, "mine"), (None, "colleagues")):
            for key in keys:
                rows = _rows(owner, key, dept)
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
                     "frequency": row.frequency, "duration": row.duration,
                     "route": row.route, "dose": None}
            if row.kind == "drug":
                entry["dose"] = _dose(db.session.get(Drug, row.item_id), visit.patient)
            items.append(entry)
        if not items:
            continue
        habit_drugs = [i for i in items if i["kind"] == "drug" and i["habit"]]
        out.append({"dx_key": key, "title": dx.display_title(), "source": source,
                    "visits": rows[0].visits, "items": items, "dept": dept,
                    "offer_preset": (dept == "clinic" and source == "mine"
                                     and len(habit_drugs) >= 2
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
    if kind not in ("test", "drug", "phrase") or not key or not item_id:
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
    """A doctor's own habits, by department and diagnosis — his screen, no
    one else's."""
    from app.models import Diagnosis, OrderPattern

    _min, share = thresholds()
    rows = (OrderPattern.query.filter(OrderPattern.doctor_id == doctor_id)
            .order_by(OrderPattern.dx_key, OrderPattern.share.desc()).all())
    groups = {}
    for r in rows:
        dept = r.dept or "clinic"
        g = groups.setdefault((dept, r.dx_key), {"dx_key": r.dx_key, "dept": dept,
                                                 "visits": r.visits, "items": []})
        g["items"].append({"kind": r.kind, "name": r.name, "share": round(r.share),
                           "habit": r.share >= share,
                           # A sentence's «frequency» is which box it goes in.
                           "frequency": r.frequency if r.kind != "phrase" else None,
                           "duration": r.duration, "route": r.route})
    titles = {}
    if groups:
        codes = list({k for _d, k in groups})
        for code, title in (Diagnosis.query.filter(Diagnosis.code.in_(codes))
                            .with_entities(Diagnosis.code, Diagnosis.title)):
            titles.setdefault((code or "").upper(), title)
    # A category with the same visits as one code under it says nothing new.
    for dept, key in [k for k in groups if "." not in k[1] and k[0] != "imaging"]:
        if any(d == dept and k != key and k.startswith(key)
               and g["visits"] == groups[(dept, key)]["visits"]
               for (d, k), g in groups.items()):
            del groups[(dept, key)]
    for (_d, key), g in groups.items():
        g["title"] = titles.get(key, "")
    # A report's sentences are kept by the kind of study, named here.
    studies = [int(k[1:]) for d, k in groups if d == "imaging" and k[1:].isdigit()]
    if studies:
        from app.models import Investigation

        names = {f"i{r.id}": r.name_ar or r.name_en or "" for r in
                 Investigation.query.filter(Investigation.id.in_(studies))}
        for (d, key), g in groups.items():
            if d == "imaging":
                g["title"] = names.get(key, "")
    return sorted(groups.values(), key=lambda g: (g["dept"] != "clinic", -g["visits"]))


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


# ------------------------------------------------ imaging reports (ج-٤ د) --
#: The two boxes of a report.
BOXES = ("text", "comment")
PHRASE_MIN, PHRASE_MAX = 8, 200


def phrases(text):
    """A report's sentences, as a reporter would recognise them again:
    one per line or per full stop, spaces folded, the stop dropped."""
    import re

    out = []
    for line in re.split(r"[\n\r]+|(?<=[.!؟?])\s+", text or ""):
        line = " ".join(line.split()).strip(" .-•*")
        if PHRASE_MIN <= len(line) <= PHRASE_MAX and line not in out:
            out.append(line)
    return out


def phrase_id(box, sentence):
    import zlib

    return zlib.crc32(f"{box}|{sentence}".encode("utf-8")) & 0x7FFFFFFF


def _study_key(investigation_id):
    return f"i{investigation_id}"[:12]


def _refresh_imaging(today):
    """Reports written in the program — a PDF has no sentences to count —
    by their reporter, per kind of study."""
    from app.models import OrderPattern, VisitInvestigation
    from app.utils.med_board import utc

    min_visits, _share = thresholds()
    start, end = utc(today - timedelta(days=WINDOW_DAYS), today - timedelta(days=1))
    counts = Counter()
    seen = defaultdict(Counter)
    for who, inv, text, comment in (VisitInvestigation.query
                                    .filter(VisitInvestigation.kind == "imaging",
                                            VisitInvestigation.investigation_id.isnot(None),
                                            VisitInvestigation.resulted_at >= start,
                                            VisitInvestigation.resulted_at < end,
                                            VisitInvestigation.result_text.isnot(None))
                                    .with_entities(VisitInvestigation.resulted_by,
                                                   VisitInvestigation.investigation_id,
                                                   VisitInvestigation.result_text,
                                                   VisitInvestigation.result_comment)):
        sentences = {("text", x) for x in phrases(text)} | {("comment", x) for x in phrases(comment)}
        if not sentences:
            continue
        for owner in ((who, None) if who is not None else (None,)):
            counts[(owner, inv)] += 1
            seen[(owner, inv)].update(sentences)
    now = datetime.utcnow()
    kept = 0
    for (owner, inv), n in counts.items():
        if n < min_visits:
            continue
        for (box, sentence), k in seen[(owner, inv)].items():
            share = 100.0 * k / n
            if share >= SOMETIMES_SHARE:
                db.session.add(OrderPattern(
                    dept="imaging", doctor_id=owner, dx_key=_study_key(inv), kind="phrase",
                    item_id=phrase_id(box, sentence), name=sentence, frequency=box,
                    visits=n, seen=k, share=round(share, 1), computed_at=now))
                kept += 1
    return kept


def for_report(order, user):
    """The reporter's usual sentences for this kind of study, or the
    department's together without names — for the boxes of the report.
    Nothing already in the report, nothing refused."""
    if order is None or user is None or not order.investigation_id \
            or "imaging" not in departments():
        return []
    key = _study_key(order.investigation_id)
    _min, share = thresholds()
    refused = _refused(user.id)
    written = {"text": set(phrases(order.result_text)),
               "comment": set(phrases(order.result_comment))}
    for owner, source in ((user.id, "mine"), (None, "colleagues")):
        rows = _rows(owner, key, "imaging")
        if rows:
            break
    else:
        return []
    items = [{"kind": "phrase", "item_id": r.item_id, "name": r.name, "box": r.frequency,
              "share": round(r.share), "habit": r.share >= share}
             for r in rows
             if r.name not in written.get(r.frequency, set())
             and (key, "phrase", r.item_id) not in refused]
    if not items:
        return []
    return [{"dx_key": key, "source": source, "visits": rows[0].visits, "items": items,
             "dept": "imaging"}]
