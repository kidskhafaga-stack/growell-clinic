"""التغذية — التقييم وأمر الأكل. GAHAR `ICD.13`.

النية بتقول الرابط بين الاتنين بالنص:

> The assessment **leads to a plan of care, or intervention**, designed to
> help the patient either maintain the assessed status or attain a healthier
> status.

**فتقييم ما أدّاش لحاجة هو الفشل اللي المعيار موجود علشانه** — مش تقييم
ناقص، ده تقييم كامل محدّش عمل بيه حاجة. ودي أقوى قراية في الملف ده.

---

**وليه جدولين مش واحد؟** لأن الاتنين مش مرحلتين من حاجة واحدة:

* تقييم ممكن يخلص من غير أمر خالص — طفل اتقيّم وطلع أكله عادي.
* وأمر واحد ممكن يتغيّر خمس مرات والتقييم زي ما هو.

يعني العلاقة **واحد لكتير**، مش نوعين من نفس الصف زي `SAS.18`/`SAS.23`.
ودمجهم كان هيخلّي كل تغيير في الأكل يكرّر التقييم، أو يخلّي التقييم
يتمسح كل ما الأكل يتغيّر.

---

**والبرنامج ما بيكتبش قايمة الأنظمة الغذائية.** (د)(١) بيقول *"a list of
all special diets **is available**"* — بتاعة المستشفى. فهي `Lookup`
بدومين `special_diet`، **وبتبدأ فاضية**: «حمية سكري» و«قليل الملح»
مفردات إكلينيكية، واختراعها هنا نفس غلطة اختراع مقياس فرز أو سلّم تسكين.
والشاشة بتقول للعيادة تكتبها بدل ما تعرض عليها اختيارات من عندنا.
"""
from datetime import datetime

from app.extensions import db

#: اسم القايمة في `Lookup` — بتتملّى من شاشة الإعدادات، وبتبدأ فاضية.
DIET_DOMAIN = "special_diet"


class NutritionAssessment(db.Model):
    """One nutritional assessment — `ICD.13` (ج) and evidence 3/5."""

    __tablename__ = "nutrition_assessments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)
    #: دليل ٣: مؤهّل مسؤول. مين قيّم، مش مين كتب الصف.
    assessed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    #: (ج) «مكوّنات التقييم» — سياسة المستشفى، فبكلام اللي قيّم. البرنامج
    #: مالوش استمارة تقييم تغذية ولا بيخترع بنودها.
    findings = db.Column(db.Text)

    #: **خلاصة التقييم: محتاج نظام خاص ولا لأ.**
    #:
    #: تلات حالات عن قصد: ``None`` يعني محدّش قال، و``False`` يعني اتقيّم
    #: وأكله عادي، و``True`` يعني محتاج. عمود بحالتين كان هيخلّي «اتقيّم
    #: وطلع كويس» و«محدّش قيّمه» نفس الحاجة — وهما أبعد حاجتين عن بعض
    #: في الباب ده.
    needs_special_diet = db.Column(db.Boolean)

    #: الخطة اللي التقييم أدّى لها — النية بتقول إنه **لازم** يأدّي لحاجة.
    plan = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="nutrition_assessments")
    assessed_by = db.relationship("User", foreign_keys=[assessed_by_id])

    def __repr__(self):
        return f"<NutritionAssessment patient={self.patient_id}>"


class DietOrder(db.Model):
    """One food order — `ICD.13` (د)(٣): *recorded in the medical record*."""

    __tablename__ = "diet_orders"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)

    #: مفتاح من قايمة العيادة (`Lookup` دومين `special_diet`). النص
    #: المعروض بيتقرا من القايمة، فتغيير التسمية بيغيّرها في كل مكان
    #: والصفوف القديمة تفضل مقروءة.
    diet_key = db.Column(db.String(40), nullable=False, index=True)
    #: تفاصيل بكلام اللي كتب — كمية، قوام، حاجة تتجنّب.
    detail = db.Column(db.Text)

    #: (د)(٤) «مواعيد الوجبات بتراعي تفضيلات المريض». بكلامهم، لأن
    #: «بعد المغرب» و«قبل حصة العلاج الطبيعي» حاجات البرنامج ما يعرفهاش.
    meal_times = db.Column(db.String(160))

    #: (هـ) أكل الأهل. **تلات حالات**: ``None`` محدّش قال، ``False``
    #: ممنوع، ``True`` مسموح واتشاف. وممنوع غير محدّش سأل — والتانية هي
    #: اللي بتحصل فعلاً لما الأهل يجيبوا أكل ومحدّش يقول حاجة.
    family_food_allowed = db.Column(db.Boolean)
    family_food_note = db.Column(db.String(200))

    ordered_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    ordered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    stopped_at = db.Column(db.DateTime, index=True)
    stopped_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)

    patient = db.relationship("Patient", backref="diet_orders")
    ordered_by = db.relationship("User", foreign_keys=[ordered_by_id])
    stopped_by = db.relationship("User", foreign_keys=[stopped_by_id])

    @property
    def running(self):
        return self.stopped_at is None

    def diet_name(self, lang="ar"):
        """اسم النظام من قايمة العيادة — مش من عندنا."""
        from app.utils import lookups

        return lookups.label(DIET_DOMAIN, self.diet_key, lang)

    def __repr__(self):
        return f"<DietOrder {self.diet_key} patient={self.patient_id}>"
