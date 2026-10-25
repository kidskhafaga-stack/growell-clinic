"""The report builder — the report on your own terms (REPORTS_PLAN.md ت-٢).

Pick a **source** (visits, diagnoses, medicines, bookings, bills, billed
services), a **period**, what to **count or add up**, and how to **split** it
(by month, by doctor, by payer, by age…). Then, if wanted, **compare**: this
period against the one before or the same dates a year earlier, or one
doctor/payer/age group against another side by side. Or ask for the
**descriptive statistics** of a number (count, mean, median, standard
deviation, lowest, highest).

What holds it together:

* **Aggregates only.** No source has the child as a split, and no list of
  names comes out of here — the medical board's drill-down is where names
  are, behind its own permission.
* **The program's own definitions.** A bill's value is what the bills screen
  says it is: what the family pays plus what the payer covers (the cover is
  stored as a discount, so it is added back), bills refunded in full left
  out. A diagnosis is counted once per visit and code, as the medical board
  counts it. Two screens may not disagree about one number.
* **Each source says who may use it** — money needs the finance rights the
  management board needs — and a saved report is run with the permissions of
  whoever opens it.
* **Numbers, not verdicts.** A change is shown as a change.

Everything is read for the period in a handful of queries and grouped here;
a clinic's year is a few tens of thousands of rows.
"""
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from app.extensions import db
from app.utils import money

#: Rows shown before the rest are folded into «the rest».
MAX_ROWS = 60
#: Columns a side-by-side split shows before folding the rest.
MAX_SPLIT = 6
TIME_DIMS = ("day", "month", "quarter", "year", "weekday")
#: The week as an Egyptian calendar hangs it: Saturday first.
WEEK_ORDER = (5, 6, 0, 1, 2, 3, 4)
AGGS = ("sum", "avg", "median", "sd", "min", "max", "stats")
COMPARE = ("prev", "year", "custom")


def _t(key, **kw):
    from app.i18n import t

    return t(key, **kw)


# ------------------------------------------------------------ helpers -----
def _norm(text):
    """Lower case, and Arabic letters that are written more than one way read
    as one — the same forgiveness as the reports search."""
    s = (text or "").strip().casefold()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ـ", "")):
        s = s.replace(a, b)
    return "".join(ch for ch in s if not ("ً" <= ch <= "ْ"))


def _age_group(dob, on):
    from app.utils.med_board import age_groups

    if dob is None or on is None:
        return "over"
    days = (on - dob).days
    for key, upper in age_groups():
        if upper is None or days <= upper:
            return key
    return "over"


def _months(dob, on):
    if dob is None or on is None or on < dob:
        return None
    return round((on - dob).days / 30.4375, 1)


def _parse(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:            # 29 February
        return d.replace(year=d.year - 1, day=28)


# ------------------------------------------------------------ sources -----
def _may_reports(u):
    return u.can_open("reports")


def _may_money(u):
    return u.can_open("reports") and u.can("finance_manage")


class Source:
    def __init__(self, key, icon, dims, measures, default_by, default_m, load, check,
                 filters=(), text_dim=None, money=False):
        self.key, self.icon = key, icon
        self.dims = dims                  # ordered keys
        self.measures = measures          # {key: (kind, field, fmt)}
        self.default_by, self.default_m = default_by, default_m
        self.load, self.check = load, check
        self.filters = filters
        self.text_dim = text_dim
        self.money = money


def _visits(d_from, d_to, ctx):
    from app.models import Appointment, Patient, Visit

    q = (db.session.query(Visit.visit_date, Visit.doctor_id, Visit.patient_id,
                          Patient.date_of_birth, Patient.gender, Appointment.appt_type)
         .join(Patient, Patient.id == Visit.patient_id)
         .outerjoin(Appointment, Appointment.id == Visit.appointment_id)
         .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to))
    return [{"d": vd, "child": pid, "doctor": doc, "gender": g or "", "age": _age_group(dob, vd),
             "age_m": _months(dob, vd), "appt_type": at or "none"}
            for vd, doc, pid, dob, g, at in q.all()]


