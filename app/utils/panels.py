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
    """Which of their panels opens first — **or none, which is an answer.**

    A neurologist who works only neurology opens that screen forty times a
    day; making them pass through anything else first is forty clicks, so
    they say so once and the screen remembers. There is no "general" panel to
    default to — the complaint, the examination and the vitals are the screen
    itself and never go away.

    And it used to fall back to the first panel they work, which quietly
    turned *"I see newborns sometimes"* into *"open every visit on newborn
    care"*. Those are different statements, and the doctor is the one who
    knows which they meant. Empty means the visit screen opens as it does for
    everybody else, with the panel there to be opened when the child in front
    of them needs it.
    """
    mine = for_doctor(doctor)
    if not mine:
        return ""
    chosen = (getattr(doctor, "specialty_panel", None) or "").strip()
    return chosen if chosen in mine else ""


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


def conditions_for(key, lang="ar"):
    """``[{code, label}]`` — the conditions this specialty follows long-term.

    Names only. **No ICD code is attached here, and that is a decision rather
    than an omission.**

    The obvious shortcut is to look each condition up in the loaded ICD table
    and store what comes back. It was tried, and what comes back is wrong often
    enough to be dangerous: "Type 1 diabetes mellitus" resolves to `E10.10`,
    which is type 1 *with ketoacidosis*, not the unspecified `E10.9`;
    "Epilepsy" resolves to a specific localisation-related variant rather than
    `G40.909`; and coeliac disease, sickle cell disease and iron deficiency
    anaemia resolve to nothing at all, because the bundled table is the US
    clinical modification and spells them the other way.

    A wrong code on a child's problem list is worse than no code: it is a
    clinical claim nobody made, and it travels — into reports, into insurance,
    into the next doctor's reading of the file. So the panel offers the name
    and the doctor attaches the code through the ICD search already sitting in
    the same form, which knows about the spelling.
    """
    meta = panel(key) or {}
    field = "label_en" if lang == "en" else "label_ar"
    return [{"code": row["code"],
             "label": row.get(field) or row.get("label_ar"),
             "label_ar": row.get("label_ar"),
             "label_en": row.get("label_en")}
            for row in meta.get("conditions") or []]


def problems_already_on(patient_id, keys):
    """The condition codes from these panels that are already on the file.

    Matched on the stored Arabic title, which is what the chip writes, so a
    condition added by pressing the chip is recognised and one typed by hand
    in different words is not. That asymmetry is deliberate: the alternative is
    fuzzy matching a doctor's free text against a fixed list, and a chip that
    greyed itself out because it *guessed* the child already had asthma would
    be hiding a real action behind a guess.

    Worst case here is an offered chip for something already on the list, and
    the problem list itself is visible on the same file — which is a smaller
    cost than a chip that quietly refuses to work.
    """
    from app.models import PatientProblem

    titles = {row.title for row in
              PatientProblem.query.filter_by(patient_id=patient_id).all()}
    if not titles:
        return set()
    found = set()
    for key in keys:
        for row in (panel(key) or {}).get("conditions") or []:
            if row.get("label_ar") in titles:
                found.add(row["code"])
    return found


def history_for(patient_id, keys):
    """``{panel_key: PanelHistory}`` for the panels this doctor works.

    Read for the whole set in one query rather than one per panel: the visit
    screen renders every panel at once, so a per-panel lookup would be twenty
    queries to draw one page.
    """
    from app.models import PanelHistory

    if not keys:
        return {}
    rows = PanelHistory.query.filter(
        PanelHistory.patient_id == patient_id,
        PanelHistory.panel.in_(list(keys))).all()
    return {row.panel: row for row in rows}


def save_history(patient_id, key, text, user_id=None):
    """Write this specialty's case history for this child, or clear it.

    One row per patient per panel, updated in place. Clearing it to blank
    **deletes the row** rather than leaving an empty one behind, so "has this
    specialty written anything" stays a question the data answers by itself.

    Returns the row, or ``None`` when it was cleared.
    """
    from app.extensions import db
    from app.models import PanelHistory

    if panel(key) is None:
        return None

    row = PanelHistory.query.filter_by(patient_id=patient_id, panel=key).first()
    text = (text or "").strip()

    if not text:
        if row is not None:
            db.session.delete(row)
        return None

    if row is None:
        row = PanelHistory(patient_id=patient_id, panel=key)
        db.session.add(row)
    row.text = text
    row.updated_by = user_id
    return row
