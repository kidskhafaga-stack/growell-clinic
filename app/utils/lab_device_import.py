"""An analyser's result file, read onto its tubes (LAB_GLAB360_PLAN.md م-٢ أ;
the rows are ``models/lab_device``).

Most analysers can print their results to a file — comma, semicolon or tab
separated — long before anybody connects them live. This reads that file:

* **two shapes**: a row per test (tube, test code, value, unit, flag), or a
  row per tube with a column per test code (the way most haematology
  analysers print a CBC). The columns are the device's own headers, or found
  by their usual names in English or Arabic;
* **a line is written only when everything is known**: the tube's number
  finds one lab order, the device's code is linked to an analyte here, and
  that analyte is on the order's test. It then goes through **exactly the
  bench's own save** (``lab_results.save``): the child's range, critical,
  delta, auto-validation — and the result is **not released** by arriving;
* **nothing is guessed and nothing is lost**: a tube nobody ordered, a code
  nobody linked, a test not on that order, or a result already written or
  released is held in a list for a person, with the reason, and can be
  written once the link is made — never put on a child by a near match;
* the analyser's own flags (H, L, a sample warning) are kept on the line.
"""
import csv
import io
from datetime import datetime

from app.extensions import db
from app.models.lab_device import (REVIEW_STATES, LabDevice, LabDeviceCode,
                                   LabImportLine, LabImportRun)

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

#: The usual names of each column, compared without case or spaces.
USUAL = {
    "sample": ("sample", "sampleid", "sampleno", "samplenumber", "sample_id", "barcode",
               "specimen", "specimenid", "tube", "tubeid", "id", "labno", "accession",
               "رقمالعينة", "العينة", "الباركود"),
    "code": ("test", "testcode", "testname", "assay", "assaycode", "param", "parameter",
             "analyte", "item", "code", "التحليل", "كودالتحليل"),
    "value": ("result", "value", "res", "resultvalue", "conc", "concentration", "النتيجة",
              "القيمة"),
    "unit": ("unit", "units", "الوحدة"),
    "flag": ("flag", "flags", "alarm", "abnormalflag", "العلامة"),
}


class ImportError_(ValueError):
    """A refusal with a key (``lab_device.err_<key>``)."""


def _norm(name):
    return "".join((name or "").lower().split()).replace("_", "").replace("-", "").replace(".", "")


def _decode(data):
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_("encoding")


def _rows(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ImportError_("empty")
    if len(rows) > MAX_ROWS + 1:
        raise ImportError_("too_big")
    return rows[0], rows[1:]


def _find(header, device_col, key):
    """The index of a column: the device's own header, else a usual name."""
    names = [_norm(h) for h in header]
    if device_col:
        want = _norm(device_col)
        return names.index(want) if want in names else None
    for usual in USUAL[key]:
        if _norm(usual) in names:
            return names.index(_norm(usual))
    return None


def read(device, data):
    """``(shape, [(row_no, sample, code, value, unit, flag)])`` from a file's
    bytes — nothing written."""
    if not data:
        raise ImportError_("empty")
    if len(data) > MAX_BYTES:
        raise ImportError_("too_big")
    header, body = _rows(_decode(data))
    i_sample = _find(header, device.col_sample, "sample")
    if i_sample is None:
        raise ImportError_("no_sample_column")
    i_code = _find(header, device.col_code, "code")
    i_value = _find(header, device.col_value, "value")
    i_unit = _find(header, device.col_unit, "unit")
    i_flag = _find(header, device.col_flag, "flag")

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    out = []
    if i_code is not None and i_value is not None:
        for n, row in enumerate(body, start=2):
            out.append((n, cell(row, i_sample), cell(row, i_code), cell(row, i_value),
                        cell(row, i_unit), cell(row, i_flag)))
        return "long", out
    # A row per tube: every other column is a test code.
    skip = {i for i in (i_sample, i_unit, i_flag) if i is not None}
    for n, row in enumerate(body, start=2):
        for i, head in enumerate(header):
            if i in skip or not head.strip():
                continue
            out.append((n, cell(row, i_sample), head.strip(), cell(row, i), "", ""))
    return "wide", out


def _order_for(sample):
    from app.models import VisitInvestigation

    if not sample:
        return None
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.sample_code == sample,
                    VisitInvestigation.kind == "lab")
            .order_by(VisitInvestigation.id.desc()).all())
    rows = [r for r in rows if r.status != "cancelled"]
    return rows[0] if len(rows) == 1 else None


