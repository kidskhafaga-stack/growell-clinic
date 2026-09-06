"""Starter content for the drug reference (المرجع الدوائي).

A paediatric working set for the Egyptian market: the classes a children's
clinic prescribes from, the active ingredients inside them with their
weight/age dosing and the safety limits that matter, and the trade names those
ingredients are actually sold under here.

Everything is a *starting point the clinic owns*: every figure is editable from
the screens, and the reference computes and warns — it never prescribes. Doses
follow the common paediatric references (BNF for Children / WHO); the treating
doctor remains responsible for the final dose.
"""
from app.extensions import db
from app.models import Drug, DrugClass, GenericDoseBand, GenericDrug

# (code, name_ar, name_en, icon, sort)
CLASSES = [
    ("ANALG", "خافضات الحرارة ومسكنات الألم", "Antipyretics & analgesics", "bi-thermometer-half", 10),
    ("ABX", "المضادات الحيوية", "Antibiotics", "bi-bug", 20),
    ("ANTIH", "مضادات الهيستامين والحساسية", "Antihistamines & allergy", "bi-wind", 30),
    ("RESP", "أدوية الجهاز التنفسي", "Respiratory", "bi-lungs", 40),
    ("STER", "الكورتيزونات", "Corticosteroids", "bi-capsule", 50),
    ("GIT", "أدوية الجهاز الهضمي", "Gastrointestinal", "bi-egg-fried", 60),
    ("ORS", "الجفاف والإسهال", "Rehydration & diarrhoea", "bi-droplet", 70),
    ("VIT", "الفيتامينات والمعادن", "Vitamins & minerals", "bi-brightness-high", 80),
    ("ANTIF", "مضادات الفطريات", "Antifungals", "bi-flower1", 90),
    ("ANTIV", "مضادات الفيروسات", "Antivirals", "bi-shield-plus", 100),
    ("PARAS", "طاردات الديدان والطفيليات", "Antiparasitics", "bi-bug-fill", 110),
    ("TOPIC", "المستحضرات الموضعية", "Topical preparations", "bi-bandaid", 120),
    # Infant formula is the most paediatric thing in the Egyptian register —
    # 147 products across first, second and third stage, hypoallergenic,
    # lactose-free, anti-regurgitation and preterm — and there was no shelf
    # for it. It is not a drug and does not belong under vitamins; a clinic
    # that recommends a milk needs to find it where it looks for milk.
    ("MILK", "ألبان الأطفال", "Infant formula", "bi-cup-straw", 130),
    # 190 products the register files under ORAL CARE and this program filed
    # nowhere. Its own label is used rather than a guess at what each one is:
    # every single name says what it is — MOUTH WASH, ORAL GEL, ORAL SPRAY,
    # TOOTHPASTE — including all 35 that list no ingredient at all.
    #
    # It earns a shelf in a *children's* clinic for one reason that has
    # nothing to do with tidiness: 28 of those 190 contain a local anaesthetic
    # or a salicylate, several are sold as teething gels, and they were
    # sitting in the catalogue with no class, no warning and no way to find
    # them.
    ("ORAL", "العناية بالفم والأسنان", "Oral & dental care", "bi-emoji-smile", 140),
]

# name_ar, name_en, class, dosing…, safety…
# dose = (per_kg, per_kg_max, basis, doses_per_day, max_per_kg_day,
#         max_single_mg, max_daily_mg)
GENERICS = [
    dict(
        name_ar="باراسيتامول", name_en="Paracetamol", cls="ANALG", atc="N02BE01",
        routes="oral, rectal, IV",
        dose=(10, 15, "per_dose", 4, 60, 1000, 4000),
        indications="خفض الحرارة وتسكين الألم الخفيف إلى المتوسط.",
        contraindications="فرط الحساسية للمادة، قصور كبدي شديد.",
        precautions="لا تتجاوز 60 مج/كج/يوم؛ انتبه للجرعات المكررة في الأدوية المركّبة.",
        black_box="الجرعة الزائدة تسبب فشلاً كبدياً حاداً — أخطر خطأ شائع هو تكرار الجرعة قبل 4 ساعات.",
        hepatic="يُخفَّض في القصور الكبدي، ويُتجنّب في القصور الشديد.",
        preg="B", lact="آمن أثناء الرضاعة.",
        ref="BNF for Children", note="كل 4–6 ساعات، بحد أقصى 4 جرعات يومياً.",
    ),
    dict(
        name_ar="إيبوبروفين", name_en="Ibuprofen", cls="ANALG", atc="M01AE01",
        routes="oral",
        dose=(5, 10, "per_dose", 3, 40, 400, 1200),
        min_age=6,
        indications="خفض الحرارة، الألم، والالتهاب.",
        contraindications="أقل من 6 شهور، الجفاف، قرحة المعدة، الربو المتحسس للأسبرين، جدري الماء.",
        precautions="يؤخذ بعد الأكل؛ يُتجنّب مع الجفاف أو القيء المستمر (خطر على الكلى).",
        renal="يُتجنّب في القصور الكلوي وفي حالات الجفاف.",
        preg="C", lact="مسموح بجرعات قصيرة.",
        ref="BNF for Children", note="كل 6–8 ساعات مع الطعام.",
    ),
    dict(
        name_ar="أموكسيسيللين", name_en="Amoxicillin", cls="ABX", atc="J01CA04",
        routes="oral",
        dose=(25, 50, "per_day", 3, 90, None, 3000),
        indications="التهابات الأذن الوسطى والجيوب والجهاز التنفسي والبولي.",
        contraindications="حساسية البنسلين.",
        precautions="يُكمَل الكورس كاملاً (5–10 أيام) حتى مع تحسّن الأعراض.",
        renal="تُباعد الجرعات في القصور الكلوي الشديد.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
    ),
    dict(
        name_ar="أموكسيسيللين + حمض كلافولانيك", name_en="Amoxicillin/Clavulanate",
        cls="ABX", atc="J01CR02", routes="oral",
        dose=(45, 90, "per_day", 2, 90, None, 3000),
        indications="التهابات متكررة أو لم تستجب للأموكسيسيللين وحده.",
        contraindications="حساسية البنسلين، تاريخ يرقان ركودي مع نفس الدواء.",
        precautions="الحساب على مكوّن الأموكسيسيللين فقط — أشهر خطأ هو حساب الجرعة على إجمالي التركيز.",
        black_box="تجاوز 90 مج/كج/يوم من مكوّن الأموكسيسيللين يزيد الإسهال والتأثير الكبدي.",
        hepatic="يُوقف عند ظهور يرقان.",
        preg="B", lact="آمن.", ref="BNF for Children",
        note="التركيزات المختلفة (156 / 228 / 312 / 457) تختلف في نسبة الكلافولانيك.",
    ),
    dict(
        name_ar="أزيثروميسين", name_en="Azithromycin", cls="ABX", atc="J01FA10",
        routes="oral", dose=(10, 10, "per_day", 1, 12, 500, 500),
        min_age=6,
        indications="التهابات الجهاز التنفسي، السعال الديكي، بديل عند حساسية البنسلين.",
        contraindications="حساسية الماكروليدات، تاريخ يرقان مع الدواء.",
        precautions="يُعطى قبل الأكل بساعة أو بعده بساعتين.",
        black_box="يطيل فترة QT — حذر مع أدوية أخرى تطيل QT أو اضطراب أملاح.",
        preg="B", lact="آمن.", ref="BNF for Children",
        note="اليوم الأول 10 مج/كج ثم 5 مج/كج لمدة 4 أيام (أو 10 مج/كج ×3 أيام).",
    ),
    dict(
        name_ar="كلاريثروميسين", name_en="Clarithromycin", cls="ABX", atc="J01FA09",
        routes="oral", dose=(15, 15, "per_day", 2, 15, 500, 1000),
        indications="التهابات الجهاز التنفسي، بديل عند حساسية البنسلين.",
        contraindications="حساسية الماكروليدات، الاستخدام مع بعض أدوية القلب.",
        black_box="يطيل فترة QT ويتفاعل مع كثير من الأدوية (سيسابرايد، بعض مضادات الهيستامين).",
        preg="C", lact="مسموح بحذر.", ref="BNF for Children",
    ),
    dict(
        name_ar="سيفيكسيم", name_en="Cefixime", cls="ABX", atc="J01DD08",
        routes="oral", dose=(8, 8, "per_day", 1, 8, 400, 400),
        min_age=6,
        indications="التهابات الأذن والجهاز البولي والتنفسي.",
        contraindications="حساسية السيفالوسبورينات.",
        renal="تُخفَّض الجرعة عند تصفية كرياتينين أقل من 60.",
        preg="B", lact="آمن.", ref="BNF for Children",
    ),
    dict(
        name_ar="سيفترياكسون", name_en="Ceftriaxone", cls="ABX", atc="J01DD04",
        routes="IM, IV", dose=(50, 75, "per_day", 1, 80, 2000, 2000),
        indications="التهابات شديدة، الالتهاب السحائي (بجرعات أعلى)، حالات المستشفى.",
        contraindications="حساسية السيفالوسبورينات، حديثي الولادة مع محاليل الكالسيوم.",
        black_box="لا يُخلط أو يُعطى مع محاليل تحتوي كالسيوم في حديثي الولادة (ترسّبات قاتلة).",
        preg="B", lact="آمن.", ref="BNF for Children",
    ),
    dict(
        name_ar="سيفوروكسيم", name_en="Cefuroxime", cls="ABX", atc="J01DC02",
        routes="oral", dose=(20, 30, "per_day", 2, 30, 500, 1000),
        min_age=3,
        indications="التهابات الأذن والجهاز التنفسي.",
        contraindications="حساسية السيفالوسبورينات.",
        preg="B", lact="آمن.", ref="BNF for Children",
    ),
    dict(
        name_ar="سيتريزين", name_en="Cetirizine", cls="ANTIH", atc="R06AE07",
        routes="oral", min_age=6,
        indications="حساسية الأنف، الأرتيكاريا، الحكة.",
        contraindications="أقل من 6 شهور.",
        precautions="قد يسبب نعاساً خفيفاً.",
        renal="تُنصَّف الجرعة في القصور الكلوي.",
        preg="B", lact="مسموح بحذر.", ref="BNF for Children",
        bands=[(6, 11, "2.5 مج مرة يومياً", 2.5, 1),
               (12, 23, "2.5 مج مرة أو مرتين يومياً", 2.5, 2),
               (24, 71, "5 مج مقسّمة على مرتين", 2.5, 2),
               (72, None, "5–10 مج مرة يومياً", 10, 1)],
    ),
    dict(
        name_ar="لوراتادين", name_en="Loratadine", cls="ANTIH", atc="R06AX13",
        routes="oral", min_age=24,
        indications="حساسية الأنف والجلد — أقل نعاساً.",
        contraindications="أقل من سنتين.",
        hepatic="تُقلَّل الجرعة في القصور الكبدي.",
        preg="B", lact="مسموح.", ref="BNF for Children",
        bands=[(24, 71, "5 مج مرة يومياً", 5, 1),
               (72, None, "10 مج مرة يومياً", 10, 1)],
    ),
    dict(
        name_ar="سالبوتامول", name_en="Salbutamol", cls="RESP", atc="R03AC02",
        routes="inhaled, oral, nebulised",
        dose=(0.1, 0.15, "per_dose", 3, 0.6, 4, 12),
        indications="نوبات الضيق التنفسي وحساسية الصدر.",
        contraindications="فرط الحساسية للمادة.",
        precautions="الاستنشاق أفضل وأسرع وأقل أعراضاً من الشراب.",
        side="رعشة، زيادة ضربات القلب، انخفاض البوتاسيوم مع الجرعات العالية.",
        preg="C", lact="آمن.", ref="BNF for Children",
        note="بخّاخ: 100–200 ميكروجرام حسب العمر؛ نبيولايزر: 2.5 مج (<5 سنوات) أو 5 مج.",
    ),
    dict(
        name_ar="مونتيلوكاست", name_en="Montelukast", cls="RESP", atc="R03DC03",
        routes="oral", min_age=6,
        indications="الوقاية من نوبات الربو وحساسية الأنف.",
        contraindications="أقل من 6 شهور.",
        black_box="تحذير من تغيّرات نفسية وسلوكية (اضطراب النوم، القلق، الكوابيس) — يُوقف ويُراجع الطبيب.",
        preg="B", lact="مسموح.", ref="FDA / BNF for Children",
        bands=[(6, 23, "4 مج (حبيبات) مرة يومياً بالليل", 4, 1),
               (24, 59, "4 مج مرة يومياً بالليل", 4, 1),
               (60, 179, "5 مج مرة يومياً بالليل", 5, 1),
               (180, None, "10 مج مرة يومياً بالليل", 10, 1)],
    ),
    dict(
        name_ar="بريدنيزولون", name_en="Prednisolone", cls="STER", atc="H02AB06",
        routes="oral", dose=(1, 2, "per_day", 1, 2, 40, 60),
        indications="نوبات الربو المتوسطة والشديدة، الالتهابات المناعية.",
        contraindications="عدوى فطرية جهازية، تطعيمات حية أثناء الجرعات العالية.",
        precautions="كورس قصير 3–5 أيام لا يحتاج تدريجاً؛ الكورس الطويل يُوقف تدريجياً.",
        preg="C", lact="مسموح.", ref="BNF for Children",
    ),
    dict(
        name_ar="ديكساميثازون", name_en="Dexamethasone", cls="STER", atc="H02AB02",
        routes="oral, IM, IV", dose=(0.15, 0.6, "per_dose", 1, 0.6, 16, 16),
        indications="الخانوق (croup)، الالتهابات الشديدة، الوذمة.",
        contraindications="عدوى جهازية غير مغطاة.",
        preg="C", lact="مسموح.", ref="BNF for Children",
        note="الخانوق: جرعة واحدة 0.15–0.6 مج/كج.",
    ),
    dict(
        name_ar="أوميبرازول", name_en="Omeprazole", cls="GIT", atc="A02BC01",
        routes="oral", dose=(0.7, 1.0, "per_day", 1, 3.5, 20, 40),
        min_age=1,
        indications="الارتجاع المعدي المريئي، قرحة المعدة.",
        contraindications="فرط الحساسية.",
        precautions="يؤخذ قبل الأكل بنصف ساعة.",
        hepatic="تُقلَّل الجرعة في القصور الكبدي.",
        preg="C", lact="مسموح بحذر.", ref="BNF for Children",
    ),
    dict(
        name_ar="أوندانسيترون", name_en="Ondansetron", cls="GIT", atc="A04AA01",
        routes="oral, IV", dose=(0.15, 0.15, "per_dose", 3, 0.45, 8, 24),
        min_age=6,
        indications="القيء المصاحب للنزلات المعوية (جرعة واحدة عادةً).",
        contraindications="متلازمة QT الطويلة، الاستخدام مع أبومورفين.",
        black_box="يطيل فترة QT — حذر مع اضطراب الأملاح أو أدوية أخرى تطيل QT.",
        preg="B", lact="مسموح.", ref="BNF for Children",
    ),
    dict(
        name_ar="دومبيريدون", name_en="Domperidone", cls="GIT", atc="A03FA03",
        routes="oral", dose=(0.25, 0.25, "per_dose", 3, 0.75, 10, 30),
        indications="القيء والارتجاع (استعمال محدود ولأقصر مدة).",
        contraindications="اضطرابات القلب وإطالة QT، القصور الكبدي المتوسط والشديد.",
        black_box="مخاطر قلبية (إطالة QT) — أقصر مدة وأقل جرعة، وتُراجع دواعي الاستعمال.",
        hepatic="ممنوع في القصور الكبدي المتوسط فأكثر.",
        preg="C", lact="مسموح بحذر.", ref="EMA / BNF for Children",
    ),
    dict(
        name_ar="محلول معالجة الجفاف", name_en="Oral rehydration salts (ORS)",
        cls="ORS", routes="oral",
        indications="تعويض السوائل والأملاح في الإسهال والقيء — العلاج الأساسي للجفاف الخفيف والمتوسط.",
        precautions="يُذاب الكيس في الكمية المكتوبة من الماء النظيف بالضبط، ويُستهلك خلال 24 ساعة.",
        ref="WHO",
        bands=[(0, 23, "50–100 مل بعد كل إسهال", None, None),
               (24, 119, "100–200 مل بعد كل إسهال", None, None),
               (120, None, "حتى 300 مل بعد كل إسهال", None, None)],
    ),
    dict(
        name_ar="الزنك", name_en="Zinc sulfate", cls="ORS", atc="A12CB01",
        routes="oral",
        indications="مع محلول الجفاف في الإسهال الحاد — يقصّر مدته ويقلل تكراره.",
        precautions="يُكمَل 10–14 يوماً حتى بعد توقف الإسهال.",
        ref="WHO",
        bands=[(0, 5, "10 مج يومياً لمدة 10–14 يوم", 10, 1),
               (6, None, "20 مج يومياً لمدة 10–14 يوم", 20, 1)],
    ),
    dict(
        name_ar="فيتامين د", name_en="Vitamin D (cholecalciferol)", cls="VIT",
        atc="A11CC05", routes="oral",
        indications="الوقاية من الكساح ونقص فيتامين د.",
        precautions="الجرعات العلاجية العالية بوصفة وتحت متابعة.",
        ref="WHO / AAP",
        bands=[(0, 11, "400 وحدة دولية يومياً", 400, 1),
               (12, None, "600 وحدة دولية يومياً", 600, 1)],
    ),
    dict(
        name_ar="الحديد (عنصري)", name_en="Elemental iron", cls="VIT",
        atc="B03AA07", routes="oral",
        dose=(3, 6, "per_day", 2, 6, 200, 200),
        indications="أنيميا نقص الحديد والوقاية منها.",
        precautions="يُعطى بين الوجبات مع فيتامين ج؛ يُتجنّب مع الحليب والشاي.",
        side="اسوداد البراز، إمساك، مغص.",
        black_box="الجرعة الزائدة من الحديد سبب شائع للتسمم القاتل في الأطفال — يُحفظ بعيداً تماماً.",
        ref="BNF for Children",
    ),
    dict(
        name_ar="نيستاتين", name_en="Nystatin", cls="ANTIF", atc="A07AA02",
        routes="oral (topical in mouth)",
        indications="فطريات الفم (سلاق) والحفاض.",
        contraindications="فرط الحساسية.",
        precautions="يُدهن/يُقطّر بعد الرضعة ويُكمَل 48 ساعة بعد اختفاء الأعراض.",
        preg="B", lact="آمن.", ref="BNF for Children",
        bands=[(0, 23, "1 مل (100,000 وحدة) 4 مرات يومياً", None, 4),
               (24, None, "1–2 مل 4 مرات يومياً", None, 4)],
    ),
    dict(
        name_ar="فلوكونازول", name_en="Fluconazole", cls="ANTIF", atc="J02AC01",
        routes="oral, IV", dose=(3, 6, "per_day", 1, 12, 400, 400),
        indications="فطريات الفم والمريء المقاومة، الفطريات الجهازية.",
        contraindications="الاستخدام مع سيسابرايد؛ حساسية الأزولات.",
        renal="تُخفَّض الجرعة في القصور الكلوي.",
        hepatic="متابعة وظائف الكبد في الكورسات الطويلة.",
        preg="D", lact="مسموح بحذر.", ref="BNF for Children",
    ),
    dict(
        name_ar="أسيكلوفير", name_en="Aciclovir", cls="ANTIV", atc="J05AB01",
        routes="oral, IV", dose=(20, 20, "per_dose", 4, 80, 800, 3200),
        indications="جدري الماء والهربس.",
        precautions="يبدأ خلال 24 ساعة من ظهور الطفح ليكون مفيداً؛ الإكثار من السوائل.",
        renal="تُعدَّل الجرعة في القصور الكلوي.",
        preg="B", lact="مسموح.", ref="BNF for Children",
    ),
    dict(
        name_ar="ألبيندازول", name_en="Albendazole", cls="PARAS", atc="P02CA03",
        routes="oral", min_age=12,
        indications="الديدان المعوية (الأسكارس، الدبوسية، الشصية).",
        contraindications="أقل من سنة (إلا بقرار الطبيب)، الحمل.",
        precautions="تُكرَّر الجرعة بعد أسبوعين في الديدان الدبوسية، ويُعالَج أفراد الأسرة.",
        preg="C", lact="مسموح بحذر.", ref="WHO",
        bands=[(12, 23, "200 مج جرعة واحدة", 200, 1),
               (24, None, "400 مج جرعة واحدة", 400, 1)],
    ),
    dict(
        name_ar="ميترونيدازول", name_en="Metronidazole", cls="PARAS", atc="P01AB01",
        routes="oral, IV", dose=(15, 30, "per_day", 3, 40, 800, 2400),
        indications="الجيارديا والأميبا والالتهابات اللاهوائية.",
        contraindications="فرط الحساسية، الثلث الأول من الحمل.",
        precautions="طعم معدني وغثيان شائعان؛ يُمنع الكحول تماماً.",
        preg="B", lact="يُفضّل إيقاف الرضاعة مع الجرعة الواحدة الكبيرة.",
        ref="BNF for Children",
    ),
]

