"""Assessment tools inside the visit (DOCTOR_EASE_PLAN.md ب-٤).

The tools live in ``data/visit_scores.json`` — items and points exactly as the
published source has them, the source named beside each. The doctor marks
what they see; the program only adds it up. The result is a **score**, never
a decision: the band beside it is printed only where the source itself
defines one, with that source.

A finished score is kept as an ordinary reading (``Measurement``) on the
visit, so it draws a curve with every other number the child has. Which
answer was picked for each item rides in ``value_text`` (option positions,
dot-separated) so the visit screen can show them again.

The server adds it up again from the posted answers; what the page showed is
a convenience, never what is saved.
"""
import json
import os
from functools import lru_cache

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "visit_scores.json")


@lru_cache(maxsize=1)
def _catalogue():
    with open(_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def catalogue_tools():
    """The tools as the catalogue has them — a licensed one without wording."""
    return list(_catalogue()["tools"])


# ---- licensed tools (c-ACT, ACT) ---------------------------------------
# Their wording is copyrighted. The catalogue carries only their shape; a
# clinic that holds a licence enters the official text and who granted it
# (Setting ``score_text:<key>``), and only then does the tool appear.
def licence_text(key):
    from app.models import Setting

    try:
        data = json.loads(Setting.get(f"score_text:{key}") or "{}")
    except (TypeError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _lang_ready(tool, text, lang):
    items = text.get("items") or []
    if len(items) != len(tool["items"]):
        return False
    for shape, given in zip(tool["items"], items):
        opts = given.get(f"options_{lang}") or []
        if not (given.get(lang) or "").strip() or len(opts) != len(shape["options"]) \
                or not all((o or "").strip() for o in opts):
            return False
    return True


def licence_ready(tool, text=None):
    """``[langs]`` the clinic has entered the full wording in, when it has
    also said whose licence it is; ``[]`` otherwise."""
    if not tool.get("licensed"):
        return ["ar", "en"]
    text = licence_text(tool["key"]) if text is None else text
    if not (text.get("holder") or "").strip():
        return []
    return [lang for lang in ("ar", "en") if _lang_ready(tool, text, lang)]


def _with_text(tool):
    """A licensed tool with the clinic's wording put into its shape."""
    if not tool.get("licensed"):
        return tool
    text = licence_text(tool["key"])
    langs = licence_ready(tool, text)
    if not langs:
        return None
    out = dict(tool, licence_holder=text.get("holder", ""), licence_ref=text.get("ref", ""))
    items = []
    for shape, given in zip(tool["items"], text["items"]):
        item = dict(shape)
        for lang in langs:
            item[f"label_{lang}"] = given[lang].strip()
        item.setdefault("label_ar", item.get("label_en", ""))
        options = []
        for k, opt in enumerate(shape["options"]):
            o = dict(opt)
            for lang in langs:
                o[lang] = given[f"options_{lang}"][k].strip()
            o.setdefault("ar", o.get("en", ""))
            options.append(o)
        item["options"] = options
        items.append(item)
    out["items"] = items
    return out


def all_tools():
    """Every tool ready to use: a licensed one only once its wording is in."""
    return [t for t in (_with_text(t) for t in catalogue_tools()) if t is not None]


def save_licence(key, holder, ref, items):
    """Keep a clinic's licensed wording. ``items``: one dict per question,
    ``{ar, en, options_ar: [...], options_en: [...]}``."""
    from app.models import Setting

    Setting.set(f"score_text:{key}", json.dumps(
        {"holder": (holder or "").strip()[:200], "ref": (ref or "").strip()[:200],
         "items": items}, ensure_ascii=False))


def by_code():
    """Every tool in the catalogue by its reading code (shape and names)."""
    return {t["code"]: t for t in catalogue_tools()}


def tools_for(panel_keys=()):
    """The tools offered on a visit: everywhere ones (``"*"``) and those
    named for one of the visit's specialty panels."""
    keys = set(panel_keys or ())
    return [t for t in all_tools() if "*" in t.get("for", []) or keys & set(t.get("for", []))]


def band(tool, total):
    for b in tool.get("bands") or []:
        if total <= b["max"]:
            return b
    return None


def total_of(tool, picks):
    """``picks``: one option position per item, or ``None`` where unanswered.
    The sum when every item is answered with an option it has, else ``None``."""
    if len(picks) != len(tool["items"]):
        return None
    total = 0
    for item, pick in zip(tool["items"], picks):
        if pick is None or not 0 <= pick < len(item["options"]):
            return None
        total += item["options"][pick]["points"]
    return total


def age_pick(tool, patient):
    """For an item answered by the patient's age (``from_age``): the option
    whose years hold this patient, by item position. ``{}`` when none does."""
    if patient is None or not patient.date_of_birth:
        return {}
    years = patient.age_parts[0]
    out = {}
    for i, item in enumerate(tool["items"]):
        if not item.get("from_age"):
            continue
        for j, opt in enumerate(item["options"]):
            low, high = opt.get("years") or (None, None)
            if low is not None and low <= years <= high:
                out[i] = j
    return out


def in_age(tool, patient):
    """Whether the patient is inside the ages the tool was made for (when the
    tool says), so the screen can say when it is used outside them."""
    rng = tool.get("age_months")
    if not rng or patient is None or not patient.date_of_birth:
        return True
    years, months = patient.age_parts
    age = years * 12 + months
    return rng[0] <= age <= rng[1]


def _picks_from_form(tool, form):
    picks = []
    for item in tool["items"]:
        raw = form.get(f"sc_{tool['key']}_{item['code']}")
        picks.append(int(raw) if raw is not None and str(raw).lstrip("-").isdigit() else None)
    return picks


def save(visit, form, user_id=None):
    """Keep each tool the doctor finished on this visit; a tool marked
    cleared is removed; one half answered is left as it was."""
    from app.extensions import db
    from app.models import Measurement

    saved = {}
    for tool in all_tools():
        row = Measurement.query.filter_by(visit_id=visit.id, code=tool["code"]).first()
        if form.get(f"sc_{tool['key']}_clear") == "1":
            if row is not None:
                db.session.delete(row)
            continue
        picks = _picks_from_form(tool, form)
        if all(p is None for p in picks):
            continue
        total = total_of(tool, picks)
        if total is None:
            continue
        if row is None:
            row = Measurement(patient_id=visit.patient_id, visit_id=visit.id,
                              code=tool["code"], panel="score")
            db.session.add(row)
        row.value_num = float(total)
        row.value_text = ".".join(str(p) for p in picks)
        row.unit = None
        row.recorded_by = user_id
        saved[tool["key"]] = total
    return saved


def state(visit, tools, lang="ar"):
    """What the visit screen needs for each tool: the answers already saved
    on this visit (or the age-given one), the saved total and its band, the
    last finished score on an earlier visit, and whether the patient is in
    the tool's ages."""
    from app.models import Measurement, Visit

    out = {}
    for tool in tools:
        row = Measurement.query.filter_by(visit_id=visit.id, code=tool["code"]).first()
        picks = {}
        if row is not None and row.value_text:
            for i, part in enumerate(row.value_text.split(".")):
                if part.lstrip("-").isdigit():
                    picks[i] = int(part)
        else:
            picks = age_pick(tool, visit.patient)
        last = (Measurement.query.join(Visit, Measurement.visit_id == Visit.id)
                .filter(Measurement.patient_id == visit.patient_id,
                        Measurement.code == tool["code"],
                        Measurement.visit_id != visit.id,
                        Measurement.value_num.isnot(None),
                        Visit.visit_date <= visit.visit_date)
                .order_by(Visit.visit_date.desc(), Measurement.id.desc()).first())
        total = int(row.value_num) if row is not None and row.value_num is not None else None
        b = band(tool, total) if total is not None else None
        out[tool["key"]] = {
            "picks": picks, "total": total,
            "band": (b.get(lang) or b.get("ar")) if b else "",
            "last": ({"total": int(last.value_num), "date": last.visit.visit_date.isoformat()}
                     if last is not None else None),
            "in_age": in_age(tool, visit.patient),
            "age_found": bool(age_pick(tool, visit.patient)) or not any(
                it.get("from_age") for it in tool["items"]),
        }
    return out


__all__ = ["age_pick", "all_tools", "band", "by_code", "in_age", "save", "state",
           "tools_for", "total_of"]
