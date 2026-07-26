"""The doctor's day: procedures done, doses given, the child measured.

Three things the doctor records, each of which has to come out right somewhere
else entirely — a procedure has to reach the till, a dose has to come out of
the right box in the fridge and off the right line of the schedule, and a
measurement has to land on the right curve.

The cases here are the ones that actually happen in a clinic: the same dose
offered twice, a first dose the child had at a government unit, the
government vaccine that isn't the clinic's to sell, a procedure added after
the family already paid.
"""
from datetime import date, timedelta

import pytest


# --------------------------------------------------------------- helpers --
def _stock(clinic):
    from app.models import VaccineInventory

    with clinic["app"].app_context():
        return {b.lot_number: (b.qty_used or 0)
                for b in VaccineInventory.query.all()}


def _doses(clinic):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        return [{"number": d.dose_number, "lot": d.lot_number,
                 "outside": d.given_outside, "place": d.outside_place,
                 "batch": d.inventory_id, "doctor": d.doctor_id,
                 "invoice": d.invoice_id, "vaccine": d.vaccine_id}
                for d in PatientVaccine.query.order_by(PatientVaccine.id).all()]


def _give(client, clinic, **extra):
    data = {"vaccine_id": clinic["ids"]["pcv"], "brand_id": clinic["ids"]["brand"]}
    data.update(extra)
    return client.post(f"/visits/{clinic['ids']['visit']}/give-vaccine",
                       data=data, follow_redirects=True)


def _measure(client, clinic, **fields):
    data = {"record_date": date.today().isoformat()}
    data.update(fields)
    return client.post(f"/growth/{clinic['ids']['child']}/add", data=data,
                       follow_redirects=True)


def _records(clinic):
    from app.models import GrowthRecord

    with clinic["app"].app_context():
        return [{"w": r.weight_kg, "h": r.height_cm, "hc": r.head_circ_cm,
                 "bmi": r.bmi, "date": r.record_date}
                for r in GrowthRecord.query.order_by(GrowthRecord.id).all()]


def _checkout_lines(client, clinic):
    """The lines reception is actually offered when billing the visit.

    Read from the form's prefill payload, not from the page text: every
    service in the clinic appears in the dropdown, so searching the HTML for a
    name proves only that the service exists.
    """
    import json
    import re

    body = client.get(
        f"/finance/invoices/new?visit_id={clinic['ids']['visit']}"
    ).get_data(as_text=True)
    match = re.search(r"const prefill = (.*?);\n", body, re.S)
    assert match, "the billing form stopped emitting its prefill"
    return json.loads(match.group(1)) or []


def _collect(client, clinic, drop=None):
    """Bill the visit the way the browser does: submit the offered lines back.

    Hand-building the POST would prove the route works on data the real form
    never sends — the interesting cases here are exactly about which hidden
    fields survive. ``drop`` removes lines whose description contains it,
    which is the cashier deleting a row before collecting.
    """
    lines = [line for line in _checkout_lines(client, clinic)
             if not (drop and drop in line["description"])]
    data = {"patient_id": clinic["ids"]["child"],
            "doctor_id": clinic["ids"]["doctor"],
            "visit_id": clinic["ids"]["visit"],
            "line_service_id": [str(ln.get("service_id") or "") for ln in lines],
            "line_description": [ln["description"] for ln in lines],
            "line_unit_price": [str(ln.get("unit_price") or 0) for ln in lines],
            "line_quantity": [str(ln.get("quantity") or 1) for ln in lines],
            "line_no_commission": [str(ln.get("no_commission") or "0")
                                   for ln in lines],
            "line_brand_id": [str(ln.get("brand_id") or "") for ln in lines],
            "line_dose_id": [str(ln.get("dose_id") or "") for ln in lines],
            "line_vs_id": [str(ln.get("vs_id") or "") for ln in lines]}
    return client.post("/finance/invoices/new", data=data, follow_redirects=True)


# ====================================================== the procedures ====
def test_a_procedure_the_doctor_did_is_waiting_to_be_billed(clinic):
    from app.models import VisitService

    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/services",
                data={"service_id": clinic["ids"]["nebul"], "quantity": "2"},
                follow_redirects=True)
    with clinic["app"].app_context():
        done = VisitService.query.one()
        assert done.quantity == 2
        assert done.invoice_id is None, "not billed until reception collects"


def test_the_till_picks_up_what_the_doctor_added(clinic):
    """The doctor adds a nebuliser session; reception opens the checkout and
    it's already on the bill. Anything less and the clinic works for free."""
    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/services",
                data={"service_id": clinic["ids"]["nebul"], "quantity": "2"},
                follow_redirects=True)

    desk = clinic["sign_in"]("boss")
    offered = _checkout_lines(desk, clinic)
    assert any("تنفس" in line["description"] for line in offered)


