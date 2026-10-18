"""Ready visits for common complaints (DOCTOR_EASE_PLAN.md ب-١) — see
``models/visit_template.py``."""
from app.extensions import db

TEXT_MAX = 4000


class TemplateError(ValueError):
    """A refusal with a locale key (``visit_tpl.err_<key>``)."""


def for_doctor(doctor):
    """The doctor's own templates first, then the shared ones; most used
    first within each."""
    from app.models import VisitTemplate

    return (VisitTemplate.query
            .filter(db.or_(VisitTemplate.doctor_id == doctor.id,
                           VisitTemplate.is_shared.is_(True)))
            .order_by((VisitTemplate.doctor_id != doctor.id), VisitTemplate.use_count.desc(),
                      VisitTemplate.name).all())


def _preset(doctor, preset_id):
    from app.models import RxPreset

    if not preset_id:
        return None
    row = db.session.get(RxPreset, preset_id)
    return row if row is not None and row.is_active and row.visible_to(doctor) else None


def as_dict(row, doctor, lang="ar"):
    preset = row.rx_preset if row.rx_preset is not None and row.rx_preset.visible_to(doctor) else None
    return {"id": row.id, "name": row.name, "cc": row.chief_complaint or "",
            "exam": row.clinical_exam or "", "plan": row.plan or "",
            "preset": preset.id if preset is not None and preset.is_active else None,
            "preset_name": preset.name if preset is not None else "",
            "shared": row.doctor_id != doctor.id,
            "by": row.doctor.display_name(lang) if row.doctor else ""}


def _fill(row, doctor, name, cc, exam, plan, preset_id, shared):
    name = (name or "").strip()[:80]
    if not name:
        raise TemplateError("name")
    cc, exam, plan = ((x or "").strip()[:TEXT_MAX] for x in (cc, exam, plan))
    preset = _preset(doctor, preset_id)
    if not (cc or exam or plan or preset):
        raise TemplateError("empty")
    row.name = name
    row.chief_complaint, row.clinical_exam, row.plan = cc or None, exam or None, plan or None
    row.rx_preset_id = preset.id if preset is not None else None
    row.is_shared = bool(shared)


def save(doctor, name, cc, exam, plan, preset_id=None, shared=False):
    """A new ready visit, or the doctor's one of the same name replaced."""
    from app.models import VisitTemplate

    clean = (name or "").strip()[:80]
    row = (VisitTemplate.query.filter_by(doctor_id=doctor.id, name=clean).first()
           if clean else None)
    if row is None:
        row = VisitTemplate(doctor_id=doctor.id, name=clean or "-")
    _fill(row, doctor, name, cc, exam, plan, preset_id, shared)
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def update(row, doctor, name, cc, exam, plan, preset_id=None, shared=False):
    """Edit one the doctor owns, in place."""
    _fill(row, doctor, name, cc, exam, plan, preset_id, shared)
    db.session.flush()
    return row


def mine(doctor):
    from app.models import VisitTemplate

    return VisitTemplate.query.filter_by(doctor_id=doctor.id).order_by(VisitTemplate.name).all()


def used(ids, doctor):
    from app.models import VisitTemplate

    for tid in ids:
        row = db.session.get(VisitTemplate, tid)
        if row is not None and row.visible_to(doctor):
            row.use_count = (row.use_count or 0) + 1


__all__ = ["TemplateError", "as_dict", "for_doctor", "mine", "save", "update", "used"]
