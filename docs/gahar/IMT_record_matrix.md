# مراجعة الملف الطبي مع GAHAR 2025

> **النص المقتبس هنا حرفي** من `GAHAR_2025_full.md` (الطبعة التانية ٢٠٢٥)،
> وكل سطر في عمود «اللي عندنا» **متحقَّق من الكود** بالملف والسطر.
> واللي مش متحقَّق مكتوب إنه مش متحقَّق.

---

## ليه المراجعة دي دلوقتي

**الملف الطبي في البرنامج اتبنى على عيادة خارجية.** الطفل بيجي، يتكشف عليه،
ياخد تطعيم، يتقاس، يتصرفله دوا — وده كله موجود وقوي.

**وبعدين زوّدنا أقسام داخلية.** أسرّة وإقامة (`beds`)، رعاية مركزة (`icu`)،
حضّانة (`nicu`)، عنبر (`ward`)، ملاحظة (`observations`)، طوارئ (`emergency`)،
عمليات (`theatres`)، إفاقة (`recovery`).

والسؤال اللي المراجعة دي بتجاوب عليه: **لما الطفل يتنوّم، السجل بتاعه لسه
«ملف واحد» زي ما IMT.08 بيطلب — ولا بقى حتّتين؟**

الإجابة المختصرة: **بقى حتّتين، والحتّة التانية مش ظاهرة في الملف أصلاً.**

---

## البنود اللي بتحكم الملف الطبي

| الكود | البند | الصفحة |
|---|---|---|
| **IMT.08** | *The Patient's medical record is managed to ensure effectiveness* | ٤٨٧ |
| **IMT.09** | *The hospital establishes the patient's medical record review process* | ٤٨٨ |
| **IMT.05** | *The hospital maintains data and information confidentiality and security* | ٤٨٣ |
| **IMT.06** | *Patient's medical record and information are protected from loss, destruction, tampering…* | ٤٨٤ |
| **IMT.07** | *Retention time of records, data, and information…* | ٤٨٦ |
| **IMT.04** · GSR.29 | *The hospital defines standardized symbols and abbreviations* | ٤٨١ |
| **ACT.04** | *…process guiding the hospitalization of patients* | ٨٩ |
| **ACT.15** | *Discharge summaries are complete* | ١٠٥ |
| **ICD.06** | *Initial medical assessment and subsequent reassessments are performed* | ١٢٧ |
| **ICD.07** | *Initial nursing assessments and reassessments are performed* | ١٢٩ |
| **ICD.15** | *An individualized plan of care is developed for every patient* | ١٤١ |

---

## ١) IMT.08 — إدارة الملف الطبي

### النص بالحرف

> Every patient evaluated or treated in the hospital has a medical record. The
> file is assigned **a number unique to the patient**…
>
> The patient's medical record must have **uniform contents and order**. The
> main goal … is to facilitate the **accessibility** of data and information…

**دلائل الامتثال:**

| # | الدليل | عندنا | الحالة |
|---|---|---|---|
| ٣ | *A patient's medical record is initiated with **a unique identifier** for every patient evaluated or treated* | `Patient.patient_number` — `unique=True, nullable=False, index=True` (`app/models/patient.py:33`)، وحروفه بتتقرا من `app/utils/numbering.py` | ✅ |
| ٤ | *The patient's medical record **contents, format, and location of entries** are standardized* | شاشة الملف بتبويبات ثابتة (`app/templates/patients/profile.html:233`) — **بس الإقامة مش فيها** | 🟡 |
| ٥ | *The patient's medical record is **available when needed** by a healthcare professional* | الجزء الخارجي أيوه؛ **الإقامة المقفولة لأ** — تحت | ❌ |
| ١ · ٢ | سياسة معتمدة + وعي الموظفين | **بره البرنامج** — دي ورق المستشفى | — |

### الفجوة، بالكود

تبويبات الملف هي: `overview` · `family` · `visits` · `studies` · `growth` ·
`vaccinations` · `prescriptions` · `documents` (+ `dental` · `history` ·
`finance` بشروط) — `app/templates/patients/profile.html:233`.

**مفيش تبويب للإقامة.** واللي بيوصل للإقامة من الملف حاجة واحدة بس:

```python
# app/blueprints/patients/routes.py:602 — _ward_context
admission = ward.open_admission(patient_id)
return {"open_admission": admission, ...}
```

و`open_admission` بتعريفها بترجّع **الإقامة المفتوحة بس**:

