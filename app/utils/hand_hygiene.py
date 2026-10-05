"""Hand hygiene — GAHAR IPC.04 / GSR.22. Models in
``app/models/hand_hygiene.py``.

**The rules the records keep:**

* an observation names the staff category, never the person — the WHO tool
  measures the place, not the individual, and staff who are named stop
  being observed honestly;
* each opportunity has its moment(s) and what was done; compliance is
  actions over opportunities, the WHO's formula, and nothing else;
* a missing sink, soap, towel, rub, poster or basket needs what was done
  about it beside it;
* **the target is the hospital's**: without one written, a rate is shown and
  nothing is called below target.
"""
from datetime import date, datetime

from app.extensions import db
from app.models.hand_hygiene import (ACTIONS, CATEGORIES, FACILITY_ITEMS,
                                     MOMENTS, HandHygieneAction,
                                     HandHygieneFacilityCheck,
                                     HandHygieneOpportunity,
                                     HandHygieneSession, HandHygieneTraining)

TARGET_SETTING = "hand_hygiene_target"
#: Rows the observation form offers; a session longer than this is two.
MAX_ROWS = 40

#: Who stands in a care area and may observe or check a station.
_CLINICAL = ("beds", "emergency", "nicu", "icu", "ward", "inpatient", "theatres",
             "visits", "labs", "imaging", "dentistry", "vaccinations",
             "observations")


class HandHygieneError(ValueError):
    """A refusal with a key the screen can name (``hh.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(value, need=False):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        if need:
            raise HandHygieneError("need_date")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HandHygieneError("bad_date") from None


def _text(value, limit):
    return (str(value or "")).strip()[:limit] or None


def may_observe(user):
    return bool(user is not None and (
        user.is_admin or any(user.can_access(m) for m in _CLINICAL)
        or user.can_access("reports")))


def may_manage(user):
    """The month's actions, the training record and the target — the
    infection-control lead, who reads the reports."""
    return bool(user is not None and (user.is_admin or user.can_access("reports")))


def _place(form, need=True):
    """``(unit_id, area)`` — a care unit, or the area as written."""
    from app.models.place import Unit

    raw = str(form.get("unit_id") or "").strip()
    if raw.isdigit():
        unit = db.session.get(Unit, int(raw))
        if unit is None:
            raise HandHygieneError("need_area")
        return unit.id, None
    area = _text(form.get("area"), 120)
    if need and not area:
        raise HandHygieneError("need_area")
    return None, area


def _list(form, key):
    if hasattr(form, "getlist"):
        return form.getlist(key)
    value = form.get(key)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ============================================================ observation ==
def observe(user, form):
    """One observation session with its opportunities. The caller commits.

    The form's rows are ``op-<i>-category``, ``op-<i>-m`` (one per moment
    ticked), ``op-<i>-action`` and ``op-<i>-gloves``. A row left blank is
    skipped; a row half filled is refused rather than guessed at."""
    unit_id, area = _place(form)
    on = _day(form.get("observed_on"), need=True)
    if on > _today():
        raise HandHygieneError("future")
    rows = []
    for i in range(MAX_ROWS):
        category = (form.get(f"op-{i}-category") or "").strip()
        moments = sorted({m for m in _list(form, f"op-{i}-m")
                          if str(m).isdigit() and int(m) in MOMENTS})
        action = (form.get(f"op-{i}-action") or "").strip()
        if not (category or moments or action):
            continue
        if category not in CATEGORIES or not moments or action not in ACTIONS:
            raise HandHygieneError("half_row")
        rows.append(HandHygieneOpportunity(
            category=category, moments="".join(str(m) for m in moments),
            action=action, gloves=bool(form.get(f"op-{i}-gloves"))))
    if not rows:
        raise HandHygieneError("no_rows")
    session = HandHygieneSession(unit_id=unit_id, area=area, observed_on=on,
                                 observer_id=user.id,
                                 note=_text(form.get("note"), 2000))
    session.opportunities = rows
    db.session.add(session)
    db.session.flush()
    return session


def _rate(done, total):
    return round(100.0 * done / total, 1) if total else None


def _opportunities(start, end):
    return (db.session.query(HandHygieneOpportunity, HandHygieneSession)
            .join(HandHygieneSession,
                  HandHygieneOpportunity.session_id == HandHygieneSession.id)
            .filter(HandHygieneSession.observed_on >= start,
                    HandHygieneSession.observed_on <= end)
            .all())


def compliance(start, end, lang="ar"):
    """The period's rate — overall, by area, by staff category and by
    moment. A moment's row counts every opportunity that answered it, so
    an opportunity for moments 1 and 4 is in both."""
    pairs = _opportunities(start, end)
    total = len(pairs)
    done = sum(1 for o, _s in pairs if o.done)

    areas = {}
    for o, s in pairs:
        row = areas.setdefault(s.area_key, {"name": s.area_name(lang), "n": 0, "done": 0})
        row["n"] += 1
        row["done"] += o.done
    by_area = sorted(({**r, "rate": _rate(r["done"], r["n"])} for r in areas.values()),
                     key=lambda r: (r["rate"] if r["rate"] is not None else 101, r["name"]))

    def tally(keys, pick):
        out = []
        for key in keys:
            hits = [o for o, _s in pairs if pick(o, key)]
            n = len(hits)
            got = sum(1 for o in hits if o.done)
            out.append({"key": key, "n": n, "done": got, "rate": _rate(got, n)})
        return out

    return {
        "n": total, "done": done, "rate": _rate(done, total),
        "rub": sum(1 for o, _s in pairs if o.action == "rub"),
        "wash": sum(1 for o, _s in pairs if o.action == "wash"),
        "gloves_missed": sum(1 for o, _s in pairs if o.gloves and not o.done),
        "sessions": len({s.id for _o, s in pairs}),
        "by_area": by_area,
        "by_category": tally(CATEGORIES, lambda o, k: o.category == k),
        "by_moment": tally(MOMENTS, lambda o, k: str(k) in o.moments),
    }


def _month_start(day):
    return day.replace(day=1)


def _shift(month, by):
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


def trend(months=12, today=None):
    """The hospital's rate month by month, oldest first."""
    today = today or _today()
    last = _month_start(today)
    first = _shift(last, -(months - 1))
    rows = {_shift(first, i): {"n": 0, "done": 0} for i in range(months)}
    for o, s in _opportunities(first, today):
        row = rows[_month_start(s.observed_on)]
        row["n"] += 1
        row["done"] += o.done
    return [{"month": m, "n": r["n"], "rate": _rate(r["done"], r["n"])}
            for m, r in sorted(rows.items())]


