"""اللي الطفل وأهله محتاجينه — غير الدوا والتشخيص. GAHAR `PCC.12`.

> The hospital identifies and addresses the patient's emotional, religious,
> spiritual needs and other preferences.
>
> 1. Healthcare providers identify patients' emotional, religious, and
>    spiritual needs.
> 2. Patient needs and preferences are documented in the patient's medical
>    record.
> 3. Plans of care consider emotional, religious, and spiritual needs.

**وكانت بتتكتب في مكانين غلط.** `Patient.notes` — نص حر مفيش حاجة فيه
بتقول «ده احتياج»، فمحدّش بيدوّر عليه هناك. وخانة «التفضيلات» في خطة
الرعاية (`ICD.15`) — دي بتاعة خطة واحدة في إقامة واحدة: بتروح مع الخطة،
والطفل اللي بيجي العيادة مالوش خطة أصلاً.

والاحتياج **حقيقة عن الطفل**، مش عن زيارة ولا عن إقامة: «بيخاف من
الإبر — استعملوا الكريم المخدّر»، «الأسرة صايمة في رمضان»، «مفيش جيلاتين
خنزير»، «الأم عايزة دكتورة». بيتقال مرة، ولازم يتشاف في كل مرة.

---

**والأنواع أربعة، وهي كلمات المعيار نفسه** — *emotional, religious,
spiritual* و*other preferences*. مش قايمة اخترعناها: البرنامج ما بيخترعش
مفردات، وده التقسيم اللي المراجِع هيدوّر بيه. والكلام نفسه كلام الأسرة.

**والاحتياج بيخلص، مش بيتمسح** — نفس `PatientMedication`: «بيخاف من
الإبر» عند سنتين ممكن ما تبقاش صح عند ست سنين، والملف لازم يقدر يقول إيه
اللي كان صح الشهر اللي فات.
"""
from datetime import datetime

from app.extensions import db

EMOTIONAL, RELIGIOUS, SPIRITUAL, OTHER = (
    "emotional", "religious", "spiritual", "other")
#: بترتيب المعيار.
KINDS = (EMOTIONAL, RELIGIOUS, SPIRITUAL, OTHER)


class PatientNeed(db.Model):
    """احتياج أو تفضيل واحد، بكلام الأسرة."""

    __tablename__ = "patient_needs"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default=OTHER)
    #: **مش nullable**: احتياج من غير كلام هو نفس الفراغ اللي الجدول ده
    #: اتعمل علشانه.
    text = db.Column(db.String(300), nullable=False)

    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False)
    ended_at = db.Column(db.DateTime, index=True)
    ended_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    end_reason = db.Column(db.String(200))

    patient = db.relationship("Patient", backref=db.backref(
        "needs", order_by="PatientNeed.created_at.desc()"))
    recorder = db.relationship("User", foreign_keys=[recorded_by])
    ender = db.relationship("User", foreign_keys=[ended_by])

    @property
    def is_current(self):
        return self.ended_at is None

    def __repr__(self):
        return f"<PatientNeed {self.kind} p={self.patient_id}>"
