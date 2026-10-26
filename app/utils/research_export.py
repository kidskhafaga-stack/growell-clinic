"""The research export — a study's data with no child named in it.

HOSPITAL_PLAN.md ٥‑د ت-٧: *«تختار مجموعة («تحت سنتين، التهاب شعيبات، ٢٠٢٥»)،
وتطلع Excel أو CSV من غير أسماء: كود بدل الاسم، والسن وقت الحالة بدل تاريخ
الميلاد، ومعاها ملف بيشرح كل عمود.»*

**Only for a protocol the committee approved, while its approval holds**
(`may_export`). And whose children:

* **participants** — the children enrolled with their guardian's research
  consent and not withdrawn. Every approved protocol may read these.
* **records** — every child the filters find, for a review of past records.
  Only when the committee allowed it (`ResearchProtocol.record_review`).

**What leaves, and what never does.** One row per visit in the range: a code
for the child, sex, age in months at the visit, the visit's year, the days
since the child's first visit in the export (so a course can be followed
without a date), the diagnoses (code and title), the measurements, and the
medicines by name. Never: a name, a file number, a national number, a phone,
an address, a date of birth, a visit date, and **no free text** — a
complaint or a note can carry a name, a street, a school.

**The code** is an HMAC of the protocol and the child under the program's
secret key: the same child has the same code in every export of the same
study, a different one in another study, and it cannot be turned back into a
file without the key — which never leaves the clinic.

Every export is recorded (`ResearchExport`) with who, when, which protocol,
the filters, and how many children and rows.
"""
import csv
import hashlib
import hmac
import io
import json
import zipfile
from datetime import date, datetime

from flask import current_app

from app.extensions import db

PARTICIPANTS, RECORDS = "participants", "records"

#: The columns, in order: (name, Arabic, English, kind, unit).
CODEBOOK = (
    ("study_code", "كود الطفل في الدراسة (ثابت جوه البروتوكول، مش بيرجع لملفه)",
     "The child's code in this study (stable within the protocol, not reversible)", "text", ""),
    ("sex", "النوع: M ذكر، F أنثى", "Sex: M male, F female", "category", ""),
    ("age_months", "السن بالشهور يوم الزيارة", "Age in months on the day of the visit", "integer", "months"),
    ("visit_year", "سنة الزيارة", "Year of the visit", "integer", ""),
    ("day_of_course", "عدد الأيام من أول زيارة للطفل في التصدير ده",
     "Days since the child's first visit in this export", "integer", "days"),
    ("visit_kind", "نوع الزيارة (عيادة، طوارئ، متابعة عن بعد…)",
     "Kind of visit (clinic, emergency, remote follow-up…)", "category", ""),
    ("dx_codes", "أكواد التشخيص (ICD) مفصولة بـ ;", "Diagnosis codes (ICD), separated by ;", "text", ""),
    ("dx_titles", "أسماء التشخيص بالإنجليزي مفصولة بـ ;", "Diagnosis titles (English), separated by ;", "text", ""),
    ("weight_kg", "الوزن", "Weight", "decimal", "kg"),
    ("height_cm", "الطول", "Length / height", "decimal", "cm"),
    ("head_circ_cm", "محيط الرأس", "Head circumference", "decimal", "cm"),
    ("temperature_c", "الحرارة", "Temperature", "decimal", "°C"),
    ("pulse_bpm", "النبض", "Pulse", "integer", "beats/min"),
    ("resp_rate", "التنفس", "Respiratory rate", "integer", "breaths/min"),
    ("spo2", "تشبع الأكسجين", "Oxygen saturation", "integer", "%"),
    ("medicines", "الأدوية المكتوبة في الزيارة مفصولة بـ ;", "Medicines prescribed at the visit, separated by ;", "text", ""),
)
COLUMNS = tuple(c[0] for c in CODEBOOK)


class ExportRefused(Exception):
    """Why this export cannot be made — a key the screen says in words."""