# --- second wave: the rest of a paediatric formulary ------------------------
GENERICS += [
    dict(name_ar="ديكلوفيناك", name_en="Diclofenac", cls="ANALG", atc="M01AB05",
         routes="oral, rectal, IM", dose=(0.5, 1, "per_dose", 3, 3, 50, 150),
         min_age=12, indications="ألم والتهاب — يُستخدم بحذر في الأطفال.",
         contraindications="أقل من سنة، قرحة المعدة، الربو المتحسس للأسبرين، الجفاف.",
         renal="يُتجنّب في القصور الكلوي.", preg="C", ref="BNF for Children"),
    dict(name_ar="ميفيناميك أسيد", name_en="Mefenamic acid", cls="ANALG",
         atc="M01AG01", routes="oral", dose=(6.5, 6.5, "per_dose", 3, 20, 500, 1500),
         min_age=6, indications="خافض حرارة ومسكن.",
         contraindications="قرحة المعدة، أقل من 6 شهور.", preg="C", ref="BNF for Children"),
    dict(name_ar="فينوباربيتال", name_en="Phenobarbital", cls="ANALG", atc="N03AA02",
         routes="oral, IV", dose=(3, 5, "per_day", 1, 8, 200, 200),
         indications="تشنجات الأطفال وحديثي الولادة.",
         black_box="مثبط للتنفس بجرعات عالية — يُعطى تحت إشراف.",
         hepatic="حذر شديد في القصور الكبدي.", preg="D", ref="BNF for Children"),
    dict(name_ar="أمبيسيللين", name_en="Ampicillin", cls="ABX", atc="J01CA01",
         routes="IV, IM, oral", dose=(50, 100, "per_day", 4, 200, None, 4000),
         indications="التهابات المستشفى وحديثي الولادة.",
         contraindications="حساسية البنسلين.", preg="B", ref="BNF for Children"),
    dict(name_ar="فلوكلوكساسيللين", name_en="Flucloxacillin", cls="ABX",
         atc="J01CF05", routes="oral, IV", dose=(50, 100, "per_day", 4, 100, None, 4000),
         indications="التهابات الجلد العنقودية.",
         contraindications="حساسية البنسلين، تاريخ يرقان مع نفس الدواء.",
         hepatic="متابعة وظائف الكبد في الكورسات الطويلة.", preg="B",
         ref="BNF for Children"),
    dict(name_ar="سيفاكلور", name_en="Cefaclor", cls="ABX", atc="J01DC04",
         routes="oral", dose=(20, 40, "per_day", 3, 40, 500, 1500),
         min_age=1, indications="التهابات الأذن والجهاز التنفسي.",
         contraindications="حساسية السيفالوسبورينات.", preg="B", ref="BNF for Children"),
    dict(name_ar="سيفادروكسيل", name_en="Cefadroxil", cls="ABX", atc="J01DB05",
         routes="oral", dose=(30, 30, "per_day", 2, 30, 1000, 2000),
         indications="التهابات الجلد والحلق والبول.",
         contraindications="حساسية السيفالوسبورينات.", preg="B", ref="BNF for Children"),
    dict(name_ar="سيفبودوكسيم", name_en="Cefpodoxime", cls="ABX", atc="J01DD13",
         routes="oral", dose=(8, 10, "per_day", 2, 10, 200, 400), min_age=2,
         indications="التهابات الأذن والجهاز التنفسي.",
         contraindications="حساسية السيفالوسبورينات.", preg="B", ref="BNF for Children"),
    dict(name_ar="ترايميثوبريم/سلفاميثوكسازول", name_en="Co-trimoxazole", cls="ABX",
         atc="J01EE01", routes="oral", dose=(6, 8, "per_day", 2, 12, 320, 640),
         min_age=2,
         indications="التهابات البول، الوقاية من الالتهاب الرئوي بالمتكيسة الرئوية.",
         contraindications="أقل من شهرين، اليرقان الوليدي، نقص G6PD الشديد.",
         black_box="طفح جلدي شديد نادر (ستيفنز جونسون) — يُوقف فوراً عند أي طفح.",
         renal="تُعدَّل الجرعة في القصور الكلوي.", preg="C", ref="BNF for Children"),
    dict(name_ar="نيتروفورانتوين", name_en="Nitrofurantoin", cls="ABX", atc="J01XE01",
         routes="oral", dose=(3, 3, "per_day", 4, 7, 100, 400), min_age=3,
         indications="التهاب المسالك البولية والوقاية منه.",
         contraindications="أقل من 3 شهور، القصور الكلوي، نقص G6PD.",
         renal="ممنوع عند ضعف وظائف الكلى.", preg="B", ref="BNF for Children"),
    dict(name_ar="فانكومايسين", name_en="Vancomycin", cls="ABX", atc="J01XA01",
         routes="IV", dose=(40, 60, "per_day", 4, 60, 2000, 2000),
         indications="التهابات شديدة مقاومة (مستشفى).",
         black_box="سمية كلوية وسمعية — يحتاج قياس مستوى الدواء.",
         renal="تُعدَّل الجرعة على وظائف الكلى.", monitoring="مستوى الدواء ووظائف الكلى",
         preg="C", ref="BNF for Children"),
    dict(name_ar="جنتاميسين", name_en="Gentamicin", cls="ABX", atc="J01GB03",
         routes="IV, IM", dose=(5, 7, "per_day", 1, 7, 400, 400),
         indications="التهابات شديدة بالسالبة الجرام.",
         black_box="سمية كلوية وسمعية — قياس المستوى ووظائف الكلى ضروري.",
         renal="تُباعد الجرعات في القصور الكلوي.", monitoring="مستوى الدواء، الكرياتينين، السمع",
         preg="D", ref="BNF for Children"),
    dict(name_ar="ديسلوراتادين", name_en="Desloratadine", cls="ANTIH", atc="R06AX27",
         routes="oral", min_age=6, indications="حساسية الأنف والأرتيكاريا.",
         contraindications="أقل من 6 شهور.", preg="B", ref="BNF for Children",
         bands=[(6, 11, "1 مج مرة يومياً", 1, 1), (12, 59, "1.25 مج مرة يومياً", 1.25, 1),
                (60, 143, "2.5 مج مرة يومياً", 2.5, 1), (144, None, "5 مج مرة يومياً", 5, 1)]),
    dict(name_ar="كلورفينيرامين", name_en="Chlorpheniramine", cls="ANTIH",
         atc="R06AB04", routes="oral", min_age=12,
         indications="حساسية وحكة — مهدئ (يسبب نعاساً).",
         contraindications="أقل من سنة، الجلوكوما، احتباس البول.",
         preg="B", ref="BNF for Children",
         bands=[(12, 23, "1 مج مرتين يومياً", 1, 2), (24, 71, "1 مج كل 4–6 ساعات", 1, 4),
                (72, 143, "2 مج كل 4–6 ساعات", 2, 4), (144, None, "4 مج كل 4–6 ساعات", 4, 4)]),
    dict(name_ar="كيتوتيفين", name_en="Ketotifen", cls="ANTIH", atc="R06AX17",
         routes="oral", min_age=6, indications="الوقاية من نوبات الحساسية والربو الخفيف.",
         side="نعاس وزيادة الشهية.", preg="B", ref="BNF for Children",
         bands=[(6, 35, "0.05 مج/كج مرتين يومياً", None, 2),
                (36, None, "1 مج مرتين يومياً", 1, 2)]),
    dict(name_ar="بوديزونيد (استنشاق)", name_en="Budesonide (inhaled)", cls="RESP",
         atc="R03BA02", routes="inhaled, nebulised",
         indications="الوقاية من نوبات الربو (علاج أساسي وليس للنوبة).",
         precautions="المضمضة بعد الاستنشاق لتفادي فطريات الفم.",
         monitoring="متابعة الطول مع الاستخدام الطويل.", preg="B",
         ref="BNF for Children",
         bands=[(6, 143, "0.5 مج بالنبيولايزر مرة أو مرتين يومياً", 0.5, 2),
                (144, None, "0.5–1 مج مرتين يومياً", 1, 2)]),
    dict(name_ar="فلوتيكازون (استنشاق)", name_en="Fluticasone (inhaled)", cls="RESP",
         atc="R03BA05", routes="inhaled", min_age=12,
         indications="الوقاية من نوبات الربو.",
         precautions="المضمضة بعد الاستنشاق.", preg="C", ref="BNF for Children"),
    dict(name_ar="إبراتروبيوم", name_en="Ipratropium", cls="RESP", atc="R03BB01",
         routes="inhaled, nebulised",
         indications="يُضاف للسالبوتامول في النوبات المتوسطة والشديدة.",
         contraindications="فرط الحساسية.", preg="B", ref="BNF for Children",
         bands=[(0, 59, "125–250 ميكروجرام بالنبيولايزر", None, 3),
                (60, None, "250 ميكروجرام بالنبيولايزر", None, 3)]),
    dict(name_ar="أمبروكسول", name_en="Ambroxol", cls="RESP", atc="R05CB06",
         routes="oral", min_age=24,
         indications="مذيب للبلغم (فائدته محدودة تحت سنتين).",
         contraindications="أقل من سنتين.", preg="B", ref="EDA leaflet",
         bands=[(24, 59, "7.5 مج مرتين يومياً", 7.5, 2),
                (60, 143, "15 مج مرتين يومياً", 15, 2),
                (144, None, "30 مج مرتين يومياً", 30, 2)]),
    dict(name_ar="أسيتيل سيستئين", name_en="Acetylcysteine", cls="RESP",
         atc="R05CB01", routes="oral", min_age=24,
         indications="مذيب للبلغم؛ وترياق التسمم بالباراسيتامول (بروتوكول مستشفى).",
         preg="B", ref="BNF for Children",
         bands=[(24, 83, "100 مج مرتين يومياً", 100, 2),
                (84, None, "200 مج مرتين يومياً", 200, 2)]),
    dict(name_ar="هيدروكورتيزون", name_en="Hydrocortisone", cls="STER", atc="H02AB09",
         routes="IV, IM, oral", dose=(2, 4, "per_dose", 4, 16, 100, 400),
         indications="الحساسية الشديدة، نوبات الربو الحادة، قصور الغدة الكظرية.",
         preg="C", ref="BNF for Children"),
    dict(name_ar="سيميثيكون", name_en="Simethicone", cls="GIT", atc="A03AX13",
         routes="oral", indications="المغص والانتفاخ عند الرضع.",
         precautions="لا يُمتص من الأمعاء — آمن، وفائدته عرضية.",
         ref="EDA leaflet",
         bands=[(0, 11, "20 مج بعد كل رضعة عند اللزوم", 20, 4),
                (12, None, "40 مج بعد الأكل", 40, 3)]),
    dict(name_ar="لاكتولوز", name_en="Lactulose", cls="GIT", atc="A06AD11",
         routes="oral", indications="الإمساك المزمن عند الأطفال.",
         contraindications="انسداد معوي، جالاكتوسيميا.",
         precautions="الجرعة تُعدَّل حسب استجابة الطفل — الهدف براز لين يومياً.",
         preg="B", ref="BNF for Children",
         bands=[(0, 11, "2.5 مل مرتين يومياً", None, 2),
                (12, 59, "5 مل مرتين يومياً", None, 2),
                (60, 143, "10 مل مرتين يومياً", None, 2),
                (144, None, "15 مل مرتين يومياً", None, 2)]),
    dict(name_ar="بولي إيثيلين جلايكول", name_en="Polyethylene glycol (macrogol)",
         cls="GIT", atc="A06AD15", routes="oral",
         indications="الإمساك وتفريغ البراز المتحجر — الخيار الأول للأطفال.",
         contraindications="انسداد معوي.", preg="B", ref="NICE / BNF for Children",
         bands=[(12, 71, "كيس واحد يومياً يُعدَّل حسب الاستجابة", None, 1),
                (72, None, "1–2 كيس يومياً", None, 2)]),
    dict(name_ar="راسيكادوتريل", name_en="Racecadotril", cls="ORS", atc="A07XA04",
         routes="oral", dose=(1.5, 1.5, "per_dose", 3, 6, 100, 300), min_age=3,
         indications="يُضاف لمحلول الجفاف لتقليل كمية الإسهال.",
         contraindications="أقل من 3 شهور.", preg="C", ref="EDA leaflet"),
    dict(name_ar="بروبيوتيك (لاكتوباسيلس)", name_en="Probiotic (Lactobacillus)",
         cls="ORS", routes="oral",
         indications="تقصير مدة الإسهال الحاد، والإسهال المصاحب للمضاد الحيوي.",
         precautions="حذر في نقص المناعة الشديد أو وجود قسطرة وريدية مركزية.",
         ref="ESPGHAN",
         bands=[(0, 23, "كيس/قطارة يومياً", None, 1), (24, None, "كيس أو اتنين يومياً", None, 2)]),
    dict(name_ar="فيتامين أ د", name_en="Vitamins A + D", cls="VIT", routes="oral",
         indications="الوقاية من نقص فيتامين أ ود عند الرضع.",
         precautions="لا يُجمع مع مكمل فيتامين د آخر بلا حساب.",
         ref="WHO",
         bands=[(0, 11, "نقطة يومياً حسب المستحضر", None, 1),
                (12, None, "حسب توصية الطبيب", None, 1)]),
    dict(name_ar="كالسيوم + فيتامين د", name_en="Calcium with vitamin D", cls="VIT",
         routes="oral", indications="نقص الكالسيوم، الكساح، النمو السريع.",
         precautions="يُباعد ساعتين عن الحديد والمضادات الحيوية من مجموعة التتراسيكلين.",
         ref="BNF for Children",
         bands=[(0, 35, "حسب المستحضر ووزن الطفل", None, 1),
                (36, None, "500 مج كالسيوم يومياً", 500, 1)]),
    dict(name_ar="حمض الفوليك", name_en="Folic acid", cls="VIT", atc="B03BB01",
         routes="oral", indications="أنيميا نقص الفولات، وحالات الأنيميا المزمنة.",
         preg="A", lact="آمن.", ref="BNF for Children",
         bands=[(0, 11, "500 ميكروجرام يومياً", 0.5, 1),
                (12, None, "5 مج يومياً حسب الحالة", 5, 1)]),
    dict(name_ar="فيتامين ب المركب", name_en="Vitamin B complex", cls="VIT",
         routes="oral", indications="نقص فيتامينات ب، ضعف الشهية.",
         ref="EDA leaflet",
         bands=[(0, 23, "قطارة يومياً", None, 1), (24, None, "5 مل يومياً", None, 1)]),
    dict(name_ar="كلوتريمازول (موضعي)", name_en="Clotrimazole (topical)", cls="ANTIF",
         atc="D01AC01", routes="topical",
         indications="فطريات الجلد والحفاض.",
         precautions="يُدهن مرتين يومياً ويستمر أسبوعاً بعد اختفاء الطفح.",
         preg="B", ref="BNF for Children"),
    dict(name_ar="ميكونازول (فموي موضعي)", name_en="Miconazole oral gel", cls="ANTIF",
         atc="A01AB09", routes="topical (oral)", min_age=4,
         indications="سلاق الفم.",
         contraindications="أقل من 4 شهور (خطر الاختناق بالجل).",
         preg="C", ref="BNF for Children"),
    dict(name_ar="أوسيلتاميفير", name_en="Oseltamivir", cls="ANTIV", atc="J05AH02",
         routes="oral", dose=(3, 4, "per_dose", 2, 8, 75, 150),
         indications="الأنفلونزا — يبدأ خلال 48 ساعة من الأعراض.",
         renal="تُعدَّل الجرعة في القصور الكلوي.", preg="C", ref="BNF for Children",
         note="أقل من سنة: 3 مج/كج للجرعة مرتين يومياً."),
    dict(name_ar="ميبيندازول", name_en="Mebendazole", cls="PARAS", atc="P02CA01",
         routes="oral", min_age=12,
         indications="الديدان الدبوسية والأسكارس والشصية.",
         contraindications="أقل من سنة، الحمل.",
         precautions="تُكرَّر بعد أسبوعين في الدودة الدبوسية، ويُعالَج كل أفراد البيت.",
         preg="C", ref="WHO",
         bands=[(12, None, "100 مج مرتين يومياً لمدة 3 أيام (أو 500 مج جرعة واحدة)", 100, 2)]),
    dict(name_ar="برازيكوانتيل", name_en="Praziquantel", cls="PARAS", atc="P02BA01",
         routes="oral", dose=(40, 40, "per_dose", 1, 60, None, None), min_age=48,
         indications="البلهارسيا والديدان الشريطية.",
         contraindications="أقل من 4 سنوات (إلا بقرار الطبيب).",
         preg="B", ref="WHO"),
    dict(name_ar="بيرميثرين (موضعي)", name_en="Permethrin (topical)", cls="TOPIC",
         atc="P03AC04", routes="topical", min_age=2,
         indications="الجرب وقمل الرأس.",
         precautions="يُدهن على جلد جاف ويُغسل بعد 8–12 ساعة، ويُعاد بعد أسبوع؛ ويُعالَج كل أفراد البيت.",
         preg="B", ref="BNF for Children"),
    dict(name_ar="فيوسيديك أسيد (موضعي)", name_en="Fusidic acid (topical)",
         cls="TOPIC", atc="D06AX01", routes="topical",
         indications="التهابات الجلد البكتيرية السطحية (القوباء).",
         precautions="لا يُستخدم لفترات طويلة تفادياً للمقاومة.", preg="B",
         ref="BNF for Children"),
    dict(name_ar="هيدروكورتيزون (موضعي)", name_en="Hydrocortisone (topical)",
         cls="TOPIC", atc="D07AA02", routes="topical",
         indications="الإكزيما والتهاب الجلد التحسسي.",
         contraindications="العدوى الفطرية أو الفيروسية غير المغطاة.",
         precautions="أقصر مدة وأقل تركيز، وتجنّب الوجه والثنيات إلا بتعليمات.",
         preg="C", ref="BNF for Children"),
    dict(name_ar="زنك أكسيد (موضعي)", name_en="Zinc oxide (topical)", cls="TOPIC",
         routes="topical", indications="التهاب الحفاض والوقاية منه.",
         precautions="يُدهن طبقة عازلة مع كل تغيير حفاض.", ref="EDA leaflet"),
    dict(name_ar="زيلوميتازولين (أنف)", name_en="Xylometazoline (nasal)", cls="RESP",
         atc="R01AA07", routes="nasal", min_age=24,
         indications="احتقان الأنف — لأقصر مدة ممكنة.",
         contraindications="أقل من سنتين، الاستخدام أكثر من 5 أيام (احتقان ارتدادي).",
         preg="C", ref="BNF for Children"),
    dict(name_ar="محلول ملحي للأنف", name_en="Saline nasal drops", cls="RESP",
         routes="nasal", indications="تنظيف الأنف عند الرضع — آمن في أي عمر.",
         ref="AAP",
         bands=[(0, None, "نقطة أو اتنين في كل فتحة عند اللزوم", None, None)]),
]

