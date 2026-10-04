"""A result written analyte by analyte, read against the child's own range.

Asked as *«البرنامج يطلع النتيجة ويعرفها ويفهمها ويفهما للطبيب»*. A CBC is a
dozen numbers, each with its own usual range for a child of this age and sex,
and until now the order had room for one number and a range typed in by hand.

**What is judged, and against what.**

* The range is the laboratory's own (`models/lab_reference.LabRange`), chosen
  for this child: the age in days on the day the sample was drawn, and the
  sex. A row for the child's sex is preferred to one for everybody, and a
  narrow age band to a wide one.
* **Only an approved range calls a value high or low.** A draft is shown
  beside the value as a reference and says it is a draft; it flags nothing.
  No range at all is no flag at all — never «normal».
* A *cutoff* (a lipid target) is a guideline, not a usual range: shown, never
  used to flag. A *note* is words.
* Critical is the laboratory's own critical limits, on the approved row, and
  nothing else. Strictly beyond the limit: a limit of 7 flags 6.9, not 7.

**And the doctor is told.** A critical value is stamped on the order and sits
on the bell of whoever answers for the child — the doctor who ordered it, the
visit's doctor, the stay's responsible doctor, and whoever is on the rota now
— until one of them says they have read it (`mark_read`).

None of this runs in a clinic without the lab module: the values are written
only from the lab's result screen, and every other screen reads the counts on
the order, which stay empty.
"""
import re
import threading
import time
from datetime import datetime

from app.extensions import db