def test_a_billed_procedure_is_not_billed_again(clinic):
    """It was added on Sunday, collected on Sunday. On Monday it must not
    reappear on the next bill."""
    from app.models import VisitService

    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/services",
                data={"service_id": clinic["ids"]["nebul"], "quantity": "1"},
                follow_redirects=True)

    desk = clinic["sign_in"]("boss")
    _collect(desk, clinic)

    with clinic["app"].app_context():
        assert VisitService.query.one().invoice_id is not None
    offered = _checkout_lines(desk, clinic)
    assert not any("تنفس" in line["description"] for line in offered), \
        "already paid for, still being offered"


def test_the_doctors_cut_follows_the_procedures_own_rate(clinic):
    """The exam pays 40%, the nebuliser 50%. A bill with both owes the
    doctor each at its own rate, not one blended number."""
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"]),
                            str(clinic["ids"]["nebul"])],
        "line_description": ["كشف", "جلسة تنفس"],
        "line_unit_price": ["200", "150"], "line_quantity": ["1", "1"],
    }, follow_redirects=True)
    with clinic["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.total == 350.0
        assert invoice.doctor_share_total == 155.0        # 80 + 75
        assert invoice.clinic_share_total == 195.0


def test_a_discount_shrinks_the_doctors_cut_with_it(clinic):
    """The clinic gave the discount; the doctor's percentage is of what was
    actually charged, not of the list price."""
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"])],
        "line_description": ["كشف"], "line_unit_price": ["200"],
        "line_quantity": ["1"], "line_discount_value": ["50"],
    }, follow_redirects=True)
    with clinic["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.total == 150.0
        assert invoice.doctor_share_total == 60.0          # 40% of 150, not 200


def test_a_percentage_discount_is_a_percentage(clinic):
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"])],
        "line_description": ["كشف"], "line_unit_price": ["200"],
        "line_quantity": ["1"], "line_discount_value": ["25"],
        "line_discount_is_percent": ["1"],
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert Invoice.query.one().total == 150.0


def test_a_discount_cannot_exceed_the_line(clinic):
    """A 500 discount on a 200 line is a typo, not a 300 refund."""
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"])],
        "line_description": ["كشف"], "line_unit_price": ["200"],
        "line_quantity": ["1"], "line_discount_value": ["500"],
    }, follow_redirects=True)
    with clinic["app"].app_context():
        assert Invoice.query.one().total == 0.0


# ====================================================== the vaccinations ==
def test_a_dose_comes_out_of_the_box_that_expires_first(clinic):
    """Two lots in the fridge. The one going out of date first is the one
    used — the other way round, a clinic throws away what it paid for."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    assert _stock(clinic) == {"LATE": 0, "SOON": 1, "GOV": 0}


def test_the_dose_records_which_lot_it_came_from(clinic):
    """When a lot is recalled, the clinic has to be able to say which
    children got it."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    dose = _doses(clinic)[0]
    assert dose["lot"] == "SOON" and dose["batch"] is not None


def test_the_doctor_who_gave_it_is_credited(clinic):
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    assert _doses(clinic)[0]["doctor"] == clinic["ids"]["doctor"]


def test_doses_are_given_in_order(clinic):
    """Nobody types the dose number; the schedule knows which one is next."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    _give(doctor, clinic)
    assert [d["number"] for d in _doses(clinic)] == [1, 2]


def test_the_same_dose_is_not_given_twice(clinic):
    """The commonest real mistake: two people record the same dose, the
    schedule silently shifts, and the child is one dose short at school."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    before = _stock(clinic)
    _give(doctor, clinic, dose_number="1")
    assert len(_doses(clinic)) == 1
    assert _stock(clinic) == before, "a refused dose still came out of the fridge"


def test_when_the_course_is_finished_there_is_nothing_left_to_give(clinic):
    doctor = clinic["sign_in"]("doc")
    for _ in range(3):
        _give(doctor, clinic)
    _give(doctor, clinic)                       # a fourth attempt
    assert len(_doses(clinic)) == 3


def test_a_dose_given_at_a_government_unit_is_recorded_but_not_deducted(clinic):
    """The first dose was elsewhere. It has to go on the card — otherwise the
    schedule is wrong for years — without touching the clinic's fridge."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic, dose_number="1", given_outside="1")
    assert _stock(clinic) == {"LATE": 0, "SOON": 0, "GOV": 0}
    dose = _doses(clinic)[0]
    assert dose["outside"] is True and dose["batch"] is None


def test_after_an_outside_first_dose_the_clinic_gives_the_second(clinic):
    """Which is the entire reason for recording it."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic, dose_number="1", given_outside="1")
    _give(doctor, clinic)
    given = _doses(clinic)
    assert [d["number"] for d in given] == [1, 2]
    assert given[1]["outside"] is False and given[1]["batch"] is not None


