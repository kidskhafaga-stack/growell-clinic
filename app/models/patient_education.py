"""اتقالهم إيه، وإزاي، وفهموا ولا لأ — PCC.07.

> **PCC.07** Patients' and families' education is provided.
>
> (د) **Documentation of patient education activities**, including
> **information and education provided**, **how** the information and
> education were delivered (e.g., in writing, verbally, by demonstration,
> etc.), and **confirmation that the patient and/or family understood** the
> information and education provided.
>
> دليل ٤: *Patient education activities are recorded in the patient's medical
> record.*

**تلات حاجات في جملة واحدة، والتلاتة أعمدة.** «اتقالهم» بتخبّي تلاتة: **إيه**
اللي اتقال، **إزاي** اتقال، و**فهموا** ولا لأ. عمود واحد كان هيشيل واحدة منهم
ويسيب التانيتين للنسيان — وأهمهم التالتة، لأن أهل ما فهموش هما أهل اتقالهم
ومفيش حاجة حصلت.

---

**وإيه علاقته بـ`family_told` اللي موجودة خلاص؟**

`RiskAssessment.family_told` و`BloodRequest.family_told` و
`CarePlan.family_involved` كلهم بيجاوبوا سؤال معيارهم: *"The families of
patients at higher risk are **aware of and involved in** prevention
measures."* ده سؤال بنعم/لأ، ومكانه الصح جنب التقييم نفسه.

`PCC.07` بيسأل حاجة أغنى: **المحتوى، والطريقة، والتأكيد**. فالبوليان مش
بيتشال ومش بيتكرّر — هو الإجابة السريعة عند السرير، وده السجل. و`utils`
بيوصّلهم: علامة بتقول إن الأهل عارفين ومفيش صف تثقيف هي **فجوة حقيقية**
محدّش كان يقدر يشوفها.

---

**والتلات مواضيع اللي المعيار بيطلبها لكل مريض**، مش لبعضهم: (أ) بيقول *"at
least the following needs are to be addressed **for all patients**"* —
التشخيص والحالة · خطة الرعاية ونتيجتها المتوقّعة وبدائلها · تعليمات الخروج.

والباقي مواضيع بتيجي من المعايير اللي بتشاور على `PCC.07` — السقوط وقرح
الفراش والجلطات والدم والدوا والموافقة — وبتبقى مطلوبة **لما السجل يدّي سبب
ليها**، مش على طول.
"""
from datetime import datetime

from app.extensions import db

#: The three `PCC.07` (أ) names for **every** patient, in its own order.
DIAGNOSIS, CARE_PLAN, DISCHARGE = ("diagnosis", "care_plan", "discharge")
REQUIRED_TOPICS = (DIAGNOSIS, CARE_PLAN, DISCHARGE)

#: The rest, each one a standard that points at `PCC.07` in its own related
#: list. They are asked for only when the record gives a reason — a child
#: nobody found at risk of falling needs no falls teaching, and a list that
#: demanded it anyway is a list a ward learns to tick without reading.
FALL, PRESSURE, VTE, BLOOD, MEDICATION, CONSENT, OTHER = (
    "fall", "pressure", "vte", "blood", "medication", "consent", "other")
TOPICS = REQUIRED_TOPICS + (FALL, PRESSURE, VTE, BLOOD, MEDICATION, CONSENT,
                            OTHER)

#: (ج) *"in a language and format that they understand"* — the standard's own
#: examples. `interpreter` is not a method of its own: it is *how* a method
#: was delivered, and it has its own column for that reason.
WRITTEN, VERBAL, DEMONSTRATION, VIDEO = ("written", "verbal", "demonstration",
                                         "video")
METHODS = (VERBAL, WRITTEN, DEMONSTRATION, VIDEO)


class PatientEducation(db.Model):
    """One thing somebody explained to a family, and whether it landed."""

    __tablename__ = "patient_education"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # Where it happened, when it happened somewhere. Both nullable: teaching a
    # mother to use a spacer happens in the clinic room, on the ward, and on
    # the phone afterwards, and a row that needed one of them would lose the
    # third.
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True,
                         index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"),
                             nullable=True, index=True)

    topic = db.Column(db.String(16), nullable=False, index=True)
    #: (د) — **what was actually said**, in the words of whoever said it. The
    #: topic is the program's vocabulary; this is the clinic's, and nothing
    #: reads it.
    detail = db.Column(db.Text)
    #: (د) — *how* it was delivered. Its own column because «اتشرحله» and
    #: «اداله ورقة» are different acts with different evidence, and a family
    #: handed a leaflet in a language they do not read was not taught.
    method = db.Column(db.String(16), nullable=False, default=VERBAL)
    #: (ج) — whether it went through an interpreter. *"in a language … they
    #: understand"* is the element it answers.
    interpreter = db.Column(db.Boolean, default=False, nullable=False)

    #: (د) — **confirmation that they understood**, and the whole point.
    #: ``None`` nobody checked · ``False`` checked and they had not ·
    #: ``True`` confirmed. The middle one is a real and useful record: it is
    #: what sends somebody back to explain it again, and a two-state column
    #: would file it as "not taught yet" instead.
    understood = db.Column(db.Boolean)

    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False,
                   index=True)

    patient = db.relationship("Patient", backref="education")
    visit = db.relationship("Visit")
    admission = db.relationship("Admission")
    by = db.relationship("User")

    # No ``landed`` boolean here on purpose. It was written, and a mutation
    # showed nothing could tell whether it was right: no screen reads it, and
    # no screen would — the tab draws three states, not two, and the two-state
    # answer to "is this finished" is ``education.state(...) == DONE``, read
    # across a topic's rows rather than one row at a time.
    def __repr__(self):
        return f"<PatientEducation {self.topic} patient={self.patient_id}>"
