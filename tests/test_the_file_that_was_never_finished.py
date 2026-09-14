"""A file somebody started at the desk and nobody ever came back to.

> «انا النهارده جيت وسجلت بيانات المريض بالطريقة السريعة وكشف ومشى، جه مره
> تانيه لازم انبه الاستقبال ان يستكمل البيانات بتاعت المريض قبل تلقي خدمة
> تانيه»

The quick registration takes a name, a sex and a date of birth. That is the
right amount to get a child seen, and it is also how a file with no phone
number on it enters the system. Nothing was ever wrong with the quick path —
what was missing is anything that said the file was still half-written.

Five things this suite pins:

* **Derived, never stored.** Fill the phone in and the flag is gone on the
  next read, everywhere, with nothing to recompute and nothing to forget.
* **The clinic decides what «basic» means.** A vocabulary plus a setting, not
  a rule this program invented for somebody else's building.
* **Unset and empty are different answers.** A clinic that has never opened
  the setting gets the default; one that deliberately asked for nothing gets
  nothing. "Nobody said" is not "said no" — the distinction this codebase has
  spent its whole life keeping.
* **Every field names a column that exists.** A requirement nobody can satisfy
  is worse than no requirement at all.
* **It tells; it never blocks.** Booking, admitting and seeing a child all
  carry on exactly as before. A three-in-the-morning arrival is not made to
  wait for an address.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def desk():
    """One child registered the quick way, and one with a full file."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Family, Parent, Patient, User
        from app.utils.clock import local_today

        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)

        # The quick path: a name, a sex, a birthday. Nothing else.
        quick = Patient(patient_number="P1", full_name="طفل سريع",
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=500))
        db.session.add(quick)

        family = Family(family_name="عائلة كاملة")
        db.session.add(family)
        db.session.flush()
        db.session.add(Parent(family_id=family.id, relation="mother",
                              full_name="فاطمة السيد", phone="01000000000",
                              national_id="29001011234567",
                              address="٥ شارع النيل", is_primary_contact=True))
        full = Patient(patient_number="P2", full_name="طفل كامل",
                       gender="female", is_active=True, family_id=family.id,
                       date_of_birth=local_today() - timedelta(days=800))
        db.session.add(full)
        db.session.commit()
        ids = {"quick": quick.id, "full": full.id, "family": family.id,
               "boss": boss.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _patient(ctx, which):
    from app.models import Patient
    return ctx["db"].session.get(Patient, ctx["ids"][which])


# ------------------------------------------------- what is missing --------
def test_the_quick_file_is_missing_the_two_that_matter(desk):
    """The scenario as it was described: seen once, back again, and nothing
    on file but a name and a birthday."""
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        gaps = basics.missing(_patient(desk, "quick"))

    assert gaps == ["phone", "guardian"]
    assert basics.DEFAULT_REQUIRED == ("phone", "guardian")


def test_a_finished_file_says_nothing(desk):
    """No badge where there is nothing to chase. A warning on every row is
    the same as no warning at all."""
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        assert basics.missing(_patient(desk, "full")) == []
        assert basics.is_complete(_patient(desk, "full")) is True


def test_filling_it_in_clears_it_with_nothing_to_recompute(desk):
    """**The reason it is derived.** Reception types the number and the flag
    is gone on the next read — no column to update, no screen to refresh, and
    nothing that can be forgotten and left nagging about a file already
    fixed."""
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        child = _patient(desk, "quick")
        assert "phone" in basics.missing(child)

        child.own_phone = "01111111111"
        desk["db"].session.commit()

        assert "phone" not in basics.missing(_patient(desk, "quick"))


def test_a_guardian_with_no_phone_is_still_a_guardian(desk):
    """Two separate facts, and the program must not collapse them: somebody
    is on file as responsible, and somebody can be rung. A file can have the
    first without the second."""
    from app.models import Parent
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        child = _patient(desk, "quick")
        family_id = desk["ids"]["family"]
        child.family_id = family_id
        quiet = Parent(family_id=family_id, relation="father",
                       full_name="أب من غير تليفون")
        desk["db"].session.add(quiet)
        desk["db"].session.commit()

        gaps = basics.missing(_patient(desk, "quick"))

    # The family it joined already has a mother with a phone, so both are met.
    assert gaps == []


def test_a_phone_of_nothing_but_spaces_is_not_a_phone(desk):
    """A survivor from the measuring, and a real one: these are free-text
    boxes. Somebody who taps the field, types a space and saves has not given
    the clinic a number to ring — and a file that reads as complete because of
    it is worse than one that reads as empty, because nobody goes back to it.
    """
    from app.models import Parent
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        child = _patient(desk, "quick")
        child.own_phone = "   "
        # ...and a guardian whose number is blank too, since `contact_phone`
        # hands a guardian's back unstripped.
        family_id = desk["ids"]["family"]
        empty = desk["db"].session.get(type(child), desk["ids"]["full"])
        for parent in empty.family.parents:
            parent.phone = "  "
        child.family_id = family_id
        desk["db"].session.commit()

        assert "phone" in basics.missing(_patient(desk, "quick")), \
            "a phone of spaces counted as a phone number"
        # The guardian is still a guardian — that is a different fact.
        assert "guardian" not in basics.missing(_patient(desk, "quick"))


def test_a_child_with_a_family_and_nobody_in_it(desk):
    """An empty family is not a guardian. The row exists; the person does
    not."""
    from app.models import Family
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        empty = Family(family_name="عائلة فاضية")
        desk["db"].session.add(empty)
        desk["db"].session.flush()
        child = _patient(desk, "quick")
        child.family_id = empty.id
        desk["db"].session.commit()

        assert "guardian" in basics.missing(_patient(desk, "quick"))


def test_nobody_is_not_a_problem_to_report(desk):
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        assert basics.missing(None) == []
        assert basics.is_complete(None) is True


# ------------------------------------- the clinic decides, not the program -
def test_the_clinic_can_ask_for_more(desk):
    from app.models import Setting
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        Setting.set(basics.SETTING, "phone,guardian,guardian_id,address")
        desk["db"].session.commit()

        assert basics.required() == ("phone", "guardian", "guardian_id",
                                     "address")
        # The full file has all four; the quick one has none of them.
        assert basics.missing(_patient(desk, "full")) == []
        assert basics.missing(_patient(desk, "quick")) == [
            "phone", "guardian", "guardian_id", "address"]


def test_unset_and_empty_are_different_answers(desk):
    """**Nobody said is not said no.** A clinic that has never opened the
    setting is asked for the default; one that deliberately cleared it is
    asked for nothing, and must not be quietly given the default back."""
    from app.models import Setting
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        assert basics.required() == basics.DEFAULT_REQUIRED   # never set

        Setting.set(basics.SETTING, "")
        desk["db"].session.commit()

        assert basics.required() == ()
        assert basics.missing(_patient(desk, "quick")) == []


def test_the_answer_is_kept_in_the_programs_own_order(desk):
    """Whatever order it was saved in, reception reads the same list — the
    thing worth chasing first, first."""
    from app.models import Setting
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        Setting.set(basics.SETTING, "blood_type,guardian,phone")
        desk["db"].session.commit()

        assert basics.required() == ("phone", "guardian", "blood_type")


def test_a_key_that_is_not_a_field_is_ignored(desk):
    """A setting carrying something this build does not know about — an older
    key, or a typo — asks for what it can and does not raise on a screen."""
    from app.models import Setting
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        Setting.set(basics.SETTING, "phone,shoe_size")
        desk["db"].session.commit()

        assert basics.required() == ("phone",)


# --------------------------------------- the vocabulary is not invented ----
def test_every_field_reads_something_that_exists(desk):
    """A requirement nobody can satisfy is worse than no requirement. Each key
    is asked of a real patient, and the reader has to answer without raising
    — which is the check that it names a column and not a wish."""
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        child = _patient(desk, "full")
        for key in basics.ORDER:
            assert key in basics.FIELDS, "%s is in ORDER but has no reader" % key
            assert basics.FIELDS[key](child) in (True, False)

    assert set(basics.ORDER) == set(basics.FIELDS), \
        "a field with no place in the order, or an order with no field"


def test_the_three_that_can_never_be_missing_are_not_asked_for(desk):
    """`full_name`, `date_of_birth` and `gender` are `nullable=False`. A check
    for them could never fire, and a line that can never fire reads as a
    protection the program does not actually have."""
    from app.utils import patient_basics as basics

    for never in ("full_name", "date_of_birth", "gender", "name"):
        assert never not in basics.FIELDS, \
            "%s cannot be missing — asking for it is a line that never runs" % never


# --------------------------------------------- and it reaches the screen --
#
# The rule is only worth anything where somebody is about to act. These check
# the three search boxes a clinic actually picks a child from, because a flag
# that exists in a util and nowhere on a screen is a flag nobody sees.


def _enable(ctx, *modules):
    from app.models import Setting

    with ctx["app"].app_context():
        for name in modules:
            Setting.set("mod_enabled:%s" % name, "1")
        ctx["db"].session.commit()


def test_the_theatre_booking_search_answers_at_all(desk):
    """**It used to answer 500.** The route read `p.file_number` and `Patient`
    has never had that column — it is `patient_number` — so every keystroke in
    the booking box raised and the list stayed empty. A search that looked
    wired up on screen and had never once returned a name."""
    _enable(desk, "theatres")

    answer = desk["sign_in"]().get("/theatres/patient-search?q=طفل")

    assert answer.status_code == 200, "the booking search is raising"
    rows = answer.get_json()
    assert rows and rows[0]["name"] == "طفل سريع"
    assert rows[0]["file"] == "P1", "the file number is not the patient number"


@pytest.mark.parametrize("module,url,unwrap", [
    ("theatres", "/theatres/patient-search?q=طفل", lambda d: d),
    ("appointments", "/appointments/patient-search?q=طفل",
     lambda d: d["patients"]),
    ("prescriptions", "/prescriptions/patient-search?q=طفل", lambda d: d),
])
def test_every_picker_carries_the_gaps(desk, module, url, unwrap):
    """One rule, every box a child is chosen from — the desk, the pharmacy
    and the theatre. Each answers a different shape, so each is asked."""
    _enable(desk, module)

    rows = unwrap(desk["sign_in"]().get(url).get_json())

    assert rows, "no row came back for %s" % module
    assert rows[0]["missing"] == ["phone", "guardian"], \
        "%s does not say the file is half-written" % module


def test_a_finished_file_carries_an_empty_list_not_a_missing_key(desk):
    """An empty list, always — so a screen can read `.length` without first
    asking whether the field is there. A key that appears only sometimes is
    how a badge comes to throw on the one row it matters for."""
    _enable(desk, "theatres")

    rows = desk["sign_in"]().get("/theatres/patient-search?q=كامل").get_json()

    assert rows and rows[0]["missing"] == []


def test_the_wording_the_badge_uses_exists_in_both_languages(desk):
    """The badge names each gap. A key with no wording shows the key itself to
    a reception desk, which is the thing `test_no_raw_keys_on_screen` exists
    to stop."""
    import json
    import os

    from app.utils import patient_basics as basics

    for lang in ("ar", "en"):
        with open(os.path.join(ROOT, "app/i18n/locales/%s.json" % lang),
                  encoding="utf-8") as fh:
            words = json.load(fh)["basics"]
        for key in basics.ORDER:
            assert ("f_" + key) in words, \
                "%s has no wording in %s" % (key, lang)
        assert "{n}" in words["missing_n"], \
            "the badge in %s cannot say how many" % lang


# ------------------------------------------ the clinic's own answer -------

def _save(ctx, **form):
    """Post the settings form the way the screen does."""
    client = ctx["sign_in"]()
    page = client.get("/settings/").get_data(as_text=True)
    import re
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    body = {"csrf_token": token, "tab": "clinic"}
    body.update(form)
    return client.post("/settings/", data=body, follow_redirects=True)


def test_the_card_is_on_the_settings_screen(desk):
    """A setting nothing can reach is a switch with no hand on it."""
    from app.i18n import translate as t
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        html = desk["sign_in"]().get("/settings/").get_data(as_text=True)
        assert t("basics.title") in html
        for key in basics.ORDER:
            assert 'value="%s"' % key in html, "%s is not offered" % key


def test_the_screen_saves_what_the_clinic_ticked(desk):
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        _save(desk, **{basics.SETTING + "__present": "1",
                       basics.SETTING: ["phone", "blood_type"]})
        assert basics.required() == ("phone", "blood_type")


def test_unticking_the_last_box_means_none_not_the_default(desk):
    """**The one that would have gone unnoticed.** A save that skipped an
    empty answer would hand the default back, and the clinic that had just
    switched the whole thing off would go on being nagged — while the screen
    showed the boxes it had unticked."""
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        _save(desk, **{basics.SETTING + "__present": "1"})   # nothing ticked

        assert basics.required() == ()
        assert basics.missing(_patient(desk, "quick")) == []


def test_a_form_that_never_carried_the_card_changes_nothing(desk):
    """Some other tab posting the same form must not wipe this answer."""
    from app.models import Setting
    from app.utils import patient_basics as basics

    with desk["app"].app_context():
        Setting.set(basics.SETTING, "phone,address")
        desk["db"].session.commit()

        _save(desk)   # no marker, no boxes

        assert basics.required() == ("phone", "address")


def test_the_childs_own_file_says_what_it_is_missing(desk):
    """The one screen with everything in front of somebody to finish it."""
    from app.i18n import translate as t

    with desk["app"].app_context():
        html = desk["sign_in"]().get(
            "/patients/%s" % desk["ids"]["quick"]).get_data(as_text=True)

        assert "data-basics-missing" in html
        assert t("basics.missing_n", n=2) in html
        assert t("basics.f_phone") in html


def test_a_finished_file_wears_no_badge(desk):
    with desk["app"].app_context():
        html = desk["sign_in"]().get(
            "/patients/%s" % desk["ids"]["full"]).get_data(as_text=True)

        assert "data-basics-missing" not in html
