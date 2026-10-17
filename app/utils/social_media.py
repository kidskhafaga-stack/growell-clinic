"""The photo of the X-ray a family sends on Messenger, Instagram, Telegram or
TikTok — kept, not left as a link that stops working.

Each platform hands over a file differently, and each says so in its own
documentation:

* **Meta** sends a CDN URL in ``attachments[].payload.url`` that expires —
  it has to be fetched soon after it arrives;
* **Telegram** sends a ``file_id``: ``getFile`` gives a ``file_path`` valid
  for at least an hour, fetched from ``/file/bot<token>/<file_path>``, files
  up to 20 MB;
* **TikTok** sends a ``media_id``: ``/business/message/media/download/``
  (with the conversation and message ids) gives a ``download_url`` valid for
  24 hours, fetched with the header ``x-user: <access token>``.

Meta wants the webhook answered within five seconds, so a file is never
fetched inside it. The message is filed with its file **queued** on it
(``media_pending``); the queue is worked straight after the platform has
had its answer (``after_response``). Then the same rules as WhatsApp's
(``wa_media``): the size capped, the type decided by us from the declared
type, only images and PDFs kept, and filed on a child's record only when a
person has already linked the sender to that child.
"""
import json

from app.extensions import db
from app.models import MessageLog
from app.utils import social, wa_media

PENDING = "media_pending"
#: How many queued files one pass works through.
BATCH = 10
TIMEOUT = 20
#: Telegram does not say a type for photos; its paths end in one.
_EXT_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
             "webp": "image/webp", "gif": "image/gif", "pdf": "application/pdf"}
#: The attachment types worth fetching: a picture or a document.
_WANTED = {"image", "file", "photo", "document"}


def queue(log, item):
    """Remember the files a message carried, to fetch after the answer."""
    wanted = [[kind, ref] for kind, ref in item.media if kind in _WANTED and ref]
    if not wanted or log is None:
        return False
    # TikTok's ids are filed as ``tt:<id>``; its download asks for the bare id.
    raw_mid = item.msg_id[3:] if item.msg_id.startswith("tt:") else item.msg_id
    log.link = json.dumps({"m": wanted, "conv": item.conversation, "mid": raw_mid})
    log.error = PENDING
    return True


def _get(url, headers=None):
    """Fetch a URL with the size cap → ``(bytes, mime)`` or ``(None, why)``."""
    try:
        import requests
    except ImportError:                      # pragma: no cover
        return None, "requests_missing"
    try:
        resp = requests.get(url, headers=headers or {}, timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            return None, f"download_{resp.status_code}"
        data = wa_media._read_capped(resp)
        if data is None:
            return None, "too_big"
        return data, (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except Exception as exc:                 # noqa: BLE001
        return None, f"error:{type(exc).__name__}"


def _telegram(file_id):
    cfg = social.telegram_config()
    _, raw = social._post(f"{social.TELEGRAM}/bot{cfg['token']}/getFile",
                          {"file_id": file_id})
    try:
        path = (json.loads(raw or "{}").get("result") or {}).get("file_path")
    except ValueError:
        path = None
    if not path:
        return None, "no_file_path"
    data, mime = _get(f"{social.TELEGRAM}/file/bot{cfg['token']}/{path}")
    if data is not None and mime not in wa_media.MIME_EXT:
        mime = _EXT_MIME.get(path.rsplit(".", 1)[-1].lower(), mime)
    return data, mime


def _tiktok(kind, media_id, conversation, message_id):
    token = social.tiktok_access_token()
    cfg = social.tiktok_config()
    _, data = social._tiktok_call("business/message/media/download/", {
        "business_id": cfg["business_id"], "conversation_id": conversation,
        "message_id": message_id, "media_id": media_id,
        "media_type": "VIDEO" if kind == "video" else "IMAGE"},
        headers={"Access-Token": token})
    url = (data.get("data") or {}).get("download_url") if data.get("code") == 0 else None
    if not url:
        return None, "no_download_url"
    return _get(url, headers={"x-user": token})


def _fetch(row, kind, ref, info):
    if row.channel in social.META_CHANNELS:
        return _get(ref)
    if row.channel == "telegram":
        return _telegram(ref)
    if row.channel == "tiktok":
        return _tiktok(kind, ref, info.get("conv") or "", info.get("mid") or "")
    return None, "unknown_channel"


def capture(row):
    """Fetch and keep the first usable file of one queued message."""
    from app.models import PatientAttachment

    try:
        info = json.loads(row.link or "{}")
    except ValueError:
        info = {}
    reason = "no_media"
    for kind, ref in info.get("m") or []:
        try:
            data, mime = _fetch(row, kind, ref, info)
        except social.SendRefused as exc:
            data, mime = None, exc.code
        if data is None:
            reason = mime or "media_failed"
            continue
        stored = wa_media.store(data, mime)
        if not stored:
            reason = f"unsupported_type:{mime}"
            continue
        row.image_url = f"static/uploads/patient_docs/{stored}"
        row.error = None
        if row.patient_id:
            body = row.body or ""
            caption = "" if body.startswith("[") else body.split("\n[", 1)[0].strip()
            kind_ = wa_media.kind_for(caption, mime)
            db.session.add(PatientAttachment(
                patient_id=row.patient_id, filename=stored,
                original_name=caption[:120] or None, kind=kind_,
                label=caption[:160] or None, source=row.channel,
                investigation_id=wa_media.answered_order(row.patient_id, kind_)))
        return True
    row.error = reason[:200]
    return False


def fetch_pending(limit=BATCH):
    """Work through the queue. Returns how many files were kept."""
    rows = (MessageLog.query.filter_by(error=PENDING, direction="in")
            .order_by(MessageLog.id).limit(limit).all())
    kept = sum(1 for row in rows if capture(row))
    if rows:
        db.session.commit()
    return kept


def after_response(response):
    """Fetch the queue once the platform has its answer — never inside the
    five seconds it waits for one."""
    from flask import current_app

    app = current_app._get_current_object()

    def work():
        with app.app_context():
            try:
                fetch_pending()
            except Exception:  # noqa: BLE001 — a file never costs a message
                db.session.rollback()
                app.logger.exception("social media: queued files not fetched")
    response.call_on_close(work)
    return response


__all__ = ["PENDING", "after_response", "capture", "fetch_pending", "queue"]
