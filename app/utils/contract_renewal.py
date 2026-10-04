"""A new contract from a date, and its prices, without retyping a list.

Asked as *«لو الادارة عايز تعمل عقد جديد مثلاً من تاريخ كذا الى كذا … انا كنت
عامل العقد من كذا لكذا علشان بعد كده يتنفذ لوحده»* and *«هزود 20% على الكشف
هزود 30% على كذا … او انزل شيت للعقد … واعدل على اسعاره وبعد كده ارفعه»*.

The dates already do the work: a renewal is a copy of the old contract with
its own period, and on its first day it bills by itself (the contract with
the later start wins a shared day — `PayerEntity.active_contract`). What was
missing is changing the copy's prices without retyping them:

* **a raise** — by service, by category, or everything, a percentage or an
  amount, rounded the way the hospital rounds;
* **a sheet** — the contract's list downloaded, edited in Excel, uploaded.

**Both end at the same screen**, a preview of what would change — prices
moved, services newly covered, services out of the contract, rows not
recognised — and nothing is written until somebody confirms it. The confirm
posts the whole proposed list to the contract's own save, so there is one
way a price list is written, not three.

And the reminder (`state`): how long a contract has left, whether its renewal
is ready, and — the case that costs money quietly — a contract that ended
with no renewal while members still carry valid cards, whose children are
now billed the cash price.
"""
import math
from datetime import timedelta

from app.extensions import db

REMIND_KEY = "contract_remind_days"
DEFAULT_REMIND_DAYS = 30
ROUNDINGS = (0, 1, 5, 10)


