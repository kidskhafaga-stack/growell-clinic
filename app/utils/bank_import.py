"""Reading a bank statement, and finding out which lines the clinic knows about.

Two jobs that are easy to confuse.

**Parsing** turns whatever the bank exported into dated, signed amounts. Every
Egyptian bank exports something different: one signed column or a debit and a
credit column, Arabic headers or English, Arabic-Indic digits, thousands
commas, negatives in brackets, the amount with "EGP" stuck on the end. None of
that is interesting and all of it has to work, because a clinic will not retype
a statement by hand and a parser that gives up sends them back to paper.

**Matching** says "this statement line and this payment are the same event".
That is a claim about two records the clinic already has, and it is the whole
value of the exercise: what matters is not the lines that matched but the ones
that did not — money the bank knows about that the clinic never recorded, and
money the clinic recorded that never arrived.

Two rules the rest of this file exists to keep:

**Nothing is matched when the answer is ambiguous.** One candidate at the same
amount within a few days is a match. Two candidates is a question for a person.
A reconciliation that quietly picked one of two identical amounts would report
"all matched" while pointing at the wrong movement, which is worse than
reporting nothing.

**Nothing posts a journal entry.** A line with no match is a question, and the
answer is sometimes "record the bank charge" and sometimes "the bank made a
mistake" — the program is in no position to choose, and a reconciliation that
invented entries to make itself balance would be describing its own arithmetic
rather than the clinic's money.
"""
import csv
import hashlib
import io
import re
from datetime import date, datetime

# Days either side of the statement date a movement may sit and still be the
# same event. A transfer typed on Thursday shows up on the statement on Sunday.
DEFAULT_WINDOW_DAYS = 3

# Amounts equal to the piastre. Floats being floats, 19.0 and 18.999999 are the
# same fee and must not be two.
TOLERANCE = 0.005

# Tills with something external to check against. A cash drawer has no
# statement — it has a count, which is a different screen.
RECONCILABLE_KINDS = ("bank", "wallet", "clearing")

# Header aliases, lower-cased and stripped. A clinic's existing export usually
# works without renaming a thing.
HEADERS = {
    "date": ("date", "value date", "transaction date", "posting date", "trx date",
             "التاريخ", "تاريخ", "تاريخ العملية", "تاريخ الحركة",
             "تاريخ القيمة", "تاريخ الاستحقاق"),
    "amount": ("amount", "value", "signed amount", "transaction amount",
               "المبلغ", "القيمة", "مبلغ", "قيمة الحركة"),
    "debit": ("debit", "dr", "withdrawal", "withdrawals", "paid out", "out",
              "مدين", "منصرف", "سحب", "خارج", "مسحوبات"),
    "credit": ("credit", "cr", "deposit", "deposits", "paid in", "in",
               "دائن", "وارد", "إيداع", "ايداع", "داخل", "إيداعات"),
    "description": ("description", "details", "narrative", "narration", "memo",
                    "particulars", "statement", "البيان", "التفاصيل", "الوصف",
                    "بيان الحركة", "الشرح", "ملاحظات"),
    "reference": ("reference", "ref", "ref no", "reference no", "cheque",
                  "cheque no", "document", "doc no", "transaction id",
                  "المرجع", "رقم المرجع", "رقم العملية", "الشيك", "رقم الشيك",
                  "رقم المستند"),
    "balance": ("balance", "running balance", "closing balance", "الرصيد",
                "الرصيد بعد الحركة", "رصيد"),
}

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y",
                 "%Y/%m/%d", "%d %b %Y", "%d-%b-%Y", "%d/%m/%y", "%d-%b-%y")


class StatementError(ValueError):
    """A statement that cannot be read, with a key the screen can name."""


# ------------------------------------------------------------- parsing -----
def _norm(text):
    if text is None:
        return ""
    text = str(text).translate(_ARABIC_DIGITS).strip().lower()
    # Arabic orthography varies by whoever typed the header.
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ى", "ي").replace("ة", "ه"))
    return re.sub(r"[\s_.:\-]+", " ", text).strip()


