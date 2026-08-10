"""Messaging module (WhatsApp).

Prepares patient appointment confirmations (and logs them). Depending on the
configured provider the message is either sent through an API or surfaced as a
click-to-send wa.me link for the front desk.
"""
import os
import uuid
from datetime import date, datetime

from flask import current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.models import (
    ACTIVE_STATUSES,
    AUTOMATION_TYPES,
    MESSAGE_STATUSES,
    OCCASION_TYPES,
    SEND_MODES,
    SKIP_REASONS,
    TEMPLATE_VARIABLES,
    Appointment,
    MessageLog,
    MessageTemplate,
    Patient,
    Setting,
    User,
)
from app.utils import whatsapp as wa
from app.utils.decorators import admin_required, module_required
from app.utils.paging import paginate
from app.utils.resend import retryable
from app.utils.triage import TOPICS as TRIAGE_TOPICS
from app.utils.clock import local_today

MODULE = "messages"
ALLOWED_IMG = {"png", "jpg", "jpeg", "webp", "gif"}
WA_CONFIG_KEYS = [
    "crm_mode", "wa_provider", "wa_country_code", "queue_mode",
    "wa_cloud_token", "wa_cloud_phone_id",
    "wa_wapilot_key", "wa_wapilot_instance", "wa_wapilot_endpoint",
    "wa_public_base_url", "wa_send_from", "wa_send_to", "wa_daily_cap",
    # How far ahead of an appointment its reminder goes out. It lives with the
    # window and the cap rather than on the template, because the template's
    # own delay columns mean "after the trigger" for every other type and a
    # column that means "before" for one row is a bug factory.
    "wa_reminder_hours",
    # How long without a visit before a family is worth a message. The clinic
    # decides; it has to stay under the archiving window.
    "recall_after_months",
    "wa_meta_verify_token", "wa_meta_app_secret",
    "wa_approved_templates",
]
WA_TOGGLE_KEYS = ["wa_inbound_enabled"]


def _crm_img_dir():
    return os.path.join(current_app.static_folder, "uploads", "crm")


def _save_crm_image(file):
    """Store an uploaded template image, returning its static-relative path."""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMG:
        flash(t("crm.bad_image"), "warning")
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(_crm_img_dir(), exist_ok=True)
    file.save(os.path.join(_crm_img_dir(), secure_filename(name)))
    return f"static/uploads/crm/{name}"


def _remove_crm_image(rel_path):
    if not rel_path or not rel_path.startswith("static/uploads/crm/"):
        return
    path = os.path.join(current_app.static_folder, rel_path.split("static/", 1)[1])
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _day_appointments(doctor_id, on_date):
    """A doctor's active bookings for a day, ordered by time (queue order)."""
    return (
        Appointment.query
        .filter(Appointment.doctor_id == doctor_id)
        .filter(Appointment.appt_date == on_date)
        .filter(Appointment.status.in_(ACTIVE_STATUSES))
        .order_by(Appointment.appt_time, Appointment.id)
        .all()
    )


def queue_position(appointment):
    """1-based position among the doctor's same-day active bookings."""
    day = _day_appointments(appointment.doctor_id, appointment.appt_date)
    for idx, appt in enumerate(day, start=1):
        if appt.id == appointment.id:
            return idx
    return len(day) + 1


def _appt_confirm_body(appt, lang, queue=None):
    """Render the patient appointment-confirmation message."""
    if queue is None:
        mode = Setting.get("queue_mode", "number")
        queue = queue_position(appt) if mode == "number" else appt.time_label
    return wa.render(wa.template_body("appointment_confirm"), {
        "patient": appt.patient.display_name(lang) if appt.patient else "",
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
        "date": appt.appt_date.strftime("%Y-%m-%d"),
        "time": appt.time_label,
        "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
        "queue": queue,
    })


@messages_bp.route("/")
@module_required(MODULE)
def index():
    """Send dashboard: delivery stats, status filter, scheduled queue, log."""
    status = (request.args.get("status") or "").strip()

    q = MessageLog.query
    if status in MESSAGE_STATUSES:
        q = q.filter(MessageLog.status == status)
    pagination = paginate(q.order_by(MessageLog.created_at.desc()))

    counts = {s: 0 for s in MESSAGE_STATUSES}
    for st, n in (db.session.query(MessageLog.status, db.func.count())
                  .group_by(MessageLog.status).all()):
        counts[st] = n
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (MessageLog.query
                  .filter(MessageLog.status == "sent",
                          MessageLog.sent_at >= today).count())
    due_now = (MessageLog.query
               .filter(MessageLog.status == "scheduled",
                       MessageLog.scheduled_at <= datetime.utcnow()).count())
    return render_template(
        "messages/index.html", pagination=pagination, logs=pagination.items,
        counts=counts, status=status, statuses=MESSAGE_STATUSES,
        sent_today=sent_today, due_now=due_now,
        by_type=_delivery_by_type(), failures=_recent_failures(),
        retryable=len(retryable()),
        skip_reasons=SKIP_REASONS,
        daily_cap=Setting.get("wa_daily_cap", "") or "0",
    )


# How far back the delivery board looks. Older than this is history, not a
# problem anyone is going to act on this morning.
BOARD_DAYS = 30


