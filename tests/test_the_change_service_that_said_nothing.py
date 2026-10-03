"""The change-service box that said nothing, and the board with no doctor on it.

Reported with a screenshot: *«ليه الجزء ده مش شغال؟»*. Reception picked the
service the visit actually was, and nothing came back — no figure, no
sentence, a confirm button that never woke up. The address of the question
is built with a placeholder id and swapped per row; the swap looked for
``/0`` at the very **end** of the path, and both addresses carry the id in
the middle (``/appointments/0/service-proposal``). Every ask went to
appointment 0, the 404 page did not read as an answer, and the failure was
swallowed.

Asked for in the same breath:

* the pick is a **search**, not a list — a hospital has thousands of
  services — with the appointment's own doctor's services first, under
  «بيقدمها», as on the checkout screen;
* when the board shows **everyone's** day, each row says whose patient it
  is, and the doctor filter stays where it was.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _node():
    node = shutil.which("node")
    if node is None:                       # pragma: no cover - CI has node
        pytest.skip("node is not installed")
    return node


def _book(clinic, doctor_key="doctor"):
    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"][doctor_key],
                           appt_date=local_today(), appt_time=time(10, 0),
                           appt_type="new", status="scheduled")
        clinic["db"].session.add(appt)
        clinic["db"].session.commit()
        return appt.id


def _second_doctor(clinic):
    from app.models import User

    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. منى", role="doctor",
                     is_active=True)
        other.set_password("secret")
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["doctor2"] = other.id


def _between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i) + len(end)]


# ------------------------------------------------------ the address itself --
def test_the_question_goes_to_the_appointment_on_the_row(clinic, tmp_path):
    """**Run, not read**: the swap is lifted out of the rendered board and
    executed against the very addresses the board was handed."""
    _book(clinic)
    page = clinic["sign_in"]("boss").get("/appointments/").get_data(as_text=True)
    ask, do = re.search(r"'(/appointments/0/service-proposal)', '(/appointments/0/change-service)'",
                        page).groups()
    swap = _between(page, "fixUrl(template, id)", "},")
    script = tmp_path / "swap.js"
    script.write_text("var o = {" + swap + "};\n"
                      f"console.log(JSON.stringify([o.fixUrl({json.dumps(ask)}, 42),"
                      f" o.fixUrl({json.dumps(do)}, 42),"
                      f" o.fixUrl('/x/0', 7), o.fixUrl('/x/0?a=1', 7),"
                      f" o.fixUrl('/x/10/y', 7)]));\n", encoding="utf-8")
    out = subprocess.run([_node(), str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [
        "/appointments/42/service-proposal", "/appointments/42/change-service",
        "/x/7", "/x/7?a=1", "/x/10/y"]


def test_a_failed_answer_is_said_not_swallowed(clinic):
    page = clinic["sign_in"]("boss").get("/appointments/").get_data(as_text=True)
    catch = _between(page, "// Said, not swallowed", "this.fix.ok = false;")
    said = json.loads(re.search(r'this\.fix\.says = ("[^"]*");', catch).group(1))
    assert said.startswith("مقدرتش أحسب") and "verdict = 'failed'" in catch


# ----------------------------------------------------------- the search --
def _groups(page, tmp_path, services, marked, q, cap=40):
    fn = _between(page, "function fixGroups(", "\n}")
    script = tmp_path / "groups.js"
    script.write_text(fn + "\nconsole.log(JSON.stringify(fixGroups("
                      f"{json.dumps(services)}, {json.dumps(marked)}, "
                      f"{json.dumps(q)}, {cap})));\n", encoding="utf-8")
    out = subprocess.run([_node(), str(script)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_doctors_own_services_come_first_and_the_search_narrows(clinic, tmp_path):
    page = clinic["sign_in"]("boss").get("/appointments/").get_data(as_text=True)
    services = [{"id": 1, "name": "كشف", "price": 200},
                {"id": 2, "name": "جلسة تنفس", "price": 150},
                {"id": 3, "name": "كشف منزلي", "price": 500}]
    g = _groups(page, tmp_path, services, [2], "")
    assert [s["id"] for s in g["mine"]] == [2]
    assert [s["id"] for s in g["other"]] == [1, 3]

    g = _groups(page, tmp_path, services, [2], "كشف")
    assert g["mine"] == [] and [s["id"] for s in g["other"]] == [1, 3]

    # Nobody has marked this doctor: one plain list, nothing hidden.
    g = _groups(page, tmp_path, services, None, "")
    assert g["mine"] == [] and len(g["other"]) == 3


def test_thousands_of_services_are_capped_and_say_there_are_more(clinic, tmp_path):
    page = clinic["sign_in"]("boss").get("/appointments/").get_data(as_text=True)
    services = [{"id": i, "name": f"خدمة {i}", "price": i} for i in range(1, 3001)]
    g = _groups(page, tmp_path, services, None, "")
    assert len(g["other"]) == 40 and g["more"] is True
    g = _groups(page, tmp_path, services, None, "خدمة 2999")
    assert [s["id"] for s in g["other"]] == [2999] and g["more"] is False


def test_the_modal_knows_the_rows_doctor_and_has_a_search_box(clinic):
    from app.models import Invoice, InvoiceItem
    from app.utils.finance import generate_invoice_number

    appt = _book(clinic)
    with clinic["app"].app_context():
        db = clinic["db"]
        inv = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"], appointment_id=appt)
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, service_id=clinic["ids"]["exam"],
                                   description="كشف", quantity=1, unit_price=200))
        db.session.commit()
    page = clinic["sign_in"]("boss").get("/appointments/").get_data(as_text=True)
    assert f"openFix({appt}, {clinic['ids']['doctor']})" in page
    assert "data-svcfix-search" in page and "data-svcfix-list" in page
    assert "<select class=\"input\" x-model=\"fix.serviceId\"" not in page
    rows = json.loads(re.search(r"fixServices: (\[.*?\]),\n", page).group(1))
    assert {"id": clinic["ids"]["exam"], "name": "كشف", "price": 200.0} in rows


# ------------------------------------------------------- whose patient --
def test_everyones_day_names_the_doctor_on_each_row(clinic):
    _second_doctor(clinic)
    _book(clinic, "doctor")
    _book(clinic, "doctor2")
    page = clinic["sign_in"]("boss").get("/appointments/?doctor_id=0").get_data(as_text=True)
    assert f'data-doctor-tag="{clinic["ids"]["doctor"]}"' in page
    assert f'data-doctor-tag="{clinic["ids"]["doctor2"]}"' in page
    assert "د. منى" in page
    assert 'id="docFilter"' in page, "the filter at the top went away"


def test_one_doctors_board_does_not_repeat_the_name_on_every_row(clinic):
    _second_doctor(clinic)
    _book(clinic, "doctor")
    page = clinic["sign_in"]("boss").get(
        f"/appointments/?doctor_id={clinic['ids']['doctor']}").get_data(as_text=True)
    assert "data-doctor-tag" not in page
