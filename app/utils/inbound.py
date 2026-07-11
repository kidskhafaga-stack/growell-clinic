"""Inbound WhatsApp handling — provider-agnostic normalize + route.

Normalizes Meta Cloud API and WaPilot v2 webhook payloads to one shape, matches
the sender to a patient by guardian phone, logs the message, and — when it is a
rating reply — fills the patient's open satisfaction survey. The result lands in
the same ``Feedback`` model, so the existing stars/analytics keep working; only
the collection *channel* differs.
"""
import re
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Feedback, MessageLog, Parent, Patient
from app.utils.whatsapp import normalize_phone


# --- Provider payload normalizers --------------------------------------
def normalize_meta(payload):
    """Meta Cloud API webhook → list of normalized items."""
    items = []
    for entry in (payload or {}).get("entry", []):
        for change in entry.get("changes", []):
            for m in (change.get("value") or {}).get("messages", []):
                items.append(_meta_message(m))
    return [i for i in items if i and i.get("from_phone")]


def _meta_message(m):
    mtype = m.get("type")
    item = {"from_phone": m.get("from"), "text": None, "button_id": None, "media": None}
    if mtype == "text":
        item["text"] = (m.get("text") or {}).get("body")
    elif mtype == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        item["button_id"] = reply.get("id")
        item["text"] = reply.get("title")
    elif mtype in ("image", "document", "audio", "video"):
        media = m.get(mtype) or {}
        item["media"] = {"id": media.get("id"), "mime": media.get("mime_type"), "kind": mtype}
        item["text"] = media.get("caption")
    return item


def normalize_wapilot(payload):
    """WaPilot v2 ``message`` webhook → list of normalized items."""
    m = (payload or {}).get("message") or {}
    if not m:
        return []
    reply = m.get("list_reply") or m.get("button_reply") or {}
    return [{
        "from_phone": m.get("chat_id") or m.get("from"),
        "text": m.get("text"),
        "button_id": reply.get("id") or m.get("button_id"),
        "media": None,
    }]


# --- Matching + rating capture -----------------------------------------
def _match_patients(phone):
    """Patients whose guardian phone matches the inbound number (by family)."""
    if not phone:
        return []
    target = normalize_phone(phone)
    fam_ids = set()
    for p in Parent.query.filter(Parent.phone.isnot(None)).all():
        if (normalize_phone(p.phone) == target
                or (p.phone_alt and normalize_phone(p.phone_alt) == target)):
            if p.family_id:
                fam_ids.add(p.family_id)
    if not fam_ids:
        return []
    return (Patient.query.filter(Patient.family_id.in_(fam_ids))
            .order_by(Patient.id).all())


_RATE_RE = re.compile(r"([0-9]{1,2})")


def _extract_rating(item):
    """A 1..5 rating from a button id (``rate_5``) or a numeric reply."""
    raw = (item.get("button_id") or item.get("text") or "").strip()
    if not raw:
        return None
    m = _RATE_RE.search(raw)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except ValueError:
        return None
    return n if 1 <= n <= 5 else None


def _capture_rating(patients, item):
    """Fill the most recent open survey for these patients from a reply."""
    if not patients:
        return False
    rating = _extract_rating(item)
    if rating is None:
        return False
    pids = [p.id for p in patients]
    fb = (Feedback.query
          .filter(Feedback.patient_id.in_(pids), Feedback.status == "sent",
                  Feedback.created_at >= datetime.utcnow() - timedelta(days=14))
          .order_by(Feedback.created_at.desc()).first())
    if fb is None:
        return False
    fb.doctor_rating = rating
    fb.status = "submitted"
    fb.submitted_at = datetime.utcnow()
    return True


def handle_inbound(item, provider):
    """Log one normalized inbound message and capture a rating if present.

    Caller commits. Returns ``{"matched", "captured"}``.
    """
    phone = normalize_phone(item.get("from_phone"))
    patients = _match_patients(phone)
    body = (item.get("text") or item.get("button_id")
            or ("[media]" if item.get("media") else ""))
    log = MessageLog(direction="in", provider=provider, to_phone=phone,
                     body=body or "", status="received",
                     patient_id=(patients[0].id if patients else None))
    db.session.add(log)
    captured = _capture_rating(patients, item)
    return {"matched": bool(patients), "captured": captured}
