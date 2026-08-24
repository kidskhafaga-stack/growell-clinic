"""The user guide, as data — so it can be filtered by what you are allowed to do.

The guide used to be 240 lines of Jinja with the Arabic and the English of every
bullet written twice, one ``{% if ar %}`` apart. It said the same thing to
everybody: signing in as an admin, a doctor and a receptionist and measuring the
rendered page gave 4,193 / 4,114 / 4,075 characters — a 3% spread, which is the
size of the person's name in the top bar. A receptionist read a section on the
doctor's statement of account and one on writing a prescription, and neither
screen exists for them.

Holding the sections here instead makes that fixable: every section names the
**module** it describes, and the route hands the user only the sections their
role can actually reach. It also makes it checkable — a test can assert that
reception is never told about the doctor's statement, which it cannot do while
the text lives inside a template.

``capability`` is the second gate, and it is not decoration: module access says
"you can open Finance", a capability says "you may take money" or "you may move
the clinic's own cash between tills". Two people with the same module see
different sections, which is exactly how the screens themselves behave.

Sections whose module is ``None`` are for everybody — signing in, your own
account, the language switch.
"""
from app.models.permissions import MODULES

# Each section: key, module gate (None = everyone), optional capability gate,
# icon, (ar, en) title, and the bullets as (ar, en) pairs.
#
# The bullets carry <b> markup and are rendered unescaped. They are written
# here, in this file, and nothing user-supplied reaches them.
SECTIONS = [
    {
        "key": "basics",
        "module": None,
        "icon": "box-arrow-in-right",
        "title": ("الدخول وحسابك", "Signing in & your account"),
        "lines": [
            ("سجّل الدخول باسم المستخدم وكلمة المرور. كل مستخدم له <b>دور</b> "
             "بيحدد الأقسام اللي بيشوفها والعمليات اللي يقدر يعملها.",
             "Sign in with your username and password. Each user has a "
             "<b>role</b> that decides which sections they see and what they "
             "may do."),
            ("من الشريط العلوي: تبديل اللغة (عربي/إنجليزي) والوضع الليلي/النهاري "
             "— الاختيار بيتحفظ لحسابك.",
             "From the top bar: switch language (Arabic/English) and "
             "light/dark mode — the choice is saved to your account."),
            ("<b>حسابي</b>: تغيير كلمة المرور والصورة الشخصية. الأطباء كمان "
             "بيرفعوا التوقيع والختم اللي بيظهروا على الروشتة والتقارير.",
             "<b>My profile</b>: change your password and photo. Doctors also "
             "upload the signature and stamp used on prescriptions and "
             "reports."),
            ("كل عملية بتتسجّل باسمك ووقتها في سجل النشاط.",
             "Every action is recorded with your name and the time in the "
             "activity log."),
        ],
    },
    {
        "key": "dashboard",
        "module": "dashboard",
        "icon": "speedometer2",
        "title": ("لوحة اليوم", "Today's dashboard"),
        "lines": [
            ("أول شاشة بعد الدخول: مواعيد النهارده، المنتظرين، والتنبيهات اللي "
             "تخصّ دورك أنت.",
             "The first screen after signing in: today's appointments, who is "
             "waiting, and the alerts that belong to your role."),
            ("الأرقام بتتحدّث لحظياً من غير ما تعيد تحميل الصفحة.",
             "The figures refresh live — no page reload."),
        ],
    },
    {
        "key": "patients",
        "module": "patients",
        "icon": "people",
        "title": ("المرضى والملفات", "Patients & files"),
        "lines": [
            ("<b>مريض جديد</b> من المرضى ← «مريض جديد». الإخوة بيترابطوا تلقائياً "
             "تحت نفس اسم العائلة.",
             "<b>New patient</b> from Patients → \"New patient\". Siblings are "
             "linked automatically under the same family name."),
            ("<b>ملف المريض</b>: البيانات، أولياء الأمور، الإخوة، التنبيهات "
             "الطبية، والتأمين/العضوية.",
             "<b>Patient file</b>: details, guardians, siblings, medical "
             "alerts, and insurance/membership."),
            ("<b>استيراد جماعي</b>: نزّل قالب Excel/CSV، املأه وارفعه — بتظهر "
             "معاينة بالصفوف الصالحة والأخطاء، ومفيش حاجة بتتحفظ قبل التأكيد.",
             "<b>Bulk import</b>: download the Excel/CSV template, fill it and "
             "upload — a preview shows valid rows and errors, and nothing is "
             "saved until you confirm."),
            ("<b>استيراد التاريخ السابق</b> (زيارات وفلوس قديمة) بيتم على دفعات، "
             "وكل دفعة يمكن التراجع عنها بالكامل.",
             "<b>Historical import</b> (old visits and money) runs in batches, "
             "and any batch can be rolled back in full."),
            ("<b>الأرشيف</b>: المريض اللي مابقاش بيجي من سنين بيتأرشف — بيخف عن "
             "القوائم والبحث ويرجع بضغطة لما يرجع.",
             "<b>Archive</b>: a patient inactive for years is archived — out "
             "of the lists and search, and back with one click when they "
             "return."),
            ("<b>تحليل المرضى</b>: التوزيع بالنوع والعمر والفئة.",
             "<b>Patient analytics</b>: distribution by sex, age and "
             "category."),
        ],
    },
    {
        "key": "patient_file",
        "module": "patients",
        "capability": "patient_medical",
        "icon": "file-medical",
        "title": ("الملف الطبي الكامل", "The full medical file"),
        "lines": [
            ("الملف الطبي (الزيارات، التشخيصات، الروشتات، النمو، التطعيمات) "
             "مايفتحش غير لمن عنده صلاحية <b>الاطلاع على الملف الطبي</b>.",
             "The clinical file (visits, diagnoses, prescriptions, growth, "
             "vaccinations) opens only for whoever holds the <b>view medical "
             "file</b> capability."),
            ("الاستقبال بيشوف البيانات الأساسية اللي محتاجها للتسجيل والحجز "
             "والتحصيل — ومايشوفش الملف الطبي.",
             "Reception sees the basic details needed to register, book and "
             "collect — and not the clinical file."),
        ],
    },
    {
        "key": "appointments",
        "module": "appointments",
        "icon": "calendar-week",
        "title": ("المواعيد والدور", "Appointments & the queue"),
        "lines": [
            ("<b>لوحة اليوم</b>: تنقّل بين الأيام والأطباء والعيادات، وغيّر حالة "
             "الموعد (منتظر / جاري / مكتمل / لم يحضر).",
             "<b>Day board</b>: move between days, doctors and clinics, and "
             "change each appointment's status (waiting / in progress / done / "
             "no-show)."),
            ("<b>أقرب موعد متاح</b> بيحسبه النظام من جداول عمل الأطباء ومدة "
             "الكشف.",
             "<b>First available slot</b> is computed from the doctors' "
             "schedules and the consultation length."),
            ("الترتيب <b>بالدور (رقم)</b> أو <b>بالتوقيت المحجوز</b> — اختيار "
             "المدير من الإعدادات؛ وفيه أولوية حجز للحالات الخاصة.",
             "Order by <b>queue number</b> or <b>booked time</b> — the admin "
             "chooses in Settings; special cases can be given priority."),
            ("زر <b>واتساب</b> على الموعد بيبعت للمريض تأكيد بالوقت ورقم الدور.",
             "The <b>WhatsApp</b> button sends the patient a confirmation with "
             "the time and queue number."),
        ],
    },
    {
        "key": "visits",
        "module": "visits",
        "icon": "clipboard2-pulse",
        "title": ("الزيارة والكشف", "The visit"),
        "lines": [
            ("<b>محطة الطبيب</b> (الزيارات ← المحطة): طابور النهارده لحظياً، "
             "نادِ المريض التالي، ابدأ وأنهِ الزيارة من نفس الشاشة.",
             "<b>Doctor's station</b> (Visits → Station): today's queue live, "
             "call the next patient, start and end the visit from one screen."),
            ("<b>العلامات الحيوية</b> (وزن/طول/محيط رأس/حرارة/نبض/تنفس/تشبّع) "
             "مع حساب BMI فوري — والقياسات بتروح لمخطط النمو أوتوماتيك.",
             "<b>Vitals</b> (weight, height, head circumference, temperature, "
             "pulse, respiration, saturation) with instant BMI — and the "
             "measurements flow into the growth chart automatically."),
            ("<b>التشخيص ICD-10</b> ببحث فوري بالاسم أو الكود، عربي أو "
             "إنجليزي، مع تصنيف أولي/ثانوي/نهائي.",
             "<b>ICD-10 diagnosis</b> with instant search by name or code, in "
             "Arabic or English, classified primary / secondary / final."),
            ("<b>تنبيهات الأمان</b>: الحساسية والتداخلات الدوائية وشريط "
             "العلامات الحمراء بيظهروا قدام الطبيب في الزيارة نفسها.",
             "<b>Safety alerts</b>: allergies, drug interactions and the "
             "red-flag banner appear in front of the doctor inside the visit "
             "itself."),
            ("<b>طلبات التحاليل والأشعة</b> وتسجيل نتائجها من «الزيارات ← "
             "النتائج».",
             "<b>Lab and imaging requests</b> and their results, under "
             "Visits → Results."),
            ("<b>عبارات جاهزة</b> قابلة للتعديل بتقلّل الكتابة، وملخص الزيارة "
             "بيتطبع أو بيتحفظ كصورة.",
             "<b>Editable quick phrases</b> cut the typing, and the visit "
             "summary prints or saves as an image."),
        ],
    },
    {
        "key": "growth",
        "module": "growth",
        "icon": "graph-up",
        "title": ("مخططات النمو", "Growth charts"),
        "lines": [
            ("منحنيات <b>WHO</b> (٠–٥ سنوات) و<b>CDC</b> (٢–٢٠ سنة) للوزن "
             "والطول ومحيط الرأس وBMI، بقيم LMS الرسمية.",
             "<b>WHO</b> (0–5 y) and <b>CDC</b> (2–20 y) curves for weight, "
             "height, head circumference and BMI, from the official LMS "
             "tables."),
            ("لكل قياس <b>Percentile</b> و<b>Z-score</b>، والقياسات بتتجمع "
             "تلقائياً من الزيارات مع إمكانية الإضافة اليدوية.",
             "Every point carries its <b>percentile</b> and <b>Z-score</b>; "
             "measurements are collected from visits automatically and can be "
             "added by hand."),
            ("<b>تنبيه الانحراف</b> عند ±2 (انتباه) و±3 (تنبيه) لأحدث قياس.",
             "<b>Deviation flag</b> at ±2 (watch) and ±3 (alert) on the latest "
             "measurement."),
        ],
    },
    {
        "key": "vaccinations",
        "module": "vaccinations",
        "icon": "shield-plus",
        "title": ("التطعيمات", "Vaccinations"),
        "lines": [
            ("<b>جدول كل طفل حسب عمره</b> مع تسجيل الجرعة ورقمها، وشهادة تطعيم "
             "قابلة للطباعة.",
             "<b>An age-based schedule per child</b> with dose recording and a "
             "printable vaccination certificate."),
            ("الجرعة اللي بتتاخد في العيادة <b>بتتخصم من المخزن تلقائياً</b> "
             "(الأقرب انتهاءً أولاً)، والأمبولة متعددة الجرعات محسوبة.",
             "A dose given in the clinic <b>deducts from stock "
             "automatically</b> (first-expiry-first-out), and multi-dose vials "
             "are accounted for."),
            ("<b>متابعة الالتزام</b> على مستوى العيادة + <b>تذكيرات</b> واتساب "
             "للجرعات المستحقة.",
             "<b>Compliance tracking</b> clinic-wide, plus WhatsApp "
             "<b>reminders</b> for due doses."),
            ("<b>إدارة التطعيمات</b>: اللقاحات، الأصناف التجارية، والجداول "
             "الزمنية — كلها من الشاشة.",
             "<b>Manage vaccinations</b>: vaccines, brands and schedules — all "
             "from the screen."),
            ("<b>الجداول المزروعة تتعدّل.</b> البرنامج بيزرع جداول من "
             "المرجع، وبيعلّم عليها «للمراجعة» لأنها <u>متوقّع</u> إنها "
             "تحتاج تظبيط: النشرة بتتغيّر، والعيادة ممكن تمشي على CDC مش "
             "على نشرة الشركة. من شاشة الجداول تقدر تعدّل كل جرعة في مكانها "
             "— السن، الحد الأدنى والأقصى للفاصل، وعلامة البوستر — وتقدر "
             "تفتح «تعديل الجدول ومصدره» عشان تغيّر <b>مصدر المعلومة</b> "
             "نفسه والاسم ونطاق السن والصنف التجاري. خانة فاضية معناها «مفيش "
             "قيمة»، مش «سيبها زي ما هي».",
             "<b>Seeded schedules are meant to be corrected.</b> The program "
             "seeds schedules from the reference and marks them "
             "\u201cfor review\u201d because they are <u>expected</u> to need "
             "it: leaflets are revised, and a clinic may follow the CDC rather "
             "than the manufacturer's label. On the schedules screen each dose "
             "row is edited in place \u2014 age, minimum and maximum interval, "
             "and the booster tick \u2014 and \u201cEdit this schedule and its "
             "source\u201d changes <b>where the information came from</b>, "
             "along with the name, age band and brand. An empty box means "
             "\u201cno value\u201d, not \u201cleave it alone\u201d."),
        ],
    },
    {
        "key": "prescriptions",
        "module": "prescriptions",
        "icon": "capsule",
        "title": ("الروشتة والمرجع الدوائي", "Prescriptions & drug reference"),
        "lines": [
            ("<b>روشتة جديدة</b> من داخل الزيارة أو من ملف المريض — بتفتح "
             "مملوءة بالمريض والطبيب والوزن والتشخيص.",
             "<b>New prescription</b> from inside the visit or from the "
             "patient file — it opens pre-filled with patient, doctor, weight "
             "and diagnosis."),
            ("<b>كتالوج الأدوية المصري</b> كامل بالأسماء التجارية، ببحث فوري "
             "عربي/إنجليزي.",
             "<b>The full Egyptian drug register</b> by trade name, with "
             "instant Arabic/English search."),
            ("<b>المرجع الدوائي</b>: الأدوية مرتّبة بالتصنيف الدوائي، وكل مادة "
             "بجرعتها لكل كجم و<b>مصدر</b> الجرعة، والتحذيرات والمتابعة "
             "المطلوبة.",
             "<b>The drug reference</b>: drugs grouped by class, each "
             "ingredient with its per-kg dose and the <b>source</b> of that "
             "dose, its warnings and the monitoring it needs."),
            ("<b>حاسبة الجرعة بالوزن</b>: بتحسب الجرعة والحجم بالملليلتر حسب "
             "التركيز، وبتنبّه لو الجرعة عدّت السقف اليومي.",
             "<b>Weight-based dose calculator</b>: the dose and the millilitres "
             "for the concentration in hand, with a warning when the daily "
             "ceiling is exceeded."),
            ("<b>قوالب روشتات</b> جاهزة لكل طبيب (وتعليمات وعبارات) — كلها "
             "بتتظبط من مكان واحد.",
             "<b>Prescription templates</b> per doctor (plus instructions and "
             "phrases) — all set up in one place."),
            ("<b>فحص التداخلات والحساسية</b> بيشتغل قبل الحفظ، مش بعده.",
             "<b>Interaction and allergy checks</b> run before saving, not "
             "after."),
        ],
    },
    {
        "key": "inventory",
        "module": "inventory",
        "icon": "box-seam",
        "title": ("المخزون والمشتريات", "Inventory & purchasing"),
        "lines": [
            ("<b>الأصناف والدفعات</b> بتواريخ صلاحية وكميات، مع تنبيهات قرب "
             "الانتهاء والمخزون المنخفض والنفاد.",
             "<b>Items and batches</b> with expiry dates and quantities, plus "
             "near-expiry, low-stock and out-of-stock alerts."),
            ("<b>مستندات مرقّمة</b>: إذن إضافة، صرف، تحويل بين المخازن، مرتجع، "
             "وجرد.",
             "<b>Numbered documents</b>: goods receipt, issue, inter-warehouse "
             "transfer, return and stocktake."),
            ("<b>دورة الشراء</b>: أمر شراء ← اعتماد ← استلام، مع الموردين "
             "وكشوف حساباتهم.",
             "<b>Purchase cycle</b>: order → approval → receipt, with "
             "suppliers and their statements."),
            ("<b>كارت الصنف</b>: الرصيد والقيمة والدفعات والحركة، و<b>مسح "
             "الباركود</b> للإدخال السريع.",
             "<b>Item card</b>: balance, value, batches and movement — plus "
             "<b>barcode scanning</b> for fast entry."),
        ],
    },
    {
        "key": "cashier",
        "module": "finance",
        "capability": "cashier",
        # The till is the one screen reached by module *or* capability — see
        # ``cashier_access``. Reception collects money without being handed the
        # P&L, so gating this section on both would have told a receptionist
        # "you may take payments" in the permissions card and then shown them
        # no section explaining how.
        "access": "any",
        "icon": "cash-coin",
        "title": ("الكاشير والتحصيل", "Cashier & collection"),
        "lines": [
            ("<b>التحصيل في مكان واحد</b>: اختر المريض أو الفاتورة، سجّل الدفع "
             "(نقدي/كارت/مقسّم على أكتر من طريقة) واطبع الإيصال.",
             "<b>Collection in one place</b>: pick the patient or invoice, "
             "record the payment (cash / card / split across methods) and "
             "print the receipt."),
            ("التحصيل <b>بيتطلب وردية مفتوحة</b>، وفيه زر «اقفل ورديتك» عند "
             "التسليم — بيطلع تقرير الوردية (افتتاحي/تحصيل/متوقع/فعلي/فرق).",
             "Collecting <b>requires an open shift</b>, and \"close your "
             "shift\" at handover prints the shift report (opening, "
             "collected, expected, actual, difference)."),
            ("<b>الدفع الزائد ممنوع</b> — النظام مش بيقبل رصيد سالب على "
             "الفاتورة.",
             "<b>Overpayment is refused</b> — the system will not leave an "
             "invoice with a negative balance."),
        ],
    },
    {
        "key": "invoices",
        "module": "finance",
        "icon": "receipt",
        "title": ("الفواتير", "Invoices"),
        "lines": [
            ("<b>فاتورة واحدة للزيارة</b>: الكشف والإجراء والتطعيم اللي "
             "اتعملوا في نفس الزيارة بيتجمعوا على فاتورة واحدة بتستكمل.",
             "<b>One invoice per visit</b>: the consultation, the procedure "
             "and the vaccination done in the same visit go onto one invoice "
             "that keeps filling."),
            ("الحالة تلقائية — <b>مدفوعة / جزئية / غير مدفوعة</b> — مع دفعات "
             "جزئية وتعديل وطباعة وتصدير.",
             "Status is automatic — <b>paid / partial / unpaid</b> — with "
             "part-payments, editing, printing and export."),
            ("الخصم المسمّى (تأمين/نادي/نقابة) <b>بيتطبّق تلقائياً</b> حسب جدول "
             "تغطية الجهة، والكارت المنتهي بينبّهك.",
             "A named discount (insurer / club / syndicate) is <b>applied "
             "automatically</b> from the payer's benefits table, and an "
             "expired card is flagged."),
        ],
    },
    {
        "key": "services",
        "module": "finance",
        "capability": "finance_manage",
        "icon": "cash-stack",
        "title": ("الخدمات والعمولات", "Services & commissions"),
        "lines": [
            ("<b>الخدمات</b>: السعر والتكلفة وأقصى خصم والكود — والربحية "
             "بتتحسب لك (سعر − تكلفة − عمولة).",
             "<b>Services</b>: price, cost, maximum discount and code — with "
             "profitability computed for you (price − cost − commission)."),
            ("<b>عمولة الطبيب</b> نسبة أو مبلغ، وتقدر تخصّص نسبة مختلفة لكل "
             "طبيب على نفس الخدمة.",
             "<b>Doctor commission</b> as a percentage or a fixed amount, "
             "overridable per doctor on the same service."),
            ("<b>مستهلكات الخدمة</b>: تربط الخدمة بأصناف المخزن، فتتخصم "
             "تلقائياً كل ما الخدمة تتفوتر.",
             "<b>Service consumables</b>: link a service to stock items and "
             "they are deducted automatically whenever it is billed."),
        ],
    },
    {
        "key": "payers",
        "module": "finance",
        "capability": "finance_manage",
        "icon": "file-earmark-medical",
        "title": ("الجهات والمطالبات", "Payers & claims"),
        "lines": [
            ("<b>الجهات</b> (تأمين/نادي/نقابة) وجدول التغطية لكل خدمة.",
             "<b>Payers</b> (insurer / club / syndicate) and the per-service "
             "benefits table."),
            ("الخصم اللي أخده العضو بيفضل <b>مستحقاً على الجهة</b>، وتطبع "
             "مطالبة بالفترة لكل جهة وتتابع تحصيلها.",
             "The member's discount stays <b>claimable from the payer</b>; "
             "print a per-period claim per payer and track its collection."),
        ],
    },
    {
        "key": "books",
        "module": "finance",
        "capability": "finance_manage",
        "icon": "journal-text",
        "title": ("الدفاتر والإقفال", "Ledgers & closing"),
        "lines": [
            ("<b>المصروفات والمستحقات</b> للموردين، و<b>اليومية</b> وقائمة "
             "الدخل والميزان.",
             "<b>Expenses and payables</b> to suppliers, plus the "
             "<b>journal</b>, the income statement and the trial balance."),
            ("<b>كشف حساب الطبيب</b>: اختر الطبيب والفترة → نصيبه من كل "
             "الفواتير، مع خيار «المدفوعة فقط» للتسوية على المُحصّل.",
             "<b>Doctor statement</b>: pick a doctor and a period → their "
             "share across every invoice, with \"paid only\" to settle on what "
             "was actually collected."),
            ("<b>الفترات المالية</b>: إقفال الفترة يمنع التعديل عليها بأثر "
             "رجعي، و<b>الإقفال اليومي</b> بيربط التحصيل بالخزنة.",
             "<b>Accounting periods</b>: closing one blocks retroactive edits, "
             "and the <b>end-of-day</b> ties collections to the till."),
            ("<b>الفاتورة الإلكترونية (مصلحة الضرائب)</b>: فعّل الربط من "
             "الإعدادات، حوّل الفاتورة لفاتورة ضريبية، وتابع حالتها (مقبولة/"
             "مرفوضة) بالـUUID. فيه وضع تجريبي بدون اعتمادات.",
             "<b>Egyptian e-invoicing</b>: enable it in Settings, turn an "
             "invoice into a tax invoice and follow its status "
             "(accepted/rejected) with the UUID. A demo mode runs without "
             "credentials."),
        ],
    },
    {
        "key": "treasury",
        "module": "finance",
        "capability": "treasury_move",
        "icon": "safe",
        "title": ("الخزن والتحويلات", "Tills & transfers"),
        "lines": [
            ("<b>الخزن والحسابات</b>: كشف حركة لكل خزنة، إيداع وسحب وتحويل بين "
             "الخزن.",
             "<b>Tills and accounts</b>: a movement statement per till, with "
             "deposits, withdrawals and transfers between them."),
            ("<b>العدّ والتسوية</b>: تعدّ الدرج وتقارن بالمتوقع. تسوية الفرق "
             "نفسها صلاحية منفصلة للمدير — اللي بيعدّ مش هو اللي بيمسح العجز.",
             "<b>Counting and reconciliation</b>: count the drawer against "
             "what is expected. Writing off the difference is a separate "
             "admin-only capability — whoever counts the drawer is not the one "
             "who erases a shortage."),
        ],
    },
    {
        "key": "reports",
        "module": "reports",
        "icon": "bar-chart-line",
        "title": ("التقارير", "Reports"),
        "lines": [
            ("<b>مالية</b>: الدخل، أعمار الديون، الخصومات، الضريبة، الميزان، "
             "والميزانية.",
             "<b>Financial</b>: income, AR ageing, discounts, VAT, trial "
             "balance and balance sheet."),
            ("<b>تشغيلية وطبية</b>: أداء العيادة، الأطباء والموظفين، المخزون، "
             "والتطعيمات.",
             "<b>Operational and clinical</b>: clinic performance, doctors and "
             "staff, inventory and vaccinations."),
            ("كل تقرير <b>بيطبع على A4</b> بترويسة العيادة وبيتصدّر "
             "Excel/CSV.",
             "Every report <b>prints on A4</b> with the clinic letterhead and "
             "exports to Excel/CSV."),
        ],
    },
    {
        "key": "ai",
        "module": "ai",
        "icon": "robot",
        "title": ("المساعد الذكي", "The AI assistant"),
        "lines": [
            ("<b>داخل الزيارة</b>: تلخيص الزيارة، اقتراح جرعة، ومساعدة "
             "تشخيصية — اقتراح بيراجعه الطبيب، مش قرار.",
             "<b>Inside the visit</b>: summarise the visit, suggest a dose, "
             "help with a differential — a suggestion the doctor reviews, not "
             "a decision."),
            ("<b>البحث في ملفات المرضى</b> بسؤال عادي — الإجابة بتتبني من "
             "السجلات نفسها، مش من معلومات الموديل.",
             "<b>Search the patient records</b> in plain language — the answer "
             "is built from the records themselves, not from the model's own "
             "knowledge."),
            ("<b>عداد الاستهلاك</b> بيوضّح كل ميزة استهلكت قد إيه. بيتسجّل "
             "العدّ بس — لا نص المحادثة ولا بيانات المريض.",
             "<b>A usage meter</b> shows what each feature consumed. Only the "
             "counts are stored — never the conversation text or patient "
             "data."),
        ],
    },
    {
        "key": "messages",
        "module": "messages",
        "icon": "whatsapp",
        "title": ("واتساب وخدمة المرضى", "WhatsApp & patient service"),
        "lines": [
            ("<b>هب واحد</b> لكل الرسائل: قالب لكل نوع (تأكيد حجز، تذكير "
             "تطعيم، متابعة، استبيان…)، وتشغيل/إيقاف و<b>تلقائي أو يدوي</b> "
             "لكل نوع على حدة.",
             "<b>One hub</b> for every message: a template per type "
             "(confirmation, vaccination reminder, follow-up, survey…), each "
             "with on/off and <b>automatic or manual</b> sending."),
            ("<b>جدول اليوم</b>: ابعت جدول الطبيب له، أو أخطر كل مرضى اليوم.",
             "<b>Today's roster</b>: send a doctor their day, or notify all of "
             "today's patients."),
            ("<b>المناسبات</b> وأعياد الميلاد، و<b>ردود سريعة</b> جاهزة "
             "للاستقبال.",
             "<b>Occasions</b> and birthdays, plus <b>quick replies</b> for "
             "reception."),
            ("<b>صندوق وارد موحّد</b> بيربط الرسالة الواردة بالمريض تلقائياً من "
             "رقمه.",
             "<b>A unified inbox</b> that matches an incoming message to the "
             "patient by their number."),
            ("<b>استبيان الرضا</b> بيتبعت بعد الزيارة (نجوم للطبيب وللخدمة "
             "وNPS)، وتحليلاته بتظهر لكل طبيب.",
             "<b>The satisfaction survey</b> goes out after the visit (stars "
             "for the doctor and the service, plus NPS), and its analysis "
             "shows per doctor."),
            ("<b>حدود الإرسال</b>: نافذة زمنية، حد يومي، وإيقاف الرسائل لمريض "
             "بعينه — عشان البرنامج مايتحوّلش لمصدر إزعاج.",
             "<b>Sending limits</b>: a time window, a daily cap, and an opt-out "
             "per patient — so the system never becomes a nuisance."),
        ],
    },
    {
        "key": "users",
        "module": "users",
        "icon": "person-gear",
        "title": ("المستخدمون والصلاحيات", "Users & permissions"),
        "lines": [
            ("<b>المستخدمون</b>: إضافة وتعديل وتعطيل، وربط المستخدم بطبيب.",
             "<b>Users</b>: add, edit, disable, and link a user to a doctor."),
            ("<b>الأدوار</b>: عدّل الأقسام المتاحة لكل دور، أو أنشئ دور جديد "
             "بالكامل من الشاشة — من غير تعديل ملفات.",
             "<b>Roles</b>: edit which sections each role reaches, or create a "
             "whole new role from the screen — no file editing."),
            ("<b>الأطباء</b>: التخصص واللقب والتوقيع والختم وسعر الكشف "
             "والنسب.",
             "<b>Doctors</b>: specialty, title, signature, stamp, consultation "
             "fee and shares."),
            ("<b>سجل التدقيق</b>: مين عمل إيه وإمتى ومن أي جهاز.",
             "<b>Audit log</b>: who did what, when, and from which device."),
        ],
    },
    {
        "key": "settings",
        "module": "settings",
        "icon": "gear",
        "title": ("الإعدادات وأدوات البيانات", "Settings & data tools"),
        "lines": [
            ("<b>هوية المنشأة</b> والشعار والعملة، و<b>معالج أول تشغيل</b> "
             "بيجهّز التخصص والخدمات وأنواع الزيارات من أول مرة.",
             "<b>Facility identity</b>, logo and currency, plus a <b>first-run "
             "wizard</b> that sets up the specialty, services and visit types "
             "from the start."),
            ("<b>تفعيل/تعطيل الموديولات</b>: العيادة الصغيرة بتقفل اللي "
             "مش محتاجاه فيختفي من كل الشاشات.",
             "<b>Enable or disable modules</b>: a small clinic switches off "
             "what it does not need and it disappears from every screen."),
            ("<b>النسخ الاحتياطي</b>: نسخة يدوية، جدولة تلقائية، تنزيل، "
             "و<b>استعادة من داخل البرنامج</b> — مع نسخة أمان قبل أي استعادة.",
             "<b>Backups</b>: manual copies, a schedule, download, and "
             "<b>restore from inside the program</b> — with a safety copy "
             "taken before any restore."),
            ("<b>أنواع الزيارات</b> و<b>الأجهزة</b> وأدوات البيانات — "
             "و<b>منطقة الخطر</b> لمسح كل البيانات (بتتطلب كتابة DELETE).",
             "<b>Visit types</b>, <b>devices</b> and data tools — plus a "
             "<b>danger zone</b> that wipes everything (type DELETE)."),
        ],
    },
]