def map_headers(headers):
    """Column index -> canonical key, for the headers we recognise."""
    wanted = {}
    for index, raw in enumerate(headers):
        name = _norm(raw)
        if not name:
            continue
        for key, aliases in HEADERS.items():
            if key in wanted.values():
                continue                    # first matching column wins
            if name in {_norm(a) for a in aliases}:
                wanted[index] = key
                break
    return wanted


def parse_amount(value):
    """A money cell as a float, or None.

    Handles Arabic-Indic digits, thousands separators, a trailing currency, a
    leading minus, and accountants' brackets for negatives — all of which turn
    up in real exports and none of which mean anything different.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).translate(_ARABIC_DIGITS).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace("٫", ".").replace("٬", ",").replace("،", ",")
    # Pull the number *out* rather than deleting everything that is not one.
    # Deleting is the tempting version and it is wrong: "ج.م ٧٥٠" has a dot in
    # the currency, and stripping the letters leaves ".750" — seven hundred and
    # fifty read as three quarters of a pound.
    found = re.search(r"\d[\d,.]*", text)
    if found is None:
        return None
    # A minus ahead of the number is a minus wherever the export put it —
    # before the currency, after it, with a space.
    if "-" in text[:found.start()]:
        negative = True
    text = found.group(0).rstrip(".,")
    if text.count(",") and text.count("."):
        text = text.replace(",", "")        # 1,234.56
    elif text.count(",") and not text.count("."):
        # 1,234 is thousands; 1,50 is a decimal comma. Three trailing digits
        # after the last comma is the giveaway.
        parts = text.split(",")
        text = "".join(parts) if len(parts[-1]) == 3 else ".".join(parts)
    if not re.fullmatch(r"\d*\.?\d*", text) or text in ("", "."):
        return None
    number = float(text)
    return -number if negative else number


def parse_date(value):
    """A date cell as a ``date``, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).translate(_ARABIC_DIGITS).strip()
    if not text:
        return None
    text = text.split(" ")[0] if re.match(r"^\d", text) and " " in text \
        and ":" in text else text
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_matrix(headers, data):
    """Rows of a statement as dicts, plus the rows that could not be read.

    Returns ``(rows, skipped)``. A row is skipped rather than guessed at when
    it has no date or no amount: a statement line without either is a subtotal,
    a header repeat, or a blank, and inventing values for it would put money in
    the reconciliation that the bank never mentioned.
    """
    mapping = map_headers(headers)
    keys = set(mapping.values())
    if "date" not in keys:
        raise StatementError("no_date_column")
    if not keys & {"amount", "debit", "credit"}:
        raise StatementError("no_amount_column")

    rows, skipped = [], 0
    for raw in data:
        cell = {key: (raw[i] if i < len(raw) else None)
                for i, key in mapping.items()}
        when = parse_date(cell.get("date"))
        amount = _signed(cell)
        if when is None or amount is None or amount == 0:
            skipped += 1
            continue
        rows.append({
            "date": when,
            "amount": round(amount, 2),
            "description": _text(cell.get("description"), 255),
            "reference": _text(cell.get("reference"), 80),
            "balance": parse_amount(cell.get("balance")),
        })
    return rows, skipped


def _signed(cell):
    """One signed amount out of whichever columns the bank used.

    Positive is money arriving. A debit column carries a positive number that
    means the opposite, which is exactly the trap this folds away — "which
    column was it in" is a property of the export format, not of what happened.
    """
    if "amount" in cell:
        direct = parse_amount(cell.get("amount"))
        if direct:
            return direct
    credit = parse_amount(cell.get("credit")) or 0
    debit = parse_amount(cell.get("debit")) or 0
    total = abs(credit) - abs(debit)
    return total or None


def _text(value, limit):
    if value in (None, ""):
        return None
    return str(value).strip()[:limit] or None


def read_statement(file_storage):
    """Parse an uploaded .csv/.xlsx statement into rows.

    Reuses the spreadsheet reader the patient importer already uses, so a bank
    that only exports Excel is not a reason to make the clinic convert files.
    """
    from app.utils.imports import read_matrix

    headers, data, error = read_matrix(file_storage)
    if error == "unsupported":
        raise StatementError("unsupported_file")
    if error or not data:
        raise StatementError("empty_file")
    return parse_matrix(headers, data)


