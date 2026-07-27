"""Where the money actually is.

Every collection used to post to one ledger account whatever the family paid
with, so InstaPay money sitting in a phone app appeared in the books as notes
in a drawer. That account was not a drawer — it was "everything in by any
means minus everything out", a number nobody can count and nothing can be
checked against, and a shortage in the cash was covered by the InstaPay money
next to it.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def tilled(clinic):
    """The clinic with its default tills seeded, and the cashier signed in."""
    from app.utils.accounting import ensure_seeded
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
    clinic["desk"] = clinic["sign_in"]("desk")
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _till(tilled, code):
    from app.models import CashAccount

    with tilled["app"].app_context():
        return CashAccount.query.filter_by(code=code).first()


def _invoice(tilled, total=200):
    """An issued invoice with an open balance."""
    from app.models import Invoice, InvoiceItem

    with tilled["app"].app_context():
        n = Invoice.query.count() + 1
        inv = Invoice(invoice_number=f"INV-T{n:04d}",
                      patient_id=tilled["ids"]["child"],
                      invoice_date=date.today(), status="issued")
        tilled["db"].session.add(inv)
        tilled["db"].session.flush()
        inv.items.append(InvoiceItem(description="كشف", quantity=1,
                                     unit_price=total))
        tilled["db"].session.commit()
        return inv.id


# ------------------------------------------------------------- the tills ---
def test_a_fresh_clinic_gets_a_till_per_way_of_paying(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        kinds = {a.code: a.kind for a in CashAccount.active()}
    assert kinds["1010"] == "cash"
    assert kinds["1011"] == "wallet"      # instapay
    assert kinds["1013"] == "clearing"    # card, under collection
    assert kinds["1020"] == "bank"


def test_seeding_twice_does_not_double_them(tilled):
    from app.models import CashAccount
    from app.utils.treasury import seed_accounts

    with tilled["app"].app_context():
        before = CashAccount.query.count()
        seed_accounts()
        assert CashAccount.query.count() == before


def test_a_clinic_that_renamed_a_till_keeps_its_name(tilled):
    """Seeding runs on every upgrade. It must never walk over the name a
    clinic put on the wall."""
    from app.models import CashAccount
    from app.utils.treasury import seed_accounts

    with tilled["app"].app_context():
        till = CashAccount.query.filter_by(code="1010").first()
        till.name = "خزنة استقبال الدور الأرضي"
        tilled["db"].session.commit()
        seed_accounts()
        assert (CashAccount.query.filter_by(code="1010").first().name
                == "خزنة استقبال الدور الأرضي")


def test_the_card_till_knows_where_it_settles(tilled):
    """Card money is not in the bank on the day it was taken. Without this the
    card account grows forever and nobody can clear it to zero."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert card.settles_into is not None
        assert card.settles_into.code == "1020"


def test_only_cash_tills_take_a_shift(tilled):
    """Nobody hands over an InstaPay balance at the end of the evening."""
    with tilled["app"].app_context():
        assert _till(tilled, "1010").counts_by_hand is True
        assert _till(tilled, "1011").counts_by_hand is False
        assert _till(tilled, "1013").counts_by_hand is False


