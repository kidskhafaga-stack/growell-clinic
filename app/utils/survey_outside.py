"""The survey page outside the clinic, and the program's side of it.

Asked as: *«أرفع جزء التقييمات على Vercel وأعمل حفظ على داتا بيز خارجية وأعمل
سينك مع البرنامج — أحسن ما أخرّج كل البرنامج على النت»*. The program stays
on the clinic's own network; one small page (``outside/survey``) lives on the
internet, and this is the only thing that talks to it.

**What leaves the clinic, and nothing else:** the clinic's name, logo, colour
and thank-you words; and per survey its random code, the unit's name and the
questions. No child's name, no phone number, no doctor, no diagnosis.

**What comes back:** the family's answers, which are then judged here by the
same rules as the clinic's own page (``survey_flow.save``) — so the page
outside can never add what the rules refuse — and **deleted outside** once
they are in.

**The keys are not in the program's database or its code.** ``clinic.env``
holds the page's address and the key the page knows the program by:

    SURVEY_PAGE_URL=https://<the page>.vercel.app
    SURVEY_SYNC_KEY=<a long random key, the same one set on Vercel>

Everything here is best-effort and silent to families: a survey that could
not be sent out stays waiting and goes on the next try.
"""
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from app.extensions import db

ENV_URL = "SURVEY_PAGE_URL"
ENV_KEY = "SURVEY_SYNC_KEY"
MIN_KEY = 24
TIMEOUT = 15
#: How long a family has to answer, on the page outside.
DAYS = 30
#: A logo bigger than this is not sent — the page shows the initial instead.
MAX_LOGO = 300 * 1024


def base_url():
    url = (os.environ.get(ENV_URL) or "").strip().rstrip("/")
    return url if url.startswith("https://") else None


def key():
    value = (os.environ.get(ENV_KEY) or "").strip()
    return value if len(value) >= MIN_KEY else None


def configured():
    return bool(base_url() and key())


def link(token):
    return f"{base_url()}/?t={token}"


# ---------------------------------------------------------------- the wire
def _call(action, payload=None):
    """POST ``{action, ...}`` to the page's sync function. Returns the JSON
    reply, or raises. TLS is verified as it is everywhere else."""
    body = json.dumps({"action": action, **(payload or {})}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url()}/api/sync", data=body, method="POST",
        headers={"Content-Type": "application/json", "x-clinic-key": key()})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8") or "{}")
    if not data.get("ok"):
        raise RuntimeError(f"{action}_refused")
    return data


# ------------------------------------------------------------- what leaves
def brand(lang="ar"):
    """The clinic as the page shows it."""
    from flask import current_app

    from app.models import Setting
    from app.utils.feedback import survey_config

    out = {"name": (Setting.get("clinic_name_ar") if lang == "ar" else None)
           or Setting.get("clinic_name") or "",
           "thanks": survey_config(lang)["thanks"],
           "review_url": (Setting.get("survey_review_url") or "").strip(),
           "colour": (Setting.get("clinic_accent") or "").strip()}
    logo = Setting.get("clinic_logo") or ""
    if logo:
        path = os.path.join(current_app.static_folder, "uploads", "clinic",
                            os.path.basename(logo))
        mime = mimetypes.guess_type(path)[0] or ""
        if (mime in ("image/png", "image/jpeg", "image/webp", "image/gif")
                and os.path.isfile(path) and os.path.getsize(path) <= MAX_LOGO):
            with open(path, "rb") as f:
                out["logo"] = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    return out


def _labels(lang):
    from app.i18n import t

    keys = ("next", "back", "yes", "no", "why_q", "nps_low", "nps_high",
            "thanks_title", "privacy", "care", "review")
    out = {k: t(f"feedback.{k}") for k in keys}
    out.update(send=t("feedback.submit"), sending=t("survey_out.sending"),
               failed=t("survey_out.failed"), already=t("survey_out.already"),
               missing=t("feedback.invalid"))
    return out


