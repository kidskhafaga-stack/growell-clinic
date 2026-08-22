"""Greeting a child by their own name, in their own grammar.

Two things asked for together, and the second is more than tidiness.

**The name.** A birthday card came out as *"كل سنة وانت طيب يا عمر محمد السيد
خفاجة"* — every one of a child's four names, because `{patient}` is the full
name and it was the only token there was. A prescription heading wants all
four; a birthday card wants one.

**The grammar.** Arabic has no gender-neutral second person. One body forces a
clinic to choose between wording that is wrong for half its register and
"طيب/طيبة" in the middle of a greeting, which reads like a form. So a template
may carry a second wording for a girl, and falls back to the first whenever
that is blank — the same idiom, and the same fallback, as `name`/`name_en` and
`title`/`title_en` everywhere else in this program.

**Blank is the ordinary answer.** Most templates need one wording. A clinic
that writes only the first keeps exactly the behaviour it had before the
column existed, and that is the first thing tested here.

**`{first_name}` is derived once, not at twelve call sites.** Twelve places
build one of these mappings; adding a token to twelve places is adding it to
eleven and forgetting one, and the forgotten one is a message that goes out
with a gap where a child's name should be.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_ctx(clinic):
    return clinic


def _template(clinic, occasion="birthday", body=None, body_female=None,
              is_system=True):
    from app.extensions import db
    from app.models import MessageTemplate

    with clinic["app"].app_context():
        MessageTemplate.query.filter_by(occasion=occasion).delete()
        tpl = MessageTemplate(
            name="tpl", occasion=occasion, is_system=is_system, is_active=True,
            body=body or "كل سنة وانت طيب يا {first_name} — {clinic}",
            body_female=body_female)
        db.session.add(tpl)
        db.session.commit()
        return tpl.id


# --------------------------------------------------------------- the name

def test_a_greeting_uses_the_name_a_person_would_use(clinic_ctx):
    from app.utils import whatsapp as wa

    with clinic_ctx["app"].app_context():
        out = wa.render("مرحباً {first_name}",
                        {"patient": "عمر محمد السيد خفاجة"})

    assert out == "مرحباً عمر"


def test_the_full_name_is_still_there_for_what_needs_it(clinic_ctx):
    """An extra token, never a replacement. A prescription heading wants all
    four names."""
    from app.utils import whatsapp as wa

    with clinic_ctx["app"].app_context():
        out = wa.render("{patient} / {first_name}",
                        {"patient": "عمر محمد السيد خفاجة"})

    assert out == "عمر محمد السيد خفاجة / عمر"


def test_it_is_derived_once_and_not_at_every_call_site(clinic_ctx):
    """The reason it lives in `render`. No caller passes `first_name`, and
    every caller gets it — including the ones written after this."""
    from app.utils import whatsapp as wa

    with clinic_ctx["app"].app_context():
        assert wa.render("{first_name}", {"patient": "سارة أحمد"}) == "سارة"


def test_a_caller_that_supplies_it_is_not_overridden(clinic_ctx):
    from app.utils import whatsapp as wa

    with clinic_ctx["app"].app_context():
        out = wa.render("{first_name}",
                        {"patient": "عمر خفاجة", "first_name": "بوبو"})

    assert out == "بوبو"


@pytest.mark.parametrize("full,expected", [
    ("عمر", "عمر"), ("  عمر  محمد", "عمر"), ("", ""), (None, ""),
])
def test_the_name_split_does_not_fall_over(clinic_ctx, full, expected):
    from app.utils.whatsapp import first_name_of

    assert first_name_of(full) == expected


def test_every_template_that_greets_offers_the_token(clinic_ctx):
    """A token the composer screen never shows is a token nobody uses."""
    from app.models.message import TEMPLATE_VARIABLES

    missing = [k for k, v in TEMPLATE_VARIABLES.items()
               if "patient" in v and "first_name" not in v]

    assert not missing, missing


# ------------------------------------------------------------ the grammar

def test_one_wording_still_goes_to_everybody(clinic_ctx):
    """Tested first, and deliberately: this is what every existing template
    does, and the feature must not disturb it."""
    from app.extensions import db
    from app.models import MessageTemplate

    tpl_id = _template(clinic_ctx, body="أهلاً {first_name}")

    with clinic_ctx["app"].app_context():
        tpl = db.session.get(MessageTemplate, tpl_id)

        assert tpl.body_for("male") == "أهلاً {first_name}"
        assert tpl.body_for("female") == "أهلاً {first_name}"
        assert tpl.body_for(None) == "أهلاً {first_name}"


def test_a_girl_gets_the_wording_written_for_her(clinic_ctx):
    from app.extensions import db
    from app.models import MessageTemplate

    tpl_id = _template(clinic_ctx, body="كل سنة وانت طيب",
                       body_female="كل سنة وانتي طيبة")

    with clinic_ctx["app"].app_context():
        tpl = db.session.get(MessageTemplate, tpl_id)

        assert tpl.body_for("female") == "كل سنة وانتي طيبة"
        assert tpl.body_for("male") == "كل سنة وانت طيب"


def test_an_empty_second_box_falls_back(clinic_ctx):
    """Blank has to mean "one wording is enough", not "send nothing"."""
    from app.extensions import db
    from app.models import MessageTemplate

    tpl_id = _template(clinic_ctx, body="أهلاً", body_female="   ")

    with clinic_ctx["app"].app_context():
        assert db.session.get(MessageTemplate, tpl_id).body_for("female") == "أهلاً"


def test_the_birthday_message_asks_for_the_childs_own_wording(clinic_ctx):
    """End to end, on the message that prompted this."""
    from app.extensions import db
    from app.models import Patient

    _template(clinic_ctx, body="كل سنة وانت طيب يا {first_name}",
              body_female="كل سنة وانتي طيبة يا {first_name}")

    with clinic_ctx["app"].app_context():
        girl = Patient(patient_number="G1", full_name="سارة أحمد محمود",
                       gender="female", date_of_birth=date(2018, 8, 22),
                       own_phone="01000000001", is_active=True)
        db.session.add(girl)
        db.session.commit()
        girl_id = girl.id

    clinic_ctx["sign_in"]("boss").get(f"/messages/occasions/birthday/{girl_id}",
                                      follow_redirects=True)

    with clinic_ctx["app"].app_context():
        from app.models import MessageLog

        log = (MessageLog.query.filter_by(patient_id=girl_id)
               .order_by(MessageLog.id.desc()).first())

    assert log is not None, "no birthday message was produced at all"
    assert log.body == "كل سنة وانتي طيبة يا سارة", log.body


def test_a_campaign_greets_each_child_in_their_own_grammar(clinic_ctx):
    """The one place getting the Arabic wrong is wrong hundreds of times in an
    afternoon."""
    from app.extensions import db
    from app.models import MessageLog, MessageTemplate, Patient

    from app.utils.occasions import enqueue_occasion
    from app.utils.clock import local_today

    with clinic_ctx["app"].app_context():
        MessageTemplate.query.delete()
        Patient.query.delete()
        db.session.add_all([
            Patient(patient_number="C1", full_name="عمر خفاجة", gender="male",
                    date_of_birth=date(2018, 1, 1), own_phone="01000000011",
                    is_active=True),
            Patient(patient_number="C2", full_name="سارة خفاجة",
                    gender="female", date_of_birth=date(2019, 1, 1),
                    own_phone="01000000022", is_active=True),
        ])
        tpl = MessageTemplate(name="عيد", occasion="greeting", is_active=True,
                              body="كل سنة وانت طيب يا {first_name}",
                              body_female="كل سنة وانتي طيبة يا {first_name}",
                              occasion_date=local_today())
        db.session.add(tpl)
        db.session.commit()

        enqueue_occasion(tpl)
        db.session.commit()

        bodies = sorted(m.body for m in MessageLog.query.all())

    assert bodies == ["كل سنة وانت طيب يا عمر",
                      "كل سنة وانتي طيبة يا سارة"], bodies


# -------------------------------------------------------------- the screen

def test_the_composer_offers_the_second_box(clinic_ctx):
    _template(clinic_ctx)

    page = clinic_ctx["sign_in"]("boss").get(
        "/messages/occasions", follow_redirects=True).data.decode()

    assert 'name="body_female"' in page, \
        "there is no way to write the feminine wording"


def test_saving_it_and_clearing_it_both_work(clinic_ctx):
    """Clearing has to be possible: a clinic that decides one wording is
    enough must be able to say so."""
    from app.extensions import db
    from app.models import MessageTemplate

    tpl_id = _template(clinic_ctx, body="أهلاً")
    client = clinic_ctx["sign_in"]("boss")

    client.post(f"/messages/type/{tpl_id}/save",
                data={"body": "أهلاً", "body_female": "أهلاً بيها"},
                follow_redirects=True)
    with clinic_ctx["app"].app_context():
        assert db.session.get(MessageTemplate, tpl_id).body_female == "أهلاً بيها"

    client.post(f"/messages/type/{tpl_id}/save",
                data={"body": "أهلاً", "body_female": ""},
                follow_redirects=True)
    with clinic_ctx["app"].app_context():
        assert db.session.get(MessageTemplate, tpl_id).body_female is None


def test_the_new_column_is_registered_for_an_existing_database(clinic_ctx):
    from app.utils.schema import ADDITIONS

    assert ("message_templates", "body_female") in {
        (table, column) for table, column, *_ in ADDITIONS}


def test_the_wording_exists_in_both_languages(clinic_ctx):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["occasions"]
        for key in ("body_female", "body_female_hint"):
            assert key in block, f"{lang} is missing occasions.{key}"
