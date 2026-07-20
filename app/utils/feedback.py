"""Read-side roll-ups for patient satisfaction feedback (doctor stars + CRM
analytics). All figures use only ``submitted`` responses."""
from sqlalchemy import func

from app.extensions import db
from app.models import Feedback

# The survey's built-in questions, in display order. The wording and visibility
# of each are editable from the survey builder (stored in Settings); the data
# columns on ``Feedback`` stay fixed so the analytics keep working.
SURVEY_QUESTIONS = ["doctor", "service", "nps", "comment"]


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
    if mode not in ("link", "external", "inline"):
        mode = "link"
    return mode, (Setting.get("survey_external_url", "") or "").strip()


def inline_survey_text(lang="ar"):
    """The survey as a numbered WhatsApp text block (inline mode): intro, the
    visible questions with their answer scale, and a one-line reply example."""
    from app.i18n import t
    cfg = survey_config(lang)
    scales = {"doctor": " (1-5)", "service": " (1-5)", "nps": " (0-10)",
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