def _diagnoses(d_from, d_to, ctx):
    from app.models import Diagnosis, Patient, Visit

    en = ctx["lang"] == "en"
    q = (db.session.query(Diagnosis.visit_id, Diagnosis.code, Diagnosis.icd_version,
                          Diagnosis.title, Diagnosis.title_en, Visit.visit_date, Visit.doctor_id,
                          Visit.patient_id, Patient.date_of_birth, Patient.gender)
         .join(Visit, Visit.id == Diagnosis.visit_id)
         .join(Patient, Patient.id == Visit.patient_id)
         .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to))
    seen, out = set(), []
    names = ctx.setdefault("names", {}).setdefault("diagnosis", {})
    for vid, code, ver, title, title_en, vd, doc, pid, dob, g in q.all():
        code = (code or "").strip()
        key = f"c:{ver or '10'}:{code}" if code else "t:" + _norm(title)
        if (vid, key) in seen:
            continue
        seen.add((vid, key))
        shown = (title_en if en and title_en else title) or ""
        names.setdefault(key, f"{code} — {shown}" if code else shown)
        out.append({"d": vd, "child": pid, "visit": vid, "doctor": doc, "gender": g or "",
                    "age": _age_group(dob, vd), "age_m": _months(dob, vd), "diagnosis": key})
    return out


def _drugs(d_from, d_to, ctx):
    from app.models import Drug, Patient, Prescription, PrescriptionItem

    q = (db.session.query(PrescriptionItem.prescription_id, PrescriptionItem.drug_name,
                          Drug.drug_class, Prescription.rx_date, Prescription.doctor_id,
                          Prescription.patient_id, Patient.date_of_birth, Patient.gender)
         .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
         .join(Patient, Patient.id == Prescription.patient_id)
         .outerjoin(Drug, Drug.id == PrescriptionItem.drug_id)
         .filter(Prescription.rx_date >= d_from, Prescription.rx_date <= d_to))
    names = ctx.setdefault("names", {})
    drug_names, classes = names.setdefault("drug", {}), names.setdefault("drug_class", {})
    out = []
    for rx_id, drug, klass, rd, doc, pid, dob, g in q.all():
        key = _norm(drug)
        drug_names.setdefault(key, (drug or "").strip())
        ckey = _norm(klass) if klass else "none"
        if klass:
            classes.setdefault(ckey, klass.strip())
        out.append({"d": rd, "child": pid, "rx": rx_id, "doctor": doc, "gender": g or "",
                    "age": _age_group(dob, rd), "age_m": _months(dob, rd), "drug": key,
                    "drug_class": ckey})
    return out


def _appointments(d_from, d_to, ctx):
    from app.models import Appointment, Patient

    q = (db.session.query(Appointment.appt_date, Appointment.doctor_id, Appointment.patient_id,
                          Appointment.status, Appointment.appt_type, Patient.date_of_birth,
                          Patient.gender)
         .join(Patient, Patient.id == Appointment.patient_id)
         .filter(Appointment.appt_date >= d_from, Appointment.appt_date <= d_to))
    return [{"d": ad, "child": pid, "doctor": doc, "status": st or "", "appt_type": at or "none",
             "gender": g or "", "age": _age_group(dob, ad)}
            for ad, doc, pid, st, at, dob, g in q.all()]


def _payer_fields(payer_id, ctx):
    payer = ctx["payers"].get(payer_id) if payer_id else None
    cash = payer is None or payer.entity_type == "cash"
    return {"payer": payer_id if payer is not None else 0,
            "payer_kind": "cash" if cash else "contract",
            "payer_type": (payer.entity_type if payer is not None else "cash") or "other"}


