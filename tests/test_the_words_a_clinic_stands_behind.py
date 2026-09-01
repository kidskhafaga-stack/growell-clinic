"""The wording every consent is signed under, editable by the clinic.

Asked for directly: *"وعايز شاشة اقدر اغير فيها صيغ جميع الموافقات بالعربي
والانجليزي"*. There was no such screen and no way to do it: the seven consent
statements lived in the program's locale files, so a clinic could not change a
word of any of them. A consent form's entire job is to say what is being
agreed to, in words the clinic stands behind.

Two rules hold everything else up.

**Overrides sit beside the default, never on top of it.** The box holds what
the clinic wrote; clearing it puts the program's wording back. A default that
can be edited *away* is a default nobody can ever get back — the same rule the
clinical thresholds follow.

**Editing changes nothing already signed.** The statement is copied onto the
consent row at the moment of signing, which was already true and is what makes
this screen safe to have at all.
"""
from app.models import CONSENT_TYPES
from app.utils import consent as cs


def _key(kind, lang):
    return f"consent_text_{kind}_{lang}"


# ------------------------------------------------------------- the store ---
def test_the_program_has_wording_for_every_kind_in_both_languages(clinic):
    with clinic["app"].app_context():
        for kind in CONSENT_TYPES:
            for lang in ("ar", "en"):
                assert cs.default_statement(kind, lang).strip(), (kind, lang)


def test_the_two_languages_are_different_texts(clinic):
    """A consent is signed in the language it was read in. If the English were
    the Arabic, one of the two guardians signed something they could not
    read."""
    with clinic["app"].app_context():
        assert cs.default_statement("vaccination", "ar") \
            != cs.default_statement("vaccination", "en")


def test_a_clinic_can_write_its_own(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(_key("vaccination", "ar"), "نص العيادة")
        clinic["db"].session.commit()
        assert cs.statement_in("vaccination", "ar") == "نص العيادة"


def test_editing_one_language_leaves_the_other_alone(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        english = cs.statement_in("vaccination", "en")
        Setting.set(_key("vaccination", "ar"), "نص العيادة")
        clinic["db"].session.commit()
        assert cs.statement_in("vaccination", "en") == english


def test_the_default_survives_being_overridden(clinic):
    """The point of the whole design. A clinic that has rewritten every
    consent must still be able to see what the program says and put it back."""
    from app.models import Setting

    with clinic["app"].app_context():
        before = cs.default_statement("vaccination", "ar")
        Setting.set(_key("vaccination", "ar"), "نص العيادة")
        clinic["db"].session.commit()
        assert cs.default_statement("vaccination", "ar") == before


def test_clearing_the_box_restores_the_default(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        default = cs.default_statement("vaccination", "ar")
        Setting.set(_key("vaccination", "ar"), "نص العيادة")
        clinic["db"].session.commit()
        Setting.set(_key("vaccination", "ar"), "")
        clinic["db"].session.commit()
        assert cs.statement_in("vaccination", "ar") == default


# -------------------------------------------------------------- the screen -
def _screen(clinic):
    return clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)


def test_every_kind_has_a_box_in_both_languages(clinic):
    page = _screen(clinic)
    for kind in CONSENT_TYPES:
        for lang in ("ar", "en"):
            assert f'name="{_key(kind, lang)}"' in page, (kind, lang)


def test_the_screen_shows_no_raw_keys(clinic):
    page = _screen(clinic)
    for key in ("settings.consent_title", "settings.consent_hint",
                "settings.consent_default", "settings.lang_ar"):
        assert key not in page


def test_saving_the_form_stores_what_was_typed(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    boss.post("/settings/", data={_key("photography", "en"): "Our own words"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert Setting.get(_key("photography", "en")) == "Our own words"
        assert cs.statement_in("photography", "en") == "Our own words"


def test_saving_an_empty_box_does_not_store_an_empty_consent(clinic):
    """Blank means "use the default", not "this consent says nothing"."""
    boss = clinic["sign_in"]("boss")
    boss.post("/settings/", data={_key("photography", "en"): "Our own words"},
              follow_redirects=True)
    boss.post("/settings/", data={_key("photography", "en"): "   "},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert cs.statement_in("photography", "en") \
            == cs.default_statement("photography", "en")


# ------------------------------------------- and nothing already signed -----
def test_editing_the_wording_does_not_change_a_consent_already_given(clinic):
    """The reason this screen is safe to have. What was signed is a fact about
    that day, copied onto the row — not looked up when the paper is
    reprinted."""
    from app.models import Consent, Setting
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        signed = cs.statement_in("general", "ar")
        row = Consent(patient_id=clinic["ids"]["child"],
                      consent_type="general",
                      guardian_name="أب", statement=signed,
                      signed_date=local_today())
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        consent_id = row.id

        Setting.set(_key("general", "ar"), "نص مختلف تماماً")
        clinic["db"].session.commit()

        assert Consent.query.get(consent_id).statement == signed

    printed = clinic["sign_in"]("boss").get(
        f"/patients/consents/{consent_id}/print").get_data(as_text=True)
    assert "نص مختلف تماماً" not in printed
