"""What a guardian is actually signing.

Reported: *"the wording of the consents — its own text for each kind, clear in
Arabic and in English according to the language in use."*

There were seven consent kinds and **one sentence**: "I confirm I have been
informed of the nature of the medical service, its risks and alternatives, and
I agree to it." A photography consent and an anaesthesia consent were signed
under identical words. That sentence is true of both and says what is being
agreed to in neither — and saying what is being agreed to is the entire job of
a consent form.

Two further things came out of looking at it, and both are worse than the
wording:

**The text was resolved when the form was printed, not when it was signed.**
``statement`` was nullable and the printout fell back to the live translation,
so re-printing a consent after the wording was edited — or from an English
session — produced a document stating that somebody had agreed to words they
were never shown. What was signed is a fact about that day, and a record that
re-renders itself is not a record.

**And two screens wrote consents by two different routes.** The patient file
hand-built a ``Consent`` row while the visit room went through ``record()``, so
whichever door the consent came in by decided what it said. They go through one
writer now.

The blank-textarea test is the one that connects the wording to reality:
nobody types a consent statement into an empty box while a family waits, so an
empty box guaranteed every consent in the clinic was signed under the generic
sentence no matter how good the per-kind text was.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

KINDS = ["general", "examination", "procedure", "vaccination", "anesthesia",
         "data_privacy", "photography"]


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ============================================================ the wording ===
@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_has_its_own_words(clinic, kind):
    from app.utils.consent import statement_for

    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        text = statement_for(kind)
        assert text and text != f"consent.statements.{kind}"
        assert text != t("consent.default_statement"), (
            f"{kind} is still signing the generic sentence")


def test_no_two_kinds_share_the_same_sentence(clinic):
    """The failure this item is about, stated directly."""
    from app.utils.consent import statement_for

    with clinic["app"].test_request_context("/"):
        texts = [statement_for(k) for k in KINDS]
    assert len(set(texts)) == len(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_the_wording_exists_in_both_languages(clinic, kind):
    """"According to the language in use" only means something if both are
    written. A missing Arabic key falls back to English silently, and a family
    signs a paragraph they cannot read."""
    import json

    for lang in ("ar", "en"):
        data = json.loads(_read("app", "i18n", "locales", f"{lang}.json"))
        text = data["consent"]["statements"].get(kind)
        assert text and len(text) > 60, f"{lang}/{kind}"


def test_the_arabic_and_english_are_not_the_same_string(clinic):
    """Copying the English into the Arabic file is how a translation gets
    "done" without being done."""
    import json

    ar = json.loads(_read("app", "i18n", "locales", "ar.json"))["consent"]["statements"]
    en = json.loads(_read("app", "i18n", "locales", "en.json"))["consent"]["statements"]
    for kind in KINDS:
        assert ar[kind] != en[kind], kind


def test_each_kind_says_something_specific_to_itself(clinic):
    """Seven different paragraphs that all avoid naming what they are about
    would pass every test above. Each has to carry its own subject."""
    from app.utils.consent import statement_for

    marks = {
        "vaccination": ("تطعيم",),
        "anesthesia": ("تخدير",),
        "photography": ("تصوير",),
        "data_privacy": ("بيانات",),
        "procedure": ("الإجراء", "إجراء"),
        "examination": ("فحص", "كشف"),
    }
    with clinic["app"].test_request_context("/"):
        for kind, words in marks.items():
            text = statement_for(kind)
            assert any(w in text for w in words), kind


def test_an_unknown_kind_is_never_signed_under_a_blank(clinic):
    from app.utils.consent import statement_for

    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert statement_for("something_new") == t("consent.default_statement")


# ================================================== frozen at signing time ==
def test_the_wording_is_stored_on_the_row(clinic):
    """Not looked up when it is printed. A record that re-renders itself is
    not a record of anything."""
    from app.models import Patient
    from app.utils.consent import record

    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        patient = clinic["db"].session.get(Patient, ids["child"])
        row = record(patient, "photography", "الأم")
        clinic["db"].session.commit()
        assert row.statement
        assert "تصوير" in row.statement


def test_changing_the_wording_does_not_rewrite_what_was_signed(clinic):
    """The heart of it. Somebody edits the standard text next month; every
    consent already on file must still print the words its guardian read."""
    from app.models import Consent, Patient
    from app.utils.consent import record

    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        patient = clinic["db"].session.get(Patient, ids["child"])
        row = record(patient, "vaccination", "الأم")
        clinic["db"].session.commit()
        row_id, signed_text = row.id, row.statement

    # The catalogue moves on.
    import app.i18n as i18n
    translations = i18n._load_translations()
    original = translations["ar"]["consent"]["statements"]["vaccination"]
    translations["ar"]["consent"]["statements"]["vaccination"] = "نص جديد تماماً"
    try:
        with clinic["app"].app_context():
            stored = clinic["db"].session.get(Consent, row_id)
            assert stored.statement == signed_text
            assert "نص جديد" not in stored.statement
    finally:
        translations["ar"]["consent"]["statements"]["vaccination"] = original


def test_a_statement_typed_by_hand_wins(clinic):
    """The doctor adding a sentence for this particular case is the point of
    the box being editable."""
    from app.models import Patient
    from app.utils.consent import record

    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        patient = clinic["db"].session.get(Patient, ids["child"])
        row = record(patient, "procedure", "الأم", statement="نص مخصوص للحالة")
        clinic["db"].session.commit()
        assert row.statement == "نص مخصوص للحالة"


def test_whitespace_is_not_a_statement(clinic):
    """A box the cursor passed through is not a consent somebody wrote."""
    from app.models import Patient
    from app.utils.consent import record, statement_for

    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        patient = clinic["db"].session.get(Patient, ids["child"])
        row = record(patient, "anesthesia", "الأم", statement="   ")
        clinic["db"].session.commit()
        assert row.statement == statement_for("anesthesia")


# ==================================================== one writer, two doors =
def test_both_screens_write_through_the_same_function(clinic):
    """The patient file hand-built its own row while the visit room went
    through record(), so which door the consent came in by decided what it
    said."""
    import inspect

    from app.blueprints.patients import routes as patients_routes
    from app.blueprints.visits import routes as visits_routes

    for module in (patients_routes, visits_routes):
        source = inspect.getsource(module)
        assert "from app.utils.consent import" in source


def test_the_patient_file_records_the_per_kind_wording(clinic, boss):
    from app.models import Consent

    ids = clinic["ids"]
    boss.post(f"/patients/{ids['child']}/consents", data={
        "consent_type": "photography", "guardian_name": "الأم",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        row = Consent.query.filter_by(consent_type="photography").first()
        assert row is not None
        assert row.statement and "تصوير" in row.statement


def test_the_visit_room_records_the_per_kind_wording(clinic):
    from app.models import Consent

    ids = clinic["ids"]
    doc = clinic["sign_in"]("doc")
    doc.post(f"/visits/{ids['visit']}/consent", data={
        "consent_type": "vaccination", "guardian_name": "الأم",
    }, follow_redirects=True)
    with clinic["app"].app_context():
        row = Consent.query.filter_by(consent_type="vaccination").first()
        assert row is not None
        assert row.statement and "تطعيم" in row.statement


# ======================================================= what the form shows
@pytest.mark.parametrize("screen", ["patients/profile.html", "visits/record.html"])
def test_the_form_shows_the_words_before_they_are_signed(clinic, screen):
    """The box was empty, and nobody types a consent statement into an empty
    box while a family waits — so every consent in the clinic was signed under
    the generic sentence regardless of how good the per-kind text was."""
    body = _read("app", "templates", *screen.split("/"))
    assert "consent_statements" in body, screen
    assert 'name="statement"' in body, screen
    assert "texts[kind]" in body, screen


def test_the_shown_text_follows_the_chosen_kind(clinic, boss):
    """Picking "photography" and reading out the anaesthesia paragraph would
    be worse than the single generic sentence, not better."""
    body = _read("app", "templates", "patients", "profile.html")
    assert "x-effect" in body or "x-model" in body
    reply = boss.get(f"/patients/{clinic['ids']['child']}")
    assert reply.status_code == 200
    page = reply.get_data(as_text=True)
    assert "تصوير" in page and "تخدير" in page


# ------------------------------------------------------------- the printout
def test_the_printed_form_shows_what_was_signed(clinic, boss):
    from app.models import Consent, Patient
    from app.utils.consent import record

    ids = clinic["ids"]
    with clinic["app"].test_request_context("/"):
        patient = clinic["db"].session.get(Patient, ids["child"])
        record(patient, "data_privacy", "الأم")
        clinic["db"].session.commit()
    with clinic["app"].app_context():
        consent_id = Consent.query.filter_by(consent_type="data_privacy").first().id

    body = boss.get(f"/patients/consents/{consent_id}/print").get_data(as_text=True)
    assert "بيانات" in body


def test_an_old_row_with_no_stored_text_still_prints(clinic, boss):
    """Consents written before this change have no statement. They must print,
    and print that kind's wording rather than the one generic sentence."""
    from app.models import Consent

    ids = clinic["ids"]
    with clinic["app"].app_context():
        row = Consent(patient_id=ids["child"], consent_type="anesthesia",
                      guardian_name="الأم", signed_date=date.today())
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        consent_id = row.id

    reply = boss.get(f"/patients/consents/{consent_id}/print")
    assert reply.status_code == 200
    assert "تخدير" in reply.get_data(as_text=True)
