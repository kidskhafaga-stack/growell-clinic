"""Auto-validation — the laboratory's rules say which results are ready to
release, and a person releases them (LAB_GLAB360_PLAN.md م-١).

**Off until the laboratory opens it, test by test** (:data:`SETTING` — the
tests it chose; empty = off). For a chosen test, a result *passes* only when
every one of these holds together:

* every analyte has a **number**, judged against a range the lab director
  **approved** for this child's age and sex, and it is **inside** it — a
  draft range never passes anything;
* **no critical value** and **no delta flag**;
* **today's quality control passed** for each analyte: at least one control
  run today, and none of today's runs rejected — no control today, no pass;
* the sample was **not rejected** since it was drawn, and nobody wrote a note
  on it at reception (haemolysed, clotted…).

**A person still releases.** The owner's rule is that the program suggests
and a person confirms: the list of results waiting for release says, beside
each one, «passes the rules» or **why not**, and «release everything that
passed» is one press by somebody the hospital authorized (``lab_release``) —
recorded as released by that person, *by the rules*. A result that does not
pass waits exactly as before, with its reasons written beside it.

No number here is the program's: the ranges, the critical limits, the delta
limits and the control rules are all the laboratory's own.
"""
import json
from datetime import datetime, timedelta

from app.extensions import db

SETTING = "lab_autoverify_tests"
#: Why a result does not pass — ``lab_auto.why_<key>``.
REASONS = ("not_chosen", "not_measured", "no_value", "no_range", "outside",
           "critical", "delta", "no_qc_today", "qc_failed", "rejected", "sample_note")


def chosen():
    """The investigation ids the laboratory opened to auto-validation."""
    from app.models import Setting

    try:
        ids = json.loads(Setting.get(SETTING) or "[]")
    except ValueError:
        return set()
    return {int(i) for i in ids if str(i).isdigit()}


def choose(ids):
    """Write the laboratory's choice. The caller commits."""
    from app.models import Setting

    clean = sorted({int(i) for i in ids if str(i).strip().isdigit()})
    Setting.set(SETTING, json.dumps(clean))
    return clean


def on():
    return bool(chosen())


def _qc_today(analyte_ids, now=None):
    """``{analyte_id: "ok" | "none" | "failed"}`` for today's control runs,
    by the clinic's own calendar day."""
    from app.models.lab_quality import QcMaterial, QcRun
    from app.utils.clock import local_today, to_utc

    today = local_today()
    start = to_utc(datetime.combine(today, datetime.min.time()))
    end = start + timedelta(days=1)
    out = {a: "none" for a in analyte_ids}
    if not analyte_ids:
        return out
    runs = (db.session.query(QcRun, QcMaterial.analyte_id)
            .join(QcMaterial, QcRun.material_id == QcMaterial.id)
            .filter(QcMaterial.analyte_id.in_(list(analyte_ids)),
                    QcRun.run_at >= start, QcRun.run_at < end).all())
    for run, analyte_id in runs:
        if not run.accepted:
            out[analyte_id] = "failed"
        elif out.get(analyte_id) != "failed":
            out[analyte_id] = "ok"
    return out


def _rejected_since_drawn(order):
    from app.models.lab_reference import SampleRejection

    q = SampleRejection.query.filter(SampleRejection.order_id == order.id)
    if order.collected_at is not None:
        q = q.filter(SampleRejection.rejected_at >= order.collected_at)
    return q.first() is not None


def check(order, chosen_ids=None, qc=None):
    """``[]`` when ``order`` passes the rules, else the reasons it does not
    (keys of :data:`REASONS`, each once, in that order)."""
    chosen_ids = chosen() if chosen_ids is None else chosen_ids
    if order.investigation_id not in chosen_ids:
        return ["not_chosen"]
    values = list(order.analyte_values or [])
    if not values:
        return ["not_measured"]
    why = []
    ids = {v.analyte_id for v in values}
    qc = qc if qc is not None else _qc_today(ids)
    for v in values:
        if v.value is None:
            why.append("no_value")
        elif not v.range_approved:
            why.append("no_range")
        elif v.flag in ("critical_low", "critical_high"):
            why.append("critical")
        elif v.flag != "normal":
            why.append("outside")
        if v.delta_hit:
            why.append("delta")
        state = qc.get(v.analyte_id, "none")
        if state == "none":
            why.append("no_qc_today")
        elif state == "failed":
            why.append("qc_failed")
    if order.critical_at is not None:
        why.append("critical")
    if _rejected_since_drawn(order):
        why.append("rejected")
    if (order.received_note or "").strip():
        why.append("sample_note")
    return [r for r in REASONS if r in set(why)]


def sort_out(orders):
    """``{order_id: [reasons]}`` for a list — one QC read for all of it."""
    chosen_ids = chosen()
    if not chosen_ids:
        return {}
    ids = {v.analyte_id for o in orders for v in (o.analyte_values or [])}
    qc = _qc_today(ids)
    return {o.id: check(o, chosen_ids, qc) for o in orders}


def release_passing(user, now=None):
    """Release every waiting result that passes, in ``user``'s name — the
    one press. Returns the orders released. The caller commits."""
    from app.utils import lab_release

    if not lab_release.may_release(user):
        raise lab_release.ReleaseError("not_allowed")
    waiting = lab_release.waiting()
    verdicts = sort_out(waiting)
    done = []
    for order in waiting:
        if verdicts.get(order.id) == []:
            lab_release.verify(order, user, at=now)
            order.verified_by_rules = True
            done.append(order)
    db.session.flush()
    return done


def lab_tests():
    """The tests the laboratory answers analyte by analyte — the ones a rule
    can read."""
    from app.models import Investigation

    rows = Investigation.query.filter(Investigation.is_active.is_(True)).all()
    return sorted([r for r in rows if getattr(r, "analyte_links", None)],
                  key=lambda r: (r.name_ar or r.name_en or ""))
