"""Reading a clinic's old case history out of whatever its last program exported.

Every clinic's export has a different shape, so nothing here assumes a layout:
the columns are matched by their headers (Arabic or English), the guess is shown
on a mapping screen, and the clinic corrects it. That is the same shape as the
patient import, on purpose — somebody who has done one should recognise the
other.

**Speed.** A real export is 9,908 rows and reading it takes under a second, so
the file was never the bottleneck; the database is. Two rules keep it that way,
and both are load-bearing rather than tidiness:

* **Look things up in bulk, once.** One query builds ``{file number: patient}``
  for the whole upload. Asking per row is ten thousand round trips, which turns
  a two-second import into minutes of a spinning screen.
* **Parse once, not once per screen.** The parsed rows are cached between the
  mapping step, the preview and the import, so walking through the wizard does
  not re-read the workbook three times.
"""
import re
from datetime import date, datetime, time

# Canonical columns: (key, required, arabic label).
HISTORY_COLUMNS = [
    ("source_row", False, "م (رقم السطر في البرنامج القديم)"),
    ("service_date", True, "تاريخ الخدمة"),
    ("service_time", False, "وقت الخدمة"),
    ("patient_code", True, "كود المريض"),
    ("patient_name", False, "اسم المريض"),
    ("doctor_code", False, "كود الطبيب"),
    ("doctor_name", False, "اسم الطبيب"),
    ("service_name", True, "الخدمة"),
    ("service_group", False, "فئة الخدمة"),
    ("service_kind", False, "نوع الخدمة"),
    ("client_category", False, "التعاقد / فئة العميل"),
    ("price", False, "السعر الإجمالي"),
    ("doctor_share", False, "نصيب الطبيب"),
    ("paid_cash", False, "نقدي"),
    ("paid_company", False, "شركات"),
    ("quantity", False, "الكمية"),
    ("notes", False, "ملاحظات"),
]

REQUIRED_KEYS = {key for key, required, _ in HISTORY_COLUMNS if required}

# Header aliases, lower-cased and normalised. Deliberately generous: the whole
# point is that a clinic's own export works without renaming anything.
COLUMN_ALIASES = {
    "م": "source_row", "#": "source_row", "مسلسل": "source_row",
    "رقم": "source_row", "id": "source_row", "serial": "source_row",
    "تاريخ الخدمه": "service_date", "التاريخ": "service_date",
    "date": "service_date", "service date": "service_date",
    "تاريخ": "service_date",
    "وقت الخدمه": "service_time", "الوقت": "service_time", "time": "service_time",
    "كود المريض": "patient_code", "رقم المريض": "patient_code",
    "رقم الملف": "patient_code", "كود": "patient_code",
    "patient code": "patient_code", "patient id": "patient_code",
    "file no": "patient_code", "file number": "patient_code",
    "اسم المريض": "patient_name", "المريض": "patient_name",
    "patient": "patient_name", "patient name": "patient_name",
    "كود الطبيب": "doctor_code", "doctor code": "doctor_code",
    "اسم الطبيب": "doctor_name", "الطبيب": "doctor_name",
    "doctor": "doctor_name", "doctor name": "doctor_name",
    "الخدمه": "service_name", "الخدمة": "service_name",
    "البند": "service_name", "service": "service_name",
    "service name": "service_name", "الصنف": "service_name",
    "فئة الخدمه": "service_group", "فئه الخدمه": "service_group",
    "service group": "service_group", "category": "service_group",
    "نوع الخدمه": "service_kind", "service type": "service_kind",
    "التعاقد": "client_category", "فئة العميل": "client_category",
    "فئه العميل": "client_category", "نوع العميل": "client_category",
    "client category": "client_category", "contract": "client_category",
    "السعر الاجمالي": "price", "الاجمالي": "price", "السعر": "price",
    "المبلغ": "price", "total": "price", "price": "price", "amount": "price",
    "نصيب الطبيب": "doctor_share", "حصة الطبيب": "doctor_share",
    "doctor share": "doctor_share",
    "نقدي": "paid_cash", "نقدى": "paid_cash", "cash": "paid_cash",
    "شركات": "paid_company", "تامين": "paid_company",
    "company": "paid_company", "insurance": "paid_company",
    "الكميه": "quantity", "العدد": "quantity", "quantity": "quantity",
    "qty": "quantity",
    "ملاحظات": "notes", "notes": "notes", "note": "notes",
}


