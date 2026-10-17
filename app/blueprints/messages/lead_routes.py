"""Families who asked and have not come yet, and the channels they ask on
(``CONNECTHUB_PLAN.md``, stage one).

Work for the desk, so behind the module like the inbox; the channels screen
changes how the clinic is reached, so it needs ``messages_setup`` like the
WhatsApp connection does. Every rule lives in ``utils/leads`` and
``utils/channels``; these only read the form and say what happened.
"""
from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app.blueprints.messages import messages_bp
from app.extensions import db
from app.i18n import t
from app.models import Lead, MessageLog, Patient, User
from app.models.crm import LOST_REASONS, MANUAL_STAGES, SOURCE_KINDS
from app.utils import channels, leads
from app.utils.appointments import list_doctors, parse_date_arg
from app.utils.clock import local_today
from app.utils.decorators import (admin_required, capability_required,
                                  client_ip, module_required)

MODULE = "messages"


def _staff():
    rows = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return [u for u in rows if u.can_access(MODULE)]


def _identities(form):
    return {"phone": form.get("phone"), "email": form.get("email"),
            "instagram": form.get("instagram"),
            "messenger": form.get("messenger"), "tiktok": form.get("tiktok"),
            "telegram": form.get("telegram")}


def _lead_or_404(lead_id):
    return db.get_or_404(Lead, lead_id)


@messages_bp.route("/leads")
@module_required(MODULE)
def leads_board():
    """The families who asked: overdue follow-ups first, then the ones
    nobody has answered yet — and, below, where they came from."""
    stage = request.args.get("stage") or "open"
    channel = request.args.get("channel") or None
    mine = request.args.get("mine") == "1"
    due_only = request.args.get("due") == "1"
    days = request.args.get("days", 90, type=int)
    days = days if days in leads.REPORT_PERIODS else 90
    return render_template(
        "messages/leads.html",
        rows=leads.board(stage=stage, channel=channel,
                         owner_id=current_user.id if mine else None,
                         due_only=due_only),
        counts=leads.counts(), due=leads.due_count(), stage=stage,
        channel=channel, mine=mine, due_only=due_only,
        report=leads.report(days), days=days, periods=leads.REPORT_PERIODS,
        channels_on=channels.enabled(), all_channels=channels.CHANNELS,
        kinds=SOURCE_KINDS, staff=_staff(), doctors=list_doctors(),
        today=local_today())


@messages_bp.route("/leads", methods=["POST"])
@module_required(MODULE)
def lead_new():
    """Write down somebody who asked — on any channel, connected or not."""
    form = request.form
    try:
        lead, created = leads.open_lead(
            current_user, form.get("name"), _identities(form),
            form.get("channel") or "",
            source_kind=form.get("source_kind") or "message",
            campaign=form.get("campaign"), source_url=form.get("source_url"),
            doctor_id=form.get("doctor_id", type=int),
            interest=form.get("interest"), message=form.get("message"),
            owner_id=form.get("owner_id", type=int) or current_user.id,
            follow_up_on=parse_date_arg(form.get("follow_up_on"),
                                        default=None))
    except ValueError as exc:
        flash(t("leads.need_" + str(exc)), "danger")
        return redirect(url_for("messages.leads_board"))
    db.session.commit()
    flash(t("leads.opened" if created else "leads.already_open"),
          "success" if created else "info")
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


@messages_bp.route("/leads/<int:lead_id>")
@module_required(MODULE)
def lead_view(lead_id):
    lead = _lead_or_404(lead_id)
    return render_template(
        "messages/lead.html", lead=lead, contact=lead.contact,
        suggestions=leads.suggestions(lead.contact),
        stages=MANUAL_STAGES, reasons=LOST_REASONS, staff=_staff(),
        doctors=list_doctors(), all_channels=channels.CHANNELS,
        today=local_today())


@messages_bp.route("/leads/<int:lead_id>/stage", methods=["POST"])
@module_required(MODULE)
def lead_stage(lead_id):
    lead = _lead_or_404(lead_id)
    stage = request.form.get("stage")
    if leads.move(lead, stage, current_user,
                  reason=request.form.get("reason") or None,
                  note=request.form.get("note")) is None:
        flash(t("leads.need_reason" if stage == "lost"
                else "leads.not_moved"), "danger")
    else:
        db.session.commit()
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


@messages_bp.route("/leads/<int:lead_id>/work", methods=["POST"])
@module_required(MODULE)
def lead_work(lead_id):
    """Owner, follow-up day and a note — one form, each saved if it moved."""
    lead = _lead_or_404(lead_id)
    owner_id = request.form.get("owner_id", type=int)
    if owner_id != lead.owner_id:
        owner = db.session.get(User, owner_id) if owner_id else None
        if owner_id and (owner is None or not owner.can_access(MODULE)):
            abort(400)
        leads.assign(lead, owner, current_user)
    on = parse_date_arg(request.form.get("follow_up_on"), default=None)
    if on != lead.follow_up_on:
        leads.follow_up(lead, on, current_user)
    leads.note(lead, request.form.get("note"), current_user)
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


