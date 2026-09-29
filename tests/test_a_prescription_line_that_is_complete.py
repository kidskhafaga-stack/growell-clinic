"""A prescription line that carries what GAHAR `MMS.11` (هـ) asks for.

Asked as part of «كان فى حاجه فى الروشته», with the rule this project keeps:
*«المهم المبداء بتاعنا الجودة وان الطبيب ميكتبش كتير»*.

What is held here:

* the form, the strength and the route come off the drug that was picked —
  the doctor types nothing new — and a name typed with no drug behind it has
  none of them rather than a guess;
* the height sits beside the weight, and the time beside the date;
* a «عند اللزوم» line asks what for and how often at most, and nothing else
  does — boxes left over from before the frequency changed are dropped;
* a line still missing something is said to be on the screen, never on the
  paper, and saving is never refused for it.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402


def _drug(clinic, **over):
    from app.models import Drug

    with clinic["app"].app_context():
        row = Drug(trade_name=over.pop("trade_name", "Brufen"), form="syrup",
                   strength="100mg/5ml", route="oral", **over)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _write(clinic, lines):
    data = {"patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"]}
    for key in ("item_drug_id", "item_name", "item_dose", "item_frequency",
                "item_duration", "item_instructions", "item_prn_reason",
                "item_prn_hours", "item_prn_max"):
        data[key] = [line.get(key[5:], "") for line in lines]
    reply = clinic["sign_in"]("doc").post("/prescriptions/new", data=data)
    assert reply.status_code == 302, reply.get_data(as_text=True)[:400]
    return int(reply.headers["Location"].rstrip("/").split("/")[-1])


def _items(clinic, rx_id):
    from app.models import Prescription

    with clinic["app"].app_context():
        rx = clinic["db"].session.get(Prescription, rx_id)
        return [{c: getattr(it, c) for c in (
            "drug_name", "form", "strength", "route", "frequency",
            "prn_reason", "prn_min_hours", "prn_max_per_day")} for it in rx.items]


def _page(clinic, rx_id):
    return clinic["sign_in"]("doc").get(f"/prescriptions/{rx_id}").get_data(as_text=True)


def test_the_form_strength_and_route_come_off_the_drug_picked(clinic):
    did = _drug(clinic)
    rx_id = _write(clinic, [
        {"drug_id": did, "name": "Brufen", "dose": "5ml", "frequency": "1x3",
         "duration": "5d"},
        {"name": "دوا مكتوب باليد", "dose": "5ml", "frequency": "1x3", "duration": "3d"}])
    picked, typed = _items(clinic, rx_id)
    assert (picked["form"], picked["strength"], picked["route"]) == ("syrup", "100mg/5ml", "oral")
    assert (typed["form"], typed["strength"], typed["route"]) == (None, None, None)
    page = _page(clinic, rx_id)
    assert "data-rx-facts" in page and "شراب" in page and "بالفم" in page
    assert "100mg/5ml" in page
    assert "data-rx-incomplete" not in page


def test_a_strength_the_name_already_says_is_not_printed_twice(clinic):
    did = _drug(clinic, trade_name="Brufen 100mg/5ml")
    rx_id = _write(clinic, [{"drug_id": did, "name": "Brufen 100 mg/5 ml", "dose": "5ml",
                             "frequency": "1x3", "duration": "5d"}])
    page = _page(clinic, rx_id)
    facts = page.split("data-rx-facts>")[1].split("</div>")[0]
    assert "100mg" not in facts and "شراب" in facts


def test_when_needed_asks_what_for_and_how_often_and_nothing_else_does(clinic):
    rx_id = _write(clinic, [
        {"name": "Paracetamol", "dose": "5ml", "frequency": "prn",
         "prn_reason": "حرارة فوق ٣٨٫٥", "prn_hours": "6", "prn_max": "4"},
        # Boxes filled, then the frequency changed: they are not kept.
        {"name": "Amoxicillin", "dose": "5ml", "frequency": "1x3", "duration": "7d",
         "prn_reason": "بقايا", "prn_hours": "6", "prn_max": "4"}])
    prn, regular = _items(clinic, rx_id)
    assert (prn["frequency"], prn["prn_reason"], prn["prn_min_hours"],
            prn["prn_max_per_day"]) == ("عند اللزوم", "حرارة فوق ٣٨٫٥", 6, 4)
    assert (regular["prn_reason"], regular["prn_min_hours"], regular["prn_max_per_day"]) == (
        None, None, None)
    page = _page(clinic, rx_id)
    assert "data-rx-prn" in page and "حرارة فوق ٣٨٫٥" in page
    assert "كل ٦ ساعات" in page and "٤ مرات في اليوم" in page
    assert "بقايا" not in page


def test_nonsense_limits_are_not_kept(clinic):
    rx_id = _write(clinic, [{"name": "Paracetamol", "dose": "5ml", "frequency": "prn",
                             "prn_reason": "ألم", "prn_hours": "0", "prn_max": "99"}])
    (line,) = _items(clinic, rx_id)
    assert (line["prn_min_hours"], line["prn_max_per_day"]) == (None, None)


def test_a_line_missing_something_is_said_on_screen_not_refused(clinic):
    rx_id = _write(clinic, [
        {"name": "Paracetamol", "dose": "5ml", "frequency": "prn"},
        {"name": "Amoxicillin", "dose": "5ml", "frequency": "1x3"}])
    page = _page(clinic, rx_id)
    notice = page.split("data-rx-incomplete")[1].split("</p>")[0]
    assert "لإيه" in notice and "أقصى عدد مرات" in notice and "المدة" in notice
    # The notice is on the screen only.
    assert 'class="card gc-scale-in no-print" data-rx-incomplete' in page


def test_the_height_sits_beside_the_weight_taken_with_it(clinic):
    from app.models import GrowthRecord

    rx_id = _write(clinic, [{"name": "Zinc", "dose": "5ml", "frequency": "1x1",
                             "duration": "10d"}])
    # A height from another day is not printed beside today's weight.
    with clinic["app"].app_context():
        clinic["db"].session.add_all([
            GrowthRecord(patient_id=clinic["ids"]["child"], height_cm=70.0,
                         record_date=local_today() - timedelta(days=90)),
            GrowthRecord(patient_id=clinic["ids"]["child"], weight_kg=12.5,
                         record_date=local_today())])
        clinic["db"].session.commit()
    page = _page(clinic, rx_id)
    assert "12.5" in page and "data-rx-height" not in page and "70.0" not in page


def test_measured_together_they_print_together(clinic):
    from app.models import GrowthRecord

    with clinic["app"].app_context():
        clinic["db"].session.add(GrowthRecord(
            patient_id=clinic["ids"]["child"], weight_kg=12.6, height_cm=88.5,
            record_date=local_today()))
        clinic["db"].session.commit()
    rx_id = _write(clinic, [{"name": "Zinc", "dose": "5ml", "frequency": "1x1",
                             "duration": "10d"}])
    band = _page(clinic, rx_id).split("data-rx-height>")[1].split("</span></span>")[0]
    assert "88.5" in band


def test_the_time_sits_beside_the_date(clinic):
    from app.models import Prescription
    from app.utils.clock import hhmm

    rx_id = _write(clinic, [{"name": "Zinc", "dose": "5ml", "frequency": "1x1",
                             "duration": "10d"}])
    with clinic["app"].app_context():
        written = hhmm(clinic["db"].session.get(Prescription, rx_id).created_at)
    assert f"{local_today()} · {written}" in _page(clinic, rx_id)


def test_a_prescription_dated_back_prints_no_hour(clinic):
    from app.models import Prescription

    rx_id = _write(clinic, [{"name": "Zinc", "dose": "5ml", "frequency": "1x1",
                             "duration": "10d"}])
    with clinic["app"].app_context():
        rx = clinic["db"].session.get(Prescription, rx_id)
        rx.rx_date = local_today() - timedelta(days=1)
        clinic["db"].session.commit()
    page = _page(clinic, rx_id)
    assert f"{local_today() - timedelta(days=1)}</strong>" in page


def test_either_limit_makes_a_when_needed_line_complete(clinic):
    rx_id = _write(clinic, [{"name": "Paracetamol", "dose": "5ml", "frequency": "prn",
                             "prn_reason": "ألم", "prn_max": "4"}])
    assert "data-rx-incomplete" not in _page(clinic, rx_id)


def test_a_prescription_from_another_day_carries_no_notice(clinic):
    """Nobody can go back and complete last year's line; saying so helps no one."""
    from datetime import datetime

    from app.models import Prescription

    rx_id = _write(clinic, [{"name": "Amoxicillin", "dose": "5ml", "frequency": "1x3"}])
    assert "data-rx-incomplete" in _page(clinic, rx_id)
    with clinic["app"].app_context():
        rx = clinic["db"].session.get(Prescription, rx_id)
        rx.created_at = datetime.utcnow() - timedelta(days=2)
        clinic["db"].session.commit()
    assert "data-rx-incomplete" not in _page(clinic, rx_id)


def test_a_template_without_the_measurements_prints_no_height(clinic):
    from app.models import GrowthRecord, RxPrintTemplate

    with clinic["app"].app_context():
        clinic["db"].session.add_all([
            GrowthRecord(patient_id=clinic["ids"]["child"], weight_kg=12.6, height_cm=88.5,
                         record_date=local_today()),
            RxPrintTemplate(name="t", mode="white", is_default=True, page_size="A4",
                            font_size=14, margin_mm=12, show_weight=False)])
        clinic["db"].session.commit()
    rx_id = _write(clinic, [{"name": "Zinc", "dose": "5ml", "frequency": "1x1",
                             "duration": "10d"}])
    page = _page(clinic, rx_id)
    assert "data-rx-height" not in page and "88.5" not in page