# ------------------------------------------------- method is not the till --
def test_a_method_names_a_default_till(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        assert CashAccount.for_method("instapay").code == "1011"
        assert CashAccount.for_method("cash").code == "1010"
        assert CashAccount.for_method("card").code == "1013"


def test_two_cash_tills_can_both_take_cash(tilled):
    """The whole reason the mapping is a default and not a binding: a clinic
    with reception on two floors has both desks taking cash."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        tilled["db"].session.add(CashAccount(
            code="1014", name="خزنة استقبال الدور التاني", kind="cash",
            sort_order=9, is_active=True))
        tilled["db"].session.commit()
        # The default is unchanged — the second desk is chosen per payment.
        assert CashAccount.for_method("cash").code == "1010"
        assert len([a for a in CashAccount.active() if a.kind == "cash"]) == 2


# --------------------------------------------------- money lands somewhere --
def test_a_cash_payment_lands_in_the_drawer(tilled):
    from app.models import Payment

    inv = _invoice(tilled)
    tilled["desk"].post("/finance/shift/open", data={"opening_float": "0"})
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "cash"})

    with tilled["app"].app_context():
        pay = Payment.query.filter_by(invoice_id=inv).first()
        assert pay.account.code == "1010"


def test_an_instapay_payment_does_not(tilled):
    """The one this whole thing exists for."""
    from app.models import Payment

    inv = _invoice(tilled)
    tilled["desk"].post("/finance/shift/open", data={"opening_float": "0"})
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    with tilled["app"].app_context():
        assert Payment.query.filter_by(invoice_id=inv).first().account.code == "1011"


def test_the_cashier_can_send_one_payment_to_another_till(tilled):
    """Without inventing a payment method called "cash-emergency"."""
    from app.models import CashAccount, Payment

    with tilled["app"].app_context():
        other = CashAccount(code="1014", name="خزنة الطوارئ", kind="cash",
                            sort_order=9, is_active=True)
        tilled["db"].session.add(other)
        tilled["db"].session.commit()
        other_id = other.id

    inv = _invoice(tilled)
    tilled["desk"].post("/finance/shift/open", data={"opening_float": "0"})
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "cash",
                              "account_id": str(other_id)})

    with tilled["app"].app_context():
        assert Payment.query.filter_by(invoice_id=inv).first().account_id == other_id


# ------------------------------------------------------------ the ledger ---
def test_the_journal_follows_the_till_not_the_drawer(tilled):
    from app.models import JournalLine

    inv = _invoice(tilled)
    tilled["desk"].post("/finance/shift/open", data={"opening_float": "0"})
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    with tilled["app"].app_context():
        codes = {ln.account.code for ln in JournalLine.query.all()
                 if ln.debit}
        assert "1011" in codes, "InstaPay must not be booked to the drawer"


# -------------------------------------------------------------- the gate ---
def test_cash_without_a_shift_is_still_refused(tilled):
    from app.models import Payment

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "cash"})

    with tilled["app"].app_context():
        assert Payment.query.filter_by(invoice_id=inv).count() == 0


def test_instapay_without_a_shift_is_not(tilled):
    """Refusing money that never touches the drawer because the drawer is shut
    is refusing money for no reason — the shift's count is identical either
    way."""
    from app.models import Payment

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    with tilled["app"].app_context():
        assert Payment.query.filter_by(invoice_id=inv).count() == 1


def test_the_cashier_is_told_where_it_landed(tilled):
    """A notice, not a refusal. They need to know the 200 went to InstaPay and
    then get on with their day."""
    inv = _invoice(tilled)
    body = tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                               data={"amount": "200", "method": "instapay"},
                               follow_redirects=True).get_data(as_text=True)
    assert "إنستاباي" in body


# -------------------------------------------------------- money going out --
def test_an_expense_leaves_a_particular_till(tilled):
    from app.models import Expense

    tilled["boss"].post("/finance/expenses/new",
                        data={"category": "other", "description": "كهربا",
                              "amount": "300", "payment_method": "cash"})

    with tilled["app"].app_context():
        assert Expense.query.first().account.code == "1010"


def test_a_supplier_paid_by_transfer_comes_out_of_the_bank(tilled):
    from app.models import Supplier, SupplierPayment

    with tilled["app"].app_context():
        supplier = Supplier(name="مورد")
        tilled["db"].session.add(supplier)
        tilled["db"].session.commit()
        sid = supplier.id

    tilled["boss"].post(f"/finance/payables/{sid}/pay",
                        data={"amount": "500", "method": "transfer"})

    with tilled["app"].app_context():
        assert SupplierPayment.query.first().account.code == "1020"


# ------------------------------------------------------------- balances ----
def test_the_balance_is_opening_plus_movements(tilled):
    from app.utils.treasury import account_balance

    inv = _invoice(tilled, total=200)
    tilled["desk"].post("/finance/shift/open", data={"opening_float": "0"})
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "cash"})
    tilled["boss"].post("/finance/expenses/new",
                        data={"category": "other", "description": "كهربا",
                              "amount": "50", "payment_method": "cash"})

    with tilled["app"].app_context():
        drawer = _till(tilled, "1010")
        drawer.opening_balance = 100
        tilled["db"].session.commit()
        assert account_balance(drawer) == 250.0    # 100 + 200 − 50


def test_the_balance_is_not_a_stored_column(tilled):
    """A column updated on every movement is the easiest thing to write and
    the most dangerous to live with: one interrupted write and there are two
    answers with no way to tell which lies."""
    from app.models import CashAccount

    assert not hasattr(CashAccount, "current_balance")
    assert not hasattr(CashAccount, "balance_cached")


def test_money_in_one_till_does_not_show_up_in_another(tilled):
    from app.utils.treasury import account_balance

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    with tilled["app"].app_context():
        assert account_balance(_till(tilled, "1011")) == 200.0
        assert account_balance(_till(tilled, "1010")) == 0.0


def test_the_totals_are_grouped_by_how_they_are_checked(tilled):
    """"We hold 40,000" means something different when 30,000 of it is card
    takings that have not landed yet."""
    from app.utils.treasury import total_by_kind

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "card"})

    with tilled["app"].app_context():
        totals = total_by_kind()
        assert totals["clearing"] == 200.0
        assert totals["cash"] == 0.0


# ------------------------------------------------------------- migration ---
def test_history_is_tagged_from_the_method_it_was_taken_with(tilled):
    from app.models import Payment
    from app.utils.treasury_migrate import migrate_history

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})
    with tilled["app"].app_context():
        # …as though it had been taken before tills existed.
        Payment.query.filter_by(invoice_id=inv).first().account_id = None
        tilled["db"].session.commit()

        migrate_history()
        assert Payment.query.filter_by(invoice_id=inv).first().account.code == "1011"


def test_the_migration_does_not_rewrite_the_old_entries(tilled):
    """A ledger is not a document you edit. The January report a clinic
    printed has to still read the same in March — so the correction is one
    dated entry, not a rearranged past."""
    from app.models import JournalEntry, Payment
    from app.utils.treasury_migrate import migrate_history

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})
    with tilled["app"].app_context():
        pay = Payment.query.filter_by(invoice_id=inv).first()
        original = JournalEntry.query.filter_by(source_type="payment",
                                                source_id=pay.id).first()
        before = original.entry_number
        pay.account_id = None
        tilled["db"].session.commit()

        migrate_history()
        after = JournalEntry.query.filter_by(source_type="payment",
                                             source_id=pay.id).first()
        assert after.entry_number == before


def test_running_the_migration_twice_corrects_the_books_once(tilled):
    from app.models import JournalEntry
    from app.utils.treasury_migrate import migrate_history

    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    with tilled["app"].app_context():
        migrate_history()
        entries = JournalEntry.query.filter_by(source_type="till_migration").all()
        first = {(e.source_id, e.entry_number) for e in entries}
        migrate_history()
        again = JournalEntry.query.filter_by(source_type="till_migration").all()
        # Same entries, same numbers — corrected once, not stacked twice.
        assert {(e.source_id, e.entry_number) for e in again} == first


# --------------------------------------------------------------- screens ---
def test_the_screen_lists_the_tills_with_their_balances(tilled):
    body = tilled["boss"].get("/finance/tills").get_data(as_text=True)
    assert "إنستاباي" in body
    assert "1013" in body


def test_a_till_statement_shows_what_went_through_it(tilled):
    inv = _invoice(tilled)
    tilled["desk"].post(f"/finance/invoices/{inv}/payment",
                        data={"amount": "200", "method": "instapay"})

    till = None
    with tilled["app"].app_context():
        till = _till(tilled, "1011").id
    body = tilled["boss"].get(f"/finance/tills/{till}").get_data(as_text=True)
    assert "200" in body


def test_the_statement_opens_on_a_till_with_no_movements(tilled):
    with tilled["app"].app_context():
        till = _till(tilled, "1020").id
    assert tilled["boss"].get(f"/finance/tills/{till}").status_code == 200


def test_the_finance_hub_links_to_it(tilled):
    body = tilled["boss"].get("/finance/").get_data(as_text=True)
    assert "/finance/tills" in body
