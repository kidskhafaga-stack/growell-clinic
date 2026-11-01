"""A payer's form filled from the program, and the approval asked for early —
CONTRACTS_PLAN.md ع-٣, ع-٤ and ع-٥.

* **The form** (:class:`PayerForm`): the company's blank page with the
  program's facts dragged onto it. :func:`facts` reads every fact the form
  can hold for one child — from the card, the visit, the booking, the
  approval — and the print puts each where the form says, in millimetres.
* **Early** (ع-٤): :func:`asks_for` lists what on a visit or a booking needs
  the payer's approval under the contract (``PayerContractRule.needs_approval``)
  and has none on file — said on the visit and the booking, not discovered
  when the bill is made. :func:`ask` opens the request, tied to them.
* **Sent** (ع-٥): :func:`send` mails the request to the payer's approvals
  desk, or puts it on WhatsApp, with the form as a PDF (``utils/pdf``; the self-contained page where the
  library is missing). The
  answer is still recorded by a person (``utils/approvals.decide``) — the
  program never reads «approved» out of a reply by itself.
"""
import json
from datetime import date, datetime

from app.extensions import db

#: Every fact a form can carry, in the order the designer lists them.
FIELDS = ("patient_name", "patient_name_en", "patient_number", "birth_date", "age", "gender",
          "membership_number", "plan_name", "holder_name", "holder_relation", "card_expiry",
          "payer_name", "service_type", "diagnosis", "diagnosis_code", "services",
          "approval_number", "estimate", "doctor_name", "doctor_specialty", "date",
          "clinic_name", "check")
#: The page sizes offered, in millimetres.
PAGES = {"A4": (210, 297), "A5": (148, 210), "Letter": (216, 279)}
ALIGNS = ("right", "center", "left")


class FormError(ValueError):
    """A refusal with a key (``payer_form.err_<key>``)."""


# ----------------------------------------------------------- the layout ---
def clean_layout(raw, width, height):
    """The designer's fields, checked: known facts only, inside the page,
    sensible sizes. Anything else is dropped rather than refused — a
    misplaced box is moved back by the person, not lost with the rest."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        raise FormError("layout") from None
    out = []
    for f in data if isinstance(data, list) else []:
        if not isinstance(f, dict) or f.get("key") not in FIELDS:
            continue
        try:
            x = min(max(float(f.get("x", 0)), 0), width)
            y = min(max(float(f.get("y", 0)), 0), height)
            w = min(max(float(f.get("w", 50)), 5), width)
            size = min(max(float(f.get("size", 10)), 6), 28)
        except (TypeError, ValueError):
            continue
        out.append({"key": f["key"], "x": round(x, 1), "y": round(y, 1), "w": round(w, 1),
                    "size": round(size, 1),
                    "align": f.get("align") if f.get("align") in ALIGNS else "right"})
    return out[:80]


def save(form, data, files, user):
    """Make or change a form. ``data`` is the screen's form."""
    from app.models import PayerEntity, PayerForm
    from app.utils.care_setting import SETTINGS
    from app.utils.uploads import save_document

    if form is None:
        payer = db.session.get(PayerEntity, int(data.get("payer_id") or 0) or 0)
        if payer is None:
            raise FormError("payer")
        form = PayerForm(payer_id=payer.id, by_id=user.id, name="-")
        db.session.add(form)
    name = (data.get("name") or "").strip()[:120]
    if not name:
        raise FormError("name")
    form.name = name
    form.setting = data.get("setting") if data.get("setting") in SETTINGS else None
    page = data.get("page")
    if page in PAGES:
        form.width_mm, form.height_mm = PAGES[page]
    form.print_background = data.get("print_background") == "1"
    upload = files.get("background") if files else None
    if upload is not None and upload.filename:
        stored = save_document(upload)
        if stored is None or stored.rsplit(".", 1)[-1] == "pdf":
            raise FormError("background")
        form.background = stored
    if "layout" in data:
        form.fields = json.dumps(clean_layout(data.get("layout"), form.width_mm, form.height_mm),
                                 ensure_ascii=False)
    form.is_active = data.get("is_active", "1") == "1"
    db.session.flush()
    return form


def forms_for(payer, setting=None):
    """The payer's active forms for a department, its own before «any»."""
    from app.models import PayerForm

    if payer is None:
        return []
    rows = PayerForm.query.filter_by(payer_id=payer.id, is_active=True).all()
    rows = [f for f in rows if f.setting in (None, setting) or setting is None]
    return sorted(rows, key=lambda f: (f.setting is None, f.name))


# ------------------------------------------------------------ the facts ---
def _age(born, on):
    if not born:
        return ""
    months = (on.year - born.year) * 12 + on.month - born.month - (on.day < born.day)
    years, months = divmod(max(months, 0), 12)
    return f"{years}y {months}m" if years else f"{months}m"