# ------------------------------------------------------------- storing -----
def digest(row):
    """A fingerprint of a statement row as it appeared in the file.

    Used to tell a re-import from new lines. Deliberately **not** a unique
    key: two genuinely identical transactions on one day are two transactions,
    and a unique index would swallow the second one silently.
    """
    parts = (row["date"].isoformat(), f"{row['amount']:.2f}",
             (row.get("description") or ""), (row.get("reference") or ""))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:40]


def import_lines(account, file_storage, user_id=None):
    """Store a statement against one till. Returns ``(added, skipped, repeats)``.

    Re-importing the same file adds nothing: each row's fingerprint is counted
    against how many rows carrying it are already stored, and only the surplus
    is inserted. That handles the honest duplicate too — a statement with two
    identical 200 lines imported twice ends with two, not one and not four.
    """
    from collections import Counter

    from app.extensions import db
    from app.models import BankLine

    if account is None:
        raise StatementError("no_account")
    if account.kind not in RECONCILABLE_KINDS:
        raise StatementError("not_reconcilable")

    rows, skipped = read_statement(file_storage)
    if not rows:
        raise StatementError("nothing_readable")

    already = Counter(d for (d,) in db.session.query(BankLine.digest)
                      .filter(BankLine.account_id == account.id).all())
    added, repeats = 0, 0
    for row in rows:
        mark = digest(row)
        if already[mark] > 0:
            already[mark] -= 1
            repeats += 1
            continue
        db.session.add(BankLine(
            account_id=account.id, line_date=row["date"], amount=row["amount"],
            description=row["description"], reference=row["reference"],
            balance=row["balance"], digest=mark, status="unmatched",
            imported_by=user_id))
        added += 1
    db.session.commit()
    return added, skipped, repeats


# ------------------------------------------------------------ matching -----
def _taken(account_id):
    """Movements already claimed by a statement line, so two lines cannot both
    point at the same payment."""
    from app.models import BankLine

    rows = (BankLine.query
            .filter(BankLine.account_id == account_id,
                    BankLine.status == "matched").all())
    return {(r.matched_kind, r.matched_id) for r in rows}


def candidates(line, rows=None, window_days=DEFAULT_WINDOW_DAYS, taken=None):
    """Movements that could be this statement line, best first.

    Same amount to the piastre, dated within the window, and not already
    claimed by another line. The amount has to be exact: "close enough" on
    money is how a reconciliation comes to point at the wrong transaction.
    """
    from datetime import timedelta

    from app.utils import treasury

    if rows is None:
        rows = treasury.movements(line.account)
    if taken is None:
        taken = _taken(line.account_id)

    low = line.line_date - timedelta(days=window_days)
    high = line.line_date + timedelta(days=window_days)
    out = []
    for row in rows:
        when = row["at"].date() if row["at"] else None
        if when is None or when < low or when > high:
            continue
        if abs(row["amount"] - line.amount) > TOLERANCE:
            continue
        if (row["kind"], row["id"]) in taken:
            continue
        out.append(dict(row, gap=abs((when - line.line_date).days)))
    # Nearest date first: of two identical amounts, the one on the statement's
    # own day is the likelier pair. It is still not matched automatically.
    out.sort(key=lambda r: r["gap"])
    return out


def match(line, kind, movement_id, user_id=None):
    """Tie a statement line to a movement the clinic already recorded."""
    from app.extensions import db

    if line is None:
        raise StatementError("no_line")
    if line.status == "matched":
        raise StatementError("already_matched")
    if not kind or movement_id is None:
        raise StatementError("no_movement")
    if (kind, movement_id) in _taken(line.account_id):
        raise StatementError("movement_taken")
    line.status = "matched"
    line.matched_kind = kind
    line.matched_id = movement_id
    line.matched_by = user_id
    db.session.commit()
    return line


def unmatch(line, user_id=None):
    """Undo a match. Always available: a wrong match that could not be undone
    would be a permanent lie about which payment reached the bank."""
    from app.extensions import db

    if line is None:
        raise StatementError("no_line")
    line.status = "unmatched"
    line.matched_kind = None
    line.matched_id = None
    line.matched_by = user_id
    db.session.commit()
    return line