@messages_bp.route("/leads/<int:lead_id>/contact", methods=["POST"])
@module_required(MODULE)
def lead_contact(lead_id):
    """Add a way to reach them — the number a family on Instagram sent."""
    lead = _lead_or_404(lead_id)
    before = {(i.kind, i.value) for i in lead.contact.identities}
    other = leads.find_contact(_identities(request.form))
    leads.contact_for(lead.contact.name, _identities(request.form),
                      current_user)
    if other is not None and other.id != lead.contact_id:
        # The number is already somebody else's. Not moved: a person sorts
        # that out, the program does not decide it.
        flash(t("leads.identity_taken"), "danger")
    elif {(i.kind, i.value) for i in lead.contact.identities} != before:
        db.session.commit()
        flash(t("common.saved"), "success")
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


@messages_bp.route("/leads/<int:lead_id>/link", methods=["POST"])
@module_required(MODULE)
def lead_link(lead_id):
    """A person says whose family this is."""
    lead = _lead_or_404(lead_id)
    patient = db.session.get(Patient, request.form.get("patient_id", type=int)
                             or 0)
    if patient is None:
        flash(t("leads.pick_child"), "danger")
    else:
        leads.link_patient(lead.contact, patient, current_user,
                           ip_address=client_ip())
        db.session.commit()
        flash(t("leads.linked"), "success")
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


@messages_bp.route("/leads/<int:lead_id>/convert", methods=["POST"])
@module_required(MODULE)
def lead_convert(lead_id):
    """Make the booking request — the same queue and approval as any other.
    Nothing is sent to the family and nothing is booked here."""
    lead = _lead_or_404(lead_id)
    try:
        row = leads.convert(
            lead, current_user,
            doctor_id=request.form.get("doctor_id", type=int),
            wanted_date=parse_date_arg(request.form.get("wanted_date"),
                                       default=None),
            message=request.form.get("message"), ip_address=client_ip())
    except ValueError as exc:
        flash(t("leads.need_" + str(exc)), "danger")
        return redirect(url_for("messages.lead_view", lead_id=lead.id))
    db.session.commit()
    flash(t("leads.converted"), "success")
    return redirect(url_for("appointments.requests_page",
                            _anchor=f"request-{row.id}"))


@messages_bp.route("/inbox/<key>/lead", methods=["POST"])
@module_required(MODULE)
def inbox_lead(key):
    """From a WhatsApp conversation: the number, the child when the thread
    is on a file, and the conversation to go back to."""
    from app.utils import inbox as ibx

    rec = ibx.conversation_for(key, create=False)
    patient = None
    phone = None
    if key.startswith("p") and key[1:].isdigit():
        patient = db.session.get(Patient, int(key[1:]))
        last = (ibx.thread_query(key).filter_by(direction="in")
                .order_by(MessageLog.id.desc()).first())
        phone = (last.to_phone if last is not None
                 else (rec.phone if rec is not None else None))
    else:
        phone = key
    try:
        lead, created = leads.open_lead(
            current_user, request.form.get("name"), {"phone": phone},
            "whatsapp", source_kind="message",
            message=request.form.get("message"),
            owner_id=current_user.id, conversation_key=key, patient=patient)
    except ValueError as exc:
        flash(t("leads.need_" + str(exc)), "danger")
        return redirect(url_for("messages.inbox_thread", key=key))
    db.session.commit()
    flash(t("leads.opened" if created else "leads.already_open"),
          "success" if created else "info")
    return redirect(url_for("messages.lead_view", lead_id=lead.id))


