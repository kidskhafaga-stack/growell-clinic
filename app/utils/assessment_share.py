"""An approved assessment to the family (ASSESSMENTS_PLAN.md ت-٣).

The same road the lab result takes (``utils/lab_share``, م-٤), and for the
same reasons:

* only **after the doctor approved it** — a draft never leaves;
* a **link** when the clinic can be reached from outside: it opens the report
  after the child's date of birth, ends after the lab share's days, and five
  wrong answers lock it;
* the **report itself as a file** when the program runs on the clinic's own
  network, because a link there opens nothing on a family's phone;
* **Arabic and English** in the one page, one shown and a switch for the
  other, and it **prints** — the family's right.

What it carries is the report as the doctor approved it: the scores the
specialist wrote, each tool's own criterion where its instructions set one,
the impression and the doctor's word. Nothing is added.
"""
import secrets
from datetime import datetime, timedelta

from app.extensions import db
from app.utils import lab_share


class ShareError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _link(token):
    from flask import url_for

    from app.utils import whatsapp as wa

    base = wa.get_config().get("public_base")
    path = url_for("assessments.shared", token=token)
    return f"{base}{path}" if base else url_for("assessments.shared", token=token, _external=True)


def sheet(row, open_lang="ar"):
    """The report as one self-contained page, in both languages."""
    from flask import g, render_template

    from app.i18n import available_languages, get_direction, translate
    from app.utils import assessments as asm
    from app.utils.clock import local_now

    langs = [code for code in ("ar", "en") if code in available_languages()] or ["ar"]
    open_lang = open_lang if open_lang in langs else langs[0]
    printed = local_now()
    saved = (getattr(g, "lang", None), getattr(g, "direction", None))
    bodies = []
    try:
        for code in langs:
            g.lang, g.direction = code, get_direction(code)
            bodies.append((code, g.direction, render_template(
                "assessments/_report_sheet_body.html", row=row, patient=row.patient,
                form=row.form, answers=row.answers or {}, history=asm.history(row),
                age=asm.age_on(row.patient, row.assessed_on), asm=asm,
                clinic_name=lab_share._clinic_name(), printed_at=printed,
                L=code)))
    finally:
        g.lang, g.direction = saved
    name = row.form.get("name_" + open_lang) or row.form.get("name_ar") or ""
    return render_template("assessments/report_sheet.html", bodies=bodies, open_lang=open_lang,
                           title=f"{name} — {row.patient.display_name(open_lang)}").lstrip()


def file_name(row):
    number = "".join(ch for ch in (row.patient.patient_number or "") if ch.isalnum())
    return f"assessment-{row.kind}-{number or row.patient_id}-{row.assessed_on:%Y%m%d}.html"


def live(row):
    """The link already with the family for this assessment, still working."""
    from app.models import AssessmentShare

    for share in (AssessmentShare.query.filter_by(assessment_id=row.id)
                  .order_by(AssessmentShare.id.desc()).all()):
        if share.mode == "link" and lab_share.state(share) == "ok":
            return share
    return None


def sent(row):
    from app.models import AssessmentShare

    return (AssessmentShare.query.filter_by(assessment_id=row.id)
            .order_by(AssessmentShare.id.desc()).all())


def send(row, user, lang="ar"):
    """Send this approved assessment to the family on WhatsApp. Returns
    ``(share, log)``; the caller commits."""
    from app.models import ActivityLog, AssessmentShare
    from app.utils import whatsapp as wa

    if row is None or not row.is_approved:
        raise ShareError("not_approved")
    patient = row.patient
    phone = patient.contact_phone if patient else None
    if not phone:
        raise ShareError("no_phone")
    mode = "link" if lab_share.online() else "file"
    if mode == "link" and live(row):
        raise ShareError("already_sent")
    template = "assessment_report" if mode == "link" else "assessment_report_file"
    share = AssessmentShare(token=secrets.token_urlsafe(24), assessment_id=row.id,
                            patient_id=patient.id, mode=mode, to_phone=phone,
                            created_by=getattr(user, "id", None),
                            expires_at=datetime.utcnow() + timedelta(days=lab_share.days()))
    db.session.add(share)
    db.session.flush()
    name = row.form.get("name_" + lang) or row.form.get("name_ar") or ""
    body = wa.render(wa.template_body(template), {
        "patient": patient.display_name(lang),
        "first_name": (patient.display_name(lang) or "").split(" ")[0],
        "assessment": name,
        "clinic": lab_share._clinic_name(),
        "link": _link(share.token) if mode == "link" else "",
        "days": lab_share.days(),
    })
    if mode == "link":
        log = wa.send(body, phone, patient_id=patient.id, user_id=getattr(user, "id", None),
                      template_type=template, ignore_window=True)
    else:
        log = wa.send_document(body, phone, sheet(row, lang).encode("utf-8"), file_name(row),
                               patient_id=patient.id, user_id=getattr(user, "id", None),
                               template_type=template)
    db.session.flush()
    share.message_id = log.id
    ActivityLog.record("assessment.sent", user_id=getattr(user, "id", None),
                       entity="assessment_share", entity_id=share.id,
                       detail=f"{mode} assessment={row.id}")
    return share, log


def by_token(token):
    from app.models import AssessmentShare

    token = (token or "").strip()
    if not token or len(token) > 48:
        return None
    return AssessmentShare.query.filter_by(token=token).first()