def _bills(d_from, d_to, ctx):
    from sqlalchemy.orm import selectinload

    from app.models import Invoice

    q = (Invoice.query.options(selectinload(Invoice.items), selectinload(Invoice.payments),
                               selectinload(Invoice.patient))
         .filter(Invoice.invoice_date >= d_from, Invoice.invoice_date <= d_to,
                 Invoice.status != "refunded"))
    out = []
    for inv in q.all():
        p = inv.patient
        dob = p.date_of_birth if p is not None else None
        family, payer = inv.total, inv.payer_total
        row = {"d": inv.invoice_date, "child": inv.patient_id, "doctor": inv.doctor_id,
               "status": inv.status, "gender": (p.gender if p is not None else "") or "",
               "age": _age_group(dob, inv.invoice_date),
               "billed": round(family + payer, 2), "family": family, "payer_share": payer,
               "paid": inv.paid, "balance": inv.balance}
        row.update(_payer_fields(inv.payer_id, ctx))
        out.append(row)
    return out


def _lines(d_from, d_to, ctx):
    from app.models import Invoice, InvoiceItem, Service

    on = db.func.coalesce(InvoiceItem.service_date, Invoice.invoice_date)
    q = (db.session.query(InvoiceItem.unit_price, InvoiceItem.quantity, InvoiceItem.discount_value,
                          InvoiceItem.discount_is_percent, InvoiceItem.payer_amount,
                          InvoiceItem.doctor_id, InvoiceItem.service_id, InvoiceItem.description,
                          InvoiceItem.service_date, Invoice.invoice_date, Invoice.doctor_id,
                          Invoice.payer_id, Invoice.patient_id, Service.name, Service.name_en,
                          Service.category)
         .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
         .outerjoin(Service, Service.id == InvoiceItem.service_id)
         .filter(on >= d_from, on <= d_to, Invoice.status != "refunded"))
    en = ctx["lang"] == "en"
    names = ctx.setdefault("names", {}).setdefault("service", {})
    out = []
    for (price, qty, dv, pct, payer_amount, line_doc, sid, desc, sdate, idate, inv_doc,
         payer_id, pid, sname, sname_en, cat) in q.all():
        # The line's own arithmetic, exactly as InvoiceItem works it out.
        gross_p = money.times_piastres(money.piastres(price), qty or 1)
        disc_p = (money.percent_piastres(gross_p, dv or 0) if pct
                  else min(money.piastres(dv), gross_p))
        gross, disc = money.pounds(gross_p), money.pounds(disc_p)
        net = money.pounds(gross_p - disc_p)
        if not payer_id:
            cover = 0.0
        elif payer_amount is None:
            cover = disc                       # billed before cover was kept per line
        else:
            cover = round(min(payer_amount or 0, gross), 2)
        key = f"s:{sid}" if sid else "d:" + _norm(desc)
        names.setdefault(key, ((sname_en if en and sname_en else sname) or desc or "").strip())
        row = {"d": sdate or idate, "child": pid, "doctor": line_doc or inv_doc,
               "service": key, "category": cat or "other", "qty": qty or 1,
               "billed": round(net + cover, 2), "family": net, "payer_share": cover}
        row.update(_payer_fields(payer_id, ctx))
        out.append(row)
    return out


_COUNT = ("count", None, "int")
_KIDS = ("distinct", "child", "int")
_AGE = ("num", "age_m", "num")