def _apply(line, order, analyte_id, user, force=False):
    """Write one value onto its order through the bench's own save. Returns
    the line's new state."""
    from app.utils import lab_results

    if order.verified_at is not None:
        return "already"
    current = next((v for v in (order.analyte_values or []) if v.analyte_id == analyte_id), None)
    if current is not None and current.has_value and not force:
        number, words = lab_results.parse(line.raw_value)
        if (number, words) != (current.value, current.text or None):
            return "already"
    lab_results.save(order, {analyte_id: line.raw_value}, user=user)
    return "applied"


def _place(line, device_codes, user, force=False):
    """Decide one line: written, or held with its reason."""
    from app.utils import lab_results

    if not (line.raw_value or "").strip():
        return "empty"
    order = _order_for(line.sample_code)
    if order is None:
        return "no_sample"
    line.order_id = order.id
    analyte_id = device_codes.get((line.code or "").strip().lower())
    if analyte_id is None:
        return "no_code"
    line.analyte_id = analyte_id
    on_test = {row["analyte"].id for row in lab_results.sheet(order)}
    if analyte_id not in on_test:
        return "not_on_test"
    return _apply(line, order, analyte_id, user, force=force)


def _codes(device):
    return {c.code.strip().lower(): c.analyte_id for c in device.codes}


def run(device, data, filename=None, user=None, now=None):
    """Read a file and write what can be written. Returns the run. The caller
    commits."""
    if device is None or not device.is_active:
        raise ImportError_("no_device")
    shape, rows = read(device, data)
    run_row = LabImportRun(device_id=device.id, filename=(filename or "")[:200] or None,
                           at=now or datetime.utcnow(), by_id=getattr(user, "id", None),
                           shape=shape)
    db.session.add(run_row)
    db.session.flush()
    codes = _codes(device)
    for n, sample, code, value, unit, flag in rows:
        line = LabImportLine(run_id=run_row.id, row_no=n, sample_code=sample[:40] or None,
                             code=code[:40] or None, raw_value=value[:120] or None,
                             unit=unit[:30] or None, flag=flag[:30] or None, state="empty")
        db.session.add(line)
        line.state = _place(line, codes, user)
    db.session.flush()
    return run_row


def retry(run_row, user=None):
    """Try again the lines still held — after a code was linked, a tube
    labelled. Returns how many were written."""
    codes = _codes(run_row.device)
    written = 0
    for line in run_row.lines:
        if line.state in REVIEW_STATES and line.state != "already":
            line.state = _place(line, codes, user)
            written += line.state == "applied"
    db.session.flush()
    return written


def write_anyway(line, user=None):
    """A person writes a held «already» line over the value on the order —
    never over a released result."""
    if line.state != "already":
        return line
    codes = _codes(line.run.device)
    line.state = _place(line, codes, user, force=True)
    if line.state == "applied":
        line.resolved_at, line.resolved_by = datetime.utcnow(), getattr(user, "id", None)
    db.session.flush()
    return line


def dismiss(line, user=None, note=None):
    line.state = "dismissed"
    line.resolved_at = datetime.utcnow()
    line.resolved_by = getattr(user, "id", None)
    line.note = (note or "").strip()[:160] or None
    return line


def link_code(device, code, analyte_id):
    """Link the analyser's code to an analyte here (or move it). The caller
    commits."""
    code = (code or "").strip()[:40]
    if not code or not analyte_id:
        raise ImportError_("link")
    row = next((c for c in device.codes if c.code.strip().lower() == code.lower()), None)
    if row is None:
        row = LabDeviceCode(device_id=device.id, code=code, analyte_id=int(analyte_id))
        db.session.add(row)
        device.codes.append(row)
    else:
        row.analyte_id = int(analyte_id)
    db.session.flush()
    return row


def held_count():
    """Lines waiting for a person, across every run — for the lab's bar."""
    return (db.session.query(db.func.count(LabImportLine.id))
            .filter(LabImportLine.state.in_(REVIEW_STATES)).scalar() or 0)


def save_device(form, device=None):
    """Create or edit a device from a form. The caller commits."""
    name = (form.get("name") or "").strip()[:120]
    if not name:
        raise ImportError_("name")
    device = device or LabDevice(name=name)
    device.name = name
    device.model = (form.get("model") or "").strip()[:120] or None
    for col in ("col_sample", "col_code", "col_value", "col_unit", "col_flag"):
        setattr(device, col, (form.get(col) or "").strip()[:60] or None)
    if device.id is None:
        db.session.add(device)
    db.session.flush()
    return device
