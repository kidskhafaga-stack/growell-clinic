"""The FHIR interface (ROADMAP.md ٣, ``utils/fhir_api``): another system reads
a child's record — read-only, one key per receiver, and only the children
somebody at the clinic shared with it, until a date. Off until an
administrator turns it on; every read written down.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _on(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        Setting.set("fhir_api_enabled", "1" if on else "0")
        c["db"].session.commit()


def _receiver(c, scope="summary"):
    import re

    boss = c["sign_in"]("boss")
    page = boss.post("/interop/", data={"action": "add", "name": "مستشفى التحويل",
                                        "scope": scope}).get_data(as_text=True)
    return re.search(r"data-key>([^<]+)<", page).group(1)


def _share(c, days=30):
    from app.models.interop import FhirReceiver

    with c["app"].app_context():
        rid = FhirReceiver.query.order_by(FhirReceiver.id.desc()).first().id
    c["sign_in"]("doc").post(f"/interop/patient/{c['ids']['child']}",
                             data={"receiver_id": rid, "days": days})


def _id(c):
    from app.models import Patient
    from app.utils import fhir_api

    with c["app"].app_context():
        pid = fhir_api.logical_id(c["db"].session.get(Patient, c["ids"]["child"]))
        c["db"].session.commit()
        return pid


@pytest.fixture()
def api(clinic):
    return clinic["app"].test_client()


def _get(client, path, key=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return client.get(path, headers=headers)


def test_off_it_is_not_there(clinic, api):
    _on(clinic)
    key = _receiver(clinic)
    _on(clinic, False)
    assert _get(api, "/fhir/r4/metadata").status_code == 404
    assert _get(api, "/fhir/r4/Patient", key).status_code == 404


def test_the_key_is_shown_once_and_kept_only_as_a_hash(clinic):
    from app.models.interop import FhirReceiver

    _on(clinic)
    key = _receiver(clinic)
    assert key.startswith("ppfh_") and len(key) > 30
    with clinic["app"].app_context():
        row = FhirReceiver.query.one()
        assert row.key_hash != key and key not in row.key_hash and row.key_hint == key[-4:]
    page = clinic["sign_in"]("boss").get("/interop/").get_data(as_text=True)
    assert key not in page and "data-new-key" not in page


def test_nothing_until_a_child_is_shared(clinic, api):
    _on(clinic)
    key = _receiver(clinic)
    body = _get(api, "/fhir/r4/Patient", key).get_json()
    assert body["resourceType"] == "Bundle" and body["total"] == 0
    assert _get(api, f"/fhir/r4/Patient/{_id(clinic)}", key).status_code == 404


def test_a_shared_child_reads_as_the_files_do(clinic, api):
    from app.models import ActivityLog

    _on(clinic)
    key = _receiver(clinic)
    _share(clinic)
    pid = _id(clinic)
    found = _get(api, "/fhir/r4/Patient?identifier=P1", key).get_json()
    assert found["total"] == 1 and found["entry"][0]["resource"]["id"] == pid
    assert _get(api, f"/fhir/r4/Patient/{pid}", key).get_json()["resourceType"] == "Patient"
    summary = _get(api, f"/fhir/r4/Patient/{pid}/$summary", key)
    assert summary.status_code == 200 and summary.mimetype == "application/fhir+json"
    assert summary.get_json()["type"] == "document"
    assert _get(api, f"/fhir/r4/Patient/{pid}/$everything", key).status_code == 403, \
        "a summary key does not get the whole record"
    with clinic["app"].app_context():
        actions = {a.action for a in ActivityLog.query.filter(ActivityLog.action.like("fhir_api.%"))}
    assert {"fhir_api.search", "fhir_api.read", "fhir_api.summary", "fhir_api.share"} <= actions


def test_the_whole_record_for_a_full_key(clinic, api):
    _on(clinic)
    key = _receiver(clinic, scope="full")
    _share(clinic)
    body = _get(api, f"/fhir/r4/Patient/{_id(clinic)}/$everything", key).get_json()
    assert body["resourceType"] == "Bundle" and body["type"] == "collection"


def test_wrong_revoked_stopped_and_ended(clinic, api):
    from app.models.interop import FhirReceiver, FhirShare

    _on(clinic)
    key = _receiver(clinic)
    _share(clinic)
    pid = _id(clinic)
    assert _get(api, f"/fhir/r4/Patient/{pid}", "ppfh_wrong").status_code == 401
    assert _get(api, f"/fhir/r4/Patient/{pid}").status_code == 401
    with clinic["app"].app_context():
        share = FhirShare.query.one()
        share.until = datetime.utcnow() - timedelta(minutes=1)
        clinic["db"].session.commit()
    assert _get(api, f"/fhir/r4/Patient/{pid}", key).status_code == 404, "the share ended"
    _share(clinic)
    with clinic["app"].app_context():
        newest = FhirShare.query.order_by(FhirShare.id.desc()).first().id
    clinic["sign_in"]("doc").post(f"/interop/share/{newest}/stop")
    assert _get(api, f"/fhir/r4/Patient/{pid}", key).status_code == 404, "stopped"
    _share(clinic)
    assert _get(api, f"/fhir/r4/Patient/{pid}", key).status_code == 200
    with clinic["app"].app_context():
        rid = FhirReceiver.query.one().id
    clinic["sign_in"]("boss").post(f"/interop/receiver/{rid}/revoke")
    assert _get(api, f"/fhir/r4/Patient/{pid}", key).status_code == 401, "revoked"


def test_nothing_can_be_written(clinic, api):
    _on(clinic)
    key = _receiver(clinic)
    resp = api.post("/fhir/r4/Patient", json={"resourceType": "Patient"},
                    headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 405


def test_who_may_open_the_screens_and_the_doors(clinic):
    child = clinic["ids"]["child"]
    assert clinic["sign_in"]("doc").get("/interop/").status_code in (302, 403)
    assert clinic["sign_in"]("desk").get(f"/interop/patient/{child}").status_code in (302, 403)
    assert "data-interop-door" in clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-fhir-share" not in clinic["sign_in"]("doc").get(f"/patients/{child}").get_data(as_text=True)
    _on(clinic)
    assert "data-fhir-share" in clinic["sign_in"]("doc").get(f"/patients/{child}").get_data(as_text=True)
