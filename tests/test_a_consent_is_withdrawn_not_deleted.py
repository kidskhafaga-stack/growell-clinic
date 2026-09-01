"""A consent you can delete is not a record of consent.

The statement the guardian signs promises it in its own words — *"ولي أن أسحب
موافقتي في أي وقت"* — and the program had no way to record that happening. It
had a delete button, and deleting is not withdrawing.

Both things are facts and the file needs both: the consent *was* given, and it
no longer stands from a particular day. A row that can be made to say the
consent never happened cannot be evidence that it did.

Deleting stays, for the one case it is actually for — a consent written on the
wrong child, which is not a fact about anybody — and it is admin only now.
Before, the difference between erasing a document and recording a withdrawal
was a button label.
"""
import pytest

from app.utils.clock import local_today


@pytest.fixture
def consent(clinic):
    from app.models import Consent

    with clinic["app"].app_context():
        row = Consent(patient_id=clinic["ids"]["child"],
                      consent_type="general", guardian_name="أبو الطفل",
                      guardian_relation="father", statement="نص الموافقة",
                      signed_date=local_today())
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        clinic["consent_id"] = row.id
    return clinic


def _page(kit):
    return kit["sign_in"]("boss").get(
        f"/patients/{kit['ids']['child']}").get_data(as_text=True)


# ----------------------------------------------------------- withdrawing ---
def test_withdrawing_keeps_the_row(consent):
    from app.models import Consent

    consent["sign_in"]("boss").post(
        f"/patients/consents/{consent['consent_id']}/withdraw",
        data={"reason": "الأهل غيّروا رأيهم"}, follow_redirects=True)

    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert row is not None, "withdrawing deleted the consent"
        assert row.is_withdrawn
        assert row.withdrawn_reason == "الأهل غيّروا رأيهم"
        assert row.withdrawn_by is not None


def test_the_day_it_stopped_standing_is_recorded(consent):
    """The fact somebody will need later. "It was withdrawn" without a date
    cannot answer whether a procedure done on Tuesday was covered."""
    from app.models import Consent

    consent["sign_in"]("boss").post(
        f"/patients/consents/{consent['consent_id']}/withdraw",
        follow_redirects=True)
    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert row.withdrawn_at is not None
        assert row.withdrawn_at.date() == local_today()


def test_the_screen_says_it_is_withdrawn(consent):
    consent["sign_in"]("boss").post(
        f"/patients/consents/{consent['consent_id']}/withdraw",
        follow_redirects=True)
    page = _page(consent)
    assert "مسحوبة" in page or "withdrawn" in page
    assert "consent.withdrawn_badge" not in page


def test_a_withdrawal_can_be_undone(consent):
    """Recorded against the wrong consent, at a desk, with a queue waiting —
    the same reason a referral is reversible."""
    from app.models import Consent

    boss = consent["sign_in"]("boss")
    boss.post(f"/patients/consents/{consent['consent_id']}/withdraw",
              follow_redirects=True)
    boss.post(f"/patients/consents/{consent['consent_id']}/withdraw",
              follow_redirects=True)
    with consent["app"].app_context():
        row = Consent.query.get(consent["consent_id"])
        assert not row.is_withdrawn
        assert row.withdrawn_reason is None


def test_it_is_written_down(consent):
    from app.models import ActivityLog

    consent["sign_in"]("boss").post(
        f"/patients/consents/{consent['consent_id']}/withdraw",
        follow_redirects=True)
    with consent["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="consent.withdraw").count() == 1


# --------------------------------------------------------- and deleting ----
def test_deleting_is_admin_only(consent):
    """It used to be open to anyone who could edit a patient, which made
    erasing a signed document as easy as correcting a phone number.

    Checked with the **doctor**, not reception: reception cannot reach the
    consent section at all, so it would be refused by gating that was already
    there and the test would pass with the admin check deleted."""
    from app.models import Consent

    answer = consent["sign_in"]("doc").post(
        f"/patients/consents/{consent['consent_id']}/delete")
    assert answer.status_code == 403
    with consent["app"].app_context():
        assert Consent.query.get(consent["consent_id"]) is not None


def test_an_admin_can_still_delete_one_written_on_the_wrong_child(consent):
    from app.models import Consent

    consent["sign_in"]("boss").post(
        f"/patients/consents/{consent['consent_id']}/delete",
        follow_redirects=True)
    with consent["app"].app_context():
        assert Consent.query.get(consent["consent_id"]) is None


def test_a_doctor_can_withdraw_one_but_not_delete_it(consent):
    """Reception is not in this comparison: it cannot see the consent section
    at all, so it would show neither button whatever this code did."""
    for who, expect_delete in (("boss", True), ("doc", False)):
        page = consent["sign_in"](who).get(
            f"/patients/{consent['ids']['child']}").get_data(as_text=True)
        assert f"/patients/consents/{consent['consent_id']}/withdraw" in page
        assert (f"/patients/consents/{consent['consent_id']}/delete" in page) \
            is expect_delete


# ------------------------------------------------------------ the clock ----
def test_a_new_consent_is_dated_by_the_clinic_clock(clinic, monkeypatch):
    """`signed_date` defaulted to `date.today` — the machine's wall clock. A
    consent signed at half past midnight in Cairo on a UTC server was dated
    **yesterday**, on a signed document.

    Measured, not introspected. The first version of this asked whether the
    column default *was* `date.today` and passed with the bug put back — it
    was reading SQLAlchemy's wrapper, not the behaviour. This makes the
    clinic's clock answer something the server's clock cannot, and looks at
    what the row got.
    """
    import datetime

    from app.models import Consent

    # Patched at `to_local`, which is what `local_today` calls. Patching
    # `local_today` on the model's module does nothing: the column default
    # holds a direct reference to the function, captured at import, so the
    # name on the module is no longer the path anything takes. That version
    # of this test passed with the bug put back.
    import app.utils.clock as clock

    shifted = datetime.datetime.utcnow() + datetime.timedelta(days=200)
    elsewhere = shifted.date()
    assert elsewhere != datetime.date.today()
    monkeypatch.setattr(clock, "to_local", lambda moment, tz=None: shifted)

    with clinic["app"].app_context():
        row = Consent(patient_id=clinic["ids"]["child"],
                      consent_type="general", guardian_name="أب",
                      statement="نص")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        assert row.signed_date == elsewhere, (
            "the consent date came from the server's clock, not the clinic's")


def test_the_columns_are_in_the_upgrade_list():
    from app.utils.schema import ADDITIONS

    for column in ("withdrawn_at", "withdrawn_reason", "withdrawn_by"):
        assert any(t == "consents" and c == column
                   for t, c, _type in ADDITIONS), column