def facts(patient, payer=None, visit=None, appointment=None, approval=None, lang="ar"):
    """``{field: text}`` — what the form prints for this child and this
    occasion. A fact the program does not hold is an empty string, never a
    guess."""
    from app.models import Setting
    from app.utils.care_setting import OUTPATIENT

    payer = payer or (approval.payer if approval is not None else None)
    on = (visit.visit_date if visit is not None else
          appointment.appt_date if appointment is not None else date.today())
    card = None
    if payer is not None:
        cards = [c for c in getattr(patient, "coverages", []) if c.payer_id == payer.id]
        cards.sort(key=lambda c: (c.is_valid_on(on), c.created_at or datetime.min), reverse=True)
        card = cards[0] if cards else None
    dx = []
    if visit is not None:
        dx = sorted(visit.diagnoses, key=lambda d: (d.dx_type != "final", d.id))
    doctor = (visit.doctor if visit is not None else
              appointment.doctor if appointment is not None else None)
    services = []
    if approval is not None and approval.service is not None:
        services.append(approval.service.name)
    elif approval is not None and approval.description:
        services.append(approval.description)
    if visit is not None and not services:
        services = [s.name for s in visit.services]
    from app.i18n import t

    out = {
        "patient_name": patient.full_name or "",
        "patient_name_en": getattr(patient, "full_name_en", None) or "",
        "patient_number": patient.patient_number or "",
        "birth_date": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
        "age": _age(patient.date_of_birth, on),
        "gender": t("genders." + patient.gender) if patient.gender in ("male", "female") else "",
        "membership_number": (card.membership_number or "") if card else "",
        "plan_name": (card.plan_name or "") if card else "",
        "holder_name": (card.holder_name or "") if card else "",
        "holder_relation": (card.holder_relation or "") if card else "",
        "card_expiry": card.expiry_date.isoformat() if card and card.expiry_date else "",
        "payer_name": payer.name if payer is not None else "",
        "service_type": t("contracts.setting_" + OUTPATIENT),
        "diagnosis": "، ".join(d.display_title(lang) for d in dx),
        "diagnosis_code": ", ".join(d.code for d in dx if d.code),
        "services": "، ".join(services),
        "approval_number": (approval.approval_number or "") if approval is not None else "",
        "estimate": (f"{approval.estimate:g}" if approval is not None and approval.estimate else ""),
        "doctor_name": doctor.display_name(lang) if doctor is not None else "",
        "doctor_specialty": (getattr(doctor, "specialty", None) or "") if doctor is not None else "",
        "date": on.isoformat(),
        "clinic_name": Setting.get("clinic_name_ar" if lang == "ar" else "clinic_name_en")
        or Setting.get("clinic_name") or "",
        "check": "✓",
    }
    return out


# ------------------------------------------------------------ early (ع-٤) --
def _payer_of(patient, on):
    card = patient.active_coverage if patient is not None else None
    if card is None or not card.is_valid_on(on):
        return None
    return card.payer


def _appointment_services(appt):
    from app.models import Service

    ids = [int(x) for x in (appt.extra_service_ids or "").split(",") if x.strip().isdigit()]
    return [s for s in (db.session.get(Service, i) for i in ids) if s is not None]


def asks_for(patient, visit=None, appointment=None):
    """``[(service, approval or None)]`` — what on this visit or booking the
    payer's contract wants an approval for, each with the request already
    open for it (any state) or ``None``."""
    from app.models import InsuranceApproval
    from app.utils import approvals
    from app.utils.care_setting import OUTPATIENT

    on = (visit.visit_date if visit is not None else
          appointment.appt_date if appointment is not None else date.today())
    payer = _payer_of(patient, on)
    if payer is None:
        return []
    services = ([s.service for s in visit.services if s.service is not None] if visit is not None
                else _appointment_services(appointment) if appointment is not None else [])
    out, seen = [], set()
    for service in services:
        if service.id in seen or not approvals.rule_asks(payer, service, on, OUTPATIENT):
            continue
        seen.add(service.id)
        held = approvals.find(patient.id, payer.id, service.id, day=on)
        if held is not None:
            continue
        asked = (InsuranceApproval.query
                 .filter(InsuranceApproval.patient_id == patient.id,
                         InsuranceApproval.payer_id == payer.id,
                         InsuranceApproval.service_id == service.id,
                         InsuranceApproval.status == "requested")
                 .order_by(InsuranceApproval.id.desc()).first())
        out.append((service, asked))
    return out


def ask(patient, service, user, visit=None, appointment=None, estimate=None):
    """Open the request for one service, tied to the visit or booking; one
    already waiting for it is returned rather than doubled."""
    from app.models import InsuranceApproval

    on = (visit.visit_date if visit is not None else
          appointment.appt_date if appointment is not None else date.today())
    payer = _payer_of(patient, on)
    if payer is None:
        raise FormError("no_card")
    for s, asked in asks_for(patient, visit, appointment):
        if s.id == service.id and asked is not None:
            return asked
    row = InsuranceApproval(patient_id=patient.id, payer_id=payer.id, service_id=service.id,
                            description=service.name[:200],
                            estimate=estimate if estimate is not None else service.price,
                            visit_id=getattr(visit, "id", None),
                            appointment_id=getattr(appointment, "id", None),
                            requested_by=user.id)
    db.session.add(row)
    db.session.flush()
    return row