# -------------------------------------------------------------- channels ---
@messages_bp.route("/channels", methods=["GET", "POST"])
@capability_required("messages_setup")
def channels_setup():
    """Which channels this clinic uses, how each one reaches the program,
    the public request page, and links that carry their campaign."""
    if request.method == "POST":
        channels.set_enabled(request.form.getlist("channel"))
        channels.set_page(request.form.get("page") == "on")
        db.session.commit()
        flash(t("common.saved"), "success")
        return redirect(url_for("messages.channels_setup"))
    tag = channels.campaign_tag(request.args.get("c") or "",
                                request.args.get("label") or "")
    doctor_id = request.args.get("doctor_id", type=int)
    link = None
    if tag or doctor_id:
        path = url_for("booking_page.form", src=tag or None,
                       doctor=doctor_id or None)
        base = channels.public_base()
        link = (base + path) if base else request.url_root.rstrip("/") + path
    from app.utils import social

    base = channels.public_base() or request.url_root.rstrip("/")
    meta = social.meta_config()
    return render_template(
        "messages/channels.html", all_channels=channels.CHANNELS,
        meta=meta, meta_ready=social.meta_ready(),
        tg_ready=social.telegram_ready(),
        has_page_token=bool(meta["token"]), has_app_secret=bool(meta["app_secret"]),
        has_tg_token=bool(social.telegram_config()["token"]),
        social_hook=base + url_for("webhooks.social_verify"),
        tg_hook=base + url_for("webhooks.telegram_receive"),
        tiktok=social.tiktok_config(), tt_ready=social.tiktok_ready(),
        mail=_mail_shown(), mail_ready=_mail_ready(),
        ig_mode=social.instagram_mode(), ig=_ig_shown(), ig_ready=social.instagram_ready(),
        ig_redirect=base + url_for("messages.channels_instagram_callback"),
        tt_hook=base + url_for("webhooks.tiktok_receive"),
        tt_redirect=base + url_for("messages.channels_tiktok_callback"),
        on=channels.enabled(), page_open=channels.page_open(),
        connection={k: channels.connection(k) for k in channels.CHANNELS},
        public_base=channels.public_base(), link=link, tag=tag,
        doctors=list_doctors(), doctor_id=doctor_id,
        lang=getattr(g, "lang", "ar"))


# Secrets the clinic types once. Left blank, a secret keeps the value it
# has — a form that re-shows a token is a form that leaks it.
_META_PLAIN = ("meta_page_id", "meta_graph_version", "tt_app_id", "tt_auth_url",
               "ig_app_id",
               "mail_imap_host", "mail_imap_port", "mail_smtp_host",
               "mail_smtp_port", "mail_user", "mail_address")
_SECRETS = ("meta_page_token", "meta_app_secret", "tg_bot_token",
            "tt_app_secret", "mail_password", "ig_app_secret")


@messages_bp.route("/channels/connect", methods=["POST"])
@admin_required
def channels_connect():
    """Save the clinic's own Meta Page app and Telegram bot (stage two).
    Admin only, like the WhatsApp connection: these are the keys to the
    clinic's accounts."""
    import secrets

    from app.models import Setting

    for key in _META_PLAIN:
        value = (request.form.get(key) or "").strip()[:600]
        if key.endswith("_port") and value and not value.isdigit():
            value = ""
        Setting.set(key, value)
    for key in _SECRETS:
        value = (request.form.get(key) or "").strip()
        if value:
            Setting.set(key, value[:500])
        elif request.form.get("clear_" + key):
            Setting.set(key, "")
    Setting.set("meta_human_agent", "1" if request.form.get("meta_human_agent") else "")
    Setting.set("ig_mode", "login" if request.form.get("ig_mode") == "login" else "page")
    # The verify token and Telegram's secret are made here, long and random —
    # never typed, so never guessable.
    if request.form.get("regen_meta") or not Setting.get("meta_verify_token"):
        Setting.set("meta_verify_token", secrets.token_urlsafe(24))
    if request.form.get("regen_tg") or not Setting.get("tg_webhook_secret"):
        Setting.set("tg_webhook_secret", secrets.token_urlsafe(24))
    db.session.commit()
    flash(t("common.saved"), "success")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


