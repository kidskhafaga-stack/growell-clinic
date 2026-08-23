"""Which extra fields a visit screen shows, and where they come from.

Asked directly: *"هل هنعمل شاشة مختلفة للزيارة لو الدكتور دكتور اسنان ولو غدد
ولو رمد؟"* — and the answer is no, one screen with a panel on it.

**Why not a screen per specialty.** The file is one, and the survey's own
strongest argument is that: *"طبيب الأسنان لا يعرف أن الطفل عنده فتحة في القلب"*.
Separate screens would break the very thing it says is valuable. A child with
asthma and caries is one visit; if the dental screen is its own, the weight is
recorded twice or not at all. And the constant part is the larger part —
complaint, examination, diagnosis, plan, investigations, prescription do not
change by specialty. What changes is which measurements and which alerts.

**Whose choice it is.** Both, in an order. The panel follows the doctor by
default, because nobody opens a dropdown forty times a day. The visit can
change it, because the panel is a property of *what this visit is about* rather
than of who is typing: a cardiologist seeing a child with a cold does not want
LVEDD on the screen. The panel actually used is recorded on the visit, since
the readings taken belong to it.

**Why the doctor's `specialty` field cannot drive it.** It is free text — a
doctor has typed "طب أطفال" or "استشاري قلب أطفال" or anything else into it, and
it prints on the prescription. Matching a panel against prose would work in
testing and fail on a real clinic. So the panel is its own coded field, and the
free-text one is left alone doing the job it already has.
"""
import json
import os

from app.utils.request_cache import remember

_PATH = os.path.join(os.path.dirname(__file__), "..", "data",
                     "specialty_panels.json")


def _load():
    with open(os.path.abspath(_PATH), encoding="utf-8") as fh:
        return json.load(fh)


def catalogue():
    """The whole catalogue, read once per request."""
    return remember("panels:catalogue", _load)


def all_panels():
    """``{key: panel}`` — every panel a clinic could choose."""
    return catalogue().get("panels", {})


def panel(key):
    """One panel, or ``None`` for a key nothing answers to.

    ``None`` rather than a default, deliberately. A visit recorded under a
    panel that has since been renamed should show no panel and keep its
    readings, not silently acquire a different specialty's fields.
    """
    return all_panels().get((key or "").strip()) or None


def choices(lang="ar"):
    """``[(key, label)]`` for a menu, in catalogue order."""
    key = "name_en" if lang == "en" else "name_ar"
    return [(pid, meta.get(key) or meta.get("name_ar") or pid)
            for pid, meta in all_panels().items()]


def field_map(key):
    """``{code: field}`` for one panel — for validating what a form sent.

    A form posts field names; nothing else may be written to `measurements`
    from it. Without this a crafted request could invent a code and the file
    would carry a reading no catalogue describes.
    """
    meta = panel(key)
    return {f["code"]: f for f in (meta or {}).get("fields", [])}


def for_visit(visit, doctor=None, lang="ar"):
    """The panel this visit should show: its own, else the doctor's, else none.

    Returns ``(key, panel_or_None)``. The key is returned even when nothing
    answers to it, so a screen can say "this visit was recorded under
    `cardiology`, which this clinic no longer has" rather than pretending the
    reading came from nowhere.
    """
    key = (getattr(visit, "specialty_panel", None) or "").strip()
    if not key and doctor is not None:
        key = (getattr(doctor, "specialty_panel", None) or "").strip()
    return key, panel(key)


def readings(visit, key):
    """``{code: Measurement}`` already recorded on this visit for that panel."""
    from app.models import Measurement

    if not visit or not getattr(visit, "id", None):
        return {}
    rows = Measurement.query.filter_by(visit_id=visit.id).all()
    wanted = set(field_map(key))
    return {row.code: row for row in rows if row.code in wanted}


def vitals_shown(meta, vitals):
    """What the panel *reads* rather than asks for.

    Returns ``[(code, value)]`` for the vital signs this panel wants to see,
    skipping the ones that were never taken — a panel showing "—" against six
    empty rows is a panel that looks broken.
    """
    out = []
    for code in (meta or {}).get("reads", []):
        value = getattr(vitals, code, None) if vitals is not None else None
        if value not in (None, ""):
            out.append((code, value))
    return out