# ------------------------------------------------------------ the reminder --
def remind_days():
    from app.models import Setting

    try:
        days = int(Setting.get(REMIND_KEY) or DEFAULT_REMIND_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_REMIND_DAYS
    return max(1, min(days, 365))


def successor(contract):
    """The renewal already made for ``contract`` — an active contract of the
    same payer that starts after it and has not ended."""
    if contract is None or contract.payer is None:
        return None
    from app.utils.clock import local_today

    today = local_today()
    start = contract.start_date
    later = [c for c in contract.payer.contracts
             if c.id != contract.id and c.is_active and c.start_date
             and (start is None or c.start_date > start)
             and (c.end_date is None or c.end_date >= today)]
    return min(later, key=lambda c: c.start_date) if later else None


def _members_with_cards(payer_id, today):
    from app.models import PatientCoverage

    rows = PatientCoverage.query.filter_by(payer_id=payer_id, is_active=True).all()
    return sum(1 for r in rows if r.expiry_date is None or r.expiry_date >= today)


def state(contract, today=None, days=None):
    """``{"key", "days", "renewal"}`` for the payers screen and the bell, or
    ``None`` when there is nothing to say.

    * ``renewed`` — ending, and its renewal is ready (says when it starts);
    * ``ending`` — ends within the reminder window, no renewal yet;
    * ``lapsed`` — ended, no contract in force for the payer, and members
      still carry valid cards.
    """
    from app.utils.clock import local_today

    if contract is None or not contract.is_active or contract.end_date is None:
        return None
    today = today or local_today()
    days = remind_days() if days is None else days
    left = (contract.end_date - today).days
    nxt = successor(contract)
    if left >= 0:
        if left > days:
            return None
        if nxt is not None:
            return {"key": "renewed", "days": left, "renewal": nxt}
        return {"key": "ending", "days": left, "renewal": None}
    if nxt is not None or contract.payer.active_contract(today) is not None:
        return None
    # Only the newest ended contract speaks for its payer.
    newer = [c for c in contract.payer.contracts
             if c.id != contract.id and c.is_active and c.end_date
             and c.end_date > contract.end_date]
    if newer:
        return None
    members = _members_with_cards(contract.payer_id, today)
    if not members:
        return None
    return {"key": "lapsed", "days": left, "renewal": None, "members": members}


def needing_attention(today=None):
    """``(ending, lapsed)`` — contracts to renew, and ones that lapsed."""
    from app.models import PayerContract
    from app.utils.clock import local_today

    today = today or local_today()
    days = remind_days()
    rows = (PayerContract.query
            .filter(PayerContract.is_active.is_(True),
                    PayerContract.end_date.isnot(None),
                    PayerContract.end_date <= today + timedelta(days=days)).all())
    ending, lapsed = [], []
    for c in rows:
        found = state(c, today, days)
        if found is None:
            continue
        if found["key"] == "ending":
            ending.append(c)
        elif found["key"] == "lapsed":
            lapsed.append(c)
    return ending, lapsed


# ----------------------------------------------------- the proposed list --
def rounded(value, step):
    """``value`` to the hospital's step (0 = to the piastre), half up."""
    if value is None:
        return None
    if not step:
        return round(value + 1e-9, 2)
    return float(math.floor(value / step + 0.5) * step)


def current(contract, services):
    """``{service_id: (price, type, value)}`` — the list as it stands;
    ``type`` is ``none`` where the contract does not cover the service."""
    rates = {r.service_id: r for r in contract.rates}
    out = {}
    for svc in services:
        r = rates.get(svc.id)
        if r is None:
            out[svc.id] = (None, "none", 0.0)
            continue
        covered = (r.coverage_value or 0) > 0
        out[svc.id] = (r.special_price,
                       r.coverage_type if covered else "none",
                       float(r.coverage_value or 0) if covered else 0.0)
    return out


def _in_contract(row):
    price, ctype, _value = row
    return price is not None or ctype != "none"


def raised(contract, services, rules, step=1):
    """The list with ``rules`` applied. ``rules`` is ``[(target, kind,
    value)]`` — target ``all`` · ``cat:<category>`` · ``svc:<id>``; kind
    ``percent`` or ``amount``. The most specific rule decides a service:
    its own, then its category's, then «everything»; they do not add up.

    «Everything» and a category reach the services already in the contract;
    a rule naming one service reaches it either way."""
    now = current(contract, services)
    by = {}
    for target, kind, value in rules:
        if kind not in ("percent", "amount") or value is None:
            continue
        by[target] = (kind, value)
    out = {}
    for svc in services:
        row = now[svc.id]
        rule = by.get(f"svc:{svc.id}")
        if rule is None and _in_contract(row):
            rule = by.get(f"cat:{svc.category}") or by.get("all")
        if rule is None:
            out[svc.id] = row
            continue
        base = row[0] if row[0] is not None else (svc.price or 0)
        kind, value = rule
        new = base * (1 + value / 100.0) if kind == "percent" else base + value
        out[svc.id] = (max(rounded(new, step), 0.0), row[1], row[2])
    return out


def diff(services, before, after):
    """The rows that change, for the preview: ``[{service, kind, before,
    after}]`` with kind ``changed`` · ``added`` · ``removed``."""
    rows = []
    for svc in services:
        a, b = before[svc.id], after[svc.id]
        if a == b:
            continue
        if not _in_contract(a) and _in_contract(b):
            kind = "added" if b[1] != "none" else "changed"
        elif _in_contract(a) and not _in_contract(b):
            kind = "removed"
        elif a[1] == "none" and b[1] != "none":
            kind = "added"
        elif a[1] != "none" and b[1] == "none":
            kind = "removed"
        else:
            kind = "changed"
        rows.append({"service": svc, "kind": kind, "before": a, "after": b})
    return rows


def apply(contract, services, proposal):
    """Write ``proposal`` as the contract's list (the renewal's raise)."""
    from app.models import PayerContractRate

    rates = {r.service_id: r for r in contract.rates}
    for svc in services:
        price, ctype, value = proposal[svc.id]
        row = rates.get(svc.id)
        if price is None and ctype == "none":
            if row is not None:
                db.session.delete(row)
            continue
        if row is None:
            row = PayerContractRate(contract_id=contract.id, service_id=svc.id)
            db.session.add(row)
            contract.rates.append(row)
        row.special_price = price
        row.coverage_type = ctype if ctype != "none" else "percent"
        row.coverage_value = value if ctype != "none" else 0
    db.session.flush()


# ------------------------------------------------------------- the sheet --
COLUMNS = ("code", "service", "category", "list_price", "contract_price",
           "cover_type", "cover_value")
_TYPES = {"percent": "percent", "نسبة": "percent", "%": "percent",
          "amount": "amount", "مبلغ": "amount", "fixed": "amount",
          "": "none", "none": "none", "غير مغطى": "none", "مش متغطي": "none",
          "not covered": "none"}


def export(contract, services, t, lang="ar"):
    """The contract's list as a workbook — every active service, so a
    service the contract does not cover yet can be given cover in Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    now = current(contract, services)
    wb = Workbook()
    ws = wb.active
    ws.title = "Contract"
    ws.sheet_view.rightToLeft = lang == "ar"
    ws.append([t(f"renewal.col_{c}") for c in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8F0EC")
    for svc in services:
        price, ctype, value = now[svc.id]
        ws.append([svc.code or "", svc.display_name(lang), svc.category or "",
                   svc.price or 0, price if price is not None else "",
                   t(f"renewal.type_{ctype}"), value if ctype != "none" else ""])
    for col, width in zip("ABCDEFG", (12, 34, 16, 12, 14, 14, 12)):
        ws.column_dimensions[col].width = width
    # The words a person may type in the cover column, said on a second sheet.
    help_ws = wb.create_sheet("Help")
    for line in (t("renewal.sheet_help_1"), t("renewal.sheet_help_2"),
                 t("renewal.sheet_help_3")):
        help_ws.append([line])
    help_ws.column_dimensions["A"].width = 110
    return wb


def _number(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", ".").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return False


def read(contract, services, stream, t, lang="ar"):
    """``(proposal, unknown, bad)`` from an uploaded sheet.

    A row is matched by its code, else by the service's name exactly as the
    sheet was downloaded. A service missing from the sheet keeps what it
    has — a sheet trimmed to the rows somebody edited is a normal sheet.
    ``unknown`` are rows naming no service here; ``bad`` are rows whose
    figures cannot be read, and they change nothing."""
    import openpyxl

    proposal = current(contract, services)
    by_code = {(s.code or "").strip().lower(): s for s in services if s.code}
    by_name = {}
    for s in services:
        for name in {s.name, s.display_name("ar"), s.display_name("en")}:
            if name:
                by_name[name.strip()] = s
    words = dict(_TYPES)
    for key in ("percent", "amount", "none"):
        words[t(f"renewal.type_{key}").strip().lower()] = key
    book = openpyxl.load_workbook(stream, read_only=True, data_only=True)
    sheet = book.worksheets[0]
    unknown, bad = [], []
    for n, row in enumerate(sheet.iter_rows(values_only=True)):
        if n == 0 or row is None or not any(v not in (None, "") for v in row):
            continue
        cells = list(row) + [None] * (len(COLUMNS) - len(row))
        code, name, _cat, _list, price, ctype, value = cells[:7]
        svc = by_code.get(str(code).strip().lower()) if code not in (None, "") else None
        if svc is None and name:
            svc = by_name.get(str(name).strip())
        if svc is None:
            unknown.append(n + 1)
            continue
        price = _number(price)
        value = _number(value)
        kind = words.get(str(ctype or "").strip().lower())
        if price is False or value is False or kind is None \
                or (price is not None and price < 0) \
                or (kind != "none" and (not value or value <= 0)) \
                or (kind == "percent" and value > 100):
            bad.append(n + 1)
            continue
        proposal[svc.id] = (price, kind, float(value) if kind != "none" else 0.0)
    return proposal, unknown, bad
