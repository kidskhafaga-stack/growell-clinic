"""Growth charts module (Phase 5).

Interactive WHO/CDC percentile charts with LMS-based percentile/Z-score for
weight, height, head circumference and BMI — plotting the patient's growth
records (auto-captured from visits, or added manually here).
"""
from datetime import datetime

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from app.blueprints.growth import growth_bp
from app.extensions import db
from app.i18n import t
from app.models import ActivityLog, GrowthRecord, Patient
from app.utils.decorators import client_ip, module_required
from app.utils import rcpch
from app.utils.growth import (
    INDICATORS,
    age_in_months,
    compute_at_age,
    compute_point,
    reference_curves,
    reference_range,
    references,
    status_for_z,
)

MODULE = "growth"

# Accept both our chart indicator keys and plain measurement names at the API.
_MEASUREMENT_ALIASES = {
    "weight": "wfa", "wfa": "wfa",
    "height": "hfa", "length": "hfa", "hfa": "hfa",
    "head": "hcfa", "ofc": "hcfa", "hc": "hcfa", "hcfa": "hcfa",
    "bmi": "bmifa", "bmifa": "bmifa",
}


def _all_references():
    """WHO/CDC (LMS) plus RCPCH (offline package) when it is installed."""
    return references() + rcpch.sources()


def _default_reference(patient):
    """WHO for under-5s, CDC for older children (both remain switchable)."""
    parts = patient.age_parts
    return "WHO" if parts[0] < 5 else "CDC"


def _records(patient):
    return (
        GrowthRecord.query.filter_by(patient_id=patient.id)
        .order_by(GrowthRecord.record_date)
        .all()
    )


@growth_bp.route("/")
@module_required(MODULE)
def index():
    # Patients that have at least one growth record.
    sub = db.session.query(GrowthRecord.patient_id).distinct().subquery()
    pagination = (
        Patient.query.filter(Patient.id.in_(db.session.query(sub.c.patient_id)))
        .order_by(Patient.full_name)
        .paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    )
    return render_template(
        "growth/index.html", patients=pagination.items, pagination=pagination
    )


@growth_bp.route("/<int:patient_id>")
@module_required(MODULE)
def view(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    records = _records(patient)
    return render_template(
        "growth/chart.html",
        patient=patient,
        references=_all_references(),
        indicators=list(INDICATORS.keys()),
        default_ref=_default_reference(patient),
        has_records=bool(records),
        records=records,
        today=datetime.utcnow().date().isoformat(),
    )


@growth_bp.route("/<int:patient_id>/data")
@module_required(MODULE)
def data(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    ref = request.args.get("ref", "WHO")
    indicator = request.args.get("indicator", "wfa")
    if indicator not in INDICATORS:
        indicator = "wfa"

    field = INDICATORS[indicator]["field"]
    is_rcpch = rcpch.is_rcpch(ref)
    if is_rcpch:
        curves = rcpch.reference_curves(ref, indicator, patient.gender)
        rng = rcpch.reference_range(ref)
    else:
        curves = reference_curves(ref, indicator, patient.gender)
        rng = reference_range(ref)

    points = []
    for rec in _records(patient):
        value = getattr(rec, field, None)
        # Don't plot/score measurements outside the reference's valid ages.
        months = age_in_months(patient.date_of_birth, rec.record_date)
        if months is None or (rng and (months < rng[0] - 0.5 or months > rng[1] + 0.5)):
            continue
        if is_rcpch:
            pt = rcpch.compute_point(ref, indicator, patient.gender, months, value)
        else:
            pt = compute_point(ref, indicator, patient.gender, patient.date_of_birth,
                               rec.record_date, value)
        if pt:
            pt["date"] = rec.record_date.isoformat()
            pt["status"] = status_for_z(pt["z"])
            points.append(pt)

    return jsonify({
        "curves": curves, "points": points,
        "unit": INDICATORS[indicator]["unit"], "gender": patient.gender,
    })


@growth_bp.route("/api/calculate", methods=["POST"])
@module_required(MODULE)
def api_calculate():
    """Stateless Z-score / percentile calculator (all offline).

    POST JSON: ``{gender, age_months, measurement_type, value, source}``
    where ``source`` is ``WHO`` / ``CDC`` / ``RCPCH``. Routes WHO & CDC to the
    bundled LMS engine and RCPCH to the ``rcpchgrowth`` package — no data leaves
    the server. Returns ``{ok, z, percentile, status, source}``.
    """
    data = request.get_json(silent=True) or {}
    gender = "female" if data.get("gender") == "female" else "male"
    source = (data.get("source") or "WHO").strip()
    indicator = _MEASUREMENT_ALIASES.get(
        (data.get("measurement_type") or "weight").strip().lower()
    )
    if not indicator:
        return jsonify({"ok": False, "error": "bad_measurement_type"}), 400
    try:
        age_months = float(data.get("age_months"))
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_numeric_input"}), 400

    if rcpch.is_rcpch(source):
        pt = rcpch.compute_point(source, indicator, gender, age_months, value)
    else:
        pt = compute_at_age(source, indicator, gender, age_months, value)

    if not pt or pt.get("z") is None:
        return jsonify({"ok": False, "error": "out_of_range", "source": source}), 200
    return jsonify({
        "ok": True, "source": source, "measurement_type": indicator,
        "z": pt["z"], "percentile": pt["percentile"],
        "status": status_for_z(pt["z"]),
    })


@growth_bp.route("/<int:patient_id>/add", methods=["POST"])
@module_required(MODULE)
def add(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    raw_date = (request.form.get("record_date") or "").strip()
    try:
        record_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        flash(t("growth.invalid_date"), "danger")
        return redirect(url_for("growth.view", patient_id=patient.id))

    def fnum(name):
        raw = (request.form.get(name) or "").strip()
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    weight = fnum("weight_kg")
    height = fnum("height_cm")
    head = fnum("head_circ_cm")
    if not any([weight, height, head]):
        flash(t("growth.need_value"), "warning")
        return redirect(url_for("growth.view", patient_id=patient.id))

    bmi = None
    if weight and height:
        m = height / 100.0
        bmi = round(weight / (m * m), 1) if m > 0 else None

    db.session.add(GrowthRecord(
        patient_id=patient.id, record_date=record_date, source="manual",
        weight_kg=weight, height_cm=height, head_circ_cm=head, bmi=bmi,
    ))
    ActivityLog.record(
        "growth.add", user_id=current_user.id, entity="patient",
        entity_id=patient.id, ip_address=client_ip(),
    )
    db.session.commit()
    flash(t("growth.added"), "success")
    return redirect(url_for("growth.view", patient_id=patient.id))
