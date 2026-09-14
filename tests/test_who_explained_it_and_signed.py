"""The doctor's own name at the bottom of the consent — GAHAR PCC.08 (3).

> *"The responsible physician obtaining the informed consent **signs the form
> with the patient**."*

The program had two things that look like this from a distance and are not it:

* **`obtained_by`** — which account typed the row. Usually reception, filing
  what came back from the clinic. A system field, not a signature.
* **a «شاهد» line on the printed sheet**, with that account's name printed
  under it. A witness attests that they watched somebody sign; the responsible
  physician attests that **they** explained what was being agreed to. Two
  different claims, and the sheet was carrying the one nobody had asked for
  while the one the standard asks for had nowhere to go.

The model already says the right thing about the guardian — *"a row carrying a
name is a claim; the signature is the only thing in it that is evidence"* — and
this file is that same sentence applied to the doctor.

Four things pinned here:

* **It does not reach backwards.** `stands_on()` is untouched, so a consent
  taken on paper last year goes on standing. Making the physician's signature
  a condition would have every consent in every running clinic read as
  *unsigned* the morning after an update, and drop the consent item off
  theatre cases that were fine the day before.
* **Reception cannot make the claim.** Unlike a clinical privilege — which is
  a judgement this program has no business overriding — this is a fact about
  the account, and there is no three-in-the-morning case where recording the
  desk as the doctor who explained an anaesthetic is the right answer.
* **Signing twice does not move the date.**
* **On paper there is no second image**, because both signatures are on the
  one sheet that was already scanned.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A child with a signed consent, a doctor, and the front desk."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Consent, Patient, Setting, User
        from app.utils.clock import local_today

        Setting.set("mod_enabled:patients", "1")
        people = {}
        for username, name, role in (("doc", "د. الطبيب", "doctor"),
                                     ("boss", "المدير", "admin"),
                                     ("desk", "الاستقبال", "reception")):
            user = User(username=username, full_name=name, role=role,
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
            people[username] = user
        db.session.flush()
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      is_active=True, date_of_birth=local_today())
        db.session.add(kid)
        db.session.flush()
        signed = Consent(patient_id=kid.id, consent_type="procedure",
                         guardian_name="الأم", signed_date=local_today(),
                         obtained_by=people["desk"].id,
                         signature_file="scan.png", signature_kind="paper")
        blank = Consent(patient_id=kid.id, consent_type="general",
                        guardian_name="الأم", signed_date=local_today())
        db.session.add_all([signed, blank])
        db.session.commit()
        ids = {k: v.id for k, v in people.items()}
        ids.update({"kid": kid.id, "signed": signed.id, "blank": blank.id})

    def sign_in(username="doc"):
        """A signed-in client. **Used outside `app_context()`, deliberately.**

        Flask-Login caches the signed-in user on `g`, and `g` belongs to the
        application context — so two clients used inside one long-lived
        `with app.app_context()` share it, the second sign-in is skipped as
        «already authenticated», and both requests are served as whoever
        signed in first. A test that compared two roles that way would pass
        while proving nothing. Every request below therefore runs with no
        outer context, which is what happens in the app: one per request.
        """
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _consent(clinic, key="signed"):
    from app.models import Consent

    clinic["db"].session.expire_all()
    return clinic["db"].session.get(Consent, clinic["ids"][key])


# ------------------------------------------------- who may make the claim --
@pytest.mark.parametrize("username,allowed", [("doc", True), ("boss", True),
                                              ("desk", False)])
def test_only_a_doctor_signs_as_the_responsible_physician(clinic, username,
                                                          allowed):
    """**Refused, not warned about.** The privileges module warns and goes
    ahead because refusing there moves the operation somewhere the program
    cannot see. Nothing moves here: reception pressing this writes a sentence
    on a signed document that is simply untrue."""
    clinic["sign_in"](username).post(
        "/patients/consents/%s/physician-signature" % clinic["ids"]["signed"],
        follow_redirects=True)

    with clinic["app"].app_context():
        assert _consent(clinic).physician_signed is allowed


def test_the_one_who_signed_is_the_one_recorded(clinic):
    """Not `obtained_by` — the desk filed this row, and the standard is asking
    who explained it."""
    with clinic["app"].app_context():
        clinic["sign_in"]("doc").post(
            "/patients/consents/%s/physician-signature"
            % clinic["ids"]["signed"], follow_redirects=True)
        row = _consent(clinic)

        assert row.physician_id == clinic["ids"]["doc"]
        assert row.obtained_by == clinic["ids"]["desk"]


@pytest.mark.parametrize("username,drawn", [("doc", True), ("desk", False)])
def test_only_the_account_that_could_sign_is_offered_the_button(clinic,
                                                                username,
                                                                drawn):
    """A control that refuses when pressed is a control that should not have
    been drawn."""
    page = clinic["sign_in"](username).get(
        "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)

    assert ("data-physician-box" in page) is drawn


# --------------------------------------------------- on paper, and on screen
def test_on_paper_there_is_no_second_image(clinic):
    """Both signatures are on the one sheet `signature_file` already holds. A
    second copy of it would be the program storing the same picture twice and
    calling the second one a different fact."""
    with clinic["app"].app_context():
        clinic["sign_in"]("doc").post(
            "/patients/consents/%s/physician-signature"
            % clinic["ids"]["signed"], follow_redirects=True)
        row = _consent(clinic)

        assert row.physician_signed is True
        assert row.physician_signature_file is None


def test_on_screen_the_doctor_has_an_image_of_their_own(clinic):
    """There was never a sheet, so the two signatures are two images."""
    import base64

    png = base64.b64encode(
        bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 40).decode()
    with clinic["app"].app_context():
        clinic["sign_in"]("doc").post(
            "/patients/consents/%s/physician-signature"
            % clinic["ids"]["signed"],
            data={"drawn": "data:image/png;base64," + png},
            follow_redirects=True)
        row = _consent(clinic)

        assert row.physician_signed is True
        assert row.physician_signature_file


def test_a_drawn_signature_that_is_not_an_image_is_refused(clinic):
    """The header on a data URL is a string somebody typed, and this writes
    files into a folder the browser serves."""
    import base64

    with clinic["app"].app_context():
        clinic["sign_in"]("doc").post(
            "/patients/consents/%s/physician-signature"
            % clinic["ids"]["signed"],
            data={"drawn": "data:image/png;base64,"
                  + base64.b64encode(b"<?php echo 1; ?>").decode()},
            follow_redirects=True)

        assert _consent(clinic).physician_signed is False


# --------------------------------------------------------- what it does not -
def test_it_does_not_reach_back_and_invalidate_what_was_signed(clinic):
    """**The rule that decides the whole shape of this.** A consent taken
    correctly, on paper, before any of this existed has no physician row — and
    an update that made it read as unsigned would drop the consent item off
    theatre cases that were fine the day before, silently."""
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        row = _consent(clinic)

        assert row.physician_signed is False
        assert row.stands_on(local_today()) is True


def test_the_theatre_checklist_reads_the_same_as_it_did(clinic):
    """`consent_state` keeps its five words. A sixth would make every linked
    consent in every running clinic stop counting overnight."""
    from app.utils import theatres as th

    assert "no_physician" not in str(th.consent_state.__doc__)


# ------------------------------------------------ and where it is asked for -
def test_the_gap_is_named_while_somebody_can_still_close_it(clinic):
    with clinic["app"].app_context():
        page = clinic["sign_in"]("doc").get(
            "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)

    assert "data-physician-missing" in page


def test_a_blank_sheet_is_waiting_on_the_conversation_not_the_doctor(clinic):
    """A consent nobody has signed at all is not a form waiting on the
    physician. Two warnings on one blank sheet teaches whoever reads them to
    read neither."""
    from app.utils import consent as cu

    with clinic["app"].app_context():
        assert cu.physician_missing(_consent(clinic, "blank")) is False
        assert cu.physician_missing(_consent(clinic, "signed")) is True


def test_a_withdrawn_consent_needs_nobody_chasing(clinic):
    from datetime import datetime

    from app.utils import consent as cu

    with clinic["app"].app_context():
        row = _consent(clinic)
        row.withdrawn_at = datetime.utcnow()
        clinic["db"].session.commit()

        assert cu.physician_missing(row) is False


def test_a_withdrawn_consent_cannot_be_signed(clinic):
    from datetime import datetime

    with clinic["app"].app_context():
        row = _consent(clinic)
        row.withdrawn_at = datetime.utcnow()
        clinic["db"].session.commit()
        clinic["sign_in"]("doc").post(
            "/patients/consents/%s/physician-signature"
            % clinic["ids"]["signed"], follow_redirects=True)

        assert _consent(clinic).physician_signed is False


def test_nothing_is_claimed_about_a_consent_that_is_not_there(clinic):
    from app.utils import consent as cu

    assert cu.physician_missing(None) is False


# ------------------------------------------------- signing twice, and once --
def test_a_second_press_does_not_move_the_date(clinic):
    """The moment a doctor put their name to this is a fact, and a slow screen
    must not rewrite it — the same rule `privileges.withdraw` follows."""
    with clinic["app"].app_context():
        client = clinic["sign_in"]("doc")
        client.post("/patients/consents/%s/physician-signature"
                    % clinic["ids"]["signed"], follow_redirects=True)
        first = _consent(clinic).physician_signed_at

        client.post("/patients/consents/%s/physician-signature"
                    % clinic["ids"]["signed"], follow_redirects=True)

        assert _consent(clinic).physician_signed_at == first


def test_a_second_doctor_does_not_take_the_first_ones_place(clinic):
    """**Two different accounts, and so two requests outside any shared
    context** — see `sign_in`. Run inside one, the second sign-in is skipped
    and both presses come from the first doctor, which is the one arrangement
    under which this test cannot fail."""
    where = ("/patients/consents/%s/physician-signature"
             % clinic["ids"]["signed"])
    clinic["sign_in"]("doc").post(where, follow_redirects=True)
    clinic["sign_in"]("boss").post(where, follow_redirects=True)

    with clinic["app"].app_context():
        assert _consent(clinic).physician_id == clinic["ids"]["doc"]


# ------------------------------------------------------- and on the paper --
def test_the_printed_form_has_a_line_for_the_doctor(clinic):
    """**The form is what somebody signs on.** A sheet with no line for the
    doctor is a sheet the doctor cannot sign, whatever the program records —
    and it is the line a surveyor reads."""
    from app.i18n import _load_translations, _lookup

    with clinic["app"].app_context():
        page = clinic["sign_in"]("doc").get(
            "/patients/consents/%s/print"
            % clinic["ids"]["signed"]).get_data(as_text=True)
        said = _lookup(_load_translations(), "ar", "consent.physician_signature")

    assert said in page


def test_the_line_is_there_before_anybody_has_signed(clinic):
    from app.i18n import _load_translations, _lookup

    with clinic["app"].app_context():
        page = clinic["sign_in"]("doc").get(
            "/patients/consents/%s/print"
            % clinic["ids"]["blank"]).get_data(as_text=True)
        said = _lookup(_load_translations(), "ar", "consent.physician_signature")

    assert said in page


def test_the_sheet_no_longer_calls_the_typist_a_witness(clinic):
    """`obtained_by` printed under «شاهد» put a statement on the sheet that
    nobody had made — on the one line the standard is actually about."""
    with clinic["app"].app_context():
        page = clinic["sign_in"]("doc").get(
            "/patients/consents/%s/print"
            % clinic["ids"]["signed"]).get_data(as_text=True)

    assert "الاستقبال" not in page


def test_the_doctors_name_prints_once_they_have_signed(clinic):
    with clinic["app"].app_context():
        client = clinic["sign_in"]("doc")
        client.post("/patients/consents/%s/physician-signature"
                    % clinic["ids"]["signed"], follow_redirects=True)
        page = client.get("/patients/consents/%s/print"
                          % clinic["ids"]["signed"]).get_data(as_text=True)

    assert "د. الطبيب" in page


def test_the_column_is_in_the_upgrade_list():
    from app.utils.schema import ADDITIONS

    for column in ("physician_id", "physician_signed_at",
                   "physician_signature_file"):
        assert any(t == "consents" and c == column for t, c, _ in ADDITIONS), column


# ---------------------------- the same rule, held at both ends -------------
#
# The route refuses reception *and* so does `sign_as_physician`; the route
# short-circuits a second press *and* the util is idempotent. Each was
# covering the other, so removing either left every test still passing — the
# exact shape `labs.collect`/`labs.perform` has a comment about: **a guard
# from one side is half a rule, and the missing half is the one somebody gets
# through.** So both halves are pinned here, separately.
def test_the_util_refuses_the_desk_even_with_no_route_in_front_of_it(clinic):
    from app.models import User
    from app.utils import consent as cu

    with clinic["app"].app_context():
        desk = clinic["db"].session.get(User, clinic["ids"]["desk"])
        row = _consent(clinic)

        assert cu.sign_as_physician(row, desk) is None
        assert row.physician_signed is False


def test_the_util_will_not_sign_for_nobody(clinic):
    from app.utils import consent as cu

    with clinic["app"].app_context():
        assert cu.sign_as_physician(_consent(clinic), None) is None
        assert cu.sign_as_physician(None, object()) is None


def test_the_util_itself_does_not_move_the_date(clinic):
    from app.models import User
    from app.utils import consent as cu

    with clinic["app"].app_context():
        doc = clinic["db"].session.get(User, clinic["ids"]["doc"])
        row = _consent(clinic)
        cu.sign_as_physician(row, doc)
        first = row.physician_signed_at

        cu.sign_as_physician(row, doc)

        assert row.physician_signed_at == first


def test_the_route_says_why_when_it_refuses(clinic):
    """Reception pressing it gets told, and — the reason the route checks at
    all rather than leaving it to the util — nothing is written to disk on the
    way to finding out."""
    from app.i18n import _load_translations, _lookup

    page = clinic["sign_in"]("desk").post(
        "/patients/consents/%s/physician-signature" % clinic["ids"]["signed"],
        follow_redirects=True).get_data(as_text=True)
    with clinic["app"].app_context():
        said = _lookup(_load_translations(), "ar", "consent.physician_only")

    assert said in page


def test_the_route_says_so_on_a_second_press(clinic):
    from app.i18n import _load_translations, _lookup

    client = clinic["sign_in"]("doc")
    where = "/patients/consents/%s/physician-signature" % clinic["ids"]["signed"]
    client.post(where, follow_redirects=True)
    page = client.post(where, follow_redirects=True).get_data(as_text=True)
    with clinic["app"].app_context():
        said = _lookup(_load_translations(), "ar", "consent.physician_already")

    assert said in page


def test_naming_the_physician_is_not_the_same_as_their_signature(clinic):
    """**The whole point of the standard, in one assertion.** Knowing which
    doctor is responsible is a name in a row — the thing `obtained_by` already
    was. The signature is a separate fact with a time on it, and the column
    the program reads to answer «did they sign» has to be that one."""
    with clinic["app"].app_context():
        row = _consent(clinic)
        row.physician_id = clinic["ids"]["doc"]
        clinic["db"].session.commit()

        assert row.physician_signed is False


# ------------------------------------- the screen nobody could find --------
def test_the_wording_editor_has_a_door_from_where_it_is_used(clinic):
    """Asked for a second time — *«عايز برده شاشة لتعديل صياغات الاقرارات»* —
    about a screen that was already built, complete, per kind and per
    language, with the program's own text still reachable underneath.

    **It had no way in from anywhere a consent is written.** Whoever is
    reading the sentence a family is about to sign is exactly the person who
    notices it is wrong, and they were two screens and a guess away from the
    box that fixes it. A feature with no door into it from where it is used is
    a feature the clinic does not have.
    """
    page = clinic["sign_in"]("boss").get(
        "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)

    assert "data-consent-wording-link" in page
    assert "?tab=consent" in page


def test_and_not_to_somebody_it_would_refuse(clinic):
    """The settings screen is `@admin_required`. A link that lands on «مالكش
    صلاحية» is worse than no link — the same rule as the physician's own
    button above."""
    page = clinic["sign_in"]("doc").get(
        "/patients/%s" % clinic["ids"]["kid"]).get_data(as_text=True)

    assert "data-consent-wording-link" not in page


def test_the_door_opens_on_the_wording_tab(clinic):
    """And it is the tab the link names — `?tab=consent` rather than a hash,
    because the settings screen rewrites its own hash and a link to one it is
    already on does nothing at all. The comment in that screen's `init()` is
    about exactly this."""
    page = clinic["sign_in"]("boss").get(
        "/settings/?tab=consent").get_data(as_text=True)

    assert 'id="consent-text"' in page
    assert 'name="consent_text_general_ar"' in page
