"""Which label's age limit a clinic follows — and, when it writes its own,
whether the label changed or the clinic decided.

The catalogue (``app/data/egypt_vaccines.json``) quotes each brand's label
under ``label_age``: the sentence, the link, the day it was read, and the
upper age in days (``None`` where the label has none). Where the EU and US
labels disagree it carries both, the EU one first — the default, by the
clinic owner's decision on 16 November 2026:

    «امشي على النشرة الأوروبية اكتب الاثنين النشرتين وخلى الديفولت الاوربية
    وينفع اي مستشفى تغير او عيادة حسب النشرة المعتمده لديها او تقدر تعدل ولما
    يعدل يقول هل حصل تعديل فى النشرة ولا ده تعديل خاص بالعيادة او المستشفى»

So a clinic may:

* **adopt a label** the catalogue quotes (``default`` or ``other``) — its
  ceiling becomes that label's; or
* **write its own** (``own``) — and then it must say which of two things
  happened: **the label changed** (a newer leaflet than the one quoted), or
  **this is the clinic's or hospital's own decision**. Both need words.

Every choice is signed and dated on the brand, and written to the activity
log; once a clinic has chosen, re-seeding the catalogue leaves the ceiling
alone (:func:`app.utils.vaccines._fill_brand_facts`).
"""
import json
import os
from datetime import datetime

CHOICES = ("default", "other", "own")
#: Why a ceiling is what it is. ``adopted`` is set by the program when a
#: quoted label is chosen; the other two are the person's answer.
KINDS = ("adopted", "label_changed", "clinic_own")
OWN_KINDS = ("label_changed", "clinic_own")

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data",
                          "egypt_vaccines.json")


class LabelChoiceError(ValueError):
    """Said to the person; nothing is saved. Carries a translation key."""


def days_through(years):
    """«through N years of age» — up to the day before birthday N+1, the way
    the catalogue already writes Priorix Tetra («up to 12 inclusive»)."""
    return int((years + 1) * 365.25 + 0.5)


def age_words(days):
    """``days`` as the age it closes at — «56 سنة», «5 شهور و2 أسبوع»."""
    from app.i18n import t

    if not days:
        return None
    years = int(days / 365.25)
    rest = days - years * 365.25
    months = int(rest / 30.4375)
    weeks = int((rest - months * 30.4375) / 7)
    parts = []
    if years:
        parts.append(t("vlabel.n_years", n=years))
    if months:
        parts.append(t("vlabel.n_months", n=months))
    if weeks and not years:
        parts.append(t("vlabel.n_weeks", n=weeks))
    return t("vlabel.and").join(parts) or t("vlabel.n_weeks", n=days // 7)


def _catalogue():
    from app.utils.request_cache import remember

    def load():
        with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
            data = json.load(fh)
        return {(v["code"], b["name"]): b.get("label_age")
                for v in data["vaccines"] for b in v["brands"]
                if b.get("label_age")}

    return remember("vaccines:label_age", load)


def labels_for(brand):
    """The labels the catalogue quotes for this brand, default first.

    Each is ``{"key", "label", "url", "quote", "upper_days", "read_on"}``.
    Empty when the label was never read (the gaps are named in
    ``tests/test_each_brand_says_its_own_age.py``)."""
    if brand is None or brand.vaccine is None:
        return []
    found = _catalogue().get((brand.vaccine.code, brand.name))
    if not found:
        return []
    out = [{"key": "default", "label": found["label"], "url": found["url"],
            "quote": found["quote"], "upper_days": found.get("upper_days"),
            "read_on": found.get("read_on"), "note": found.get("note"),
            "before": age_words(found.get("upper_days"))}]
    other = found.get("other_label")
    if other:
        out.append({"key": "other", "label": other["label"],
                    "url": other["url"], "quote": other["quote"],
                    "upper_days": other.get("upper_days"),
                    "read_on": found.get("read_on"),
                    "before": age_words(other.get("upper_days"))})
    return out


def state(brand):
    """What the brand follows now, for the screen."""
    labels = labels_for(brand)
    choice = brand.age_label_choice or ("default" if labels else None)
    return {"labels": labels, "choice": choice,
            "decided": bool(brand.age_label_choice),
            "kind": brand.age_change_kind, "note": brand.age_change_note,
            "by": brand.age_changed_by, "at": brand.age_changed_at,
            "ceiling": brand.max_age_final_dose_days,
            "before": age_words(brand.max_age_final_dose_days),
            "disagree": len({lb["upper_days"] for lb in labels}) > 1}


def choose(brand, form, user=None, at=None):
    """Apply the clinic's choice from the form. Returns the brand.

    ``form`` carries ``choice`` (default/other/own), and for ``own`` an
    upper age in whole years (``years``, blank = no upper age), ``kind``
    (label_changed / clinic_own) and ``note``.
    """
    choice = (form.get("choice") or "").strip()
    if choice not in CHOICES:
        raise LabelChoiceError("vlabel.err_choice")
    note = (form.get("note") or "").strip()[:255] or None
    if choice in ("default", "other"):
        label = next((lb for lb in labels_for(brand) if lb["key"] == choice),
                     None)
        if label is None:
            raise LabelChoiceError("vlabel.err_choice")
        ceiling, kind = label["upper_days"], "adopted"
    else:
        kind = (form.get("kind") or "").strip()
        if kind not in OWN_KINDS:
            # The one question the owner asked to be put every time.
            raise LabelChoiceError("vlabel.err_kind")
        if not note:
            raise LabelChoiceError("vlabel.err_note")
        raw = (form.get("years") or "").strip()
        if raw:
            try:
                years = int(raw)
            except ValueError:
                raise LabelChoiceError("vlabel.err_years") from None
            if not 0 <= years <= 120:
                raise LabelChoiceError("vlabel.err_years")
            ceiling = days_through(years)
        else:
            ceiling = None            # «no upper age», said on purpose
    brand.max_age_final_dose_days = ceiling
    brand.age_label_choice = choice
    brand.age_change_kind = kind
    brand.age_change_note = note
    brand.age_changed_by = getattr(user, "id", None)
    brand.age_changed_at = at or datetime.utcnow()
    return brand
