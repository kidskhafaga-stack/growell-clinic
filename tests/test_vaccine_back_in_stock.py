"""Calling back the families who were told to come and could not be served.

*"لو التطعيم مش متوفر يبعت يقول للحالة بالتذكير عادي، ولما يتوفر يولد للناس
المتأخرة اللي اتولدلها رسايل رسالة إنه بقى متوفر وتقدر تيجي تاخده، والناس اللي
وعدها ما جاش زي ما هما."*

Three instructions. Two were already true and one was not, and the tests here
say which is which so nobody rebuilds the first two.

The reminder has never consulted the fridge — it is computed from the child's
schedule — so an empty shelf does not silence the clinic. And the order
forecast (*"محتاج ١٢ لأن عندك ١٢ مستحقة"*) has been on the reminders screen
since it was built, needed against in-stock.

What did not exist is the call back. The dose arrives and the families who did
exactly what they were asked — and found nothing — are never told. Getting
this wrong in either direction is easy, so most of what follows is about who
must *not* be messaged: the child who has since had the dose, the family
already told about this delivery, and the family who was never reminded in
the first place.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _started_course(clinic, patient_id=None, dose=1, given=None):
    """A child this clinic has actually vaccinated — the only kind it chases."""
    from app.models import PatientVaccine

    db = clinic["db"]
    db.session.add(PatientVaccine(
        patient_id=patient_id or clinic["ids"]["child"],
        vaccine_id=clinic["ids"]["pcv"], brand_id=clinic["ids"]["brand"],
        dose_number=dose, given_date=given or date(2025, 3, 1),
        event_type="given"))
    db.session.commit()


def _empty_the_shelf(clinic):
    from app.models import VaccineInventory

    db = clinic["db"]
    for batch in VaccineInventory.query.all():
        batch.qty_used = batch.qty_received
    db.session.commit()


def _reminded(clinic, patient_id=None, when=None):
    """A "your dose is due" message that went out for this brand."""
    from app.models import MessageLog

    db = clinic["db"]
    log = MessageLog(patient_id=patient_id or clinic["ids"]["child"],
                     body="due", to_phone="01001234567", status="link",
                     template_type="vaccine_due",
                     vaccine_brand_id=clinic["ids"]["brand"])
    if when:
        log.created_at = when
    db.session.add(log)
    db.session.commit()
    return log


def _restock(clinic, qty=5):
    from app.models import VaccineInventory

    db = clinic["db"]
    db.session.add(VaccineInventory(brand_id=clinic["ids"]["brand"],
                                    lot_number="NEW", qty_received=qty,
                                    expiry_date=date(2030, 1, 1)))
    db.session.commit()


def _brand(clinic):
    from app.models import VaccineBrand

    return clinic["db"].session.get(VaccineBrand, clinic["ids"]["brand"])


# ============================================== who is called back ==========
def test_a_family_that_was_reminded_and_still_needs_it_is_called(clinic):
    """The whole point: they did what they were asked and found nothing."""
    from app.utils import vaccine_back

    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)
        _restock(clinic)

        waiting = vaccine_back.waiting_for(_brand(clinic))
        assert [row["patient"].id for row in waiting] == [clinic["ids"]["child"]]


def test_nobody_is_called_while_the_shelf_is_still_empty(clinic):
    """A message saying "come and take it" when there is nothing to take is
    worse than silence — it is the same disappointment, twice."""
    from app.utils import vaccine_back

    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)

        assert vaccine_back.waiting_for(_brand(clinic)) == []


def test_a_child_who_has_since_had_the_dose_is_not_chased(clinic):
    """They may have had it here, or at a government unit, or anywhere the
    clinic later wrote down. The schedule is asked, not the message log."""
    from app.utils import vaccine_back

    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)
        _restock(clinic)
        # The rest of the course, given.
        _started_course(clinic, dose=2, given=date(2025, 5, 1))
        _started_course(clinic, dose=3, given=date(2025, 7, 1))

        assert vaccine_back.waiting_for(_brand(clinic)) == []


def test_somebody_who_was_never_reminded_is_left_alone(clinic):
    """"الناس اللي وعدها ما جاش زي ما هما" — this is not a broadcast to
    everyone due. It is a reply to the people the clinic already wrote to."""
    from app.utils import vaccine_back

    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _restock(clinic)          # stock, a due child, but no reminder sent

        assert vaccine_back.waiting_for(_brand(clinic)) == []


def test_a_family_is_not_told_twice_about_one_delivery(clinic):
    """A clinic that receives three boxes in a week must not send the same
    family three "it has arrived" messages."""
    from app.utils import vaccine_back

    db = clinic["db"]
    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)
        _restock(clinic)

        first = vaccine_back.notify(_brand(clinic))
        db.session.commit()
        assert len(first) == 1

        assert vaccine_back.waiting_for(_brand(clinic)) == [], \
            "the same family is queued for a second message"


def test_the_next_delivery_calls_them_again(clinic):
    """If they still have not come and a *new* delivery arrives, that is a new
    reason to write — the previous "already told" must not be permanent."""
    from app.utils import vaccine_back

    db = clinic["db"]
    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)
        _restock(clinic)
        vaccine_back.notify(_brand(clinic))
        db.session.commit()

        _empty_the_shelf(clinic)
        _restock(clinic, qty=3)          # a month later, a new box
        assert len(vaccine_back.waiting_for(_brand(clinic))) == 1


def test_the_longest_wait_is_first(clinic):
    """The family put off since March is called before the one from Sunday."""
    from app.models import Patient
    from app.utils import vaccine_back

    db = clinic["db"]
    with clinic["app"].app_context():
        other = Patient(patient_number="P-B", full_name="أخ", gender="male",
                        date_of_birth=date(2024, 1, 1), is_active=True)
        db.session.add(other)
        db.session.commit()
        _started_course(clinic)
        _started_course(clinic, patient_id=other.id)
        _empty_the_shelf(clinic)
        _reminded(clinic, when=datetime.utcnow() - timedelta(days=2))
        _reminded(clinic, patient_id=other.id,
                  when=datetime.utcnow() - timedelta(days=60))
        _restock(clinic)

        waiting = vaccine_back.waiting_for(_brand(clinic))
        assert [row["patient"].patient_number for row in waiting][0] == "P-B"


# ============================================== the message itself ==========
def test_the_message_records_which_vaccine_it_was_about(clinic):
    """Without it, the next delivery cannot tell who has already heard — which
    is the same column that makes the whole feature answerable."""
    from app.models import MessageLog
    from app.utils import vaccine_back

    db = clinic["db"]
    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)
        _reminded(clinic)
        _restock(clinic)

        vaccine_back.notify(_brand(clinic))
        db.session.commit()

        log = MessageLog.query.filter_by(template_type="vaccine_back").one()
        assert log.vaccine_brand_id == clinic["ids"]["brand"]
        assert log.patient_id == clinic["ids"]["child"]
        assert log.body, "an empty message was queued"


def test_both_languages_carry_the_wording(clinic):
    """A clinic in English must not send a blank message, or the key."""
    import json

    for lang in ("ar", "en"):
        path = os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                            "locales", f"{lang}.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["occasions"].get("occ_vaccine_back"), f"{lang} has no label"


def test_the_type_has_a_default_body(clinic):
    """Every managed notification is seeded with wording, so a clinic that has
    not written its own still sends a sentence."""
    from app.models import TEMPLATE_DEFAULTS, TEMPLATE_VARIABLES

    assert TEMPLATE_DEFAULTS.get("vaccine_back")
    assert "patient" in TEMPLATE_VARIABLES.get("vaccine_back", [])


# ============================================== what already existed ========
def test_the_reminder_still_goes_out_with_an_empty_shelf(clinic):
    """"يبعت يقول للحالة بالتذكير عادي". This has always been true and is
    pinned here so a later "don't remind what we can't give" does not quietly
    take it away: a clinic that goes silent loses the child to the pharmacy."""
    from app.utils.vaccines import patient_due_reminders
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        _started_course(clinic)
        _empty_the_shelf(clinic)

        patient = db.session.get(Patient, clinic["ids"]["child"])
        assert patient_due_reminders(patient), \
            "an empty fridge silenced the reminder"


def test_the_order_forecast_is_what_is_needed_minus_what_is_there(clinic):
    """"محتاج ١٢ تطعيم من ده لأن عندك ١٢ حالة مستحقة" — already built, pinned
    so it stays honest about the shelf."""
    from app.utils.vaccine_due import due_list, order_suggestion

    with clinic["app"].app_context():
        _started_course(clinic)
        rows = due_list()
        order = order_suggestion(rows)
        assert order, "nothing was suggested for a child who is due"
        first = order[0]
        assert first["to_order"] == max(first["needed"] - first["in_stock"], 0)