# --- third wave: the rest of what a paediatrician reaches for --------------
CLASSES += [
    ("NEURO", "أدوية المخ والأعصاب والتشنجات", "Neurology & anticonvulsants", "bi-activity", 55),
    ("EYEEAR", "قطرات العين والأذن", "Eye & ear drops", "bi-eye", 95),
]

GENERICS += [
    # ---- neurology / febrile convulsions ----
    dict(name_ar="ديازيبام", name_en="Diazepam", cls="NEURO", atc="N05BA01",
         routes="rectal, IV, oral", dose=(0.3, 0.5, "per_dose", 1, 1, 10, 10),
         indications="إيقاف التشنج الحراري أو النوبة المستمرة (شرجي في البيت).",
         contraindications="تثبيط تنفسي، فرط حساسية.",
         black_box="مثبط للتنفس — جرعة واحدة ثم طوارئ لو استمر التشنج.",
         preg="D", ref="BNF for Children",
         note="شرجي: 0.5 مج/كج (أقل من 3 سنوات) أو 0.3 مج/كج، جرعة واحدة."),
    dict(name_ar="فالبروات الصوديوم", name_en="Sodium valproate", cls="NEURO",
         atc="N03AG01", routes="oral", dose=(10, 15, "per_day", 2, 40, None, 2500),
         indications="الصرع بأنواعه (بوصفة أخصائي).",
         contraindications="أمراض الكبد، اضطرابات الميتوكوندريا، الحمل.",
         black_box="سمية كبدية والتهاب بنكرياس، وتشوهات جنينية — ممنوع في الفتيات بسن الإنجاب إلا بضوابط.",
         hepatic="ممنوع في القصور الكبدي.", monitoring="وظائف الكبد وصورة الدم",
         preg="X", ref="BNF for Children"),
    dict(name_ar="ليفيتيراسيتام", name_en="Levetiracetam", cls="NEURO", atc="N03AX14",
         routes="oral, IV", dose=(10, 30, "per_day", 2, 60, None, 3000),
         indications="الصرع (بوصفة أخصائي).",
         side="تغيّر مزاج وعصبية عند بعض الأطفال.",
         renal="تُخفَّض الجرعة في القصور الكلوي.", preg="C", ref="BNF for Children"),
    dict(name_ar="كاربامازيبين", name_en="Carbamazepine", cls="NEURO", atc="N03AF01",
         routes="oral", dose=(5, 10, "per_day", 2, 20, None, 1000),
         indications="الصرع البؤري (بوصفة أخصائي).",
         black_box="طفح جلدي شديد نادر — يُوقف فوراً عند أي طفح؛ ونقص كرات الدم.",
         monitoring="صورة دم ووظائف كبد", preg="D", ref="BNF for Children"),
    dict(name_ar="دايمينهيدرينات", name_en="Dimenhydrinate", cls="NEURO", atc="R06AA02",
         routes="oral", min_age=24, indications="دوار الحركة والغثيان.",
         contraindications="أقل من سنتين.", side="نعاس.", preg="B", ref="BNF for Children",
         bands=[(24, 71, "12.5–25 مج كل 6–8 ساعات", 25, 3),
                (72, 143, "25–50 مج كل 6–8 ساعات", 50, 3),
                (144, None, "50 مج كل 6–8 ساعات", 50, 3)]),
    # ---- respiratory / cough & cold ----
    dict(name_ar="ليفوسيتريزين", name_en="Levocetirizine", cls="ANTIH", atc="R06AE09",
         routes="oral", min_age=6, indications="حساسية الأنف والجلد.",
         renal="تُخفَّض الجرعة في القصور الكلوي.", preg="B", ref="BNF for Children",
         bands=[(6, 23, "1.25 مج مرة يومياً", 1.25, 1), (24, 71, "1.25 مج مرتين يومياً", 1.25, 2),
                (72, 143, "2.5 مج مرة يومياً", 2.5, 1), (144, None, "5 مج مرة يومياً", 5, 1)]),
    dict(name_ar="فيكسوفينادين", name_en="Fexofenadine", cls="ANTIH", atc="R06AX26",
         routes="oral", min_age=24, indications="حساسية الأنف — بلا نعاس تقريباً.",
         preg="C", ref="BNF for Children",
         bands=[(24, 143, "30 مج مرتين يومياً", 30, 2), (144, None, "120 مج مرة يومياً", 120, 1)]),
    dict(name_ar="كاربوسيستئين", name_en="Carbocisteine", cls="RESP", atc="R05CB03",
         routes="oral", min_age=24, indications="مذيب للبلغم.",
         contraindications="قرحة المعدة النشطة، أقل من سنتين.", ref="EDA leaflet",
         bands=[(24, 59, "62.5–125 مج 4 مرات يومياً", 125, 4),
                (60, 143, "250 مج 3 مرات يومياً", 250, 3),
                (144, None, "750 مج 3 مرات يومياً", 750, 3)]),
    dict(name_ar="بروميكسين", name_en="Bromhexine", cls="RESP", atc="R05CB02",
         routes="oral", min_age=24, indications="مذيب للبلغم.",
         contraindications="أقل من سنتين.", ref="EDA leaflet",
         bands=[(24, 71, "2 مج 3 مرات يومياً", 2, 3), (72, 143, "4 مج 3 مرات يومياً", 4, 3),
                (144, None, "8 مج 3 مرات يومياً", 8, 3)]),
    dict(name_ar="ديكستروميثورفان", name_en="Dextromethorphan", cls="RESP",
         atc="R05DA09", routes="oral", min_age=72,
         indications="كحة جافة مزعجة — لا يُستخدم مع الكحة المنتجة للبلغم.",
         contraindications="أقل من 6 سنوات، الربو النشط.",
         black_box="لا يُعطى لأقل من 6 سنوات: تقارير باختناق تنفسي وتسمم.",
         preg="C", ref="FDA / BNF for Children",
         bands=[(72, 143, "5–7.5 مج كل 6–8 ساعات", 7.5, 3),
                (144, None, "10–15 مج كل 6–8 ساعات", 15, 3)]),
    dict(name_ar="محلول ملحي مركّز 3%", name_en="Hypertonic saline 3%", cls="RESP",
         routes="nebulised", indications="التهاب الشعيبات (bronchiolitis) للتخفيف من الأعراض.",
         precautions="يُعطى بالنبيولايزر تحت ملاحظة — قد يسبب كحة أو تضييق مؤقت.",
         ref="AAP", bands=[(0, None, "4 مل بالنبيولايزر عند اللزوم", None, 3)]),
    dict(name_ar="موميتازون (أنف)", name_en="Mometasone (nasal)", cls="RESP",
         atc="R01AD09", routes="nasal", min_age=24,
         indications="حساسية الأنف المزمنة.",
         precautions="الاستخدام المنتظم لأسابيع هو ما يُحدث الفرق.", preg="C",
         ref="BNF for Children",
         bands=[(24, 143, "بخة واحدة في كل فتحة يومياً", None, 1),
                (144, None, "بختان في كل فتحة يومياً", None, 1)]),
    dict(name_ar="أوكسي ميتازولين (أنف)", name_en="Oxymetazoline (nasal)", cls="RESP",
         atc="R01AA05", routes="nasal", min_age=72,
         indications="احتقان الأنف — لأقصر مدة.",
         contraindications="أقل من 6 سنوات، الاستخدام أكثر من 3–5 أيام.",
         preg="C", ref="BNF for Children"),
    # ---- antibiotics & antimicrobials ----
    dict(name_ar="سيفاليكسين", name_en="Cephalexin", cls="ABX", atc="J01DB01",
         routes="oral", dose=(25, 50, "per_day", 3, 100, 1000, 4000),
         indications="التهابات الجلد والحلق والبول.",
         contraindications="حساسية السيفالوسبورينات.", renal="تُعدَّل في القصور الكلوي.",
         preg="B", ref="BNF for Children"),
    dict(name_ar="كليندامايسين", name_en="Clindamycin", cls="ABX", atc="J01FF01",
         routes="oral, IV", dose=(20, 30, "per_day", 3, 40, 600, 1800),
         indications="التهابات الجلد والعظام واللاهوائيات.",
         black_box="التهاب قولون بالمطثية العسيرة — أي إسهال شديد يستدعي الإيقاف.",
         preg="B", ref="BNF for Children"),
    dict(name_ar="دوكسيسيكلين", name_en="Doxycycline", cls="ABX", atc="J01AA02",
         routes="oral", dose=(2, 4, "per_day", 2, 4, 100, 200), min_age=96,
         indications="حالات خاصة (الحمى المالطية، الريكتسيا) بقرار الطبيب.",
         contraindications="أقل من 8 سنوات (تصبّغ الأسنان) إلا للضرورة، الحمل.",
         preg="D", ref="BNF for Children"),
    dict(name_ar="سيبروفلوكساسين", name_en="Ciprofloxacin", cls="ABX", atc="J01MA02",
         routes="oral, IV", dose=(20, 30, "per_day", 2, 40, 750, 1500),
         indications="حالات محددة (بول معقّد، تيفود) بقرار الطبيب.",
         contraindications="الاستخدام الروتيني في الأطفال.",
         black_box="التهاب وتمزق الأوتار واعتلال الأعصاب — يُقصر على دواعٍ محددة.",
         preg="C", ref="BNF for Children"),
    # ---- GI ----
    dict(name_ar="إيزوميبرازول", name_en="Esomeprazole", cls="GIT", atc="A02BC05",
         routes="oral", dose=(0.5, 1, "per_day", 1, 2, 20, 40), min_age=12,
         indications="الارتجاع المريئي المقاوم.", hepatic="تُقلَّل في القصور الكبدي.",
         preg="B", ref="BNF for Children"),
    dict(name_ar="هيوسين بيوتيل بروميد", name_en="Hyoscine butylbromide", cls="GIT",
         atc="A03BB01", routes="oral", min_age=72,
         indications="المغص المعوي التشنجي.",
         contraindications="أقل من 6 سنوات بلا وصفة، الجلوكوما، انسداد معوي.",
         preg="C", ref="BNF for Children",
         bands=[(72, 143, "10 مج حتى 3 مرات يومياً", 10, 3),
                (144, None, "10–20 مج حتى 4 مرات يومياً", 20, 4)]),
    dict(name_ar="تريميبوتين", name_en="Trimebutine", cls="GIT", atc="A03AA05",
         routes="oral", min_age=6, indications="اضطرابات حركة الأمعاء والمغص.",
         ref="EDA leaflet",
         bands=[(6, 59, "1 مل/كج/اليوم مقسّمة على 3 مرات", None, 3),
                (60, None, "24 مج 3 مرات يومياً", 24, 3)]),
    dict(name_ar="ساكاروميسس بولاردي", name_en="Saccharomyces boulardii", cls="ORS",
         routes="oral", indications="الإسهال الحاد والإسهال المصاحب للمضاد الحيوي.",
         contraindications="نقص المناعة الشديد أو قسطرة وريدية مركزية.",
         ref="ESPGHAN",
         bands=[(0, 23, "250 مج يومياً", 250, 1), (24, None, "250 مج مرتين يومياً", 250, 2)]),
    dict(name_ar="جليسرين (لبوس)", name_en="Glycerin suppository", cls="GIT",
         routes="rectal", indications="إمساك عارض — تفريغ سريع.",
         precautions="للاستخدام العارض فقط وليس علاجاً للإمساك المزمن.", ref="BNF for Children",
         bands=[(0, 11, "لبوس أطفال عند اللزوم", None, 1),
                (12, None, "لبوس أطفال عند اللزوم", None, 1)]),
    dict(name_ar="أورسوديوكسي كوليك أسيد", name_en="Ursodeoxycholic acid", cls="GIT",
         atc="A05AA02", routes="oral", dose=(10, 20, "per_day", 2, 30, None, 1000),
         indications="ركود صفراوي وأمراض كبدية بقرار الأخصائي.",
         hepatic="بمتابعة وظائف الكبد.", preg="B", ref="BNF for Children"),
    # ---- eye & ear ----
    dict(name_ar="كلورامفينيكول (قطرة عين)", name_en="Chloramphenicol (eye)",
         cls="EYEEAR", atc="S01AA01", routes="ophthalmic",
         indications="التهاب الملتحمة البكتيري.",
         precautions="نقطة كل 2–6 ساعات حسب الشدة، وتُرمى العبوة بعد 28 يوماً.",
         preg="C", ref="BNF for Children",
         bands=[(0, None, "نقطة في العين المصابة كل 2–6 ساعات", None, 4)]),
    dict(name_ar="توبراميسين (قطرة عين)", name_en="Tobramycin (eye)", cls="EYEEAR",
         atc="S01AA12", routes="ophthalmic", indications="التهاب الملتحمة البكتيري.",
         preg="B", ref="BNF for Children",
         bands=[(0, None, "نقطة كل 4 ساعات", None, 4)]),
    dict(name_ar="أولوباتادين (قطرة عين)", name_en="Olopatadine (eye)", cls="EYEEAR",
         atc="S01GX09", routes="ophthalmic", min_age=36,
         indications="التهاب الملتحمة التحسسي.", preg="C", ref="BNF for Children",
         bands=[(36, None, "نقطة مرتين يومياً", None, 2)]),
    dict(name_ar="أوفلوكساسين (قطرة أذن)", name_en="Ofloxacin (otic)", cls="EYEEAR",
         atc="S02AA16", routes="otic", min_age=12,
         indications="التهاب الأذن الخارجية والوسطى مع ثقب/أنبوبة.",
         preg="C", ref="BNF for Children",
         bands=[(12, None, "5 نقاط في الأذن المصابة مرتين يومياً", None, 2)]),
    dict(name_ar="مسكن أذن موضعي (ليدوكايين/فينازون)", name_en="Otic analgesic drops",
         cls="EYEEAR", routes="otic", min_age=6,
         indications="تسكين ألم الأذن مع طبلة سليمة.",
         contraindications="ثقب الطبلة أو وجود إفرازات.", ref="EDA leaflet",
         bands=[(6, None, "3–4 نقاط عند اللزوم", None, 4)]),
    # ---- skin ----
    dict(name_ar="موبيروسين (موضعي)", name_en="Mupirocin (topical)", cls="TOPIC",
         atc="D06AX09", routes="topical",
         indications="القوباء والتهابات الجلد السطحية.",
         precautions="3 مرات يومياً لمدة 5–7 أيام.", preg="B", ref="BNF for Children"),
    dict(name_ar="ميثيل بريدنيزولون أسيبونات (موضعي)",
         name_en="Methylprednisolone aceponate (topical)", cls="TOPIC", atc="D07AC14",
         routes="topical", min_age=48,
         indications="الإكزيما المتوسطة.",
         precautions="مرة يومياً ولمدة محدودة، ويُتجنّب الوجه إلا بتعليمات.",
         preg="C", ref="BNF for Children"),
    dict(name_ar="بيتاميثازون (موضعي)", name_en="Betamethasone (topical)", cls="TOPIC",
         atc="D07AC01", routes="topical", min_age=12,
         indications="الإكزيما والالتهابات الجلدية المقاومة.",
         contraindications="الوجه والثنيات في الأطفال الصغار، العدوى غير المغطاة.",
         precautions="كورتيزون قوي — أقصر مدة وأقل مساحة.", preg="C",
         ref="BNF for Children"),
    dict(name_ar="كيتوكونازول (موضعي)", name_en="Ketoconazole (topical)", cls="ANTIF",
         atc="D01AC08", routes="topical",
         indications="فطريات الجلد وقشرة فروة الرأس (الشامبو).",
         preg="C", ref="BNF for Children"),
    dict(name_ar="كالامين (موضعي)", name_en="Calamine lotion", cls="TOPIC",
         routes="topical", indications="تهدئة الحكة (جدري الماء، لدغ الحشرات).",
         precautions="موضعي مهدّئ فقط — لا يعالج السبب.", ref="EDA leaflet"),
    dict(name_ar="جل التسنين (كاموميل)", name_en="Teething gel (chamomile)",
         cls="TOPIC", routes="topical (oral)", min_age=3,
         indications="تهدئة ألم التسنين.",
         contraindications="المستحضرات المحتوية على ليدوكايين أو ساليسيلات لأقل من سنتين.",
         precautions="كمية صغيرة على اللثة عند اللزوم.", ref="EDA leaflet"),
    # ---- vitamins & supplements ----
    dict(name_ar="مالتي فيتامين شراب", name_en="Multivitamin syrup", cls="VIT",
         routes="oral", indications="دعم عام عند ضعف التغذية أو النقاهة.",
         precautions="لا يُجمع مع مكملات أخرى تحتوي نفس الفيتامينات.", ref="EDA leaflet",
         bands=[(0, 23, "قطارة/2.5 مل يومياً", None, 1), (24, None, "5 مل يومياً", None, 1)]),
    dict(name_ar="ل-كارنيتين", name_en="L-carnitine", cls="VIT", atc="A16AA01",
         routes="oral", dose=(50, 100, "per_day", 3, 100, None, 3000),
         indications="نقص الكارنيتين وبعض أمراض الأيض (بقرار أخصائي).",
         preg="B", ref="BNF for Children"),
    dict(name_ar="أوميجا 3", name_en="Omega-3 (fish oil)", cls="VIT", routes="oral",
         indications="مكمل غذائي — دعم النمو والتركيز.",
         precautions="حذر مع أدوية سيولة الدم.", ref="EDA leaflet",
         bands=[(24, 143, "5 مل يومياً", None, 1), (144, None, "5–10 مل يومياً", None, 1)]),
    dict(name_ar="ليسين (فاتح شهية)", name_en="Lysine (appetite)", cls="VIT",
         routes="oral", indications="ضعف الشهية والنقاهة.",
         precautions="مكمل غذائي — يُراجع سبب ضعف الشهية أولاً.", ref="EDA leaflet",
         bands=[(12, 71, "2.5–5 مل يومياً", None, 1), (72, None, "5–10 مل يومياً", None, 1)]),
    dict(name_ar="مغنيسيوم", name_en="Magnesium", cls="VIT", routes="oral",
         indications="نقص المغنيسيوم، تقلصات العضلات.",
         renal="حذر في القصور الكلوي.", ref="BNF for Children",
         bands=[(24, None, "حسب المستحضر ووزن الطفل", None, 1)]),
]