# The capabilities, said in words a user recognises rather than in slugs.
CAPABILITY_LABELS = {
    "patient_medical": ("الاطلاع على الملف الطبي الكامل",
                        "View the full medical file"),
    "cashier": ("تحصيل المدفوعات وطباعة الإيصالات",
                "Collect payments and print receipts"),
    "finance_manage": ("إدارة المالية بالكامل (الخدمات، الجهات، الدفاتر)",
                       "Full finance (services, payers, ledgers)"),
    "treasury_move": ("تحريك أموال العيادة بين الخزن",
                      "Move the clinic's money between tills"),
    "treasury_adjust": ("تسوية فروق الجرد (مدير فقط)",
                        "Write off counting differences (admin only)"),
}


def section_titles():
    """Every section's key and title — used by the services list on About."""
    return [(s["key"], s["title"]) for s in SECTIONS]


def visible_to(user, section, module_enabled=None):
    """Is this section about something ``user`` can actually reach?

    A section whose module is switched off for the whole facility is hidden
    from everybody, admin included: describing a screen that is not in the
    sidebar is how a guide starts lying.

    ``access="any"`` means module **or** capability, which is not a convenience
    — it is the rule ``cashier_access`` actually enforces on the till screens.
    A guide whose gate disagrees with the decorator is wrong in one of two
    directions, and both are worse than no guide.
    """
    module = section.get("module")
    capability = section.get("capability")
    if (module is not None and module_enabled is not None
            and not module_enabled(module)):
        return False
    if section.get("access") == "any":
        return ((module is not None and user.can_access(module))
                or (capability is not None and user.can(capability)))
    if module is not None and not user.can_access(module):
        return False
    if capability is not None and not user.can(capability):
        return False
    return True


def sections_for(user, module_enabled=None):
    """The sections this user's role can act on."""
    return [s for s in SECTIONS if visible_to(user, s, module_enabled)]


def unknown_modules():
    """Sections pointing at a module that does not exist.

    A typo here silently hides a section from everybody — ``can_access`` says
    no to a module nobody has. Checked by a test rather than trusted.
    """
    known = set(MODULES)
    return [s["key"] for s in SECTIONS
            if s.get("module") is not None and s["module"] not in known]
