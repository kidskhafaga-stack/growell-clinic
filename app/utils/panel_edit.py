"""A clinic's own changes to a specialty panel (ASSESSMENTS_PLAN.md ق-١).

Asked by the clinic's owner: *«ليه فى شاشة التخصصات دي مش بنقدر نضيف بند فى
التخصص نشيل بند ونقل بنقيس ايه وبنقيسه ازاي بحيث البرنامج يفهمه صح؟»*

The catalogue (``data/specialty_panels.json``) is never written to. What a
clinic changes is kept beside it, one setting per panel
(``panel_edit:<key>``), and laid over it by :func:`panels.merged` — so the
visit screen, the save, the curves and the alerts all read the clinic's
version without knowing there is one.

**What may change, and what may not:**

* a field may be added, hidden, renamed, moved, and told how it is measured;
  a number its unit, its sensible range and its decimal places, whether it is
  drawn and whether it may carry an alert; a choice its options;
* a new field's **code never changes** and its **type is set once** — a
  reading taken as a number is not re-read as a word (make a new field);
* a catalogue field is **hidden, never deleted**; a field the clinic added
  is deleted only while no reading was ever taken in it, and hidden after;
* an option a reading was taken with cannot be removed — the box would no
  longer show it and the next save would erase the reading.
"""
import json

from app.extensions import db
from app.utils import panels

#: The kinds of field a clinic may add. «Yes / no» is a choice of two.
TYPES = ("number", "choice", "yesno", "date", "text")
YESNO = ["نعم", "لأ"]

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")


def _num(raw):
    raw = (raw or "").strip().translate(_DIGITS).replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return False


def change(key):
    """This clinic's changes to one panel — a fresh copy to edit."""
    return json.loads(json.dumps(panels.edits().get(key) or {}))


def _write(key, data, user, what):
    from app.models import ActivityLog, Setting
    from app.utils.request_cache import forget

    Setting.set(f"{panels.EDIT_PREFIX}:{key}", json.dumps(data, ensure_ascii=False))
    forget("panels:merged")
    ActivityLog.record(f"panels.{what}", user_id=getattr(user, "id", None),
                       entity="panel", detail=key)


def readings(code):
    """How many readings were ever taken in this field."""
    from app.models import Measurement

    return Measurement.query.filter_by(code=code).count()


def _option_used(code, option):
    from app.models import Measurement

    return Measurement.query.filter_by(code=code, value_text=option).count() > 0


def _find(key, code):
    """``(field, own)`` — the field as this clinic now has it, visible or not."""
    meta = panels.panel(key) or {}
    for f in list(meta.get("fields", [])) + list(meta.get("hidden_fields", [])):
        if f["code"] == code:
            return f, bool(f.get("own"))
    return None, False


def _options(raw):
    out = []
    for line in (raw or "").splitlines():
        line = line.strip()[:60]
        if line and line not in out:
            out.append(line)
    return out[:20]


def _read_shape(form, kind):
    """The parts of a field a clinic may set, from the edit form.
    ``(values, problem)``."""
    values = {}
    for name in ("label_ar", "label_en"):
        text = (form.get(name) or "").strip()[:120]
        if text:
            values[name] = text
    for name in ("how_ar", "how_en"):
        values[name] = (form.get(name) or "").strip()[:200]
    if kind == "number":
        values["unit"] = (form.get("unit") or "").strip()[:20]
        low, high, places = _num(form.get("min")), _num(form.get("max")), _num(form.get("decimals"))
        if any(v is False for v in (low, high, places)):
            return None, "bad_number"
        if low is not None and high is not None and low > high:
            return None, "bad_range"
        if places is not None and not (0 <= places <= 6 and places == int(places)):
            return None, "bad_decimals"
        values["min"], values["max"] = low, high
        values["decimals"] = int(places) if places is not None else None
        values["chart"] = form.get("chart") == "1"
        values["alert"] = form.get("alert") == "1"
    return values, None


