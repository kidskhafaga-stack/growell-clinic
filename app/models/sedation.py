"""التخدير والتسكين الإجرائي: حلقة واحدة من البنج لحد ما الطفل يمشي.

أربع معايير، وتلات قوايم صريحة — و**ده تاني مكان في الكتاب بيعدّد محتويات
سجل بالنص** بعد قايمة الطوارئ:

* `SAS.18` — سجل التخدير، إحدى عشر بند (أ)–(ك).
* `SAS.23` — سجل التسكين الإجرائي، عشر بنود (أ)–(ي).
* `SAS.24` — رعاية ما بعد التسكين، سبع بنود (أ)–(ز).

---

**والقايمتين الأولانيتين نفس القايمة تقريباً.** حطّهم جنب بعض:

| `SAS.18` تخدير | `SAS.23` تسكين |
|---|---|
| (أ) الحالة الفسيولوجية | (أ) نفسها |
| (ب) وقت بداية التخدير | (ب) وقت بداية التسكين |
| (ج) **نوع التخدير** | (ج) **درجة التسكين** |
| (د) الأدوية بجرعتها وطريقها ووقتها | (د) نفسها |
| (هـ) السوايل داخل وخارج | (هـ) نفسها |
| (و) **الدم ومشتقاته** | — |
| (ز) أي حدث غير معتاد | (و) نفسه |
| (ح) حالته قبل ما يسيب المسرح | (ز) نفسها |
| (ط) المآل | (ح) نفسه |
| (ي) وقت النقل | (ط) نفسه |
| (ك) توقيع طبيب التخدير | (ي) توقيع الطبيب |

**تلات بنود بس بيفرقوا.** فجدولين كانوا هيبقوا نسختين من نفس الحاجة بيفرقوا
مع الوقت — والفرق بينهم `kind`، والقايمة المطلوبة بتتغيّر بيه زي ما مواضيع
التثقيف بتتغيّر بالسجل.

**و`SAS.24` مرحلة تانية من نفس الحلقة مش سجل تالت.** والدليل في النص نفسه:
(ي) في التخدير «وقت النقل»، و(ب) في ما بعد التسكين «وقت استلام المريض» —
**دي لحظة واحدة**. عمودين ليها كانوا هيقدروا يختلفوا، وساعتها الملف بيقول
إن الطفل ساب المسرح الساعة تلاتة ووصل الإفاقة الساعة اتنين.
"""
from datetime import datetime

from app.extensions import db

ANAESTHESIA, SEDATION = ("anaesthesia", "sedation")
KINDS = (ANAESTHESIA, SEDATION)

#: المآل — «راح فين بعد ما فاق».
RECOVERY, WARD, ICU, HOME = ("recovery", "ward", "icu", "home")
DISPOSITIONS = (RECOVERY, WARD, ICU, HOME)

#: البنود المشتركة بين القايمتين، بترتيبها في النص.
SHARED = ("status", "start", "drugs", "fluids", "event", "condition",
          "disposition", "transfer", "signature")
#: واللي بيخصّ كل واحدة لوحدها.
ONLY_ANAESTHESIA = ("technique", "blood")
ONLY_SEDATION = ("score",)
#: ورعاية ما بعد التسكين — `SAS.24` (أ)–(ز).
RECOVERY_ITEMS = ("recovery_status", "recovery_event", "recovery_score",
                  "recovery_disposition", "recovery_transfer",
                  "recovery_signature")


def required_for(kind):
    """البنود اللي القايمة بتطلبها للنوع ده."""
    extra = ONLY_ANAESTHESIA if kind == ANAESTHESIA else ONLY_SEDATION
    return SHARED + extra


class SedationRecord(db.Model):
    """One anaesthetic or sedation episode, theatre through recovery."""

    __tablename__ = "sedation_records"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("operations.id"),
                             nullable=True, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    kind = db.Column(db.String(16), nullable=False, index=True)

    # (ب) وقت البداية — بنج أو تسكين.
    started_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    # (ج) نوع التخدير — تخدير بس. بكلام المستشفى.
    technique = db.Column(db.String(120))
    # (ج) درجة التسكين — تسكين بس. **بمقياس المستشفى**: البرنامج ما بيخترعش
    # سلّم تسكين، زي ما ما اخترعش مقياس فرز ولا أداة تقييم خطورة.
    score = db.Column(db.String(60))

    # (د) الأدوية بجرعتها وطريقها ووقتها — بخطّ اللي كتب.
    drugs = db.Column(db.Text)
    # (هـ) السوايل: داخل وخارج. رقمين لأن الفرق بينهم هو المعلومة.
    fluids_in_ml = db.Column(db.Integer)
    fluids_out_ml = db.Column(db.Integer)
    # (و) الدم ومشتقاته — تخدير بس.
    blood_given = db.Column(db.String(200))
    # (ز)/(و) أي حدث غير معتاد. `None` معناها محدّش كتب، مش «مفيش».
    unusual_event = db.Column(db.Text)

    # (ح)/(ز) حالته قبل ما يسيب المسرح.
    condition_on_leaving = db.Column(db.String(200))
    # (ط)/(ح) المآل، و(ي)/(ط) وقت النقل.
    disposition = db.Column(db.String(16), index=True)
    # **عمود واحد للحظة واحدة.** ده «وقت النقل» في قايمة التخدير و«وقت
    # استلام المريض» في قايمة ما بعد التسكين — عمودين كانوا هيقدروا
    # يختلفوا، وساعتها الملف بيقول إن الطفل ساب المسرح بعد ما وصل الإفاقة.
    left_theatre_at = db.Column(db.DateTime, index=True)
    # (ك)/(ي) التوقيع.
    signed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    signed_at = db.Column(db.DateTime)

    # --- `SAS.24`: الإفاقة، نفس الحلقة ومرحلة تانية ---
    recovery_event = db.Column(db.Text)
    # (د) «حالته قبل الخروج **حسب درجة محدّدة**» — والدرجة دي بتاعة
    # المستشفى، زي كل مقياس تاني في البرنامج.
    recovery_score = db.Column(db.String(60))
    recovery_disposition = db.Column(db.String(16))
    recovery_left_at = db.Column(db.DateTime, index=True)
    recovery_signed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="sedation_records")
    signed_by = db.relationship("User", foreign_keys=[signed_by_id])
    recovery_signed_by = db.relationship(
        "User", foreign_keys=[recovery_signed_by_id])

    @property
    def in_theatre(self):
        """لسه في المسرح."""
        return self.left_theatre_at is None

    @property
    def in_recovery(self):
        """ساب المسرح ولسه في الإفاقة."""
        return self.left_theatre_at is not None and self.recovery_left_at is None

    @property
    def minutes(self):
        end = self.recovery_left_at or self.left_theatre_at or datetime.utcnow()
        return int((end - self.started_at).total_seconds() // 60)

    @property
    def recovery_minutes(self):
        """قد إيه قعد في الإفاقة، أو ``None`` لو ما وصلهاش."""
        if self.left_theatre_at is None:
            return None
        end = self.recovery_left_at or datetime.utcnow()
        return int((end - self.left_theatre_at).total_seconds() // 60)

    def __repr__(self):
        return f"<SedationRecord {self.kind} patient={self.patient_id}>"