def may_export(protocol, today=None):
    """``None`` when the protocol may be exported, else the reason."""
    today = today or date.today()
    if protocol.state != "approved" or protocol.approved_on is None:
        return "not_approved"
    if protocol.valid_until is not None and protocol.valid_until < today:
        return "lapsed"
    return None


def study_code(protocol_id, patient_id):
    """The child's code in this study — stable, not reversible without the
    clinic's secret key."""
    key = (current_app.config.get("SECRET_KEY") or "").encode("utf-8")
    digest = hmac.new(key, f"research:{protocol_id}:{patient_id}".encode(),
                      hashlib.sha256).hexdigest()
    return f"S{protocol_id}-{digest[:10].upper()}"


def _months(born, on):
    if not born or not on:
        return None
    months = (on.year - born.year) * 12 + (on.month - born.month)
    if on.day < born.day:
        months -= 1
    return max(months, 0)


def clean_filters(raw):
    """What the screen sent, as filters: ages in months, a diagnosis (an ICD
    code's start or a word of the title), and a range of years."""
    def number(key):
        value = (raw.get(key) or "").strip()
        return int(value) if value.isdigit() else None

    out = {"age_from": number("age_from"), "age_to": number("age_to"),
           "year_from": number("year_from"), "year_to": number("year_to"),
           "dx": (raw.get("dx") or "").strip()[:60] or None}
    return {k: v for k, v in out.items() if v is not None}


def _cohort_ids(protocol, mode):
    from app.models import ResearchParticipant

    if mode == PARTICIPANTS:
        return {p.patient_id for p in ResearchParticipant.query.filter_by(
            protocol_id=protocol.id).filter(ResearchParticipant.withdrawn_on.is_(None))}
    return None                         # records: every child the filters find


def _visits(protocol, mode, filters):
    from sqlalchemy.orm import selectinload

    from app.models import Diagnosis, Patient, Visit

    query = (Visit.query.join(Patient, Visit.patient_id == Patient.id)
             .options(selectinload(Visit.patient), selectinload(Visit.vitals),
                      selectinload(Visit.diagnoses)))
    ids = _cohort_ids(protocol, mode)
    if ids is not None:
        if not ids:
            return []
        query = query.filter(Visit.patient_id.in_(ids))
    if filters.get("year_from"):
        query = query.filter(Visit.visit_date >= date(filters["year_from"], 1, 1))
    if filters.get("year_to"):
        query = query.filter(Visit.visit_date <= date(filters["year_to"], 12, 31))
    if filters.get("dx"):
        word = filters["dx"]
        query = query.filter(Visit.id.in_(
            db.session.query(Diagnosis.visit_id).filter(db.or_(
                Diagnosis.code.ilike(f"{word}%"), Diagnosis.title.ilike(f"%{word}%"),
                Diagnosis.title_en.ilike(f"%{word}%")))))
    out = []
    for visit in query.order_by(Visit.patient_id, Visit.visit_date, Visit.id):
        age = _months(visit.patient.date_of_birth, visit.visit_date)
        if filters.get("age_from") is not None and (age is None or age < filters["age_from"]):
            continue
        if filters.get("age_to") is not None and (age is None or age > filters["age_to"]):
            continue
        out.append((visit, age))
    return out


def _medicines(visit_ids):
    """``{visit_id: [name, …]}`` — the medicine's generic name where the
    catalogue knows it, the name as written otherwise. One query."""
    from sqlalchemy.orm import selectinload

    from app.models import Prescription, PrescriptionItem

    if not visit_ids:
        return {}
    out = {}
    rows = (Prescription.query.options(selectinload(Prescription.items)
                                       .selectinload(PrescriptionItem.drug))
            .filter(Prescription.visit_id.in_(visit_ids)).all())
    for rx in rows:
        for item in rx.items:
            drug = getattr(item, "drug", None)
            name = (getattr(drug, "generic_name", None) or item.drug_name or "").strip()
            if name:
                out.setdefault(rx.visit_id, []).append(name)
    return out


