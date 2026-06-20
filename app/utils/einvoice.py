"""ETA e-invoice document building & submission.

Two modes (set in settings as ``eta_mode``):

* ``demo``  – simulate the portal: generate a UUID / long id / public link and
              mark the document Valid. Lets the whole flow be demonstrated with
              no credentials.
* ``live``  – authenticate (OAuth2) and POST to the ETA API. Document signing
              (eSeal) is delegated to an optional local signing service URL;
              without it, live submission reports a clear, actionable error.
"""
import hashlib
import json
import urllib.request
import uuid as uuidlib
from datetime import datetime

from app.extensions import db
from app.models import EInvoiceDocument, Setting

# ETA endpoints (production); preprod hosts are the ``*.preprod`` equivalents.
ID_HOST = {"production": "https://id.eta.gov.eg",
           "preprod": "https://id.preprod.invoicing.eta.gov.eg"}
API_HOST = {"production": "https://api.invoicing.eta.gov.eg",
            "preprod": "https://api.preprod.invoicing.eta.gov.eg"}


def get_config():
    g = Setting.get
    return {
        "enabled": g("eta_enabled", "0") == "1",
        "mode": g("eta_mode", "demo"),
        "environment": g("eta_environment", "preprod"),
        "client_id": g("eta_client_id", ""),
        "client_secret": g("eta_client_secret", ""),
        "tax_number": g("eta_tax_number", ""),
        "activity_code": g("eta_activity_code", ""),
        "company": g("eta_company_name", "") or g("clinic_name_ar", "") or g("clinic_name", ""),
        "address": g("eta_branch_address", "") or g("clinic_address", ""),
        "signing_url": g("eta_signing_url", ""),
        "tax_mode": g("eta_default_tax", "exempt"),  # exempt | taxable
        "vat_rate": float(g("eta_vat_rate", "14") or 14),
    }


def build_document(invoice, cfg=None):
    """Build a simplified ETA e-invoice JSON payload for an invoice."""
    cfg = cfg or get_config()
    taxable = cfg["tax_mode"] == "taxable"
    rate = cfg["vat_rate"] if taxable else 0

    lines = []
    for it in invoice.items:
        net = it.net
        tax = round(net * rate / 100.0, 2) if taxable else 0
        lines.append({
            "description": it.description,
            "itemType": "EGS",
            "itemCode": (it.service.code if it.service and it.service.code else "EG-0000"),
            "unitType": "EA",
            "quantity": it.quantity,
            "unitValue": {"currencySold": "EGP", "amountEGP": it.unit_price},
            "salesTotal": it.gross,
            "discount": {"rate": 0, "amount": it.discount_amount},
            "netTotal": net,
            "taxableItems": ([{"taxType": "T1", "amount": tax, "rate": rate}]
                             if taxable else []),
            "total": round(net + tax, 2),
        })

    tax_total = round(sum(l["taxableItems"][0]["amount"] if l["taxableItems"] else 0
                          for l in lines), 2)
    return {
        "documentType": "I", "documentTypeVersion": "1.0",
        "dateTimeIssued": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "taxpayerActivityCode": cfg["activity_code"],
        "internalID": invoice.invoice_number,
        "issuer": {
            "type": "B", "id": cfg["tax_number"], "name": cfg["company"],
            "address": {"country": "EG", "regionCity": "", "street": cfg["address"]},
        },
        "receiver": {
            "type": "P", "id": "", "name": invoice.patient.display_name("ar"),
            "address": {"country": "EG"},
        },
        "invoiceLines": lines,
        "totalDiscountAmount": invoice.discount_total,
        "totalSalesAmount": invoice.subtotal,
        "netAmount": invoice.total,
        "taxTotals": ([{"taxType": "T1", "amount": tax_total}] if taxable else []),
        "totalAmount": round(invoice.total + tax_total, 2),
    }


def submit(document_row, user_id=None, cfg=None):
    """Submit a queued EInvoiceDocument; updates its status in place."""
    cfg = cfg or get_config()
    invoice = document_row.invoice
    payload = build_document(invoice, cfg)
    document_row.doc_json = json.dumps(payload, ensure_ascii=False, indent=2)
    document_row.submitted_at = datetime.utcnow()

    if cfg["mode"] != "live":
        _simulate(document_row, payload)
        return document_row

    document_row.is_demo = False
    ok, result = _submit_live(cfg, payload)
    if ok:
        document_row.status = "submitted"
        document_row.uuid = result.get("uuid")
        document_row.long_id = result.get("longId")
        document_row.submission_uuid = result.get("submissionUUID")
        document_row.public_url = result.get("publicUrl")
        document_row.error = None
    else:
        document_row.status = "rejected"
        document_row.error = result
    return document_row


def _simulate(row, payload):
    """Demo mode: fabricate believable ETA identifiers and mark Valid."""
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest().upper()
    row.is_demo = True
    row.uuid = digest[:64].lower()
    row.long_id = "EG-DEMO-" + digest[:12]
    row.submission_uuid = uuidlib.uuid4().hex[:16].upper()
    row.public_url = (
        "https://preprod.invoicing.eta.gov.eg/documents/" + row.uuid + "/share"
    )
    row.status = "valid"
    row.error = None


def _get_token(cfg):
    host = ID_HOST.get(cfg["environment"], ID_HOST["preprod"])
    data = (
        f"grant_type=client_credentials&client_id={cfg['client_id']}"
        f"&client_secret={cfg['client_secret']}"
    ).encode("utf-8")
    req = urllib.request.Request(
        host + "/connect/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8")).get("access_token")


def _submit_live(cfg, payload):
    if not cfg["client_id"] or not cfg["client_secret"]:
        return False, "ETA credentials not configured."
    if not cfg["signing_url"]:
        # Signing (eSeal) is mandatory for live submission.
        return False, "Document signing service (eSeal) not configured."
    try:
        token = _get_token(cfg)
        if not token:
            return False, "Authentication failed (no token)."
        # Sign via the configured local signing service, then submit.
        signed = _sign(cfg["signing_url"], payload)
        host = API_HOST.get(cfg["environment"], API_HOST["preprod"])
        body = json.dumps({"documents": [signed]}).encode("utf-8")
        req = urllib.request.Request(
            host + "/api/v1.0/documentsubmissions", data=body,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        accepted = (data.get("acceptedDocuments") or [{}])[0]
        return True, {
            "uuid": accepted.get("uuid"),
            "longId": accepted.get("longId"),
            "submissionUUID": data.get("submissionId"),
        }
    except Exception as exc:  # noqa: BLE001 - network / signing failure
        return False, str(exc)[:300]


def _sign(signing_url, payload):
    body = json.dumps({"document": payload}).encode("utf-8")
    req = urllib.request.Request(
        signing_url, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8")).get("document", payload)


def queue_for_invoice(invoice, user_id=None):
    """Flag an invoice as a tax invoice and ensure it has a queued document."""
    invoice.is_tax = True
    doc = EInvoiceDocument.query.filter_by(invoice_id=invoice.id).first()
    if doc is None:
        doc = EInvoiceDocument(invoice_id=invoice.id, status="queued",
                               created_by=user_id)
        db.session.add(doc)
    elif doc.status in ("rejected", "cancelled"):
        doc.status = "queued"
        doc.error = None
    return doc
