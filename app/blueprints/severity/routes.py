"""Severity scores on entering intensive care (HOSPITAL_PLAN.md ت-٦ب) — see
``utils/severity.py`` for what the engine does and what it refuses."""
from datetime import datetime
from functools import wraps

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.severity import severity_bp
from app.extensions import db
from app.i18n import t
from app.utils import severity as sev


def _may_manage(user):
    return user.role == "admin" or user.can("severity_scores")


def _door(check):
    """Who may, before whether it is on: refused first, then a copy without
    the ICU or NICU module has no such page."""
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from flask import current_app

            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not check(current_user):
                abort(403, description=t("auth.no_permission"))
            if not sev.module_on():
                abort(404)
            return view(*args, **kwargs)
        return wrapped
    return deco


_manage = _door(_may_manage)
_read = _door(lambda u: u.can_open("reports") or _may_manage(u))
_clinical = _door(lambda u: u.can("patient_medical"))


def _lang():
    return getattr(g, "lang", "ar")


def _score(score_id):
    from app.models import SeverityScore

    return db.get_or_404(SeverityScore, score_id)


# ------------------------------------------------------------ the scores --
@severity_bp.route("/")
@_manage
def index():
    from app.models import SeverityScore

    scores = SeverityScore.query.order_by(SeverityScore.key, SeverityScore.version.desc()).all()
    units = [{"kind": k, "now": sev.choice(k), "history": sev.history(k)} for k in sev.units_on()]
    return render_template("severity/index.html", scores=scores, units=units,
                           active=[s for s in scores if s.status == "active"],
                           kinds=("equation", "points"))


@severity_bp.route("/new", methods=["POST"])
@_manage
def new():
    import re

    from app.models import ActivityLog, SeverityScore

    key = (request.form.get("key") or "").strip().lower()
    name = (request.form.get("name_ar") or "").strip()
    kind = request.form.get("kind")
    if not re.match(r"^[a-z][a-z0-9_]{1,39}$", key) or not name or kind not in ("equation", "points"):
        flash(t("severity.err_new"), "warning")
        return redirect(url_for("severity.index"))
    if SeverityScore.query.filter_by(key=key).first():
        flash(t("severity.err_key_taken"), "warning")
        return redirect(url_for("severity.index"))
    row = SeverityScore(key=key, version=1, name_ar=name[:120],
                        name_en=(request.form.get("name_en") or "").strip()[:120] or None,
                        kind=kind, inputs=[], examples=[], created_by=current_user.id)
    db.session.add(row)
    db.session.flush()
    ActivityLog.record("severity.new", user_id=current_user.id, entity="severity_score",
                       entity_id=row.id, detail=key)
    db.session.commit()
    return redirect(url_for("severity.score", score_id=row.id))


def _float(name):
    raw = (request.form.get(name) or "").strip()
    return sev._num(raw) if raw else None


@severity_bp.route("/<int:score_id>", methods=["GET", "POST"])
@_manage
def score(score_id):
    """A draft is written here and tested on every save; an approved version
    is read only — a change is a new version."""
    from app.models import ActivityLog

    row = _score(score_id)
    inputs_raw = sev.inputs_text(row.inputs, row.kind)
    examples_raw = sev.examples_text(row.examples)
    problems = {}
    if request.method == "POST":
        if row.status != "draft":
            abort(409)
        inputs_raw = request.form.get("inputs") or ""
        examples_raw = request.form.get("examples") or ""
        inputs, bad_in = sev.parse_inputs(inputs_raw, row.kind)
        examples, bad_ex = sev.parse_examples(examples_raw)
        try:
            numbers = {k: _float(k) for k in ("window_before_h", "window_after_h",
                                              "intercept", "slope", "tolerance")}
        except ValueError:
            numbers, problems["numbers"] = None, True
        if bad_in:
            problems["inputs"] = bad_in
        if bad_ex:
            problems["examples"] = bad_ex
        if not problems:
            row.name_ar = (request.form.get("name_ar") or row.name_ar).strip()[:120]
            row.name_en = (request.form.get("name_en") or "").strip()[:120] or None
            row.source = (request.form.get("source") or "").strip()[:4000] or None
            row.licence_holder = (request.form.get("licence_holder") or "").strip()[:200] or None
            row.licence_ref = (request.form.get("licence_ref") or "").strip()[:200] or None
            row.window_before_h = numbers["window_before_h"]
            row.window_after_h = numbers["window_after_h"]
            row.intercept = numbers["intercept"]
            row.slope = numbers["slope"] if row.kind == "points" else None
            if numbers["tolerance"] is not None and numbers["tolerance"] > 0:
                row.tolerance = numbers["tolerance"]
            row.inputs, row.examples = inputs, examples
            sev.test(row)
            ActivityLog.record("severity.edit", user_id=current_user.id, entity="severity_score",
                               entity_id=row.id, detail=f"{row.key} v{row.version}")
            db.session.commit()
            flash(t("severity.saved_ok") if row.test_ok else t("severity.saved_not_yet"),
                  "success" if row.test_ok else "warning")
            return redirect(url_for("severity.score", score_id=row.id))
        flash(t("severity.err_lines"), "warning")
    return render_template("severity/score.html", row=row, inputs_raw=inputs_raw,
                           examples_raw=examples_raw, problems=problems,
                           blockers=sev.blockers(row) if row.status == "draft" else [],
                           transforms=list(sev.TRANSFORMS), min_examples=sev.MIN_EXAMPLES)