```python
# app/utils/beds.py:121
def open_admission(patient_id):
    """The stay this child is currently in, or ``None``."""
    return (Admission.query
            .filter(Admission.patient_id == patient_id,
                    Admission.discharged_at.is_(None))
            ...
```

**ومفيش مكان تاني في البرنامج بيدوّر على إقامات طفل.** `Admission.query`
مع `Admission.patient_id` ليها **استخدام واحد في الريبو كله**، وهو السطر ده
(`app/utils/beds.py:124`).

يعني بالعربي: **طفل اتنوّم تلات أيام في مارس، اتعمله عملية، خرج — ملفه
النهارده ما بيقولش إنه اتنوّم أصلاً.** ولا الإقامة، ولا السرير، ولا أوردرات
الملاحظة، ولا ملاحظات المرور، ولا مراجعة الصيدلي — كلها موجودة في قاعدة
البيانات ومربوطة بالطفل، و**الطريق الوحيد ليها إنك تكون فاتح شاشة العنبر
والطفل لسه راقد فيها**.

وده مش «تبويب ناقص» — ده الدليل ٥ نفسه: السجل **مش متاح** للطبيب اللي محتاجه.

### وتقرير الحالة برضه

`patients/report` (`app/blueprints/patients/routes.py:624`) — «التقرير الطبي
الشامل» — بيجمّع: بيانات · قايمة المشاكل · النمو · التطعيمات · آخر ١٠ زيارات ·
آخر روشتة.

**مفيهوش إقامات، ومفيهوش عمليات.** فالورقة اللي المفروض تلخّص الملف بتلخّص
نُصّه.

---

## ٢) ACT.15 — ملخّص الخروج

### النص بالحرف

> A discharge summary is a clinical report prepared by a healthcare
> professional at the conclusion of a hospital stay… **It is considered a legal
> document**…
>
> The discharge summary includes at least the following:
> a) The reason for hospitalization.
> b) Provisional and/or final diagnosis.
> c) Investigations.
> d) Significant findings.
> e) Procedures performed.
> f) Medications (before/during) and/or other treatments.
> g) Patient's condition and disposition at discharge.
> h) Discharge instructions, including diet, medications, and follow-up instructions.
> i) Name of the medical staff member who discharged the patient.

**ودلائل الامتثال ٣ و٤:** *A copy … is **kept in the patient's medical record***،
و *A copy … is **given to the patient***.

### اللي عندنا

خروج الإقامة كله تلات أعمدة (`app/models/admission.py:67-70`):

```python
discharged_at = db.Column(db.DateTime, index=True)
discharged_by = db.Column(db.Integer, db.ForeignKey("users.id"))
outcome       = db.Column(db.String(16))
discharge_note = db.Column(db.Text)          # نص حر
```

و`beds.discharge()` (`app/utils/beds.py:196`) بتكتبهم وبتقفل السرير. خلاص.

| العنصر | عندنا | فين |
|---|---|---|
| أ) سبب التنويم | 🟡 `Admission.reason` — نص حر ٢٠٠ حرف | `admission.py:65` |
| ب) التشخيص المبدئي/النهائي | 🟡 موجود على **الزيارة** مش على الإقامة | `models/diagnosis.py` |
| ج) الفحوصات | 🟡 موجودة على **الزيارة** | `VisitInvestigation` |
| د) النتائج المهمة | ❌ | — |
| هـ) الإجراءات اللي اتعملت | 🟡 `Operation` موجودة ومربوطة بالإقامة (`admission_id`)، بس مش بتتجمّع في ملخّص | `models/theatre.py` |
| و) الأدوية قبل/أثناء | 🟡 `drugbook` · `MedicationReview` | — |
| ز) حالة الطفل والمآل عند الخروج | 🟡 `outcome` بس — أربع قيم (`home` · `transferred` · `self_discharge` · `died`)، من غير حالة إكلينيكية | `admission.py:69` |
| ح) تعليمات الخروج (أكل · دوا · متابعة) | 🟡 **لحالات اليوم الواحد بس**: `recovery.discharge()` بتفرض `followup` وبتجيب `instructions_for` — وده أقوى من العنبر | `utils/recovery.py:99` |
| ط) اسم اللي خرّجه | ✅ `discharged_by` | `admission.py:68` |

**مفيش ملخّص خروج ولا صفحة بتطبعه ولا نسخة بتتسلّم للأهل.** موجود `discharge_note`
واحد نص حر، وده بالضبط اللي البند بيقول عنه إنه «وثيقة قانونية» بتسعة عناصر.

