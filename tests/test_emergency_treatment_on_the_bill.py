"""What was given in emergency, on the bill — as each hospital charges it.

Asked as *«وطريقة الحساب ... وهل يقدر يعمل مراجعة قبل الحساب حاجه اتصرفت
عليه بالغلط»* and answered *«فى حجات بتتحسب كده وحجات بتتحسب كده على حسب كل
مستشفى»*. What is held here:

* only what was **given** is owed — not what was written, not what was
  cancelled;
* a service «inclusive» of its drug is one line, and the vial still leaves
  the shelf; «separate» is the service and the vial on their own lines; a
  service nobody has set is charged separately;
* a drug with no service is its own line, priced from the shelf, with no
  commission;
* the desk sees the lines and a line it takes off is not charged — and is
  offered again, never lost;
* each thing is charged once and leaves the shelf once, whatever is posted.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

BLANKS = ("line_brand_id", "line_dose_id", "line_dose_number", "line_vs_id",
          "line_op_id", "line_anaes_op_id", "line_test_id", "line_rx_line_id",
          "line_pkg_id", "line_pkg_sale_id")


@pytest.fixture()
def er(clinic):
    from app.models import Service, Setting, StoreItem, User

    with clinic["app"].app_context():
        db = clinic["db"]
        for module in ("emergency", "finance"):
            Setting.set(f"mod_enabled:{module}", "1")
        nurse = User(username="nurse", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        im = Service(name="حقنة عضل", category="procedure",
                     service_type="procedure", price=50, is_active=True,
                     supplies_mode="inclusive")
        neb = Service(name="جلسة تنفس", category="procedure",
                      service_type="session", price=80, is_active=True,
                      supplies_mode="separate")
        dress = Service(name="غيار", category="procedure",
                        service_type="procedure", price=60, is_active=True)
        vial = StoreItem(name="Ceftriaxone 500mg", item_type="drug", unit="vial",
                         sell_price=45, opening_stock=20, is_active=True)
        amp = StoreItem(name="Salbutamol neb", item_type="drug", unit="amp",
                        sell_price=12, opening_stock=20, is_active=True)
        db.session.add_all([nurse, im, neb, dress, vial, amp])
        db.session.commit()
        clinic["ids"].update(nurse=nurse.id, im=im.id, neb=neb.id,
                             dress=dress.id, vial=vial.id, amp=amp.id)
    return clinic


def _given(er, service=None, item=None, units=1, give=True, cancel=False):
    """An attendance with one thing on it, as the ward screen would leave it."""
    from app.models import EmergencyVisit, Patient, Service, StoreItem, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with er["app"].app_context():
        db = er["db"]
        child = db.session.get(Patient, er["ids"]["child"])
        visit = (EmergencyVisit.query.filter_by(patient_id=child.id,
                                                departed_at=None).first()
                 or util.arrive(child))
        db.session.flush()
        doc = db.session.get(User, er["ids"]["doctor"])
        nurse = db.session.get(User, er["ids"]["nurse"])
        order = eo.write(
            visit, doc, name="Ceftriaxone", dose="500 mg",
            service=db.session.get(Service, er["ids"][service]) if service else None,
            store_item=db.session.get(StoreItem, er["ids"][item]) if item else None,
            units=units)
        if cancel:
            eo.cancel(order, nurse)
        elif give:
            eo.give(order, nurse)
        db.session.commit()
        return order.id


def _lines(er):
    from app.utils import emergency_orders as eo

    with er["app"].test_request_context():
        return eo.checkout_lines(eo.unbilled(er["ids"]["child"]), "ar")


def _pay(er, lines):
    data = {"doctor_id": er["ids"]["doctor"], "discount_id": "none",
            "line_desc": [], "line_service_id": [], "line_price": [],
            "line_qty": [], "line_no_commission": [], "line_er_order_id": [],
            "line_er_item_id": [], **{k: [] for k in BLANKS}}
    for line in lines:
        data["line_desc"].append(line["description"])
        data["line_service_id"].append(str(line.get("service_id") or ""))
        data["line_price"].append(str(line["unit_price"]))
        data["line_qty"].append(str(line["quantity"]))
        data["line_no_commission"].append(line.get("no_commission", "0"))
        data["line_er_order_id"].append(str(line.get("er_order_id") or ""))
        data["line_er_item_id"].append(str(line.get("er_item_id") or ""))
        for key in BLANKS:
            data[key].append("")
    return er["sign_in"]("boss").post(f"/finance/collect/{er['ids']['child']}",
                                      data=data)


def _bill(er):
    from app.models import Invoice

    with er["app"].app_context():
        invoice = Invoice.query.filter_by(patient_id=er["ids"]["child"]).order_by(
            Invoice.id.desc()).first()
        return [(i.description.split(" — ")[0], i.unit_price, i.quantity,
                 i.service_id, i.commission_amount or 0) for i in invoice.items]


def _stock_out(er, item):
    from app.models import StockMovement

    with er["app"].app_context():
        return sum(-m.qty for m in StockMovement.query.filter_by(
            item_id=er["ids"][item], kind="out").all())


def _order(er, oid):
    from app.models import EmergencyOrder

    with er["app"].app_context():
        o = er["db"].session.get(EmergencyOrder, oid)
        return o.invoice_item_id, o.item_invoice_item_id, o.stock_movement_id


# =========================================================== what is owed ==
def test_only_what_was_given_is_owed(er):
    _given(er, service="im", item="vial", give=False)
    _given(er, service="im", item="vial", cancel=True)
    assert _lines(er) == []


# ====================================================== the three shapes ==
def test_an_inclusive_service_is_one_line_and_the_vial_still_leaves(er):
    oid = _given(er, service="im", item="vial")
    lines = _lines(er)
    assert [(line["unit_price"], line.get("er_order_id")) for line in lines] == [(50, oid)]
    assert _pay(er, lines).status_code == 302
    assert _bill(er)[0][:3] == ("حقنة عضل", 50, 1)
    assert _stock_out(er, "vial") == 1
    assert _order(er, oid)[0] is not None
    assert _lines(er) == [], "offered again after it was paid"


def test_a_separate_service_puts_the_drug_on_its_own_line(er):
    oid = _given(er, service="neb", item="amp", units=2)
    lines = _lines(er)
    assert [(line["unit_price"], line["quantity"]) for line in lines] == [(80, 1), (12, 2)]
    _pay(er, lines)
    bill = _bill(er)
    assert [b[:3] for b in bill] == [("جلسة تنفس", 80, 1), ("Salbutamol neb", 12, 2)]
    # Nobody's percentage rides on the ampoule.
    assert bill[1][3] is None and bill[1][4] == 0
    assert _stock_out(er, "amp") == 2
    service_line, item_line, moved = _order(er, oid)
    assert service_line and item_line and moved
    assert _lines(er) == []


def test_a_service_nobody_set_is_charged_separately(er):
    _given(er, service="dress", item="vial")
    assert [line["unit_price"] for line in _lines(er)] == [60, 45]


def test_a_drug_with_no_service_is_its_own_charge(er):
    oid = _given(er, item="vial")
    lines = _lines(er)
    assert [(line["unit_price"], line.get("er_item_id"), line.get("no_commission"))
            for line in lines] == [(45, oid, "1")]
    _pay(er, lines)
    assert _order(er, oid)[0] is not None and _stock_out(er, "vial") == 1
    assert _lines(er) == []


def test_a_line_with_nothing_to_charge_is_not_offered(er):
    _given(er)
    assert _lines(er) == []


# ============================================================== the desk ==
def test_a_line_the_desk_takes_off_is_not_charged_and_comes_back(er):
    oid = _given(er, service="neb", item="amp")
    service_line, drug_line = _lines(er)
    _pay(er, [service_line])
    assert [b[0] for b in _bill(er)] == ["جلسة تنفس"]
    # The ampoule was used: it left the shelf with the service.
    assert _stock_out(er, "amp") == 1
    # And it is offered again rather than lost — the desk decides.
    again = _lines(er)
    assert [(line["unit_price"], line.get("er_item_id")) for line in again] == [(12, oid)]
    _pay(er, again)
    assert _stock_out(er, "amp") == 1, "the ampoule left the shelf twice"
    assert _lines(er) == []


def test_a_posted_id_that_is_not_owed_charges_nothing_twice(er):
    oid = _given(er, service="im", item="vial")
    lines = _lines(er)
    _pay(er, lines)
    first = _order(er, oid)
    _pay(er, lines)  # the same form, posted again
    assert _order(er, oid) == first
    assert _stock_out(er, "vial") == 1


def test_the_attendance_page_points_to_the_desk(er):
    from app.models import EmergencyVisit

    _given(er, service="im", item="vial")
    with er["app"].app_context():
        attendance = EmergencyVisit.query.one().id
    page = er["sign_in"]("boss").get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert "data-to-collect" in page
    nurse = er["sign_in"]("nurse").get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert "data-to-collect" not in nurse


# ========================================================= the services ==
def test_the_hospital_says_per_service_and_the_list_says_what_is_unset(er):
    from app.models import Service

    page = er["sign_in"]("boss").get("/finance/services").get_data(as_text=True)
    assert 'data-supplies="unset"' in page and 'data-supplies="inclusive"' in page
    er["sign_in"]("boss").post(f"/finance/services/{er['ids']['dress']}/edit", data={
        "name": "غيار", "category": "procedure", "price": "60", "is_active": "1",
        "se": "1", "service_type": "procedure", "supplies_mode": "inclusive"})
    with er["app"].app_context():
        assert er["db"].session.get(Service, er["ids"]["dress"]).supplies_mode == "inclusive"
    er["sign_in"]("boss").post(f"/finance/services/{er['ids']['dress']}/edit", data={
        "name": "غيار", "category": "procedure", "price": "60", "is_active": "1",
        "se": "1", "service_type": "procedure", "supplies_mode": "whatever"})
    with er["app"].app_context():
        assert er["db"].session.get(Service, er["ids"]["dress"]).supplies_mode is None