def ignore(line, note=None, user_id=None):
    """Set a line aside — with words, because "ignored" alone tells nobody why.

    The honest use is a line that belongs to something outside this program: a
    loan instalment, an owner's own transfer, interest.
    """
    from app.extensions import db

    if line is None:
        raise StatementError("no_line")
    note = (note or "").strip()
    if not note:
        raise StatementError("need_note")
    line.status = "ignored"
    line.note = note[:255]
    line.matched_kind = None
    line.matched_id = None
    line.matched_by = user_id
    db.session.commit()
    return line


def auto_match(account, window_days=DEFAULT_WINDOW_DAYS, user_id=None):
    """Match every line that has exactly one possible answer. Returns the count.

    **Exactly one.** Two candidates at the same amount is a question for a
    person, and picking one of them would let the screen report "reconciled"
    while pointing at the wrong movement — a reconciliation that lies is worse
    than one that leaves work to do.
    """
    from app.extensions import db
    from app.models import BankLine
    from app.utils import treasury

    rows = treasury.movements(account)
    taken = _taken(account.id)
    lines = (BankLine.query
             .filter(BankLine.account_id == account.id,
                     BankLine.status == "unmatched")
             .order_by(BankLine.line_date, BankLine.id).all())
    matched = 0
    for line in lines:
        found = candidates(line, rows=rows, window_days=window_days,
                           taken=taken)
        if len(found) != 1:
            continue
        only = found[0]
        line.status = "matched"
        line.matched_kind = only["kind"]
        line.matched_id = only["id"]
        line.matched_by = user_id
        taken.add((only["kind"], only["id"]))
        matched += 1
    if matched:
        db.session.commit()
    return matched


def reconciliation(account, window_days=DEFAULT_WINDOW_DAYS):
    """The two-sided answer: what the bank says, what the program says, and the
    lines on each side nobody can explain.

    Both sides matter and they mean different things. A statement line with no
    movement is money the bank knows about that the clinic never recorded — a
    fee, a direct debit, a collection that went missing. A movement with no
    statement line is money the clinic recorded that never arrived, which is
    the more alarming of the two.
    """
    from app.models import BankLine
    from app.utils import treasury

    lines = (BankLine.query.filter(BankLine.account_id == account.id)
             .order_by(BankLine.line_date, BankLine.id).all())
    rows = treasury.movements(account)
    taken = _taken(account.id)

    unmatched = [ln for ln in lines if ln.status == "unmatched"]
    for line in unmatched:
        line.options = candidates(line, rows=rows, window_days=window_days,
                                  taken=taken)

    return {
        "lines": lines,
        "unmatched": unmatched,
        "ignored": [ln for ln in lines if ln.status == "ignored"],
        # Movements the statement never mentioned. Only the ones the statement
        # could plausibly cover: a movement dated after the last imported line
        # has not had its chance to arrive yet, and calling it missing would
        # cry wolf on every reconciliation.
        "missing": _unseen(rows, taken, lines),
        "statement_total": round(sum(ln.amount for ln in lines
                                     if ln.status != "ignored"), 2),
        "program_total": round(sum(r["amount"] for r in rows), 2),
        "balance": treasury.account_balance(account),
    }


def _unseen(rows, taken, lines):
    """Movements no statement line accounts for, up to the statement's last day."""
    if not lines:
        return []
    horizon = max(ln.line_date for ln in lines)
    out = []
    for row in rows:
        when = row["at"].date() if row["at"] else None
        if when is None or when > horizon:
            continue
        if (row["kind"], row["id"]) in taken:
            continue
        out.append(row)
    return out


def sample_csv():
    """A one-line template, so "what should the file look like" has an answer."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["التاريخ", "البيان", "المرجع", "مدين", "دائن", "الرصيد"])
    writer.writerow(["2026-07-28", "تحصيل فيزا", "POS-9931", "", "1,975.00",
                     "12,975.00"])
    writer.writerow(["2026-07-29", "مصاريف بنكية", "", "25.00", "",
                     "12,950.00"])
    return buf.getvalue()