**ومُفارقة تستاهل تتقال:** حالة اليوم الواحد اللي بتخرج من الإفاقة أحسن حالاً
من الطفل اللي قعد أسبوع في العنبر — لأن `recovery.discharge()` **بترفض** تخرّج
من غير قرار متابعة، والعنبر ما بيرفضش حاجة.

---

## ٣) IMT.09 — مراجعة اكتمال الملف

### النص بالحرف

> a) Random sampling and selecting approximately **5%** of patient's medical records.
> b) Review of a representative sample of **all services**.
> c) Review of a representative sample of **all disciplines/staff**.
> d) Involvement of representatives of all disciplines who make entries.
> e) Review of the **completeness and legibility** of entries.
> f) Review occurs **at least quarterly**.

### اللي عندنا

**مفيش.** مفيش شاشة ولا تقرير بيقيس اكتمال الملفات.

> **تحذير من خلط سهل:** `app/models/chart_review.py` **مش** ده. `ChartReview`
> هي **مراجعة الصيدلي الإكلينيكي لشيت الأدوية** في إقامة — بند أدوية (MMS)،
> مش مراجعة سجل. اسمها بيغري بالخلط، فمكتوب هنا عشان ما يتحسبش امتثال لبند
> هي مش بتخصّه.

**واللي البرنامج يقدر يعمله هنا أكتر من ورقة:** النسبة ٥٪ والعيّنة الممثِّلة
والربع سنوي كلها شغل حسابي، والاكتمال نفسه — «إقامة خرجت من غير ملخّص»،
«عملية خلصت من غير sign-out»، «يوم في العنبر من غير مرور» — كله مقروء من
السجل دلوقتي حالاً. ده البند اللي **البرنامج يقدر يحمله كامل** مش يساعد فيه.

---

## ٤) ICD.06 · ICD.07 · ICD.15 — محتوى السجل للطفل المنوّم

| البند | الدليل اللي يخصّنا | عندنا | الحالة |
|---|---|---|---|
| **ICD.06** | *Initial medical assessments are performed **within 24 hours of hospitalization*** (دليل ٣) | `Visit` فيها `chief_complaint` · `clinical_exam` · `plan` (`models/visit.py:44-46`)، و`Admission.visit_id` **nullable** — فطفل يتنوّم من غير زيارة أصلاً | 🟡 |
| **ICD.06** | *Medical **reassessments** are performed … and recorded* (دليل ٥) | `RoundNote` — اتجاه + تقييم + خطة، مرّة أو أكتر في اليوم | ✅ |
| **ICD.07** | *Initial **nursing** assessment … upon admission* بعناصره أ)–و) | `Observation` بيغطّي القياسات المتكررة (حرارة · نبض · تنفس · ضغط · سكر · AVPU · ألم · أكسجين)، **بس مفيش تقييم تمريضي أولي** بالسقوط والتقرّحات والتغذية عند الدخول | 🟡 |
| **ICD.15** | *The plan of care … **is documented in the patient medical record*** بعناصره أ)–ز) | `RoundNote.plan` — خطة اليوم. **مفيش خطة رعاية بأهداف ومدد زمنية** (عنصر هـ)، ولا **مشاركة الأهل** موثّقة (عنصر ج) | 🟡 |

> **ملاحظة أمانة:** `ICD.06` و`ICD.07` و`ICD.15` كلهم بيقولوا «المستشفى تضع
> سياسة تحدّد الحد الأدنى للمحتوى والتكرار». الحد الأدنى ده **قرار المستشفى**،
> والبرنامج ما يخترعوش — اللي يخصّه إنه **يقدر يسجّل** العناصر لما المستشفى
> تحدّدها، ويقدر يقول مين ناقص.

---

## ٥) IMT.05 · IMT.06 · IMT.07 · IMT.04

| البند | الدليل | عندنا | الحالة |
|---|---|---|---|
| **IMT.05** ٣ | *There is a **list of authorized individuals** with access to the patient's medical record* | الأدوار والصلاحيات موجودة (`models/permissions.py` · `user_capability.py`) و`patient_medical` بتحكم تبويبات الملف — **بس مفيش تقرير بيطبع «مين له حق الوصول»** | 🟡 |
| **IMT.05** ٤ | *Only authorized individuals have access* | `module_required` · `can_access` على كل طريق، ومحروس بـ`tests/test_permission_sweep.py` | ✅ |
| **IMT.05** ٥ | *signed confidentiality agreement in each staff member's personal file* | ملف الموظف موجود، **مفيش إقرار سرّية** | ❌ |
| **IMT.06** ١ | *Medical records … secured and protected at all times* | نسخ احتياطية (`utils/backups.py`) + `ActivityLog` للتغييرات | 🟡 |
| **IMT.07** | *Retention time **for each type of document*** + إجراءات الإتلاف | `backups.apply_retention` موجودة — **بس دي مدة حفظ النُسخ الاحتياطية، مش مدة حفظ السجل**، ومفيش إتلاف موثّق | ❌ |
| **IMT.04** GSR.29 | قايمة اختصارات معتمدة + قايمة ممنوعة (ISMP) | **مفيش**. (`utils/rx_shorthand.py` بتفكّ اختصارات الروشتة — ده العكس: بتفهم المكتوب، مش بتحكم اللي يتكتب) | ❌ |

