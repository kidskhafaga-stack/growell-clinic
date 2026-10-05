"""Who in the laboratory is competent for what — GAHAR DAS.11.

The three items of evidence, and what the program can hold of each:

1. *an approved policy covering (أ)–(هـ)* — the policy is the hospital's;
   every assessment names which of the five ways it used (direct observation
   of the routine work, of equipment checks, review of work records,
   problem solving, specially provided samples), so the file shows the
   policy being followed;
2. *performed annually and recorded in the staff file* — one row per
   assessment, per person and per section, kept for ever; the person's page
   is the file, and whoever is past the date the assessor set is listed;
3. *work scheduled and processed based upon the competencies assessed* — a
   report of results written or released by somebody with no standing
   assessment for that section on that day; and, when the laboratory
   switches it on (:data:`CHECK_SETTING`), a word to the person entering a
   result outside their competency.

**A word, never a wall.** A potassium at three in the morning is entered by
whoever is there; the program says it and the report counts it. Holding a
result back for paperwork is the one thing a laboratory must not do.

The verdict is always the assessor's. The program never decides somebody is
competent; it reads what was written and the date it was written for.
"""
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models.lab_quality import (COMPETENCY_METHODS, COMPETENCY_RESULTS,
                                    LabCompetency)

CHECK_SETTING = "lab_competency_check"


class CompetencyError(ValueError):
    """A refusal with a key the screen can name (``lab_comp.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(value):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise CompetencyError("bad_date") from None


def may_write(user):
    """The laboratory's head assesses: whoever builds the lists, or whoever
    releases results — the same people who write its documents."""
    return bool(user is not None and (user.is_admin or user.can("lab_release")))


def checking():
    from app.models import Setting

    try:
        return Setting.get(CHECK_SETTING) == "1"
    except Exception:                   # noqa: BLE001 — settings not ready
        return False


def set_checking(on):
    from app.models import Setting

    Setting.set(CHECK_SETTING, "1" if on else "0")


# ---------------------------------------------------------- who and where --
def sections():
    """The laboratory's sections as its catalogue names them."""
    from app.models import Investigation

    rows = (db.session.query(Investigation.category)
            .filter(Investigation.kind == "lab",
                    Investigation.category.isnot(None),
                    Investigation.category != "")
            .distinct().all())
    return sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})


def staff():
    """Everybody who can reach the laboratory, and anybody with a file."""
    from app.models import User

    filed = {r[0] for r in db.session.query(LabCompetency.user_id).distinct()}
    people = User.query.filter(User.is_active.is_(True)).order_by(
        User.full_name).all()
    return [u for u in people if u.id in filed or u.can_access("labs")]


