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
from app.i18n import t
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
    from app.utils.feedback import CONCERNS, survey_config
    # What the survey is about, in the family's words: "the stay in the
    # NICU" rather than "your visit" when it was three nights upstairs.
    about = None
    if fb.admission is not None or fb.emergency_visit is not None:
        centre = fb.cost_centre.display_name(lang) if fb.cost_centre else ""
        about = t("feedback.about_stay", place=centre) if centre else None
    return render_template(
        "feedback/rate.html", fb=fb, clinic=_clinic_name(lang),
        concerns=CONCERNS, about=about,
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
        fb.finance_rating = _clamp(request.form.get("finance_rating"), 1, 5)
        from app.utils.feedback import clean_concerns
        fb.concerns = clean_concerns(request.form.getlist("concern"))
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


# ------------------------------------------------------------ complaints ---
# Two public pages for the complaints book (``utils/complaint_cases``): the
# family's verdict on the answer they were sent, and a complaint written by
# the family themselves from a link the clinic sent them. Same rules as the
# survey: an opaque token, no login, rate-limited, and a page that never
# errors at a guardian because of something on the clinic's side.
@feedback_bp.route("/c/<token>", methods=["GET", "POST"])
@limit("survey", SURVEY_PER_MINUTE, methods=("GET", "POST"))
def case_verdict(token):
    from app.models import Complaint
    from app.utils import complaint_cases as cases

    lang = getattr(g, "lang", "ar")
    case = Complaint.query.filter_by(token=token).first()
    if case is None:
        return render_template("feedback/case_verdict.html", case=None,
                               clinic=_clinic_name(lang)), 404
    if request.method == "POST":
        stars = _clamp(request.form.get("stars"), 1, 5)
        if stars is not None and cases.rate(case, stars,
                                            request.form.get("comment")):
            db.session.commit()
        return redirect(url_for("feedback.case_verdict", token=token))
    return render_template("feedback/case_verdict.html", case=case,
                           clinic=_clinic_name(lang),
                           can_rate=(case.rated_at is None
                                     and case.status in ("answered", "closed")))


@feedback_bp.route("/c/new/<token>", methods=["GET", "POST"])
@limit("survey", SURVEY_PER_MINUTE, methods=("GET", "POST"))
def case_new(token):
    from app.models import Patient
    from app.models.complaint import KINDS, SIDES
    from app.utils import complaint_cases as cases

    lang = getattr(g, "lang", "ar")
    pid = cases.read_invite(token)
    patient = db.session.get(Patient, pid) if pid else None
    if patient is None:
        return render_template("feedback/case_new.html", patient=None,
                               clinic=_clinic_name(lang)), 404
    if request.method == "POST":
        try:
            case = cases.open_case(
                request.form.get("description"), kind=request.form.get("kind"),
                channel="online", patient=patient, side=request.form.get("side"),
                wanted=request.form.get("wanted"), lang=lang)
        except ValueError:
            return redirect(url_for("feedback.case_new", token=token))
        db.session.commit()
        return redirect(url_for("feedback.case_verdict", token=case.token))
    return render_template("feedback/case_new.html", patient=patient,
                           clinic=_clinic_name(lang), kinds=KINDS, sides=SIDES,
                           hours=cases.first_contact_hours())