# (trade_name, generic_en, form, strength, conc_mg_per_ml, manufacturer)
BRANDS = [
    ("Cetal", "Paracetamol", "syrup", "120 mg/5 ml", 24, "Epico"),
    ("Cetal Forte", "Paracetamol", "syrup", "250 mg/5 ml", 50, "Epico"),
    ("Abimol", "Paracetamol", "syrup", "120 mg/5 ml", 24, "Amoun"),
    ("Paramol", "Paracetamol", "suppository", "125 mg", None, "Sedico"),
    ("Brufen", "Ibuprofen", "syrup", "100 mg/5 ml", 20, "Kahira"),
    ("Nurofen", "Ibuprofen", "syrup", "100 mg/5 ml", 20, "Reckitt"),
    ("Megamox", "Amoxicillin", "syrup", "250 mg/5 ml", 50, "Amoun"),
    ("E-Mox", "Amoxicillin", "syrup", "125 mg/5 ml", 25, "Epico"),
    ("Hibiotic", "Amoxicillin/Clavulanate", "syrup", "457 mg/5 ml", 80, "Amoun"),
    ("Augmentin", "Amoxicillin/Clavulanate", "syrup", "312 mg/5 ml", 50, "GSK"),
    ("Zisrocin", "Azithromycin", "syrup", "200 mg/5 ml", 40, "Kahira"),
    ("Zithromax", "Azithromycin", "syrup", "200 mg/5 ml", 40, "Pfizer"),
    ("Klacid", "Clarithromycin", "syrup", "125 mg/5 ml", 25, "Abbott"),
    ("Suprax", "Cefixime", "syrup", "100 mg/5 ml", 20, "Sanofi"),
    ("Ceftriaxone", "Ceftriaxone", "injection", "500 mg vial", None, "Various"),
    ("Zinnat", "Cefuroxime", "syrup", "125 mg/5 ml", 25, "GSK"),
    ("Zyrtec", "Cetirizine", "drops", "10 mg/ml", 10, "UCB"),
    ("Alerid", "Cetirizine", "syrup", "5 mg/5 ml", 1, "Cipla"),
    ("Claritine", "Loratadine", "syrup", "5 mg/5 ml", 1, "Bayer"),
    ("Ventolin", "Salbutamol", "inhaler", "100 mcg/puff", None, "GSK"),
    ("Farcolin", "Salbutamol", "nebuliser solution", "5 mg/ml", 5, "Pharco"),
    ("Singulair", "Montelukast", "granules/tablet", "4 mg", None, "MSD"),
    ("Hostacortin", "Prednisolone", "tablet", "5 mg", None, "Kahira"),
    ("Solupred", "Prednisolone", "syrup", "15 mg/5 ml", 3, "Sanofi"),
    ("Fortecortin", "Dexamethasone", "ampoule", "8 mg/2 ml", 4, "Merck"),
    ("Losec", "Omeprazole", "capsule", "20 mg", None, "AstraZeneca"),
    ("Zofran", "Ondansetron", "syrup", "4 mg/5 ml", 0.8, "Novartis"),
    ("Motilium", "Domperidone", "suspension", "5 mg/5 ml", 1, "Janssen"),
    ("Rehydran", "Oral rehydration salts (ORS)", "sachet", "WHO formula", None, "Various"),
    ("Zincotone", "Zinc sulfate", "syrup", "15 mg/5 ml", 3, "Eva"),
    ("Vidrop", "Vitamin D (cholecalciferol)", "drops", "2800 IU/ml", None, "Medical Union"),
    ("Ferro-Sanol", "Elemental iron", "drops", "30 mg/ml", 30, "Sanofi"),
    ("Mycostatin", "Nystatin", "oral suspension", "100,000 IU/ml", None, "BMS"),
    ("Diflucan", "Fluconazole", "syrup", "50 mg/5 ml", 10, "Pfizer"),
    ("Zovirax", "Aciclovir", "suspension", "200 mg/5 ml", 40, "GSK"),
    ("Alzental", "Albendazole", "suspension", "200 mg/5 ml", 40, "Eipico"),
    ("Flagyl", "Metronidazole", "suspension", "125 mg/5 ml", 25, "Sanofi"),
]