def _delivery_by_type(days=BOARD_DAYS):
    """Sent vs failed per notification type — the shape of the problem.

    A single "12 failed" tells you nothing worth acting on. "Every vaccine
    reminder failed and nothing else did" tells you exactly where to look.

    ``sent`` and ``arrived`` are counted apart on purpose. "Sent" only ever
    meant the provider accepted the message; ``delivered``/``read`` are the
    provider coming back to say it reached the handset. A board that adds them
    together tells a clinic every reminder landed while a dead number quietly
    swallows one a week — which is exactly what this program did before the
    delivery receipts were read.
    """
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.session.query(MessageLog.template_type, MessageLog.status,
                             db.func.count())
            .filter(MessageLog.created_at >= since,
                    MessageLog.direction == "out")
            .group_by(MessageLog.template_type, MessageLog.status).all())
    board = {}
    for kind, status, count in rows:
        entry = board.setdefault(kind or "other",
                                 {"type": kind or "other", "total": 0,
                                  "sent": 0, "failed": 0, "link": 0,
                                  "scheduled": 0, "skipped": 0,
                                  "delivered": 0, "read": 0})
        entry["total"] += count
        if status in entry:
            entry[status] += count
    for entry in board.values():
        entry["arrived"] = entry["delivered"] + entry["read"]
        # Accepted by the provider, and never heard of again. On a clinic whose
        # provider sends receipts this is the number worth looking at: it is
        # the messages nobody can say arrived.
        entry["unconfirmed"] = entry["sent"]
        done = entry["sent"] + entry["arrived"] + entry["failed"]
        entry["fail_rate"] = round(entry["failed"] * 100.0 / done, 1) if done else 0
    return sorted(board.values(), key=lambda e: (-e["failed"], -e["total"]))


def _recent_failures(limit=20, days=BOARD_DAYS):
    """The ones that didn't go, with the reason — a list you can act on.

    Skipped counts as didn't go. A clinic reported the post-visit and
    post-vaccination messages "not being generated": they were being skipped —
    no number on the file, or the type switched off — and a skip that appears
    on no screen is the same thing as a bug to whoever is waiting for the
    message.
    """
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    return (MessageLog.query
            .filter(MessageLog.status.in_(("failed", "skipped")),
                    MessageLog.created_at >= since)
            .order_by(MessageLog.created_at.desc()).limit(limit).all())


@messages_bp.route("/recall")
@module_required(MODULE)
def recall():
    """The families who have stopped coming — as a list to read, not a sweep.

    This is the only message the clinic sends to people who are not currently
    talking to it, so nothing here is scheduled or automatic: somebody looks at
    the list and presses.
    """
    from app.utils import recall as rc
    from app.utils.archiving import inactive_years

    rows = rc.candidates()
    return render_template(
        "messages/recall.html", rows=rows, months=rc.after_months(),
        cutoff=rc.cutoff(), archive_years=inactive_years(),
        archive_conflict=rc.archive_conflict(),
        daily_cap=Setting.get("wa_daily_cap", "") or "0")


@messages_bp.route("/recall/send", methods=["POST"])
@module_required(MODULE)
def recall_send():
    """Send one family's recall, or everybody currently on the list."""
    from app.utils import recall as rc

    lang = getattr(g, "lang", "ar")
    patient_id = request.form.get("patient_id", type=int)
    if patient_id:
        patient = db.session.get(Patient, patient_id)
        last = next((d for p, d in rc.candidates() if p.id == patient_id), None)
        log = rc.send_to(patient, last, user_id=current_user.id, lang=lang)
        db.session.commit()
        flash(t("crm.recall_sent_one") if log is not None
              else t("crm.recall_none"), "success" if log else "info")
    else:
        result = rc.send_all(user_id=current_user.id, lang=lang)
        flash(t("crm.recall_sent_n", n=result["sent"]) if result["sent"]
              else t("crm.recall_none"),
              "success" if result["sent"] else "info")
    return redirect(url_for("messages.recall"))


@messages_bp.route("/resend-failed", methods=["POST"])
@module_required(MODULE)
def resend_failed():
    """Send the recent failures again — the ones still worth sending.

    The board has counted failures since it was built and offered nothing to
    do about them; the only remedy was to find each one and send it by hand,
    which nobody does twelve times.
    """
    from app.utils.resend import resend_all

    result = resend_all(user_id=current_user.id)
    if result["resent"]:
        flash(t("crm.resent_n", n=result["resent"]), "success")
    else:
        flash(t("crm.resend_none"), "info")
    return redirect(request.referrer or url_for("messages.index"))


@messages_bp.route("/service")
@module_required(MODULE)
def service_board():
    """Whether this clinic answers people, and how fast.

    The send screen counts messages by status, which says how the *provider*
    is doing. This says how the clinic is doing — which is the question
    somebody running one actually has.
    """
    from app.utils.service_stats import summary

    days = request.args.get("days", 30, type=int)
    days = days if days in (7, 30, 90) else 30
    return render_template("messages/service.html",
                           stats=summary(days=days), days=days)


@messages_bp.route("/inbox")
@module_required(MODULE)
def inbox():
    """WhatsApp conversations: one row per patient/phone with the last message.

    Defaults to the ones still waiting for an answer — a customer-service
    inbox that opens on "who is waiting" is the difference between a log and
    a work list."""
    from app.utils import inbox as ibx

    search = (request.args.get("q") or "").strip()
    view = request.args.get("view") or "open"
    mine = view == "mine"
    convs = ibx.conversations(search=search, only_open=(view == "open"),
                              assignee=current_user.id if mine else None)
    # The counters must not depend on the filter the user is looking through.
    every = ibx.conversations(search=search)
    mine_count = sum(1 for c in every
                     if c["record"] is not None
                     and c["record"].assigned_to == current_user.id)
    return render_template(
        "messages/inbox.html", conversations=convs, search=search, view=view,
        total=len(every), open_count=sum(1 for c in every if c["open"]),
        mine_count=mine_count, stats=ibx.response_stats(),
        staff=_desk_staff(), waiting_label=waiting_label,
        patients=Patient.query.filter_by(is_active=True)
        .order_by(Patient.full_name).limit(500).all())


