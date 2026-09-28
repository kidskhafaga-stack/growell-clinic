"""Read-side roll-ups for patient satisfaction feedback (doctor stars + CRM
analytics). All figures use only ``submitted`` responses."""
from sqlalchemy import func

from app.extensions import db
from app.models import Feedback

# The survey's built-in questions, in display order. The wording and visibility
# of each are editable from the survey builder (stored in Settings); the data
# columns on ``Feedback`` stay fixed so the analytics keep working.
SURVEY_QUESTIONS = ["doctor", "service", "finance", "nps", "comment"]


def survey_config(lang="ar"):
    """The survey as the clinic has customised it: per-question label + whether
    it's shown, plus the intro title and thank-you line. Any field left blank in
    Settings falls back to the built-in translated default, so an untouched
    clinic still gets a complete, sensible survey."""
    from app.i18n import t
    from app.models import Setting

    def _text(key, default):
        return (Setting.get(f"{key}_{lang}") or "").strip() or default

    def _shown(key):
        return Setting.get(f"survey_show_{key}", "1") != "0"

    defaults = {
        "doctor": t("feedback.q_doctor"), "service": t("feedback.q_service"),
        "finance": t("feedback.q_finance"),
        "nps": t("feedback.q_nps"), "comment": t("feedback.q_comment"),
    }
    return {
        "intro": _text("survey_intro", t("feedback.title")),
        "thanks": _text("survey_thanks", t("feedback.thanks_hint")),
        "questions": {
            q: {"label": _text(f"survey_q_{q}", defaults[q]), "show": _shown(q)}
            for q in SURVEY_QUESTIONS
        },
    }


def survey_delivery():
    """How the survey reaches the patient — chosen in the survey builder.

    * ``link`` (default): a link to the built-in public rating page. Needs the
      clinic's public base URL (tunnel/domain) to open outside the LAN.
    * ``external``: a link the clinic pasted (e.g. a Google Form) — works even
      when the program itself is offline/LAN-only, since the form is hosted
      outside.
    * ``inline``: no page at all — the questions are numbered inside the
      WhatsApp message and the patient simply replies; answers arrive in the
      WhatsApp inbox.
    """
    from app.models import Setting
    mode = (Setting.get("survey_mode", "link") or "link").strip()
    if mode not in ("link", "external", "inline", "outside"):
        mode = "link"
    # The page outside the clinic, only once clinic.env says where it is.
    # Until then the clinic's own page, as before.
    if mode == "outside":
        from app.utils import survey_outside
        if not survey_outside.configured():
            mode = "link"
    return mode, (Setting.get("survey_external_url", "") or "").strip()


def inline_survey_text(lang="ar"):
    """The survey as a numbered WhatsApp text block (inline mode): intro, the
    visible questions with their answer scale, and a one-line reply example."""
    from app.i18n import t
    cfg = survey_config(lang)
    scales = {"doctor": " (1-5)", "service": " (1-5)", "finance": " (1-5)",
              "nps": " (0-10)",
              "comment": ""}
    lines = [cfg["intro"]]
    n = 0
    for q in SURVEY_QUESTIONS:
        meta = cfg["questions"][q]
        if not meta["show"]:
            continue
        n += 1
        lines.append(f"{n}. {meta['label']}{scales.get(q, '')}")
    lines.append(t("feedback.inline_reply_hint"))
    return "\n".join(lines)


def doctor_ratings():
    """``{doctor_id: {"avg": float, "count": int}}`` over submitted ratings."""
    rows = (db.session.query(
                Feedback.doctor_id,
                func.avg(Feedback.doctor_rating),
                func.count(Feedback.doctor_rating))
            .filter(Feedback.status == "submitted",
                    Feedback.doctor_rating.isnot(None))
            .group_by(Feedback.doctor_id).all())
    return {d: {"avg": round(float(a), 2), "count": int(n)}
            for d, a, n in rows if d is not None}


def clinic_summary(limit_comments=15):
    """Clinic-wide satisfaction figures for the analytics panel."""
    sub = Feedback.query.filter_by(status="submitted")
    total_sent = Feedback.query.count()
    total_sub = sub.count()

    avg_service, avg_doctor = (
        db.session.query(func.avg(Feedback.service_rating),
                         func.avg(Feedback.doctor_rating))
        .filter(Feedback.status == "submitted").first())

    dist = {i: 0 for i in range(1, 6)}
    for r, n in (db.session.query(Feedback.service_rating, func.count())
                 .filter(Feedback.status == "submitted",
                         Feedback.service_rating.isnot(None))
                 .group_by(Feedback.service_rating).all()):
        if r in dist:
            dist[r] = int(n)

    nps_vals = [v for (v,) in db.session.query(Feedback.nps)
                .filter(Feedback.status == "submitted",
                        Feedback.nps.isnot(None)).all()]
    nps = None
    if nps_vals:
        promoters = sum(1 for v in nps_vals if v >= 9)
        detractors = sum(1 for v in nps_vals if v <= 6)
        nps = round((promoters - detractors) * 100.0 / len(nps_vals))

    comments = (sub.filter(Feedback.comment.isnot(None))
                .order_by(Feedback.submitted_at.desc())
                .limit(limit_comments).all())

    return {
        "sent": total_sent,
        "submitted": total_sub,
        "response_rate": round(total_sub * 100.0 / total_sent) if total_sent else 0,
        "avg_service": round(float(avg_service), 2) if avg_service else None,
        "avg_doctor": round(float(avg_doctor), 2) if avg_doctor else None,
        "distribution": dist,
        "dist_max": max(dist.values()) if dist else 0,
        "nps": nps,
        "nps_count": len(nps_vals),
        "comments": comments,
    }