SOURCES = {
    "visits": Source(
        "visits", "clipboard2-pulse",
        ["month", "quarter", "year", "day", "weekday", "doctor", "appt_type", "gender", "age"],
        {"count": _COUNT, "children": _KIDS, "age_m": _AGE},
        "month", "count", _visits, _may_reports,
        filters=("doctor", "appt_type", "gender", "age")),
    "diagnoses": Source(
        "diagnoses", "heart-pulse",
        ["diagnosis", "month", "quarter", "year", "weekday", "doctor", "gender", "age"],
        {"count": _COUNT, "children": _KIDS, "age_m": _AGE},
        "diagnosis", "count", _diagnoses, _may_reports,
        filters=("doctor", "gender", "age"), text_dim="diagnosis"),
    "drugs": Source(
        "drugs", "capsule",
        ["drug", "drug_class", "month", "quarter", "year", "doctor", "gender", "age"],
        {"count": _COUNT, "rx": ("distinct", "rx", "int"), "children": _KIDS, "age_m": _AGE},
        "drug", "count", _drugs, lambda u: _may_reports(u) and u.can_open("prescriptions"),
        filters=("doctor", "gender", "age"), text_dim="drug"),
    "appointments": Source(
        "appointments", "calendar-check",
        ["month", "quarter", "year", "day", "weekday", "doctor", "status", "appt_type", "gender", "age"],
        {"count": _COUNT, "children": _KIDS},
        "month", "count", _appointments, lambda u: _may_reports(u) and u.can_open("appointments"),
        filters=("doctor", "status", "appt_type", "gender", "age")),
    "bills": Source(
        "bills", "receipt",
        ["month", "quarter", "year", "day", "weekday", "payer_kind", "payer", "payer_type",
         "doctor", "status", "gender", "age"],
        {"billed": ("num", "billed", "money"), "family": ("num", "family", "money"),
         "payer_share": ("num", "payer_share", "money"), "paid": ("num", "paid", "money"),
         "balance": ("num", "balance", "money"), "count": _COUNT, "children": _KIDS},
        "month", "billed", _bills, _may_money,
        filters=("payer_kind", "payer", "payer_type", "doctor", "status", "gender", "age"),
        money=True),
    "lines": Source(
        "lines", "list-check",
        ["service", "category", "month", "quarter", "year", "payer_kind", "payer", "payer_type",
         "doctor"],
        {"billed": ("num", "billed", "money"), "family": ("num", "family", "money"),
         "payer_share": ("num", "payer_share", "money"), "qty": ("num", "qty", "int"),
         "count": _COUNT, "children": _KIDS},
        "service", "billed", _lines, _may_money,
        filters=("payer_kind", "payer", "payer_type", "category", "doctor"),
        text_dim="service", money=True),
}


def available(user):
    """The sources this person may use, in the builder's order."""
    out = []
    for key, src in SOURCES.items():
        try:
            ok = bool(src.check(user))
        except Exception:  # noqa: BLE001 — a broken check hides one source
            ok = False
        if ok:
            out.append(key)
    return out


# --------------------------------------------------------------- spec -----
def spec_from(args, user, today=None):
    """The question the form asks, checked against what this person may use.
    ``None`` when they may use no source at all."""
    from app.utils.med_board import window

    keys = available(user)
    if not keys:
        return None
    src = args.get("src") if args.get("src") in keys else keys[0]
    s = SOURCES[src]
    w = window(args.get("from"), args.get("to"), args.get("preset") or "90", today=today)
    by = args.get("by") if args.get("by") in s.dims else s.default_by
    split = args.get("split") if args.get("split") in s.dims and args.get("split") != by else ""
    m = args.get("m") if args.get("m") in s.measures else s.default_m
    kind = s.measures[m][0]
    agg = args.get("agg") if args.get("agg") in AGGS else "sum"
    if kind != "num":
        agg = "sum"
    vs = args.get("vs") if args.get("vs") in COMPARE else ""
    b_from = b_to = None
    if vs == "prev":
        b_from, b_to = w["prev_from"], w["prev_to"]
    elif vs == "year":
        b_from, b_to = _year_before(w["from"]), _year_before(w["to"])
    elif vs == "custom":
        b_from, b_to = _parse(args.get("from2")), _parse(args.get("to2"))
        if b_from is None or b_to is None:
            b_from, b_to = w["prev_from"], w["prev_to"]
        elif b_from > b_to:
            b_from, b_to = b_to, b_from
    if agg == "stats":
        vs, split = "", ""
    if vs:
        split = ""
    filters = {}
    for dim in s.filters:
        picked = [v for v in args.getlist("f_" + dim) if v != ""] if hasattr(args, "getlist") else []
        if picked:
            filters[dim] = set(picked)
    return {"src": src, "from": w["from"], "to": w["to"], "preset": w["preset"],
            "by": by, "split": split, "m": m, "agg": agg, "vs": vs,
            "b_from": b_from, "b_to": b_to, "filters": filters,
            "q": (args.get("q") or "").strip()[:80], "sources": keys}


