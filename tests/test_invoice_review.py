"""Finding a bill, correcting it on the record, and handing the lot over.

Reported: *"the patient invoices screen needs to be searchable, with filters
and date ranges. And you should be able to open an invoice and add or delete
while the period is still open, like a review — but of course that has to be
recorded, who and when, so the accountant can check. And it should be
exportable for the tax-invoice queue."*

The screen had a status chip and a page number. Finding one bill meant knowing
roughly how long ago it was and paging back to it, which is not a review — it
is a search by memory.

Editing already worked and already refused a closed period. What was missing is
the half that makes it safe: **nothing was written down.** A line could be
added, repriced or deleted on an open month and the invoice would simply read
differently afterwards, with no way for anybody to see that it had changed. An
"editable while open" bill with no record is not a review process, it is an
unlogged way to change money after the fact — so every change now says what it
was, what it became, who did it and when.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def bills(clinic):
    """Three invoices, on three days, for two patients."""
    from app.models import Invoice, InvoiceItem, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        other = Patient(patient_number="P-OTHER", full_name="سلمى فاروق",
                        gender="female", date_of_birth=date(2023, 5, 1),
                        is_active=True)
        db.session.add(other)
        db.session.flush()

        made = {}
        rows = [("INV-A", clinic["ids"]["child"], date.today(), 200,
                 clinic["ids"]["doctor"]),
                ("INV-B", clinic["ids"]["child"], date.today() - timedelta(days=10),
                 300, None),
                ("INV-C", other.id, date.today() - timedelta(days=40), 400,
                 clinic["ids"]["doctor"])]
        for number, pid, when, price, doc in rows:
            inv = Invoice(invoice_number=number, patient_id=pid,
                          invoice_date=when, doctor_id=doc,
                          created_by=clinic["ids"]["admin"])
            db.session.add(inv)
            db.session.flush()
            db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                       unit_price=price, quantity=1))
            db.session.flush()
            inv.recalc_status()
            made[number] = inv.id
        db.session.commit()
        made["other_patient"] = other.id
        return made


def _numbers(body):
    return {n for n in ("INV-A", "INV-B", "INV-C") if n in body}


# ================================================================ finding it
def test_an_invoice_can_be_found_by_its_number(bills, boss):
    body = boss.get("/finance/invoices",
                    query_string={"q": "INV-B"}).get_data(as_text=True)
    assert _numbers(body) == {"INV-B"}


def test_an_invoice_can_be_found_by_the_patients_name(bills, boss):
    """What reception actually has: a family at the desk, not a number."""
    body = boss.get("/finance/invoices",
                    query_string={"q": "سلمى"}).get_data(as_text=True)
    assert _numbers(body) == {"INV-C"}


def test_an_invoice_can_be_found_by_file_number(bills, boss):
    body = boss.get("/finance/invoices",
                    query_string={"q": "P-OTHER"}).get_data(as_text=True)
    assert _numbers(body) == {"INV-C"}


def test_the_list_can_be_cut_to_a_date_range(bills, boss):
    """Reviewing a month is the whole reason this screen is opened."""
    since = (local_today() - timedelta(days=20)).isoformat()
    body = boss.get("/finance/invoices",
                    query_string={"from": since}).get_data(as_text=True)
    assert _numbers(body) == {"INV-A", "INV-B"}


def test_the_range_has_both_ends(bills, boss):
    body = boss.get("/finance/invoices", query_string={
        "from": (date.today() - timedelta(days=20)).isoformat(),
        "to": (date.today() - timedelta(days=5)).isoformat(),
    }).get_data(as_text=True)
    assert _numbers(body) == {"INV-B"}


def test_the_list_can_be_cut_to_one_doctor(bills, boss, clinic):
    body = boss.get("/finance/invoices", query_string={
        "doctor_id": clinic["ids"]["doctor"]}).get_data(as_text=True)
    assert _numbers(body) == {"INV-A", "INV-C"}


def test_the_filters_combine(bills, boss, clinic):
    """Each one alone is a demo; together is the review an accountant does."""
    body = boss.get("/finance/invoices", query_string={
        "doctor_id": clinic["ids"]["doctor"],
        "from": (date.today() - timedelta(days=20)).isoformat(),
    }).get_data(as_text=True)
    assert _numbers(body) == {"INV-A"}


def test_the_status_chips_keep_the_rest_of_the_filter(bills, boss):
    """Losing the date range on every chip click is how a filter bar becomes
    something people stop using."""
    since = (local_today() - timedelta(days=20)).isoformat()
    body = boss.get("/finance/invoices",
                    query_string={"from": since}).get_data(as_text=True)
    assert f"from={since}" in body or f"from={since.replace('-', '%2D')}" in body


def test_a_bad_date_does_not_empty_the_screen(bills, boss):
    """A typed-in query string must not be a way to lose the books."""
    body = boss.get("/finance/invoices",
                    query_string={"from": "not-a-date"}).get_data(as_text=True)
    assert _numbers(body) == {"INV-A", "INV-B", "INV-C"}


def test_the_filtered_set_is_added_up(bills, boss):
    """A list of money you have to total yourself is a list you cannot check a
    handover against."""
    body = boss.get("/finance/invoices", query_string={
        "from": (date.today() - timedelta(days=20)).isoformat()}).get_data(as_text=True)
    assert "500.00" in body          # 200 + 300, not 900


# ================================================== correcting it, on record
def _items(clinic, invoice_id):
    from app.models import Invoice

    with clinic["app"].app_context():
        inv = clinic["db"].session.get(Invoice, invoice_id)
        return [(i.id, i.description, i.unit_price) for i in inv.items]


def _history(clinic, invoice_id):
    from app.models import ActivityLog

    with clinic["app"].app_context():
        return [(r.action, r.detail, r.user_id) for r in
                ActivityLog.query.filter_by(entity="invoice",
                                            entity_id=invoice_id).all()]


def test_editing_a_line_is_written_down(bills, boss, clinic):
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    actions = [a for a, _d, _u in _history(clinic, bills["INV-A"])]
    assert "invoice.item_edit" in actions


def test_the_record_says_what_it_was_and_what_it_became(bills, boss, clinic):
    """"The price was edited" tells an accountant nothing. "200 → 150" is the
    thing they are checking."""
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    detail = [d for a, d, _u in _history(clinic, bills["INV-A"])
              if a == "invoice.item_edit"][0]
    assert "200" in detail and "150" in detail


def test_the_record_says_who(bills, boss, clinic):
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    users = [u for a, _d, u in _history(clinic, bills["INV-A"])
             if a == "invoice.item_edit"]
    assert users == [clinic["ids"]["admin"]]


def test_deleting_a_line_is_written_down_before_it_is_gone(bills, boss, clinic):
    """Afterwards there is nothing left to describe, and "a line was removed"
    is not a reviewable statement."""
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/delete",
              follow_redirects=True)

    detail = [d for a, d, _u in _history(clinic, bills["INV-A"])
              if a == "invoice.item_delete"]
    assert detail and "كشف" in detail[0]


def test_adding_a_line_is_written_down(bills, boss, clinic):
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/add", data={
        "description": "جلسة تنفس", "unit_price": "150", "quantity": "1",
    }, follow_redirects=True)

    detail = [d for a, d, _u in _history(clinic, bills["INV-A"])
              if a == "invoice.item_add"]
    assert detail and "جلسة تنفس" in detail[0]


def test_an_edit_that_changes_nothing_writes_nothing(bills, boss, clinic):
    """A log full of "no change" entries is a log nobody reads to the end."""
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"description": "كشف", "unit_price": "200", "quantity": "1"},
              follow_redirects=True)

    assert not [a for a, _d, _u in _history(clinic, bills["INV-A"])
                if a == "invoice.item_edit"]


def test_the_invoice_number_is_in_the_record(bills, boss, clinic):
    """An id means nothing on a printed audit list."""
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    detail = [d for a, d, _u in _history(clinic, bills["INV-A"])
              if a == "invoice.item_edit"][0]
    assert "INV-A" in detail


def test_the_history_is_on_the_invoice_screen(bills, boss, clinic):
    item_id = _items(clinic, bills["INV-A"])[0][0]
    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    body = boss.get(f"/finance/invoices/{bills['INV-A']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.history") in body
    assert "invoice.item_edit" in body


def test_the_screen_says_whether_the_bill_can_still_be_corrected(bills, boss,
                                                                 clinic):
    """Somebody about to correct a bill should know before they try whether
    the month is still open."""
    body = boss.get(f"/finance/invoices/{bills['INV-A']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.history_hint") in body


def test_a_closed_period_says_so_instead(bills, boss, clinic):
    from app.utils.periods import close_period, ensure_month

    with clinic["app"].app_context():
        today = local_today()
        close_period(ensure_month(today.year, today.month))
        clinic["db"].session.commit()

    body = boss.get(f"/finance/invoices/{bills['INV-A']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.history_locked") in body


def test_a_closed_period_still_refuses_the_edit_itself(bills, boss, clinic):
    """The message is a courtesy. The refusal is the rule."""
    from app.utils.periods import close_period, ensure_month

    item_id = _items(clinic, bills["INV-A"])[0][0]
    with clinic["app"].app_context():
        today = local_today()
        close_period(ensure_month(today.year, today.month))
        clinic["db"].session.commit()

    boss.post(f"/finance/invoices/{bills['INV-A']}/item/{item_id}/edit",
              data={"unit_price": "150", "quantity": "1"}, follow_redirects=True)

    assert _items(clinic, bills["INV-A"])[0][2] == 200


# ==================================================== handing it over =======
def test_the_export_carries_the_filtered_set(bills, boss):
    """An export with its own idea of the range is one nobody can reconcile
    against the screen they were looking at when they pressed the button."""
    reply = boss.get("/finance/invoices/export", query_string={
        "from": (date.today() - timedelta(days=20)).isoformat()})
    body = reply.get_data(as_text=True)
    assert "INV-A" in body and "INV-B" in body
    assert "INV-C" not in body


def test_the_export_is_a_spreadsheet_file(bills, boss):
    reply = boss.get("/finance/invoices/export")
    assert "attachment" in reply.headers["Content-Disposition"]
    assert "csv" in reply.headers["Content-Type"]


def test_the_export_states_the_discount_separately(bills, boss, clinic):
    """A filing wants the discount stated. An export that has already
    subtracted it cannot be checked against the paper the family was given."""
    from app.models import Invoice

    with clinic["app"].app_context():
        inv = clinic["db"].session.get(Invoice, bills["INV-A"])
        inv.items[0].discount_value = 50
        clinic["db"].session.commit()

    body = boss.get("/finance/invoices/export").get_data(as_text=True)
    header, *lines = [ln for ln in body.splitlines() if ln.strip()]
    assert "discount" in header and "gross" in header and "net" in header
    row = dict(zip(header.split(","),
                   [ln for ln in lines if ln.startswith("INV-A")][0].split(",")))
    assert float(row["gross"]) == 200
    assert float(row["discount"]) == 50
    assert float(row["net"]) == 150


def test_the_export_names_who_issued_each_bill(bills, boss):
    body = boss.get("/finance/invoices/export").get_data(as_text=True)
    assert "issued_by" in body.splitlines()[0]


def test_taking_the_register_out_of_the_building_is_recorded(bills, boss, clinic):
    """It is every patient the clinic has billed. Who exported it, and when,
    is the least that should be known."""
    from app.models import ActivityLog

    boss.get("/finance/invoices/export")

    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="invoice.export").count() == 1


def test_the_export_opens_as_arabic_in_excel(bills, boss):
    """Without the byte-order mark Excel reads the names as mojibake, and the
    accountant's first act is to retype them."""
    body = boss.get("/finance/invoices/export").get_data(as_text=True)
    assert body.startswith("﻿")


def test_reception_cannot_export_the_whole_register(bills, clinic):
    """Collecting money is not the same permission as taking the clinic's
    billing history home."""
    desk = clinic["sign_in"]("desk")
    assert desk.get("/finance/invoices/export").status_code == 403


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("search_ph", "export_tax", "history", "history_hint",
                    "history_locked", "history_none"):
            assert data["invoices"].get(key), f"{lang}.invoices.{key}"
        for key in ("when", "who"):
            assert data["common"].get(key), f"{lang}.common.{key}"
