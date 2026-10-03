"""The tube has its number before the needle, on a label a reader can scan.

Asked as *«ليه مش بيولد رقم العينة؟ ويقدر يطبعها وتتقرا بالباركود؟»*.

The number was written only when «the sample was taken» was pressed, so
there was nothing to stick on the tube while it was being drawn, and no
barcode anywhere. What is held here:

* printing a label writes the number, and drawing keeps it — the tube and
  the record carry the same one;
* a label printed twice is the same tube, not a new number;
* a film or a study has no tube, and no label;
* one sheet for every tube a child is waiting for;
* the label page only reads — an order with no number is left off it;
* a scanned code (any case, stray spaces) opens its order; an unknown one
  says so.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def bench_(clinic):
    from app.models import Investigation, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        cbc = Investigation(name_ar="صورة دم كاملة", kind="lab", tube="EDTA بنفسجي",
                            sample_type="دم", is_active=True)
        db.session.add(cbc)
        db.session.commit()
        clinic["ids"]["cbc"] = cbc.id
    return clinic


def _order(c, name="صورة دم كاملة", kind="lab", patient=None):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"],
                                 patient_id=patient or c["ids"]["child"],
                                 investigation_id=c["ids"]["cbc"] if kind == "lab" else None,
                                 kind=kind, name=name, status="requested",
                                 created_at=datetime.utcnow() - timedelta(minutes=5))
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _row(c, order_id):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = c["db"].session.get(VisitInvestigation, order_id)
        return {"code": row.sample_code, "status": row.status}


def test_printing_the_label_writes_the_number_and_drawing_keeps_it(bench_):
    order = _order(bench_)
    client = bench_["sign_in"]("boss")
    answer = client.post(f"/labs/order/{order}/label")
    assert f"/labs/labels?ids={order}" in answer.headers["Location"]
    code = _row(bench_, order)["code"]
    assert code and _row(bench_, order)["status"] == "requested"

    sheet = client.get(f"/labs/labels?ids={order}").get_data(as_text=True)
    assert f'data-label="{order}"' in sheet and code in sheet
    assert "<svg" in sheet and "EDTA" in sheet and "P1" in sheet

    client.post(f"/labs/order/{order}/label")
    assert _row(bench_, order)["code"] == code, "a second print made a new tube"

    client.post(f"/labs/order/{order}/collect", data={"code": ""})
    after = _row(bench_, order)
    assert after == {"code": code, "status": "collected"}


def test_a_code_typed_at_the_bench_still_wins(bench_):
    order = _order(bench_)
    client = bench_["sign_in"]("boss")
    client.post(f"/labs/order/{order}/label")
    client.post(f"/labs/order/{order}/collect", data={"code": "EXT-77"})
    assert _row(bench_, order)["code"] == "EXT-77"


def test_a_study_has_no_tube_and_no_label(bench_):
    order = _order(bench_, name="إيكو", kind="diagnostic")
    client = bench_["sign_in"]("boss")
    client.post(f"/labs/order/{order}/label")
    assert _row(bench_, order)["code"] is None
    assert client.get(f"/labs/labels?ids={order}").status_code == 404


def test_one_sheet_for_every_tube_the_child_is_waiting_for(bench_):
    first = _order(bench_)
    second = _order(bench_, name="سكر")
    answer = bench_["sign_in"]("boss").post(
        f"/labs/patient/{bench_['ids']['child']}/labels")
    location = answer.headers["Location"]
    assert str(first) in location and str(second) in location
    assert _row(bench_, first)["code"] and _row(bench_, second)["code"]
    assert _row(bench_, first)["code"] != _row(bench_, second)["code"]


def test_the_label_page_only_reads(bench_):
    order = _order(bench_)
    assert bench_["sign_in"]("boss").get(f"/labs/labels?ids={order}").status_code == 404
    assert _row(bench_, order)["code"] is None


def test_a_scanned_tube_opens_its_order(bench_):
    order = _order(bench_)
    client = bench_["sign_in"]("boss")
    client.post(f"/labs/order/{order}/label")
    code = _row(bench_, order)["code"]
    answer = client.get(f"/labs/scan?code=  {code.lower()} ")
    assert answer.headers["Location"].endswith(f"/labs/order/{order}")
    unknown = client.get("/labs/scan?code=999999-99999", follow_redirects=True)
    assert "999999-99999" in unknown.get_data(as_text=True)


def test_the_rack_has_the_scan_box_and_the_print_buttons(bench_):
    order = _order(bench_)
    page = bench_["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-scan" in page and 'name="code"' in page and "autofocus" in page
    assert f'/labs/order/{order}/label' in page and "data-print-child" in page


def test_a_numbered_tube_is_reprinted_not_renumbered(bench_):
    order = _order(bench_)
    client = bench_["sign_in"]("boss")
    client.post(f"/labs/order/{order}/label")
    code = _row(bench_, order)["code"]
    page = client.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-reprint" in page and f"/labs/labels?ids={order}" in page
    assert client.get(f"/labs/labels?ids={order}").status_code == 200
    assert _row(bench_, order)["code"] == code