# --------------------------------------------------------------- normalising
_DIACRITICS = re.compile(r"[ً-ْـ]")


def normalise_arabic(value):
    """Fold the spellings of one Arabic word into a single form.

    ``أ إ آ`` → ``ا``, ``ة`` → ``ه``, ``ى`` → ``ي``, diacritics and tatweel
    dropped, runs of whitespace collapsed. Without this "نقدى" and "نقدي" and
    "نقدي " are three different categories, and an import that matches on the
    raw text builds three of them.
    """
    text = (str(value) if value is not None else "").strip().lower()
    text = _DIACRITICS.sub("", text)
    text = (text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                .replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و")
                .replace("ئ", "ي"))
    return re.sub(r"\s+", " ", text).strip()


# The aliases are matched against *normalised* headers, so they have to be
# normalised themselves. Written by hand they end up half-folded — "فئة الخدمه"
# has the ة on one word and not the other — and then a real header spelt
# "فئة الخدمة" misses by one letter and the column silently goes unmapped.
# Folding the table at import time is the only way the two stay in step.
COLUMN_ALIASES = {normalise_arabic(alias): key
                  for alias, key in COLUMN_ALIASES.items()}


def _norm_header(value):
    return normalise_arabic(value)


# A second pass, for the headers no alias list will ever finish covering.
#
# The alias table matches exactly, which is right for the wordings we know and
# useless for the ones we do not: a file headed "Visit Date" missed the date
# column entirely — a **required** field — and the person importing had to find
# it on the mapping screen and point at it. Measured on an export with English
# headers in a different order: nine of fourteen columns were recognised and
# the date was not one of them.
#
# So each key also carries the *words* that mean it. "Visit Date", "Date of
# service" and "تاريخ الكشف" all contain one, and none of them needs adding by
# hand. Deliberately word-ish rather than clever: no scoring, no distance —
# a wrong guess here silently imports the wrong column, and the mapping screen
# is right there for anything this cannot see.
LOOSE_WORDS = [
    ("service_date", r"date|تاريخ"),
    ("service_time", r"\btime\b|الساعة|الوقت"),
    ("patient_code", r"\bmrn\b|file *(no|number|#)|رقم الملف|كود المريض"),
    ("patient_name", r"patient|المريض|اسم المريض"),
    ("doctor_share", r"(doctor|طبيب|دكتور).*(share|نصيب|حصة)"
                     r"|(share|نصيب|حصة).*(doctor|طبيب|دكتور)"),
    ("doctor_name", r"doctor|طبيب|دكتور|consultant"),
    ("service_name", r"service|procedure|item|الخدمة|الخدمه|البند|الصنف"),
    ("paid_company", r"insurance|company|تامين|تأمين|شرك"),
    ("paid_cash", r"cash|نقد"),
    ("price", r"amount|total|price|fee|السعر|المبلغ|الاجمالي|الإجمالي"),
    ("quantity", r"\bqty\b|quantity|الكمية|الكميه|العدد"),
    ("notes", r"remark|comment|note|ملاحظ"),
]
_LOOSE = [(key, re.compile(pattern, re.I)) for key, pattern in LOOSE_WORDS]


def map_headers(raw_headers):
    """``{column index: canonical key}`` for the headers we recognise.

    Exact aliases first — they are precise and they are what the known exports
    use. The word pass then fills only what is still empty, and only from
    columns nothing has claimed, so it can never overrule a name we know.
    """
    mapping = {}
    for index, header in enumerate(raw_headers):
        key = COLUMN_ALIASES.get(_norm_header(header))
        if key and key not in mapping.values():
            mapping[index] = key

    taken_keys = set(mapping.values())
    for key, pattern in _LOOSE:
        if key in taken_keys:
            continue
        for index, header in enumerate(raw_headers):
            if index in mapping:
                continue
            if pattern.search(str(header or "")):
                mapping[index] = key
                taken_keys.add(key)
                break
    return mapping


