"""A continuous infusion: the doctor's dose per kilo, as millilitres an hour
(DOCTOR_EASE ٤-ج ع-٣).

Arithmetic only, from three numbers the doctor writes — the dose and its unit,
and the syringe (so many mg, or units, in so many mL) — and the child's latest
weight. The program has no dose of its own and says nothing about whether the
dose is right: the answer is shown for the doctor to confirm.
"""
#: unit → how many of the syringe's amount-units an hour, per kilo, per 1 dose.
#: The syringe holds mg (or units, for «units/kg/h»).
UNITS = {
    "mcg_kg_min": 60 / 1000.0,   # mcg/kg/min → mg/kg/h
    "mcg_kg_h": 1 / 1000.0,      # mcg/kg/h  → mg/kg/h
    "mg_kg_h": 1.0,              # mg/kg/h
    "units_kg_h": 1.0,           # units/kg/h, with units in the syringe
}


class InfusionError(ValueError):
    """A refusal with a key (``infusion.err_<key>``)."""


def _number(raw, key):
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise InfusionError(key)
    if value <= 0:
        raise InfusionError(key)
    return value


def rate(dose, unit, weight_kg, amount, volume_ml):
    """``{"ml_h", "per_h", "concentration"}`` — mL an hour, the amount an
    hour (mg or units), and the syringe's amount per mL."""
    if unit not in UNITS:
        raise InfusionError("unit")
    dose = _number(dose, "dose")
    weight = _number(weight_kg, "weight")
    amount = _number(amount, "syringe")
    volume = _number(volume_ml, "syringe")
    concentration = amount / volume
    per_h = dose * weight * UNITS[unit]
    return {"ml_h": round(per_h / concentration, 2), "per_h": round(per_h, 3),
            "concentration": round(concentration, 4)}
