"""What a complete prescription line carries — GAHAR `MMS.11` (هـ).

The standard lists eleven things. Most were already on the paper: who the
child is, the drug, the dose, how often and how long, the doctor. What was
missing is here, and **none of it is typed by the doctor twice**:

* the form, the strength and the route come from the catalogue entry the
  doctor already picked (:func:`snapshot`);
* the height sits beside the weight when they were taken together
  (:func:`height_for`);
* the time sits beside the date, from when it was written;
* only a "when needed" line asks anything new — what for, and how often at
  most — because without those a «عند اللزوم» is an open bottle (:func:`is_prn`).

And (ز): a line that is still missing something is *said* to be, on the
prescription's own screen (:func:`missing`). Never a block — a doctor who
cannot save is a doctor who writes on paper.
"""
from app.utils.rx_shorthand import expand_frequency

#: The settled wording the shorthand gives "prn" / "sos" / «عند اللزوم».
PRN_TEXT = expand_frequency("prn")

# The catalogue carries routes in two vocabularies — the Egyptian register's
# and the drug book's. Each maps to the words a ward already uses where there
# are some (``meds.route_*``), and to its own where there are not.
_ROUTE_KEYS = {
    "oral": "meds.route_oral",
    "topical": "meds.route_topical",
    "eye": "meds.route_eye", "ophthalmic": "meds.route_eye",
    "ear": "meds.route_ear", "otic": "meds.route_ear",
    "rectal": "meds.route_rectal",
    "inhaled": "meds.route_inhaled", "inhalation": "meds.route_inhaled",
    "nebulised": "meds.route_nebulised",
    "iv": "meds.route_iv", "im": "meds.route_im", "sc": "meds.route_sc",
    "injection": "rx.route_injection",
    "nasal": "rx.route_nasal",
    "vaginal": "rx.route_vaginal",
    "oromucosal": "rx.route_mouth",
}


def route_word(code):
    """The route in the reader's language, or as stored when unknown."""
    from app.i18n import t

    code = (code or "").strip()
    key = _ROUTE_KEYS.get(code.lower())
    return t(key) if key else code


def form_word(code):
    from app.i18n import t
    from app.models.prescription import DRUG_FORMS

    code = (code or "").strip()
    return t("drug_forms." + code) if code in DRUG_FORMS else code


def snapshot(drug):
    """``{form, strength, route}`` off a catalogue entry, blanks as None."""
    if drug is None:
        return {"form": None, "strength": None, "route": None}
    return {key: ((getattr(drug, key, None) or "").strip() or None)
            for key in ("form", "strength", "route")}


def is_prn(frequency):
    return (frequency or "").strip() == PRN_TEXT


def _count(value, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def prn_fields(frequency, reason, min_hours, max_per_day):
    """What a line keeps of the three "when needed" boxes.

    Nothing unless the line *is* "when needed": boxes the screen hid are not
    a doctor's answer, and a reason left over from before the frequency was
    changed would print on a line that no longer needs one.
    """
    if not is_prn(frequency):
        return {"prn_reason": None, "prn_min_hours": None, "prn_max_per_day": None}
    return {"prn_reason": (reason or "").strip()[:160] or None,
            "prn_min_hours": _count(min_hours, 1, 72),
            "prn_max_per_day": _count(max_per_day, 1, 24)}


def missing(item):
    """The `MMS.11` elements this line still lacks — keys, in print order."""
    gaps = []
    if not (item.dose or "").strip():
        gaps.append("dose")
    if not (item.frequency or "").strip():
        gaps.append("frequency")
    if is_prn(item.frequency):
        if not (item.prn_reason or "").strip():
            gaps.append("prn_reason")
        if not (item.prn_min_hours or item.prn_max_per_day):
            gaps.append("prn_max")
    elif not (item.duration or "").strip():
        gaps.append("duration")
    return gaps


def incomplete(rx):
    """``[(item, gaps)]`` for every line of ``rx`` that is missing something."""
    out = []
    for item in rx.items:
        gaps = missing(item)
        if gaps:
            out.append((item, gaps))
    return out


def height_for(patient, weight_record=None):
    """The height to print beside the weight: ``(cm, date)`` or ``None``.

    **Only from the weight's own measurement.** The newest height taken on
    another day, set beside today's weight, is the child who never existed
    that ``growth_picture`` already refuses to draw — and how old is too old
    for a growing child's height is a clinical number this program has no
    business choosing. A clinic that measures both at the desk gets both.
    """
    if weight_record is not None and getattr(weight_record, "height_cm", None):
        return weight_record.height_cm, weight_record.record_date
    return None


def line_facts(item):
    """The words printed under a drug's name: form · strength · route.

    The strength is left out when the name already carries it — the picker
    names a product "Brufen 100mg/5ml" precisely so two rows of one brand
    can be told apart — because saying it twice is noise on a paper that is
    already short of room.
    """
    facts = []
    if getattr(item, "form", None):
        facts.append(form_word(item.form))
    strength = (getattr(item, "strength", None) or "").strip()
    squash = lambda text: "".join((text or "").lower().split())  # noqa: E731
    if strength and squash(strength) not in squash(item.drug_name):
        facts.append(strength)
    if getattr(item, "route", None):
        facts.append(route_word(item.route))
    return facts


def prn_words(item):
    """The "when needed" limits in words — Arabic counted the Arabic way."""
    from app.i18n import get_locale, t
    from app.utils.rx_shorthand import ar_plural

    arabic = get_locale() == "ar"
    words = []
    if not any(getattr(item, key, None)
               for key in ("prn_reason", "prn_min_hours", "prn_max_per_day")):
        return words
    if item.prn_reason:
        words.append(t("rx.prn_for", reason=item.prn_reason))
    if item.prn_min_hours:
        n = item.prn_min_hours
        words.append(t("rx.prn_every", n=ar_plural(n, "ساعة", "ساعتين", "ساعات", "ساعة")
                       if arabic else n))
    if item.prn_max_per_day:
        n = item.prn_max_per_day
        words.append(t("rx.prn_most", n=ar_plural(n, "مرة", "مرتين", "مرات", "مرة")
                       if arabic else n))
    return words


def init_app(app):
    """The two the printed paper asks for, wherever it is included from."""
    app.jinja_env.globals["rx_height"] = height_for
    app.jinja_env.globals["rx_line_facts"] = line_facts
    app.jinja_env.globals["rx_prn_words"] = prn_words


def past_reasons(limit=30):
    """The "what for" this clinic has written before, most used first.

    Offered as suggestions on the box, so the second time is one tap. Only
    what doctors here actually wrote — nothing is supplied from outside.
    """
    from sqlalchemy import func

    from app.extensions import db
    from app.models.prescription import PrescriptionItem

    rows = (db.session.query(PrescriptionItem.prn_reason,
                             func.count(PrescriptionItem.id))
            .filter(PrescriptionItem.prn_reason.isnot(None),
                    PrescriptionItem.prn_reason != "")
            .group_by(PrescriptionItem.prn_reason)
            .order_by(func.count(PrescriptionItem.id).desc())
            .limit(limit).all())
    return [reason for reason, _ in rows]