def config(fb, lang="ar"):
    """One survey as the page needs it — and nothing about the family."""
    from app.i18n import t
    from app.utils import survey_flow
    from app.utils.feedback import CONCERNS, survey_config

    steps = []
    for s in survey_flow.steps(fb, lang):
        step = {k: s[k] for k in ("key", "kind", "builtin", "label", "options",
                                  "branch_only", "jumps")}
        if s["builtin"] and s["key"] in CONCERNS:
            step["concerns"] = [{"value": f"{s['key']}:{c}",
                                 "label": t(f"feedback.c_{c}")}
                                for c in CONCERNS[s["key"]]]
        steps.append(step)
    unit = (fb.cost_centre.display_name(lang) if fb.cost_centre is not None
            else t("board_cs.outpatient"))
    return {"intro": survey_config(lang)["intro"], "unit": unit, "lang": lang,
            "dir": "rtl" if lang == "ar" else "ltr", "steps": steps,
            "labels": _labels(lang)}


# -------------------------------------------------------------- the moves
def push(rows=None, lang="ar"):
    """Send the waiting surveys (and the clinic's brand) out. Returns how
    many went. A survey that did not go stays waiting."""
    from app.models import Feedback

    if not configured():
        return 0
    if rows is None:
        since = datetime.utcnow() - timedelta(days=DAYS)
        rows = (Feedback.query.filter(Feedback.outside_state == "pending",
                                      Feedback.status == "sent",
                                      Feedback.created_at >= since)
                .order_by(Feedback.id).limit(200).all())
    if not rows:
        return 0
    reply = _call("push", {"brand": brand(lang), "surveys": [
        {"token": fb.token, "config": config(fb, lang), "days": DAYS}
        for fb in rows]})
    went = set(reply.get("pushed") or [])
    for fb in rows:
        if fb.token in went:
            fb.outside_state = "out"
    return len(went)


def _form(payload):
    """The page's answers as the form the clinic's own page would send."""
    from werkzeug.datastructures import MultiDict

    pairs = []
    for field, values in (payload or {}).items():
        for value in values if isinstance(values, list) else [values]:
            pairs.append((str(field), str(value)))
    return MultiDict(pairs)


def pull(lang="ar"):
    """Collect the answers waiting outside, judge them here, and have them
    deleted outside. Returns how many surveys were answered."""
    from app.models import Feedback
    from app.utils import survey_flow
    from app.utils.complaints import raise_from_feedback

    if not configured():
        return 0
    waiting = _call("pull").get("answers") or []
    taken, answered = [], 0
    for item in waiting:
        token = str(item.get("token") or "")
        taken.append(token)
        fb = Feedback.query.filter_by(token=token).first()
        if fb is None or fb.status == "submitted":
            continue
        survey_flow.save(fb, _form(item.get("payload")), lang)
        fb.status = "submitted"
        fb.submitted_at = datetime.utcnow()
        fb.outside_state = "answered"
        db.session.flush()
        raise_from_feedback(fb, lang)
        answered += 1
    # Kept here first; only then deleted there — a failure in between means
    # the same answers come again, and a survey already answered is skipped.
    db.session.commit()
    if taken:
        _call("done", {"tokens": taken})
    return answered


def sync(lang="ar"):
    """Push, then pull. Records when and whether it worked. Runs from a
    screen's heartbeat or from the command line — where there is no request,
    and the words the page is sent still have to be translated."""
    from contextlib import nullcontext

    from flask import current_app, has_request_context

    with (nullcontext() if has_request_context()
          else current_app.test_request_context()):
        return _sync(lang)


def _sync(lang):
    from app.models import Setting

    result = {"pushed": 0, "answered": 0, "error": None}
    try:
        result["pushed"] = push(lang=lang)
        db.session.commit()
        result["answered"] = pull(lang)
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
        db.session.rollback()
        result["error"] = type(exc).__name__
    Setting.set("survey_outside_last", datetime.utcnow().isoformat(timespec="seconds"))
    Setting.set("survey_outside_error", result["error"] or "")
    db.session.commit()
    return result


def maybe_sync(min_gap_minutes=10):
    """The same heartbeat that drains the message queue: at most every ten
    minutes, one process at a time, and never an error on the screen that
    happened to call it."""
    from app.models import Setting

    if not configured():
        return None
    try:
        now = datetime.utcnow()
        last = Setting._read("survey_outside_tick")
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(minutes=min_gap_minutes):
                    return None
            except ValueError:
                pass
        if not Setting.swap("survey_outside_tick", last, now.isoformat()):
            db.session.rollback()
            return None
        db.session.commit()
        return sync()
    except Exception:  # noqa: BLE001 — a heartbeat never breaks a screen
        db.session.rollback()
        return None
