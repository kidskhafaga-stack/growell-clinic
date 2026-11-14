"""The FHIR interface's doors (``utils/fhir_api``).

``GET /fhir/r4/metadata``                     what this server answers
``GET /fhir/r4/Patient?identifier=…|_id=…``   the shared children that match
``GET /fhir/r4/Patient/<id>``                 one shared child
``GET /fhir/r4/Patient/<id>/$summary``        the International Patient Summary
``GET /fhir/r4/Patient/<id>/$everything``     the whole record (scope «full»)

Off, every door answers 404 as if it were not there. A missing or wrong key
is 401; a child not shared with this receiver — or an id that is nobody's —
is the same 404, so the answer says nothing about who is a patient here.
"""
import json

from flask import Response, g, request, url_for

from app.blueprints.fhir_api import fhir_api_bp
from app.extensions import db
from app.utils import fhir_api as api
from app.utils.decorators import client_ip
from app.utils.rate_limit import limit

MEDIA = "application/fhir+json"
#: A machine reading shared records, not a person — generous, but a ceiling.
PER_MINUTE = 120


def _send(body, status=200):
    return Response(json.dumps(body, ensure_ascii=False), status=status,
                    mimetype=MEDIA, headers={"Cache-Control": "no-store"})


def _fail(code, text, status):
    body, status = api.outcome(code, text, status)
    resp = _send(body, status)
    if status == 401:
        resp.headers["WWW-Authenticate"] = 'Bearer realm="fhir"'
    return resp


def _receiver():
    """``(receiver, None)`` or ``(None, response)``."""
    if not api.enabled():
        return None, _fail("not-found", "Not found", 404)
    receiver = api.receiver_for(request.headers.get("Authorization"))
    if receiver is None:
        return None, _fail("login", "A valid key is required", 401)
    return receiver, None


def _noted(receiver, what, patient=None):
    """Write the read down before answering; a read that cannot be written
    down is not answered."""
    try:
        api.note(receiver, what, patient, ip=client_ip())
        db.session.commit()
    except Exception:  # noqa: BLE001 - e.g. a read-only licence
        db.session.rollback()
        return _fail("transient", "The read could not be recorded; try again later", 503)
    return None


def _lang():
    return "en" if (request.args.get("_language") or "").lower().startswith("en") else "ar"


@fhir_api_bp.route("/metadata", methods=["GET"])
@limit("fhir", PER_MINUTE, methods=("GET",))
def metadata():
    if not api.enabled():
        return _fail("not-found", "Not found", 404)
    return _send(api.capability(url_for("fhir_api.metadata", _external=True)
                                .rsplit("/metadata", 1)[0]))


@fhir_api_bp.route("/Patient", methods=["GET"])
@limit("fhir", PER_MINUTE, methods=("GET",))
def patient_search():
    receiver, refused = _receiver()
    if refused:
        return refused
    wanted_id = (request.args.get("_id") or "").strip()
    ident = (request.args.get("identifier") or "").strip()
    value = ident.split("|", 1)[1] if "|" in ident else ident
    found = []
    for patient in api.shared_patients(receiver):
        if wanted_id and api.logical_id(patient) != wanted_id:
            continue
        if value and (patient.patient_number or "") != value:
            continue
        resource = api.patient_resource(patient, _lang())
        if resource:
            found.append(resource)
    failed = _noted(receiver, "search")
    if failed:
        return failed
    return _send(api.searchset(found))


def _one(resource_id, what):
    receiver, refused = _receiver()
    if refused:
        return None, None, refused
    patient = api.find(receiver, resource_id)
    if patient is None:
        return None, None, _fail("not-found", "Not found", 404)
    return receiver, patient, None


@fhir_api_bp.route("/Patient/<resource_id>", methods=["GET"])
@limit("fhir", PER_MINUTE, methods=("GET",))
def patient_read(resource_id):
    receiver, patient, refused = _one(resource_id, "read")
    if refused:
        return refused
    resource = api.patient_resource(patient, _lang())
    failed = _noted(receiver, "read", patient)
    return failed or _send(resource)


@fhir_api_bp.route("/Patient/<resource_id>/$summary", methods=["GET"])
@limit("fhir", PER_MINUTE, methods=("GET",))
def patient_summary(resource_id):
    from app.utils.fhir_ips import ips_for

    receiver, patient, refused = _one(resource_id, "summary")
    if refused:
        return refused
    bundle = ips_for(patient, lang=_lang())
    failed = _noted(receiver, "summary", patient)
    return failed or _send(bundle)


@fhir_api_bp.route("/Patient/<resource_id>/$everything", methods=["GET"])
@limit("fhir", PER_MINUTE, methods=("GET",))
def patient_everything(resource_id):
    from app.utils.fhir_export import bundle_for

    receiver, patient, refused = _one(resource_id, "everything")
    if refused:
        return refused
    if receiver.scope != "full":
        return _fail("forbidden", "This key may read the patient summary only", 403)
    bundle = bundle_for(patient, _lang())
    failed = _noted(receiver, "everything", patient)
    return failed or _send(bundle)


@fhir_api_bp.before_request
def _no_writes():
    """Read-only: anything but GET is refused before it is read."""
    if request.method not in ("GET", "HEAD"):
        return _fail("not-supported", "This server is read-only", 405)
    g.fhir_api = True
    return None
