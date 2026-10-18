"""The doctor's panel templates (DOCTOR_EASE_PLAN.md أ-٣) — see
``models/panel_template.py``."""
import json

from app.extensions import db
from app.utils import panels


class TemplateError(ValueError):
    """A refusal with a locale key (``panel_tpl.err_<key>``)."""


def _clean(key, answers):
    """Only the panel's own choice fields, answers it still offers, and only
    where the field applies (``show_if``)."""
    fields = panels.field_map(key)
    out = {}
    for code, value in (answers or {}).items():
        f = fields.get(code)
        value = (value or "").strip() if isinstance(value, str) else ""
        if f is None or f.get("type") != "choice" or value not in f.get("options", []):
            continue
        out[code] = value
    return {c: v for c, v in out.items() if panels.shown(fields[c], out)}


def for_doctor(doctor, key):
    """The doctor's own templates for this panel, then the shared ones."""
    from app.models import PanelTemplate

    rows = (PanelTemplate.query.filter(PanelTemplate.panel_key == key)
            .filter(db.or_(PanelTemplate.doctor_id == doctor.id,
                           PanelTemplate.is_shared.is_(True)))
            .order_by((PanelTemplate.doctor_id != doctor.id), PanelTemplate.use_count.desc(),
                      PanelTemplate.name).all())
    return rows


def values(row):
    """What a template fills now — its answers the panel still offers."""
    try:
        raw = json.loads(row.values or "{}")
    except ValueError:
        raw = {}
    return _clean(row.panel_key, raw)


def dropped(row):
    """How many of its answers the panel no longer offers."""
    try:
        raw = json.loads(row.values or "{}")
    except ValueError:
        raw = {}
    return max(0, len(raw) - len(values(row)))


def save(doctor, key, name, answers, shared=False):
    from app.models import PanelTemplate

    if panels.panel(key) is None:
        raise TemplateError("panel")
    name = (name or "").strip()[:80]
    if not name:
        raise TemplateError("name")
    clean = _clean(key, answers)
    if not clean:
        raise TemplateError("empty")
    row = PanelTemplate.query.filter_by(doctor_id=doctor.id, panel_key=key, name=name).first()
    if row is None:
        row = PanelTemplate(doctor_id=doctor.id, panel_key=key, name=name)
        db.session.add(row)
    row.values = json.dumps(clean, ensure_ascii=False)
    row.is_shared = bool(shared)
    db.session.flush()
    return row


def mine(doctor):
    from app.models import PanelTemplate

    return (PanelTemplate.query.filter_by(doctor_id=doctor.id)
            .order_by(PanelTemplate.panel_key, PanelTemplate.name).all())


def used(ids, doctor):
    """Count a use for each template id the visit was filled from."""
    from app.models import PanelTemplate

    for tid in ids:
        row = db.session.get(PanelTemplate, tid)
        if row is not None and (row.doctor_id == doctor.id or row.is_shared):
            row.use_count = (row.use_count or 0) + 1


__all__ = ["TemplateError", "dropped", "for_doctor", "mine", "save", "used", "values"]