def test_the_government_vaccine_is_not_taken_from_clinic_stock(clinic):
    """It isn't the clinic's to sell, and its stock isn't the clinic's to
    spend."""
    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/give-vaccine",
                data={"vaccine_id": clinic["ids"]["opv"]}, follow_redirects=True)
    assert _stock(clinic)["GOV"] == 0
    assert len(_doses(clinic)) == 1, "the dose still belongs on the card"


def test_a_dose_given_in_the_clinic_reaches_the_bill(clinic):
    """Vaccines are given by the doctor and paid for at the desk. The dose
    has to be waiting there — a 900-pound vial is not something to lose."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    offered = _checkout_lines(desk, clinic)
    vaccine_lines = [line for line in offered if "Prevenar" in line["description"]]
    assert len(vaccine_lines) == 1
    assert vaccine_lines[0]["unit_price"] == 900


def test_the_dose_given_elsewhere_is_never_charged_for(clinic):
    """Billing a family for a dose a government unit gave them is the kind of
    mistake that ends a clinic's reputation."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic, dose_number="1", given_outside="1")

    assert len(_doses(clinic)) == 1, "the dose should still be on the card"
    desk = clinic["sign_in"]("boss")
    offered = _checkout_lines(desk, clinic)
    assert not any("Prevenar" in line["description"] for line in offered)


def test_the_free_vaccine_is_not_charged_for(clinic):
    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/give-vaccine",
                data={"vaccine_id": clinic["ids"]["opv"]}, follow_redirects=True)

    assert len(_doses(clinic)) == 1, "the dose should still be on the card"
    desk = clinic["sign_in"]("boss")
    offered = _checkout_lines(desk, clinic)
    assert not any("شلل" in line["description"] for line in offered)


def test_a_billed_dose_is_marked_billed(clinic):
    """So the next bill doesn't charge for it again."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    _collect(desk, clinic)
    assert _doses(clinic)[0]["invoice"] is not None


def test_a_dose_left_off_the_bill_is_not_marked_as_paid(clinic):
    """The cashier deletes the vaccine line and collects the exam only.

    The dose must not be stamped with that invoice. Stamping it treats it as
    paid for, drops it off the "not billed yet" list, and 900 pounds leaves
    the clinic with nothing anywhere recording that it was owed. A dose is
    paid for when something charged for it, not because it happened today.
    """
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    _collect(desk, clinic, drop="Prevenar")

    assert _doses(clinic)[0]["invoice"] is None


def test_a_dose_left_off_the_bill_is_still_owed_tomorrow(clinic):
    """Not being marked paid is only half of it — it has to come back to the
    desk, or the money is lost just as quietly."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    _collect(desk, clinic, drop="Prevenar")

    offered = _checkout_lines(desk, clinic)
    assert any("Prevenar" in line["description"] for line in offered)


def test_a_procedure_left_off_the_bill_is_not_marked_as_paid(clinic):
    """The same rule for the doctor's work: taken off the bill means unbilled,
    not free."""
    from app.models import VisitService

    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/services",
                data={"service_id": clinic["ids"]["nebul"], "quantity": "1"},
                follow_redirects=True)

    desk = clinic["sign_in"]("boss")
    _collect(desk, clinic, drop="تنفس")

    with clinic["app"].app_context():
        assert VisitService.query.one().invoice_id is None
    assert any("تنفس" in line["description"]
               for line in _checkout_lines(desk, clinic))


