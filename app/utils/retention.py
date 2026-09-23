"""`IMT.07` — مدة الحفظ لكل نوع مستند، وإيه اللي عدّاها، ودفتر الإتلاف.

**قارئ مش حارس.** الشاشة بتقول «٣١٢ روشتة عدّت مدة الحفظ» — وبس. ما
بتمسحش، وما بتعرضش زرار يمسح، لأن مسح سجل طبي من برنامج قرار مالوش رجوع،
والقانون اللي بيحكمه العيادة هي اللي بتسأل عنه. اللي بيتعدم فعلاً (ورق،
أفلام، نسخ على وسيط) بيتسجّل في الدفتر بإيد اللي عدمه.

**والأنواع ثابتة، مش قايمة حرة.** كل نوع مربوط بعمود التاريخ اللي بيتحسب
منه — الزيارة بتاريخها، الروشتة بتاريخها، الإقامة **بيوم خروجها** (إقامة
لسه مفتوحة ما بتعدّيش مدتها أبداً). نوع مكتوب بإيد ما يعرفش يتعدّ، ورقم
ما بيتعدّش ما يستاهلش يتعرض.
"""
from datetime import datetime, time

from sqlalchemy import case, func, null

from app.extensions import db
from app.models import RecordDestruction, RetentionRule
from app.utils.clock import local_today, to_local, to_utc

#: الأنواع، بترتيب الشاشة.
DOC_TYPES = ("visits", "prescriptions", "investigations", "consents",
             "attachments", "admissions", "invoices", "messages", "activity")

#: دفتر الإتلاف بيقبل كمان «نوع تاني» — أفلام أشعة، دفاتر ورق قديمة —
#: حاجات اتعدمت ومالهاش صف في البرنامج أصلاً.
OTHER = "other"

YEARS_MIN, YEARS_MAX = 1, 100


def _sources():
    """``{نوع: (عمود التاريخ, شروط زيادة)}``."""
    from app.models import (ActivityLog, Admission, Consent, Invoice,
                            MessageLog, PatientAttachment, Prescription,
                            Visit, VisitInvestigation)

    return {
        "visits": (Visit.visit_date, ()),
        "prescriptions": (Prescription.rx_date, ()),
        "investigations": (VisitInvestigation.created_at, ()),
        "consents": (Consent.signed_date, ()),
        "attachments": (PatientAttachment.created_at, ()),
        # الإقامة بتتحسب من يوم خروجها — والمفتوحة مالهاش مدة بتعدّي.
        "admissions": (Admission.discharged_at,
                       (Admission.discharged_at.isnot(None),)),
        "invoices": (Invoice.invoice_date, ()),
        "messages": (MessageLog.created_at, ()),
        "activity": (ActivityLog.created_at, ()),
    }


def _cutoff(column, years, today):
    """أول يوم **جوه** المدة. اللي قبله عدّاها.

    نفس الحساب بتاع الأرشفة — ٢٩ فبراير بيقع على ٢٨ في السنة اللي مش
    كبيسة، بدل ما يوقع الصفحة.
    """
    from app.utils.archiving import cutoff_date

    day = cutoff_date(years, today)
    if isinstance(column.type, db.DateTime):
        # **العمود ده UTC واليوم ده يوم العيادة.** نص الليل عند العيادة
        # بيبقى الساعة ١٠ بالليل اليوم اللي قبله في UTC، فمن غير التحويل
        # سجل اتعمل الساعة ١٢:٣٠ بالليل كان هيتعدّ «عدّى المدة» وهو جوّاها.
        return to_utc(datetime.combine(day, time.min))
    return day


def rules():
    """``{نوع: RetentionRule}`` — للي اتحدّد بس."""
    return {r.doc_type: r for r in RetentionRule.query.all()}


def _as_date(value):
    """أقدم سجل **بيوم العيادة** — عمود الوقت متخزّن UTC."""
    if isinstance(value, datetime):
        return (to_local(value) or value).date()
    return value