def query_args(spec):
    """The spec back as the form's arguments — what a saved report keeps."""
    out = [("src", spec["src"])]
    if spec["preset"]:
        out.append(("preset", spec["preset"]))
    else:
        out += [("from", spec["from"].isoformat()), ("to", spec["to"].isoformat())]
    out += [("by", spec["by"]), ("m", spec["m"])]
    for key in ("split", "vs", "q"):
        if spec[key]:
            out.append((key, spec[key]))
    if spec["agg"] != "sum":
        out.append(("agg", spec["agg"]))
    if spec["vs"] == "custom":
        out += [("from2", spec["b_from"].isoformat()), ("to2", spec["b_to"].isoformat())]
    for dim, vals in sorted(spec["filters"].items()):
        out += [("f_" + dim, v) for v in sorted(vals)]
    return out


# ------------------------------------------------------------ grouping ----
def _key(dim, r):
    d = r["d"]
    if dim == "day":
        return d.isoformat()
    if dim == "month":
        return f"{d.year:04d}-{d.month:02d}"
    if dim == "quarter":
        return f"{d.year:04d}-Q{(d.month - 1) // 3 + 1}"
    if dim == "year":
        return f"{d.year:04d}"
    if dim == "weekday":
        return str(d.weekday())
    v = r.get(dim)
    return "" if v is None else str(v)


def _buckets(dim, d_from, d_to):
    """Every bucket of a time split across the period, empty ones included,
    in order — so a month nobody came still shows as a month."""
    if dim == "weekday":
        return [str(i) for i in WEEK_ORDER]
    out, d = [], d_from
    if dim == "day":
        if (d_to - d_from).days > 400:
            return None
        while d <= d_to:
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    while d <= d_to:
        k = _key(dim, {"d": d})
        if not out or out[-1] != k:
            out.append(k)
        # next month start
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    if dim == "year":
        out = sorted(set(out))
    return out


def _value(rows, measure, agg):
    kind, field, _fmt = measure
    if kind == "count":
        return len(rows)
    if kind == "distinct":
        return len({r.get(field) for r in rows if r.get(field) is not None})
    vals = [r[field] for r in rows if r.get(field) is not None]
    if agg == "sum":
        return round(sum(vals), 2)
    if not vals:
        return None
    if agg == "avg":
        return round(sum(vals) / len(vals), 2)
    if agg == "median":
        return round(statistics.median(vals), 2)
    if agg == "sd":
        return round(statistics.stdev(vals), 2) if len(vals) > 1 else None
    if agg == "min":
        return round(min(vals), 2)
    if agg == "max":
        return round(max(vals), 2)
    return None