def test_a_hand_typed_vaccine_line_still_settles_the_dose(clinic):
    """Reception bills the vaccine themselves rather than from the prefill.
    The line names the brand, and that is enough to settle one dose of it —
    otherwise the dose is charged for and then offered again tomorrow."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "visit_id": clinic["ids"]["visit"],
        "line_service_id": [""], "line_description": ["Prevenar"],
        "line_unit_price": ["900"], "line_quantity": ["1"],
        "line_brand_id": [str(clinic["ids"]["brand"])],
    }, follow_redirects=True)

    assert _doses(clinic)[0]["invoice"] is not None


def test_one_line_settles_one_dose_not_every_dose(clinic):
    """Two doses given, one paid for. The other is still owed."""
    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    _give(doctor, clinic)

    desk = clinic["sign_in"]("boss")
    desk.post("/finance/invoices/new", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "visit_id": clinic["ids"]["visit"],
        "line_service_id": [""], "line_description": ["Prevenar"],
        "line_unit_price": ["900"], "line_quantity": ["1"],
        "line_brand_id": [str(clinic["ids"]["brand"])],
    }, follow_redirects=True)

    billed = [d["invoice"] for d in _doses(clinic)]
    assert sum(1 for b in billed if b is not None) == 1


def test_which_dose_it_was_is_on_the_record(clinic):
    """"A dose of the pentavalent" tells the next clinic nothing. Which one
    it was decides everything that follows."""
    from app.models import PatientVaccine, VaccineBrand
    from app.utils.dose_labels import dose_label, next_dose_text

    doctor = clinic["sign_in"]("doc")
    _give(doctor, clinic)
    with clinic["app"].app_context():
        dose = PatientVaccine.query.one()
        brand = clinic["db"].session.get(VaccineBrand, clinic["ids"]["brand"])
        assert dose_label(dose.dose_number, brand=brand) == "الجرعة الأولى"
        line = next_dose_text(dose.patient, dose.vaccine, brand, dose.dose_number)
        assert "الجرعة الثانية" in line


# ======================================================= the measurements ==
def test_weight_and_height_give_a_bmi(clinic):
    doctor = clinic["sign_in"]("doc")
    _measure(doctor, clinic, weight_kg="9.5", height_cm="75")
    record = _records(clinic)[0]
    assert record["w"] == 9.5 and record["h"] == 75.0
    assert record["bmi"] == 16.9


def test_one_measurement_on_its_own_is_enough(clinic):
    """A nurse who only had time for the head circumference still recorded
    something worth keeping."""
    doctor = clinic["sign_in"]("doc")
    _measure(doctor, clinic, head_circ_cm="45")
    record = _records(clinic)[0]
    assert record["hc"] == 45.0 and record["bmi"] is None


def test_an_empty_measurement_is_not_recorded(clinic):
    doctor = clinic["sign_in"]("doc")
    _measure(doctor, clinic)
    assert _records(clinic) == []


def test_a_date_that_is_not_a_date_records_nothing(clinic):
    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/growth/{clinic['ids']['child']}/add",
                data={"record_date": "٣٢ يناير", "weight_kg": "9"},
                follow_redirects=True)
    assert _records(clinic) == []


@pytest.mark.parametrize("indicator,value,expected_status", [
    ("wfa", 7.9, "normal"),        # a 6-month-old boy on the 50th centile
    ("wfa", 5.5, "alert"),         # severely underweight
    ("hfa", 67.6, "normal"),
    ("hcfa", 43.3, "normal"),
])
def test_a_measurement_is_scored_against_the_standard(clinic, indicator, value,
                                                      expected_status):
    """The number alone means nothing to a parent. Where it sits on the curve
    is the whole reason for measuring."""
    from app.utils.growth import compute_point, status_for_z

    with clinic["app"].app_context():
        point = compute_point("WHO", indicator, "male", date(2025, 1, 1),
                              date(2025, 7, 1), value)
        assert point is not None
        assert status_for_z(point["z"]) == expected_status


def test_the_percentile_reads_the_way_a_parent_hears_it(clinic):
    from app.utils.growth import compute_point

    with clinic["app"].app_context():
        point = compute_point("WHO", "wfa", "male", date(2025, 1, 1),
                              date(2025, 7, 1), 7.9)
        assert 45 <= point["percentile"] <= 55
        assert abs(point["z"]) < 0.1


def test_a_teenager_is_not_plotted_on_the_nought_to_five_chart(clinic):
    """The WHO standard stops at five years. Reading a fifteen-year-old
    against it doesn't give a wrong answer — it gives a confident one."""
    from app.models import GrowthRecord, Patient

    with clinic["app"].app_context():
        teen = Patient(patient_number="P2", full_name="مراهق", gender="male",
                       date_of_birth=date(2010, 1, 1), is_active=True)
        clinic["db"].session.add(teen)
        clinic["db"].session.flush()
        clinic["db"].session.add(GrowthRecord(patient_id=teen.id,
                                              record_date=date.today(),
                                              weight_kg=55, source="manual"))
        clinic["db"].session.commit()
        teen_id = teen.id

    doctor = clinic["sign_in"]("doc")
    body = doctor.get(f"/growth/{teen_id}/data?ref=WHO&indicator=wfa").get_json()
    assert body["points"] == [], "a 15-year-old scored on the 0–5 standard"


def test_measurements_are_kept_in_order_over_time(clinic):
    """A growth chart is the shape of the line, not the last dot."""
    doctor = clinic["sign_in"]("doc")
    for days, weight in ((60, "6.0"), (30, "7.0"), (0, "7.9")):
        doctor.post(f"/growth/{clinic['ids']['child']}/add", data={
            "record_date": (date.today() - timedelta(days=days)).isoformat(),
            "weight_kg": weight}, follow_redirects=True)
    body = doctor.get(
        f"/growth/{clinic['ids']['child']}/data?ref=WHO&indicator=wfa").get_json()
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)
    assert len(dates) == 3
