"""The lab result as the family and the referring doctor read it — م-٤.

«عايز منظر التحليل أفضل والشكل يكون تفاعلي أكتر … وإمكانية الطباعة طبعاً
لأن ده حق المريض.» A card per test, each value on a bar showing where it
sits against the reference the laboratory wrote, an arrow when the
laboratory's own flag says low or high, and the child's earlier values of the
same test behind a tap — on the link, in the file, and on paper.

**Nothing here is the program's own reading.** The flag is the one the
laboratory's range gave (`LabResultValue.flag`), or for a single number the
plain comparison with the low and high written on the order; the bar is
drawn from those same two numbers. No word about what a value means.
"""
from app.extensions import db

#: Earlier values shown behind each card, newest last.
HISTORY = 6


def _flag(value, low, high):
    if value is None or (low is None and high is None):
        return None
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "normal"


def _bar(value, low, high):
    """Where the value and the reference band sit on a bar, in percent:
    ``{"band": (start, end), "at": pos}`` — or ``None`` when there is no
    two-sided reference or no number to place."""
    if value is None or low is None or high is None or high <= low:
        return None
    span = high - low
    lo, hi = low - span * 0.6, high + span * 0.6
    lo, hi = min(lo, value - span * 0.1), max(hi, value + span * 0.1)
    width = hi - lo

    def pct(x):
        return round((x - lo) / width * 100, 1)

    return {"band": (pct(low), pct(high)), "at": max(1.0, min(99.0, pct(value)))}


def _spark(points):
    """An SVG polyline for the points, in a 100×28 box, or ``None``."""
    values = [v for _d, v in points if v is not None]
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1.0
    step = 100 / (len(values) - 1)
    return " ".join(f"{round(i * step, 1)},{round(26 - (v - lo) / rng * 24, 1)}"
                    for i, v in enumerate(values))


def _shown(value):
    return "" if value is None else f"{value:g}"


def _simple_history(order):
    from app.models import VisitInvestigation

    if not order.investigation_id:
        return []
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id == order.patient_id,
                    VisitInvestigation.investigation_id == order.investigation_id,
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.result_value.isnot(None),
                    VisitInvestigation.resulted_at <= order.resulted_at,
                    VisitInvestigation.id != order.id)
            .order_by(VisitInvestigation.resulted_at.desc()).limit(HISTORY - 1).all())
    return [(r.resulted_at, r.result_value) for r in reversed(rows)]


def _analyte_history(order, analyte_id):
    from app.models import LabResultValue, VisitInvestigation

    rows = (db.session.query(VisitInvestigation.resulted_at, LabResultValue.value)
            .join(LabResultValue, LabResultValue.order_id == VisitInvestigation.id)
            .filter(VisitInvestigation.patient_id == order.patient_id,
                    VisitInvestigation.status == "resulted",
                    VisitInvestigation.resulted_at <= order.resulted_at,
                    VisitInvestigation.id != order.id,
                    LabResultValue.analyte_id == analyte_id,
                    LabResultValue.value.isnot(None))
            .order_by(VisitInvestigation.resulted_at.desc()).limit(HISTORY - 1).all())
    return list(reversed(rows))


def _line(name, value, text, unit, low, high, flag, ref_text, before, now_at):
    points = list(before) + ([(now_at, value)] if value is not None else [])
    return {"name": name, "value": _shown(value) or (text or ""), "unit": unit or "",
            "low": low, "high": high, "flag": flag,
            "ref": ref_text if ref_text is not None else (
                f"{_shown(low)} – {_shown(high)}" if low is not None and high is not None
                else (f"< {_shown(high)}" if high is not None
                      else (f"> {_shown(low)}" if low is not None else ""))),
            "bar": _bar(value, low, high),
            "history": points if len(points) > 1 else [],
            "spark": _spark(points)}


def card(order, lang="ar"):
    """One test, ready to draw."""
    lines = []
    if order.analytes_resulted:
        for v in order.analyte_values:
            if not v.has_value:
                continue
            note = v.ref_note if v.ref_kind == "note" else None
            lines.append(_line(v.analyte.name, v.value, v.text, v.unit,
                               v.ref_low, v.ref_high, v.flag, note,
                               _analyte_history(order, v.analyte_id),
                               order.resulted_at))
    elif order.result_value is not None:
        lines.append(_line(order.display_name(lang), order.result_value, None,
                           order.result_unit, order.result_low, order.result_high,
                           _flag(order.result_value, order.result_low, order.result_high),
                           None, _simple_history(order), order.resulted_at))
    out_of = sum(1 for ln in lines if ln["flag"] and ln["flag"] != "normal")
    who = order.orderer or (order.visit.doctor if order.visit else None)
    return {"id": order.id, "name": order.display_name(lang), "lines": lines,
            "text": order.result_text, "comment": order.result_comment,
            "specimen": (order.investigation.sample_type
                         if order.investigation and order.investigation.sample_type else None),
            "collected_at": order.collected_at, "resulted_at": order.resulted_at,
            "verified_at": order.verified_at,
            "verifier": order.verifier.display_name(lang) if order.verifier else None,
            "ordered_by": who.display_name(lang) if who else None,
            "critical": order.critical_at is not None, "out_of": out_of}


def cards(orders, lang="ar"):
    """Every test, and the summary line: how many values are outside their
    reference, of how many."""
    out = [card(o, lang) for o in orders]
    values = sum(len(c["lines"]) for c in out)
    flagged = sum(c["out_of"] for c in out)
    return out, {"tests": len(out), "readings": values, "flagged": flagged}


def numbers_text(orders, lang="ar"):
    """The results as lines of text, for a message — the value, the unit,
    the reference, and ↑ / ↓ where the laboratory's flag says so."""
    arrows = {"low": " ↓", "high": " ↑", "critical_low": " ↓↓", "critical_high": " ↑↑"}
    rows = []
    for c in cards(orders, lang)[0]:
        if not c["lines"]:
            if c["text"]:
                rows.append(f"• {c['name']}: {c['text']}")
            continue
        for ln in c["lines"]:
            ref = f" ({ln['ref']})" if ln["ref"] else ""
            unit = f" {ln['unit']}" if ln["unit"] else ""
            rows.append(f"• {ln['name']}: {ln['value']}{unit}{ref}{arrows.get(ln['flag'], '')}")
    return "\n".join(rows)