def _stats(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    if not vals:
        return [0, None, None, None, None, None]
    sd = round(statistics.stdev(vals), 2) if len(vals) > 1 else None
    return [len(vals), round(sum(vals) / len(vals), 2), round(statistics.median(vals), 2), sd,
            round(min(vals), 2), round(max(vals), 2)]


def _change(a, b):
    if a is None or b is None:
        return None, None
    diff = round(a - b, 2)
    pct = round(diff * 100 / b, 1) if b else None
    return diff, pct


def label(dim, key, ctx):
    """What a bucket is called on the screen."""
    if key == "__rest__":
        return _t("builder.rest")
    if dim in ("day", "month", "year"):
        return key
    if dim == "quarter":
        y, q = key.split("-Q")
        return _t("builder.quarter_of", q=q, y=y)
    if dim == "weekday":
        return _t("weekdays." + key)
    if dim == "doctor":
        u = ctx["doctors"].get(int(key)) if key.isdigit() else None
        return u.display_name(ctx["lang"]) if u is not None else _t("builder.none")
    if dim == "payer":
        if key in ("", "0"):
            return _t("builder.cash")
        p = ctx["payers"].get(int(key)) if key.isdigit() else None
        if p is None:
            return key
        return (p.name_en if ctx["lang"] == "en" and p.name_en else p.name)
    if dim == "payer_kind":
        return _t("builder.kind_" + (key or "cash"))
    if dim == "payer_type":
        pt = ctx["payer_types"].get(key)
        if pt is not None:
            return (pt.name_en if ctx["lang"] == "en" and pt.name_en else pt.name_ar) or key
        return _t("builder.cash") if key == "cash" else key
    if dim == "gender":
        return _t("genders." + key) if key in ("male", "female") else _t("builder.none")
    if dim == "age":
        return _t("agegrp." + key)
    if dim == "appt_type":
        return _t("builder.no_appt") if key == "none" else _t("appt_types." + key)
    if dim == "status":
        return _t("statuses." + key) if key in ctx["appt_statuses"] else _t("builder.bst_" + key)
    if dim == "category":
        return _t("service_categories." + key)
    if dim == "drug_class" and key == "none":
        return _t("builder.no_class")
    return ctx.get("names", {}).get(dim, {}).get(key, key)


def _ctx(lang):
    from app.models import PayerEntity, PayerType, User
    from app.models.appointment import APPOINTMENT_STATUSES

    return {"lang": lang,
            "doctors": {u.id: u for u in User.query.all()},
            "payers": {p.id: p for p in PayerEntity.query.all()},
            "payer_types": {pt.key: pt for pt in PayerType.query.all()},
            "appt_statuses": set(APPOINTMENT_STATUSES)}


def _filter(rows, spec, src, ctx):
    out = rows
    for dim, keep in spec["filters"].items():
        out = [r for r in out if _key(dim, r) in keep]
    if spec["q"] and src.text_dim:
        words = _norm(spec["q"]).split()
        names = ctx.get("names", {}).get(src.text_dim, {})
        out = [r for r in out
               if all(w in _norm(names.get(r[src.text_dim], r[src.text_dim])) for w in words)]
    return out


def _group(rows, dim):
    g = defaultdict(list)
    for r in rows:
        g[_key(dim, r)].append(r)
    return g


def _order(dim, groups, measure, agg, d_from, d_to):
    """The rows' order: time in time, everything else biggest first, with
    what is past :data:`MAX_ROWS` folded into one row."""
    if dim in TIME_DIMS:
        keys = _buckets(dim, d_from, d_to)
        if keys is None:
            keys = sorted(groups)
        return keys, []
    keys = sorted(groups, key=lambda k: (-(_value(groups[k], measure, agg) or 0), k))
    if len(keys) > MAX_ROWS:
        return keys[:MAX_ROWS - 1], keys[MAX_ROWS - 1:]
    return keys, []


# ---------------------------------------------------------------- run -----
def run(spec, lang="ar"):
    """The table (and the chart's series) for a checked spec."""
    src = SOURCES[spec["src"]]
    ctx = _ctx(lang)
    measure = src.measures[spec["m"]]
    agg, by = spec["agg"], spec["by"]
    raw = src.load(spec["from"], spec["to"], ctx)
    options = _options(raw, src, ctx)
    rows = _filter(raw, spec, src, ctx)
    groups = _group(rows, by)
    keys, rest = _order(by, groups, measure, agg, spec["from"], spec["to"])
    fmt = "num" if agg in ("avg", "median", "sd") and measure[2] == "int" else measure[2]

    def row_for(k):
        return groups.get(k, [])

    def rest_rows():
        return [r for k in rest for r in groups[k]]

    table = {"rows": [], "fmt": fmt, "mode": "plain", "time": by in TIME_DIMS}
    if agg == "stats":
        table["mode"] = "stats"
        table["cols"] = [_t("builder.st_n"), _t("builder.st_mean"), _t("builder.st_median"),
                         _t("builder.st_sd"), _t("builder.st_min"), _t("builder.st_max")]
        for k in keys:
            table["rows"].append({"label": label(by, k, ctx), "cells": _stats(row_for(k), measure[1])})
        if rest:
            table["rows"].append({"label": label(by, "__rest__", ctx),
                                  "cells": _stats(rest_rows(), measure[1])})
        table["total"] = _stats(rows, measure[1])
        table["col_fmt"] = ["int"] + [measure[2] if measure[2] == "money" else "num"] * 5
    elif spec["vs"]:
        table["mode"] = "vs"
        b_raw = src.load(spec["b_from"], spec["b_to"], ctx)
        b_rows = _filter(b_raw, spec, src, ctx)
        b_groups = _group(b_rows, by)
        a_lbl = f"{spec['from'].isoformat()} → {spec['to'].isoformat()}"
        b_lbl = f"{spec['b_from'].isoformat()} → {spec['b_to'].isoformat()}"
        table["cols"] = [a_lbl, b_lbl, _t("builder.diff"), _t("builder.pct")]
        if by in TIME_DIMS and by != "weekday":
            # Periods side by side line up by place: the first month of each,
            # the second of each… — «أول ٦ شهور ٢٠٢٦ قصاد ٢٠٢٥».
            b_keys = _buckets(by, spec["b_from"], spec["b_to"]) or sorted(b_groups)
            for i in range(max(len(keys), len(b_keys))):
                ka = keys[i] if i < len(keys) else None
                kb = b_keys[i] if i < len(b_keys) else None
                a = _value(groups.get(ka, []), measure, agg) if ka else None
                b = _value(b_groups.get(kb, []), measure, agg) if kb else None
                name = " / ".join(label(by, k, ctx) for k in (ka, kb) if k)
                table["rows"].append({"label": name, "cells": [a, b, *_change(a, b)]})
        else:
            all_keys = keys + [k for k in sorted(b_groups, key=lambda k: -(
                _value(b_groups[k], measure, agg) or 0)) if k not in groups and k not in rest]
            for k in all_keys:
                a = _value(groups.get(k, []), measure, agg)
                b = _value(b_groups.get(k, []), measure, agg)
                table["rows"].append({"label": label(by, k, ctx), "cells": [a, b, *_change(a, b)]})
            if rest:
                a = _value(rest_rows(), measure, agg)
                b = _value([r for k in rest for r in b_groups.get(k, [])], measure, agg)
                table["rows"].append({"label": label(by, "__rest__", ctx),
                                      "cells": [a, b, *_change(a, b)]})
        a, b = _value(rows, measure, agg), _value(b_rows, measure, agg)
        table["total"] = [a, b, *_change(a, b)]
        table["col_fmt"] = [fmt, fmt, fmt, "pct"]
    elif spec["split"]:
        table["mode"] = "split"
        split = spec["split"]
        s_groups = _group(rows, split)
        s_keys, s_rest = _order(split, s_groups, measure, agg, spec["from"], spec["to"])
        if split not in TIME_DIMS and len(s_keys) + len(s_rest) > MAX_SPLIT:
            s_rest = s_keys[MAX_SPLIT - 1:] + s_rest
            s_keys = s_keys[:MAX_SPLIT - 1]
        cols = [label(split, k, ctx) for k in s_keys]
        if s_rest:
            cols.append(label(split, "__rest__", ctx))
        table["cols"] = cols + [_t("builder.total")]
        rest_set = set(s_rest)

        def cells(rs):
            by_split = _group(rs, split)
            out = [_value(by_split.get(k, []), measure, agg) for k in s_keys]
            if s_rest:
                out.append(_value([r for r in rs if _key(split, r) in rest_set], measure, agg))
            return out + [_value(rs, measure, agg)]

        for k in keys:
            table["rows"].append({"label": label(by, k, ctx), "cells": cells(row_for(k))})
        if rest:
            table["rows"].append({"label": label(by, "__rest__", ctx), "cells": cells(rest_rows())})
        table["total"] = cells(rows)
        table["col_fmt"] = [fmt] * len(table["cols"])
    else:
        total = _value(rows, measure, agg)
        share = measure[0] in ("count",) or (measure[0] == "num" and agg == "sum")
        table["cols"] = [_t("builder.m_" + spec["m"])] + ([_t("builder.share")] if share else [])

        def cells(rs):
            v = _value(rs, measure, agg)
            if not share:
                return [v]
            return [v, round(v * 100 / total, 1) if total and v is not None else None]

        for k in keys:
            table["rows"].append({"label": label(by, k, ctx), "cells": cells(row_for(k))})
        if rest:
            table["rows"].append({"label": label(by, "__rest__", ctx), "cells": cells(rest_rows())})
        table["total"] = cells(rows)
        table["col_fmt"] = [fmt] + (["pct"] if share else [])
    table["n"] = len(rows)
    mx = []
    for i in range(len(table["cols"])):
        vals = [abs(r["cells"][i]) for r in table["rows"]
                if isinstance(r["cells"][i], (int, float))]
        mx.append(max(vals) if vals else 0)
    table["max"] = mx
    table["bar"] = [table["mode"] != "stats" and table["col_fmt"][i] != "pct"
                    and not (table["mode"] == "vs" and i == 2) for i in range(len(table["cols"]))]
    table["chart"] = _chart(table) if table["time"] and table["mode"] != "stats" else None
    table["options"] = options
    return table


def _options(raw, src, ctx):
    """What each filter can be set to, from what the period has."""
    out = {}
    for dim in src.filters:
        keys = sorted({_key(dim, r) for r in raw})
        named = [(k, label(dim, k, ctx)) for k in keys]
        named.sort(key=lambda kv: kv[1])
        out[dim] = named
    return out


def _chart(table, width=720, height=220, pad=34):
    """A line per column over time — the columns that are values, not the
    difference or the share."""
    mode = table["mode"]
    if mode == "vs":
        series = [0, 1]
    elif mode == "split":
        series = list(range(len(table["cols"]) - 1))[:MAX_SPLIT]
    else:
        series = [0]
    rows = table["rows"]
    if len(rows) < 2:
        return None
    vals = [r["cells"][i] or 0 for r in rows for i in series]
    top = max(vals + [0]) or 1
    step = (width - 2 * pad) / (len(rows) - 1)

    def y(v):
        return round(height - pad - (v or 0) * (height - 2 * pad) / top, 1)

    lines = []
    for n, i in enumerate(series):
        pts = " ".join(f"{round(pad + j * step, 1)},{y(r['cells'][i])}" for j, r in enumerate(rows))
        lines.append({"n": n, "label": table["cols"][i], "points": pts,
                      "last": (round(pad + (len(rows) - 1) * step, 1), y(rows[-1]["cells"][i]))})
    every = max(1, len(rows) // 8)
    ticks = [(round(pad + j * step, 1), r["label"]) for j, r in enumerate(rows) if j % every == 0]
    return {"w": width, "h": height, "pad": pad, "lines": lines, "ticks": ticks,
            "top": top, "y_top": y(top), "y_mid": y(top / 2), "base": height - pad}


def export_rows(spec, table, lang="ar"):
    """Header and rows as plain values, for CSV and Excel."""
    head = [_t("builder.d_" + spec["by"])] + list(table["cols"])
    body = [[r["label"], *[("" if c is None else c) for c in r["cells"]]] for r in table["rows"]]
    body.append([_t("builder.total"), *[("" if c is None else c) for c in table["total"]]])
    return head, body