@severity_bp.route("/<int:score_id>/activate", methods=["POST"])
@_manage
def activate(score_id):
    row = _score(score_id)
    missing = sev.activate(row, current_user, request.form.get("note"))
    if missing:
        db.session.rollback()
        flash(t("severity.err_blocked"), "warning")
    else:
        db.session.commit()
        flash(t("severity.activated"), "success")
    return redirect(url_for("severity.score", score_id=row.id))


@severity_bp.route("/<int:score_id>/version", methods=["POST"])
@_manage
def version(score_id):
    copy = sev.new_version(_score(score_id), current_user)
    db.session.commit()
    flash(t("severity.new_version"), "success")
    return redirect(url_for("severity.score", score_id=copy.id))


@severity_bp.route("/unit/<kind>", methods=["POST"])
@_manage
def unit(kind):
    from app.models import SeverityScore

    if kind not in sev.units_on():
        abort(404)
    score_id = request.form.get("score_id", type=int)
    row = db.session.get(SeverityScore, score_id) if score_id else None
    try:
        since = datetime.strptime(request.form.get("since") or "", "%Y-%m-%d").date()
    except ValueError:
        flash(t("severity.err_since"), "warning")
        return redirect(url_for("severity.index"))
    problem = sev.choose(kind, row, since, current_user, request.form.get("note"))
    if problem:
        db.session.rollback()
        flash(t("severity.err_" + problem), "warning")
    else:
        db.session.commit()
        flash(t("severity.unit_set"), "success")
    return redirect(url_for("severity.index"))


# ------------------------------------------------------------- a child --
@severity_bp.route("/admission/<int:admission_id>/<kind>", methods=["GET", "POST"])
@_clinical
def admission(admission_id, kind):
    from app.models import Admission, SeverityRecord
    from app.utils.clock import local_date, to_local, to_utc

    if kind not in sev.units_on():
        abort(404)
    stay = db.get_or_404(Admission, admission_id)
    came = sev.entered(stay, kind)
    if came is None:
        abort(404)
    done = SeverityRecord.query.filter_by(admission_id=stay.id, unit_kind=kind).first()
    score = done.score if done else sev.choice(kind, on=local_date(came))
    if request.method == "POST" and not done:
        values = {}
        try:
            for r in (score.inputs if score else []):
                if r["type"] == "ratio":
                    top = sev._num(request.form.get(f"v_{r['code']}_top"))
                    bottom = sev._num(request.form.get(f"v_{r['code']}_bottom"))
                    if top is not None and bottom is not None:
                        values[r["code"]] = [top, bottom]
                elif r["type"] == "yesno":
                    raw = request.form.get(f"v_{r['code']}")
                    if raw in ("0", "1"):
                        values[r["code"]] = float(raw)
                else:
                    v = sev._num(request.form.get(f"v_{r['code']}"))
                    if v is not None:
                        values[r["code"]] = v
            moment = datetime.strptime(request.form.get("measured_at") or "", "%Y-%m-%dT%H:%M")
        except ValueError:
            flash(t("severity.err_number"), "warning")
            return redirect(url_for("severity.admission", admission_id=stay.id, kind=kind))
        row, problem = sev.record(stay, kind, to_utc(moment).replace(tzinfo=None), values, current_user)
        if problem:
            db.session.rollback()
            flash(t("severity.err_" + problem), "warning")
        else:
            db.session.commit()
            flash(t("severity.recorded"), "success")
        return redirect(url_for("severity.admission", admission_id=stay.id, kind=kind))
    start, end = sev.window(score, came) if score else (None, None)
    return render_template("severity/record.html", stay=stay, kind=kind, came=to_local(came),
                           score=score, done=done, start=to_local(start) if start else None,
                           end=to_local(end) if end else None,
                           now=to_local(datetime.utcnow()))


# ------------------------------------------------------------- the unit --
@severity_bp.route("/board")
@_read
def board():
    units = sev.units_on()
    kind = request.args.get("unit")
    kind = kind if kind in units else (units[0] if units else None)
    if kind is None:
        abort(404)
    return render_template("severity/board.html", units=units, kind=kind,
                           data=sev.board(kind), now=sev.choice(kind),
                           may_manage=_may_manage(current_user))