# --- second wave: more of what an Egyptian pharmacy actually stocks ---------
BRANDS += [
    ("Adol", "Paracetamol", "syrup", "120 mg/5 ml", 24, "Julphar"),
    ("Panadol Baby", "Paracetamol", "syrup", "120 mg/5 ml", 24, "GSK"),
    ("Cetal", "Paracetamol", "suppository", "250 mg", None, "Epico"),
    ("Temp", "Paracetamol", "suppository", "125 mg", None, "Amoun"),
    ("Perfalgan", "Paracetamol", "infusion", "10 mg/ml", 10, "BMS"),
    ("Ibubrufen", "Ibuprofen", "syrup", "200 mg/5 ml", 40, "Kahira"),
    ("Ibucap", "Ibuprofen", "suspension", "100 mg/5 ml", 20, "Sedico"),
    ("Cataflam", "Diclofenac", "tablet", "25 mg", None, "Novartis"),
    ("Voltaren", "Diclofenac", "suppository", "12.5 mg", None, "Novartis"),
    ("Ponstan", "Mefenamic acid", "suspension", "50 mg/5 ml", 10, "Pfizer"),
    ("Luminal", "Phenobarbital", "tablet", "15 mg", None, "Kahira"),
    ("Amoxil", "Amoxicillin", "syrup", "250 mg/5 ml", 50, "GSK"),
    ("Julmentin", "Amoxicillin/Clavulanate", "syrup", "312 mg/5 ml", 50, "Julphar"),
    ("Curam", "Amoxicillin/Clavulanate", "syrup", "457 mg/5 ml", 80, "Sandoz"),
    ("Augmentin ES", "Amoxicillin/Clavulanate", "syrup", "642 mg/5 ml", 120, "GSK"),
    ("Unictam", "Ampicillin", "vial", "375 mg", None, "Amoun"),
    ("Flumox", "Flucloxacillin", "syrup", "250 mg/5 ml", 50, "Epico"),
    ("Ceclor", "Cefaclor", "syrup", "125 mg/5 ml", 25, "Lilly"),
    ("Curisafe", "Cefadroxil", "syrup", "250 mg/5 ml", 50, "Amoun"),
    ("Duricef", "Cefadroxil", "syrup", "250 mg/5 ml", 50, "BMS"),
    ("Orelox", "Cefpodoxime", "syrup", "40 mg/5 ml", 8, "Sanofi"),
    ("Cefotax", "Ceftriaxone", "vial", "1 g", None, "Egyptian Int. Pharma"),
    ("Xorin", "Cefuroxime", "syrup", "250 mg/5 ml", 50, "Amoun"),
    ("Septrin", "Co-trimoxazole", "suspension", "240 mg/5 ml", 48, "GSK"),
    ("Sutrim", "Co-trimoxazole", "suspension", "240 mg/5 ml", 48, "Kahira"),
    ("Uvamin", "Nitrofurantoin", "capsule", "100 mg", None, "Amoun"),
    ("Vancomycin", "Vancomycin", "vial", "500 mg", None, "Various"),
    ("Garamycin", "Gentamicin", "ampoule", "20 mg/2 ml", 10, "Schering"),
    ("Zithrokan", "Azithromycin", "syrup", "200 mg/5 ml", 40, "Marcyrl"),
    ("Xithrone", "Azithromycin", "syrup", "200 mg/5 ml", 40, "Hikma"),
    ("Klaricid", "Clarithromycin", "syrup", "250 mg/5 ml", 50, "Abbott"),
    ("Cefix", "Cefixime", "syrup", "100 mg/5 ml", 20, "Marcyrl"),
    ("Winex", "Cefixime", "syrup", "100 mg/5 ml", 20, "Kahira"),
    ("Aerius", "Desloratadine", "syrup", "2.5 mg/5 ml", 0.5, "MSD"),
    ("Histazine", "Chlorpheniramine", "syrup", "2 mg/5 ml", 0.4, "Kahira"),
    ("Allergex", "Chlorpheniramine", "tablet", "4 mg", None, "Egyptian Group"),
    ("Zaditen", "Ketotifen", "syrup", "1 mg/5 ml", 0.2, "Novartis"),
    ("Cetrizal", "Cetirizine", "syrup", "5 mg/5 ml", 1, "Amoun"),
    ("Lorine", "Loratadine", "syrup", "5 mg/5 ml", 1, "Amoun"),
    ("Pulmicort", "Budesonide (inhaled)", "nebuliser respule", "0.5 mg/2 ml", 0.25, "AstraZeneca"),
    ("Miflonide", "Budesonide (inhaled)", "inhaler capsule", "200 mcg", None, "Novartis"),
    ("Flixotide", "Fluticasone (inhaled)", "inhaler", "50 mcg/puff", None, "GSK"),
    ("Atrovent", "Ipratropium", "nebuliser solution", "250 mcg/ml", None, "Boehringer"),
    ("Butakort", "Budesonide (inhaled)", "nebuliser respule", "0.5 mg/2 ml", 0.25, "Sigma"),
    ("Mucosolvan", "Ambroxol", "syrup", "15 mg/5 ml", 3, "Boehringer"),
    ("Mucophylline", "Ambroxol", "syrup", "15 mg/5 ml", 3, "Sedico"),
    ("Fluimucil", "Acetylcysteine", "sachet", "100 mg", None, "Zambon"),
    ("Solu-Cortef", "Hydrocortisone", "vial", "100 mg", None, "Pfizer"),
    ("Predsol", "Prednisolone", "syrup", "15 mg/5 ml", 3, "Kahira"),
    ("Dexazone", "Dexamethasone", "ampoule", "8 mg/2 ml", 4, "Kahira"),
    ("Disflatyl", "Simethicone", "drops", "40 mg/ml", 40, "Amoun"),
    ("Infacol", "Simethicone", "drops", "40 mg/ml", 40, "Forest"),
    ("Duphalac", "Lactulose", "syrup", "10 g/15 ml", None, "Abbott"),
    ("Lactulose", "Lactulose", "syrup", "10 g/15 ml", None, "Egyptian Group"),
    ("Movicol Junior", "Polyethylene glycol (macrogol)", "sachet", "6.9 g", None, "Norgine"),
    ("Hidrasec", "Racecadotril", "sachet", "30 mg", None, "Bioprojet"),
    ("Antinal", "Racecadotril", "sachet", "30 mg", None, "Amoun"),
    ("Lacteol Fort", "Probiotic (Lactobacillus)", "sachet", "10 billion", None, "Adam Pharma"),
    ("Bacillac", "Probiotic (Lactobacillus)", "sachet", "1.5 billion", None, "Kahira"),
    ("Rehydran N", "Oral rehydration salts (ORS)", "sachet", "WHO formula", None, "Sedico"),
    ("Hydrasal", "Oral rehydration salts (ORS)", "sachet", "WHO formula", None, "Amoun"),
    ("Zinc Plus", "Zinc sulfate", "syrup", "15 mg/5 ml", 3, "Amoun"),
    ("Devarol S", "Vitamin D (cholecalciferol)", "ampoule", "200,000 IU", None, "Memphis"),
    ("Ossofortin", "Calcium with vitamin D", "syrup", "—", None, "Sedico"),
    ("Calcimate", "Calcium with vitamin D", "syrup", "—", None, "Kahira"),
    ("A-D Vit", "Vitamins A + D", "drops", "—", None, "Memphis"),
    ("Folicap", "Folic acid", "capsule", "500 mcg", None, "Sedico"),
    ("Neuroton", "Vitamin B complex", "syrup", "—", None, "Kahira"),
    ("Haemojet", "Elemental iron", "syrup", "—", None, "Marcyrl"),
    ("Ferrofol", "Elemental iron", "capsule", "—", None, "Sedico"),
    ("Canesten", "Clotrimazole (topical)", "cream", "1%", None, "Bayer"),
    ("Dermatin", "Clotrimazole (topical)", "cream", "1%", None, "Kahira"),
    ("Daktarin Oral Gel", "Miconazole oral gel", "oral gel", "2%", None, "Janssen"),
    ("Nystatin", "Nystatin", "oral suspension", "100,000 IU/ml", None, "Kahira"),
    ("Tamiflu", "Oseltamivir", "suspension", "6 mg/ml", 6, "Roche"),
    ("Vermox", "Mebendazole", "suspension", "100 mg/5 ml", 20, "Janssen"),
    ("Antiver", "Mebendazole", "suspension", "100 mg/5 ml", 20, "Kahira"),
    ("Distocide", "Praziquantel", "tablet", "600 mg", None, "Epico"),
    ("Zentel", "Albendazole", "suspension", "200 mg/5 ml", 40, "GSK"),
    ("Flagyl", "Metronidazole", "suspension", "125 mg/5 ml", 25, "Sanofi"),
    ("Amrizole", "Metronidazole", "suspension", "125 mg/5 ml", 25, "Amoun"),
    ("Lyclear", "Permethrin (topical)", "cream", "5%", None, "Sedico"),
    ("Kwell", "Permethrin (topical)", "lotion", "1%", None, "Egyptian Group"),
    ("Fucidin", "Fusidic acid (topical)", "cream", "2%", None, "Leo Pharma"),
    ("Fucicort", "Fusidic acid (topical)", "cream", "2% + steroid", None, "Leo Pharma"),
    ("Cortizone", "Hydrocortisone (topical)", "cream", "1%", None, "Kahira"),
    ("Sudocrem", "Zinc oxide (topical)", "cream", "15.25%", None, "Teva"),
    ("Zincoderm", "Zinc oxide (topical)", "cream", "—", None, "Amoun"),
    ("Otrivin Baby", "Saline nasal drops", "nasal drops", "0.9%", None, "Novartis"),
    ("Sinomarin", "Saline nasal drops", "nasal spray", "seawater", None, "Gerolymatos"),
    ("Otrivin", "Xylometazoline (nasal)", "nasal drops", "0.05%", None, "Novartis"),
    ("Zofran", "Ondansetron", "ampoule", "4 mg/2 ml", 2, "Novartis"),
    ("Ondansetron", "Ondansetron", "syrup", "4 mg/5 ml", 0.8, "Egyptian Group"),
    ("Dompy", "Domperidone", "suspension", "5 mg/5 ml", 1, "Amoun"),
    ("Omez", "Omeprazole", "capsule", "20 mg", None, "Dr Reddy's"),
    ("Gastrazole", "Omeprazole", "capsule", "20 mg", None, "Sedico"),
    ("Diflucan", "Fluconazole", "capsule", "50 mg", None, "Pfizer"),
    ("Flucoral", "Fluconazole", "capsule", "150 mg", None, "Amoun"),
    ("Acyclovir", "Aciclovir", "cream", "5%", None, "Egyptian Group"),
    ("Virolex", "Aciclovir", "suspension", "200 mg/5 ml", 40, "Krka"),
    ("Singulair", "Montelukast", "chewable tablet", "5 mg", None, "MSD"),
    ("Montelo", "Montelukast", "granules", "4 mg", None, "Amoun"),
    ("Ventolin", "Salbutamol", "nebuliser solution", "5 mg/ml", 5, "GSK"),
    ("Butamol", "Salbutamol", "syrup", "2 mg/5 ml", 0.4, "Sigma"),
]

