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
        if (trade, strength or "") in existing:
            continue
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
    """Attach drugs the clinic typed itself to a matching ingredient."""
    generics = {}
    for g in GenericDrug.query.all():
        for key in (g.name_en, g.name_ar):
            if key:
                generics[key.strip().lower()] = g.id
    n = 0
    for d in Drug.query.filter(Drug.generic_id.is_(None)).all():
        key = (d.generic_name or "").strip().lower()
        if key and key in generics:
            d.generic_id = generics[key]
            n += 1
    return n


def seed_drugbook(force=False):
    """Seed classes → ingredients → trade names. Idempotent; returns counts."""
    if not force and GenericDrug.query.first() is not None:
        return {"classes": 0, "generics": 0, "brands": 0, "linked": 0}
    return {
        "classes": seed_drug_classes(),
        "generics": seed_generics(),
        "brands": seed_brands(),
        "linked": link_existing_drugs(),
    }