def set_field(key, code, form, user):
    """Change one field. ``None`` when done, else the reason it was not."""
    field, own = _find(key, code)
    if field is None:
        return "unknown"
    kind = field.get("type")
    values, problem = _read_shape(form, kind)
    if problem:
        return problem
    if kind == "choice" and form.get("options") is not None:
        opts = _options(form.get("options"))
        if len(opts) < 2:
            return "few_options"
        gone = [o for o in field.get("options") or [] if o not in opts]
        if any(_option_used(code, o) for o in gone):
            return "option_used"
        values["options"] = opts
    data = change(key)
    if own:
        for row in data.get("added") or []:
            if row["code"] == code:
                row.update(values)
    else:
        data.setdefault("fields", {}).setdefault(code, {}).update(values)
    _write(key, data, user, "field")
    return None


def add_field(key, form, user):
    """A field of the clinic's own. ``(code, None)`` or ``(None, reason)``."""
    if panels.panel(key) is None:
        return None, "unknown"
    kind = (form.get("type") or "").strip()
    if kind not in TYPES:
        return None, "bad_type"
    if not (form.get("label_ar") or "").strip():
        return None, "no_label"
    stored = "choice" if kind == "yesno" else kind
    values, problem = _read_shape(form, stored)
    if problem:
        return None, problem
    if kind == "yesno":
        values["options"] = list(YESNO)
    elif kind == "choice":
        opts = _options(form.get("options"))
        if len(opts) < 2:
            return None, "few_options"
        values["options"] = opts
    data = change(key)
    n = int(data.get("next") or 1)
    taken = set(panels.field_labels())
    code = f"c_{key}_{n}"
    while code in taken:
        n += 1
        code = f"c_{key}_{n}"
    data["next"] = n + 1
    row = {"code": code, "type": stored, "label_en": values.get("label_en") or ""}
    row.update(values)
    if stored == "number":
        row.setdefault("chart", True)
    data.setdefault("added", []).append(row)
    _write(key, data, user, "field_add")
    return code, None


def hide(key, code, user):
    field, _own = _find(key, code)
    if field is None:
        return "unknown"
    data = change(key)
    hidden = data.setdefault("hidden", [])
    if code not in hidden:
        hidden.append(code)
    _write(key, data, user, "field_hide")
    return None


def show(key, code, user):
    data = change(key)
    if code not in (data.get("hidden") or []):
        return "unknown"
    data["hidden"] = [c for c in data["hidden"] if c != code]
    _write(key, data, user, "field_show")
    return None


def remove(key, code, user):
    """A field the clinic added: gone while it holds no reading, hidden
    after — a reading on a child's file keeps its name."""
    field, own = _find(key, code)
    if field is None or not own:
        return "unknown"
    if readings(code):
        return hide(key, code, user) or "kept_hidden"
    data = change(key)
    data["added"] = [r for r in data.get("added") or [] if r["code"] != code]
    data["hidden"] = [c for c in data.get("hidden") or [] if c != code]
    data["order"] = [c for c in data.get("order") or [] if c != code]
    data.get("fields", {}).pop(code, None)
    _write(key, data, user, "field_remove")
    return None


def move(key, code, step, user):
    """One place up (``-1``) or down (``1``) among the fields shown with it
    — the yes/no symptoms among themselves, the rest among themselves."""
    meta = panels.panel(key) or {}
    every = [f["code"] for f in list(meta.get("fields", [])) + list(meta.get("hidden_fields", []))]
    shown = meta.get("fields", [])
    field = next((f for f in shown if f["code"] == code), None)
    if field is None or step not in (-1, 1):
        return "unknown"
    flag = field.get("type") == "flag"
    same = [f["code"] for f in shown if (f.get("type") == "flag") == flag]
    i = same.index(code)
    j = i + step
    if not 0 <= j < len(same):
        return None
    other = same[j]
    a, b = every.index(code), every.index(other)
    every[a], every[b] = every[b], every[a]
    data = change(key)
    data["order"] = every
    _write(key, data, user, "field_move")
    return None


def reset(key, user):
    """Back to the catalogue. A field of the clinic's own that holds
    readings stays, hidden; one that holds none goes."""
    data = change(key)
    kept = [r for r in data.get("added") or [] if readings(r["code"])]
    fresh = {"next": data.get("next") or 1} if kept or data.get("next") else {}
    if kept:
        fresh["added"] = kept
        fresh["hidden"] = [r["code"] for r in kept]
    _write(key, fresh, user, "reset")
    return None


def is_edited(key):
    data = panels.edits().get(key) or {}
    return bool(data.get("fields") or data.get("hidden") or data.get("order")
                or data.get("added"))