---

## أخطر تلات فجوات، بالترتيب

الترتيب مبني على نفس تلات الحاجات اللي رتّبنا بيها SAS.06: **كل قد إيه
بيحصل** · **حجم الضرر** · **وقد إيه البرنامج يقدر يحمله بأمانة**.

### ١ — الملف ما بيشوفش الإقامات (IMT.08 دليل ٤ و٥)

**بيلمس كل طفل اتنوّم، وبيكبر كل يوم.** والضرر مباشر: الطبيب اللي بيستقبل
الطفل تاني مرّة **ما يعرفش إنه كان منوّم**، ولا بأي إجراء، ولا خرج إزاي.
وده بالظبط اللي IMT.08 موجود عشانه — *continuity of care*.

**والبرنامج يقدر يحمله كامل**: الداتا كلها موجودة ومربوطة، والناقص **شاشة
بتقراها**. أقل شغل وأعلى قيمة في المراجعة دي كلها.

### ٢ — مفيش ملخّص خروج (ACT.15)

**وثيقة قانونية بتسعة عناصر مسمّاة**، والبند بيقول نسخة في الملف ونسخة للأهل.
عندنا سطر نص حر.

والعناصر التسعة **معظمها متسجّل فعلاً** في أماكن متفرّقة (التشخيص، الفحوصات،
العمليات، الأدوية) — فالشغل تجميع وطباعة أكتر منه تسجيل جديد. والعنصرين
الناقصين حقيقي (د: النتائج المهمة · ز: الحالة عند الخروج) سطرين.

### ٣ — مفيش مراجعة اكتمال الملف (IMT.09)

آخر واحد **مش لأنه أقل أهمية، لكن لأن التنتين اللي فوقه شرطه**: مراجعة
اكتمال على ملف نُصّه مش ظاهر هتقيس النُص. ولمّا يتعملوا، ده البند اللي
البرنامج يقدر يحمله **كامل** — العيّنة والنسبة والربع سنوي والاكتمال كلهم
حساب.

---

## واللي قوي فعلاً، عشان المراجعة تبقى عادلة

- **الرقم الفريد (IMT.08 دليل ٣)** — `unique=True, nullable=False`، ومعاه مديول
  ترقيم بيقرا الحروف من آخر ملف اتعمل. البند ده متحقّق بالكامل.
- **الوصول المحكوم (IMT.05 دليل ٤)** — كل طريق في البرنامج وراه صلاحية،
  و**اختبار بيمشي على كل الطرق** يتأكد إن مفيش واحد نسي.
- **إعادة التقييم (ICD.06 دليل ٥)** — `RoundNote` بترد على «الطبيب بيعيد
  التقييم ويسجّل» أحسن من ورق كتير.
- **الموافقة المستنيرة (PCC.08/09)** — وثيقة حقيقية بلغتها وتوقيعها، ومربوطة
  بالعملية بالإيد (`Operation.consent_id`).
- **الـ checklist وتوقيتات العملية وصلاحيات الجرّاح (SAS.02 · SAS.06)** —
  متقفولة، وفي `SAS_theatres_matrix.md`.

---

## تصحيح لحاجة كنا كاتبينها

`compliance_matrix.md` بيقول عن قسم IMT:

> **«الجزء ده مغطّى ومعلّم في الكود من قبل، بخلاف التلاتة اللي فوق»**

ده **اتكتب قبل ما نص الدليل يوصل**، وكان بيتكلم عن حاجات موجودة (قايمة
المشاكل، الموافقة، مطابقة الأدوية، سجل التدقيق) — وكلها فعلاً موجودة.

**بس «مغطّى» كانت كبيرة أوي على اللي كان متحقَّق ساعتها.** النص وصل دلوقتي،
والمراجعة دي هي الإجابة الحقيقية: **IMT.08 نُصّه، وIMT.04 وIMT.07 وIMT.09
مش موجودين.**
