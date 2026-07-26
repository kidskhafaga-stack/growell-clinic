"""The X-ray the parent sends on WhatsApp, landing in the child's file.

The doctor asks for a chest film. The parent photographs the report at the lab
and sends it to the clinic. Until now the webhook noticed a file had arrived,
wrote the word ``[media]`` in the conversation, and threw the file away — so the
doctor opened the thread to find a placeholder where the X-ray should be.

This downloads it from the provider and files it where it belongs: on the
patient's record as a document, in the conversation as something you can open,
and therefore in front of the doctor during the visit.

Everything here treats the provider's response as hostile input: the size is
capped before it is written, the type is decided by *us* from the declared MIME
rather than by any filename the sender chose, and nothing is attached to a
patient's record unless we actually matched the sender to that patient.
"""
import os
import uuid

from app.extensions import db
from app.utils.uploads import ALLOWED_DOC_EXTENSIONS, docs_dir

# A phone photo is 2–6 MB; a scanned PDF report can be larger. Past this we
# stop reading rather than let one message fill the clinic's disk.
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT = 30

# Declared MIME → the extension we store it under. Anything not on this list
# is not saved: the clinic's document folder is served over the web, and a file
# type nobody asked for has no business being written into it.
MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif", "application/pdf": "pdf",
}

# What the parent says when they send it — used to file it under the right tab.
KIND_HINTS = {
    "imaging": ("أشعة", "اشعه", "أشعه", "سونار", "رنين", "إيكو", "ايكو",
                "x-ray", "xray", "ultrasound", "ct", "mri", "echo"),
    "lab": ("تحليل", "تحاليل", "معمل", "صورة دم", "lab", "blood", "cbc",
            "test", "result"),
}


def kind_for(caption, mime=""):
    """Which tab this belongs under, from what the parent wrote."""
    text = (caption or "").lower()
    for kind, words in KIND_HINTS.items():
        if any(word in text for word in words):
            return kind
    return "report" if (mime or "").endswith("pdf") else "imaging"


def _read_capped(response):
    """Read a streamed response, stopping at ``MAX_BYTES``."""
    chunks, total = [], 0
    for chunk in response.iter_content(64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def download(media, cfg=None):
    """Fetch one inbound file → ``(bytes, mime)``, or ``(None, reason)``.

    Meta's Cloud API hands out a media *id*: you ask it for a short-lived URL,
    then fetch that URL with the same token. Providers that send a direct link
    are used as-is.
    """
    from app.utils.whatsapp import get_config

    if not media:
        return None, "no_media"
    try:
        import requests
    except ImportError:                      # pragma: no cover
        return None, "requests_missing"

    cfg = cfg or get_config()
    url, headers = media.get("url"), {}
    try:
        if not url:
            token, media_id = cfg.get("cloud_token"), media.get("id")
            if not token or not media_id:
                return None, "not_configured"
            headers = {"Authorization": f"Bearer {token}"}
            meta = requests.get(f"https://graph.facebook.com/v20.0/{media_id}",
                                headers=headers, timeout=TIMEOUT)
            if meta.status_code != 200:
                return None, f"lookup_{meta.status_code}"
            url = (meta.json() or {}).get("url")
            if not url:
                return None, "no_url"
        resp = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            return None, f"download_{resp.status_code}"
        mime = (resp.headers.get("Content-Type")
                or media.get("mime") or "").split(";")[0].strip().lower()
        data = _read_capped(resp)
        if data is None:
            return None, "too_big"
        return data, mime
    except Exception as exc:                 # noqa: BLE001 - never break the webhook
        return None, f"error:{type(exc).__name__}"


def store(data, mime):
    """Write the bytes into the patient-documents folder → stored filename.

    The extension comes from the declared type, never from a name the sender
    supplied — a document folder that is served over the web must not accept a
    file type on somebody else's say-so.
    """
    ext = MIME_EXT.get((mime or "").lower())
    if not ext or ext not in ALLOWED_DOC_EXTENSIONS or not data:
        return None
    stored = f"{uuid.uuid4().hex}.{ext}"
    folder = docs_dir()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, stored), "wb") as out:
        out.write(data)
    return stored


def capture(item, log):
    """Save an inbound file and file it on the patient's record.

    Returns the created ``PatientAttachment`` (or None). The message is already
    saved by the time this runs, so a failure here costs the file, never the
    conversation.
    """
    from app.models import PatientAttachment

    media = (item or {}).get("media")
    if not media or log is None:
        return None
    data, mime = download(media)
    if data is None:
        log.error = (mime or "media_failed")[:200]
        return None
    stored = store(data, mime)
    if not stored:
        log.error = f"unsupported_type:{mime}"[:200]
        return None

    # The conversation shows it; the file is inside the patient's documents.
    log.image_url = f"static/uploads/patient_docs/{stored}"
    if not log.patient_id:
        # An unmatched number: keep the file with the message, but never guess
        # whose record it belongs on.
        return None
    caption = (item.get("text") or "").strip()
    att = PatientAttachment(
        patient_id=log.patient_id, filename=stored,
        original_name=(caption[:120] or None),
        kind=kind_for(caption, mime),
        label=caption[:160] or None)
    db.session.add(att)
    return att
