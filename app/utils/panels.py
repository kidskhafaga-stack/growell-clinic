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


def for_doctor(doctor):
    """The panel keys this doctor works, in catalogue order.

    A list, because a doctor works more than one: paediatrics and
    gastroenterology follow the same children, and a screen that made them
    choose would make them choose again on the next visit. Stored as a
    comma-separated string on the user — a join table for a handful of keys
    per doctor would be three files to answer a question one column answers.

    Falls back to the single `specialty_panel` a doctor already had, so
    nobody's setting is lost by this arriving.
    """
    if doctor is None:
        return []
    raw = (getattr(doctor, "specialty_panels", None) or "").strip()
    if not raw:
        one = (getattr(doctor, "specialty_panel", None) or "").strip()
        raw = one
    known = all_panels()
    seen, out = set(), []
    for key in raw.split(","):
        key = key.strip()
        if key and key in known and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def default_for_doctor(doctor):
    """Which of their panels opens first. Their own, not a house rule.

    A neurologist who works only neurology opens that screen forty times a
    day; making them pass through anything else first is forty clicks. There
    is no "general" panel to default to — the complaint, the examination and
    the vitals are the screen itself and never go away.
    """
    mine = for_doctor(doctor)
    if not mine:
        return ""
    chosen = (getattr(doctor, "specialty_panel", None) or "").strip()
    return chosen if chosen in mine else mine[0]


def for_visit(visit, doctor=None, lang="ar"):
    """The panel this visit should show: its own, else the doctor's, else none.

    Returns ``(key, panel_or_None)``. The key is returned even when nothing
    answers to it, so a screen can say "this visit was recorded under
    `cardiology`, which this clinic no longer has" rather than pretending the
    reading came from nowhere.
    """
    key = (getattr(visit, "specialty_panel", None) or "").strip()
    if not key and doctor is not None:
        key = default_for_doctor(doctor)
    return key, panel(key)


def readings(visit, key):
    """``{code: Measurement}`` already recorded on this visit for that panel."""
    from app.models import Measurement

    if not visit or not getattr(visit, "id", None):
        return {}
    rows = Measurement.query.filter_by(visit_id=visit.id).all()
    wanted = set(field_map(key))
    return {row.code: row for row in rows if row.code in wanted}


def all_readings(visit):
    """``{code: Measurement}`` for everything recorded on this visit.

    Not filtered to one panel, because the screen now renders them all: a
    reading taken under cardiology must still be in its box when the doctor
    flicks the menu back to cardiology, without a round trip to find out — and
    a visit whose panel was later put away must not appear to have lost the
    readings it took.
    """
    from app.models import Measurement

    if not visit or not getattr(visit, "id", None):
        return {}
    return {row.code: row
            for row in Measurement.query.filter_by(visit_id=visit.id).all()}


def every_panel_for(visit, vitals, lang="ar"):
    """Every panel, ready to render, so choosing one costs nothing.

    The screen used to say *"choose one and save the visit to see its
    fields"* — and it was reported exactly as it reads: *"علشان ده يظهر لازم
    ادوس حفظ وده مش منطقي"*. It is not. Picking a specialty is how a doctor
    says what this visit is about, and answering with a round trip through the
    server puts a save between the question and the fields — on a screen that
    is filled in forty times a day, and before there is anything worth saving.

    The catalogue is a small data file already read once per request, so the
    honest fix is to hand the screen all of it and let the choice be a choice.

    What the save does with them is decided in `_save_panel`: every panel this
    doctor works is written, because one visit can be a cardiology visit and a
    gastroenterology visit at once and a child is not asked to come back twice.
    A panel outside that list is ignored exactly as an invented field name is —
    the list is worked out on the server and never read from the form.

    Returns ``[{key, meta, label, reads}]`` in catalogue order.
    """
    out = []
    name_key = "name_en" if lang == "en" else "name_ar"
    for key, meta in all_panels().items():
        out.append({
            "key": key,
            "meta": meta,
            "label": meta.get(name_key) or meta.get("name_ar") or key,
            "reads": vitals_shown(meta, vitals),
        })
    return out


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


def charts_for(key):
    """The investigation codes this panel follows as a curve.

    Empty for a panel that answered the survey's chart question with its own
    measurements and with images rather than with lab tests — ophthalmology and
    dentistry both did. Empty is a real answer here and not a gap: their
    readings are already drawn, because `series.curves_for` has plotted panel
    measurements since the panels existed.
    """
    return list((panel(key) or {}).get("charts") or [])


def chart_tests(key, lang="ar"):
    """``[Investigation]`` for this panel's chart list, in the order it names.

    Resolved by code, never by name. A clinic that renames "مخزون الحديد
    (فيريتين)" to "فيريتين" keeps its curve; a lookup by text would have
    silently stopped matching the day somebody tidied the catalogue.

    A code that answers to nothing is skipped rather than raising: the
    catalogue is a clinic's to edit, and a panel losing one of its tests
    should cost that test and not the screen.
    """
    from app.models import Investigation

    codes = charts_for(key)
    if not codes:
        return []
    found = {row.code: row for row in
             Investigation.query.filter(Investigation.code.in_(codes)).all()}
    return [found[code] for code in codes if code in found]
