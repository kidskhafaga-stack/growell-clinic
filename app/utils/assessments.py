"""Assessments for the neurology and development specialties — ت-١.

ASSESSMENTS_PLAN.md. A form per kind of assessment (ADHD first), from the
guideline, with its source beside each part (``data/assessments.json``); the
clinic edits its own copy (`AssessmentForm`); every assessment keeps the
form it was filled on.

**The program records and adds up — it never interprets.** A tool's field
shows «meets the scale's criterion» only where the tool's own scoring
instructions set a figure (``meets``), and it says it is a screening
criterion, not a diagnosis. A commercial test carries no items and no
scoring: its boxes are copied from the publisher's report.

**Who.** Writing: anyone holding ``assessments`` (a psychologist, a speech
or occupational therapist — granted to the person, no new role) or a
doctor. Approving: a doctor. Reading: whoever may read the medical file.
"""
import copy
import json
import os
from datetime import date, datetime
from functools import lru_cache

from app.extensions import db

_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "assessments.json")
MODULE = "panels"
CAPABILITY = "assessments"
OPTION_TYPES = ("single", "multi", "checks")


class AssessmentError(ValueError):
    """A refusal with a key the screen can name (``assessment.err_<key>``)."""


# ------------------------------------------------------------ catalogue --
@lru_cache(maxsize=1)
def _catalogue():
    with open(_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def default_kinds():
    return _catalogue()["kinds"]


def default_tools():
    return _catalogue()["tools"]


def on():
    from app.utils.facility import module_enabled

    return module_enabled(MODULE)


def _row(kind):
    from app.models import AssessmentForm

    return AssessmentForm.query.filter_by(kind=kind).first()


def form_for(kind):
    """The form this clinic fills for ``kind``: its own copy, else the
    default — with every tool it names resolved into ``tool_defs``."""
    if kind not in default_kinds():
        return None
    row = _row(kind)
    form = copy.deepcopy(row.form if row is not None else default_kinds()[kind])
    # The default tools, as this clinic worded them, and its own tools —
    # kept apart so one taken off the form is never lost.
    defs = dict(copy.deepcopy(default_tools()))
    defs.update(form.get("tool_defs") or {})
    defs.update(form.get("own_tools") or {})
    section = tools_section(form)
    if section is not None:
        wanted = list(section.get("shown") or []) + list(section.get("more") or [])
        form["tool_defs"] = {k: defs[k] for k in wanted if k in defs}
    return form


def is_edited(kind):
    return _row(kind) is not None


def every_tool(form):
    """Every tool this form could use: the catalogue's and the clinic's own."""
    out = dict(default_tools())
    out.update(form.get("own_tools") or {})
    out.update(form.get("tool_defs") or {})
    return out


def tools_section(form):
    for section in form.get("sections") or []:
        if section.get("type") == "tools":
            return section
    return None


def kinds(lang="ar"):
    """``[(key, name, icon)]`` for the «new assessment» menu."""
    out = []
    for key, meta in default_kinds().items():
        form = form_for(key)
        out.append((key, form.get(f"name_{lang}") or form.get("name_ar"), form.get("icon") or "clipboard2-pulse"))
    return out


# ---------------------------------------------------------------- people --
def may_read(user):
    return bool(user and user.is_authenticated
                and (user.can("patient_medical") or user.can(CAPABILITY)))


def may_write(user):
    from app.models import User

    return bool(user and user.is_authenticated
                and (user.can(CAPABILITY) or User.sees_patients(user.role, user.is_practitioner)))


def may_approve(user):
    return bool(user and user.is_authenticated and user.role == "doctor")


def may_edit_form(user):
    return may_write(user)


# ------------------------------------------------------------ the record --
def age_on(patient, on):
    """``(years, months)`` on that day."""
    born = patient.date_of_birth
    if not born or not on:
        return None
    months = (on.year - born.year) * 12 + (on.month - born.month) - (1 if on.day < born.day else 0)
    months = max(months, 0)
    return months // 12, months % 12


def start(patient, kind, user, visit=None, on=None):
    from app.models import ActivityLog, Assessment
    from app.utils.clock import local_today

    if not may_write(user):
        raise AssessmentError("not_allowed")
    form = form_for(kind)
    if form is None:
        raise AssessmentError("no_kind")
    row = Assessment(patient_id=patient.id, visit_id=getattr(visit, "id", None),
                     kind=kind, form=form, answers={}, assessed_on=on or local_today(),
                     assessor_id=user.id)
    db.session.add(row)
    db.session.flush()
    ActivityLog.record("assessment.start", user_id=user.id, entity="assessment",
                       entity_id=row.id, detail=kind)
    return row


def _number(raw, low=None, high=None):
    raw = (raw or "").strip().replace("٫", ".")
    raw = raw.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise AssessmentError("not_a_number")
    if (low is not None and value < low) or (high is not None and value > high):
        raise AssessmentError("out_of_range")
    return int(value) if value.is_integer() else round(value, 2)


def _getlist(form, key):
    return form.getlist(key) if hasattr(form, "getlist") else (form.get(key) or [])


def read_answers(row, data):
    """The answers a posted form carries, checked against the row's own form."""
    out = {}
    for section in row.form.get("sections") or []:
        key, kind = section["key"], section.get("type")
        allowed = [o["key"] for o in section.get("options") or []]
        if kind == "single":
            value = (data.get(key) or "").strip()
            out[key] = value if value in allowed else None
        elif kind in ("multi", "checks"):
            out[key] = [v for v in _getlist(data, key) if v in allowed]
        elif kind == "text":
            out[key] = (data.get(key) or "").strip()[:4000]
        elif kind == "date":
            try:
                out[key] = date.fromisoformat((data.get(key) or "").strip()).isoformat()
            except ValueError:
                out[key] = None
        elif kind == "tools":
            tools = {}
            for tkey, tool in (row.form.get("tool_defs") or {}).items():
                if data.get(f"use_{tkey}") != "1":
                    continue
                values = {}
                for field in tool.get("fields") or []:
                    high = field.get("max") if field.get("type") == "count" else 99999
                    low = 0 if field.get("type") == "count" else -99999
                    values[field["key"]] = _number(data.get(f"t_{tkey}_{field['key']}"), low, high)
                tools[tkey] = values
            out["tools"] = tools
    return out


def save(row, data, user):
    if row.status == "approved":
        raise AssessmentError("approved")
    if not may_write(user):
        raise AssessmentError("not_allowed")
    row.answers = read_answers(row, data)
    when = (data.get("assessed_on") or "").strip()
    if when:
        try:
            row.assessed_on = date.fromisoformat(when)
        except ValueError:
            pass
    return row


def send_for_review(row, user):
    from app.models import ActivityLog

    if row.status == "approved":
        raise AssessmentError("approved")
    row.status = "review"
    ActivityLog.record("assessment.review", user_id=user.id, entity="assessment",
                       entity_id=row.id)
    return row


def approve(row, user, note=None):
    from app.models import ActivityLog

    if not may_approve(user):
        raise AssessmentError("not_a_doctor")
    if row.status == "approved":
        raise AssessmentError("approved")
    row.status, row.approved_by, row.approved_at = "approved", user.id, datetime.utcnow()
    row.doctor_note = (note or "").strip()[:4000] or None
    ActivityLog.record("assessment.approve", user_id=user.id, entity="assessment",
                       entity_id=row.id)
    return row


def waiting_for(user):
    """Assessments sent for a doctor's approval."""
    from app.models import Assessment

    if not may_approve(user):
        return []
    return (Assessment.query.filter_by(status="review")
            .order_by(Assessment.updated_at).limit(200).all())


def meets(field, value):
    return (value is not None and field.get("meets") is not None
            and value >= field["meets"])


def history(row):
    """``{(tool, field): [(date, value)]}`` from this child's approved
    assessments of the same kind before this one, and this one — the same
    tool only, never two tools on one line."""
    from app.models import Assessment

    earlier = (Assessment.query
               .filter(Assessment.patient_id == row.patient_id, Assessment.kind == row.kind,
                       Assessment.status == "approved", Assessment.id != row.id,
                       Assessment.assessed_on <= row.assessed_on)
               .order_by(Assessment.assessed_on, Assessment.id).all())
    out = {}
    for item in earlier + [row]:
        for tkey, values in ((item.answers or {}).get("tools") or {}).items():
            for fkey, value in (values or {}).items():
                if value is not None:
                    out.setdefault((tkey, fkey), []).append((item.assessed_on, value))
    return {k: v for k, v in out.items() if len(v) > 1}


def for_patient(patient_id):
    from app.models import Assessment

    return (Assessment.query.filter_by(patient_id=patient_id)
            .order_by(Assessment.assessed_on.desc(), Assessment.id.desc()).all())


# --------------------------------------------- the clinic edits the form --
def _editable(kind):
    form = form_for(kind)
    if form is None:
        raise AssessmentError("no_kind")
    return form


def _keep(kind, form, user):
    from app.models import ActivityLog, AssessmentForm

    row = _row(kind)
    if row is None:
        row = AssessmentForm(kind=kind, form=form, updated_by=user.id)
        db.session.add(row)
    else:
        row.form, row.updated_by = form, user.id
    ActivityLog.record("assessment.form_edit", user_id=user.id, entity="assessment_form",
                       detail=kind)
    return row


def _section(form, key):
    for section in form.get("sections") or []:
        if section["key"] == key:
            return section
    raise AssessmentError("no_section")


def _slug(_text, taken):
    """A key the clinic's own line keeps for ever — never reused, so an old
    assessment's answer never comes to mean a new line."""
    n = len(taken) + 1
    while f"c{n}" in taken:
        n += 1
    return f"c{n}"


def add_option(kind, section_key, label, user):
    label = (label or "").strip()[:160]
    if not label:
        raise AssessmentError("need_label")
    form = _editable(kind)
    section = _section(form, section_key)
    if section.get("type") not in OPTION_TYPES:
        raise AssessmentError("no_section")
    taken = {o["key"] for o in section.get("options") or []}
    section.setdefault("options", []).append({"key": _slug(label, taken), "ar": label, "en": label})
    return _keep(kind, form, user)


def remove_option(kind, section_key, option_key, user):
    form = _editable(kind)
    section = _section(form, section_key)
    before = len(section.get("options") or [])
    section["options"] = [o for o in section.get("options") or [] if o["key"] != option_key]
    if len(section["options"]) == before:
        raise AssessmentError("no_option")
    return _keep(kind, form, user)


def place_tool(kind, tool_key, where, user):
    """``shown`` (on the form from the start), ``more`` (one press away) or
    ``off``."""
    form = _editable(kind)
    section = tools_section(form)
    if section is None or tool_key not in every_tool(form):
        raise AssessmentError("no_tool")
    for bucket in ("shown", "more"):
        section[bucket] = [k for k in section.get(bucket) or [] if k != tool_key]
    if where in ("shown", "more"):
        section[where].append(tool_key)
    return _keep(kind, form, user)


def set_field(kind, tool_key, field_key, label, meets_raw, user):
    """A tool field's words, and the figure its scoring instructions set."""
    form = _editable(kind)
    tool = (form.get("tool_defs") or {}).get(tool_key)
    if tool is None:
        raise AssessmentError("no_tool")
    own = (form.get("own_tools") or {}).get(tool_key)
    for field in tool.get("fields") or []:
        if field["key"] == field_key:
            label = (label or "").strip()[:160]
            if label:
                field["ar"] = label
            meets_value = _number(meets_raw, 0, field.get("max") or 99999)
            if meets_value is None:
                field.pop("meets", None)
            else:
                field["meets"] = meets_value
            if own is not None:
                form["own_tools"][tool_key] = tool
            return _keep(kind, form, user)
    raise AssessmentError("no_field")


def add_tool(kind, name, lines, user):
    """A tool the clinic uses: its name, and one box per line."""
    name = (name or "").strip()[:120]
    fields = [ln.strip()[:120] for ln in (lines or "").splitlines() if ln.strip()][:12]
    if not name or not fields:
        raise AssessmentError("need_tool")
    form = _editable(kind)
    taken = set(every_tool(form))
    key = "clinic_" + _slug(name, {k[len("clinic_"):] for k in taken if k.startswith("clinic_")})
    form.setdefault("own_tools", {})[key] = form.setdefault("tool_defs", {})[key] = {
        "name_ar": name, "name_en": name, "kind": "clinic", "source": "",
        "fields": [{"key": f"f{i + 1}", "ar": label, "en": label, "type": "score"}
                   for i, label in enumerate(fields)]}
    tools_section(form).setdefault("shown", []).append(key)
    return _keep(kind, form, user)


def reset(kind, user):
    from app.models import ActivityLog

    row = _row(kind)
    if row is not None:
        db.session.delete(row)
        ActivityLog.record("assessment.form_reset", user_id=user.id,
                           entity="assessment_form", detail=kind)
