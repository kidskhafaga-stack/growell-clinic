"""Calculated results — a number the laboratory derives from others it measured.

The anion gap, an LDL by Friedewald, a corrected calcium, the indirect
bilirubin, a bedside eGFR: a laboratory works them out on a calculator and
types them in, and a typed sum is a sum that can be typed wrong. Here an
analyte can be **marked calculated** by the laboratory: it chooses the
formula from the list below and which of the test's own analytes feed it, and
the value is worked out when its inputs are written — read only on the
bench, judged against its own ranges, and compared with the child's last one
like any other (`utils/lab_delta`).

**Nothing is switched on by the program.** The list is the published
formulas with their published constants, each said in full on the screen, and
the laboratory turns on the ones it uses — on its own analytes, in the units
the formula is written for. An input in another unit is refused rather than
converted: a conversion nobody sees is how a result ends up 88 times wrong.

**When it is not worked out**, it says why rather than printing a number:
an input missing, Friedewald with triglycerides above the formula's own
limit, a bedside eGFR with no height on the same visit.
"""
import json

from app.extensions import db

#: ``same`` — every input in one unit, and the result in it.
FORMULAS = {
    "anion_gap": {
        "inputs": (("na", "Na", "mmol/L"), ("cl", "Cl", "mmol/L"), ("hco3", "HCO₃", "mmol/L")),
        "unit": "mmol/L", "text": "Na − (Cl + HCO₃)",
        "fn": lambda v, h: v["na"] - (v["cl"] + v["hco3"])},
    "ldl_mgdl": {
        "inputs": (("tc", "Total cholesterol", "mg/dL"), ("hdl", "HDL", "mg/dL"),
                   ("tg", "Triglycerides", "mg/dL")),
        "unit": "mg/dL", "text": "Friedewald: TC − HDL − TG/5 (TG ≤ 400 mg/dL)",
        "limit": ("tg", 400.0),
        "fn": lambda v, h: v["tc"] - v["hdl"] - v["tg"] / 5.0},
    "ldl_mmol": {
        "inputs": (("tc", "Total cholesterol", "mmol/L"), ("hdl", "HDL", "mmol/L"),
                   ("tg", "Triglycerides", "mmol/L")),
        "unit": "mmol/L", "text": "Friedewald: TC − HDL − TG/2.2 (TG ≤ 4.5 mmol/L)",
        "limit": ("tg", 4.5),
        "fn": lambda v, h: v["tc"] - v["hdl"] - v["tg"] / 2.2},
    "non_hdl": {
        "inputs": (("tc", "Total cholesterol", "same"), ("hdl", "HDL", "same")),
        "unit": "same", "text": "TC − HDL",
        "fn": lambda v, h: v["tc"] - v["hdl"]},
    "indirect_bili": {
        "inputs": (("total", "Total bilirubin", "same"), ("direct", "Direct bilirubin", "same")),
        "unit": "same", "text": "Total − Direct",
        "fn": lambda v, h: v["total"] - v["direct"]},
    "globulin": {
        "inputs": (("protein", "Total protein", "same"), ("albumin", "Albumin", "same")),
        "unit": "same", "text": "Total protein − Albumin",
        "fn": lambda v, h: v["protein"] - v["albumin"]},
    "corrected_ca_mgdl": {
        "inputs": (("ca", "Calcium", "mg/dL"), ("albumin", "Albumin", "g/dL")),
        "unit": "mg/dL", "text": "Ca + 0.8 × (4.0 − Albumin)",
        "fn": lambda v, h: v["ca"] + 0.8 * (4.0 - v["albumin"])},
    "schwartz_mgdl": {
        "inputs": (("cr", "Creatinine", "mg/dL"),), "height": True,
        "unit": "mL/min/1.73m²", "text": "Bedside Schwartz: 0.413 × height (cm) / creatinine (mg/dL)",
        "fn": lambda v, h: 0.413 * h / v["cr"] if v["cr"] else None},
    "schwartz_umol": {
        "inputs": (("cr", "Creatinine", "µmol/L"),), "height": True,
        "unit": "mL/min/1.73m²", "text": "Bedside Schwartz: 36.5 × height (cm) / creatinine (µmol/L)",
        "fn": lambda v, h: 36.5 * h / v["cr"] if v["cr"] else None},
}