def guess_mapping(headers):
    """``{canonical key: column index or ''}`` for the mapping screen."""
    found = map_headers(headers)
    guessed = {key: "" for key, _r, _l in HISTORY_COLUMNS}
    for index, key in found.items():
        guessed[key] = index
    return guessed


def fields():
    """``[(key, required, arabic label)]`` for the mapping screen."""
    return HISTORY_COLUMNS


# ------------------------------------------------------- the summary block --
def summary_columns(headers, rows, threshold=0.98):
    """Indexes of trailing columns that are a summary block, not data.

    The real export ends with ``ملخص الفترة`` / ``القيمة`` holding three rows —
    from date, to date, 9908 services — inside the same sheet. They are laid
    out like columns and read like columns, and a reader that trusts the header
    row imports them as if every service had a "period summary".

    Detected by how empty they are: a data column is filled on nearly every
    row, a summary block on a handful. Only *trailing* columns are considered,
    so a genuinely sparse column in the middle of the sheet is left alone.
    """
    if not rows:
        return set()
    total = len(rows)
    out = set()
    for index in range(len(headers) - 1, -1, -1):
        blank = sum(1 for row in rows
                    if index >= len(row) or row[index] in (None, ""))
        if blank / total >= threshold:
            out.add(index)
        else:
            break                     # the block only ever sits at the end
    return out


# ------------------------------------------------------------- reading rows -
def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _as_time(value):
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _as_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.\-]", "", str(value or ""))
    try:
        return float(text) if text not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _as_int(value, default=1):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def build_rows(data_rows, mapping):
    """Turn the raw sheet into canonical dicts, typed and stripped.

    ``mapping`` is ``{canonical key: column index}``. Rows the sheet holds but
    which carry no service name and no date are dropped here rather than
    surviving to be rejected one by one — those are the blank tails a
    spreadsheet leaves behind, and listing four hundred of them as "errors"
    buries the two that matter.
    """
    out = []
    for number, raw in enumerate(data_rows, start=2):
        record = {"_row": number}
        for key, index in mapping.items():
            if index == "" or index is None:
                continue
            index = int(index)
            record[key] = raw[index] if index < len(raw) else None
        record["service_date"] = _as_date(record.get("service_date"))
        record["service_time"] = _as_time(record.get("service_time"))
        record["price"] = _as_float(record.get("price"))
        record["doctor_share"] = _as_float(record.get("doctor_share"))
        record["paid_cash"] = _as_float(record.get("paid_cash"))
        record["paid_company"] = _as_float(record.get("paid_company"))
        record["quantity"] = _as_int(record.get("quantity"), 1)
        for key in ("patient_code", "patient_name", "doctor_code",
                    "doctor_name", "service_name", "service_group",
                    "service_kind", "client_category", "notes", "source_row"):
            value = record.get(key)
            record[key] = str(value).strip() if value not in (None, "") else ""
        if not record["service_name"] and record["service_date"] is None:
            continue
        out.append(record)
    return out


def source_key(record):
    """What a re-upload compares against.

    The source program's own row number when the export carries one — measured
    unique across all 9,908 rows of a real export, with no blanks — and
    otherwise a fingerprint.

    **The time is in the fingerprint on purpose.** Without it the same file
    produces 80 collisions: the same service, for the same patient, on the same
    day, twice. Those are real rows, and treating them as duplicates would drop
    eighty pieces of history in silence.
    """
    row_no = (record.get("source_row") or "").strip()
    if row_no:
        return f"r:{row_no}"
    parts = [
        (record.get("patient_code") or "").strip(),
        record["service_date"].isoformat() if record.get("service_date") else "",
        record["service_time"].strftime("%H:%M:%S") if record.get("service_time") else "",
        normalise_arabic(record.get("service_name")),
        f"{record.get('price') or 0:.2f}",
    ]
    return "f:" + "|".join(parts)