# --- third wave: the ingredients the register kept asking for ---------------
#
# Chosen by measurement, not by taste. After the whole Egyptian register is
# seeded, these are the single-ingredient names carrying the most trade names
# that this reference could not dose — filtered to what a paediatric clinic
# actually gives.
#
# The count on each is how many boxes it *actually* reaches, re-measured after
# the entry was written. Several are far lower than the register's raw label
# count suggested, because the register writes a salt ("HYDROXYZINE
# HYDROCHLORIDE") or spaces a word differently ("PHENOXYMETHYL PENICILLIN").
# Those are left honest rather than padded: an entry that reaches nothing today
# still carries a correct dose for the day somebody types that drug by hand.
#
# Deliberately NOT added, and the reason matters as much as the additions:
# pregabalin (96), gabapentin (69), etoricoxib (66), meloxicam (35),
# piroxicam (34), moxifloxacin (57), linezolid (37) and vonoprazan (41) are
# large in the register and are not children's medicines. Ranitidine (45) was
# withdrawn worldwide over NDMA. Putting a paediatric dose beside any of them
# would be inventing a use, and the catalogue can hold a drug perfectly well
# without pretending to dose it.
#
# Every number below carries the reference it came from in `ref=`, so it can
# be checked against the source rather than trusted because it is on a screen.
GENERICS += [
    dict(  # 50 brands
        name_ar="سيفوتاكسيم", name_en="Cefotaxime", cls="ABX", atc="J01DD01",
        routes="IV, IM",
        dose=(100, 150, "per_day", 4, 180, None, 12000),
        indications="التهابات شديدة: التهاب سحائي، إنتان دم، التهاب رئوي يحتاج دخول.",
        contraindications="حساسية شديدة سابقة للسيفالوسبورينات.",
        precautions="جرعة التهاب السحايا أعلى (200 مج/كج/يوم) وتُقرَّر في المستشفى.",
        renal="تُباعد الجرعات مع نقص الترشيح الكبيبي.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
        note="كل 6–8 ساعات وريدياً.",
    ),
    dict(  # 34 brands
        name_ar="سيفتازيديم", name_en="Ceftazidime", cls="ABX", atc="J01DD02",
        routes="IV, IM",
        dose=(30, 100, "per_day", 3, 150, None, 6000),
        indications="التهابات بالزائفة الزنجارية، والحمى مع نقص المناعة.",
        contraindications="حساسية شديدة سابقة للسيفالوسبورينات.",
        precautions="يُحفظ للحالات التي تحتاجه — استخدامه الواسع يصنع مقاومة.",
        renal="يحتاج تعديلاً واضحاً في القصور الكلوي.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
    ),
    dict(  # 32 brands
        name_ar="سيفدينير", name_en="Cefdinir", cls="ABX", atc="J01DD15",
        routes="oral",
        dose=(14, 14, "per_day", 2, 14, None, 600),
        min_age=6,
        indications="التهاب الأذن الوسطى والجيوب والحلق واللوزتين.",
        contraindications="حساسية شديدة سابقة للسيفالوسبورينات.",
        precautions="مع الحديد أو مضادات الحموضة يقل امتصاصه — يُباعَد ساعتين.",
        side="براز أحمر اللون مع الحديد — غير مقلق ويخيف الأهل بلا داعٍ.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
    ),
    dict(  # 15 brands
        name_ar="إريثرومايسين", name_en="Erythromycin", cls="ABX", atc="J01FA01",
        routes="oral",
        dose=(30, 50, "per_day", 4, 50, None, 2000),
        indications="بديل البنسلين عند الحساسية، والسعال الديكي، والكلاميديا.",
        contraindications="حساسية للماكروليدات، أمراض كبد نشطة.",
        precautions="تفاعلات دوائية كثيرة (يثبّط CYP3A4) — راجع أدوية الطفل الأخرى.",
        black_box="تضخّم البواب التضيّقي في الرضّع أقل من 6 أسابيع — يُتجنَّب إلا لضرورة.",
        hepatic="يُتجنّب في القصور الكبدي.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
        note="كل 6 ساعات؛ يُفضّل مع الطعام لتقليل مغص المعدة.",
    ),
    dict(  # 0 brands today — the register writes it "PHENOXYMETHYL
           # PENICILLIN" with a space, on 3 products. Here for the
           # rheumatic-fever prophylaxis course, not for coverage.
        name_ar="فينوكسي ميثيل بنسللين", name_en="Phenoxymethylpenicillin",
        cls="ABX", atc="J01CE02", routes="oral",
        dose=(25, 50, "per_day", 4, 50, None, 2000),
        indications="التهاب اللوزتين بالسبحيات، والوقاية من الحمى الروماتيزمية.",
        contraindications="حساسية البنسلين.",
        precautions="كورس التهاب اللوزتين 10 أيام كاملة — تقصيره سبب الحمى الروماتيزمية.",
        preg="B", lact="آمن أثناء الرضاعة.", ref="BNF for Children",
        note="على معدة فارغة، كل 6 ساعات.",
    ),
    dict(  # 33 brands
        name_ar="تيربينافين", name_en="Terbinafine", cls="ANTIF", atc="D01BA02",
        routes="oral",
        min_age=24,
        indications="سعفة فروة الرأس والأظافر.",
        contraindications="مرض كبدي نشط.",
        precautions="يحتاج متابعة وظائف الكبد في الكورسات الطويلة.",
        monitoring="وظائف الكبد قبل البدء ثم كل 4–6 أسابيع.",
        hepatic="يُمنع في القصور الكبدي.",
        preg="B", lact="غير مفضّل — يُفرَز في اللبن.",
        ref="BNF for Children",
        note="بالوزن لا بالكيلو: أقل من 20 كجم = 62.5 مج، 20–40 كجم = 125 مج، "
             "أكثر من 40 كجم = 250 مج — مرة يومياً.",
    ),
    dict(  # 4 brands
        name_ar="جريزيوفولفين", name_en="Griseofulvin", cls="ANTIF", atc="D01BA01",
        routes="oral",
        dose=(10, 20, "per_day", 1, 20, None, 1000),
        min_age=24,
        indications="سعفة فروة الرأس — العلاج الأول في الأطفال.",
        contraindications="مرض كبدي، البورفيريا.",
        precautions="يُؤخذ مع طعام دسم (لبن كامل) وإلا لا يُمتَص.",
        hepatic="يُتجنّب في القصور الكبدي.",
        preg="X", lact="غير مفضّل.",
        ref="BNF for Children", note="كورس 6–8 أسابيع لفروة الرأس.",
    ),
    dict(  # 51 brands
        name_ar="بانتوبرازول", name_en="Pantoprazole", cls="GIT", atc="A02BC02",
        routes="oral, IV",
        dose=(1, 1, "per_day", 1, 1, None, 40),
        min_age=12,
        indications="الارتجاع المريئي وقرحة المعدة عند الأطفال.",
        contraindications="فرط الحساسية للمادة.",
        precautions="لا يُستمَر بلا مراجعة — الاستخدام الطويل يقلل امتصاص الحديد وB12.",
        preg="B", lact="بيانات محدودة.", ref="BNF for Children",
        note="قبل الإفطار بنصف ساعة.",
    ),
    dict(  # 3 brands
        name_ar="سيبروهيبتادين", name_en="Cyproheptadine", cls="ANTIH",
        atc="R06AX02", routes="oral",
        dose=(0.25, 0.25, "per_day", 3, 0.5, None, 16),
        min_age=24,
        indications="الحساسية، ويُستعمل كفاتح للشهية في الأطفال.",
        contraindications="أقل من سنتين، الجلوكوما، احتباس البول، نوبات الربو الحادة.",
        precautions="النعاس شائع. فتح الشهية مكسب مؤقت ولا يعالج سبب ضعف الأكل.",
        side="نعاس، جفاف الفم، زيادة وزن سريعة.",
        preg="B", lact="غير مفضّل — يقلل إدرار اللبن.",
        ref="BNF for Children",
        note="الحد الأقصى 12 مج/يوم من 2–6 سنوات، و16 مج/يوم من 7–14 سنة.",
    ),
    dict(  # 0 brands today — the register writes the salt,
           # "HYDROXYZINE HYDROCHLORIDE", on 2 products.
        name_ar="هيدروكسيزين", name_en="Hydroxyzine", cls="ANTIH", atc="N05BB01",
        routes="oral",
        dose=(1, 2, "per_day", 4, 2, None, 100),
        min_age=12,
        indications="الحكة الشديدة والأرتيكاريا، والتهدئة قبل الإجراءات.",
        contraindications="إطالة فترة QT، أقل من سنة.",
        precautions="يزيد النعاس مع أي مهدّئ آخر.",
        preg="C", lact="غير مفضّل.", ref="BNF for Children",
    ),
    dict(
        name_ar="أدرينالين (إبينفرين)", name_en="Adrenaline (epinephrine)",
        cls="ANTIH", atc="C01CA24", routes="IM",
        dose=(0.01, 0.01, "per_dose", 3, 0.03, 0.5, None),
        indications="الحساسية المفرطة (أنافيلاكسيس) — العلاج الأول ولا بديل له.",
        contraindications="لا يوجد مانع مطلق في الأنافيلاكسيس.",
        precautions="يُعطى في عضلة الفخذ الوحشية، ويُكرَّر بعد 5 دقائق لو لم يتحسّن.",
        black_box="التأخير في إعطائه هو سبب الوفاة في الأنافيلاكسيس — "
                  "لا يُنتظَر رد الفعل على مضاد الهيستامين أو الكورتيزون.",
        preg="C", lact="آمن.", ref="WHO / BNF for Children",
        note="0.01 مج/كج من تركيز 1:1000 عضلياً، بحد أقصى 0.5 مج للجرعة "
             "(0.3 مج تحت 6 سنوات).",
    ),
    dict(  # 65 brands
        name_ar="فيتامين ج (حمض الأسكوربيك)", name_en="Vitamin C (ascorbic acid)",
        cls="VIT", atc="A11GA01", routes="oral",
        indications="نقص فيتامين ج، ودعم امتصاص الحديد.",
        contraindications="حصوات الكلى بالأوكسالات، نقص G6PD بالجرعات العالية.",
        precautions="لا دليل على أنه يمنع نزلات البرد — لا يُوصف لهذا الغرض.",
        preg="A", lact="آمن.", ref="WHO",
        note="بالسن لا بالوزن: علاج النقص 100–300 مج يومياً مقسّمة، والوقاية أقل.",
    ),
    dict(
        name_ar="فيتامين أ", name_en="Vitamin A", cls="VIT", atc="A11CA01",
        routes="oral",
        indications="نقص فيتامين أ، والدعم في الحصبة حسب توصية منظمة الصحة.",
        contraindications="فرط فيتامين أ، الحمل بجرعات عالية.",
        black_box="الجرعة الزائدة تسبب ارتفاع الضغط داخل الجمجمة — "
                  "الجرعات الكبيرة تُعطى بالسن وبمواعيد محددة، لا يومياً.",
        preg="X", lact="آمن بالجرعات العادية.", ref="WHO",
        note="بالسن: 100,000 وحدة من 6–11 شهر، و200,000 وحدة من 12–59 شهر — "
             "جرعة واحدة تتكرر كل 4–6 شهور.",
    ),
    dict(  # 64 brands
        name_ar="بوفيدون أيودين", name_en="Povidone-iodine",
        cls="TOPIC", atc="D08AG02", routes="topical",
        indications="تطهير الجروح والسحجات قبل التضميد.",
        contraindications="حساسية اليود، أمراض الغدة الدرقية.",
        precautions="لا يُستعمل على مساحات واسعة أو حروق كبيرة.",
        black_box="في حديثي الولادة يُمتَص اليود عبر الجلد ويثبّط الغدة الدرقية — "
                  "يُتجنّب تماماً تحت شهر.",
        preg="C", lact="يُتجنّب على منطقة الثدي.", ref="WHO",
    ),
    # The two ingredients that made classifying ORAL CARE worth doing. 28 of
    # the register's 190 oral-care products carry a local anaesthetic or a
    # salicylate, several are sold as teething gels — DENTINOX, KAMISTAD,
    # MUNDISAL and PANSORAL are all on Egyptian shelves — and neither
    # ingredient had an entry here, so the catalogue held them with no class,
    # no warning, and no way for a doctor to find out.
    dict(
        name_ar="كولين ساليسيلات (جل فم)",
        name_en="Choline salicylate (oral gel)", cls="ORAL",
        atc="A01AD11", routes="topical",
        indications="قرح الفم وألم اللثة — للكبار فقط.",
        contraindications="تحت ١٦ سنة؛ حساسية الأسبرين.",
        black_box="ساليسيلات: ممنوع تحت ١٦ سنة لاحتمال متلازمة راي، "
                  "والامتصاص من غشاء الفم الملتهب أعلى من المتوقع. هيئة "
                  "الدواء البريطانية قصرته على ١٦ سنة فأكثر منذ ٢٠٠٩.",
        precautions="بيتباع هنا كجل تسنين، وده بالظبط الاستعمال اللي التقييد "
                    "اتعمل عشانه.",
        preg="C", lact="يُتجنب.",
        ref="MHRA Drug Safety Update 2009 / BNF for Children",
    ),
    dict(
        name_ar="بنزوكايين (جل فم)", name_en="Benzocaine (oral gel)",
        cls="ORAL", atc="N01BA05", routes="topical",
        indications="تخدير سطحي لألم اللثة أو قرحة الفم.",
        contraindications="تحت سنتين؛ نقص G6PD أو ميتهيموجلوبينية سابقة.",
        black_box="ميتهيموجلوبينية: هيئة الغذاء والدواء الأمريكية طلبت وقف "
                  "تسويق مستحضرات التسنين المحتوية على بنزوكايين للأطفال تحت "
                  "سنتين (٢٠١٨). الازرقاق بيظهر خلال دقايق لساعتين من "
                  "الاستعمال.",
        precautions="ازرقاق حوالين الفم أو في الأظافر بعد الاستعمال = طوارئ.",
        preg="C", lact="يُتجنب.",
        ref="FDA Drug Safety Communication 2018",
    ),
    dict(  # 0 brands, deliberately. The register has 38 plain
           # "LIDOCAINE", and plain lidocaine may be the injectable —
           # so the (topical) qualifier blocks the match on purpose.
        name_ar="ليدوكايين موضعي", name_en="Lidocaine (topical)", cls="TOPIC",
        atc="D04AB01", routes="topical",
        indications="تخدير موضعي سطحي قبل الوخز أو على قرحة الفم.",
        contraindications="حساسية المخدرات الموضعية الأميدية.",
        black_box="جل التسنين المحتوي على ليدوكايين يسبب ميتهيموجلوبينية "
                  "وتشنجات في الرضّع — هيئة الغذاء والدواء الأمريكية تحذّر من "
                  "استعماله تحت سنتين.",
        precautions="كمية صغيرة على مساحة محدودة فقط؛ الابتلاع المتكرر خطر.",
        preg="B", lact="آمن موضعياً.", ref="FDA / BNF for Children",
    ),
]

