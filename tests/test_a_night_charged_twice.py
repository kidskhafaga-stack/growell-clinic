"""The daily bed charge — counted from the stay, charged once per night.

The third of the three things ``HOSPITAL_PLAN.md`` names for the inpatient
wards. Everything under it existed already: the stay knows its hours, the bed
knows where it is, the price list knows what things cost. What was missing is
the sentence joining them — *this child has been in four nights and nobody has
billed any of them.*

Five decisions are tested here, and every one of them is a way a family gets
an angry bill:

1. **A night, not a day.** In on Monday, out on Thursday is three nights. In
   and out the same afternoon is one, because a bed was made up and taken
   again. An open stay is charged to *yesterday*, never to tonight.
2. **Charged once.** The posting runs from the stay screen, from a discharge,
   and in principle nightly, so it has to be safe to run four times on the
   same Tuesday. A unique index does that; a flag somebody remembers to set
   does not.
3. **The rate is a service** — so the night is in the one price list, and so
   that having no rate means having no feature. A clinic that does not bill
   by the night sees nothing and is charged nothing.
4. **The price is snapshotted.** A price list edited in March must not rewrite
   what a family was billed in February.
5. **The night belongs to the bed at the end of it.** A child moved into
   intensive care at four in the afternoon spent that night in intensive
   care, and that is what the night cost.
6. **Emergency is charged by the hour**, and reported in one sentence:
   *"الإقامة بالساعة في الطوارىء خلي بالك"*. A child on a trolley for three
   hours who goes home has not spent a night anywhere, and billing one is not
   a rounding difference — it is a bill for something that did not happen.
7. **The price hangs off all three levels: bed, room, department.** Reported
   in the same breath: *"هي الفاتورة تفصيلية للسرير ولا الغرف ولا الحضانة"*.
   Most hospitals price the room — a single and a double are two prices for
   the same bed, and what differs is the walls — and the nursery prices the
   bed. The room level was missing.

And one that is not about money at all: **nothing is posted by opening a
page.** Money is written onto a family's account by somebody pressing
something.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A ward and an intensive care unit, priced differently."""
    from app.models import Service, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import bed_billing

    with clinic["app"].app_context():
        for module in ("observations", "beds", "ward", "icu", "emergency"):
            Setting.set(f"mod_enabled:{module}", "1")

        rates = {}
        for key, name, price in (("ward", "ليلة داخلي", 500),
                                 ("icu", "ليلة عناية", 2000),
                                 ("incubator", "ليلة حضّانة", 1200),
                                 ("single", "غرفة مفردة", 800),
                                 ("er", "ساعة ملاحظة طوارئ", 150)):
            service = Service(name=name, category="other", price=price)
            clinic["db"].session.add(service)
            clinic["db"].session.flush()
            rates[key] = service.id

        for key, kind, beds in (("ward", "ward", ["د١", "د٢"]),
                                ("icu", "icu", ["ع١"]),
                                ("er", "emergency", ["ط١"])):
            unit = Unit(name=f"قسم {key}", kind=kind,
                        rate_service_id=rates[key],
                        billing_basis=bed_billing.default_basis(kind))
            clinic["db"].session.add(unit)
            clinic["db"].session.flush()
            space = Space(unit_id=unit.id, name=f"حيّز {key}", kind="room")
            clinic["db"].session.add(space)
            clinic["db"].session.flush()
            for order, name in enumerate(beds):
                clinic["db"].session.add(
                    Bed(space_id=space.id, name=name, sort_order=order))
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
        clinic["rates"] = rates
    return clinic


