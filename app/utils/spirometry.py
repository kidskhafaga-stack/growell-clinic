"""Spirometry report helpers: draw the classic curves and give a pattern read
from the summary values a clinician enters — so the app produces a device-style
report locally, without the vendor software.

Scope note: the curves are *schematic* — reconstructed from the summary values
(FVC, FEV1, PEF), not from raw flow samples (those need the device's own
signal). The pattern is taken from the FEV1/FVC ratio, which needs no predicted
values; % predicted / GLI reference equations are a separate, later step.
"""
from __future__ import annotations

import math

# Which study field maps to which spirometry parameter (name-matched, loose).
_ALIASES = {
    "fev1": ["fev1", "fev 1", "الحجم الزفيري", "fev₁"],
    "fvc": ["fvc", "السعة الحيوية", "forced vital"],
    "ratio": ["fev1/fvc", "fev1 / fvc", "fev1fvc", "النسبة", "ratio"],
    "pef": ["pef", "peak", "التدفق الأقصى"],
    "fef2575": ["fef25-75", "fef2575", "fef 25-75", "fef25", "mmef"],
}


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def extract_params(study):
    """Pull {fev1, fvc, ratio, pef, fef2575} (floats or None) from a study's
    values by loosely matching each measurement's name."""
    out = {k: None for k in _ALIASES}
    for val in study.values:
        name = (val.name or "").strip().lower()
        for key, aliases in _ALIASES.items():
            if out[key] is None and any(a in name for a in aliases):
                out[key] = _num(val.value)
    # Derive the ratio if it wasn't entered directly.
    if out["ratio"] is None and out["fev1"] and out["fvc"]:
        out["ratio"] = round(out["fev1"] / out["fvc"] * 100.0, 1)
    # Normalise a ratio given as a fraction (0.78) to a percent (78).
    if out["ratio"] is not None and out["ratio"] <= 1.5:
        out["ratio"] = round(out["ratio"] * 100.0, 1)
    return out


def interpret(params):
    """A cautious pattern read from the ratio alone (no predicted needed).

    Returns {"pattern": key, "note": key} i18n suffixes, or None when there
    isn't enough to say anything."""
    ratio = params.get("ratio")
    fev1, fvc = params.get("fev1"), params.get("fvc")
    if ratio is None and not (fev1 and fvc):
        return None
    if ratio is None:
        ratio = fev1 / fvc * 100.0
    # A low FEV1/FVC ratio is the hallmark of an obstructive pattern. In
    # children the lower limit sits higher than the adult 70%, so flag < 80% as
    # obstructive and 80–85% as borderline; a normal ratio can't rule out a
    # restrictive pattern without predicted values.
    if ratio < 80:
        return {"pattern": "obstructive", "note": "severity_needs_pred"}
    if ratio < 85:
        return {"pattern": "borderline", "note": "restrict_needs_pred"}
    return {"pattern": "normal_ratio", "note": "restrict_needs_pred"}


# --------------------------------------------------------------- curves -----
def _poly(points, w, h, x_max, y_max, pad, flip_y=True):
    """Map data points to an SVG polyline 'points' string inside w×h with pad."""
    if not points or x_max <= 0 or y_max <= 0:
        return ""
    iw, ih = w - 2 * pad, h - 2 * pad
    out = []
    for x, y in points:
        px = pad + (x / x_max) * iw
        py = (pad + ih - (y / y_max) * ih) if flip_y else (pad + (y / y_max) * ih)
        out.append(f"{px:.1f},{py:.1f}")
    return " ".join(out)


def _axes(w, h, pad):
    return (f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" '
            f'stroke="#c9d2dc" stroke-width="1"/>'
            f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h-pad}" '
            f'stroke="#c9d2dc" stroke-width="1"/>')


def flow_volume_svg(params, w=340, h=240, pad=30):
    """Schematic expiratory flow–volume loop from FVC + PEF (+ inspiratory
    limb sketched below the axis)."""
    fvc, pef = params.get("fvc"), params.get("pef")
    if not (fvc and pef):
        return None
    v_peak = 0.12 * fvc
    exp_pts = [(0, 0), (v_peak, pef)]
    # Concave decline from PEF to zero at FVC (a few points for the curve).
    for i in range(1, 7):
        v = v_peak + (fvc - v_peak) * i / 6.0
        frac = (fvc - v) / (fvc - v_peak)
        exp_pts.append((v, pef * frac ** 1.15))
    y_max = pef * 1.15
    body = _axes(w, h, pad)
    body += (f'<polyline fill="none" stroke="#198754" stroke-width="2" '
             f'points="{_poly(exp_pts, w, h, fvc, y_max, pad)}"/>')
    # Axis labels.
    body += (f'<text x="{w-pad}" y="{h-pad+16}" font-size="10" fill="#5b6673" '
             f'text-anchor="end">Volume (L) · FVC {fvc:g}</text>')
    body += (f'<text x="{pad-6}" y="{pad+4}" font-size="10" fill="#5b6673" '
             f'text-anchor="end">Flow · PEF {pef:g}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="width:100%;max-width:{w}px;height:auto;">{body}</svg>')


def volume_time_svg(params, w=340, h=240, pad=30, t_max=6.0):
    """Schematic volume–time curve: rises to FVC, with FEV1 marked at 1 s."""
    fvc, fev1 = params.get("fvc"), params.get("fev1")
    if not fvc:
        return None
    if fev1 and 0 < fev1 < fvc:
        tau = -1.0 / math.log(1 - fev1 / fvc)
    else:
        tau = 0.5
    pts = []
    n = 60
    for i in range(n + 1):
        t = t_max * i / n
        pts.append((t, fvc * (1 - math.exp(-t / tau))))
    body = _axes(w, h, pad)
    body += (f'<polyline fill="none" stroke="#198754" stroke-width="2" '
             f'points="{_poly(pts, w, h, t_max, fvc, pad)}"/>')
    # Mark FEV1 at t = 1 s.
    if fev1:
        iw, ih = w - 2 * pad, h - 2 * pad
        x1 = pad + (1.0 / t_max) * iw
        y1 = pad + ih - (fev1 / fvc) * ih
        body += (f'<line x1="{x1:.1f}" y1="{h-pad}" x2="{x1:.1f}" y2="{y1:.1f}" '
                 f'stroke="#c0392b" stroke-dasharray="3 3" stroke-width="1"/>')
        body += (f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3" fill="#c0392b"/>')
        body += (f'<text x="{x1+4:.1f}" y="{y1-4:.1f}" font-size="10" '
                 f'fill="#c0392b">FEV1 {fev1:g}</text>')
    body += (f'<text x="{w-pad}" y="{h-pad+16}" font-size="10" fill="#5b6673" '
             f'text-anchor="end">Time (s)</text>')
    body += (f'<text x="{pad-6}" y="{pad+4}" font-size="10" fill="#5b6673" '
             f'text-anchor="end">Vol (L) · FVC {fvc:g}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="width:100%;max-width:{w}px;height:auto;">{body}</svg>')


def analyse(study):
    """Full spirometry read for a study, or None if it isn't a spirometry
    device / lacks the needed values."""
    dev = getattr(study, "device", None)
    if dev is None or dev.device_type != "spirometry":
        return None
    params = extract_params(study)
    if not (params.get("fvc") and params.get("fev1")):
        return None
    return {
        "params": params,
        "interpretation": interpret(params),
        "flow_volume": flow_volume_svg(params),
        "volume_time": volume_time_svg(params),
    }
