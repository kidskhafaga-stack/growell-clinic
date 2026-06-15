"""Bulk patient import: parsing Excel/CSV and building the template.

Header matching is alias-based and case-insensitive, accepting both English
keys and common Arabic column names so a clinic's existing sheet often works
without renaming columns.
"""
import csv
import io
from datetime import date, datetime

# Canonical columns in template order: (key, required, arabic_label, sample).
IMPORT_COLUMNS = [
    ("reference_number", False, "رقم الملف المرجعي", "1043"),
    ("full_name", True, "الاسم بالعربي", "أحمد محمد"),
    ("full_name_en", False, "الاسم بالإنجليزي", "Ahmed Mohamed"),
    ("date_of_birth", True, "تاريخ الميلاد (YYYY-MM-DD)", "2022-03-01"),
    ("gender", True, "الجنس (male/female)", "male"),
    ("national_id", False, "الرقم القومي", "22203011234567"),
    ("blood_type", False, "فصيلة الدم", "O+"),
    ("allergies", False, "الحساسية", "البنسلين"),
    ("chronic_diseases", False, "الأمراض المزمنة", ""),
    ("family_name", False, "اسم الأسرة (لربط الأخوة)", "عائلة محمد"),
    ("parent_name", False, "اسم ولي الأمر", "محمد علي"),
    ("parent_relation", False, "صلة القرابة (father/mother)", "father"),
    ("parent_phone", False, "هاتف ولي الأمر", "01000000000"),
    ("client_category", False, "فئة العميل (normal/friend/relative/employee)", "normal"),
    ("notes", False, "ملاحظات", ""),
]

# Accepted header aliases (lower-cased) -> canonical key.
COLUMN_ALIASES = {
    "reference_number": "reference_number", "ref": "reference_number",
    "رقم الملف": "reference_number", "رقم الملف المرجعي": "reference_number",
    "الرقم المرجعي": "reference_number", "رقم قديم": "reference_number",
    "full_name": "full_name", "name": "full_name", "الاسم": "full_name",
    "الاسم بالعربي": "full_name", "اسم المريض": "full_name",
    "full_name_en": "full_name_en", "name_en": "full_name_en",
    "english name": "full_name_en", "الاسم بالإنجليزي": "full_name_en",
    "الاسم بالانجليزي": "full_name_en",
    "date_of_birth": "date_of_birth", "dob": "date_of_birth",
    "birth": "date_of_birth", "تاريخ الميلاد": "date_of_birth",
    "تاريخ الميلاد (yyyy-mm-dd)": "date_of_birth", "الميلاد": "date_of_birth",
    "gender": "gender", "sex": "gender", "الجنس": "gender", "النوع": "gender",
    "الجنس (male/female)": "gender",
    "national_id": "national_id", "nid": "national_id",
    "الرقم القومي": "national_id",
    "blood_type": "blood_type", "blood": "blood_type",
    "فصيلة الدم": "blood_type", "الفصيلة": "blood_type",
    "allergies": "allergies", "الحساسية": "allergies", "حساسية": "allergies",
    "chronic_diseases": "chronic_diseases", "chronic": "chronic_diseases",
    "الأمراض المزمنة": "chronic_diseases", "الامراض المزمنة": "chronic_diseases",
    "family_name": "family_name", "family": "family_name",
    "الأسرة": "family_name", "الاسرة": "family_name",
    "اسم الأسرة": "family_name", "اسم الاسرة": "family_name",
    "اسم الأسرة (لربط الأخوة)": "family_name", "العائلة": "family_name",
    "parent_name": "parent_name", "parent": "parent_name",
    "ولي الأمر": "parent_name", "ولي الامر": "parent_name",
    "اسم ولي الأمر": "parent_name", "اسم ولي الامر": "parent_name",
    "parent_relation": "parent_relation", "relation": "parent_relation",
    "صلة القرابة": "parent_relation", "صلة القرابة (father/mother)": "parent_relation",
    "parent_phone": "parent_phone", "phone": "parent_phone",
    "هاتف ولي الأمر": "parent_phone", "الهاتف": "parent_phone",
    "التليفون": "parent_phone", "الموبايل": "parent_phone",
    "client_category": "client_category", "category": "client_category",
    "فئة العميل": "client_category", "الفئة": "client_category",
    "فئة العميل (normal/friend/relative/employee)": "client_category",
    "notes": "notes", "ملاحظات": "notes",
}

