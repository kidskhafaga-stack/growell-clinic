"""The FHIR interface: other systems read a child's record — read-only, one
key per receiver, only the children shared with it (ROADMAP.md ٣).

The record already leaves the clinic as a file (``utils/fhir_export``, the
whole record, and ``utils/fhir_ips``, the patient summary). This is the same
two documents, fetched by a machine instead of carried by hand, for the
receivers the clinic names:

* **off until an administrator turns it on** (``fhir_api_enabled``), and
  nothing to read until a receiver is added *and* a child is shared with it;
* **one key per receiver**, shown once and kept only as its SHA-256; revoking
  the receiver ends it at once;
* **a receiver sees only the children shared with it** from the child's file,
  each share until a date. Nobody can list the clinic's children;
* **the summary, or the whole record** — the receiver's scope says which;
* **every read is written down**: which receiver, which child, which
  document, from where;
* **read-only**: there is no way to write through it.

The same FHIR R4 as the files, plain and with no national profile claimed;
the summary is the IPS document as the file has it. The operations are the
ones FHIR names for exactly this: ``Patient/[id]/$everything`` and
``Patient/[id]/$summary``.

What it is not: a door to the internet. It answers on the clinic's own
server, where the program already answers; reaching it from outside is the
clinic's own network setup (and TLS) in front of it, as for the rest.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.extensions import db

KEY_SETTING = "fhir_api_enabled"
#: The longest one share may stay open, and the default when none is given.
MAX_DAYS = 365
DEFAULT_DAYS = 30
KEY_PREFIX = "ppfh_"


def enabled():
    from app.models import Setting

    return (Setting.get(KEY_SETTING) or "0") == "1"


def _hash(key):
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def new_receiver(name, scope, purpose, user):
    """``(receiver, key)`` — the key is returned this once and never kept.
    The caller commits."""
    from app.models.interop import SCOPES, FhirReceiver

    name = (name or "").strip()[:120]
    if not name:
        raise ValueError("name")
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = FhirReceiver(name=name, purpose=(purpose or "").strip()[:255] or None,
                       scope=scope if scope in SCOPES else "summary",
                       key_hash=_hash(key), key_hint=key[-4:],
                       created_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row, key


def revoke(receiver, user, now=None):
    receiver.revoked_at = now or datetime.utcnow()
    receiver.revoked_by = getattr(user, "id", None)


def receiver_for(header):
    """The active receiver whose key the ``Authorization`` header carries,
    or ``None``. Looked up by the key's hash, then compared in constant
    time."""
    from app.models.interop import FhirReceiver

    value = (header or "").strip()
    if not value.lower().startswith("bearer "):
        return None
    key = value[7:].strip()
    if not key.startswith(KEY_PREFIX):
        return None
    digest = _hash(key)
    row = FhirReceiver.query.filter_by(key_hash=digest).first()
    if row is None or not hmac.compare_digest(row.key_hash, digest) or not row.is_active:
        return None
    return row


def share(receiver, patient, user, days=DEFAULT_DAYS, reason=None, now=None):
    """Open (or extend) the child's share with the receiver. The caller
    commits."""
    from app.models.interop import FhirShare

    now = now or datetime.utcnow()
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    days = max(1, min(MAX_DAYS, days))
    row = FhirShare(receiver_id=receiver.id, patient_id=patient.id,
                    shared_by=getattr(user, "id", None), shared_at=now,
                    until=now + timedelta(days=days),
                    reason=(reason or "").strip()[:255] or None)
    db.session.add(row)
    return row


def shares_of(patient):
    from app.models.interop import FhirShare

    return (FhirShare.query.filter_by(patient_id=patient.id)
            .order_by(FhirShare.shared_at.desc()).all())


def _open_patient_ids(receiver, now=None):
    from app.models.interop import FhirShare

    now = now or datetime.utcnow()
    rows = (FhirShare.query.filter(FhirShare.receiver_id == receiver.id,
                                   FhirShare.revoked_at.is_(None),
                                   FhirShare.until > now).all())
    return list(dict.fromkeys(r.patient_id for r in rows))


def logical_id(patient):
    """The Patient resource's id — the same one the files carry."""
    import uuid

    from app.utils.fhir_export import namespace

    return str(uuid.uuid5(namespace(), f"Patient/{patient.id}"))


def shared_patients(receiver, now=None):
    from app.models import Patient

    ids = _open_patient_ids(receiver, now)
    if not ids:
        return []
    return Patient.query.filter(Patient.id.in_(ids)).all()


def find(receiver, resource_id, now=None):
    """The shared child whose Patient id this is, or ``None`` — the same
    answer for a child never shared and for an id that is nobody's."""
    for patient in shared_patients(receiver, now):
        if logical_id(patient) == resource_id:
            return patient
    return None


def outcome(code, text, status):
    """A FHIR ``OperationOutcome`` and its HTTP status."""
    return ({"resourceType": "OperationOutcome",
             "issue": [{"severity": "error", "code": code, "diagnostics": text}]},
            status)


def capability(base_url):
    """What this server answers — the CapabilityStatement FHIR asks for at
    ``/metadata``."""
    from app.utils.fhir_export import FHIR_VERSION

    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "kind": "instance",
        "software": {"name": "PediaPro"},
        "implementation": {"description": "Read-only access to the records shared "
                                          "with each receiver", "url": base_url},
        "fhirVersion": FHIR_VERSION,
        "format": ["application/fhir+json"],
        "rest": [{
            "mode": "server",
            "security": {"description": "A bearer key per receiver. Only the "
                                        "children the clinic shared with that "
                                        "receiver can be read."},
            "resource": [{
                "type": "Patient",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [{"name": "identifier", "type": "token"},
                                {"name": "_id", "type": "token"}],
                "operation": [
                    {"name": "everything",
                     "definition": "http://hl7.org/fhir/OperationDefinition/Patient-everything"},
                    {"name": "summary",
                     "definition": "http://hl7.org/fhir/uv/ips/OperationDefinition/summary"},
                ],
            }],
        }],
    }


def patient_resource(patient, lang="ar"):
    """The Patient resource alone, as the files carry it."""
    from app.utils.fhir_export import build

    record = build(patient, lang)
    for entry in record.entries:
        res = entry.get("resource") or {}
        if res.get("resourceType") == "Patient":
            return res
    return None


def searchset(resources):
    import uuid

    return {"resourceType": "Bundle", "id": str(uuid.uuid4()), "type": "searchset",
            "total": len(resources),
            "entry": [{"resource": r, "search": {"mode": "match"}} for r in resources]}


def note(receiver, what, patient=None, ip=None):
    """The audit line for one read, and the receiver's last use."""
    from app.models import ActivityLog

    receiver.last_used_at = datetime.utcnow()
    ActivityLog.record(f"fhir_api.{what}", entity="fhir_receiver", entity_id=receiver.id,
                       detail=(f"{receiver.name} → patient {patient.id}" if patient
                               else receiver.name)[:500],
                       ip_address=ip)


def recent(limit=50):
    from app.models import ActivityLog

    return (ActivityLog.query.filter(ActivityLog.action.like("fhir_api.%"))
            .order_by(ActivityLog.created_at.desc()).limit(limit).all())


__all__ = ["DEFAULT_DAYS", "KEY_SETTING", "MAX_DAYS", "capability", "enabled", "find",
           "logical_id", "new_receiver", "note", "outcome", "patient_resource",
           "receiver_for", "recent", "revoke", "searchset", "share", "shared_patients",
           "shares_of"]
