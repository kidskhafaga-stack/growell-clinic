"""حضور واحد في الطوارئ، من ساعة ما وصل لحد ما مشي — GAHAR `ICD.03(e)`.

**ده المكان الوحيد في الكتاب كله اللي بيعدّد محتويات ملف بالنص** (سطر ٤٦٧٧):

> The medical records of emergency patients should include at least:
> i) triage assessment and level · ii) medical and nurses' assessment and
> reassessment · iii) the care provided · iv) **arrival time and departure
> time** · v) patient disposition · vi) diagnosis or conclusion at termination
> · vii) **condition at departure** · viii) follow-up care instructions.

تمن بنود، والمراجِع معاه القايمة دي يدوس عليها واحد واحد.

---

**والجدول كان بيوصف العرض مش المرض.** أربعة من التمانية كانوا ❌، والسبب
مكانش عمود ناقص هنا وعمود هناك: `beds.admit` بيرفض من غير سرير بالنص
(`if bed is None: raise BedTaken("no bed")`)، **فالطفل اللي بيدخل الطوارئ
ويتفرز ويتعالج ويمشي من غير سرير مكانش ليه سجل خالص** — لا وقت وصول ولا
مغادرة ولا مآل. ودي أغلب حالات الطوارئ.

فالحضور بقى حاجة قايمة بذاتها، والسرير تفصيلة فيها مش شرط لوجودها.

---

**وليه المستوى بيتخزّن، والمشروع كله «مشتق أحسن من مخزّن».**

`red_flags.assess` بيحسب «عاجل ولا لأ» حيّ من العلامات الحيوية، وده صح
تماماً لشاشة بتقول «شوف مين دلوقتي». **ومش صح لسجل.** المراجِع بيفتح ملف
من تلات شهور ويسأل «الفرز اتعمل، وكان مستواه إيه **ساعتها**» — والحساب
الحيّ بيرد بنطاقات النهارده على أرقام إمبارح، ولو العيادة عدّلت نطاقاتها
كل ملفات الماضي بتتغيّر بأثر رجعي.

فالقاعدة بتنقلب هنا لسبب مكتوب: المطلوب مش «إيه الصح دلوقتي»، ده **«إيه
اللي اتقرّر ساعتها»**.

**والبرنامج ما بيخترعش مقياس فرز.** نفس شكل `RiskAssessment` بالظبط: اسم
الأداة (`scale`) والمستوى (`level`) **بكلام المستشفى**، وبند واحد بس
البرنامج بيقراه — `urgent` بتلات حالات: محدّش قال · لأ · أيوه. لأن
«متوسط» فوق الخط في مقياس وتحته في مقياس تاني، والبرنامج مالوش رأي.
"""
from datetime import datetime

from app.extensions import db

#: مين وصل إزاي. تصنيف تشغيلي مش إكلينيكي — وده اللي بيخلّيه مكتوب هنا.
WALK_IN, AMBULANCE, REFERRED, TRANSFER = ("walk_in", "ambulance", "referred",
                                          "transfer")
ARRIVALS = (WALK_IN, AMBULANCE, REFERRED, TRANSFER)

#: المآل — «راح فين». أربعة منهم هُمّا نفس `Admission.OUTCOMES` علشان
#: حضور بقى إقامة ما يتحكيش مرتين بكلمتين مختلفتين، واتنين زيادة بيخصّوا
#: الطوارئ لوحدها: اتحجز فوق، ومشي من غير ما حد يشوفه.
HOME, ADMITTED, TRANSFERRED = ("home", "admitted", "transferred")
SELF_DISCHARGE, LEFT_UNSEEN, DIED = ("self_discharge", "left_unseen", "died")
DISPOSITIONS = (HOME, ADMITTED, TRANSFERRED, SELF_DISCHARGE, LEFT_UNSEEN,
                DIED)


class EmergencyVisit(db.Model):
    """One attendance at the emergency department."""

    __tablename__ = "emergency_visits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)

    # المحتوى الإكلينيكي مش بيتنسخ هنا. التقييم والرعاية والتشخيص (البنود
    # ii و iii و vi) عايشين في `Visit` و`Observation` و`Diagnosis` زي أي
    # لقاء تاني — ونسخة تانية منهم كانت هتبقى نسختين بيفرقوا.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    # وبيتملّى لما الطفل يطلع فوق. الحضور ما بينتهيش علشان اتحجز — ده
    # **مآله**، والوقت اللي قعده تحت لسه وقت طوارئ.
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    # --- البند iv: الوصول والمغادرة ---
    arrived_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    arrival = db.Column(db.String(16), default=WALK_IN, nullable=False)
    departed_at = db.Column(db.DateTime, index=True)

    # --- البند i: الفرز ومستواه ---
    triaged_at = db.Column(db.DateTime, index=True)
    triaged_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # اسم الأداة والمستوى بكلام المستشفى. البرنامج ما بيخترعش مقياس.
    scale = db.Column(db.String(120))
    level = db.Column(db.String(60))
    # البند الوحيد اللي البرنامج بيقراه. تلات حالات: `None` محدّش قال.
    urgent = db.Column(db.Boolean)
    triage_note = db.Column(db.Text)

    # --- البنود v و vii و viii ---
    disposition = db.Column(db.String(20), index=True)
    # بكلام المستشفى برضه. البرنامج بيقرا «متكتوب ولا لأ» وبس — ودرجات
    # زي «اتحسّن/ما اتغيّرش» حكم إكلينيكي، واختيارها من عندنا كان هيخلّي
    # البرنامج بيقول رأي مالوش.
    condition = db.Column(db.String(200))
    followup_instructions = db.Column(db.Text)

    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="emergency_visits")
    visit = db.relationship("Visit")
    admission = db.relationship("Admission")
    triaged_by = db.relationship("User", foreign_keys=[triaged_by_id])
    by = db.relationship("User", foreign_keys=[by_id])

    @property
    def is_open(self):
        """لسه في القسم. الخروج هو **وقت** مش علامة — فمفيش عمودين ممكن
        يختلفوا."""
        return self.departed_at is None

    @property
    def minutes(self):
        """قد إيه قعد، أو قد إيه قاعد لحد دلوقتي."""
        end = self.departed_at or datetime.utcnow()
        return int((end - self.arrived_at).total_seconds() // 60)

    @property
    def wait_to_triage(self):
        """من الوصول للفرز، بالدقايق — أو ``None`` لو لسه ما اتفرزش.

        دليل `ICD.03(e)` بيطلب الفرز متسجّل؛ والمدة دي هي اللي بتخلّي
        «متسجّل» تفرق عن «اتعمل في وقته».
        """
        if self.triaged_at is None:
            return None
        return int((self.triaged_at - self.arrived_at).total_seconds() // 60)

    def __repr__(self):
        return f"<EmergencyVisit patient={self.patient_id} {self.arrived_at}>"
