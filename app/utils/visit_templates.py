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


#: The longest follow-up a ready visit may name, in days.
MAX_DAYS = 365


def _tests(ids):
    """The active catalogue tests among ``ids``, in the order given."""
    from app.models import Investigation

    out, seen = [], set()
    for raw in ids or []:
        try:
            tid = int(raw)
        except (TypeError, ValueError):
            continue
        if tid in seen:
            continue
        row = db.session.get(Investigation, tid)
        if row is not None and row.is_active:
            out.append(row)
            seen.add(tid)
    return out[:20]


def _panel_template(doctor, tid):
    from app.models import PanelTemplate

    if not tid:
        return None
    try:
        row = db.session.get(PanelTemplate, int(tid))
    except (TypeError, ValueError):
        return None
    if row is None or not (row.is_shared or row.doctor_id == doctor.id):
        return None
    return row


def _days(raw):
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= MAX_DAYS else None


def as_dict(row, doctor, lang="ar"):
    preset = row.rx_preset if row.rx_preset is not None and row.rx_preset.visible_to(doctor) else None
    panel = _panel_template(doctor, row.panel_template_id)
    return {"id": row.id, "name": row.name, "cc": row.chief_complaint or "",
            "exam": row.clinical_exam or "", "plan": row.plan or "",
            "preset": preset.id if preset is not None and preset.is_active else None,
            "preset_name": preset.name if preset is not None else "",
            "tests": [{"id": x.id, "name": (x.name_ar if lang == "ar" else (x.name_en or x.name_ar))}
                      for x in _tests(row.test_ids)],
            "family": row.family_instructions or "",
            "days": row.followup_days,
            "panel_tpl": panel.id if panel is not None else None,
            "panel_tpl_name": panel.name if panel is not None else "",
            "shared": row.doctor_id != doctor.id,
            "by": row.doctor.display_name(lang) if row.doctor else ""}


def _fill(row, doctor, name, cc, exam, plan, preset_id, shared, rest=None):
    import json

    name = (name or "").strip()[:80]
    if not name:
        raise TemplateError("name")
    cc, exam, plan = ((x or "").strip()[:TEXT_MAX] for x in (cc, exam, plan))
    preset = _preset(doctor, preset_id)
    rest = rest if rest is not None else {
        "tests": row.test_ids, "family": row.family_instructions,
        "days": row.followup_days, "panel": row.panel_template_id}
    tests = _tests(rest.get("tests"))
    family = (rest.get("family") or "").strip()[:TEXT_MAX]
    days = _days(rest.get("days"))
    panel = _panel_template(doctor, rest.get("panel"))
    if not (cc or exam or plan or preset or tests or family or days or panel):
        raise TemplateError("empty")
    row.name = name
    row.chief_complaint, row.clinical_exam, row.plan = cc or None, exam or None, plan or None
    row.rx_preset_id = preset.id if preset is not None else None
    row.tests = json.dumps([x.id for x in tests]) if tests else None
    row.family_instructions = family or None
    row.followup_days = days
    row.panel_template_id = panel.id if panel is not None else None
    row.is_shared = bool(shared)


def save(doctor, name, cc, exam, plan, preset_id=None, shared=False, rest=None):
    """A new ready visit, or the doctor's one of the same name replaced.
    ``rest`` is ``{tests, family, days, panel}``."""
    from app.models import VisitTemplate

    clean = (name or "").strip()[:80]
    row = (VisitTemplate.query.filter_by(doctor_id=doctor.id, name=clean).first()
           if clean else None)
    if row is None:
        row = VisitTemplate(doctor_id=doctor.id, name=clean or "-")
    _fill(row, doctor, name, cc, exam, plan, preset_id, shared, rest or {})
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def update(row, doctor, name, cc, exam, plan, preset_id=None, shared=False, rest=None):
    """Edit one the doctor owns, in place."""
    _fill(row, doctor, name, cc, exam, plan, preset_id, shared, rest)
    db.session.flush()
    return row


def rest_of_visit(visit):
    """What a visit holds beyond its three boxes, as a ready visit keeps it:
    the catalogue tests ordered on it, what the family was told, and the
    follow-up as a number of days from the visit."""
    from app.models import VisitInvestigation

    tests = [x.investigation_id for x in VisitInvestigation.query.filter_by(visit_id=visit.id)
             .order_by(VisitInvestigation.id).all() if x.investigation_id]
    days = ((visit.followup_due - visit.visit_date).days
            if visit.followup_due and visit.visit_date else None)
    return {"tests": tests, "family": visit.followup_instructions or "", "days": days}


def apply_rest(visit, form, user):
    """With the visit's own «حفظ»: the tests the doctor kept ticked from a
    ready visit are ordered (one already on this visit is not ordered
    twice), and the follow-up and the family's instructions land **only
    where the visit has none** — the press never writes over the doctor.
    Returns ``{"tests": n, "followup": bool, "family": bool}``."""
    from datetime import timedelta

    from app.models import VisitInvestigation
    from app.models.prescription import INVESTIGATION_KINDS
    from app.utils import labs

    done = {"tests": 0, "followup": False, "family": False}
    have = {x.investigation_id for x in VisitInvestigation.query.filter_by(visit_id=visit.id).all()}
    for test in _tests(form.getlist("vt_test")):
        if test.id in have:
            continue
        db.session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=visit.patient_id, investigation_id=test.id,
            kind=test.kind if test.kind in INVESTIGATION_KINDS else "lab",
            name=test.name_ar, name_en=test.name_en or None,
            done_outside=labs.goes_outside(test), ordered_by=user.id))
        have.add(test.id)
        done["tests"] += 1
    days = _days(form.get("vt_days"))
    if days and visit.followup_due is None and visit.visit_date:
        visit.followup_due = visit.visit_date + timedelta(days=days)
        done["followup"] = True
    family = (form.get("vt_family") or "").strip()[:TEXT_MAX]
    if family and not (visit.followup_instructions or "").strip():
        visit.followup_instructions = family
        done["family"] = True
    return done


def mine(doctor):
    from app.models import VisitTemplate

    return VisitTemplate.query.filter_by(doctor_id=doctor.id).order_by(VisitTemplate.name).all()


def used(ids, doctor):
    from app.models import VisitTemplate

    for tid in ids:
        row = db.session.get(VisitTemplate, tid)
        if row is not None and row.visible_to(doctor):
            row.use_count = (row.use_count or 0) + 1


__all__ = ["TemplateError", "apply_rest", "as_dict", "for_doctor", "mine", "rest_of_visit",
           "save", "update", "used"]