#: The Arabic-Indic digits and separators a phone keyboard types.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
#: A plain number — no «<», no «+», no comma. Anything else is words.
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def parse(raw):
    """``(number, words)`` from what was typed — one of them, or neither.

    A comma is kept as words rather than guessed at: «12,5» is twelve and a
    half in one lab and twelve thousand five hundred in the next, and a WBC
    read the wrong way is not a rounding error.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, None
    cleaned = raw.translate(_DIGITS).replace("٬", "").replace(" ", "")
    if _NUMBER.match(cleaned):
        return float(cleaned), None
    return None, raw[:120]


# ------------------------------------------------------------ the child ---
def age_days(patient, at=None):
    """The child's age in days on the clinic's day of ``at`` (UTC)."""
    from app.utils.clock import local_date, local_today

    born = getattr(patient, "date_of_birth", None)
    if born is None:
        return None
    on = local_date(at) if at is not None else local_today()
    if on is None:
        on = local_today()
    return max(0, (on - born).days)


def sex_of(patient):
    gender = (getattr(patient, "gender", None) or "").strip().lower()
    return gender if gender in ("male", "female") else None


# ------------------------------------------------------------ the range ---
def _span(rng):
    return (rng.age_to_days - (rng.age_from_days or 0)
            if rng.age_to_days is not None else float("inf"))


def _best(rows):
    """The most specific of the rows that fit: this sex before everybody,
    then the narrowest band, then the newest."""
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r.sex == "all", _span(r),
                                       -(r.id or 0)))[0]


def references(analyte, age, sex):
    """``(approved, draft)`` — the row that judges and the one that only
    informs. Either may be ``None``."""
    fit = [r for r in (analyte.ranges or []) if r.covers(age, sex)]
    approved = _best([r for r in fit if r.approved])
    draft = _best([r for r in fit if not r.approved])
    return approved, draft


def judge(value, rng):
    """What ``value`` is called against ``rng``, or ``None``.

    ``None`` whenever the answer would be a guess: no value, no range, a
    range nobody approved, or one that is not a usual range.
    """
    if value is None or rng is None or not rng.approved:
        return None
    if rng.critical_low is not None and value < rng.critical_low:
        return "critical_low"
    if rng.critical_high is not None and value > rng.critical_high:
        return "critical_high"
    if rng.kind != "interval" or (rng.low is None and rng.high is None):
        return None
    if rng.low is not None and value < rng.low:
        return "low"
    if rng.high is not None and value > rng.high:
        return "high"
    return "normal"


# ------------------------------------------------------------ the sheet ---
def measured(order):
    """Whether this order is answered analyte by analyte."""
    inv = order.investigation
    return bool(inv is not None and inv.analyte_links)


def sheet(order):
    """One line per analyte, in report order, for the form and the report:
    ``[{analyte, row, approved, draft, unit}]``.

    ``row`` is the value already written, if any. A value written for an
    analyte the test no longer lists is still shown, at the end — a result is
    not unwritten because the catalogue changed.
    """
    at = order.collected_at or order.created_at
    age, sex = age_days(order.patient, at), sex_of(order.patient)
    written = {v.analyte_id: v for v in (order.analyte_values or [])}
    out, seen = [], set()
    links = (order.investigation.analyte_links
             if order.investigation is not None else [])
    for link in links:
        a = link.analyte
        seen.add(a.id)
        approved, draft = references(a, age, sex)
        out.append({"analyte": a, "row": written.get(a.id),
                    "approved": approved, "draft": draft,
                    "unit": a.unit})
    for aid, v in written.items():
        if aid not in seen:
            out.append({"analyte": v.analyte, "row": v, "approved": None,
                        "draft": None, "unit": v.unit})
    return out


def _snapshot(row, rng):
    row.range_id = rng.id if rng is not None else None
    row.range_approved = bool(rng is not None and rng.approved)
    for mine, theirs in (("ref_kind", "kind"), ("ref_low", "low"),
                         ("ref_high", "high"), ("crit_low", "critical_low"),
                         ("crit_high", "critical_high"),
                         ("ref_label", "age_label"), ("ref_note", "note")):
        setattr(row, mine, getattr(rng, theirs) if rng is not None else None)


def save(order, entries, user=None, text=None, at=None):
    """Write the values typed for ``order``.

    ``entries`` is ``{analyte_id: raw text}``. A blank one removes the value
    it had. Returns the list of values that are critical now.

    The range each value is read against is copied onto it at this moment,
    so approving a new sheet next month does not re-read this one.
    """
    from app.models import LabResultValue
    from app.utils import labs as bench

    now = at or datetime.utcnow()
    lines = {line["analyte"].id: (i, line) for i, line in
             enumerate(sheet(order))}
    existing = {v.analyte_id: v for v in (order.analyte_values or [])}
    for aid, raw in entries.items():
        if aid not in lines:
            continue
        i, line = lines[aid]
        number, words = parse(raw)
        row = existing.get(aid)
        if number is None and words is None:
            if row is not None:
                order.analyte_values.remove(row)
                db.session.delete(row)
            continue
        if row is None:
            row = LabResultValue(analyte_id=aid, analyte=line["analyte"])
            order.analyte_values.append(row)
            existing[aid] = row
        changed = (row.value != number or (row.text or None) != words
                   or row.id is None)
        row.sort_order = i
        row.value, row.text = number, words
        row.unit = line["unit"]
        # Judged against the approved row; when there is none, the draft is
        # kept as the reference the report prints beside it, flagging nothing.
        rng = line["approved"] or line["draft"]
        _snapshot(row, rng)
        row.flag = judge(number, line["approved"])
        if changed:
            row.entered_at = now
            row.entered_by = getattr(user, "id", None)

    values = [v for v in order.analyte_values if v.has_value]
    order.analytes_resulted = len(values) or None
    order.abnormal_count = sum(1 for v in values if v.abnormal) or None
    critical = [v for v in values if v.critical]
    if critical and order.critical_at is None:
        order.critical_at = now
        order.critical_seen_at = order.critical_seen_by = None
    elif not critical and not order.critical_manual:
        # Corrected — a typo, not a child in danger. The stamp goes with it,
        # and the activity log keeps that it was ever there. One the lab
        # marked critical by hand stays: no number decided it, and no number
        # takes it away (`utils/lab_critical`).
        order.critical_at = order.critical_seen_at = None
        order.critical_seen_by = None

    _mirror(order, values)
    if text is not None:
        order.result_text = (text or "").strip() or None
    bench.settle(order, user=user, at=now)
    invalidate()
    return critical


def _mirror(order, values):
    """A test of **one** analyte keeps its number where every curve, the
    file and the export already read it — `result_value` and the range.

    Only one: a CBC's twelve numbers have no one of them that is «the»
    result, and picking the first would draw a haemoglobin curve labelled
    «CBC».
    """
    links = order.investigation.analyte_links if order.investigation else []
    if len(links) != 1:
        return
    v = values[0] if values else None
    if v is None or v.value is None:
        order.result_value = None
        order.result_low = order.result_high = None
        if v is None:
            order.result_unit = None
        return
    order.result_value = v.value
    order.result_unit = (v.unit or "")[:20] or None
    usual = v.range_approved and v.ref_kind == "interval"
    order.result_low = v.ref_low if usual else None
    order.result_high = v.ref_high if usual else None


# ------------------------------------------------------- critical values ---
_CACHE = {"at": 0.0, "rows": None}
_LOCK = threading.Lock()
#: Seconds the list of unread critical values is kept. Saving or reading one
#: clears it at once; this only bounds how stale the rota part can get.
_TTL = 30


def invalidate():
    _CACHE["at"], _CACHE["rows"] = 0.0, None


def _on_duty_now():
    """The doctors the rota has on right now, present or on call."""
    try:
        from app.utils.on_call import covering

        ids = set()
        for group in covering(roles_only=False):
            for duty in group["present"] + group["on_call"]:
                if duty.doctor_id:
                    ids.add(duty.doctor_id)
        return ids
    except Exception:  # noqa: BLE001 — a rota problem never hides a result
        return set()


def _waiting_rows():
    """``[(order_id, {user ids told})]`` for every critical value nobody has
    read — one query every few seconds, shared by everybody."""
    rows = _CACHE["rows"]
    if rows is not None and time.time() - _CACHE["at"] <= _TTL:
        return rows
    with _LOCK:
        from app.models import Admission, VisitInvestigation

        found = (VisitInvestigation.query
                 .filter(VisitInvestigation.critical_at.isnot(None),
                         VisitInvestigation.critical_seen_at.is_(None))
                 .order_by(VisitInvestigation.critical_at)
                 .limit(200).all())
        duty = _on_duty_now() if found else set()
        out = []
        for order in found:
            told = set(duty)
            told.update(i for i in (order.ordered_by,
                                    getattr(order.visit, "doctor_id", None))
                        if i)
            if order.admission_id:
                # The stay's responsible doctor now — not whoever admitted:
                # `ACT.07` moves the responsibility, and the call goes with it.
                stay = db.session.get(Admission, order.admission_id)
                mrp = stay.responsible_doctor if stay is not None else None
                if mrp is not None:
                    told.add(mrp.id)
            out.append((order.id, told))
        _CACHE["rows"], _CACHE["at"] = out, time.time()
        return out


def reads_results(user):
    """Whether this person is somebody a critical value is for — a doctor,
    or anybody who consults."""
    from app.models import User

    return bool(user is not None and getattr(user, "is_authenticated", False)
                and User.sees_patients(user.role, user.is_practitioner))


def critical_for(user):
    """The ids of the unread critical values that are this person's."""
    if not reads_results(user):
        return []
    try:
        return [oid for oid, told in _waiting_rows() if user.id in told]
    except Exception:  # noqa: BLE001 — the bell never breaks a page
        return []