def overview(today=None):
    """سطر لكل نوع: المدة، العدد، أقدم سجل، وكام عدّى المدة.

    **استعلام واحد لكل نوع** — العدد والأقدم وكام عدّى في نفس السطر.
    ``past`` بيبقى ``None`` لما المدة ما اتحدّدتش: مفيش حاجة «عدّت» مدة
    محدّش قالها، و``0`` هنا كان هيقول «كله تمام» وده مش صحيح.
    """
    today = today or local_today()
    known = rules()
    out = []
    for key, (column, where) in _sources().items():
        rule = known.get(key)
        years = rule.years if rule else None
        past_expr = (func.sum(case((column < _cutoff(column, years, today), 1),
                                   else_=0))
                     if years else null())
        total, oldest, past = db.session.query(
            func.count(), func.min(column), past_expr).select_from(
            column.class_).filter(*where).one()
        out.append({"key": key, "rule": rule, "years": years,
                    "total": total or 0, "oldest": _as_date(oldest),
                    "past": (past or 0) if years else None})
    return out


def unset():
    """الأنواع اللي لسه من غير مدة."""
    known = rules()
    return [key for key in DOC_TYPES
            if not (known.get(key) and known[key].years)]


def set_rule(doc_type, years, basis=None, user=None):
    """يحدّد (أو يشيل) مدة نوع. ما بيعملش commit.

    ``years`` فاضي بيشيل المدة — «ما اتحدّدتش» تاني، مش صفر.
    """
    if doc_type not in DOC_TYPES:
        raise ValueError("unknown document type")
    if years in ("", None):
        years = None
    else:
        years = int(years)
        if not YEARS_MIN <= years <= YEARS_MAX:
            raise ValueError("years out of range")
    rule = RetentionRule.query.filter_by(doc_type=doc_type).first()
    if rule is None:
        rule = RetentionRule(doc_type=doc_type)
        db.session.add(rule)
    rule.years = years
    rule.basis = (basis or "").strip()[:255] or None
    rule.set_by = getattr(user, "id", None)
    rule.set_at = datetime.utcnow()
    return rule


def record_destruction(done_on, doc_type, what, method, witness=None,
                       user=None, today=None):
    """سطر جديد في الدفتر. ما بيعملش commit.

    **وما بيمسحش حاجة من البرنامج.** السطر بيقول إن حاجة اتعدمت برّه —
    ورق أو وسيط — وبس.
    """
    today = today or local_today()
    if doc_type not in DOC_TYPES + (OTHER,):
        raise ValueError("unknown document type")
    what = (what or "").strip()
    method = (method or "").strip()
    if done_on is None or not what or not method:
        raise ValueError("missing")
    if done_on > today:
        raise ValueError("future")
    row = RecordDestruction(done_on=done_on, doc_type=doc_type,
                            what=what[:255], method=method[:120],
                            witness=((witness or "").strip()[:120] or None),
                            recorded_by=getattr(user, "id", None))
    db.session.add(row)
    return row


def destructions():
    """الدفتر، الأحدث الأول."""
    return (RecordDestruction.query
            .order_by(RecordDestruction.done_on.desc(),
                      RecordDestruction.id.desc()).all())


def safeguards():
    """البنود (ب) و(ج) — إيه اللي بيحمي السجل وهو محفوظ، من الإعدادات
    الموجودة فعلاً، مش كلام.

    * السرّية: كام حد بيقرا الملف ولسه ما وقّعش الإقرار (`IMT.05`).
    * الأرشفة: قواعدها زي ما العيادة ظبطتها.
    * النسخ الاحتياطية: كام نسخة بتتحفظ، ومتشفّرة ولا لأ.
    """
    from app.models import Setting
    from app.utils import archiving
    from app.utils.backups import backup_password
    from app.utils.record_access import unsigned

    return {
        "unsigned": len(unsigned()),
        "archive_years": archiving.inactive_years(),
        "archive_age": archiving.age_limit(),
        "archive_chronic": archiving.spare_chronic(),
        "archive_auto": archiving.auto_enabled(),
        "backup_keep": Setting.get("backup_keep", "14"),
        "backup_full_keep": Setting.get("backup_full_keep", "4"),
        "backup_encrypted": backup_password() is not None,
    }
