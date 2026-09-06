"""What the reference says, beside what the assistant says.

The assistant used to answer alone. The prescription screen had a button that
asked a language model for a dose and wrote the reply straight into the dose,
the frequency and the duration — three fields, filled from a sentence nobody
checked, on a screen whose whole other half is a reference with a citation on
every figure.

**Two numbers is not the problem. One number with no second opinion is.** The
value of asking a model here was never the number: it is the moment the model
says something the reference does not, because that is the moment worth
stopping on. Silently overwriting the reference's answer destroyed exactly
that signal — the disagreement arrived as an agreement.

So this module produces the comparison, and it is careful about three things.

**The reference answers as a range, not a point.** Paracetamol is 10–15 mg/kg;
a model saying 13 mg/kg is not disagreeing with anything. Only the clinic's
own band decides, so "different from what the screen shows" is not reported as
a conflict.

**The ceiling is a different kind of answer.** Inside the band, outside the
band and *over the maximum* are three verdicts, not two, because the third one
is the only one where somebody must not press the button.

**And "I could not read it" is a verdict too.** A reply with no milligrams in
it — or in words, or per dose when we hold per day — is reported as
unreadable, never as agreement. Agreement is a claim, and a claim needs
something to compare.
"""
import re

# Someone types "500mg", "500 mg", "٥٠٠ مج" or "250 mg (5 ml)". The first
# milligram figure is the dose; a millilitre figure after it is the volume it
# was converted to, and is not a second opinion about anything.
_MG = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:mg|مج|مجم|ملجم|ميلليجرام)", re.I)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def milligrams(text):
    """The first milligram figure in a free-text dose, or ``None``.

    ``None`` is a real answer and the safe one: it means the reply cannot be
    compared, which is different from the reply agreeing.
    """
    found = _MG.search((text or "").translate(_ARABIC_DIGITS))
    if not found:
        return None
    try:
        return float(found.group(1).replace(",", "."))
    except ValueError:            # "1.2.3 mg" and friends
        return None


def reference_dose(drug, weight_kg):
    """The band this program's own reference gives for one product, or None.

    ``None`` whenever the reference has nothing to say — no ingredient behind
    the box, no weight on the child, no per-kilo figure — and the screen then
    has to say *that*, rather than let the assistant's number stand as though
    it had been checked.
    """
    try:
        weight = float(weight_kg)
    except (TypeError, ValueError):
        return None
    if weight <= 0:
        return None

    generic = getattr(drug, "generic", None)
    low = getattr(drug, "dose_per_kg", None) or (
        generic.dose_per_kg if generic else None)
    if not low:
        return None
    high = (generic.dose_per_kg_max if generic else None) or low
    if high < low:
        low, high = high, low

    per_dose = generic.dose_basis != "per_day" if generic else True
    ceiling = generic.max_single_dose_mg if generic else None
    if not per_dose:
        ceiling = (generic.max_daily_dose_mg if generic else None) or ceiling

    band = {
        "low_mg": round(weight * low, 1),
        "high_mg": round(weight * high, 1),
        "per_dose": per_dose,
        "doses_per_day": (generic.doses_per_day if generic else None),
        "max_mg": ceiling,
        "source": (generic.reference if generic else None) or "",
        "ingredient": (generic.display_name("ar") if generic else ""),
    }
    conc = getattr(drug, "conc_mg_per_ml", None)
    if conc:
        band["low_ml"] = round(band["low_mg"] / conc, 1)
        band["high_ml"] = round(band["high_mg"] / conc, 1)
    # A ceiling below the band's own top is the ceiling talking: a 40 kg child
    # on paracetamol is 400–600 mg by weight and 1000 mg by the adult cap, but
    # a 90 kg adolescent is 900–1350 and the cap is the answer.
    if ceiling and band["high_mg"] > ceiling:
        band["capped_mg"] = ceiling
    return band


#: What the comparison can conclude. Four, not two.
VERDICTS = ("inside", "under", "over", "over_ceiling", "unreadable")


def compare(band, suggested):
    """Where the assistant's dose falls against the reference's own band.

    ``band`` is :func:`reference_dose`'s answer, ``suggested`` the free text
    the assistant replied with. Returns ``(verdict, milligrams)``.

    ``"unreadable"`` when either side has no number — including when the
    reference itself has nothing, which is the case the screen most needs to
    show honestly, because it is the one where nobody has checked anything.
    """
    mg = milligrams(suggested)
    if not band or mg is None:
        return "unreadable", mg
    ceiling = band.get("max_mg")
    if ceiling and mg > ceiling:
        return "over_ceiling", mg
    if mg < band["low_mg"]:
        return "under", mg
    if mg > band["high_mg"]:
        return "over", mg
    return "inside", mg


def agrees(verdict):
    """True only for the one verdict that is agreement.

    Written as a function and not as ``verdict == "inside"`` scattered about,
    because the interesting mistake is treating "unreadable" as agreement, and
    it is a mistake that reads perfectly naturally at every call site.
    """
    return verdict == "inside"
