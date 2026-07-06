"""Read-side roll-ups for patient satisfaction feedback (doctor stars + CRM
analytics). All figures use only ``submitted`` responses."""
from sqlalchemy import func

from app.extensions import db
from app.models import Feedback


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
