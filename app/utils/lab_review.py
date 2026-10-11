"""A second pair of eyes on a result before it is released — and a person decides.

The verifier looks at a written result and asks the questions every bench
asks before a result leaves: *is this possible, does it agree with itself,
does it look like the sample rather than the child* — a potassium of 7 in a
tube with a platelet count of 900, a calcium that fell by half in a day, an
MCHC no red cell can carry. The assistant is asked those questions and no
others.

**What it is asked for is narrow on purpose.** Points a verifier would check
before releasing, each one of: ``preanalytical`` (haemolysis, EDTA or drip
contamination, a clotted or wrong tube, a sample that may belong to someone
else), ``implausible`` (a value or a combination the body cannot hold),
``inconsistent`` (the result disagrees with itself), ``delta`` (a change from
this child's previous value that needs a reason) — or nothing. It is told not
to diagnose, not to suggest treatment, not to suggest a reference range and
never to say a result may be released.

**Nothing a child can be found by is sent**: no name, no file number, no
date — the age in days, the sex, the test's lines with the bench's own range
and flag, the previous value with how many days ago, and the other results
written on the same visit that day (a potassium is read beside the platelet
count). So it answers to its own switch, ``ai_lab_review``, off until the
hospital turns it on, and not to the patient-data one.

**And nothing it says is saved, or changes anything.** :func:`review` returns
the points; the order page shows them beside the result, marked as the
assistant's. Releasing stays ``lab_release.verify``, by whoever the hospital
authorized, whatever the assistant said — including nothing.
"""
import json
import re

#: What a point may be about — the screen's words are ``lab_review.kind_<k>``.
KINDS = ("preanalytical", "implausible", "inconsistent", "delta")

SYSTEM = (
    "You are a second pair of eyes for a laboratory scientist who is verifying "
    "a paediatric laboratory result before it is released. You are given the "
    "child's age in days and sex, the test, each line with its value, unit, "
    "the laboratory's own reference range and flag, the child's previous value "
    "where there is one, and other results from the same visit that day. "
    "Point out only what a verifier should check before releasing: "
    "\"preanalytical\" — a pattern suggesting the sample rather than the child "
    "(haemolysis, EDTA or IV-fluid contamination, a clotted or wrong tube, a "
    "possible sample mix-up); \"implausible\" — a value or combination that is "
    "not physiologically possible; \"inconsistent\" — the result disagrees with "
    "itself or with the other results given; \"delta\" — a change from the "
    "previous value that needs an explanation. Do not diagnose, do not suggest "
    "treatment or further tests, do not propose reference ranges, and never "
    "say that the result may or may not be released. If nothing stands out, "
    "return an empty list. Answer with one JSON object only: "
    "{\"points\": [{\"kind\": one of the four words, \"text\": one short "
    "sentence}]}, at most five points, the sentences written in LANGUAGE."
)

MAX_POINTS = 5


class ReviewError(ValueError):
    """A refusal with a key the screen can name (``lab_review.err_<key>``)."""


def enabled():
    from app.models import Setting

    return Setting.get("ai_lab_review") == "1"


def ready():
    """Switched on and the assistant set up — the button shows only then."""
    from app.utils import ai

    try:
        return enabled() and ai.is_ready()
    except Exception:          # noqa: BLE001 - a settings read never breaks the bench
        return False


# ---------------------------------------------------------------- facts ---
def _num(v):
    return "%g" % v if isinstance(v, (int, float)) else None


def _range(row):
    low, high = _num(row.ref_low), _num(row.ref_high)
    if low and high:
        return f"{low}-{high}"
    if high:
        return f"<{high}"
    if low:
        return f">{low}"
    return None


def _line(name, value, unit, rng=None, flag=None, prev=None, prev_days=None,
          calculated=False):
    bits = [f"{name}: {value}" + (f" {unit}" if unit else "")]
    if rng:
        bits.append(f"range {rng}")
    if flag:
        bits.append(f"flag {flag}")
    if calculated:
        bits.append("calculated")
    if prev is not None:
        bits.append(f"previous {prev}" + (f" ({prev_days} days ago)" if prev_days is not None else ""))
    return "; ".join(bits)


