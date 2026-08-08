"""The message after the dose, and the message after the visit.

A clinic reported both as *not generated*. Neither was a mystery once looked
at, and neither was one bug:

**The dose message had two writers and one of them was empty.** The
vaccinations screen composed it, sent it and showed the result. The visit room
— where a doctor gives most of the doses, without ever opening the
vaccinations screen — recorded the dose, took the vial out of stock, posted
the cost, and said nothing to the family at all.

**The refusals were silent.** No number on the file, the notification switched
off in settings: each was a bare ``return``. Nothing flashed, nothing logged.
From the outside that is indistinguishable from a program that forgot, which
is exactly how it was reported.

So the tests here are of two kinds: that the message is produced from *both*
places a dose can be given, and that when it is not produced, somebody can
find out why without reading the source.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _reachable(clinic, phone="01001234567"):
    """Give the child a guardian with a phone — otherwise nothing can be sent
    to anybody and every test here would pass for the wrong reason."""
    from app.models import Family, Parent, Patient

    db = clinic["db"]
    family = Family(family_name="أسرة")
    db.session.add(family)
    db.session.flush()
    db.session.add(Parent(family_id=family.id, full_name="الأب",
                          relation="father", phone=phone,
                          is_primary_contact=True))
    db.session.get(Patient, clinic["ids"]["child"]).family_id = family.id
    db.session.commit()


def _logs(clinic, ttype="vaccine_given"):
    from app.models import MessageLog

    return (MessageLog.query.filter_by(template_type=ttype)
            .order_by(MessageLog.id).all())


def _give_in_visit(clinic, client=None):
    client = client or clinic["sign_in"]("doc")
    return client.post(f"/visits/{clinic['ids']['visit']}/give-vaccine",
                       data={"vaccine_id": clinic["ids"]["pcv"],
                             "brand_id": clinic["ids"]["brand"],
                             "dose_number": 1}, follow_redirects=True)


def _give_in_vaccinations(clinic, client=None):
    client = client or clinic["sign_in"]("doc")
    return client.post(f"/vaccinations/{clinic['ids']['child']}/record",
                       data={"vaccine_id": clinic["ids"]["pcv"],
                             "brand_id": clinic["ids"]["brand"],
                             "dose_number": 1,
                             "given_date": date.today().isoformat()},
                       follow_redirects=True)


# ============================================== the dose message ============
def test_a_dose_given_in_the_visit_room_messages_the_family(clinic):
    """The bug as reported. This is where most doses are given."""
    with clinic["app"].app_context():
        _reachable(clinic)

    _give_in_visit(clinic)

    with clinic["app"].app_context():
        logs = _logs(clinic)
        assert len(logs) == 1, "the visit room gave the dose and said nothing"
        assert logs[0].status != "skipped"
        assert logs[0].to_phone


def test_a_dose_given_from_the_vaccinations_screen_still_does(clinic):
    """The path that already worked. Moving the message into one place must
    not have quietly taken it away from the screen that had it."""
    with clinic["app"].app_context():
        _reachable(clinic)

    _give_in_vaccinations(clinic)

    with clinic["app"].app_context():
        assert len(_logs(clinic)) == 1


def test_both_screens_write_the_same_message(clinic):
    """Two copies of one message is how the second one went stale in the first
    place — and a parent should not be able to tell which screen the nurse
    happened to use."""
    from app.models import Patient, Vaccine
    from app.utils.vaccine_notify import dose_message

    with clinic["app"].app_context():
        _reachable(clinic)
        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        vaccine = db.session.get(Vaccine, clinic["ids"]["pcv"])
        expected = dose_message(patient, vaccine, vaccine.brands[0], 1,
                                date.today())

    _give_in_visit(clinic)

    with clinic["app"].app_context():
        assert _logs(clinic)[0].body == expected


# ============================================== and when it does not go =====
def test_a_file_with_no_number_is_recorded_not_dropped(clinic):
    """Half of "the message is not generated": there was nothing to send it
    to, and nothing said so. The clinic can act on this one — somebody rings
    the family and writes the number down."""
    _give_in_visit(clinic)          # no family, no phone anywhere

    with clinic["app"].app_context():
        logs = _logs(clinic)
        assert len(logs) == 1, "the skip left no trace at all"
        assert logs[0].error == "missing_phone"


def test_a_notification_switched_off_says_so(clinic):
    """The other half. A clinic that turned the type off is entitled to a
    reminder of that at the moment it expects a message."""
    from app.models import MessageTemplate

    db = clinic["db"]
    with clinic["app"].app_context():
        _reachable(clinic)
        from app.utils.whatsapp import seed_system_templates

        seed_system_templates()
        tpl = MessageTemplate.query.filter_by(occasion="vaccine_given",
                                              is_system=True).first()
        tpl.is_active = False
        db.session.commit()

    _give_in_visit(clinic)

    with clinic["app"].app_context():
        logs = _logs(clinic)
        assert len(logs) == 1
        assert logs[0].status == "skipped"
        assert logs[0].error == "type_off"
        assert logs[0].body, ("the body was thrown away — somebody turning the "
                              "notification back on cannot see what was missed")


def test_the_doctor_is_told_at_the_time(clinic):
    """On the screen, while the family is still in the room. A reason buried
    in a log nobody opens is the same as no reason."""
    page = _give_in_visit(clinic).data.decode()

    import json

    with open(os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                           "locales", "ar.json"), encoding="utf-8") as fh:
        crm = json.load(fh)["crm"]
    assert crm["reason_missing_phone"] in page


# ============================================== the post-visit survey =======
def test_completing_a_visit_records_why_no_survey_went(clinic):
    """The second report: "the message after the visit is not generated".
    Same shape, same silence."""
    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/complete",
                                  follow_redirects=True)

    with clinic["app"].app_context():
        logs = _logs(clinic, "feedback")
        assert len(logs) == 1
        assert logs[0].status == "skipped"
        assert logs[0].error == "missing_phone"


def test_a_reachable_family_gets_the_survey(clinic):
    """Guarding the guard: recording the refusals is worthless if the message
    stopped going out to the families it can reach."""
    with clinic["app"].app_context():
        _reachable(clinic)

    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/complete",
                                  follow_redirects=True)

    with clinic["app"].app_context():
        logs = _logs(clinic, "feedback")
        assert len(logs) == 1
        assert logs[0].status != "skipped"


# ============================================== where to read it ============
def test_the_skipped_ones_appear_on_the_messages_screen(clinic):
    """"Messages that didn't go" listed only provider failures, so the two
    commonest reasons a family hears nothing were the ones it never showed."""
    import json

    _give_in_visit(clinic)          # skipped: no phone

    page = clinic["sign_in"]("boss").get("/messages/").data.decode()
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                           "locales", "ar.json"), encoding="utf-8") as fh:
        crm = json.load(fh)["crm"]

    assert crm["failures_title"] in page
    assert crm["reason_missing_phone"] in page, "the reason was shown as a key"
    assert "missing_phone" not in page


# ============================================== off vs never set up =========
def _seed_and_switch_off(clinic, ttype):
    """The templates as an upgraded clinic has them, with one turned off."""
    from app.models import MessageTemplate
    from app.utils.whatsapp import seed_system_templates

    seed_system_templates()
    tpl = MessageTemplate.query.filter_by(occasion=ttype, is_system=True).first()
    tpl.is_active = False
    clinic["db"].session.commit()


def test_a_switched_off_survey_is_not_sent_and_says_why(clinic):
    """Off means off. The clinic asked for silence and gets it — with a line
    in the log, so nobody spends an afternoon wondering."""
    with clinic["app"].app_context():
        _reachable(clinic)
        _seed_and_switch_off(clinic, "feedback")

    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/complete",
                                  follow_redirects=True)

    with clinic["app"].app_context():
        logs = _logs(clinic, "feedback")
        assert len(logs) == 1
        assert logs[0].status == "skipped"
        assert logs[0].error == "type_off"


def test_never_setting_a_template_up_is_not_the_same_as_turning_it_off(clinic):
    """The distinction the code used to miss.

    Asking "is there an active template" answers both "did somebody switch
    this off" and "has anybody ever set it up", and the second answer was
    being read as the first — so a clinic that never opened the templates
    screen quietly stopped messaging anybody, which is one of the two ways the
    reported bug happened.
    """
    from app.models import MessageTemplate
    from app.utils.whatsapp import type_is_off

    with clinic["app"].app_context():
        assert MessageTemplate.query.count() == 0
        assert type_is_off("feedback") is False
        assert type_is_off("vaccine_given") is False

        _seed_and_switch_off(clinic, "feedback")
        assert type_is_off("feedback") is True
        assert type_is_off("vaccine_given") is False, \
            "switching one notification off silenced the others"