# ------------------------------------------------------------- sent (ع-٥) --
def where_to(payer):
    """``[(via, address)]`` the payer can be sent a request on."""
    out = []
    if payer is not None and (payer.approvals_email or "").strip():
        out.append(("email", payer.approvals_email.strip()))
    if payer is not None and (payer.approvals_whatsapp or "").strip():
        out.append(("whatsapp", payer.approvals_whatsapp.strip()))
    return out


def page_html(form, values, lang="ar"):
    """The filled form as one self-contained page — the scan embedded — for
    the file that goes to the payer."""
    import base64
    import os

    from flask import render_template

    from app.utils.uploads import docs_dir

    background = ""
    if form is not None and form.background and form.print_background:
        path = os.path.join(docs_dir(), form.background)
        if os.path.isfile(path):
            ext = form.background.rsplit(".", 1)[-1].lower()
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            with open(path, "rb") as fh:
                background = f"data:{mime};base64," + base64.b64encode(fh.read()).decode()
    return render_template("finance/payer_form_print.html", form=form, values=values,
                           background=background, standalone=True)


def page_pdf(form, values):
    """The filled form as a PDF (``utils/pdf``) — the facts in their places
    and, when the form prints on plain paper, the scan behind them. None when
    the PDF library is not installed on this computer."""
    import os

    from app.utils import pdf
    from app.utils.uploads import docs_dir

    if form is None or not pdf.available():
        return None
    doc = pdf.new(form.width_mm, form.height_mm)
    if form.background and form.print_background:
        pdf.background(doc, os.path.join(docs_dir(), form.background))
    for f in form.layout:
        pdf.text_box(doc, f["x"], f["y"], f["w"], f["size"], values.get(f["key"], ""),
                     align=f.get("align", "right"))
    return pdf.output(doc)


def attachment(form, values, lang="ar"):
    """``(bytes, filename, mime)`` of the file that goes to the payer: the
    PDF, or the self-contained page where the PDF library is missing."""
    if form is None:
        return None
    data = page_pdf(form, values)
    if data is not None:
        return data, "approval-request.pdf", "application/pdf"
    return page_html(form, values, lang).encode("utf-8"), "approval-request.html", "text/html"


def send(approval, via, user, lang="ar"):
    """Send the request to the payer's approvals desk on ``via``. Returns
    the address it went to. The caller commits."""
    from app.i18n import t

    targets = dict(where_to(approval.payer))
    if via not in targets:
        raise FormError("no_address")
    address = targets[via]
    forms = forms_for(approval.payer)
    form = forms[0] if forms else None
    values = facts(approval.patient, approval.payer, visit=approval.visit,
                   appointment=approval.appointment, approval=approval, lang=lang)
    body = t("payer_form.request_body", patient=values["patient_name"],
             number=values["membership_number"] or "—", service=values["services"] or "—",
             diagnosis=values["diagnosis"] or "—", clinic=values["clinic_name"] or "")
    attached = attachment(form, values, lang)
    if via == "email":
        _mail(address, t("payer_form.request_subject", patient=values["patient_name"]),
              body, attached)
    else:
        _whatsapp(address, body, approval, user, attached)
    approval.sent_at, approval.sent_via, approval.sent_to = datetime.utcnow(), via, address
    approval.sent_by = user.id
    return address


def _mail(address, subject, body, attached=None):
    """Through the clinic's own mailbox (``utils/mail_channel``), the way it
    answers a family — the same server, the same login."""
    import email.utils
    import smtplib
    import ssl
    from email.message import EmailMessage

    from app.utils import mail_channel

    if not mail_channel.ready():
        raise FormError("no_mailbox")
    cfg = mail_channel.config()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["address"], address, subject
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg.set_content(body)
    if attached:
        data, filename, mime = attached
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    context = ssl.create_default_context()
    try:
        if cfg["smtp_port"] == 465:
            server = smtplib.SMTP_SSL(cfg["smtp_host"], 465, context=context,
                                      timeout=mail_channel.TIMEOUT)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=mail_channel.TIMEOUT)
            server.starttls(context=context)
        with server:
            mail_channel._smtp_login(server, cfg)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException, mail_channel.MailRefused):
        raise FormError("not_sent") from None


def _whatsapp(address, body, approval, user, attached=None):
    """On WhatsApp, with the form as a file where the connection can carry
    one (``whatsapp.send_document``); otherwise the words, and the person
    attaches the printed form."""
    from app.utils import whatsapp

    if attached:
        data, filename, mime = attached
        log = whatsapp.send_document(body, address, data, filename, mime=mime,
                                     patient_id=approval.patient_id, user_id=user.id)
    else:
        log = whatsapp.send(body, address, patient_id=approval.patient_id, user_id=user.id,
                            ignore_window=True)
    if log is not None and log.status in ("failed", "skipped") and not log.link:
        raise FormError("not_sent")
