"""The cost-centre report: each part of the clinic, what it brought in and
what it cost.

Read from the journal and nothing else, so it adds up to the income statement
to the pound — the same lines, grouped one more way. Three kinds of line do
not belong to a centre and are shown as themselves rather than spread:

* **shared costs** — an expense entered against no centre (the rent, the
  electricity) and a doctor paid on account. The clinic chose this: a line of
  its own, not a share worked out by a rule nobody agreed;
* **revenue not placed** — every invoice posted before centres existed, and
  money an insurer paid on a claim, which settles many bills at once;
* nothing else: a centre's revenue and its direct costs are what the journal
  says they are, and the net at the bottom is the income statement's.

The doctors' share of a centre's revenue is shown inside its bar, read from the
bills themselves. It is information, not a cost here: the ledger books the
doctor's money when it is paid, on account, and that is in the shared costs.
"""
from app.extensions import db
from app.models import (Account, CostCentre, Invoice, InvoiceItem,
                        JournalEntry, JournalLine)


def _money(value):
    return round(value or 0, 2)


def report(date_from, date_to):
    rows = (db.session.query(JournalLine.cost_centre_id, Account,
                             JournalEntry.source_type,
                             db.func.sum(JournalLine.debit),
                             db.func.sum(JournalLine.credit))
            .join(Account, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalEntry.entry_date >= date_from,
                    JournalEntry.entry_date <= date_to,
                    Account.type.in_(["revenue", "expense"]))
            .group_by(JournalLine.cost_centre_id, Account.id,
                      JournalEntry.source_type)
            .all())

    centres = {}
    shared = {}
    unplaced = {}
    total_rev = total_exp = 0.0
    for centre_id, account, source, debit, credit in rows:
        if account.type == "revenue":
            amount = (credit or 0) - (debit or 0)
            total_rev += amount
        else:
            amount = (debit or 0) - (credit or 0)
            total_exp += amount
        if not amount:
            continue
        if centre_id is None:
            if account.type == "revenue":
                why = source if source in ("invoice", "claim") else "other"
                unplaced[why] = unplaced.get(why, 0) + amount
            else:
                shared[account] = shared.get(account, 0) + amount
            continue
        line = centres.setdefault(centre_id, {
            "revenue": 0.0, "direct": 0.0, "accounts": {}})
        line["revenue" if account.type == "revenue" else "direct"] += amount
        line["accounts"][account] = line["accounts"].get(account, 0) + amount

    doctors = dict(
        db.session.query(InvoiceItem.cost_centre_id,
                         db.func.sum(InvoiceItem.commission_amount))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .filter(Invoice.invoice_date >= date_from,
                Invoice.invoice_date <= date_to,
                InvoiceItem.cost_centre_id.isnot(None))
        .group_by(InvoiceItem.cost_centre_id).all())

    names = {c.id: c for c in CostCentre.query.filter(
        CostCentre.id.in_(list(centres) or [0])).all()}
    lines = []
    for centre_id, line in centres.items():
        revenue = _money(line["revenue"])
        direct = _money(line["direct"])
        contribution = _money(revenue - direct)
        doctor_share = min(_money(doctors.get(centre_id)), max(revenue, 0))
        lines.append({
            "centre": names.get(centre_id),
            "revenue": revenue,
            "direct": direct,
            "contribution": contribution,
            "margin": (round(contribution * 100 / revenue, 1)
                       if revenue > 0 else None),
            "doctors": doctor_share,
            "accounts": sorted(((a, _money(v)) for a, v in line["accounts"].items()),
                               key=lambda av: (av[0].type != "revenue", av[0].code)),
        })
    lines.sort(key=lambda line: (-line["revenue"], -line["direct"]))
    widest = max((max(line["revenue"], line["direct"]) for line in lines),
                 default=0)
    for line in lines:
        line["bar"] = round(line["revenue"] * 100 / widest, 1) if widest else 0
        line["cost_bar"] = round(line["direct"] * 100 / widest, 1) if widest else 0
        line["doctor_bar"] = (round(line["doctors"] * 100 / widest, 1)
                              if widest else 0)

    placed_rev = _money(sum(line["revenue"] for line in lines))
    total_rev = _money(total_rev)
    total_exp = _money(total_exp)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "lines": lines,
        "shared": sorted(((a, _money(v)) for a, v in shared.items()),
                         key=lambda av: av[0].code),
        "shared_total": _money(sum(shared.values())),
        "unplaced": {k: _money(v) for k, v in unplaced.items() if _money(v)},
        "unplaced_total": _money(sum(unplaced.values())),
        "revenue": total_rev,
        "expenses": total_exp,
        "net": _money(total_rev - total_exp),
        "contribution": _money(sum(line["contribution"] for line in lines)),
        "placed_pct": (round(placed_rev * 100 / total_rev) if total_rev > 0
                       else None),
    }
