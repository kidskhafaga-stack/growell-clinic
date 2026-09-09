# GAHAR — مواد مرجعية ومصفوفة المطابقة

المجلد ده بيتجمّع فيه اللي بنرجعله لما نتكلم عن اعتماد GAHAR، عشان ما نفضلش
نجيب نفس الحاجة كل مرة.

| الملف | إيه هو |
|---|---|
| `GAHAR_2025_structure_reference.md` | **هيكل** دليل ٢٠٢٥ — الأقسام والفصول، وإزاي البند نفسه متركّب |
| `compliance_matrix.md` | مصفوفة المطابقة: اللي البرنامج بيعمله فعلاً، وفين هيتقاس |

## اقرا ده قبل ما تستعمل المرجع

`GAHAR_2025_structure_reference.md` هو **فهرس وإطار تفسير**، مش نص الدليل.

الملف بيقول ده عن نفسه بالحرف:

> *"This file is a **developer-oriented Markdown reference/index**... It should
> **not** be treated as a verbatim replacement for the official PDF."*

يعني بالعربي: **مفيهوش ولا كود بند واحد، ولا نص بند، ولا EOC**.

وده مش تفصيلة — ده اللي بيحدد نعمل إيه بيه:

- ✅ **بيقول أنهي فصل بيحكم أنهي قسم عندنا** — وده بيخلّي المصفوفة ليها هيكل صح
- ✅ **بيقول البند متركّب إزاي** (Statement · Keywords · Intent · Survey Process
  Guide · **EOCs** · Related Standards) — وده اللي بيحدد شكل أعمدة المصفوفة
- ❌ **بس ما بيسمحش بمقارنة بند-ببند** — لأن مفيش بنود نقارن بيها

فعمود «الحالة» في المصفوفة فاضي عن قصد، ومكتوب فيه **«بانتظار البند»**. أي حاجة
تانية تتكتب فيه دلوقتي هتبقى تخمين متلبّس شكل مطابقة.

## والمبدأ ده مكتوب في المرجع نفسه

المرجع بيقفل بالفقرة دي، وهي حرفياً نفس القاعدة اللي المشروع ماشي عليها:

> *"The system should not invent clinical or accreditation requirements. Every
> compliance claim should be traceable to: the official GAHAR standard, the
> exact EOC, the implemented system behavior, and a reproducible record."*

عشان كده المصفوفة عمودها الشمال (اللي البرنامج بيعمله) **متحقَّق منه بالكود**،
وعمودها اليمين (اللي المعيار بيطلبه) مستني نصوص البنود.

## اللي ناقص عشان نكمّل

نصوص البنود وEOCs بتاعة الفصول اللي بتحكم الأقسام اللي زوّدناها:

| الفصل | بيحكم عندنا |
|---|---|
| **Surgery, Anesthesia, and Sedation** | وحدة العمليات · تقييم ما قبل العملية · الـ checklist |
| **Critical and Special Care Services** | الرعاية المركزة · الحضّانة · الملاحظة |
| **ACT** — Access, Continuity, and Transition of Care | الدخول · حركة الأسرّة · الخروج والتحويل |
| **IMT** — Information Management and Technology | السجل نفسه: سريّته، إتاحته، وإدارته |
| **MMS** — Medication Management and Safety | الأدوية ومطابقتها |

**والملف كامل ٥٧٣ صفحة** — مش محتاجينه كله. الفصول الأربعة الأولانية تكفي
للأقسام اللي إحنا فيها.

> **ملاحظة:** موقع `gahar.gov.eg` **محجوب** من بيئة التطوير دي (سياسة شبكة، مش
> عطل)، فالمواد بتتحطّ هنا بالإيد.