# ---------------------------------------------------------------- writing --
def record(user_id, section, assessed_on, methods, result, assessor_id=None,
           due_on=None, note=None, by=None):
    """One assessment, as the assessor wrote it. The caller commits."""
    from app.models import User

    person = db.session.get(User, user_id) if user_id else None
    if person is None:
        raise CompetencyError("no_person")
    on = _day(assessed_on)
    if on is None:
        raise CompetencyError("need_date")
    if on > _today():
        raise CompetencyError("future")
    chosen = [m for m in COMPETENCY_METHODS if m in set(methods or ())]
    if not chosen:
        raise CompetencyError("need_method")
    if result not in COMPETENCY_RESULTS:
        raise CompetencyError("need_result")
    due = _day(due_on)
    if due is not None and due <= on:
        raise CompetencyError("due_before")
    section = (section or "").strip()[:80] or None
    row = LabCompetency(
        user_id=person.id, section=section, assessed_on=on,
        methods=",".join(chosen), result=result,
        assessor_id=assessor_id or getattr(by, "id", None), due_on=due,
        note=(note or "").strip()[:400] or None,
        written_by=getattr(by, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def suggested_due(on=None):
    """A year on — what "annually" means — offered in the form, never kept
    unless the assessor leaves it there."""
    on = on or _today()
    try:
        return on.replace(year=on.year + 1)
    except ValueError:                  # 29 February
        return on + timedelta(days=365)


# ---------------------------------------------------------------- reading --
def file_of(user_id):
    """The person's file, newest first."""
    return (LabCompetency.query.filter_by(user_id=user_id)
            .order_by(LabCompetency.assessed_on.desc(),
                      LabCompetency.id.desc()).all())


def latest(user_id):
    """``{section or None: newest row}`` for one person."""
    out = {}
    for row in file_of(user_id):
        out.setdefault(row.section, row)
    return out


def stands(user_id, section, day=None):
    """Was this person assessed competent for ``section`` on ``day``?

    The newest assessment for the section decides — a later «needs training»
    replaces an earlier «competent». An assessment for the whole laboratory
    counts for every section."""
    if not user_id:
        return False
    day = day or _today()
    newest = {}
    for row in file_of(user_id):
        if row.assessed_on > day:
            continue
        newest.setdefault(row.section, row)
    for key in ((section or "").strip() or None, None):
        row = newest.get(key)
        if row is not None and row.stands_on(day):
            return True
    return False


def state(row, today=None):
    """``ok`` · ``overdue`` · ``training`` · ``not_competent``."""
    today = today or _today()
    if row.result == "needs_training":
        return "training"
    if row.result == "not_competent":
        return "not_competent"
    if row.due_on is not None and row.due_on < today:
        return "overdue"
    return "ok"


def overview(today=None):
    """One line per person: their newest row per section, and its state —
    nobody with no file at all first, then whoever is overdue."""
    today = today or _today()
    lines = []
    for person in staff():
        rows = latest(person.id)
        states = {key: state(row, today) for key, row in rows.items()}
        lines.append({"user": person, "rows": rows, "states": states,
                      "empty": not rows,
                      "attention": (not rows) or any(
                          s != "ok" for s in states.values())})
    lines.sort(key=lambda l: (not l["empty"], not l["attention"],
                              l["user"].full_name or ""))
    return lines


def attention(today=None):
    """How many people the laboratory has to look at — for the bench's
    button. Nothing until the laboratory has written its first assessment:
    a clinic that never keeps these files is not told every day that it
    does not."""
    if LabCompetency.query.first() is None:
        return 0
    return sum(1 for line in overview(today) if line["attention"])


def warning_for(order, user, day=None):
    """The section to name when ``user`` is writing this order's result
    with no standing assessment for it — ``None`` otherwise, and always
    ``None`` until the laboratory switches the check on."""
    if not checking() or order is None or order.kind != "lab":
        return None
    test = getattr(order, "investigation", None)
    section = ((getattr(test, "category", None) or "").strip()) or None
    if stands(getattr(user, "id", None), section, day):
        return None
    return section or ""


def outside(start, end):
    """Evidence 3: results written or released in the period by somebody
    with no standing assessment for the test's section that day.

    ``[{"order", "who", "user", "role" ("resulted" | "released"),
    "section", "day"}]``
    """
    from app.models import VisitInvestigation
    from app.utils.clock import local_date, to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    orders = (VisitInvestigation.query
              .filter(VisitInvestigation.kind == "lab",
                      VisitInvestigation.resulted_at >= since,
                      VisitInvestigation.resulted_at <= until)
              .order_by(VisitInvestigation.resulted_at).all())
    seen = {}
    out = []
    for order in orders:
        test = order.investigation
        section = ((getattr(test, "category", None) or "").strip()) or None
        for role, who, at in (("resulted", order.resulted_by, order.resulted_at),
                              ("released", order.verified_by, order.verified_at)):
            if not who or at is None:
                continue
            day = local_date(at)
            key = (who, section, day)
            if key not in seen:
                seen[key] = stands(who, section, day)
            if not seen[key]:
                out.append({"order": order, "who": who, "role": role,
                            "user": (order.resulter if role == "resulted"
                                     else order.verifier),
                            "section": section, "day": day})
    return out
