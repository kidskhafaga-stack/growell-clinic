"""Growth standards engine: LMS-based percentile and Z-score computation.

Reference data (WHO Child Growth Standards 0–5y and CDC 2–20y) is bundled in
``app/data/growth/standards.json`` as LMS triples and loaded once. The LMS
method (Cole) converts a measurement to a Z-score:

    Z = ((value/M)**L - 1) / (L*S)     for L != 0
    Z = ln(value/M) / S                for L == 0

and the inverse (for drawing reference percentile curves):

    value = M * (1 + L*S*Z)**(1/L)     for L != 0
    value = M * exp(S*Z)               for L == 0
"""
import json
import math
import os
from datetime import date

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "growth", "standards.json")
_data = None

# Indicator metadata: which growth measurement feeds each chart.
INDICATORS = {
    "wfa": {"field": "weight_kg", "unit": "kg"},
    "hfa": {"field": "height_cm", "unit": "cm"},
    "hcfa": {"field": "head_circ_cm", "unit": "cm"},
    "bmifa": {"field": "bmi", "unit": "kg/m²"},
}

# Percentile curves drawn on charts and their corresponding Z-scores.
PERCENTILE_LINES = [
    ("P3", -1.88079), ("P15", -1.03643), ("P50", 0.0),
    ("P85", 1.03643), ("P97", 1.88079),
]


def _load():
    global _data
    if _data is None:
        with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
            _data = json.load(fh)
    return _data


def references():
    """List available references as ``[{key, label{en,ar}, range}]``."""
    refs = _load()["references"]
    return [
        {"key": k, "label": v["label"],
         "min_month": v["min_month"], "max_month": v["max_month"]}
        for k, v in refs.items()
    ]


def reference_range(ref):
    """(min_month, max_month) for a reference, or None."""
    node = _load()["references"].get(ref)
    return (node["min_month"], node["max_month"]) if node else None


def _sex_key(gender):
    return "boys" if gender == "male" else "girls"


def _table(ref, indicator, gender):
    refs = _load()["references"]
    node = refs.get(ref, {}).get("indicators", {}).get(indicator)
    if not node:
        return None
    return node.get(_sex_key(gender))


def age_in_months(dob, on_date):
    """Fractional age in months (uses 30.4375 days/month)."""
    if not dob or not on_date:
        return None
    days = (on_date - dob).days
    return days / 30.4375 if days >= 0 else None


def _lms(table, month):
    """Interpolated (L, M, S) for ``month`` from a sorted LMS table."""
    if not table:
        return None
    if month <= table[0][0]:
        _, l, m, s = table[0]
        return (l, m, s)
    if month >= table[-1][0]:
        _, l, m, s = table[-1]
        return (l, m, s)
    for i in range(1, len(table)):
        m1, l1, mm1, s1 = table[i]
        if month <= m1:
            m0, l0, mm0, s0 = table[i - 1]
            f = (month - m0) / (m1 - m0) if m1 != m0 else 0
            return (l0 + (l1 - l0) * f, mm0 + (mm1 - mm0) * f, s0 + (s1 - s0) * f)
    return None


def zscore(value, l, m, s):
    if not value or value <= 0 or m <= 0 or s == 0:
        return None
    if abs(l) < 1e-7:
        return math.log(value / m) / s
    return ((value / m) ** l - 1) / (l * s)


def value_at_z(l, m, s, z):
    if abs(l) < 1e-7:
        return m * math.exp(s * z)
    base = 1 + l * s * z
    if base <= 0:
        return None
    return m * base ** (1 / l)


def percentile_from_z(z):
    if z is None:
        return None
    p = 50 * (1 + math.erf(z / math.sqrt(2)))
    return max(0.1, min(99.9, round(p, 1)))


def compute_point(ref, indicator, gender, dob, on_date, value):
    """Return {age_months, value, z, percentile} for one measurement."""
    months = age_in_months(dob, on_date)
    if months is None or value is None:
        return None
    table = _table(ref, indicator, gender)
    lms = _lms(table, months)
    if lms is None:
        return None
    z = zscore(value, *lms)
    return {
        "age_months": round(months, 2),
        "value": round(value, 2),
        "z": round(z, 2) if z is not None else None,
        "percentile": percentile_from_z(z),
    }


def compute_at_age(ref, indicator, gender, age_months, value):
    """Like :func:`compute_point` but driven by a known age in months (no DOB).

    Used by the stateless ``/api/calculate`` endpoint."""
    if age_months is None or value is None:
        return None
    lms = _lms(_table(ref, indicator, gender), age_months)
    if lms is None:
        return None
    z = zscore(value, *lms)
    return {
        "age_months": round(age_months, 2),
        "value": round(value, 2),
        "z": round(z, 2) if z is not None else None,
        "percentile": percentile_from_z(z),
    }


def reference_curves(ref, indicator, gender):
    """Percentile curves for charting: {months:[], P3:[], ... P97:[]}."""
    table = _table(ref, indicator, gender)
    if not table:
        return None
    out = {"months": [], **{name: [] for name, _ in PERCENTILE_LINES}}
    for row in table:
        month, l, m, s = row
        out["months"].append(month)
        for name, z in PERCENTILE_LINES:
            out[name].append(round(value_at_z(l, m, s, z), 2))
    return out


def status_for_z(z):
    """Coarse clinical flag for a Z-score: normal / caution / alert."""
    if z is None:
        return "unknown"
    az = abs(z)
    if az <= 2:
        return "normal"
    if az <= 3:
        return "caution"
    return "alert"
