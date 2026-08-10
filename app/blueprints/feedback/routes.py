"""Public patient-feedback pages (no login).

A guardian opens ``/f/<token>`` from a WhatsApp link, rates the doctor and the
service, optionally leaves a comment, and submits. Everything is keyed by the
opaque token — the same login-free pattern used by the vaccination-certificate
verify page.
"""
from datetime import datetime

from flask import (current_app, g, redirect, render_template, request,
                   url_for)

from app.blueprints.feedback import feedback_bp
from app.extensions import db
from app.models import Feedback, Setting
from app.utils.rate_limit import SURVEY_PER_MINUTE, limit


def _clinic_name(lang):
    if lang == "en":
        return Setting.get("clinic_name") or Setting.get("clinic_name_ar") or "Clinic"
    return Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "العيادة"


def _clamp(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


@feedback_bp.route("/<token>", methods=["GET"])
# The one public page with a guessable-shaped URL. The token is random
# and long, so this is not what stops it being guessed — it is what stops
# the guessing being cheap.
@limit("survey", SURVEY_PER_MINUTE, methods=("GET",))
def rate(token):
    fb = Feedback.query.filter_by(token=token).first()
    lang = getattr(g, "lang", "ar")
    if fb is None:
        return render_template("feedback/rate.html", fb=None,
                               clinic=_clinic_name(lang)), 404
    from app.utils.feedback import survey_config
    return render_template(
        "feedback/rate.html", fb=fb, clinic=_clinic_name(lang),
        done=(fb.status == "submitted"), survey=survey_config(lang),
        doctor_name=fb.doctor.display_name(lang) if fb.doctor else None,
        patient_name=fb.patient.display_name(lang) if fb.patient else None,
    )


@feedback_bp.route("/<token>", methods=["POST"])
@limit("survey", SURVEY_PER_MINUTE)
def submit(token):
    fb = Feedback.query.filter_by(token=token).first()
    if fb is None:
        return render_template("feedback/rate.html", fb=None,
                               clinic=_clinic_name(getattr(g, "lang", "ar"))), 404
    if fb.status != "submitted":  # ignore double submissions
        fb.doctor_rating = _clamp(request.form.get("doctor_rating"), 1, 5)
        fb.service_rating = _clamp(request.form.get("service_rating"), 1, 5)
        fb.nps = _clamp(request.form.get("nps"), 0, 10)
        fb.comment = (request.form.get("comment") or "").strip()[:2000] or None
        fb.status = "submitted"
        fb.submitted_at = datetime.utcnow()
        # A low score used to go into a monthly average and nowhere else. It
        # now lands in the inbox as a thread waiting for an answer — which is
        # the whole difference between a complaint that is handled and one
        # that is counted.
        try:
            from app.utils.complaints import raise_from_feedback
            raise_from_feedback(fb, getattr(g, "lang", "ar"))
        except Exception:  # noqa: BLE001 — never fail a guardian's submission
            current_app.logger.exception("could not raise complaint thread")
        db.session.commit()
    return redirect(url_for("feedback.rate", token=token))
