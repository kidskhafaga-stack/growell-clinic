"""`IMT.07` — كام سنة بنحتفظ بكل نوع مستند، وسجل الإتلاف.

*"Retention time for each type of document … Data destruction procedures."*
والمراجِع *"may review the list of retention time for different types of
information"* و*"may observe the record/logbook of document destruction"*.

**المدة رقم العيادة، مش رقم البرنامج.** القانون بيختلف والعيادة هي اللي
بتسأل محاميها، فكل نوع بيبدأ **من غير مدة** — والشاشة بتقول «ما اتحدّدتش»
بدل ما تعرض رقم محدّش قاله. رقم مخترع هنا أسوأ من فراغ: بيتقري كأنه سياسة.

**والبرنامج ما بيمسحش حاجة.** المدة بتقول «السجلات دي عدّت مدتها» — وبس.
الإتلاف قرار إنسان على ورق أو على نسخة، وبيتسجّل هنا: امتى، إيه، قد إيه،
بأي طريقة، ومين شهد. والسجل ده **بيتضاف عليه بس** — سطر اتكتب غلط بيتصلّح
بسطر جديد يقول كده، زي أي دفتر.
"""
from datetime import datetime

from app.extensions import db


class RetentionRule(db.Model):
    """مدة حفظ نوع مستند واحد."""

    __tablename__ = "retention_rules"

    id = db.Column(db.Integer, primary_key=True)
    # من `utils.retention.DOC_TYPES` — مفتاح ثابت، مش نص حر.
    doc_type = db.Column(db.String(30), unique=True, nullable=False)
    # **Nullable عن قصد**: «ما اتحدّدتش» حالة حقيقية.
    years = db.Column(db.Integer)
    # المرجع — «قانون ...»، «تعليمات الوزارة ...». بخط العيادة.
    basis = db.Column(db.String(255))
    set_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    set_at = db.Column(db.DateTime)

    setter = db.relationship("User", foreign_keys=[set_by])


class RecordDestruction(db.Model):
    """سطر في دفتر الإتلاف."""

    __tablename__ = "record_destructions"

    id = db.Column(db.Integer, primary_key=True)
    done_on = db.Column(db.Date, nullable=False)
    doc_type = db.Column(db.String(30), nullable=False)
    # إيه اللي اتعدم بالظبط — «ملفات ورق زيارات ٢٠١٠–٢٠١٢، ٣ كراتين».
    what = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(120), nullable=False)
    witness = db.Column(db.String(120))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    recorder = db.relationship("User", foreign_keys=[recorded_by])