class CalcRefused(ValueError):
    """A refusal with a locale key (``lab_calc.<key>``) and its words."""

    def __init__(self, key, **words):
        super().__init__(key)
        self.key, self.words = key, words


def _norm(unit):
    return (unit or "").replace(" ", "").replace("μ", "µ").casefold()


def inputs_of(analyte):
    try:
        return json.loads(analyte.formula_inputs or "{}")
    except ValueError:
        return {}


def configure(analyte, test, formula, chosen):
    """Mark ``analyte`` calculated by ``formula`` from ``chosen`` (``{slot:
    analyte id}``), all of them analytes of ``test``. ``formula`` empty
    clears it. The caller commits."""
    if not formula:
        analyte.formula = analyte.formula_inputs = None
        return
    spec = FORMULAS.get(formula)
    if spec is None:
        raise CalcRefused("unknown")
    own = {link.analyte_id: link.analyte for link in test.analyte_links}
    picked, units = {}, set()
    for slot, label, unit in spec["inputs"]:
        aid = chosen.get(slot)
        source = own.get(aid)
        if source is None or source.id == analyte.id:
            raise CalcRefused("need_input", what=label)
        if unit != "same" and _norm(source.unit) != _norm(unit):
            raise CalcRefused("wrong_unit", what=label, want=unit, got=source.unit or "—")
        units.add(_norm(source.unit))
        picked[slot] = source.id
    if spec["unit"] == "same" and len(units) > 1:
        raise CalcRefused("units_differ")
    # The result's own unit: the formula's, or the inputs' for a difference.
    want = (next(iter(units)) if spec["unit"] == "same" else spec["unit"])
    if analyte.unit and _norm(analyte.unit) != _norm(want):
        raise CalcRefused("result_unit", want=want, got=analyte.unit)
    if not analyte.unit:
        analyte.unit = (own[picked[spec["inputs"][0][0]]].unit
                        if spec["unit"] == "same" else spec["unit"])
    analyte.formula = formula
    analyte.formula_inputs = json.dumps(picked)


def _height(order):
    """The height written on the order's own visit, or ``None``."""
    from app.models import GrowthRecord, VitalSigns

    if not order.visit_id:
        return None
    vs = (VitalSigns.query.filter(VitalSigns.visit_id == order.visit_id,
                                  VitalSigns.height_cm.isnot(None))
          .order_by(VitalSigns.id.desc()).first())
    if vs is not None:
        return vs.height_cm
    gr = (GrowthRecord.query.filter(GrowthRecord.visit_id == order.visit_id,
                                    GrowthRecord.height_cm.isnot(None))
          .order_by(GrowthRecord.id.desc()).first())
    return gr.height_cm if gr is not None else None


def work_out(analyte, order):
    """``(value, why_not)`` for a calculated ``analyte`` on ``order``."""
    spec = FORMULAS.get(analyte.formula or "")
    if spec is None:
        return None, "unknown"
    values = {v.analyte_id: v.value for v in (order.analyte_values or [])
              if v.value is not None and not v.calculated}
    slots = inputs_of(analyte)
    got = {}
    for slot, _label, _unit in spec["inputs"]:
        if values.get(slots.get(slot)) is None:
            return None, "missing"
        got[slot] = values[slots[slot]]
    limit = spec.get("limit")
    if limit and got[limit[0]] > limit[1]:
        return None, "over_limit"
    height = None
    if spec.get("height"):
        height = _height(order)
        if not height:
            return None, "no_height"
    value = spec["fn"](got, height)
    if value is None:
        return None, "missing"
    return round(value, 2), None


def text_of(analyte):
    spec = FORMULAS.get(analyte.formula or "")
    return spec["text"] if spec else ""


__all__ = ["FORMULAS", "CalcRefused", "configure", "inputs_of", "text_of", "work_out"]