def target():
    from app.models import Setting

    raw = str(Setting.get(TARGET_SETTING, "") or "").strip()
    return int(raw) if raw.isdigit() and 0 < int(raw) <= 100 else None


def set_target(raw):
    from app.models import Setting

    raw = str(raw or "").strip()
    if raw and not (raw.isdigit() and 0 < int(raw) <= 100):
        raise HandHygieneError("bad_target")
    Setting.set(TARGET_SETTING, raw)


# ============================================================= facilities ==
def check_facilities(user, form):
    unit_id, area = _place(form)
    on = _day(form.get("checked_on"), need=True)
    if on > _today():
        raise HandHygieneError("future")
    row = HandHygieneFacilityCheck(unit_id=unit_id, area=area, checked_on=on,
                                   checked_by=user.id,
                                   action=_text(form.get("action"), 2000))
    for item in FACILITY_ITEMS:
        setattr(row, item, bool(form.get(item)))
    if row.missing and not row.action:
        raise HandHygieneError("need_fix")
    db.session.add(row)
    db.session.flush()
    return row


def latest_facilities(lang="ar"):
    """The newest check of every area, those missing something first."""
    newest = {}
    for row in (HandHygieneFacilityCheck.query
                .order_by(HandHygieneFacilityCheck.checked_on.desc(),
                          HandHygieneFacilityCheck.id.desc())):
        newest.setdefault(row.area_key, row)
    return sorted(newest.values(), key=lambda r: (not r.missing, r.area_name(lang)))


# ================================================================ actions ==
def add_action(user, form):
    raw = (form.get("month") or "").strip()
    try:
        month = datetime.strptime(raw, "%Y-%m").date()
    except ValueError:
        raise HandHygieneError("need_month") from None
    if month > _month_start(_today()):
        raise HandHygieneError("future")
    unit_id, area = _place(form, need=False)
    finding = _text(form.get("finding"), 4000)
    action = _text(form.get("action"), 4000)
    if not finding or not action:
        raise HandHygieneError("need_finding")
    row = HandHygieneAction(month=month, unit_id=unit_id, area=area,
                            finding=finding, action=action, recorded_by=user.id)
    db.session.add(row)
    db.session.flush()
    return row


def actions(start, end):
    return (HandHygieneAction.query
            .filter(HandHygieneAction.month >= _month_start(start),
                    HandHygieneAction.month <= end)
            .order_by(HandHygieneAction.month.desc(), HandHygieneAction.id.desc())
            .all())


# =============================================================== training ==
def train(user_id, trained_on, trainer=None, valid_until=None, by=None):
    from app.models import User

    person = db.session.get(User, int(user_id)) if str(user_id or "").isdigit() else None
    if person is None:
        raise HandHygieneError("no_person")
    on = _day(trained_on, need=True)
    if on > _today():
        raise HandHygieneError("future")
    until = _day(valid_until)
    if until is not None and until <= on:
        raise HandHygieneError("until_before")
    row = HandHygieneTraining(user_id=person.id, trained_on=on,
                              trainer=_text(trainer, 160), valid_until=until,
                              recorded_by=getattr(by, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def training_board(today=None):
    """Every active member of staff with their newest training — those
    never trained or out of date first."""
    from app.models import User

    today = today or _today()
    newest = {}
    for row in HandHygieneTraining.query.order_by(HandHygieneTraining.trained_on.desc(),
                                                  HandHygieneTraining.id.desc()):
        newest.setdefault(row.user_id, row)
    rows = []
    for person in (User.query.filter(User.is_active.is_(True))
                   .order_by(User.full_name).all()):
        last = newest.get(person.id)
        if last is None:
            state = "never"
        elif last.valid_until is not None and last.valid_until < today:
            state = "lapsed"
        else:
            state = "ok"
        rows.append({"user": person, "last": last, "state": state})
    order = {"never": 0, "lapsed": 1, "ok": 2}
    rows.sort(key=lambda r: (order[r["state"]], r["user"].full_name or ""))
    return rows
