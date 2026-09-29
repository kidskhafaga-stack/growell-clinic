"""The admission, signed by the guardian on the screen at the bedside.

Asked as: *«لما أعمل الأدمشن للدخول يظهر، وينفع الأهل تمضي على الشاشة وتقرا
التعليمات بتاعت الأدمشن، ويبدأ يعدّ»*.

What is held here:

* admitting from the map goes straight on to the admission consent;
* the words signed are the clinic's "admission" wording (its own if it wrote
  one), stored on the row as read;
* nothing is signed without the guardian confirming they read it, giving a
  name, and drawing a signature — and a "signature" that is not an image is
  refused;
* the signed consent belongs to that stay: the stay says so, and the map
  stops flagging the bed.
"""
import base64
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)

PNG = ("data:image/png;base64,"
       "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
       "IQAAAABJRU5ErkJggg==")


def _consents(clinic, admission_id):
    from app.models import Consent

    with clinic["app"].app_context():
        return [(c.consent_type, c.guardian_name, c.signature_kind, bool(c.statement))
                for c in Consent.query.filter_by(admission_id=admission_id).all()]


def _sign(clinic, stay, **over):
    data = {"guardian_name": "أم يوسف", "guardian_relation": "mother",
            "read": "1", "drawn": PNG}
    data.update(over)
    return clinic["sign_in"]("boss").post(f"/beds/admission/{stay}/consent", data=data)


def test_admitting_from_the_map_goes_on_to_the_signature(hospital):
    from app.models import Patient

    pid = _child(hospital, "توقيع")
    with hospital["app"].app_context():
        number = hospital["db"].session.get(Patient, pid).patient_number
    reply = hospital["sign_in"]("boss").post("/beds/admit-here", data={
        "patient_number": number, "bed_id": hospital["beds"]["د١"], "then": "consent"})
    assert reply.status_code == 302 and reply.headers["Location"].endswith("/consent")
    page = hospital["sign_in"]("boss").get(reply.headers["Location"]).get_data(as_text=True)
    assert "data-consent-form" in page and "دخول الطفل للإقامة" in page


def test_nothing_is_signed_without_reading_a_name_and_a_signature(hospital):
    stay = _admit(hospital, _child(hospital, "ناقص"))
    _sign(hospital, stay, read="")
    _sign(hospital, stay, guardian_name="  ")
    _sign(hospital, stay, drawn="")
    _sign(hospital, stay, drawn="data:image/png;base64," + base64.b64encode(b"<svg onload=alert(1)>").decode())
    assert _consents(hospital, stay) == []


def test_the_signed_consent_belongs_to_the_stay(hospital):
    stay = _admit(hospital, _child(hospital, "تمام"))
    board = hospital["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    assert "data-unsigned" in board
    page = hospital["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-stay-consent="missing"' in page
    _sign(hospital, stay)
    assert _consents(hospital, stay) == [("admission", "أم يوسف", "drawn", True)]
    page = hospital["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-stay-consent="signed"' in page
    assert "data-unsigned" not in hospital["sign_in"]("boss").get("/beds/").get_data(as_text=True)
    # And the screen says it is done rather than asking again.
    again = hospital["sign_in"]("boss").get(f"/beds/admission/{stay}/consent").get_data(as_text=True)
    assert "data-consent-signed" in again and "data-consent-form" not in again


def test_the_clinics_own_wording_is_what_is_signed(hospital):
    from app.models import Consent, Setting

    with hospital["app"].app_context():
        Setting.set("consent_text_admission_ar", "الزيارة من ٥ لـ ٧ مساءً، ومرافق واحد بس.")
        hospital["db"].session.commit()
    stay = _admit(hospital, _child(hospital, "كلامنا"))
    page = hospital["sign_in"]("boss").get(f"/beds/admission/{stay}/consent").get_data(as_text=True)
    assert "مرافق واحد بس" in page
    _sign(hospital, stay)
    with hospital["app"].app_context():
        assert Consent.query.filter_by(admission_id=stay).one().statement == \
            "الزيارة من ٥ لـ ٧ مساءً، ومرافق واحد بس."