def _name(order):
    return order.name_en or order.name or "test"


def _order_lines(order):
    """The order's written lines, as plain text — values the bench wrote."""
    out = []
    at = order.collected_at or order.created_at
    for v in sorted(order.analyte_values or [], key=lambda r: (r.sort_order, r.id)):
        value = _num(v.value) if v.value is not None else (v.text or None)
        if value is None:
            continue
        days = None
        if v.delta_prev_at is not None and at is not None:
            days = max(0, (at - v.delta_prev_at).days)
        out.append(_line(v.analyte.name if v.analyte else "?", value, v.unit,
                         rng=_range(v), flag=v.flag,
                         prev=_num(v.delta_prev), prev_days=days,
                         calculated=bool(getattr(v, "calculated", False))))
    if not out and (order.result_value is not None or order.result_text):
        value = _num(order.result_value) if order.result_value is not None else None
        rng = None
        if order.result_low is not None or order.result_high is not None:
            rng = f"{_num(order.result_low) or ''}-{_num(order.result_high) or ''}"
        if value is not None:
            out.append(_line(_name(order), value, order.result_unit, rng=rng))
        if order.result_text:
            out.append("Report text: " + order.result_text.strip()[:600])
    return out


def _same_day(order):
    """Other results written on the same visit the same day — read beside."""
    from app.models import VisitInvestigation

    if not order.visit_id:
        return []
    at = order.collected_at or order.created_at
    rows = (VisitInvestigation.query
            .filter(VisitInvestigation.visit_id == order.visit_id,
                    VisitInvestigation.id != order.id,
                    VisitInvestigation.kind == "lab").all())
    out = []
    for r in rows:
        when = r.collected_at or r.created_at
        if at is not None and when is not None and abs((when - at).days) > 0:
            continue
        lines = _order_lines(r)
        if lines:
            out.append((_name(r), lines[:20]))
    return out[:6]


def facts(order):
    """Everything sent, as one text — nothing a child can be found by."""
    from app.utils import lab_results

    at = order.collected_at or order.created_at
    age = lab_results.age_days(order.patient, at)
    sex = lab_results.sex_of(order.patient) or "not recorded"
    sample = getattr(order.investigation, "sample_type", None) if order.investigation else None
    lines = _order_lines(order)
    if not lines:
        raise ReviewError("nothing_written")
    parts = [f"Child: age {age if age is not None else 'unknown'} days; sex {sex}.",
             f"Test: {_name(order)}" + (f"; sample {sample}" if sample else ""),
             "Lines:", *("- " + x for x in lines)]
    other = _same_day(order)
    if other:
        parts.append("Other results from the same visit that day:")
        for name, ls in other:
            parts.append(f"{name}:")
            parts.extend("- " + x for x in ls)
    return "\n".join(parts)


# ---------------------------------------------------------------- reply ---
def parse_reply(text):
    """``[{kind, text}]`` from the reply — anything else is dropped."""
    raw = (text or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    points = data.get("points") if isinstance(data, dict) else None
    if not isinstance(points, list):
        return None
    out = []
    for p in points:
        if not isinstance(p, dict):
            continue
        kind, words = p.get("kind"), str(p.get("text") or "").strip()
        if kind in KINDS and words:
            out.append({"kind": kind, "text": words[:300]})
        if len(out) >= MAX_POINTS:
            break
    return out


def review(order, lang="ar", config=None):
    """Ask. Returns ``[{kind, text}]`` — possibly empty: nothing stood out.
    Raises :class:`ReviewError`."""
    from app.utils import ai

    if not enabled():
        raise ReviewError("off")
    body = facts(order)
    language = "Arabic" if lang == "ar" else "English"
    result = ai.chat([{"role": "user", "content": body}],
                     system=SYSTEM.replace("LANGUAGE", language),
                     config=config, feature="lab_review")
    if not result.get("ok"):
        raise ReviewError("ai:" + str(result.get("error") or "unknown"))
    points = parse_reply(result.get("text"))
    if points is None:
        raise ReviewError("unreadable")
    return points


__all__ = ["KINDS", "ReviewError", "enabled", "facts", "parse_reply", "ready",
           "review"]