# --- third wave of trade names: more of the shelf, and more strengths ------
BRANDS += [
    # paracetamol / ibuprofen family
    ("Cetal", "Paracetamol", "syrup", "250 mg/5 ml", 50, "Epico"),
    ("Abimol", "Paracetamol", "suppository", "125 mg", None, "Amoun"),
    ("Abimol", "Paracetamol", "suppository", "250 mg", None, "Amoun"),
    ("Paramol", "Paracetamol", "suppository", "250 mg", None, "Sedico"),
    ("Panadol", "Paracetamol", "tablet", "500 mg", None, "GSK"),
    ("Adol", "Paracetamol", "suppository", "125 mg", None, "Julphar"),
    ("Pyral", "Paracetamol", "syrup", "120 mg/5 ml", 24, "Egyptian Group"),
    ("Temp", "Paracetamol", "suppository", "250 mg", None, "Amoun"),
    ("Brufen", "Ibuprofen", "suspension", "200 mg/5 ml", 40, "Kahira"),
    ("Nurofen", "Ibuprofen", "suspension", "200 mg/5 ml", 40, "Reckitt"),
    ("Ibuprofen", "Ibuprofen", "tablet", "400 mg", None, "Various"),
    ("Cataflam", "Diclofenac", "tablet", "50 mg", None, "Novartis"),
    ("Voltaren", "Diclofenac", "ampoule", "75 mg/3 ml", 25, "Novartis"),
    ("Olfen", "Diclofenac", "suppository", "12.5 mg", None, "Mepha"),
    ("Ponstan Forte", "Mefenamic acid", "tablet", "500 mg", None, "Pfizer"),
    # antibiotics — more strengths of the same lines
    ("E-Mox", "Amoxicillin", "syrup", "250 mg/5 ml", 50, "Epico"),
    ("Megamox", "Amoxicillin", "syrup", "125 mg/5 ml", 25, "Amoun"),
    ("Amoxil", "Amoxicillin", "capsule", "500 mg", None, "GSK"),
    ("Hibiotic", "Amoxicillin/Clavulanate", "syrup", "156 mg/5 ml", 25, "Amoun"),
    ("Hibiotic", "Amoxicillin/Clavulanate", "syrup", "312 mg/5 ml", 50, "Amoun"),
    ("Augmentin", "Amoxicillin/Clavulanate", "syrup", "156 mg/5 ml", 25, "GSK"),
    ("Augmentin", "Amoxicillin/Clavulanate", "syrup", "457 mg/5 ml", 80, "GSK"),
    ("Augmentin", "Amoxicillin/Clavulanate", "tablet", "1 g", None, "GSK"),
    ("Curam", "Amoxicillin/Clavulanate", "syrup", "312 mg/5 ml", 50, "Sandoz"),
    ("Klavox", "Amoxicillin/Clavulanate", "syrup", "457 mg/5 ml", 80, "Sedico"),
    ("Zisrocin", "Azithromycin", "syrup", "100 mg/5 ml", 20, "Kahira"),
    ("Zithromax", "Azithromycin", "syrup", "100 mg/5 ml", 20, "Pfizer"),
    ("Azrolid", "Azithromycin", "syrup", "200 mg/5 ml", 40, "Marcyrl"),
    ("Klacid", "Clarithromycin", "syrup", "250 mg/5 ml", 50, "Abbott"),
    ("Klaram", "Clarithromycin", "syrup", "125 mg/5 ml", 25, "Amoun"),
    ("Suprax", "Cefixime", "syrup", "100 mg/5 ml", 20, "Sanofi"),
    ("Suprax", "Cefixime", "capsule", "400 mg", None, "Sanofi"),
    ("Zinnat", "Cefuroxime", "syrup", "250 mg/5 ml", 50, "GSK"),
    ("Zinnat", "Cefuroxime", "tablet", "500 mg", None, "GSK"),
    ("Ceporex", "Cephalexin", "syrup", "250 mg/5 ml", 50, "GSK"),
    ("Keflex", "Cephalexin", "capsule", "500 mg", None, "Lilly"),
    ("Ibilex", "Cephalexin", "syrup", "125 mg/5 ml", 25, "Egyptian Group"),
    ("Dalacin C", "Clindamycin", "capsule", "150 mg", None, "Pfizer"),
    ("Clindam", "Clindamycin", "ampoule", "300 mg/2 ml", 150, "Amoun"),
    ("Vibramycin", "Doxycycline", "capsule", "100 mg", None, "Pfizer"),
    ("Ciprobay", "Ciprofloxacin", "tablet", "500 mg", None, "Bayer"),
    ("Ciprofar", "Ciprofloxacin", "tablet", "500 mg", None, "Pharco"),
    ("Rocephin", "Ceftriaxone", "vial", "1 g", None, "Roche"),
    ("Epicephin", "Ceftriaxone", "vial", "250 mg", None, "Epico"),
    ("Fortum", "Ceftriaxone", "vial", "500 mg", None, "GSK"),
    ("Flumox", "Flucloxacillin", "capsule", "500 mg", None, "Epico"),
    ("Ampicillin", "Ampicillin", "vial", "500 mg", None, "Various"),
    ("Septrin", "Co-trimoxazole", "tablet", "480 mg", None, "GSK"),
    ("Macrodantin", "Nitrofurantoin", "capsule", "50 mg", None, "Amoun"),
    # antihistamines
    ("Zyrtec", "Cetirizine", "syrup", "5 mg/5 ml", 1, "UCB"),
    ("Cetrizine", "Cetirizine", "drops", "10 mg/ml", 10, "Egyptian Group"),
    ("Xyzal", "Levocetirizine", "syrup", "2.5 mg/5 ml", 0.5, "UCB"),
    ("Levocet", "Levocetirizine", "drops", "5 mg/ml", 5, "Amoun"),
    ("Telfast", "Fexofenadine", "suspension", "30 mg/5 ml", 6, "Sanofi"),
    ("Fexo", "Fexofenadine", "tablet", "120 mg", None, "Amoun"),
    ("Aerius", "Desloratadine", "tablet", "5 mg", None, "MSD"),
    ("Claritine", "Loratadine", "tablet", "10 mg", None, "Bayer"),
    ("Zaditen", "Ketotifen", "tablet", "1 mg", None, "Novartis"),
    ("Allergyl", "Chlorpheniramine", "syrup", "2 mg/5 ml", 0.4, "Sedico"),
    # respiratory
    ("Ventolin", "Salbutamol", "syrup", "2 mg/5 ml", 0.4, "GSK"),
    ("Farcolin", "Salbutamol", "inhaler", "100 mcg/puff", None, "Pharco"),
    ("Salbovent", "Salbutamol", "nebuliser solution", "5 mg/ml", 5, "Amoun"),
    ("Aerovent", "Ipratropium", "nebuliser solution", "250 mcg/ml", None, "Sigma"),
    ("Combivent", "Ipratropium", "nebuliser solution", "with salbutamol", None, "Boehringer"),
    ("Pulmicort", "Budesonide (inhaled)", "nebuliser respule", "1 mg/2 ml", 0.5, "AstraZeneca"),
    ("Flixotide", "Fluticasone (inhaled)", "inhaler", "125 mcg/puff", None, "GSK"),
    ("Nasonex", "Mometasone (nasal)", "nasal spray", "50 mcg/dose", None, "MSD"),
    ("Momecort", "Mometasone (nasal)", "nasal spray", "50 mcg/dose", None, "Amoun"),
    ("Afrin", "Oxymetazoline (nasal)", "nasal spray", "0.05%", None, "MSD"),
    ("Sinustop", "Oxymetazoline (nasal)", "nasal drops", "0.025%", None, "Egyptian Group"),
    ("Mucosolvan", "Ambroxol", "drops", "7.5 mg/ml", 7.5, "Boehringer"),
    ("Ambrolyt", "Ambroxol", "syrup", "15 mg/5 ml", 3, "Amoun"),
    ("Rectoplexil", "Carbocisteine", "syrup", "125 mg/5 ml", 25, "Sanofi"),
    ("Mucofar", "Carbocisteine", "syrup", "250 mg/5 ml", 50, "Pharco"),
    ("Bisolvon", "Bromhexine", "syrup", "4 mg/5 ml", 0.8, "Boehringer"),
    ("Tussifed", "Dextromethorphan", "syrup", "10 mg/5 ml", 2, "Egyptian Group"),
    ("Fluimucil", "Acetylcysteine", "sachet", "200 mg", None, "Zambon"),
    ("Hypertonic Saline 3%", "Hypertonic saline 3%", "nebuliser solution", "3%", None, "Various"),
    ("Otrivin Baby Saline", "Saline nasal drops", "nasal drops", "0.9%", None, "Novartis"),
    ("Marimer", "Saline nasal drops", "nasal spray", "seawater", None, "Gilbert"),
    # GI
    ("Nexium", "Esomeprazole", "sachet", "10 mg", None, "AstraZeneca"),
    ("Esomex", "Esomeprazole", "capsule", "20 mg", None, "Amoun"),
    ("Buscopan", "Hyoscine butylbromide", "tablet", "10 mg", None, "Boehringer"),
    ("Visceralgine", "Trimebutine", "syrup", "24 mg/5 ml", 4.8, "Mepha"),
    ("Colospasmin", "Trimebutine", "syrup", "24 mg/5 ml", 4.8, "Sedico"),
    ("Motilium", "Domperidone", "tablet", "10 mg", None, "Janssen"),
    ("Zofran", "Ondansetron", "orodispersible tablet", "4 mg", None, "Novartis"),
    ("Danset", "Ondansetron", "syrup", "4 mg/5 ml", 0.8, "Amoun"),
    ("Enterogermina", "Probiotic (Lactobacillus)", "vial", "2 billion", None, "Sanofi"),
    ("Ultra-Levure", "Saccharomyces boulardii", "sachet", "250 mg", None, "Biocodex"),
    ("Bacterolact", "Saccharomyces boulardii", "sachet", "250 mg", None, "Amoun"),
    ("Glycerin Suppository", "Glycerin suppository", "suppository", "children", None, "Various"),
    ("Ursofalk", "Ursodeoxycholic acid", "suspension", "250 mg/5 ml", 50, "Falk"),
    ("Duphalac", "Lactulose", "sachet", "10 g", None, "Abbott"),
    ("Forlax Junior", "Polyethylene glycol (macrogol)", "sachet", "4 g", None, "Ipsen"),
    ("Antinal", "Racecadotril", "suspension", "—", None, "Amoun"),
    ("Smecta", "Racecadotril", "sachet", "3 g", None, "Ipsen"),
    ("Disflatyl", "Simethicone", "tablet", "40 mg", None, "Amoun"),
    # neurology
    ("Valium", "Diazepam", "tablet", "5 mg", None, "Roche"),
    ("Neuril", "Diazepam", "suppository", "5 mg", None, "Amoun"),
    ("Diazepam", "Diazepam", "rectal tube", "5 mg", None, "Various"),
    ("Depakine", "Sodium valproate", "syrup", "200 mg/5 ml", 40, "Sanofi"),
    ("Depakine Chrono", "Sodium valproate", "tablet", "500 mg", None, "Sanofi"),
    ("Keppra", "Levetiracetam", "syrup", "100 mg/ml", 100, "UCB"),
    ("Levetiracetam", "Levetiracetam", "tablet", "500 mg", None, "Various"),
    ("Tegretol", "Carbamazepine", "syrup", "100 mg/5 ml", 20, "Novartis"),
    ("Tegretol", "Carbamazepine", "tablet", "200 mg", None, "Novartis"),
    ("Dramenex", "Dimenhydrinate", "tablet", "50 mg", None, "Amoun"),
    ("Epanutin", "Phenobarbital", "syrup", "15 mg/5 ml", 3, "Pfizer"),
    # eye & ear
    ("Chloramphenicol", "Chloramphenicol (eye)", "eye drops", "0.5%", None, "Various"),
    ("Optichlor", "Chloramphenicol (eye)", "eye drops", "0.5%", None, "Egyptian Int. Pharma"),
    ("Tobrex", "Tobramycin (eye)", "eye drops", "0.3%", None, "Alcon"),
    ("Tobradex", "Tobramycin (eye)", "eye drops", "with dexamethasone", None, "Alcon"),
    ("Patanol", "Olopatadine (eye)", "eye drops", "0.1%", None, "Alcon"),
    ("Oflox", "Ofloxacin (otic)", "ear drops", "0.3%", None, "Amoun"),
    ("Otocalm", "Otic analgesic drops", "ear drops", "—", None, "Egyptian Group"),
    ("Otowaxol", "Otic analgesic drops", "ear drops", "—", None, "Norgine"),
    # skin
    ("Bactroban", "Mupirocin (topical)", "ointment", "2%", None, "GSK"),
    ("Mupiderm", "Mupirocin (topical)", "ointment", "2%", None, "Sedico"),
    ("Advantan", "Methylprednisolone aceponate (topical)", "cream", "0.1%", None, "Bayer"),
    ("Betaderm", "Betamethasone (topical)", "cream", "0.1%", None, "Kahira"),
    ("Diprosone", "Betamethasone (topical)", "cream", "0.05%", None, "Schering"),
    ("Nizoral", "Ketoconazole (topical)", "cream", "2%", None, "Janssen"),
    ("Ketofungol", "Ketoconazole (topical)", "shampoo", "2%", None, "Amoun"),
    ("Calamine Lotion", "Calamine lotion", "lotion", "—", None, "Various"),
    ("Dentinox", "Teething gel (chamomile)", "oral gel", "—", None, "Dentinox"),
    ("Kamistad Baby", "Teething gel (chamomile)", "oral gel", "—", None, "Stada"),
    ("Fucidin", "Fusidic acid (topical)", "ointment", "2%", None, "Leo Pharma"),
    ("Sudocrem", "Zinc oxide (topical)", "cream", "125 g", None, "Teva"),
    # vitamins & supplements
    ("Sanso Vit", "Multivitamin syrup", "syrup", "—", None, "Sedico"),
    ("Vitamount", "Multivitamin syrup", "syrup", "—", None, "Amoun"),
    ("Pharmaton Kiddi", "Multivitamin syrup", "syrup", "—", None, "Boehringer"),
    ("Carnitine", "L-carnitine", "syrup", "1 g/10 ml", 100, "Egyptian Group"),
    ("Omega Kids", "Omega-3 (fish oil)", "syrup", "—", None, "Various"),
    ("Appetiton", "Lysine (appetite)", "syrup", "—", None, "Sedico"),
    ("Magnesium", "Magnesium", "syrup", "—", None, "Various"),
    ("Vidrop", "Vitamin D (cholecalciferol)", "drops", "2800 IU/ml", None, "Medical Union"),
    ("Ferro Sanol", "Elemental iron", "syrup", "—", None, "Sanofi"),
    ("Hemojet", "Elemental iron", "drops", "—", None, "Marcyrl"),
    ("Folic Acid", "Folic acid", "tablet", "5 mg", None, "Various"),
    ("Zincotone", "Zinc sulfate", "drops", "—", None, "Eva"),
    # antifungal / antiviral / antiparasitic extras
    ("Mycostatin", "Nystatin", "oral drops", "100,000 IU/ml", None, "BMS"),
    ("Nystatin", "Nystatin", "vaginal/oral", "—", None, "Kahira"),
    ("Diflucan", "Fluconazole", "suspension", "50 mg/5 ml", 10, "Pfizer"),
    ("Zovirax", "Aciclovir", "cream", "5%", None, "GSK"),
    ("Tamiflu", "Oseltamivir", "capsule", "30 mg", None, "Roche"),
    ("Zentel", "Albendazole", "tablet", "400 mg", None, "GSK"),
    ("Alzental", "Albendazole", "tablet", "400 mg", None, "Eipico"),
    ("Vermox", "Mebendazole", "tablet", "100 mg", None, "Janssen"),
    ("Flagyl", "Metronidazole", "tablet", "500 mg", None, "Sanofi"),
    ("Lyclear", "Permethrin (topical)", "lotion", "5%", None, "Sedico"),
]


