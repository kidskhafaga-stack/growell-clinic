"""RCPCH UK growth reference — fully OFFLINE wrapper.

The UK growth charts (UK-WHO 0–4y chained with UK90 2–20y) are published by the
RCPCH. Their numeric reference is shipped inside the official ``rcpchgrowth``
Python package (pip), so every Z-score / centile is computed locally on the
clinic server — no external API, no data leaving the building.

This module adapts ``rcpchgrowth`` to the shapes the rest of our growth engine
already speaks (the WHO/CDC LMS layer in :mod:`app.utils.growth`):

* indicator keys ``wfa | hfa | hcfa | bmifa`` -> rcpch measurement methods
* ``compute_point`` -> ``{age_months, value, z, percentile}``
* ``reference_curves`` -> ``{months, P0.4, P2, ... P99.6}`` for charting

RCPCH plots NINE centiles spaced two-thirds of a standard deviation apart
(0.4th · 2nd · 9th · 25th · 50th · 75th · 91st · 98th · 99.6th), which is the
clinically expected look for UK charts and differs from the WHO/CDC 3–97 set.
"""
from __future__ import annotations

try:  # The package is optional; degrade gracefully if it isn't installed.
    import rcpchgrowth as _r

    RCPCH_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import problem disables the source
    _r = None
    RCPCH_AVAILABLE = False

# Our chart indicator keys -> rcpchgrowth measurement-method strings.
_METHOD = {
    "wfa": "weight",
    "hfa": "height",
    "hcfa": "ofc",
    "bmifa": "bmi",
}

# One exposed source, backed by the chained UK-WHO/UK90 reference (2wk–20y).
RCPCH_SOURCES = {
    "RCPCH": {
        "reference": "uk-who",
        "label": {"en": "RCPCH (UK-WHO / UK90)", "ar": "RCPCH (المملكة المتحدة)"},
        "min_month": 0.5,
        "max_month": 240.0,
    },
}

# RCPCH nine centiles and their Z-scores (two-thirds-SD spacing).
RCPCH_CENTILES = [
    ("P0.4", -2.67), ("P2", -2.0), ("P9", -1.33), ("P25", -0.67),
    ("P50", 0.0), ("P75", 0.67), ("P91", 1.33), ("P98", 2.0), ("P99.6", 2.67),
]

_MONTHS_PER_YEAR = 12.0
_EPS = 0.02  # nudge off the exact reference edge (interpolation is open there)


def is_rcpch(source):
    return source in RCPCH_SOURCES


def sources():
    """RCPCH source descriptors (empty when the package is unavailable)."""
    if not RCPCH_AVAILABLE:
        return []
    return [
        {"key": k, "label": v["label"],
         "min_month": v["min_month"], "max_month": v["max_month"]}
        for k, v in RCPCH_SOURCES.items()
    ]


def reference_range(source):
    node = RCPCH_SOURCES.get(source)
    return (node["min_month"], node["max_month"]) if node else None


def _method(indicator):
    return _METHOD.get(indicator)


def _sex(gender):
    return "female" if gender == "female" else "male"


def _clamp_age_years(age_months, source):
    rng = reference_range(source)
    lo, hi = (rng[0] + _EPS), (rng[1] - _EPS)
    months = min(max(age_months, lo), hi)
    return months / _MONTHS_PER_YEAR


def sds_and_centile(source, indicator, gender, age_months, value):
    """(z, percentile) for one measurement, or ``(None, None)`` if off-scale."""
    if not RCPCH_AVAILABLE or not is_rcpch(source):
        return (None, None)
    method = _method(indicator)
    if not method or value is None or value <= 0:
        return (None, None)
    lo, hi = reference_range(source)
    if age_months < lo - 0.5 or age_months > hi + 0.5:  # genuinely off-scale
        return (None, None)
    z = _safe_sds(
        RCPCH_SOURCES[source]["reference"], _clamp_age_years(age_months, source),
        method, float(value), _sex(gender),
    )
    if z is None:
        return (None, None)
    pct = float(_r.centile(z))
    return (round(float(z), 2), max(0.1, min(99.9, round(pct, 1))))


def _safe_sds(reference, age_years, method, value, sex):
    """Z-score with a tiny age nudge to dodge the open 2.0y crossover edge."""
    for age in (age_years, age_years + 0.005, age_years - 0.005,
                age_years + 0.02, age_years - 0.02):
        try:
            z = _r.sds_for_measurement(
                reference=reference, age=age, measurement_method=method,
                observation_value=value, sex=sex,
            )
            if z is not None:
                return z
        except Exception:  # noqa: BLE001 - out of range / boundary
            continue
    return None


def _safe_measurement(reference, z, method, sex, age_years):
    """Inverse (value at a centile) with the same boundary nudging."""
    for age in (age_years, age_years + 0.005, age_years - 0.005,
                age_years + 0.02, age_years - 0.02):
        try:
            v = _r.measurement_from_sds(
                reference=reference, requested_sds=z, measurement_method=method,
                sex=sex, age=age,
            )
            if v is not None:
                return float(v)
        except Exception:  # noqa: BLE001
            continue
    return None


def compute_point(source, indicator, gender, age_months, value):
    """Match :func:`app.utils.growth.compute_point` output shape."""
    if age_months is None or value is None:
        return None
    z, pct = sds_and_centile(source, indicator, gender, age_months, value)
    if z is None:
        return None
    return {
        "age_months": round(age_months, 2),
        "value": round(value, 2),
        "z": z,
        "percentile": pct,
    }


def reference_curves(source, indicator, gender):
    """Nine RCPCH centile curves over the reference age span, for charting."""
    if not RCPCH_AVAILABLE or not is_rcpch(source):
        return None
    method = _method(indicator)
    if not method:
        return None
    ref = RCPCH_SOURCES[source]["reference"]
    lo, hi = reference_range(source)
    sex = _sex(gender)

    out = {"months": [], **{name: [] for name, _ in RCPCH_CENTILES}}
    for month in _age_grid(lo, hi):
        age_years = month / _MONTHS_PER_YEAR
        row = {}
        ok = True
        for name, z in RCPCH_CENTILES:
            v = _safe_measurement(ref, z, method, sex, age_years)
            if v is None:
                ok = False
                break
            row[name] = round(v, 2)
        if not ok:
            continue
        out["months"].append(round(month, 2))
        for name, _z in RCPCH_CENTILES:
            out[name].append(row[name])
    return out if out["months"] else None


def _age_grid(lo_month, hi_month):
    """Monthly to 24m, then every 3 months — dense where growth is fastest."""
    month = max(lo_month + _EPS, 0.5)
    points = []
    while month <= 24:
        points.append(month)
        month += 1
    month = 27
    while month <= hi_month - _EPS:
        points.append(month)
        month += 3
    return points