@messages_bp.route("/channels/telegram-hook", methods=["POST"])
@admin_required
def channels_telegram_hook():
    """Tell Telegram where the clinic's webhook is, with its secret — one
    press instead of a URL typed by hand. The address must be the clinic's
    public one: Telegram calls it from the internet."""
    from app.utils import social

    base = channels.public_base()
    if not base:
        flash(t("channels.no_public_base"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    try:
        ok, said = social.telegram_set_webhook(
            base + url_for("webhooks.telegram_receive"))
    except social.SendRefused:
        flash(t("social.refused_not_ready"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    flash(t("social.tg_hook_ok") if ok else t("social.failed", err=said or "—"),
          "success" if ok else "danger")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


# ------------------------------------------------------------- TikTok ---
# The business authorizes the developer app on TikTok (OAuth), and TikTok
# sends it back here with a one-time code (valid ten minutes) that is traded
# for the account's tokens. A ``state`` kept in the session is checked on
# the way back, as TikTok's guide recommends against forged callbacks.
@messages_bp.route("/channels/tiktok/start")
@admin_required
def channels_tiktok_start():
    import secrets

    from flask import session

    from app.utils import social

    cfg = social.tiktok_config()
    if not (cfg["auth_url"] and cfg["app_id"] and cfg["secret"]):
        flash(t("social.refused_not_ready"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    state = secrets.token_urlsafe(24)
    session["tt_oauth_state"] = state
    sep = "&" if "?" in cfg["auth_url"] else "?"
    return redirect(f"{cfg['auth_url']}{sep}state={state}&disable_auto_auth=1")


@messages_bp.route("/channels/tiktok/callback")
@admin_required
def channels_tiktok_callback():
    import hmac as _hmac

    from flask import session

    from app.utils import social

    expected = session.pop("tt_oauth_state", None)
    given = request.args.get("state") or ""
    code = request.args.get("code") or ""
    if not expected or not _hmac.compare_digest(expected, given) or not code:
        flash(t("social.tt_state_bad"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    base = channels.public_base() or request.url_root.rstrip("/")
    try:
        ok, said = social.tiktok_exchange_code(
            code, base + url_for("messages.channels_tiktok_callback"))
    except social.SendRefused:
        ok, said = False, ""
    db.session.commit()
    flash(t("social.tt_connected") if ok else t("social.failed", err=said or "—"),
          "success" if ok else "danger")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


@messages_bp.route("/channels/tiktok/subscribe", methods=["POST"])
@admin_required
def channels_tiktok_subscribe():
    """Point the developer app's direct-message webhook at this clinic."""
    from app.utils import social

    base = channels.public_base()
    if not base:
        flash(t("channels.no_public_base"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    try:
        ok, said = social.tiktok_subscribe(base + url_for("webhooks.tiktok_receive"))
    except social.SendRefused:
        ok, said = False, ""
    flash(t("social.tt_subscribed") if ok else t("social.failed", err=said or "—"),
          "success" if ok else "danger")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


# ---------------------------------------------------------------- mail ---
def _mail_shown():
    from app.utils import mail_channel

    cfg = mail_channel.config()
    cfg["has_password"] = bool(cfg.pop("password"))
    return cfg


def _mail_ready():
    from app.utils import mail_channel

    return mail_channel.ready()


@messages_bp.route("/channels/mail-check", methods=["POST"])
@capability_required("messages_setup")
def channels_mail_check():
    """Read the clinic's mailbox now, rather than at the next heartbeat."""
    from app.utils import mail_channel

    filed, error = mail_channel.poll()
    if error:
        flash(t("social.failed", err=error), "danger")
    else:
        flash(t("social.mail_checked", n=filed), "success")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


# -------------------------------------------- Instagram with Instagram Login ---
# An Instagram professional account with no Facebook Page connects through
# Business Login for Instagram: the code comes back here (valid one hour,
# ``#_`` stripped), becomes a 60-day token, and the account then turns its
# webhooks on. The ``state`` is checked on the way back, as for TikTok.
def _ig_shown():
    from app.utils import social

    cfg = social.ig_login_config()
    return {"app_id": cfg["app_id"], "has_secret": bool(cfg["app_secret"]),
            "user_id": cfg["user_id"], "until": cfg["until"][:10]}


@messages_bp.route("/channels/instagram/start")
@admin_required
def channels_instagram_start():
    import secrets

    from flask import session

    from app.utils import social

    cfg = social.ig_login_config()
    if not (cfg["app_id"] and cfg["app_secret"]):
        flash(t("social.refused_not_ready"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    state = secrets.token_urlsafe(24)
    session["ig_oauth_state"] = state
    base = channels.public_base() or request.url_root.rstrip("/")
    return redirect(social.instagram_authorize_url(
        base + url_for("messages.channels_instagram_callback"), state))


@messages_bp.route("/channels/instagram/callback")
@admin_required
def channels_instagram_callback():
    import hmac as _hmac

    from flask import session

    from app.utils import social

    expected = session.pop("ig_oauth_state", None)
    given = request.args.get("state") or ""
    if request.args.get("error"):
        flash(t("social.ig_denied"), "warning")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    code = request.args.get("code") or ""
    if not expected or not _hmac.compare_digest(expected, given) or not code:
        flash(t("social.tt_state_bad"), "danger")
        return redirect(url_for("messages.channels_setup", _anchor="connect"))
    base = channels.public_base() or request.url_root.rstrip("/")
    try:
        ok, said = social.instagram_exchange_code(
            code, base + url_for("messages.channels_instagram_callback"))
    except social.SendRefused:
        ok, said = False, ""
    db.session.commit()
    flash(t("social.ig_connected") if ok else t("social.failed", err=said or "—"),
          "success" if ok else "danger")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))


@messages_bp.route("/channels/instagram/subscribe", methods=["POST"])
@admin_required
def channels_instagram_subscribe():
    from app.utils import social

    try:
        ok, said = social.instagram_subscribe()
    except social.SendRefused:
        ok, said = False, ""
    db.session.commit()
    flash(t("social.tt_subscribed") if ok else t("social.failed", err=said or "—"),
          "success" if ok else "danger")
    return redirect(url_for("messages.channels_setup", _anchor="connect"))