def seed_drug_classes():
    existing = {c.code for c in DrugClass.query.with_entities(DrugClass.code).all()}
    n = 0
    for code, ar, en, icon, order in CLASSES:
        if code in existing:
            continue
        db.session.add(DrugClass(code=code, name_ar=ar, name_en=en, icon=icon,
                                 sort_order=order, is_active=True))
        n += 1
    if n:
        db.session.flush()
    return n


def seed_generics():
    """Create the missing active ingredients (matched by English name)."""
    classes = {c.code: c.id for c in DrugClass.query.all()}
    existing = {g.name_en for g in
                GenericDrug.query.with_entities(GenericDrug.name_en).all()}
    n = 0
    for row in GENERICS:
        if row["name_en"] in existing:
            continue
        dose = row.get("dose") or (None,) * 7
        g = GenericDrug(
            class_id=classes.get(row.get("cls")),
            name_ar=row["name_ar"], name_en=row["name_en"],
            atc_code=row.get("atc"), routes=row.get("routes"),
            dose_per_kg=dose[0], dose_per_kg_max=dose[1],
            dose_basis=dose[2] or "per_dose", doses_per_day=dose[3],
            max_per_kg_day=dose[4], max_single_dose_mg=dose[5],
            max_daily_dose_mg=dose[6],
            dose_note=row.get("note"),
            min_age_months=row.get("min_age"), max_age_months=row.get("max_age"),
            indications=row.get("indications"),
            contraindications=row.get("contraindications"),
            precautions=row.get("precautions"), side_effects=row.get("side"),
            black_box=row.get("black_box"),
            renal_adjustment=row.get("renal"), hepatic_adjustment=row.get("hepatic"),
            # The reference screen has rendered this row since it was written
            # and it was always empty: the seeder never read the key. So
            # vancomycin — where trough levels are the whole safety of the
            # drug — carried its monitoring advice in the source and showed
            # nothing.
            monitoring=row.get("monitoring"),
            pregnancy_category=row.get("preg"), lactation_note=row.get("lact"),
            reference=row.get("ref"), is_active=True,
        )
        db.session.add(g)
        db.session.flush()
        for lo, hi, text, mg, per_day in row.get("bands", []):
            db.session.add(GenericDoseBand(
                generic_id=g.id, min_age_months=lo, max_age_months=hi,
                dose_text=text, dose_mg=mg, doses_per_day=per_day))
        n += 1
    if n:
        db.session.flush()
    return n


def seed_brands():
    """Create the missing trade names and attach them to their ingredient."""
    generics = {g.name_en: g for g in GenericDrug.query.all()}
    existing = {(d.trade_name, d.strength or "") for d in
                Drug.query.with_entities(Drug.trade_name, Drug.strength).all()}
    n = 0
    for trade, generic_en, form, strength, conc, maker in BRANDS:
        key = (trade, strength or "")
        if key in existing:
            continue
        existing.add(key)      # also guards repeats *inside* the seed list
        g = generics.get(generic_en)
        db.session.add(Drug(
            trade_name=trade, generic_name=generic_en,
            generic_id=g.id if g else None, form=form, strength=strength,
            conc_mg_per_ml=conc, manufacturer=maker,
            dose_per_kg=(g.dose_per_kg if g and g.dose_basis == "per_dose" else None),
            is_active=True,
        ))
        n += 1
    if n:
        db.session.flush()
    return n


def link_existing_drugs():
    """Attach drugs the clinic typed itself to a matching ingredient.

    Through the same spelling table the register import uses, so a drug a
    nurse typed as "Acyclovir" and one the register spells "ACICLOVIR" reach
    the same ingredient. Matching exactly here and loosely there would make
    whether a box carries a dose depend on who entered it.
    """
    from app.utils.ingredient_names import index_of, match, route_agrees

    table = index_of(GenericDrug.query.all())
    n = 0
    for d in Drug.query.filter(Drug.generic_id.is_(None)).all():
        found = match(d.generic_name, table)
        if found is not None and not route_agrees(d.route, found.routes):
            found = None
        if found is not None:
            d.generic_id = found.id
            n += 1
    return n


def seed_drugbook(force=False):
    """Seed classes → ingredients → trade names. Adds what is missing.

    **It used to stop dead the moment the clinic had a single ingredient.**
    The guard read "a fresh install only", and the effect was that the
    reference froze at whatever the clinic's first run produced: every
    ingredient added to this file afterwards — and the list has roughly
    doubled — never reached a clinic that had already run once. A doctor
    looked for ondansetron, or salbutamol, or vitamin D, and found nothing,
    while the same names sat in the source and in the Egyptian register beside
    it. Reported as *"ازاي الادوية دي مش موجودة عندنا"*, and every one of them
    was here.

    **Adding is safe and updating would not be**, which is the whole reason
    this can be a top-up. Every one of the four steps below is add-only: each
    skips a row that already exists and never writes over it. So a clinic that
    corrected a dose, renamed a brand or switched an ingredient off keeps every
    one of those decisions, and only gets the rows it never had.

    ``force`` is kept for the command that means "seed it again from scratch",
    and now differs from the default only in intent — there is nothing left for
    it to override.
    """
    return {
        "classes": seed_drug_classes(),
        "generics": seed_generics(),
        "brands": seed_brands(),
        "linked": link_existing_drugs(),
        "interactions": seed_interactions(),
    }


# (generic_a, generic_b, severity, note, alternative) — pairs a paediatric
# clinic actually runs into. Severity: mild | moderate | severe.
INTERACTIONS = [
    ("Azithromycin", "Domperidone", "severe",
     "الاثنان يطيلان فترة QT — الجمع بينهما يرفع خطر اضطراب نظم القلب.",
     "أوقف الدومبيريدون أو استخدم أموكسيسيللين بدل الأزيثروميسين."),
    ("Clarithromycin", "Domperidone", "severe",
     "إطالة QT مع تثبيط استقلاب الدومبيريدون — تركيزه يرتفع بشدة.",
     "أوقف الدومبيريدون، أو استخدم أموكسيسيللين/سيفيكسيم بدل الكلاريثروميسين."),
    ("Azithromycin", "Ondansetron", "moderate",
     "كلاهما يطيل QT — حذر خاصة مع الجفاف أو نقص البوتاسيوم.",
     "جرعة واحدة من الأوندانسيترون مع متابعة، أو مضاد حيوي غير ماكروليد."),
    ("Clarithromycin", "Ondansetron", "moderate",
     "إطالة QT مجتمعة.",
     "استبدل الماكروليد، أو اكتفِ بجرعة أوندانسيترون واحدة."),
    ("Ibuprofen", "Prednisolone", "moderate",
     "الاثنان يهيّجان المعدة — خطر النزف والقرحة يزيد.",
     "استخدم باراسيتامول لخفض الحرارة أثناء كورس الكورتيزون."),
    ("Ibuprofen", "Dexamethasone", "moderate",
     "تهيّج معدي مشترك مع الكورتيزون.",
     "باراسيتامول بدل الإيبوبروفين."),
    ("Elemental iron", "Omeprazole", "moderate",
     "تقليل حموضة المعدة يقلل امتصاص الحديد.",
     "باعد بينهما ساعتين على الأقل، وأعطِ الحديد مع فيتامين ج."),
    ("Elemental iron", "Zinc sulfate", "mild",
     "يتنافسان على الامتصاص عند إعطائهما معاً.",
     "باعد بين الجرعتين ساعتين."),
    ("Fluconazole", "Domperidone", "severe",
     "الفلوكونازول يرفع تركيز الدومبيريدون (إطالة QT).",
     "أوقف الدومبيريدون أثناء كورس الفلوكونازول."),
    ("Fluconazole", "Clarithromycin", "moderate",
     "إطالة QT وتداخل استقلابي.",
     "استخدم مضاداً حيوياً غير ماكروليد أثناء الفلوكونازول."),
    ("Metronidazole", "Fluconazole", "moderate",
     "احتمال إطالة QT عند الجمع.",
     "افصل الكورسين إن أمكن."),
    ("Amoxicillin/Clavulanate", "Amoxicillin", "severe",
     "ازدواج نفس المادة الفعالة — الجرعة تتضاعف بلا قصد.",
     "اكتب أحدهما فقط."),
    ("Paracetamol", "Ibuprofen", "mild",
     "التبادل بينهما شائع ومقبول، لكن التوقيت يجب أن يكون واضحاً للأم حتى لا تتكرر الجرعة.",
     "اكتب مواعيد كل دواء بوضوح، وتجنب المستحضرات المركّبة."),
    ("Ceftriaxone", "Amoxicillin/Clavulanate", "mild",
     "ازدواج تغطية بيتالاكتام بلا فائدة إضافية غالباً.",
     "اكتفِ بواحد حسب شدة الحالة."),
    ("Prednisolone", "Omeprazole", "mild",
     "يُستخدمان معاً عمداً أحياناً لحماية المعدة — ليس تعارضاً بل تنبيه.",
     "استمر إن كانت الوقاية مقصودة."),
]


def seed_interactions():
    """Create the missing interaction rules (matched by ingredient pair)."""
    from app.models import DrugInteraction

    generics = {g.name_en: g for g in GenericDrug.query.all()}
    existing = set()
    for r in DrugInteraction.query.all():
        if r.generic_a_id and r.generic_b_id:
            existing.add(tuple(sorted((r.generic_a_id, r.generic_b_id))))
    made = 0
    for a_name, b_name, severity, note, alt in INTERACTIONS:
        a, b = generics.get(a_name), generics.get(b_name)
        if a is None or b is None or a.id == b.id:
            continue
        key = tuple(sorted((a.id, b.id)))
        if key in existing:
            continue
        db.session.add(DrugInteraction(
            generic_a_id=a.id, generic_b_id=b.id, severity=severity,
            note=note, alternative=alt, is_active=True))
        existing.add(key)
        made += 1
    if made:
        db.session.flush()
    return made
