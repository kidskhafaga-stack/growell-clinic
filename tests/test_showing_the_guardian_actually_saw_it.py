"""Evidence that the guardian read it, rather than a claim that they did.

Asked as *"ازاي نعمل حاجه نتأكد منها ان ولى الامر اطلع على الكونسينت وموافق
عليه بشكل وثق وصحيح"*.

Everything a consent held was typed by a member of staff: a name, a relation,
an ID number, a date. None of it is evidence that the person named ever read
the words. A row with a name in it and nothing else is a claim, not a
document.

Two ways, and the file says which one it has, because they are not equal:

* **paper** — the printed consent came back with a wet signature and was
  scanned in. The strongest form, and the one an Egyptian clinic can stand
  behind.
* **drawn** — signed on screen with a finger. Convenient, weaker, and honest
  about being weaker.

Half of what is below is about the route not believing what it was sent. The
drawn signature arrives as a base64 string that a browser *says* is a PNG, and
this writes files into a folder the browser will later serve back.
"""
import base64
import io

import pytest

from app.utils.clock import local_today

# The smallest valid PNG: an 1x1 image, header and all.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg==")


@pytest.fixture
def consent(clinic):
    from app.models import Consent

    with clinic["app"].app_context():
        row = Consent(patient_id=clinic["ids"]["child"], consent_type="general",
                      guardian_name="أبو الطفل", statement="نص",
                      signed_date=local_today())
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        clinic["consent_id"] = row.id
    return clinic


def _url(kit):
    return f"/patients/consents/{kit['consent_id']}/signature"


# ------------------------------------------------------ the scanned paper ---
def test_the_signed_paper_can_come_back(consent):
    from app.models import Consent

    consent["sign_in"]("boss").post(
        _url(consent),
        data={"file": (io.BytesIO(PNG), "signed.png")},
        content_type="multipart/form-data", follow_redirects=True)

    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert row.has_signature
        assert row.signature_kind == "paper"
        assert row.signature_at is not None


def test_the_paper_is_dated_when_it_arrived_not_when_it_was_signed(consent):
    """The paper often comes back the next day. One date for both would be
    the file saying something nobody checked."""
    from app.models import Consent
    import datetime

    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        row.signed_date = local_today() - datetime.timedelta(days=3)
        consent["db"].session.commit()

    consent["sign_in"]("boss").post(
        _url(consent), data={"file": (io.BytesIO(PNG), "signed.png")},
        content_type="multipart/form-data", follow_redirects=True)

    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert row.signature_at.date() != row.signed_date


# -------------------------------------------------- the one on the screen ---
def test_a_signature_drawn_on_screen_is_kept(consent):
    from app.models import Consent

    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    consent["sign_in"]("boss").post(
        _url(consent), data={"drawn": data_url}, follow_redirects=True)

    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert row.has_signature
        assert row.signature_kind == "drawn"


def test_the_two_kinds_are_told_apart(consent):
    """A scan of a wet signature and a finger-drawn squiggle are not equal
    evidence. A file calling both of them "signed" would hide the difference
    at exactly the moment somebody needs it."""
    from app.models import Consent

    consent["sign_in"]("boss").post(
        _url(consent), data={"file": (io.BytesIO(PNG), "s.png")},
        content_type="multipart/form-data", follow_redirects=True)
    with consent["app"].app_context():
        assert Consent.query.get(consent["consent_id"]).signature_kind == "paper"

    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    consent["sign_in"]("boss").post(
        _url(consent), data={"drawn": data_url}, follow_redirects=True)
    with consent["app"].app_context():
        assert Consent.query.get(consent["consent_id"]).signature_kind == "drawn"


# --------------------------------------- and it believes none of the above --
@pytest.mark.parametrize("payload", [
    "data:image/png;base64,bm90IGEgcG5nIGF0IGFsbA==",   # valid base64, not an image
    "data:image/png;base64,%%%not base64%%%",           # not base64 at all
    "data:image/png;base64," + base64.b64encode(
        b"<?php echo 1; ?>").decode(),                  # a script wearing a header
    "data:image/png;base64," + base64.b64encode(
        b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>").decode(),
])
def test_it_decides_from_the_bytes_and_not_the_header(consent, payload):
    """A data URL's `image/png` is a string somebody typed. This route writes
    files into a folder the browser serves back, so what the bytes actually
    are is the only thing that may decide."""
    from app.models import Consent

    consent["sign_in"]("boss").post(
        _url(consent), data={"drawn": payload}, follow_redirects=True)
    with consent["app"].app_context():
        assert not Consent.query.get(consent["consent_id"]).has_signature


def test_a_refused_upload_leaves_the_consent_unsigned(consent):
    from app.models import Consent

    consent["sign_in"]("boss").post(
        _url(consent), data={"file": (io.BytesIO(b"not an image"), "x.png")},
        content_type="multipart/form-data", follow_redirects=True)
    with consent["app"].app_context():
        assert not Consent.query.get(consent["consent_id"]).has_signature


def test_it_needs_a_login(consent):
    answer = consent["app"].test_client().post(_url(consent))
    assert answer.status_code in (302, 401, 403)


def test_it_is_written_down(consent):
    from app.models import ActivityLog

    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    consent["sign_in"]("boss").post(
        _url(consent), data={"drawn": data_url}, follow_redirects=True)
    with consent["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="consent.signature.drawn").count() == 1


# ------------------------------------------------------------- the screen ---
def test_the_screen_says_when_there_is_no_signature(consent):
    """The absence has to be visible. A consent with no evidence that looks
    exactly like one with evidence is the state this whole thing exists to
    end."""
    page = consent["sign_in"]("boss").get(
        f"/patients/{consent['ids']['child']}").get_data(as_text=True)
    assert "من غير توقيع" in page or "no signature" in page
    assert "consent.sig_none" not in page


def test_the_screen_offers_both_ways(consent):
    page = consent["sign_in"]("boss").get(
        f"/patients/{consent['ids']['child']}").get_data(as_text=True)
    assert 'name="file"' in page             # the scanned paper
    # `x-data="sigPad(` and not `sigPad(`: the function is defined in a script
    # block that is always on the page, so searching for the bare name would
    # pass with the whole row markup deleted.
    assert 'x-data="sigPad(' in page         # the pad, on this consent
    assert 'x-ref="pad"' in page


def test_a_withdrawn_consent_is_not_offered_a_signature(consent):
    """Signing evidence onto a consent that no longer stands is a document
    saying two things at once."""
    boss = consent["sign_in"]("boss")
    boss.post(f"/patients/consents/{consent['consent_id']}/withdraw",
              follow_redirects=True)
    page = boss.get(
        f"/patients/{consent['ids']['child']}").get_data(as_text=True)
    assert 'x-data="sigPad(' not in page


def test_an_empty_pad_cannot_be_saved(consent):
    """A blank signature attached to a consent is worse than none, because the
    row would then say it has one."""
    page = consent["sign_in"]("boss").get(
        f"/patients/{consent['ids']['child']}").get_data(as_text=True)
    assert ':disabled="!drew"' in page


def test_the_columns_are_in_the_upgrade_list():
    from app.utils.schema import ADDITIONS

    for column in ("signature_file", "signature_kind", "signature_at"):
        assert any(t == "consents" and c == column
                   for t, c, _type in ADDITIONS), column