# ------------------------------------------------ what bothered them ------
#: The quick answers under a low score, per dimension of the survey. Fixed
#: keys, so the report can count them; the wording is a translation key.
#: Medical is the doctor question, service the service one, finance the bill.
CONCERNS = {
    "doctor": ("explain", "convinced", "late", "many_doctors"),
    "service": ("waiting", "nursing", "cleanliness", "reception"),
    "finance": ("price", "bill_unclear", "not_told", "insurance"),
}


def clean_concerns(values):
    """``"dimension:key,..."`` from what the page sent, keeping only the
    ones that exist — a public page takes no text it did not offer."""
    out = []
    for raw in values or ():
        dim, _, key = (raw or "").partition(":")
        if key in CONCERNS.get(dim, ()) and f"{dim}:{key}" not in out:
            out.append(f"{dim}:{key}")
    return ",".join(out)[:255] or None


# ------------------------------------------------------- sending it ------
def deliver(fb, patient, doctor=None, user_id=None, lang="ar"):
    """Send survey ``fb`` to the family — the one way it goes out, after a
    visit or after a stay. Builds the message from the ``feedback`` template
    in the clinic's delivery mode and honours its schedule. Returns the
    ``MessageLog``."""
    from app.models import Setting
    from app.models.message import _template_schedule
    from app.utils import whatsapp as wa

    tpl = wa.template_for("feedback")
    mode, ext_url = survey_delivery()
    if mode == "outside":
        from app.utils import survey_outside
        link = survey_outside.link(fb.token)
        fb.outside_state = "pending"
        # Out before the message, so the page has it when the family taps;
        # if the internet is down it waits, and goes on the next sync.
        try:
            survey_outside.push([fb], lang)
        except Exception:  # noqa: BLE001 — the survey is still sent
            pass
    elif mode == "external" and ext_url:
        link = ext_url
    elif mode == "inline":
        link = ""
    else:
        link = wa.feedback_link(fb.token)
    body = wa.render(wa.template_body("feedback"), {
        "patient": patient.display_name(lang) if patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "doctor": doctor.display_name(lang) if doctor else "",
        "link": link,
    }).strip()
    if mode == "inline":
        body = f"{body}\n\n{inline_survey_text(lang)}"
    schedule_at = _template_schedule(tpl) if tpl is not None else None
    return wa.send(body, patient.contact_phone, patient_id=patient.id,
                   user_id=user_id, template_type="feedback",
                   image_url=wa.template_image("feedback"),
                   scheduled_at=schedule_at)


def unsent(patient, reason, user_id=None):
    """Write down that a survey did not go, and why. Returns the row."""
    from app.models import MessageLog

    log = MessageLog(patient_id=patient.id if patient else None, body="",
                     to_phone=patient.contact_phone if patient else None,
                     template_type="feedback", status="skipped", error=reason,
                     created_by=user_id)
    db.session.add(log)
    return log


#: How the stay ended, and whether the family is asked about it. Never after
#: a death, and not after a transfer: that family is at another hospital.
ASK_AFTER = {"home", "self_discharge", "left_unseen"}


def recently_asked(patient_id, days=None):
    """Whether this family was sent a survey in the last ``days`` (the
    clinic's ``survey_min_days``, 7 unless it says otherwise) — so a child
    seen in emergency, admitted and discharged in one week is asked once."""
    from datetime import datetime, timedelta

    from app.models import Setting

    if days is None:
        try:
            days = int(Setting.get("survey_min_days", "7") or 7)
        except ValueError:
            days = 7
    since = datetime.utcnow() - timedelta(days=max(0, days))
    return Feedback.query.filter(Feedback.patient_id == patient_id,
                                 Feedback.created_at >= since).first() is not None


def after_stay(patient, how_left, admission=None, emergency_visit=None,
               doctor=None, centre_id=None, user=None, lang="ar"):
    """Ask the family about a stay or an emergency attendance that just
    ended. Returns the ``MessageLog`` — sent, or skipped with its reason —
    or ``None`` when this ending is not one the family is asked about.

    The same template, delivery mode and schedule as the survey after a
    visit (:func:`deliver`); the survey remembers the stay and its cost
    centre, so the report can say which unit the rating is about.
    """
    from app.utils import whatsapp as wa

    if patient is None or how_left not in ASK_AFTER:
        return None
    user_id = getattr(user, "id", None)
    if wa.type_is_off("feedback"):
        return unsent(patient, "type_off", user_id)
    if not patient.contact_phone:
        return unsent(patient, "missing_phone", user_id)
    if recently_asked(patient.id):
        return unsent(patient, "recent_survey", user_id)
    fb = Feedback(patient_id=patient.id,
                  admission_id=getattr(admission, "id", None),
                  emergency_visit_id=getattr(emergency_visit, "id", None),
                  doctor_id=getattr(doctor, "id", None),
                  cost_centre_id=centre_id, token=Feedback.new_token(),
                  created_by=user_id)
    db.session.add(fb)
    db.session.flush()
    return deliver(fb, patient, doctor=doctor, user_id=user_id, lang=lang)
