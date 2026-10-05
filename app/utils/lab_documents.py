"""The laboratory's documents about its own tests — GAHAR DAS.16, DAS.17,
DAS.14 and DAS.10.

* **DAS.17** — each test's written procedure: which version is in force,
  where it is, who approved it, when it is due its review.
* **DAS.16** — each method's verification or validation: the outcome
  against the laboratory's own criteria, who signed it, when it is due again.
* **DAS.14 evidence 2** — *a laboratory service manual distributed to all
  users*: every test the laboratory offers, with its specimen, tube,
  preparation and time, printed from the catalogue the laboratory already
  keeps, so the manual and the bench can never disagree.
* **DAS.10 evidence 3–4** — the scope of service is that same list, and
  *periodically reviewed*: who reviewed it, and when.

The documents themselves are the laboratory's; the program never writes a
procedure or decides a verification passed. It keeps the dates — because an
out-of-date procedure, a method never verified, a manual nobody reviewed are
the findings, and only a date can show them.
"""
from datetime import date

from app.extensions import db

SCOPE_SETTING = "lab_scope_reviewed"


class DocumentError(ValueError):
    """A refusal with a key the screen can name (``lab_docs.err_<key>``)."""


def may_write(user):
    """Whoever builds the lists, or whoever releases results — the head of
    the laboratory is usually the second, not the first."""
    return bool(user is not None and (user.is_admin or user.can("lab_release")))


def _day(value):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise DocumentError("bad_date") from None


# ----------------------------------------------------------- procedures --
def procedures_for(test_id):
    from app.models import LabProcedure

    return (LabProcedure.query.filter_by(investigation_id=test_id)
            .order_by(LabProcedure.effective_on.desc(),
                      LabProcedure.id.desc()).all())


def current_procedure(test_id):
    rows = procedures_for(test_id)
    return rows[0] if rows else None


def add_procedure(test, version, location, effective_on, review_due=None,
                  code=None, approved_by=None, user=None):
    from app.models import LabProcedure

    if test is None or test.kind != "lab":
        raise DocumentError("not_lab")
    version = (version or "").strip()[:20]
    location = (location or "").strip()[:255]
    if not version:
        raise DocumentError("need_version")
    if not location:
        raise DocumentError("need_location")
    effective = _day(effective_on)
    if effective is None:
        raise DocumentError("need_effective")
    review = _day(review_due)
    if review is not None and review < effective:
        raise DocumentError("review_before_effective")
    row = LabProcedure(investigation_id=test.id, version=version,
                       location=location, effective_on=effective,
                       review_due=review,
                       code=(code or "").strip()[:40] or None,
                       approved_by=(approved_by or "").strip()[:120] or None,
                       written_by=getattr(user, "id", None))
    db.session.add(row)
    return row


# --------------------------------------------------------- method checks --
def checks_for(test_id):
    from app.models import MethodCheck

    return (MethodCheck.query.filter_by(investigation_id=test_id)
            .order_by(MethodCheck.done_on.desc(), MethodCheck.id.desc()).all())


def latest_check(test_id):
    rows = checks_for(test_id)
    return rows[0] if rows else None


def add_check(test, kind, done_on, summary, accepted, signed_by,
              due_again=None, user=None):
    from app.models import METHOD_CHECK_KINDS, MethodCheck

    if test is None or test.kind != "lab":
        raise DocumentError("not_lab")
    if kind not in METHOD_CHECK_KINDS:
        raise DocumentError("kind")
    done = _day(done_on)
    if done is None:
        raise DocumentError("need_done_on")
    summary = (summary or "").strip()[:400]
    if not summary:
        raise DocumentError("need_summary")
    signed_by = (signed_by or "").strip()[:120]
    if not signed_by:
        raise DocumentError("need_signed")
    if accepted not in (True, False):
        raise DocumentError("need_verdict")
    again = _day(due_again)
    if again is not None and again <= done:
        raise DocumentError("due_before_done")
    row = MethodCheck(investigation_id=test.id, kind=kind, done_on=done,
                      summary=summary, accepted=accepted, signed_by=signed_by,
                      due_again=again, written_by=getattr(user, "id", None))
    db.session.add(row)
    return row


# ------------------------------------------------------------- the state --
def procedure_state(row, today):
    if row is None:
        return "none"
    if row.review_due is not None and row.review_due < today:
        return "overdue"
    return "ok"


def check_state(row, today):
    if row is None:
        return "none"
    if not row.accepted:
        return "failed"
    if row.due_again is not None and row.due_again < today:
        return "overdue"
    return "ok"


def overview(today=None):
    """Every active lab test with where its procedure and its verification
    stand — the ones that need something first."""
    from app.models import Investigation, LabProcedure, MethodCheck
    from app.utils.clock import local_today

    today = today or local_today()
    tests = (Investigation.query
             .filter(Investigation.kind == "lab",
                     Investigation.is_active.is_(True))
             .order_by(Investigation.category, Investigation.name_ar).all())
    newest_proc, newest_check = {}, {}
    for row in (LabProcedure.query
                .order_by(LabProcedure.effective_on, LabProcedure.id).all()):
        newest_proc[row.investigation_id] = row
    for row in MethodCheck.query.order_by(MethodCheck.done_on,
                                          MethodCheck.id).all():
        newest_check[row.investigation_id] = row
    rows = []
    for test in tests:
        proc = newest_proc.get(test.id)
        check = newest_check.get(test.id)
        rows.append({"test": test, "procedure": proc, "check": check,
                     "p_state": procedure_state(proc, today),
                     "c_state": check_state(check, today)})
    rows.sort(key=lambda r: (r["p_state"] == "ok" and r["c_state"] == "ok",
                             r["test"].category or "", r["test"].name_ar))
    return rows


def attention(today=None):
    return sum(1 for r in overview(today)
               if r["p_state"] != "ok" or r["c_state"] != "ok")


# ---------------------------------------------- the manual and its scope --
def manual_rows():
    """The service manual: every test the laboratory offers, by category."""
    from app.models import Investigation

    return (Investigation.query
            .filter(Investigation.kind == "lab",
                    Investigation.is_active.is_(True))
            .order_by(Investigation.category, Investigation.name_ar).all())


def scope_reviewed():
    """``(day, name)`` of the last scope review, or ``(None, None)``."""
    from app.models import Setting

    raw = (Setting.get(SCOPE_SETTING) or "").strip()
    if "|" not in raw:
        return None, None
    day, _, name = raw.partition("|")
    try:
        return date.fromisoformat(day), name or None
    except ValueError:
        return None, None


def mark_scope_reviewed(user, today=None):
    from app.models import Setting
    from app.utils.clock import local_today

    day = today or local_today()
    name = user.display_name("ar") if user is not None else ""
    Setting.set(SCOPE_SETTING, f"{day.isoformat()}|{name}")
    return day

