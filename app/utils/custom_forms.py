"""The clinic's own forms: drawing them, filling them, counting them.

``FORM_BUILDER_PLAN.md``. Every rule is here; the screens read and hand over.

**Designing** (``forms_design``): add a field of a kind, word it in Arabic
and English, make it required or not, give a number its unit and sensible
range, give a choice its options, move it up or down, hide it. A field's key
and kind are fixed once made; a field that has answers is hidden rather than
deleted, and an option that was chosen stays. Each change raises the form's
version, and each entry keeps the shape it was filled on.

**Filling**: by the form's audience — ``clinical`` for whoever reads the
medical file, ``desk`` for whoever opens patients. Required boxes, numbers
in range, dates and options that exist are checked; nothing is saved
otherwise.

**Counting**: per field, over a period — yes/no, each option, the numbers'
count, mean, least and greatest, how many wrote text.
"""
from datetime import date, datetime

from app.extensions import db
from app.models.custom_form import (AUDIENCES, PLACES, TYPES, CustomForm,
                                    FormEntry)

ANSWERED_TYPES = tuple(t for t in TYPES if t != "heading")
CHOICE_TYPES = ("choice", "multi")
MAX_FIELDS = 80
MAX_OPTIONS = 30
MAX_TEXT = {"text": 300, "textarea": 4000}


class FormError(ValueError):
    """Said to the person; nothing is saved. Carries a translation key (and
    the field's label where it is about one)."""

    def __init__(self, key, field=None):
        super().__init__(key)
        self.key = key
        self.field = field


# ---------------------------------------------------------- who may ----
def places_offered():
    """Where a form may be filled here — the stay only where the wards are."""
    from app.utils.facility import module_enabled

    return tuple(p for p in PLACES
                 if p != "admission" or module_enabled("beds"))


def may_design(user):
    return bool(user and user.is_authenticated and user.can("forms_design"))


def may_fill(user, form):
    if not (user and user.is_authenticated) or form is None:
        return False
    if form.audience == "clinical":
        return user.can("patient_medical")
    return user.can_access("patients")


def forms_for(place, user):
    """The active forms filled at this place that this person may fill."""
    if place not in places_offered():
        return []
    rows = (CustomForm.query.filter_by(place=place, is_active=True)
            .order_by(CustomForm.name_ar).all())
    return [f for f in rows if may_fill(user, f)]


# ----------------------------------------------------------- design ----
def _text(value, limit):
    return (value or "").strip()[:limit] or None


def _number(value):
    raw = (value or "").strip() if isinstance(value, str) else value
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise FormError("forms.err_number") from None


def _options(raw_lines_ar, raw_lines_en, old=None, current=None):
    """Options from one-per-line boxes.

    An option keeps its key by its Arabic words, wherever it moves in the
    list; a new one gets a key never used before on this field; an option
    somebody chose may be reworded in English but not taken out — the
    answers on file are stored by its key, and they must keep meaning what
    they meant."""
    ar = [x.strip() for x in (raw_lines_ar or "").splitlines() if x.strip()]
    en = [x.strip() for x in (raw_lines_en or "").splitlines()]
    current = current or []
    by_words = {o["ar"]: o["key"] for o in current}
    taken = [int(o["key"][1:]) for o in current
             if o["key"][1:].isdigit()]
    next_n = max(taken, default=0) + 1
    out, seen = [], set()
    for i, words in enumerate(ar[:MAX_OPTIONS]):
        words = words[:200]
        if words in seen:
            continue
        seen.add(words)
        key = by_words.get(words)
        if key is None:
            key = f"o{next_n}"
            next_n += 1
        out.append({"key": key, "ar": words,
                    "en": (en[i] if i < len(en) else "")[:200] or None})
    if old:
        if used_options(old) - {o["key"] for o in out}:
            raise FormError("forms.err_option_used")
    return out


def new_form(form, user=None):
    name = _text(form.get("name_ar"), 160)
    if not name:
        raise FormError("forms.err_name")
    place = (form.get("place") or "patient").strip()
    if place not in places_offered():
        raise FormError("forms.err_place")
    audience = (form.get("audience") or "clinical").strip()
    if audience not in AUDIENCES:
        raise FormError("forms.err_audience")
    row = CustomForm(name_ar=name, name_en=_text(form.get("name_en"), 160),
                     note=_text(form.get("note"), 500), place=place,
                     audience=audience, created_by=getattr(user, "id", None))
    row.fields = []
    db.session.add(row)
    return row