def all_waiting():
    """Every unread critical value, oldest first — the lab's own list."""
    from app.models import VisitInvestigation

    return (VisitInvestigation.query
            .filter(VisitInvestigation.critical_at.isnot(None),
                    VisitInvestigation.critical_seen_at.is_(None))
            .order_by(VisitInvestigation.critical_at).all())


def mark_read(order, user, at=None):
    """A doctor has read the critical value on ``order``."""
    if order.critical_at is None:
        raise ValueError("nothing critical")
    if not reads_results(user):
        raise PermissionError("not a doctor")
    order.critical_seen_at = at or datetime.utcnow()
    order.critical_seen_by = user.id
    invalidate()
    return order


# ------------------------------------------------------------- lateness ---
def late(order, now=None):
    """Whether this sample has waited longer than the laboratory says the
    test takes — ``None`` when the laboratory has not said. The routine
    figure: an order carries no «urgent» mark to choose the STAT one by."""
    inv = order.investigation
    limit = getattr(inv, "tat_max", None) or getattr(inv, "tat_min", None)
    if not limit or order.status == "resulted" or order.done_outside:
        return None
    # The laboratory's time runs from the sample, not from the order: a test
    # nobody has drawn yet is waiting on the ward, and the rack already says
    # so by listing it under «to collect».
    start = order.collected_at
    if start is None:
        return None
    waited = ((now or datetime.utcnow()) - start).total_seconds() / 60
    return waited > limit
