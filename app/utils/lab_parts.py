"""What a common test is made of, offered — never filled in.

Asked as *«عندي قائمة بالتحاليل … بس معنديش كل تحليل مكوناته ايه؟ هل ممكن
احنا ندرجها؟»*. A hospital's list often names its tests and nothing more;
the sheet says «Panel» where the parts should be (``lab_import`` keeps that
as ``parts_missing``) or says nothing at all.

**What a test is made of is not a clinical number.** A urine analysis has a
colour, a pH, a protein, pus cells per high-power field — that is what the
test *is*, the same in every laboratory. So the program can offer it. What it
does not offer is a single figure: a usual range belongs to the laboratory's
analyser and kit (``models/lab_reference.py``), and arrives by import, by
hand or from the insert reader, a draft until the director approves it.

The list lives in ``app/data/lab_panel_parts.json`` — data, not code. On a
test's page, when its name is one the list knows, the parts are shown ticked
beside the unit most laboratories print; a person unticks what the
laboratory does not report, corrects a unit, and saves. Nothing is added
without that press.

An analyte the laboratory already has is **reused**, found by any of its
names — the «Hb» already on the CBC is the «Hemoglobin» offered, not a
second haemoglobin with no ranges. Parts the list marks as calculated
(indirect bilirubin = total − direct) are wired to the program's own
published formula only when both inputs are on the test.
"""
import json
import os

from app.extensions import db

_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lab_panel_parts.json")
_CACHE = {}


def panels():
    if "panels" not in _CACHE:
        with open(_PATH, encoding="utf-8") as fh:
            _CACHE["panels"] = json.load(fh)["panels"]
    return _CACHE["panels"]


def _keys(text):
    """The whole name and the part in brackets, compared exactly — not the
    looser key the import uses, which would make a «Total Bilirubin» test
    the bilirubin panel."""
    from app.utils.lab_import import _bracketed, key

    return {key(one) for one in (text, _bracketed(text or "")) if one and key(one)}


def _test_keys(test):
    from app.utils.lab_import import _aliases

    out = set()
    names = [test.name_en, test.name_ar, test.code]
    names += _aliases(getattr(test, "aliases", None) or "")
    for name in names:
        out |= _keys((name or "").strip())
    return out


def panel_for(test):
    """The list's entry for this test, or ``None``. Matched on the whole
    name (or the part in brackets) — «Urine culture» is not a urine
    analysis."""
    if test is None or getattr(test, "kind", "lab") != "lab":
        return None
    mine = _test_keys(test)
    if not mine:
        return None
    for panel in panels():
        theirs = set()
        for name in panel["names"]:
            theirs |= _keys(name)
        if mine & theirs:
            return panel
    return None


def _existing(part):
    """An analyte the laboratory already has under any of this part's
    names."""
    from app.models import LabAnalyte
    from app.utils.lab_import import key

    wanted = {key(part["name"]), key(part.get("name_ar") or "")} - {""}
    for analyte in LabAnalyte.query.all():
        if wanted & {key(n) for n in analyte.names()}:
            return analyte
    return None


def offer(test):
    """What the page shows: the panel and each part with whether it is
    already on the test and whether the laboratory already has it."""
    panel = panel_for(test)
    if panel is None:
        return None
    on_test = {link.analyte_id for link in test.analyte_links}
    rows = []
    for i, part in enumerate(panel["parts"]):
        have = _existing(part)
        rows.append({"i": i, "part": part, "analyte": have,
                     "on_test": bool(have and have.id in on_test),
                     "unit": (have.unit if have and have.unit else part.get("unit") or "")})
    if all(r["on_test"] for r in rows):
        return None
    return {"panel": panel, "rows": rows,
            "groups": sorted({p.get("group") for p in panel["parts"] if p.get("group")})}


def apply(test, picked, units):
    """Put the ticked parts on the test. ``picked`` — the indexes ticked;
    ``units`` — ``{index: unit}`` as the person left them. Returns ``(added,
    calculated)``."""
    from app.utils import lab_calc, lab_hand

    panel = panel_for(test)
    if panel is None:
        return 0, 0
    added, made = 0, {}
    if not getattr(test, "section", None) and panel.get("section"):
        test.section = panel["section"]
    before = {link.analyte_id for link in test.analyte_links}
    for i, part in enumerate(panel["parts"]):
        if i not in picked:
            continue
        unit = (units.get(i) or "").strip()[:30] or part.get("unit")
        have = _existing(part)
        analyte = lab_hand.add_analyte(test, have.name if have else part["name"],
                                       part.get("name_ar"), unit)
        made[part["name"]] = analyte
        if analyte.id not in before:
            added += 1
    db.session.flush()
    db.session.refresh(test)
    calculated = 0
    for part in panel["parts"]:
        analyte = made.get(part["name"])
        if analyte is None or not part.get("formula") or analyte.formula:
            continue
        chosen = {slot: made[name].id for slot, name in part["inputs"].items()
                  if name in made}
        if len(chosen) != len(part["inputs"]):
            continue
        try:
            lab_calc.configure(analyte, test, part["formula"], chosen)
            calculated += 1
        except lab_calc.CalcRefused:
            continue
    return added, calculated


__all__ = ["apply", "offer", "panel_for", "panels"]