def _figure(value):
    if value is None:
        return ""
    return f"{value:g}" if isinstance(value, float) else str(value)


def rows_for(protocol, mode, filters):
    """``(rows, children)`` — the data, one dict per visit, in COLUMNS."""
    visits = _visits(protocol, mode, filters)
    medicines = _medicines([v.id for v, _ in visits])
    first = {}
    rows = []
    for visit, age in visits:
        start = first.setdefault(visit.patient_id, visit.visit_date)
        vit = visit.vitals
        rows.append({
            "study_code": study_code(protocol.id, visit.patient_id),
            "sex": {"male": "M", "female": "F"}.get(visit.patient.gender or "", ""),
            "age_months": "" if age is None else age,
            "visit_year": visit.visit_date.year if visit.visit_date else "",
            "day_of_course": (visit.visit_date - start).days if visit.visit_date and start else "",
            "visit_kind": visit.channel or "",
            "dx_codes": ";".join(d.code for d in visit.diagnoses if d.code),
            "dx_titles": ";".join((d.title_en or "").strip() for d in visit.diagnoses
                                  if (d.title_en or "").strip()),
            "weight_kg": _figure(vit.weight_kg) if vit else "",
            "height_cm": _figure(vit.height_cm) if vit else "",
            "head_circ_cm": _figure(vit.head_circ_cm) if vit else "",
            "temperature_c": _figure(vit.temperature_c) if vit else "",
            "pulse_bpm": _figure(vit.pulse_bpm) if vit else "",
            "resp_rate": _figure(vit.resp_rate) if vit else "",
            "spo2": _figure(vit.spo2) if vit else "",
            "medicines": ";".join(medicines.get(visit.id, [])),
        })
    return rows, len(first)


def _csv(rows, header):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    # A BOM, so Excel opens Arabic as Arabic; R and SPSS read it as UTF-8.
    return "﻿" + out.getvalue()


def build(protocol, user, mode, raw_filters, today=None):
    """The export as a zip (``bytes``) and its record. Raises
    :class:`ExportRefused` with the reason when it may not be made."""
    from app.models import ActivityLog, ResearchExport

    reason = may_export(protocol, today)
    if reason:
        raise ExportRefused(reason)
    if mode not in (PARTICIPANTS, RECORDS):
        raise ExportRefused("bad_mode")
    if mode == RECORDS and not protocol.record_review:
        raise ExportRefused("no_record_review")
    filters = clean_filters(raw_filters)
    rows, children = rows_for(protocol, mode, filters)
    if not rows:
        raise ExportRefused("nobody")

    data = _csv(([r[c] for c in COLUMNS] for r in rows), COLUMNS)
    codebook = _csv(([name, ar, en, kind, unit] for name, ar, en, kind, unit in CODEBOOK),
                    ("column", "meaning_ar", "meaning_en", "type", "unit"))
    readme = {
        "protocol": protocol.title, "rec_reference": protocol.rec_reference,
        "approved_on": protocol.approved_on.isoformat() if protocol.approved_on else None,
        "valid_until": protocol.valid_until.isoformat() if protocol.valid_until else None,
        "mode": mode, "filters": filters, "children": children, "rows": len(rows),
        "exported_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "no_identifiers": ["name", "file number", "national number", "phone",
                           "address", "date of birth", "visit date", "free text"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.csv", data)
        zf.writestr("codebook.csv", codebook)
        zf.writestr("about.json", json.dumps(readme, ensure_ascii=False, indent=2))

    record = ResearchExport(protocol_id=protocol.id, user_id=user.id, mode=mode,
                            filters=filters, children=children, rows=len(rows))
    db.session.add(record)
    ActivityLog.record("research.export", user_id=user.id, entity="research_protocol",
                       entity_id=protocol.id,
                       detail=f"{mode} children={children} rows={len(rows)}")
    db.session.commit()
    return buffer.getvalue(), record


def may_use(protocol, user):
    """The investigator on the protocol, or whoever runs the clinic."""
    return bool(user and (user.is_admin or user.id == protocol.investigator_id))