def _child(clinic, name):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"N{name}", full_name=name,
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=700))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, bed_name="د١", days_ago=0):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(clinic["beds"][bed_name]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        clinic["db"].session.commit()
        return row.id


def _stay(clinic, admission_id):
    from app.models.admission import Admission

    return clinic["db"].session.get(Admission, admission_id)


def _charges(clinic, admission_id):
    from app.models.bed_charge import BedCharge

    with clinic["app"].app_context():
        return (BedCharge.query
                .filter_by(admission_id=admission_id)
                .order_by(BedCharge.on_date).all())


# --------------------------------------------------------- a night, not a day
def test_three_nights_between_monday_and_thursday(hospital):
    from app.utils import bed_billing
    from app.utils.clock import local_today

    child = _child(hospital, "تلات_ليالي")
    admission = _admit(hospital, child, days_ago=3)

    with hospital["app"].app_context():
        from app.utils import beds as place

        stay = _stay(hospital, admission)
        place.discharge(stay, "home")
        hospital["db"].session.commit()
        owed = bed_billing.nights(stay)

    assert len(owed) == 3
    assert owed[0] == local_today() - timedelta(days=3)
    assert owed[-1] == local_today() - timedelta(days=1)


def test_in_and_out_the_same_afternoon_is_still_one_night(hospital):
    """A bed was made up and taken again. Every hospital in the world charges
    for it, and a floor of zero would have made a whole class of stay free."""
    from app.utils import bed_billing

    child = _child(hospital, "نفس_اليوم")
    admission = _admit(hospital, child)

    with hospital["app"].app_context():
        from app.utils import beds as place

        stay = _stay(hospital, admission)
        place.discharge(stay, "home")
        hospital["db"].session.commit()
        assert len(bed_billing.nights(stay)) == 1


def test_an_open_stay_is_never_charged_for_tonight(hospital):
    """Charging a night before it has happened is how a family is billed for
    the night they went home in."""
    from app.utils import bed_billing
    from app.utils.clock import local_today

    child = _child(hospital, "لسه_جوه")
    admission = _admit(hospital, child, days_ago=2)

    with hospital["app"].app_context():
        owed = bed_billing.nights(_stay(hospital, admission))

    assert local_today() not in owed
    assert owed[-1] == local_today() - timedelta(days=1)
    assert len(owed) == 2


def test_a_stay_that_started_today_owes_nothing_yet(hospital):
    """The floor of one night applies to a stay that has **ended**, not to one
    that has begun.

    Written the other way first, and this test is what found it: a child
    admitted an hour ago was already owing tonight, in a file whose own
    docstring says charging a night before it has happened is how a family
    gets billed for the night they went home in.
    """
    from app.utils import bed_billing

    child = _child(hospital, "النهاردة")
    admission = _admit(hospital, child)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        assert bed_billing.nights(stay) == []
        assert bed_billing.outstanding(stay) == []
        assert bed_billing.post(stay)["periods"] == 0


# ------------------------------------------------------------ charged once ---
def test_pressing_twice_does_not_bill_a_night_twice(hospital):
    """**The test this file is named for.**

    The posting runs from the stay screen, from a discharge and in principle
    nightly, so it has to be safe to run again. A unique index makes it so;
    a flag somebody has to remember to set does not.
    """
    from app.utils import bed_billing

    child = _child(hospital, "مرتين")
    admission = _admit(hospital, child, days_ago=3)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        first = bed_billing.post(stay)
        hospital["db"].session.commit()
        second = bed_billing.post(_stay(hospital, admission))
        hospital["db"].session.commit()

    assert first["periods"] == 3
    assert second["periods"] == 0
    assert len(_charges(hospital, admission)) == 3


def test_the_database_itself_refuses_the_second_row(hospital):
    """Not a check in Python. Two people pressing in the same second on two
    screens is exactly how a family gets billed twice for a Tuesday, and only
    the database can refuse that."""
    from sqlalchemy.exc import IntegrityError

    from app.models.bed_charge import BedCharge
    from app.utils import bed_billing

    child = _child(hospital, "قاعدة")
    admission = _admit(hospital, child, days_ago=2)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        bed_billing.post(stay)
        hospital["db"].session.commit()
        night = _charges(hospital, admission)[0].on_date

        hospital["db"].session.add(BedCharge(
            admission_id=admission, patient_id=child, on_date=night,
            unit_price=500, quantity=1, basis="night"))
        with pytest.raises(IntegrityError):
            hospital["db"].session.commit()
        hospital["db"].session.rollback()


def test_a_stay_gets_one_invoice_not_one_a_night(hospital):
    """Without the link, eleven days would raise eleven bills — or fall into
    the outpatient one-invoice-per-day rule and land on whichever bill the
    desk happened to open that morning."""
    from app.models.invoice import Invoice
    from app.utils import bed_billing

    child = _child(hospital, "فاتورة_واحدة")
    admission = _admit(hospital, child, days_ago=4)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        bed_billing.post(stay)
        hospital["db"].session.commit()

        bills = Invoice.query.filter_by(admission_id=admission).all()
        assert len(bills) == 1
        assert len(bills[0].items) == 4
        assert bills[0].total == 4 * 500


def test_a_second_posting_lands_on_the_same_invoice(hospital):
    """The stay's invoice is found, not raised again.

    The first version of this test posted everything in one press, so a
    ``invoice_for`` that raised a fresh bill every call passed it — the
    function was only ever entered once. Nights are posted on Tuesday and
    again on Thursday, and both belong to one account.
    """
    from app.models.invoice import Invoice
    from app.utils import bed_billing
    from app.utils.clock import local_today

    child = _child(hospital, "على_مرتين")
    admission = _admit(hospital, child, days_ago=4)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        first = bed_billing.post(stay, upto=local_today() - timedelta(days=3))
        hospital["db"].session.commit()
        second = bed_billing.post(_stay(hospital, admission))
        hospital["db"].session.commit()

        assert first["periods"] and second["periods"]
        bills = Invoice.query.filter_by(admission_id=admission).all()
        assert len(bills) == 1
        assert len(bills[0].items) == first["periods"] + second["periods"]


# ------------------------------------------------------- the rate is a switch
def test_a_clinic_that_sets_no_rate_is_never_charged(hospital):
    """The feature's own switch. A clinic that does not bill by the night
    sees nothing and is charged nothing — the same shape as a module that is
    off, rather than a list of free days."""
    from app.models.place import Unit
    from app.utils import bed_billing

    child = _child(hospital, "بدون_سعر")
    admission = _admit(hospital, child, days_ago=3)

    with hospital["app"].app_context():
        for unit in Unit.query.all():
            unit.rate_service_id = None
        hospital["db"].session.commit()

        stay = _stay(hospital, admission)
        assert bed_billing.outstanding(stay) == []
        assert bed_billing.post(stay)["periods"] == 0
        assert _charges(hospital, admission) == []


def test_the_card_is_absent_when_there_is_no_rate(hospital):
    from app.i18n import t
    from app.models.place import Unit

    child = _child(hospital, "كارت")
    admission = _admit(hospital, child, days_ago=3)
    client = hospital["sign_in"]("boss")

    page = client.get(f"/beds/admission/{admission}").get_data(as_text=True)
    assert "data-due-nights" in page

    with hospital["app"].app_context():
        for unit in Unit.query.all():
            unit.rate_service_id = None
        hospital["db"].session.commit()
        heading = None
    with hospital["app"].test_request_context("/"):
        heading = t("beds.nights")

    page = client.get(f"/beds/admission/{admission}").get_data(as_text=True)
    assert "data-due-nights" not in page
    assert heading not in page


def test_the_rate_can_be_set_from_the_screen(hospital):
    """A feature nobody can switch on is a feature that does not exist —
    which this project has walked into six times."""
    from app.models.place import Unit

    with hospital["app"].app_context():
        unit = Unit.query.filter_by(kind="ward").first()
        unit.rate_service_id = None
        hospital["db"].session.commit()
        unit_id = unit.id

    client = hospital["sign_in"]("boss")
    page = client.get("/beds/setup").get_data(as_text=True)
    assert "data-unit-rate" in page and "/beds/rate" in page

    client.post("/beds/rate", data={"unit_id": unit_id,
                                    "service_id": hospital["rates"]["ward"]},
                follow_redirects=True)
    with hospital["app"].app_context():
        assert (hospital["db"].session.get(Unit, unit_id).rate_service_id
                == hospital["rates"]["ward"])


def test_a_bed_may_cost_something_other_than_its_department(hospital):
    """The nursery is the case that forces it: one bay holds a cot, an
    incubator and a transport capsule, and they are not the same money."""
    from app.models.place import Bed
    from app.utils import bed_billing

    child = _child(hospital, "سرير_غالي")
    admission = _admit(hospital, child, days_ago=2)

    with hospital["app"].app_context():
        bed = hospital["db"].session.get(Bed, hospital["beds"]["د١"])
        bed.rate_service_id = hospital["rates"]["incubator"]
        hospital["db"].session.commit()

        stay = _stay(hospital, admission)
        assert all(row["service"].price == 1200
                   for row in bed_billing.outstanding(stay))


# ------------------------------------------------- emergency, by the hour ---
def test_three_hours_in_emergency_is_not_a_night(hospital):
    """**Reported in one sentence:** *"الإقامة بالساعة في الطوارىء خلي بالك"*.

    A child on a trolley for three hours who goes home has not spent a night
    anywhere. Billing one is not a rounding difference — it is a bill for
    something that did not happen, and it is three times the money.
    """
    from app.utils import bed_billing

    child = _child(hospital, "طوارئ_تلات_ساعات")
    admission = _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        from app.utils import beds as place

        stay = _stay(hospital, admission)
        stay.admitted_at = datetime.utcnow() - timedelta(hours=3)
        for bed_stay in stay.stays:
            bed_stay.since = stay.admitted_at
        place.discharge(stay, "home")
        hospital["db"].session.commit()

        due = bed_billing.outstanding(_stay(hospital, admission))
        assert len(due) == 1
        assert due[0]["basis"] == bed_billing.HOUR
        assert due[0]["quantity"] == 3
        assert due[0]["amount"] == 3 * 150


def test_a_part_hour_rounds_up_and_never_below_one(hospital):
    """Twenty minutes on a trolley is an hour of a trolley. Rounding down
    would make the first hour of every emergency free, and most emergency
    stays are one hour."""
    from app.utils import bed_billing

    # 60 → 1 and 180 → 3 are the boundaries, and they are the reason the
    # duration is counted in whole minutes: measured to the microsecond, the
    # discharge lands a fraction of a second past the hour and the family is
    # billed for the next one.
    for minutes, expected in ((20, 1), (60, 1), (61, 2), (180, 3), (200, 4)):
        child = _child(hospital, f"دقايق{minutes}")
        admission = _admit(hospital, child, "ط١")
        with hospital["app"].app_context():
            from app.utils import beds as place

            stay = _stay(hospital, admission)
            stay.admitted_at = datetime.utcnow() - timedelta(minutes=minutes)
            for bed_stay in stay.stays:
                bed_stay.since = stay.admitted_at
            place.discharge(stay, "home")
            hospital["db"].session.commit()
            assert bed_billing.billable_hours(
                _stay(hospital, admission)) == expected, minutes


def test_an_hourly_stay_is_charged_when_it_ends_and_not_before(hospital):
    """How many hours it was is not known until the child leaves. Charging in
    instalments would put two lines on one bill for one visit — and would
    need a second row for the same date, which the unique index refuses."""
    from app.utils import bed_billing

    child = _child(hospital, "لسه_في_الطوارئ")
    admission = _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        stay.admitted_at = datetime.utcnow() - timedelta(hours=2)
        hospital["db"].session.commit()

        assert bed_billing.outstanding(_stay(hospital, admission)) == []
        assert bed_billing.post(_stay(hospital, admission))["periods"] == 0
        # But the screen can still say what it is coming to.
        assert bed_billing.hours_so_far(_stay(hospital, admission)) == 2


def test_the_running_hours_are_shown_while_the_stay_is_open(hospital):
    """So a family is told at the trolley rather than at the door."""
    from app.i18n import t

    child = _child(hospital, "بيعد")
    admission = _admit(hospital, child, "ط١")
    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        stay.admitted_at = datetime.utcnow() - timedelta(hours=1, minutes=55)
        hospital["db"].session.commit()

    page = hospital["sign_in"]("boss").get(
        f"/beds/admission/{admission}").get_data(as_text=True)
    assert "data-running-hours" in page
    with hospital["app"].test_request_context("/"):
        assert t("beds.hours_so_far", n=2) in page


def test_the_hours_reach_the_invoice_as_a_quantity(hospital):
    """One line, four hours, not four lines — and the line says so."""
    from app.models.invoice import Invoice
    from app.utils import bed_billing

    child = _child(hospital, "فاتورة_ساعات")
    admission = _admit(hospital, child, "ط١")

    with hospital["app"].app_context():
        from app.utils import beds as place

        stay = _stay(hospital, admission)
        stay.admitted_at = datetime.utcnow() - timedelta(hours=4)
        for bed_stay in stay.stays:
            bed_stay.since = stay.admitted_at
        place.discharge(stay, "home")
        bed_billing.post(_stay(hospital, admission))
        hospital["db"].session.commit()

        bill = Invoice.query.filter_by(admission_id=admission).one()
        assert len(bill.items) == 1
        assert bill.items[0].quantity == 4
        assert bill.total == 4 * 150
        assert "4h" in bill.items[0].description

    charges = _charges(hospital, admission)
    assert len(charges) == 1
    assert charges[0].basis == "hour" and charges[0].quantity == 4


def test_a_ward_is_still_charged_by_the_night(hospital):
    """The two bases sit side by side in one hospital, and the department
    decides which — not the code, and not a global setting."""
    from app.utils import bed_billing

    child = _child(hospital, "داخلي_بالليلة")
    admission = _admit(hospital, child, "د١", days_ago=2)

    with hospital["app"].app_context():
        due = bed_billing.outstanding(_stay(hospital, admission))
        assert [row["basis"] for row in due] == ["night", "night"]
        assert all(row["quantity"] == 1 for row in due)


def test_a_new_emergency_unit_is_hourly_without_anybody_saying_so(hospital):
    """A preset, editable afterwards. What it buys is that nobody has to know
    emergency is hourly before their first emergency bill comes out wrong."""
    from app.models.place import Unit
    from app.utils import bed_billing

    assert bed_billing.default_basis("emergency") == bed_billing.HOUR
    assert bed_billing.default_basis("ward") == bed_billing.NIGHT

    client = hospital["sign_in"]("boss")
    client.post("/beds/unit", data={"name": "طوارئ ٢", "kind": "emergency"},
                follow_redirects=True)
    with hospital["app"].app_context():
        made = Unit.query.filter_by(name="طوارئ ٢").one()
        assert made.billing_basis == bed_billing.HOUR


def test_the_basis_can_be_changed_from_the_screen(hospital):
    """A preset nobody can override is a rule, and this one is not a rule:
    a clinic that charges its observation ward by the night is not wrong."""
    from app.models.place import Unit

    with hospital["app"].app_context():
        unit_id = Unit.query.filter_by(kind="emergency").first().id

    page = hospital["sign_in"]("boss").get("/beds/setup").get_data(as_text=True)
    assert "data-basis" in page

    hospital["sign_in"]("boss").post(
        "/beds/rate",
        data={"unit_id": unit_id, "service_id": hospital["rates"]["er"],
              "billing_basis": "night"}, follow_redirects=True)
    with hospital["app"].app_context():
        assert (hospital["db"].session.get(Unit, unit_id).billing_basis
                == "night")


# ------------------------------------------- bed, then room, then department
def test_the_room_is_priced_between_the_bed_and_the_department(hospital):
    """**Reported:** *"هي الفاتورة تفصيلية للسرير ولا الغرف ولا الحضانة"*.

    Most hospitals price the room: a single and a double are two prices for
    the same bed, and what differs is the walls. The chain went bed →
    department and skipped the level in the middle.
    """
    from app.models.place import Bed, Space
    from app.utils import bed_billing

    with hospital["app"].app_context():
        bed = hospital["db"].session.get(Bed, hospital["beds"]["د١"])
        space = hospital["db"].session.get(Space, bed.space_id)

        # Nothing set on the bed or the room: the department answers.
        assert bed_billing.rate_for(bed).price == 500

        # The room answers over the department.
        space.rate_service_id = hospital["rates"]["single"]
        hospital["db"].session.commit()
        assert bed_billing.rate_for(bed).price == 800

        # And the bed answers over the room.
        bed.rate_service_id = hospital["rates"]["incubator"]
        hospital["db"].session.commit()
        assert bed_billing.rate_for(bed).price == 1200


def test_a_room_rate_reaches_the_bill(hospital):
    """Not only the resolver — the nights actually charged move with it."""
    from app.models.place import Bed, Space
    from app.utils import bed_billing

    child = _child(hospital, "غرفة_مفردة")
    admission = _admit(hospital, child, "د١", days_ago=2)

    with hospital["app"].app_context():
        bed = hospital["db"].session.get(Bed, hospital["beds"]["د١"])
        space = hospital["db"].session.get(Space, bed.space_id)
        space.rate_service_id = hospital["rates"]["single"]
        hospital["db"].session.commit()

        bed_billing.post(_stay(hospital, admission))
        hospital["db"].session.commit()

    assert [c.unit_price for c in _charges(hospital, admission)] == [800, 800]


def test_the_room_rate_can_be_set_from_the_screen(hospital):
    """The middle level needs a door of its own, or a clinic that prices by
    the room cannot say so."""
    from app.models.place import Bed, Space

    with hospital["app"].app_context():
        bed = hospital["db"].session.get(Bed, hospital["beds"]["د١"])
        space_id = bed.space_id

    client = hospital["sign_in"]("boss")
    assert "data-space-rate" in client.get("/beds/setup").get_data(as_text=True)

    client.post("/beds/rate",
                data={"space_id": space_id,
                      "service_id": hospital["rates"]["single"]},
                follow_redirects=True)
    with hospital["app"].app_context():
        assert (hospital["db"].session.get(Space, space_id).rate_service_id
                == hospital["rates"]["single"])


# ------------------------------------------------------------ the snapshot ---
def test_a_price_change_does_not_rewrite_last_months_bill(hospital):
    """The same rule every printed name in this program follows."""
    from app.models import Service
    from app.utils import bed_billing

    child = _child(hospital, "سعر_قديم")
    admission = _admit(hospital, child, days_ago=2)

    with hospital["app"].app_context():
        bed_billing.post(_stay(hospital, admission))
        hospital["db"].session.commit()

        service = hospital["db"].session.get(Service, hospital["rates"]["ward"])
        service.price = 900
        hospital["db"].session.commit()

    for charge in _charges(hospital, admission):
        assert charge.unit_price == 500
    with hospital["app"].app_context():
        from app.models.invoice import Invoice
        bill = Invoice.query.filter_by(admission_id=admission).one()
        assert bill.total == 2 * 500


# ---------------------------------------------- which bed did they sleep in --
def test_a_night_is_charged_at_the_bed_they_ended_it_in(hospital):
    """A child moved up to intensive care at four in the afternoon spent that
    night in intensive care, and that is what the night cost."""
    from app.models.place import Bed
    from app.utils import bed_billing
    from app.utils.clock import local_today, to_utc

    child = _child(hospital, "اتنقل")
    admission = _admit(hospital, child, days_ago=2)

    with hospital["app"].app_context():
        from app.utils import beds as place

        stay = _stay(hospital, admission)
        # Moved yesterday afternoon, ward -> intensive care.
        moved = to_utc(datetime.combine(local_today() - timedelta(days=1),
                                        datetime.min.time())
                       + timedelta(hours=16))
        place.move(stay, hospital["db"].session.get(Bed,
                                                    hospital["beds"]["ع١"]),
                   when=moved)
        hospital["db"].session.commit()

        prices = {row["on"]: row["service"].price
                  for row in bed_billing.outstanding(_stay(hospital, admission))}

    assert prices[local_today() - timedelta(days=2)] == 500     # the ward
    assert prices[local_today() - timedelta(days=1)] == 2000    # intensive care


# ---------------------------------------------------- nobody posts silently --
def test_opening_the_stay_screen_charges_nothing(hospital):
    """Money is written onto a family's account by somebody pressing
    something. A page that bills as a side effect of being looked at bills
    every time anybody looks."""
    child = _child(hospital, "بس_بيبص")
    admission = _admit(hospital, child, days_ago=3)

    client = hospital["sign_in"]("boss")
    for _ in range(3):
        client.get(f"/beds/admission/{admission}")

    assert _charges(hospital, admission) == []


def test_the_button_charges_them_and_says_what_it_did(hospital):
    child = _child(hospital, "دوسة")
    admission = _admit(hospital, child, days_ago=3)

    page = hospital["sign_in"]("boss").post(
        f"/beds/admission/{admission}/nights", data={},
        follow_redirects=True).get_data(as_text=True)

    charges = _charges(hospital, admission)
    assert len(charges) == 3
    # Said out loud rather than left to be discovered on the bill.
    assert "1500" in page or "1500.0" in page


def test_a_discharge_charges_the_nights_and_says_so(hospital):
    """A discharge is already a deliberate act with a form in front of it,
    and it is the one moment the whole stay is finally known."""
    child = _child(hospital, "خروج_وفاتورة")
    admission = _admit(hospital, child, days_ago=3)

    page = hospital["sign_in"]("boss").post(
        f"/beds/admission/{admission}/discharge",
        data={"outcome": "home"}, follow_redirects=True).get_data(as_text=True)

    assert len(_charges(hospital, admission)) == 3
    with hospital["app"].app_context():
        from app.models.invoice import Invoice
        number = Invoice.query.filter_by(admission_id=admission).one()
        assert number.invoice_number in page


# -------------------------------------------------------- the clinic's clock -
def test_a_child_admitted_after_midnight_is_billed_on_the_right_night(hospital):
    """A night is a thing a family counts on a calendar. For a Cairo clinic on
    a UTC server the two disagree for the first three hours of every day, which
    would put a child admitted at 1am on the previous night's bill."""
    from app.utils import bed_billing
    from app.utils.clock import local_today, to_utc

    child = _child(hospital, "بعد_نص_الليل")
    admission = _admit(hospital, child, days_ago=1)

    with hospital["app"].app_context():
        stay = _stay(hospital, admission)
        # One in the morning, the clinic's clock — which is the evening
        # *before* in UTC. Counted the naive way this stay would start a day
        # early and owe two nights instead of one.
        stay.admitted_at = to_utc(
            datetime.combine(local_today() - timedelta(days=1),
                             datetime.min.time()) + timedelta(hours=1))
        for bed_stay in stay.stays:
            bed_stay.since = stay.admitted_at
        hospital["db"].session.commit()

        assert bed_billing.nights(_stay(hospital, admission)) == [
            local_today() - timedelta(days=1)]


# --------------------------------------------------------------- migration ---
def test_the_new_columns_reach_a_clinic_that_already_has_the_tables():
    """`care_units` and `care_beds` are newer than the schema baseline, so the
    migration test cannot demand these. A clinic can: anybody already running
    the version that added the beds has those tables **without** these
    columns, and `create_all` adds tables, never columns to a table that
    exists."""
    from app.utils.schema import ADDITIONS

    covered = {(table, column) for table, column, _ddl in ADDITIONS}
    for table, column in (("care_units", "rate_service_id"),
                          ("care_units", "billing_basis"),
                          ("care_spaces", "rate_service_id"),
                          ("care_beds", "rate_service_id"),
                          ("invoices", "admission_id")):
        assert (table, column) in covered, f"{table}.{column}"


def test_the_guide_explains_the_charge():
    from app.utils.handbook import SECTIONS

    keys = {s["key"] for s in SECTIONS}
    assert "beds_nights" in keys
    for section in SECTIONS:
        if section["key"] == "beds_nights":
            assert section["module"] == "beds"
            assert len(section["lines"]) >= 4


def test_every_word_on_the_nights_card_exists_in_both_languages():
    import json

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        ar = json.load(fh)
    with open("app/i18n/locales/en.json", encoding="utf-8") as fh:
        en = json.load(fh)

    for key in ("nights", "nights_outstanding", "nights_all_posted",
                "post_nights", "nights_none", "nights_posted",
                "nights_charged_n", "nightly_rate", "no_rate",
                "rate_from_unit", "save_rate", "rate_saved", "rate_hint"):
        assert key in ar["beds"] and key in en["beds"]
        assert ar["beds"][key] != en["beds"][key]