def edit_form(row, form):
    name = _text(form.get("name_ar"), 160)
    if not name:
        raise FormError("forms.err_name")
    audience = (form.get("audience") or row.audience).strip()
    if audience not in AUDIENCES:
        raise FormError("forms.err_audience")
    row.name_ar = name
    row.name_en = _text(form.get("name_en"), 160)
    row.note = _text(form.get("note"), 500)
    row.audience = audience
    # The place is fixed once entries exist: an entry made on a visit
    # would otherwise belong to a form that says it is filled on a stay.
    place = (form.get("place") or row.place).strip()
    if place != row.place:
        if row.entries.count():
            raise FormError("forms.err_place_used")
        if place not in places_offered():
            raise FormError("forms.err_place")
        row.place = place
    return row


def _bump(row, fields):
    row.fields = fields
    row.version = (row.version or 1) + 1


def _find(fields, key):
    for i, f in enumerate(fields):
        if f["key"] == key:
            return i, f
    raise FormError("forms.err_field")


def _apply(field, data):
    label = _text(data.get("label_ar"), 300)
    if not label:
        raise FormError("forms.err_label")
    field["label_ar"] = label
    field["label_en"] = _text(data.get("label_en"), 300)
    field["required"] = bool(data.get("required")) \
        and field["type"] != "heading"
    if field["type"] == "number":
        field["unit"] = _text(data.get("unit"), 20)
        field["min"] = _number(data.get("min"))
        field["max"] = _number(data.get("max"))
        if field["min"] is not None and field["max"] is not None \
                and field["min"] > field["max"]:
            raise FormError("forms.err_range")
    return field


def add_field(row, data):
    kind = (data.get("type") or "").strip()
    if kind not in TYPES:
        raise FormError("forms.err_type")
    fields = row.fields
    if len(fields) >= MAX_FIELDS:
        raise FormError("forms.err_too_many")
    field = {"key": f"f{row.next_key or 1}", "type": kind, "hidden": False}
    _apply(field, data)
    if kind in CHOICE_TYPES:
        field["options"] = _options(data.get("options_ar"),
                                    data.get("options_en"))
        if len(field["options"]) < 2:
            raise FormError("forms.err_options")
    fields.append(field)
    row.next_key = (row.next_key or 1) + 1
    _bump(row, fields)
    return field


def edit_field(row, key, data):
    fields = row.fields
    i, field = _find(fields, key)
    _apply(field, data)
    if field["type"] in CHOICE_TYPES:
        opts = _options(data.get("options_ar"), data.get("options_en"),
                        old=(row, key), current=field.get("options"))
        if len(opts) < 2:
            raise FormError("forms.err_options")
        field["options"] = opts
    fields[i] = field
    _bump(row, fields)
    return field


def move_field(row, key, step):
    fields = row.fields
    i, _f = _find(fields, key)
    j = i + (1 if step > 0 else -1)
    if 0 <= j < len(fields):
        fields[i], fields[j] = fields[j], fields[i]
        _bump(row, fields)


def hide_field(row, key, hidden=True):
    """Out of the form, or back. A field with no answers yet is removed
    outright when asked to be — nothing would be lost."""
    fields = row.fields
    i, field = _find(fields, key)
    if hidden and not answered(row, key):
        fields.pop(i)
    else:
        field["hidden"] = bool(hidden)
        fields[i] = field
    _bump(row, fields)


def answered(row, key):
    for entry in row.entries:
        value = entry.answers.get(key)
        if value not in (None, "", []):
            return True
    return False


def used_options(old):
    row, key = old
    used = set()
    for entry in row.entries:
        value = entry.answers.get(key)
        if isinstance(value, list):
            used.update(value)
        elif value:
            used.add(value)
    return used


# ------------------------------------------------------------- fill ----
def live_fields(form):
    return [f for f in form.fields if not f.get("hidden")]