ALLOWED_IMPORT_EXTENSIONS = {"xlsx", "csv"}

_GENDER_MAP = {
    "male": "male", "m": "male", "ذكر": "male", "ولد": "male",
    "female": "female", "f": "female", "أنثى": "female", "انثى": "female",
    "بنت": "female",
}

_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y",
]


def allowed_import_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMPORT_EXTENSIONS
    )


def _norm_header(value):
    return str(value or "").strip().lower()


def map_headers(raw_headers):
    """Map a sheet's header row to canonical column keys (by position)."""
    mapping = {}
    for idx, h in enumerate(raw_headers):
        key = COLUMN_ALIASES.get(_norm_header(h))
        if key:
            mapping[idx] = key
    return mapping


def parse_gender(value):
    return _GENDER_MAP.get(_norm_header(value))


def parse_date(value):
    """Parse a cell into a ``date`` or return None if unparseable/empty."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # Excel may hand us a float serial as text occasionally; ignore those.
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def read_rows(file_storage):
    """Read an uploaded .xlsx/.csv into a list of canonical-key dicts.

    Returns (rows, error). ``rows`` is a list of dicts keyed by canonical
    column name with raw cell values; row numbers are 1-based data rows.
    """
    filename = (file_storage.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "xlsx":
        return _read_xlsx(file_storage)
    if ext == "csv":
        return _read_csv(file_storage)
    return [], "unsupported"


def _rows_from_matrix(matrix):
    if not matrix:
        return [], "empty"
    headers = matrix[0]
    mapping = map_headers(headers)
    if "full_name" not in mapping.values():
        return [], "no_name_column"
    rows = []
    for raw in matrix[1:]:
        if not any(str(c).strip() for c in raw if c is not None):
            continue  # skip fully blank rows
        record = {}
        for idx, key in mapping.items():
            if idx < len(raw):
                val = raw[idx]
                record[key] = val.strip() if isinstance(val, str) else val
        rows.append(record)
    return rows, None


def _read_xlsx(file_storage):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(file_storage, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - surface a friendly message
        return [], "unreadable"
    ws = wb.active
    matrix = [list(row) for row in ws.iter_rows(values_only=True)]
    return _rows_from_matrix(matrix)


def _read_csv(file_storage):
    raw = file_storage.read()
    if isinstance(raw, bytes):
        # utf-8-sig strips a BOM that Excel-exported CSVs often carry.
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = raw
    reader = csv.reader(io.StringIO(text))
    matrix = [row for row in reader]
    return _rows_from_matrix(matrix)


def build_template_workbook():
    """Return a BytesIO .xlsx template with headers, a sample, and instructions."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Patients"

    header_fill = PatternFill("solid", fgColor="198754")
    header_font = Font(color="FFFFFF", bold=True)

    headers = [c[0] for c in IMPORT_COLUMNS]
    sample = [c[3] for c in IMPORT_COLUMNS]
    ws.append(headers)
    ws.append(sample)
    for col, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = 22

    # Instructions sheet (Arabic descriptions).
    info = wb.create_sheet("تعليمات")
    info.append(["العمود (Column)", "الوصف", "إلزامي؟"])
    for key, required, label, _ in IMPORT_COLUMNS:
        info.append([key, label, "نعم" if required else "لا"])
    for col in ("A", "B", "C"):
        info.column_dimensions[col].width = 32

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def build_template_csv():
    """Return CSV template text (BOM included for Excel compatibility)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c[0] for c in IMPORT_COLUMNS])
    writer.writerow([c[3] for c in IMPORT_COLUMNS])
    return "﻿" + out.getvalue()