def waiting_label(hours):
    """How long they've been waiting, in words a person reads at a glance.

    "waiting" is a state; "waiting since Tuesday" is a problem — and only the
    second one gets anybody to open the thread."""
    hours = hours or 0
    if hours < 1:
        return t("inbox.wait_minutes", n=max(int(hours * 60), 1))
    if hours < 24:
        return t("inbox.wait_hours", n=int(hours))
    return t("inbox.wait_days", n=int(hours // 24))


def _desk_staff():
    """Who can be handed a conversation: whoever can reach this module."""
    rows = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return [u for u in rows if u.can_access(MODULE)]


@messages_bp.route("/inbox/<key>/assign", methods=["POST"])
@module_required(MODULE)
def inbox_assign(key):
    """Hand a conversation to someone by name.

    On a desk with three people, "someone will answer it" is exactly how a
    message goes unanswered for two days."""
    from app.utils.inbox import conversation_for

    record = conversation_for(key)
    user_id = request.form.get("assigned_to", type=int)
    user = db.session.get(User, user_id) if user_id else None
    record.assigned_to = user.id if user is not None else None
    record.assigned_at = datetime.utcnow() if user is not None else None
    db.session.commit()
    flash(t("inbox.assigned", name=user.display_name(getattr(g, "lang", "ar")))
          if user is not None else t("inbox.unassigned"), "success")
    return redirect(url_for("messages.inbox_thread", key=key))


@messages_bp.route("/inbox/<key>/topic", methods=["POST"])
@module_required(MODULE)
def inbox_topic(key):
    """Say what a conversation is about — and whether it cannot wait.

    The program guesses from what the family wrote, and shows the guess as a
    guess. This is a person disagreeing, or confirming, in one click; from
    then on the guess stops being made for this thread.
    """
    from app.utils.inbox import conversation_for
    from app.utils.triage import TOPICS

    record = conversation_for(key)
    topic = (request.form.get("topic") or "").strip()
    record.topic = topic if topic in TOPICS else None
    db.session.commit()
    flash(t("triage.saved"), "success")
    return redirect(request.referrer or url_for("messages.inbox_thread", key=key))


@messages_bp.route("/inbox/<key>/note", methods=["POST"])
@module_required(MODULE)
def inbox_note(key):
    """A line for the next person who opens this thread.

    "اتصلت بيهم وما ردوش" belongs with the conversation, not in someone's
    head — and it must never be sent to the patient by accident, so it lives
    on the record and not in the message box."""
    from app.utils.inbox import conversation_for

    record = conversation_for(key)
    record.note = (request.form.get("note") or "").strip()[:255] or None
    db.session.commit()
    flash(t("inbox.note_saved"), "success")
    return redirect(url_for("messages.inbox_thread", key=key))


@messages_bp.route("/inbox/<key>/resolve", methods=["POST"])
@module_required(MODULE)
def inbox_resolve(key):
    """Declare a conversation answered — or put it back on the list.

    Stamped with the time rather than a flag, so the next message from the
    patient re-opens it without anyone remembering to."""
    from app.utils.inbox import conversation_for

    record = conversation_for(key)
    if request.form.get("reopen"):
        record.resolved_at = record.resolved_by = None
        flash(t("inbox.reopened"), "info")
    else:
        record.resolved_at = datetime.utcnow()
        record.resolved_by = current_user.id
        flash(t("inbox.resolved"), "success")
    db.session.commit()
    return redirect(url_for("messages.inbox_thread", key=key))


def _thread_query(key):
    from app.utils.inbox import thread_query

    return thread_query(key)


@messages_bp.route("/inbox/<key>")
@module_required(MODULE)
def inbox_thread(key):
    """One conversation as a chat: bubbles in/out + a reply box."""
    msgs = _thread_query(key).order_by(MessageLog.created_at).all()
    if not msgs:
        flash(t("inbox.empty_thread"), "warning")
        return redirect(url_for("messages.inbox"))
    # Opening the thread marks its inbound messages as read.
    changed = False
    for m in msgs:
        if m.direction == "in" and m.status != "read":
            m.status = "read"
            changed = True
    if changed:
        db.session.commit()
    patient = next((m.patient for m in msgs if m.patient), None)
    phone = next((m.to_phone for m in reversed(msgs) if m.to_phone), None)
    # How long the family waited for each answer, shown beside the bubbles —
    # the only way anyone notices a two-day reply.
    waits, pending = _reply_waits(msgs)
    from app.utils.service_desk import (ai_available, quick_replies,
                                        render_reply)
    lang = getattr(g, "lang", "ar")
    canned = [{"title": q.title, "body": render_reply(q.body, patient, lang)}
              for q in quick_replies()]
    from app.utils.inbox import (conversation_for, last_inbound_at,
                                 session_window)
    record = conversation_for(key, create=False)
    resolved = (record is not None
                and record.is_resolved_for(last_inbound_at(key)))
    db.session.commit()
    window = session_window(key)
    return render_template(
        "messages/thread.html", msgs=msgs, key=key, patient=patient,
        phone=phone, waits=waits, pending=pending,
        record=record, resolved=resolved, staff=_desk_staff(),
        window=window, approved=_approved_for(window),
        opted_out=bool(patient is not None and patient.wa_opt_out),
        canned=canned, ai_ready=ai_available(),
        topics=TRIAGE_TOPICS,
        patients=(Patient.query.filter_by(is_active=True)
                  .order_by(Patient.full_name).limit(500).all()
                  if patient is None else []))


def _approved_for(window):
    """``{available, list}`` — the approved templates to offer, if any.

    Only when the free window has actually shut. While it is open, free text is
    what the family should get: a template is stiffer, costs money, and
    offering both invites sending the wrong one.

    ``available`` and an empty list are different situations and the screen
    says so — the clinic is on the Cloud API and has registered nothing, which
    is a settings link, not a shrug.
    """
    from app.utils import wa_templates

    if window is None or window.get("open") or not wa_templates.available():
        return {"available": False, "list": []}
    return {"available": True, "list": wa_templates.approved()}


def _reply_waits(msgs):
    """``({inbound_id: "answered in …"}, unanswered)`` for one conversation."""
    waits = {}
    pending = False
    for i, m in enumerate(msgs):
        if m.direction != "in":
            continue
        reply = next((r for r in msgs[i + 1:] if r.direction == "out"), None)
        if reply is None:
            pending = True
            continue
        gap = (reply.created_at - m.created_at).total_seconds() / 60.0
        waits[m.id] = wait_label(max(gap, 0))
    return waits, pending


def wait_label(minutes):
    """A waiting time a human reads at a glance: minutes, hours, then days."""
    if minutes is None:
        return ""
    minutes = int(minutes)
    if minutes < 60:
        return t("inbox.in_minutes", n=minutes)
    if minutes < 60 * 24:
        return t("inbox.in_hours", n=round(minutes / 60.0, 1))
    return t("inbox.in_days", n=round(minutes / 1440.0, 1))


@messages_bp.route("/inbox/<key>/ai-suggest", methods=["POST"])
@module_required(MODULE)
def inbox_ai_suggest(key):
    """Draft a reply with the clinic's configured AI — into the box, not out.

    The suggestion lands in the reply field for a human to read, change and
    send. A clinic answering a worried parent is not a place for a machine
    with a send button."""
    from app.utils.service_desk import draft_reply

    msgs = _thread_query(key).order_by(MessageLog.created_at).all()
    patient = next((m.patient for m in msgs if m.patient), None)
    result = draft_reply(msgs, patient, getattr(g, "lang", "ar"))
    if not result.get("ok"):
        reason = result.get("error") or "failed"
        known = {"not_configured", "nothing_to_answer", "disabled", "empty"}
        return {"ok": False,
                "error": t("inbox.ai_" + reason) if reason in known
                else t("inbox.ai_failed"),
                "detail": str(reason)[:200]}, 200
    return {"ok": True, "text": result["text"],
            # The message asked the model to change its behaviour. The draft is
            # still shown — the person about to press send is the control that
            # actually holds — but they are told what they're looking at.
            "warn": (t("inbox.ai_suspicious") if result.get("suspicious")
                     else "")}


@messages_bp.route("/quick-replies", methods=["GET", "POST"])
@module_required(MODULE)
def quick_replies():
    """The canned answers, edited from inside the program."""
    from app.models import QuickReply
    from app.utils.service_desk import (DEFAULT_AWAY_BODY, hours_config,
                                        seed_quick_replies)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        if not title or not body:
            flash(t("common.required"), "warning")
            return redirect(url_for("messages.quick_replies"))
        db.session.add(QuickReply(
            title=title, body=body, is_active=True,
            sort_order=request.form.get("sort_order", type=int) or 100))
        db.session.commit()
        flash(t("quick.added"), "success")
        return redirect(url_for("messages.quick_replies"))

    if seed_quick_replies():
        db.session.commit()
    return render_template(
        "messages/quick_replies.html",
        replies=QuickReply.query.order_by(QuickReply.sort_order,
                                          QuickReply.id).all(),
        hours=hours_config(), default_away=DEFAULT_AWAY_BODY,
        weekdays=list(range(7)))


@messages_bp.route("/quick-replies/<int:reply_id>/edit", methods=["POST"])
@module_required(MODULE)
def quick_reply_edit(reply_id):
    from app.models import QuickReply

    row = db.get_or_404(QuickReply, reply_id)
    row.title = (request.form.get("title") or row.title).strip()
    row.body = (request.form.get("body") or row.body).strip()
    row.sort_order = request.form.get("sort_order", type=int) or row.sort_order
    row.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash(t("quick.updated"), "success")
    return redirect(url_for("messages.quick_replies"))


@messages_bp.route("/quick-replies/<int:reply_id>/delete", methods=["POST"])
@module_required(MODULE)
def quick_reply_delete(reply_id):
    from app.models import QuickReply

    db.session.delete(db.get_or_404(QuickReply, reply_id))
    db.session.commit()
    flash(t("quick.deleted"), "info")
    return redirect(url_for("messages.quick_replies"))


@messages_bp.route("/away-hours", methods=["POST"])
@module_required(MODULE)
def away_hours():
    """When the clinic answers, and what it says when it doesn't."""
    from app.utils.service_desk import (DEFAULT_OPEN_FROM, DEFAULT_OPEN_TO,
                                        DEFAULT_AWAY_BODY)

    days = [d for d in request.form.getlist("open_days") if d.isdigit()]
    Setting.set("wa_away_enabled", "1" if request.form.get("wa_away_enabled") else "0")
    Setting.set("wa_open_days", ",".join(days))
    Setting.set("wa_open_from",
                (request.form.get("open_from") or "").strip() or DEFAULT_OPEN_FROM)
    Setting.set("wa_open_to",
                (request.form.get("open_to") or "").strip() or DEFAULT_OPEN_TO)
    Setting.set("wa_away_body",
                (request.form.get("away_body") or "").strip() or DEFAULT_AWAY_BODY)
    db.session.commit()
    flash(t("settings.saved"), "success")
    return redirect(url_for("messages.quick_replies"))


@messages_bp.route("/inbox/<key>/link", methods=["POST"])
@module_required(MODULE)
def inbox_link(key):
    """Say who an unknown number belongs to.

    A number the system couldn't match is a person reception usually knows on
    sight — a grandmother, a driver, a second line. Naming them once moves the
    whole conversation onto the patient's file and keeps every later message
    there too."""
    from app.utils.inbox import link_phone_to_patient

    patient = db.session.get(Patient, request.form.get("patient_id", type=int))
    if patient is None:
        flash(t("inbox.link_pick"), "warning")
        return redirect(url_for("messages.inbox_thread", key=key))
    moved = link_phone_to_patient(key, patient)
    if not moved:
        flash(t("inbox.link_none"), "warning")
        return redirect(url_for("messages.inbox_thread", key=key))
    db.session.commit()
    flash(t("inbox.linked", name=patient.display_name(getattr(g, "lang", "ar")),
            n=moved), "success")
    return redirect(url_for("messages.inbox_thread", key=f"p{patient.id}"))


@messages_bp.route("/inbox/<key>/send", methods=["POST"])
@module_required(MODULE)
def inbox_send(key):
    """Reply inside a conversation via the active provider."""
    body = (request.form.get("body") or "").strip()
    if not body:
        return redirect(url_for("messages.inbox_thread", key=key))
    phone, patient_id = _thread_phone(key)
    if not phone:
        flash(t("inbox.no_phone"), "danger")
        return redirect(url_for("messages.inbox_thread", key=key))
    log = wa.send(body, phone, patient_id=patient_id, user_id=current_user.id)
    db.session.commit()
    if log.link:  # web provider: open the wa.me link for the user to hit send
        return redirect(log.link)
    flash(t("inbox.sent"), "success")
    return redirect(url_for("messages.inbox_thread", key=key))


def _thread_phone(key):
    """The number this conversation reaches, and the patient it belongs to."""
    last = _thread_query(key).order_by(MessageLog.created_at.desc()).first()
    if last is not None:
        return (last.to_phone or (last.patient.contact_phone if last.patient
                                  else None)), last.patient_id
    # A conversation the clinic is starting: no messages yet, so the number
    # comes from the patient's own file.
    if key.startswith("p") and key[1:].isdigit():
        patient = db.session.get(Patient, int(key[1:]))
        if patient is not None:
            return patient.contact_phone, patient.id
    return None, None


@messages_bp.route("/inbox/<key>/template-send", methods=["POST"])
@module_required(MODULE)
def inbox_template_send(key):
    """Reply with a Meta-approved template once the free window has shut.

    After 24 hours WhatsApp refuses free text. Before this, an old conversation
    was a dead end — the result is ready, the mother wrote two days ago, and
    the program had nothing to offer but a warning.
    """
    from app.utils import wa_templates

    tpl = wa_templates.find((request.form.get("name") or "").strip().lower())
    if tpl is None:
        flash(t("inbox.tpl_unknown"), "warning")
        return redirect(url_for("messages.inbox_thread", key=key))
    values = [(request.form.get(f"p{i}") or "").strip()
              for i in range(1, tpl["params"] + 1)]
    # Meta rejects a template with a blank parameter, and a family reading
    # "نتيجة  جاهزة" would be worse than the rejection. Catch it here, where
    # there is still a form to fix it in.
    if any(not v for v in values):
        flash(t("inbox.tpl_missing_param"), "warning")
        return redirect(url_for("messages.inbox_thread", key=key))

    phone, patient_id = _thread_phone(key)
    if not phone:
        flash(t("inbox.no_phone"), "danger")
        return redirect(url_for("messages.inbox_thread", key=key))
    log = wa.send_approved(tpl, values, phone, patient_id=patient_id,
                           user_id=current_user.id)
    db.session.commit()
    if log.status == "sent":
        flash(t("inbox.tpl_sent"), "success")
    else:
        flash(t("inbox.tpl_failed").replace("{err}", log.error or "—"), "danger")
    return redirect(url_for("messages.inbox_thread", key=key))


@messages_bp.route("/inbox/start/<int:patient_id>")
@module_required(MODULE)
def inbox_start(patient_id):
    """Open a conversation with a patient who hasn't written to us.

    The inbox could only ever show threads the patient started, so reaching a
    family first meant leaving the program. This opens their thread — empty if
    they've never written — with the reply box ready."""
    patient = db.get_or_404(Patient, patient_id)
    key = f"p{patient.id}"
    if _thread_query(key).first() is not None:
        return redirect(url_for("messages.inbox_thread", key=key))
    if not patient.contact_phone:
        flash(t("inbox.no_phone"), "danger")
        return redirect(url_for("patients.view", patient_id=patient.id))
    from app.utils.inbox import conversation_for, session_window
    conversation_for(key)
    db.session.commit()
    window = session_window(key)
    return render_template(
        "messages/thread.html", msgs=[], key=key, patient=patient,
        phone=patient.contact_phone, waits={}, pending=False,
        record=None, resolved=False, staff=_desk_staff(),
        # They have never written, so there is no open reply window — say so
        # before someone types a paragraph that can't be delivered.
        window=window, opted_out=bool(patient.wa_opt_out),
        approved=_approved_for(window),
        canned=[{"title": q.title,
                 "body": _render_canned(q.body, patient)} for q in _canned()],
        ai_ready=False)


def _canned():
    from app.utils.service_desk import quick_replies

    return quick_replies()


def _render_canned(body, patient):
    from app.utils.service_desk import render_reply

    return render_reply(body, patient, getattr(g, "lang", "ar"))


@messages_bp.route("/satisfaction")
@module_required(MODULE)
def satisfaction():
    """Patient-satisfaction analytics: CSAT/NPS, distribution, doctor board."""
    from app.utils.feedback import clinic_summary, doctor_ratings

    summary = clinic_summary()
    ratings = doctor_ratings()
    docs = ({u.id: u for u in User.query.filter(User.id.in_(ratings.keys())).all()}
            if ratings else {})
    leaderboard = sorted(
        ({"doctor": docs[d], "avg": v["avg"], "count": v["count"]}
         for d, v in ratings.items() if d in docs),
        key=lambda x: (-x["avg"], -x["count"]))
    return render_template("messages/satisfaction.html", s=summary,
                           leaderboard=leaderboard)


@messages_bp.route("/survey", methods=["GET", "POST"])
@admin_required
def survey_builder():
    """Customise the public satisfaction survey: reword or hide each built-in
    question and edit the intro / thank-you text, per language. Stored in
    Settings; the data columns stay fixed so analytics are unaffected."""
    from app.utils.feedback import SURVEY_QUESTIONS

    langs = ("ar", "en")
    if request.method == "POST":
        for q in SURVEY_QUESTIONS:
            Setting.set(f"survey_show_{q}", "1" if request.form.get(f"show_{q}") else "0")
            for lang in langs:
                Setting.set(f"survey_q_{q}_{lang}",
                            (request.form.get(f"q_{q}_{lang}") or "").strip())
        for base in ("survey_intro", "survey_thanks"):
            for lang in langs:
                Setting.set(f"{base}_{lang}",
                            (request.form.get(f"{base}_{lang}") or "").strip())
        # Delivery: built-in page link / external form (Google Form) / inline
        # questions answered by replying on WhatsApp.
        mode = (request.form.get("survey_mode") or "link").strip()
        Setting.set("survey_mode",
                    mode if mode in ("link", "external", "inline") else "link")
        Setting.set("survey_external_url",
                    (request.form.get("survey_external_url") or "").strip())
        db.session.commit()
        flash(t("survey.saved"), "success")
        return redirect(url_for("messages.survey_builder"))

    from app.utils.feedback import survey_config
    return render_template(
        "messages/survey_builder.html",
        cfg={lang: survey_config(lang) for lang in langs},
        questions=SURVEY_QUESTIONS,
        values={s.key: s.value for s in Setting.query.filter(
            Setting.key.like("survey_%")).all()})


@messages_bp.route("/send-due", methods=["POST"])
@module_required(MODULE)
def send_due():
    """Dispatch every scheduled message whose time has come."""
    res = wa.dispatch_due()
    if res["sent"] or res["skipped"]:
        flash(t("crm.dispatched", n=res["sent"], skipped=res["skipped"]), "success")
    else:
        flash(t("crm.nothing_due"), "info")
    return redirect(request.referrer or url_for("messages.index"))


@messages_bp.route("/patient/<int:patient_id>/opt-toggle", methods=["POST"])
@module_required(MODULE)
def opt_toggle(patient_id):
    """Flip a patient's WhatsApp opt-out preference."""
    patient = db.get_or_404(Patient, patient_id)
    patient.wa_opt_out = not patient.wa_opt_out
    db.session.commit()
    flash(t("crm.opted_out") if patient.wa_opt_out else t("crm.opted_in"), "info")
    return redirect(request.referrer or url_for("messages.index"))


@messages_bp.route("/appointment/<int:appt_id>/confirm")
@module_required(MODULE)
def confirm_appointment(appt_id):
    appt = db.get_or_404(Appointment, appt_id)
    patient = appt.patient
    phone = patient.contact_phone if patient else None
    if not phone:
        flash(t("messages_mod.no_phone"), "warning")
        return redirect(request.referrer or url_for("appointments.index"))

    lang = getattr(g, "lang", "ar")
    body = _appt_confirm_body(appt, lang)
    log = wa.send(body, phone, patient_id=patient.id, appointment_id=appt.id,
                  user_id=current_user.id, template_type="appointment_confirm",
                  image_url=wa.template_image("appointment_confirm"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=appt)


def _parse_day():
    raw = (request.args.get("date") or request.form.get("date") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return local_today()


@messages_bp.route("/roster")
@module_required(MODULE)
def roster():
    on_date = _parse_day()
    doctor_id = request.args.get("doctor_id", type=int)
    doctors = User.query.filter_by(role="doctor", is_active=True).order_by(User.full_name).all()
    doctor = db.session.get(User, doctor_id) if doctor_id else None

    rows = []
    if doctor is not None:
        for idx, appt in enumerate(_day_appointments(doctor.id, on_date), start=1):
            rows.append({"appt": appt, "queue": idx,
                         "phone": appt.patient.contact_phone if appt.patient else None})
    return render_template(
        "messages/roster.html", doctors=doctors, doctor=doctor,
        on_date=on_date, rows=rows,
        queue_mode=Setting.get("queue_mode", "number"),
    )


@messages_bp.route("/roster/doctor", methods=["POST"])
@module_required(MODULE)
def roster_doctor():
    on_date = _parse_day()
    doctor = db.get_or_404(User, request.form.get("doctor_id", type=int))
    if not doctor.phone:
        flash(t("messages_mod.no_doctor_phone"), "warning")
        return redirect(url_for("messages.roster", doctor_id=doctor.id, date=on_date))

    lang = getattr(g, "lang", "ar")
    appts = _day_appointments(doctor.id, on_date)
    lines = "\n".join(
        f"{i}) {a.time_label} - {a.patient.display_name(lang) if a.patient else ''}"
        for i, a in enumerate(appts, start=1)
    )
    body = wa.render(wa.template_body("doctor_schedule"), {
        "doctor": doctor.display_name(lang),
        "date": on_date.strftime("%Y-%m-%d"),
        "count": len(appts),
        "list": lines,
    })
    log = wa.send(body, doctor.phone, user_id=current_user.id,
                  template_type="doctor_schedule",
                  image_url=wa.template_image("doctor_schedule"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None)


def _parse_schedule():
    """Optional ``schedule_at`` datetime-local from the form (future only)."""
    raw = (request.form.get("schedule_at") or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            when = datetime.strptime(raw, fmt)
            return when if when > datetime.utcnow() else None
        except ValueError:
            continue
    return None


@messages_bp.route("/roster/notify", methods=["POST"])
@module_required(MODULE)
def roster_notify():
    on_date = _parse_day()
    doctor = db.get_or_404(User, request.form.get("doctor_id", type=int))
    lang = getattr(g, "lang", "ar")
    schedule_at = _parse_schedule()

    results = []
    for idx, appt in enumerate(_day_appointments(doctor.id, on_date), start=1):
        phone = appt.patient.contact_phone if appt.patient else None
        if not phone:
            results.append({"appt": appt, "log": None})
            continue
        mode = Setting.get("queue_mode", "number")
        queue = idx if mode == "number" else appt.time_label
        body = _appt_confirm_body(appt, lang, queue=queue)
        log = wa.send(body, phone, patient_id=appt.patient_id,
                      appointment_id=appt.id, user_id=current_user.id,
                      template_type="appointment_confirm",
                      image_url=wa.template_image("appointment_confirm"),
                      scheduled_at=schedule_at)
        results.append({"appt": appt, "log": log})
    db.session.commit()
    return render_template("messages/notify_result.html", results=results,
                           doctor=doctor, on_date=on_date, scheduled=schedule_at)


# =======================================================================
# CRM — occasions & birthdays
# =======================================================================
def _parse_form_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _upcoming_birthdays(days=7):
    """Active patients whose birthday falls within the next ``days`` days."""
    today = date.today()
    rows = []
    for p in Patient.query.filter_by(is_active=True).all():
        if not p.date_of_birth:
            continue
        dob = p.date_of_birth
        # This year's birthday (handle Feb 29 -> Feb 28).
        try:
            nb = dob.replace(year=today.year)
        except ValueError:
            nb = dob.replace(year=today.year, day=28)
        if nb < today:
            try:
                nb = dob.replace(year=today.year + 1)
            except ValueError:
                nb = dob.replace(year=today.year + 1, day=28)
        delta = (nb - today).days
        if 0 <= delta <= days:
            rows.append({"patient": p, "in_days": delta, "date": nb,
                         "turning": nb.year - dob.year,
                         "phone": p.contact_phone})
    return sorted(rows, key=lambda r: r["in_days"])


@messages_bp.route("/occasions")
@module_required(MODULE)
def occasions():
    """The unified Patient Customer Service (CRM) hub.

    One place for: the WhatsApp connection, the canonical per-type
    notification templates (body + image + auto/manual), free-form occasion
    templates, and upcoming birthdays.
    """
    # Make sure the canonical rows exist even before an upgrade-db has run.
    wa.seed_system_templates()

    system_rows = {
        r.occasion: r for r in
        MessageTemplate.query.filter_by(is_system=True).all()
    }
    system_templates = [system_rows[tp] for tp in AUTOMATION_TYPES
                        if tp in system_rows]
    custom_templates = (MessageTemplate.query
                        .filter_by(is_system=False)
                        .order_by(MessageTemplate.occasion, MessageTemplate.name)
                        .all())
    values = {row.key: row.value for row in Setting.query.all()}
    # Campaign roll-up per dated template (sent / pending / over how many days).
    from app.utils.occasions import campaign_report
    campaigns = {tpl.id: campaign_report(tpl)
                 for tpl in custom_templates if tpl.occasion_date or tpl.last_enqueued_on}
    from app.utils import wa_preview, wa_templates
    clinic = values.get("clinic_name_ar") or values.get("clinic_name") or ""
    return render_template(
        "messages/occasions.html",
        wa_samples=wa_preview.samples(clinic),
        approved_templates=wa_templates.parse(
            values.get("wa_approved_templates", "")),
        birthdays=_upcoming_birthdays(),
        system_templates=system_templates,
        custom_templates=custom_templates,
        occasion_types=OCCASION_TYPES,
        template_variables=TEMPLATE_VARIABLES,
        send_modes=SEND_MODES,
        values=values,
        campaigns=campaigns,
        today=date.today(),
        crm_mode=values.get("crm_mode", "manual"),
    )


@messages_bp.route("/occasions/template/<int:tpl_id>/enqueue", methods=["POST"])
@module_required(MODULE)
def occasion_enqueue_now(tpl_id):
    """Queue this occasion's campaign now (same throttled pipeline — the daily
    cap still paces the actual sending over the coming days)."""
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    tpl.last_enqueued_on = None                 # force a fresh campaign run
    from app.utils.occasions import enqueue_occasion
    n = enqueue_occasion(tpl, user_id=current_user.id, on_date=date.today())
    db.session.commit()
    flash(t("occasions.campaign_queued").replace("{n}", str(n)), "success")
    return redirect(url_for("messages.occasions") + "#custom")


@messages_bp.route("/connection", methods=["POST"])
@admin_required
def connection_save():
    """Save the WhatsApp connection / delivery configuration from the hub."""
    import secrets

    for key in WA_CONFIG_KEYS:
        Setting.set(key, (request.form.get(key) or "").strip())
    for key in WA_TOGGLE_KEYS:
        Setting.set(key, "1" if request.form.get(key) else "0")
    # Regenerate or first-time-create the inbound webhook secret on demand.
    if request.form.get("regen_secret") or not Setting.get("wa_webhook_secret", ""):
        Setting.set("wa_webhook_secret", secrets.token_urlsafe(24))
    db.session.commit()
    flash(t("settings.saved"), "success")
    return redirect(url_for("messages.occasions") + "#connection")


@messages_bp.route("/type/<int:tpl_id>/save", methods=["POST"])
@module_required(MODULE)
def system_template_save(tpl_id):
    """Edit a canonical notification type: body, image, auto/manual, on/off."""
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    tpl.body = (request.form.get("body") or "").strip()
    mode = (request.form.get("send_mode") or tpl.send_mode).strip()
    tpl.send_mode = mode if mode in SEND_MODES else tpl.send_mode
    tpl.is_active = bool(request.form.get("is_active"))
    # Per-template scheduling: delay after the trigger + fixed hour of day.
    tpl.delay_days = max(0, request.form.get("delay_days", type=int) or 0)
    tpl.delay_hours = max(0, request.form.get("delay_hours", type=int) or 0)
    sh = request.form.get("send_hour", type=int)
    tpl.send_hour = max(0, min(23, sh)) if sh is not None else None

    if request.form.get("remove_image"):
        _remove_crm_image(tpl.image_url)
        tpl.image_url = None
    new_img = _save_crm_image(request.files.get("image"))
    if new_img:
        _remove_crm_image(tpl.image_url)
        tpl.image_url = new_img

    db.session.commit()
    flash(t("crm.type_saved"), "success")
    return redirect(url_for("messages.occasions") + "#types")


@messages_bp.route("/type/<int:tpl_id>/test-send", methods=["POST"])
@module_required(MODULE)
def template_test_send(tpl_id):
    """Send this template to one number before it goes to everybody.

    The automatic replies go out unread — a template with a mistake in it
    reaches fifty families before anyone notices, and every one of those is a
    message the clinic cannot take back. One send to the receptionist's own
    phone catches it while it still costs nothing.

    What is sent is the body **as it stands in the editor**, not the saved one:
    testing the previous version and then saving a different one is exactly the
    mistake this is meant to prevent. The image, though, is the saved one — an
    unpicked file has never left the browser.
    """
    from app.utils import wa_preview

    tpl = db.get_or_404(MessageTemplate, tpl_id)
    phone = (request.form.get("phone") or "").strip()
    if not phone:
        flash(t("crm.test_no_phone"), "warning")
        return redirect(url_for("messages.occasions") + "#types")

    body = (request.form.get("body") or "").strip() or tpl.body
    clinic = Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""
    filled = wa_preview.fill(body, wa_preview.samples(clinic))
    # Tagged "test" rather than with the type's own name, which does two
    # things: the delivery report doesn't count it as a birthday greeting that
    # reached a family, and the send goes by whatever the clinic has actually
    # configured instead of the type's auto/manual preference. A test that
    # quietly becomes a link because the type is set to manual has tested
    # nothing.
    log = wa.send(filled, phone, user_id=current_user.id,
                  image_url=tpl.image_url, template_type="test",
                  ignore_window=True)
    db.session.commit()
    if log.link:  # click-to-send: hand the staff member the ready message
        return redirect(log.link)
    if log.status == "sent":
        flash(t("crm.test_sent").replace("{phone}", log.to_phone or phone),
              "success")
    else:
        flash(t("crm.test_failed").replace("{err}", log.error or "—"), "danger")
    return redirect(url_for("messages.occasions") + "#types")


@messages_bp.route("/occasions/birthday/<int:patient_id>")
@module_required(MODULE)
def send_birthday(patient_id):
    patient = db.get_or_404(Patient, patient_id)
    phone = patient.contact_phone
    if not phone:
        flash(t("messages_mod.no_phone"), "warning")
        return redirect(url_for("messages.occasions"))

    lang = getattr(g, "lang", "ar")
    body = wa.render(wa.template_body("birthday"), {
        "patient": patient.display_name(lang),
        "clinic": Setting.get("clinic_name_ar") or Setting.get("clinic_name") or "",
    })
    from app.models.message import _template_schedule
    btpl = wa.template_for("birthday")
    schedule_at = _template_schedule(btpl) if btpl is not None else None
    log = wa.send(body, phone, patient_id=patient.id, user_id=current_user.id,
                  template_type="birthday", scheduled_at=schedule_at,
                  image_url=wa.template_image("birthday"))
    db.session.commit()
    return render_template("messages/sent.html", log=log, appt=None)


@messages_bp.route("/occasions/template/new", methods=["POST"])
@module_required(MODULE)
def occasion_template_new():
    name = (request.form.get("name") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not name or not body:
        flash(t("common.required") + ": " + t("occasions.name"), "danger")
        return redirect(url_for("messages.occasions"))
    occ = (request.form.get("occasion") or "custom").strip()
    repeat = (request.form.get("repeat_rule") or "once").strip()
    db.session.add(MessageTemplate(
        name=name, body=body,
        occasion=occ if occ in OCCASION_TYPES else "custom",
        occasion_date=_parse_form_date("occasion_date"),
        repeat_rule=repeat if repeat in ("once", "yearly") else "once",
        image_url=_save_crm_image(request.files.get("image")),
    ))
    db.session.commit()
    flash(t("occasions.tpl_added"), "success")
    return redirect(url_for("messages.occasions") + "#custom")


@messages_bp.route("/occasions/template/<int:tpl_id>/edit", methods=["POST"])
@module_required(MODULE)
def occasion_template_edit(tpl_id):
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    tpl.name = (request.form.get("name") or tpl.name).strip()
    tpl.body = (request.form.get("body") or tpl.body).strip()
    occ = (request.form.get("occasion") or tpl.occasion).strip()
    tpl.occasion = occ if occ in OCCASION_TYPES else tpl.occasion
    new_date = _parse_form_date("occasion_date")
    if new_date != tpl.occasion_date:
        tpl.occasion_date = new_date
        tpl.last_enqueued_on = None   # a new date is a new campaign
    repeat = (request.form.get("repeat_rule") or tpl.repeat_rule).strip()
    tpl.repeat_rule = repeat if repeat in ("once", "yearly") else tpl.repeat_rule
    tpl.is_active = bool(request.form.get("is_active"))
    if request.form.get("remove_image"):
        _remove_crm_image(tpl.image_url)
        tpl.image_url = None
    new_img = _save_crm_image(request.files.get("image"))
    if new_img:
        _remove_crm_image(tpl.image_url)
        tpl.image_url = new_img
    db.session.commit()
    flash(t("occasions.tpl_updated"), "success")
    return redirect(url_for("messages.occasions") + "#custom")


@messages_bp.route("/occasions/template/<int:tpl_id>/delete", methods=["POST"])
@module_required(MODULE)
def occasion_template_delete(tpl_id):
    tpl = db.get_or_404(MessageTemplate, tpl_id)
    if tpl.is_system:  # canonical rows are managed, never deleted
        flash(t("crm.cant_delete_system"), "warning")
        return redirect(url_for("messages.occasions") + "#types")
    _remove_crm_image(tpl.image_url)
    db.session.delete(tpl)
    db.session.commit()
    flash(t("occasions.tpl_deleted"), "info")
    return redirect(url_for("messages.occasions") + "#custom")