def read_answers(fields, data):
    """The answers from the posted form, checked. ``data`` is a MultiDict
    (or a mapping whose ``getlist`` is absent for single values)."""
    out = {}
    for f in fields:
        if f.get("hidden") or f["type"] == "heading":
            continue
        name = f"a_{f['key']}"
        kind = f["type"]
        if kind == "multi":
            picked = data.getlist(name) if hasattr(data, "getlist") \
                else (data.get(name) or [])
            keys = {o["key"] for o in f.get("options") or []}
            value = [v for v in picked if v in keys]
            if len(value) != len(picked):
                raise FormError("forms.err_option", f)
            value = value or None
        else:
            raw = (data.get(name) or "").strip()
            value = raw or None
            if value is not None:
                if kind in MAX_TEXT:
                    value = value[:MAX_TEXT[kind]]
                elif kind == "number":
                    num = _number(value)
                    if f.get("min") is not None and num < f["min"] \
                            or f.get("max") is not None and num > f["max"]:
                        raise FormError("forms.err_out_of_range", f)
                    value = num
                elif kind == "date":
                    try:
                        value = date.fromisoformat(value).isoformat()
                    except ValueError:
                        raise FormError("forms.err_date", f) from None
                elif kind == "yesno":
                    if value not in ("yes", "no"):
                        raise FormError("forms.err_option", f)
                elif kind == "choice":
                    if value not in {o["key"] for o in f.get("options") or []}:
                        raise FormError("forms.err_option", f)
        if value is None and f.get("required"):
            raise FormError("forms.err_required", f)
        if value is not None:
            out[f["key"]] = value
    return out


def fill(form, patient, data, user=None, visit=None, admission=None):
    if not form.is_active:
        raise FormError("forms.err_closed")
    if form.place == "visit" and (visit is None
                                  or visit.patient_id != patient.id):
        raise FormError("forms.err_context")
    if form.place == "admission" and (admission is None
                                      or admission.patient_id != patient.id):
        raise FormError("forms.err_context")
    fields = form.fields
    entry = FormEntry(form_id=form.id, form_version=form.version or 1,
                      snapshot_json=form.fields_json or "[]",
                      patient_id=patient.id,
                      visit_id=getattr(visit, "id", None)
                      if form.place == "visit" else None,
                      admission_id=getattr(admission, "id", None)
                      if form.place == "admission" else None,
                      created_by=getattr(user, "id", None))
    entry.answers = read_answers(fields, data)
    db.session.add(entry)
    return entry


def amend(entry, data, user=None, at=None):
    """Correct an entry, on the shape it was filled on."""
    entry.answers = read_answers(entry.snapshot, data)
    entry.updated_by = getattr(user, "id", None)
    entry.updated_at = at or datetime.utcnow()
    return entry


def shown_value(field, value, lang="ar"):
    """An answer as words, for the screen and the print."""
    from app.i18n import t

    if value in (None, "", []):
        return ""
    kind = field.get("type")
    if kind == "yesno":
        return t("forms.yes") if value == "yes" else t("forms.no")
    if kind in CHOICE_TYPES:
        by_key = {o["key"]: o for o in field.get("options") or []}
        keys = value if isinstance(value, list) else [value]
        words = []
        for k in keys:
            o = by_key.get(k)
            if o:
                words.append((o.get("en") if lang == "en" else None)
                             or o["ar"])
        return "، ".join(words) if lang != "en" else ", ".join(words)
    if kind == "number":
        text = f"{value:g}" if isinstance(value, float) else str(value)
        return f"{text} {field.get('unit') or ''}".strip()
    return str(value)


def label(field, lang="ar"):
    return (field.get("label_en") if lang == "en" else None) \
        or field.get("label_ar") or ""


# ------------------------------------------------------------ count ----
def summary(form, start, end):
    """Entries filled between ``start`` and ``end`` (clinic dates, both
    included), counted per field on the form as it is now."""
    from app.utils.live import day_bounds

    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    rows = (form.entries.filter(FormEntry.created_at >= lo,
                                FormEntry.created_at <= hi)
            .order_by(FormEntry.created_at.desc()).all())
    per_field = []
    for f in form.fields:
        if f["type"] == "heading":
            continue
        values = [r.answers.get(f["key"]) for r in rows]
        values = [v for v in values if v not in (None, "", [])]
        item = {"field": f, "answered": len(values)}
        if f["type"] == "yesno":
            item["counts"] = {"yes": values.count("yes"),
                              "no": values.count("no")}
        elif f["type"] in CHOICE_TYPES:
            counts = {o["key"]: 0 for o in f.get("options") or []}
            for v in values:
                for k in (v if isinstance(v, list) else [v]):
                    counts[k] = counts.get(k, 0) + 1
            item["counts"] = counts
        elif f["type"] == "number":
            nums = [float(v) for v in values]
            if nums:
                item["mean"] = round(sum(nums) / len(nums), 2)
                item["least"] = min(nums)
                item["most"] = max(nums)
        per_field.append(item)
    return {"rows": rows, "total": len(rows), "fields": per_field}
