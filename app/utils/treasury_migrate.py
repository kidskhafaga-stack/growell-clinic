"""Moving the clinic's history into its tills, without rewriting it.

Every collection ever taken posted to account 1010 whatever the family paid
with. Now that InstaPay has a till of its own, 1010 holds money that was never
in the drawer — and the obvious fix, going back and re-posting each old journal
entry to the right account, is the one thing that must not be done.

**A ledger is not a document you edit.** The January report a clinic printed
has to still read the same in March; a set of books that quietly rearranges
itself overnight is worth nothing to the person who signed off on it. So the
old entries stay exactly where they are.

What happens instead is what an accountant would do: **one dated correction
entry per till**, moving the historical total out of the main drawer and into
the account it belongs in. It is visible, it is dated, it can be questioned,
and anyone reading the ledger can see the move was made rather than discover
that the past changed.

The ``account_id`` on the movement rows themselves is a different matter —
that is a label, not a posting, so it is filled in directly.
"""
MEMO = "ترحيل أرصدة الخزن — تسوية افتتاحية"


def migrate_history():
    """Tag old movements with a till and correct the ledger once.

    Returns ``{"tagged": n, "entries": n}``. Idempotent: rows already carrying
    a till are left alone, and the correction entry is posted under a fixed
    reference so a second run replaces it rather than doubling it.
    """
    from app.extensions import db
    from app.models import CashAccount, Expense, Payment, SupplierPayment

    accounts = CashAccount.query.filter_by(is_active=True).all()
    if not accounts:
        return {"tagged": 0, "entries": 0}
    by_method = {}
    for account in accounts:
        for method in account.methods:
            by_method.setdefault(method, account)
    main = next((a for a in accounts if a.code == "1010"), None)

    tagged = 0
    tagged += _tag(Payment, by_method, main)
    tagged += _tag(Expense, by_method, main, method_attr="payment_method")
    tagged += _tag(SupplierPayment, by_method, main)
    db.session.commit()

    entries = _correct_ledger(accounts, main)
    return {"tagged": tagged, "entries": entries}


def _tag(model, by_method, fallback, method_attr="method"):
    """Fill account_id on rows that predate tills, from their payment method.

    A method with no till of its own falls back to the main drawer — which is
    where its journal entry already sits, so the label and the ledger agree.
    """
    rows = model.query.filter(model.account_id.is_(None)).all()
    done = 0
    for row in rows:
        account = by_method.get(getattr(row, method_attr, None) or "") or fallback
        if account is None:
            continue
        row.account_id = account.id
        done += 1
    return done


def _correct_ledger(accounts, main):
    """One entry per till, moving its historical total out of the drawer.

    Only for tills that are *not* the main drawer: money the ledger already
    put in 1010 that belongs somewhere else. Posted with ``replace=True``
    against a stable reference, so running the upgrade twice corrects the
    books once.
    """
    from app.utils.accounting import post_entry
    from app.utils.treasury import account_balance

    if main is None:
        return 0
    made = 0
    for account in accounts:
        if account.id == main.id:
            continue
        total = account_balance(account)
        if not total:
            continue
        memo = f"{MEMO} — {account.name}"
        # Dr the till it really was in, Cr the drawer it was wrongly booked to.
        lines = [(account.code, total, 0, memo),
                 (main.code, 0, total, memo)]
        if post_entry("till_migration", account.id, memo, lines,
                      replace=True) is not None:
            made += 1
    return made
