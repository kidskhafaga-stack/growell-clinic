"""How the child's card looks — the header on the file, the visit, the
emergency attendance, the stay, the vaccinations and the growth chart
(asked: «نعمل إعدادات لشكل كارت المريض زي ما بعتها»).

The owner sent the controls: a design, the mark in the background (the
program's or the clinic's own logo), its colour, how strong, where, and
whether the shortcuts sit under «خيارات أخرى» or are all shown. Every value
is the clinic's choice in Settings → logo; the defaults are exactly the card
as it stood before the choice existed, so an update changes nothing.

What never changes with the look: the allergy and chronic illness inside the
card in red and amber, and the arrest button on the stay always on top.
"""

STYLES = ("waves", "original", "soft", "brand", "stroke", "accent")
LOGOS = ("program", "clinic", "none")
COLOURS = ("brand", "mono", "white")
PLACES = ("corner", "center", "full")
KEYS = ("menu", "all")

DEFAULTS = {"style": "waves", "logo": "program", "color": "brand",
            "opacity": 12, "pos": "corner", "keys": "menu"}

SETTING = {"style": "card_style", "logo": "card_logo", "color": "card_color",
           "opacity": "card_opacity", "pos": "card_pos", "keys": "card_keys"}

PROGRAM_MARK = "img/brand/pediapro-mark.png"


def _pick(value, allowed, default):
    value = (value or "").strip()
    return value if value in allowed else default


def opacity(value):
    """A whole percentage between 3 and 25 — the slider's range."""
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return DEFAULTS["opacity"]
    return max(3, min(25, n))


def read(rows, logo_url=None):
    """The card's look from the settings rows (``{key: value}``), with the
    clinic's logo URL when one is uploaded."""
    from flask import url_for

    try:
        program = url_for("static", filename=PROGRAM_MARK)
    except RuntimeError:            # outside a request
        program = "/static/" + PROGRAM_MARK
    look = {
        "style": _pick(rows.get(SETTING["style"]), STYLES, DEFAULTS["style"]),
        "logo": _pick(rows.get(SETTING["logo"]), LOGOS, DEFAULTS["logo"]),
        "color": _pick(rows.get(SETTING["color"]), COLOURS, DEFAULTS["color"]),
        "opacity": opacity(rows.get(SETTING["opacity"]) or DEFAULTS["opacity"]),
        "pos": _pick(rows.get(SETTING["pos"]), PLACES, DEFAULTS["pos"]),
        # Not "keys": a template reading ``look.keys`` gets the dict's method.
        "shortcuts": _pick(rows.get(SETTING["keys"]), KEYS, DEFAULTS["keys"]),
        "program_url": program,
        "clinic_url": logo_url,
    }
    # The clinic's own logo, when it chose it and uploaded one; otherwise
    # the program's. The fine-line stamp is drawn from the program's mark, so
    # it is only that mark that can be drawn in lines.
    look["src"] = "clinic" if (look["logo"] == "clinic" and logo_url) else "program"
    look["url"] = logo_url if look["src"] == "clinic" else program
    return look


__all__ = ["COLOURS", "DEFAULTS", "KEYS", "LOGOS", "PLACES", "SETTING", "STYLES",
           "opacity", "read"]
