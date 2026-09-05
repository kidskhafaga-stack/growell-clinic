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
            ("<b>الحساسية والأمراض المزمنة بالدوسة</b>: أزرار جاهزة تحت كل "
             "خانة. وأزرار حساسية الأدوية مهمة بشكل خاص — بتكتب بالظبط الكلام "
             "اللي فاحص الروشتة بيعرفه، فالدوسة عليها هي اللي بتخلّي التحذير "
             "يظهر لما يتكتب دوا من نفس العائلة. الكتابة باليد ممكن الفاحص "
             "مايفهمهاش.",
             "<b>Allergies and long illnesses in one click</b>: ready chips "
             "under each box. The drug-allergy chips matter most — they write "
             "exactly the words the prescription checker recognises, so "
             "clicking one is what makes the warning appear when a medicine "
             "from that family is written. Typed by hand, the checker may not "
             "recognise it."),
            ("قوايم الحساسية غير الدوائية والأمراض المزمنة العيادة تقدر "
             "تعدّلها من «الإعدادات ← عبارات». حساسية الأدوية مابتتعدّلش من "
             "هناك عن قصد: بتيجي من الفاحص نفسه علشان الزرار والفحص عمرهم ما "
             "يبعدوا عن بعض.",
             "The non-drug allergy and long-illness lists are yours to edit "
             "under Settings → Phrases. The drug allergies are deliberately "
             "not editable there: they come from the checker itself, so the "
             "chip and the check can never drift apart."),
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
            # Added with the feature. A suggestion the doctor cannot find
            # is a switch the clinic pays for and nobody uses.
            ("<b>اقتراح التشخيص.</b> في تاب التشخيصات، زرار «اقترح تشخيصات» "
             "بياخد الشكوى والفحص والعلامات الحيوية ويرجّع أسماء تشخيصات — "
             "والكود بييجي من تصنيف البرنامج نفسه، مش من المساعد. الاقتراح "
             "بيملّي نفس الفورم اللي بتملاه بإيدك، والبحث زي ما هو، ومحدش "
             "بيتحفظ غير لما تدوس «أضف». مقفول لحد ما الإعدادات ← الذكاء "
             "الاصطناعي تفتحه.",
             "<b>Diagnosis suggestions.</b> On the diagnoses tab, "
             "\u201csuggest\u201d takes the complaint, the examination and "
             "the vitals and returns diagnosis <i>names</i> \u2014 the code "
             "comes from the program's own classification, never from the "
             "assistant. A suggestion fills the same form you fill by hand, "
             "the search is unchanged, and nothing is saved until you press "
             "add. Off until Settings \u2192 AI turns it on."),
        ],
    },
    {
        # Opt-in, so `visible_to` keeps this away from every clinic that has
        # not switched the module on. A general paediatric practice has no
        # specialty section on its consultation screen and is not taught one.
        "key": "panels",
        "module": "panels",
        "icon": "clipboard-data",
        "title": ("قوالب التخصصات", "Specialty panels"),
        "lines": [
            ("<b>الزيارة العادية هي الأساس.</b> الشكوى والفحص والعلامات "
             "الحيوية والتشخيص والخطة موجودين دايمًا وما بيتغيروش بالتخصص — "
             "ده اللي بيخلّي ملف الطفل واحد، وطبيب الأسنان يشوف إن عنده فتحة "
             "في القلب. القالب طبقة صغيرة فوق ده، بيزوّد قياسات التخصص بس.",
             "<b>The ordinary visit is the base.</b> Complaint, examination, "
             "vitals, diagnosis and plan are always there and do not change "
             "with the specialty \u2014 that is what keeps the child's file "
             "one file, and lets the dentist see that this child has a hole "
             "in the heart. A panel is a small layer on top, adding that "
             "specialty's measurements and nothing else."),
            ("<b>مين بيقرر اللي يظهر.</b> المدير بيعلّم في إعدادات الطبيب "
             "(المستخدمون ← الأطباء ← الطبيب) القوالب اللي بيشتغلها — وممكن "
             "يبقى أكتر من واحد: أطفال عام + جهاز هضمي، أو عام + حديثي ولادة "
             "+ حساسية صدر. واحد منهم بيتعلّم «يفتح عليه» علشان مش تدوّر كل "
             "مرة. طبيب ما اتعلّمش ليه أي قالب شاشته هي الزيارة العادية من "
             "غير القسم ده خالص.",
             "<b>Who decides what shows.</b> An admin ticks, in the doctor's "
             "own setup (Users \u2192 Doctors \u2192 the doctor), which "
             "panels that doctor works \u2014 and it can be several: general "
             "paediatrics with gastroenterology, or general with newborn care "
             "and asthma. One of them is marked \u201copens on\u201d so "
             "nobody hunts for it forty times a day. A doctor with none "
             "ticked gets the ordinary visit with no panel section at all."),
            ("<b>في الزيارة.</b> القوالب بتظهر كشرايط فوق بعض — تدوس على "
             "الشريط فتظهر خانات القالب فورًا من غير حفظ. تقدر تسجّل في أكتر "
             "من قالب في نفس الزيارة: الطفل جه مرة واحدة، وكل قراءة بتتحفظ "
             "باسم القالب اللي اتسجلت منه، فالملف بيفضل عارف القياس ده جه "
             "من أنهي تخصص.",
             "<b>In the visit.</b> The panels appear as chips; pressing one "
             "shows its boxes at once, with no save in between. You can "
             "record under more than one panel in the same visit \u2014 the "
             "child came once \u2014 and every reading is stored under the "
             "panel it was entered from, so the file keeps knowing which "
             "specialty took which measurement."),
            ("<b>الطي.</b> السهم جنب العنوان بيطوي القسم كله لما مش محتاجه، "
             "والشاشة بتقصر. الطي بيتفكر لحد ما تفتحه تاني، وما بيخبّيش حاجة: "
             "العنوان بيفضل يقول مسجّل في كام قالب، والقراءات كلها بتتحفظ "
             "زي ما هي سواء القسم مفتوح أو مطوي.",
             "<b>Folding.</b> The chevron beside the heading puts the whole "
             "section away when you do not need it, and the screen gets "
             "shorter. The fold is remembered until you open it again, and "
             "it hides nothing: the heading keeps saying how many panels "
             "carry something, and every reading is saved whether the "
             "section is open or shut."),
            ("<b>قالب اتشال.</b> لو المدير شال قالب من قايمة الطبيب، القراءات "
             "اللي اتسجلت تحته بتفضل في الملف وفي زياراتها زي ما هي — "
             "الإعداد بيقول تسأل إيه بعد كده، مش بيعدّل في زيارات خلصت.",
             "<b>A panel taken away.</b> If an admin unticks a panel, the "
             "readings recorded under it stay in the file and on their "
             "visits, untouched \u2014 the setting says what to ask next, it "
             "does not edit finished visits."),
            ("<b>التنبيهات، والرقم رقمك انت.</b> الاستبيان سأل كل تخصص "
             "«البرنامج ينبّهك إمتى؟» وردّ بمية وتلات تنبيهات. اللي منهم حد "
             "رقمي — السكر التراكمي فوق كذا، الأكسجين تحت كذا — الاستبيان "
             "نفسه رفض يدّي رقم («لا يوجد رقم موحّد»)، والبرنامج ما "
             "بيخترعش رقم إكلينيكي. فالتنبيهات دي كانت معلنة ومش شغالة "
             "<b>ومكانش فيه مكان أصلاً تكتب فيه رقمك</b> — ميزة متعملة "
             "ومفيش باب ليها.",
             "<b>The alerts, and the number is yours.</b> The survey asked "
             "each specialty when the program should warn them and got a "
             "hundred and three alerts back. The ones that are a threshold "
             "\u2014 HbA1c above, saturation below \u2014 the survey itself "
             "refused to supply a figure for (\u201cthere is no single "
             "number\u201d), and this program does not invent clinical "
             "numbers. So they were declared and dormant, <b>and there was "
             "nowhere to write your own figure</b>: a feature built with no "
             "door to it."),
            ("<b>البرنامج بيقول بيبص على إيه، والعيادة بتقول إمتى تقلق.</b> "
             "الكتالوج بيقول التنبيه ده بيقرا تحليل بكوده، ولا علامة حيوية، "
             "ولا قراءة من القالب، ولا عمر الطفل، ولا طلب فحص ماجاش عليه رد — "
             "ومفيش رقم واحد في الكتالوج كله. الرقم بيتكتب من «أرقام تنبيهات "
             "التخصصات»، وهو صف في قاعدة بيانات العيادة، فالتحديث عمره ما "
             "بيلمسه.",
             "<b>The program says what it looks at; the clinic says when to "
             "worry.</b> The catalogue names a lab test by its code, a vital "
             "sign, a reading the panel takes, the child\u2019s age, or an "
             "order that never came back \u2014 and carries no number "
             "anywhere. The figure is written on the specialty-alerts screen "
             "and lives as a row in the clinic\u2019s own database, which an "
             "update never touches."),
            ("<b>خانة فاضية = التنبيه مش شغال، زي ما كان بالظبط.</b> ونسخة "
             "جديدة مفيهاش ولا رقم، فما بتشتغلش ولا تنبيه من دول. والشاشة "
             "بتقول كمان اللي مستني على حاجة تانية — مقارنة بين زيارتين، أو "
             "قاعدة معرفة أدوية، أو حاجة الطبيب بس اللي بيلاحظها — عشان "
             "العيادة اللي ملّت أربع أرقام تعرف إن الباقي مش إعداد ناقص "
             "عليها.",
             "<b>An empty box means the alert is dormant, exactly as it "
             "was.</b> A fresh install has no numbers and therefore none of "
             "these alerts. The screen also says which of the rest are "
             "waiting on something else \u2014 a comparison between two "
             "visits, a drug knowledge base, or something only a person can "
             "notice \u2014 so a clinic that filled in four numbers is not "
             "left thinking the others are a setting they missed."),
        ],
    },
    {
        # Opt-in like the two above, and for a sharper reason: this is a ward
        # screen. A clinic that sees children one at a time has no rounds at
        # all, and would be taught a department it does not run.
        "key": "observations",
        "module": "observations",
        "icon": "activity",
        "title": ("الملاحظات المتكررة", "Repeated observations"),
        "lines": [
            ("<b>ليه موجودة.</b> العلامات الحيوية في الزيارة قراءة واحدة — "
             "وده صح للعيادة الخارجية. الطفل اللي تحت الملاحظة في الطوارئ أو "
             "في الحضانة بيتقاس كل ربع ساعة أو كل ساعة حسب طلب الطبيب، والقسم "
             "ده هو اللي بيسجّل ده من غير ما يلمس قراءة الزيارة.",
             "<b>Why it exists.</b> A visit keeps one set of vitals, which is "
             "right for an outpatient. A child under observation in emergency "
             "or in an incubator is measured every fifteen minutes or every "
             "hour as the doctor asked, and this is where that is recorded "
             "\u2014 without touching the visit's own reading."),
            ("<b>الطبيب بيطلب، والتمريض بيسجّل.</b> الطبيب بيحدد كل قد إيه من "
             "قايمة ثابتة (ربع ساعة، نص ساعة، ساعة، ساعتين، أربع، تمانية). "
             "التمريض بيسجّل القراءة. تغيير المدة بيوقف الطلب القديم ويفتح "
             "طلب جديد، علشان الملف يفضل قايل الطفل كان بيتراقب إزاي في كل "
             "ساعة من إقامته.",
             "<b>The doctor orders, nursing records.</b> The doctor picks how "
             "often from a fixed list (15, 30, 60, 120, 240 or 480 minutes) "
             "and nursing records the readings. Changing the interval stops "
             "the old order and starts a new one, so the file keeps saying "
             "how closely the child was being watched at every hour of the "
             "stay."),
            ("<b>اللوحة بتقول مين اتأخر.</b> مش «آخر قراءة كانت إيه» — ده "
             "الجدول بيقوله. اللوحة بتقول مين معملوش قياس بقى له أطول من اللي "
             "الطبيب طلبه، والتأخير محسوب بالنسبة للمدة نفسها: تلات دقايق "
             "تأخير على ربع ساعة تأخير، وعلى أربع ساعات مش حاجة.",
             "<b>The board says who is overdue.</b> Not \u201cwhat was the "
             "last reading\u201d \u2014 the table says that. It says who has "
             "not been measured for longer than the doctor asked, and "
             "lateness is measured against the interval itself: three minutes "
             "past a quarter-hourly round is late, and past a four-hourly one "
             "is nothing."),
            ("<b>الأرقام بتتقرا بنفس قواعد العيادة.</b> الحرارة والنبض "
             "والتنفس والأكسجين بتتلوّن بنفس الجداول اللي شاشة الكشف "
             "بتستعملها، مش بجدول تاني — علشان الطفل ما يبقاش أصفر في شاشة "
             "وأخضر في شاشة تانية وكل واحدة مظبوطة لوحدها.",
             "<b>The numbers are read by the clinic's own rules.</b> "
             "Temperature, pulse, respiratory rate and saturation are "
             "coloured by the same tables the consultation screen uses, not "
             "by a second set \u2014 so a child cannot be amber on one screen "
             "and green on another with each screen individually correct."),
            ("<b>قراءة فاضية مترفض.</b> لو محدش قاس حاجة، مفيش صف بيتحفظ: "
             "الصف الفاضي بيقفل تنبيه التأخير من غير ما حد يكون قرّب من "
             "الطفل. جملة ملاحظة لوحدها («نايم ومرتاح») تبقى قراءة.",
             "<b>An empty reading is refused.</b> If nothing was measured, "
             "nothing is saved: an empty row would silence the lateness "
             "warning while nobody had been near the child. A note on its "
             "own (\u201csleeping, comfortable\u201d) counts as an "
             "observation."),
        ],
    },
    {
        # Opt-in, and the sharpest case of it: a clinic seeing outpatients has
        # no beds at all. Switched on by the wizard for anybody who says they
        # run a ward, an emergency, incubators or intensive care.
        "key": "beds",
        "module": "beds",
        "icon": "hospital",
        "title": ("الأسرّة والإقامة", "Beds and admissions"),
        "lines": [
            ("<b>الإقامة مش زيارة.</b> الزيارة الخارجية بتبتدي وتخلص في يوم "
             "واحد، وده صح ليها. الإقامة بتمتد أيام، وبتنتهي بقرار (خروج، أو "
             "تحويل لمستشفى تانية)، وفي كل ساعة منها الطفل في <b>مكان</b>. "
             "وملف الطفل يفضل واحد: التنويم بيظهر في نفس الملف زي الزيارة "
             "بالظبط، مش في نظام موازي.",
             "<b>A stay is not a visit.</b> An outpatient visit starts and "
             "ends on one day, which is right for it. A stay runs across "
             "days, ends in a decision (home, or a transfer to another "
             "hospital), and at every hour of it the child is in a "
             "<b>place</b>. The child's file stays one file: an admission "
             "shows up in it exactly as a visit does, not in a parallel "
             "system."),
            ("<b>القسم ← الحيّز ← السرير.</b> الحيّز مش «غرفة» بس، لأن "
             "الطوارئ بارتشنات والداخلي غُرف والعناية صالة مفتوحة فيها "
             "بارتشن عزل أو اتنين. والسرير له نوع: سرير، سرير حديثي ولادة، "
             "حضّانة، كبسولة نقل، ترولي طوارئ. الأقسام الأربعة بتشتغل على "
             "نفس الشكل ده، بيختلفوا في كثافة الملاحظة مش في شكل المكان.",
             "<b>Unit → space → bed.</b> The middle level is a *space* and "
             "not simply a room: emergency runs on partitions, the ward on "
             "rooms, intensive care is an open bay with one or two isolation "
             "partitions. A bed has a kind — bed, cot, incubator, transport "
             "capsule, emergency trolley. All four departments run on that "
             "same shape and differ by how closely a child is watched, not "
             "by what a place is."),
            ("<b>العزل خاصية للحيّز مش للسرير.</b> اللي بيعزل الطفل هو "
             "الحيطة اللي حواليه. صالة فيها ست أسرّة وواحد متعلّم عليه "
             "«معزول» دي معلومة بتكدب. فلما تسأل «فيه مكان عزل فاضي؟» "
             "البرنامج بيرد من الحيّز.",
             "<b>Isolation belongs to the space, never to the bed.</b> What "
             "isolates a child is the walls around them. A bay of six beds "
             "with one marked \u201cisolated\u201d is information that lies. "
             "So \u201cis there an isolation space free?\u201d is answered "
             "from the space."),
            ("<b>الإشغال محسوب مش متخزّن.</b> السرير فاضي لما ما يبقاش عليه "
             "إقامة مفتوحة — مفيش خانة «مشغول» في أي مكان، ولا المفروض تبقى: "
             "الفلاج ده بيبعد خروج واحد اتنسي عن قسم بيقول إنه مليان وتلات "
             "أسرّة فاضية، والتمريض بيبطّل يصدّق الشاشة في أسبوع.",
             "<b>Occupancy is counted, never stored.</b> A bed is free when "
             "no stay is open on it \u2014 there is no \u201coccupied\u201d "
             "column anywhere and there must never be one. A flag is one "
             "forgotten discharge away from a ward that reports itself full "
             "with three beds standing empty, and the staff stop believing "
             "the screen within a week."),
            ("<b>النقلة بتتسجّل، والسرير ما بيتمسحش.</b> الطفل لما ينتقل من "
             "صالة لحيّز عزل، الصف القديم بيفضل بساعاته والجديد بيفتح — "
             "علشان سؤال «كان فين يوم الأربع؟» يبقى له إجابة. والسرير بيتوقف "
             "عن الخدمة وبيرجع، وما بيتمسحش أبدًا: إقاماته هي إشغال الشهر "
             "اللي فات. والكبسولة بتتحرّك والإقامة بتفضل مفتوحة — الطفل نزل "
             "أشعة، ما خرجش.",
             "<b>A move is recorded, and a bed is never deleted.</b> When a "
             "child moves from a bay into an isolation space, the old row "
             "keeps its hours and a new one opens \u2014 so "
             "\u201cwhere were they on Wednesday?\u201d has an answer. A "
             "bed goes out of service and comes back, never deleted: its "
             "stays are last month's occupancy. And a transport capsule "
             "moves with the stay still open \u2014 the baby went down to "
             "X-ray, they did not leave."),
            ("<b>مين بيعمل إيه.</b> التنويم والنقل والخروج شغل إكلينيكي: "
             "الأطباء والتمريض ومدير العيادة. أما بناء المكان نفسه — قسم "
             "جديد، غرفة، سرير — فده للمدير، وبيتعمل من شاشة الإعداد مش من "
             "تحديث: العيادة اللي بتضيف حضّانة رقم ٧ بتعملها يوم التلات "
             "الجاي.",
             "<b>Who does what.</b> Admitting, moving and discharging are "
             "clinical acts: doctors, nursing and whoever runs the clinic. "
             "Building the place itself \u2014 a unit, a room, a bed \u2014 "
             "is the owner's, and it is done from the setup screen rather "
             "than from a release: a clinic adding incubator number seven "
             "does it on a Tuesday afternoon."),
        ],
    },
    {
        "key": "beds_drugs",
        "module": "beds",
        "icon": "capsule",
        "title": ("دورة الدواء", "The drug round"),
        "lines": [
            ("<b>الأمر حاجة والجرعة حاجة تانية.</b> الطبيب بيكتب أمر ثابت — "
             "الدوا والجرعة وكل كام ساعة — والتمريض بيسجّل كل جرعة: اتعطت، "
             "اتأجلت، أو اترفضت. لو كان في عمود واحد اسمه «آخر جرعة» على "
             "الأمر، السؤال «هو مستحق دلوقتي؟» كان هيتجاوب، والسؤال «حصل إيه "
             "الساعة اتنين؟» كان هيترد عليه بجرعة النهاردة عن كل يوم في "
             "الإقامة — وده بالظبط سؤال التحقيق في خطأ دوائي.",
             "<b>The order and the dose are two different things.</b> The "
             "doctor writes a standing order \u2014 the drug, the dose, how "
             "many hours apart \u2014 and nursing records every dose: given, "
             "held, or refused. A single \u201clast given\u201d column on "
             "the order would answer \u201cis it due?\u201d and would answer "
             "\u201cwhat happened at two o\u2019clock?\u201d with "
             "tonight\u2019s answer for every night of the stay, which is "
             "exactly what a drug-error inquiry asks."),
            ("<b>مفيش جرعات متجدولة قدام.</b> «مستحق» بيتحسب من الأمر ومن آخر "
             "جرعة، زي الملاحظة المتأخرة بالظبط. جدول جرعات جاية لازم يفضل "
             "متماشي مع أمر اتغيّر نص الليل، وأول حاجة بيعملها لما يفرق إنه "
             "يقول إن طفل اداله حاجة ما اتعطتلوش.",
             "<b>Nothing is scheduled ahead.</b> Due-ness is worked out from "
             "the order and the last dose, exactly the way a late observation "
             "is. A table of future doses has to be kept in step with an "
             "order that changed at midnight, and the first thing it does "
             "when it drifts is claim a child was given something they were "
             "not."),
            ("<b>التأجيل قرار، والصمت مش قرار.</b> جرعة اتأجلت بتحرّك الساعة "
             "زي اللي اتعطت بالظبط — حد وقف عند السرير وقرر. اللي مينفعش "
             "يحصل هو جرعة محدش كتب عنها حاجة، وده بالظبط اللي اللوحة "
             "اتعملت علشانه. وعلشان كده <b>التأجيل لازم يكون معاه سبب</b>: "
             "تأجيل من غير سبب شكله زي جرعة حد نسيها، والاتنين بيسكّتوا "
             "اللوحة.",
             "<b>A hold is a decision; silence is not.</b> A held dose moves "
             "the clock exactly as a given one does \u2014 somebody stood at "
             "the bed and decided. What must not exist is a dose nobody wrote "
             "anything about, which is the whole reason the board exists. "
             "That is why <b>a hold needs a reason</b>: one without it looks "
             "exactly like a dose somebody forgot, and both silence the "
             "board."),
            ("<b>الكتابة والإعطاء صلاحيتين مختلفتين.</b> «كتابة أوامر الدواء» "
             "صلاحية لوحدها — أقدم قاعدة أمان في أي قسم داخلي: اللي ماسك "
             "السرنجة مش هو اللي قرر اللي جواها. التمريض بياخد القسم ودورة "
             "الدواء وما بياخدش الصلاحية دي.",
             "<b>Writing and giving are two permissions.</b> "
             "\u201cWrite drug orders\u201d is a capability of its own "
             "\u2014 the oldest safety rule on a ward: whoever holds the "
             "syringe is not the one who decided what is in it. Nursing gets "
             "the ward and the drug round and not this one."),
            ("<b>والجرعة اللي اتعطت بتتحاسب وبتتخصم من المخزن.</b> الأمر "
             "بيتربط بصنف من المخزن (والكمية: أمبولة ولا أمبولتين)، وكل جرعة "
             "<b>اتعطت</b> بتتحط على فاتورة الإقامة وبتخرج من الرف. المتأجلة "
             "والمرفوضة ما بتحاسبش وما بتخصمش — محدش اداله حاجة. والأمر اللي "
             "مش مربوط بصنف بيشتغل زي ما هو من غير ما يلمس لا فلوس ولا مخزن، "
             "فالعيادة اللي ماسكة أدوية القسم بالورق ما اتغيّرش عندها حاجة.",
             "<b>And a dose that was given is charged and comes off the "
             "shelf.</b> The order is pointed at a store item (and how many "
             "units make a dose \u2014 one ampoule or two), and every "
             "<b>given</b> dose lands on the stay\u2019s invoice and leaves "
             "the store. Held and refused doses charge nothing and deduct "
             "nothing: nobody was given anything. An order with no item "
             "behind it works exactly as before and touches neither money nor "
             "stock, so a clinic that keeps its ward drugs on paper is "
             "untouched."),
            ("<b>والجرعة عمرها ما بتترفض عشان المخزن باين فاضي.</b> القسم "
             "ادّى الدوا؛ ده حصل. برنامج بيرفض يسجّله لأن عدّته بتقول إن الرف "
             "فاضي بيكون بدّل حقيقة بحاجة مرتبة. الحركة بتتسجّل والمخزون "
             "بيسمح له ينزل تحت الصفر — ده فرق للمخزن يراجعه، مش جرعة "
             "تضيع.",
             "<b>And a dose is never refused because the shelf looks "
             "empty.</b> The ward gave the drug; that happened. A program "
             "that declines to record it because its own count says the shelf "
             "is empty has replaced a true fact with a tidy one. The movement "
             "is posted and the stock is allowed to go negative \u2014 a "
             "discrepancy for the store to reconcile, not a dose to lose."),
            ("<b>وفحص الأمان مش نسخة تانية.</b> الجرعة القصوى والحساسية "
             "والتعارضات كلها <b>نفس</b> الفحص اللي شاشة الروشتة بتستعمله، "
             "وبيشوف كمان أدوية الطفل اللي من برة — الكاربامازيبين اللي حد "
             "تاني كتبه من شهور هو بالظبط النص اللي بيتعارض مع اللي هيتبدأ "
             "دلوقتي.",
             "<b>And the safety check is not a second one.</b> The dose "
             "ceilings, the allergies and the interaction pairs are the "
             "<b>same</b> check the prescription screen uses, and it sees the "
             "child\u2019s pre-existing medicines too \u2014 the "
             "carbamazepine somebody else wrote months ago is exactly the "
             "half that interacts with what is about to be started."),
        ],
    },
    {
        "key": "beds_nights",
        "module": "beds",
        "icon": "moon-stars",
        "title": ("فاتورة السرير اليومية", "The daily bed charge"),
        "lines": [
            ("<b>ليلة مش يوم — والطوارئ بالساعة.</b> الليالي بتتعد من تاريخ "
             "الدخول لتاريخ الخروج من غير يوم الخروج، وبحد أدنى ليلة واحدة: "
             "دخل الاتنين وخرج الخميس = تلات ليالي، ودخل وخرج نفس اليوم = "
             "ليلة لأن سرير اتفرش واترفع. أما الطوارئ فبالساعة: طفل قعد تلات "
             "ساعات على ترولي وراح البيت ما نامش ولا ليلة، وفاتورة ليلة عليه "
             "مش تقريب — دي فاتورة لحاجة ما حصلتش.",
             "<b>A night, not a day \u2014 and emergency by the hour.</b> "
             "Nights run from the date of admission to the date of discharge, "
             "not counting the day they leave, with a floor of one: in on "
             "Monday and out on Thursday is three nights, and in and out the "
             "same afternoon is one because a bed was made up and taken "
             "again. Emergency is different: a child on a trolley for three "
             "hours who goes home has not spent a night anywhere, and billing "
             "one is not a rounding difference \u2014 it is a bill for "
             "something that did not happen."),
            ("<b>والساعة بتتحسب لما الإقامة تخلص، مش قبل كده.</b> عدد "
             "الساعات مش معروف قبل ما الطفل يمشي، وحسابها على أقساط كان "
             "هيحط سطرين على فاتورة واحدة لزيارة واحدة. والوقت بيتقاس "
             "بالدقيقة، وأي جزء من ساعة بيتحسب ساعة — عشرين دقيقة على ترولي "
             "هي ساعة ترولي. والشاشة بتوري الساعات اللي جرت لحد دلوقتي علشان "
             "حد يقدر يقول للأهل قبل ما يوصلوا الباب.",
             "<b>And an hour is charged when the stay ends, not before.</b> "
             "How many hours it was is not known until the child leaves, and "
             "charging in instalments would put two lines on one bill for one "
             "visit. The time is counted in whole minutes and any part-hour "
             "is an hour \u2014 twenty minutes on a trolley is an hour of a "
             "trolley. The screen shows the hours run up so far, so a family "
             "can be told at the trolley rather than at the door."),
            ("<b>السعر خدمة مش رقم، وبيتحط على تلات مستويات.</b> السرير، "
             "وبعده الغرفة، وبعدهم القسم — وأقرب واحد متحط بيكسب. أغلب "
             "المستشفيات بتسعّر <b>الغرفة</b> (مفردة ومزدوجة سعرين لنفس "
             "السرير، واللي بيفرق هو الحيطان)، والحضّانات بتسعّر <b>السرير</b> "
             "لأن الصالة فيها سرير وحضّانة وكبسولة، والطوارئ بتسعّر "
             "<b>القسم</b>. وبما إنه خدمة، الخصومات وجهات التأمين ونسبة "
             "الطبيب وكود الضريبة كلهم شغّالين عليه من غير سطر زيادة.",
             "<b>The rate is a service, not a number, and it sits at three "
             "levels.</b> The bed, then the room, then the department \u2014 "
             "the nearest one set wins. Most hospitals price the <b>room</b> "
             "(a single and a double are two prices for the same bed, and "
             "what differs is the walls), the nursery prices the <b>bed</b> "
             "because one bay holds a cot, an incubator and a capsule, and "
             "emergency prices the <b>department</b>. Being a service, the "
             "discounts, the payers, the doctor\u2019s commission and the tax "
             "item code all work on it already."),
            ("<b>والسعر هو المفتاح.</b> عيادة ما حطتش سعر على أي قسم عمرها ما "
             "هيتحسب عليها ليلة ولا هتشوف الكارت ده أصلاً — زي أي مديول "
             "مقفول بالظبط.",
             "<b>And the price is the switch.</b> A clinic that has set no "
             "rate on any department is never charged for a night and never "
             "sees the card at all \u2014 exactly like a module that is off."),
            ("<b>مفيش فلوس بتتكتب من ورا حد.</b> شاشة الإقامة بتوريك الليالي "
             "اللي لسه ما اتحسبتش وحد بيدوس؛ والخروج بيحسبها لأن الخروج أصلاً "
             "قرار بيتاخد قدام فورم، وبيتقال بصوت عالي في الرسالة. مفيش "
             "تايمر بيكتب على حساب أهل الطفل بالليل.",
             "<b>No money is written behind anybody\u2019s back.</b> The stay "
             "screen shows the uncharged nights and somebody presses; the "
             "discharge charges them because a discharge is already a "
             "deliberate act with a form in front of it, and it says so in "
             "the message. There is no timer writing onto a family\u2019s "
             "account overnight."),
            ("<b>ودوسة تانية ما بتحسبش تاني.</b> كل ليلة اتحسبت ليها صف، "
             "وقاعدة البيانات نفسها بترفض ليلتين لنفس اليوم — مش شرط في "
             "الكود: اتنين بيدوسوا في نفس الثانية من شاشتين هو بالظبط إزاي "
             "أهل طفل بيتحاسبوا مرتين على يوم التلات.",
             "<b>And pressing again charges nothing twice.</b> Every charged "
             "night is a row, and the database itself refuses two for the "
             "same date \u2014 not a check in code: two people pressing in "
             "the same second on two screens is exactly how a family gets "
             "billed twice for a Tuesday."),
            ("<b>والليلة بتتحسب بالسرير اللي الطفل كان فيه آخر اليوم.</b> طفل "
             "اتنقل للعناية الساعة أربعة بعد الضهر بات في العناية، والليلة دي "
             "بفلوس العناية.",
             "<b>A night is charged at the bed they were in at the end of "
             "it.</b> A child moved up to intensive care at four in the "
             "afternoon spent that night in intensive care, and that is what "
             "the night cost."),
        ],
    },
    {
        "key": "emergency",
        "module": "emergency",
        "icon": "thermometer-half",
        "title": ("الطوارئ", "Emergency"),
        "lines": [
            ("<b>الشاشة بتجاوب على سؤال واحد: مين الأول.</b> لوحة الأسرّة "
             "بترسم المكان وبتقول مين فيه؛ الطوارئ بتتقرا بالعكس — الأسوأ "
             "فوق. والترتيب أربع حاجات بالترتيب ده: طفل محدش قاسه من ساعة ما "
             "دخل، بعدين اللي جولته اتأخرت، بعدين اللي آخر قراءة ليه البرنامج "
             "قراها «حالة تستاهل تتشاف دلوقتي»، وبعدين الباقي الأطول انتظارًا "
             "الأول.",
             "<b>The screen answers one question: who first.</b> The bed "
             "board draws the place and says who is in it; emergency is read "
             "the other way round \u2014 worst at the top. The order is four "
             "things: a child nobody has measured since they arrived, then "
             "one whose rounds are overdue, then one whose last reading the "
             "program reads as urgent, then everybody else, longest wait "
             "first."),
            ("<b>مفيش فرز جديد هنا.</b> الحرارة والأكسجين بيتقروا بنفس "
             "الجداول اللي شاشة الكشف ومحطة التمريض بيستعملوها. لو الشاشة دي "
             "عملت جدول خاص بيها، الطفل يبقى أحمر في مكان وأخضر في مكان "
             "والاتنين «مظبوطين».",
             "<b>No second triage.</b> Temperature and saturation are read by "
             "the same tables the consultation screen and the nursing station "
             "use. A department with its own thresholds would make a child "
             "red on one screen and green on another, each individually "
             "correct."),
            ("<b>الإقامة بتنتهي بقرار مش بمرور الوقت.</b> خروج، أو تحويل "
             "لمستشفى تانية، أو <b>تنويم</b> — والتنويم <em>نقل لسرير</em> مش "
             "خروج ودخول تاني: الطفل ما خرجش، والإقامة بتفضل واحدة على نفس "
             "الحتة من الرعاية.",
             "<b>A stay ends in a decision, not in time passing.</b> Home, a "
             "transfer to another hospital, or <b>admission</b> \u2014 and "
             "admission is a <em>move to a bed</em>, not a discharge followed "
             "by a new stay: the child did not leave, and one piece of care "
             "stays one stay."),
            ("<b>لازم يكون فيه قسم متبني.</b> القسم بيتعمل من إعداد الأسرّة: "
             "قسم نوعه طوارئ، وبارتشنات، وسرير في كل بارتشن. والشاشة بتقول "
             "كده صراحة لو لسه مفيش، مش بتفضل فاضية.",
             "<b>A unit has to exist first.</b> It is built from the bed "
             "setup: a unit of kind emergency, its partitions, and a bed in "
             "each. The screen says so plainly when there is none rather than "
             "sitting empty."),
        ],
    },
    {
        "key": "nicu",
        "module": "nicu",
        "icon": "moisture",
        "title": ("الحضّانات", "The incubators"),
        "lines": [
            ("<b>نفس شاشة الطوارئ، بإيقاع تاني وأربع حقايق زيادة.</b> عمر "
             "الطفل بالساعات، سن الحمل عند الولادة، الوزن مقارنة بوزن "
             "الولادة، وآخر بيليروبين فين من حد الطفل ده هو نفسه.",
             "<b>The same screen as emergency, at a different tempo and with "
             "four extra facts.</b> Hours of life, gestation at birth, weight "
             "against birth weight, and where the last bilirubin sits against "
             "<em>this baby's own</em> threshold."),
            ("<b>ولا واحدة من الأربعة جديدة.</b> الساعات وسن الحمل موجودين "
             "على ملف الطفل من زمان، والوزن هو منحنى النمو نفسه، والمقارنة هي "
             "حاسبة الصفراء اللي موجودة ومقفولة لحد ما طبيب يوافق على الجدول. "
             "اللي كان ناقص هو الوصل: الممرضة كانت بتقرا الرقم من شاشة المعمل "
             "وتعمل المقارنة في دماغها — على الحسبة الوحيدة اللي البرنامج "
             "اتعمل فيها عشان محدش يعملها في دماغه.",
             "<b>None of the four is new.</b> Hours and gestation have been "
             "on the child's file for a long time, the weight is the growth "
             "curve itself, and the comparison is the jaundice calculator "
             "\u2014 which exists and stays shut until a clinician accepts "
             "the table. What was missing is the join: a nurse read the "
             "number off the lab screen and did the comparison in their head, "
             "on the one calculation this program built so that nobody would "
             "have to."),
            ("<b>القراءة بتتحسب بساعة سحب العينة مش بدلوقتي.</b> في الأيام "
             "الأولى المنحنى بيتحرك بسرعة كفاية إن ساعات قليلة تعدّيه، فبيليروبين "
             "اتسحب الصبح بيتقارن بعمر الطفل وقتها.",
             "<b>The reading is judged at the hour the blood was drawn.</b> "
             "In the first days the curve moves fast enough that a few hours "
             "crosses it, so a bilirubin drawn this morning is compared "
             "against the baby's age at that moment."),
            ("<b>السرير هنا تلات أنواع.</b> سرير، وحضّانة، وكبسولة نقل. "
             "والكبسولة بتتحرك والإقامة بتفضل مفتوحة — الطفل نزل أشعة، ما "
             "خرجش من القسم.",
             "<b>Three kinds of bed here.</b> A cot, an incubator and a "
             "transport capsule. The capsule moves with the stay still open "
             "\u2014 the baby went down for an X-ray, they did not leave the "
             "unit."),
        ],
    },
    {
        "key": "ward",
        "module": "ward",
        "icon": "buildings",
        "title": ("الداخلي", "The wards"),
        "lines": [
            ("<b>القسم الداخلي بيتقرا بالأيام مش بالدقايق.</b> الطفل في سرير "
             "رقم أربعة مش رايح حتة قبل الخميس، والسؤال مش «مين الأول» — "
             "دول سؤالين تانيين: <b>مين محدش عمله راوند النهاردة</b>، "
             "و<b>مين متوقّع يخرج</b>.",
             "<b>A ward is read in days, not in minutes.</b> The child in bed "
             "four is not going anywhere before Thursday, and the question is "
             "not \u201cwho first\u201d \u2014 it is two others: <b>who has "
             "nobody been round to this morning</b>, and <b>who are we "
             "expecting to send home</b>."),
            ("<b>الراوند دوسة واحدة.</b> بيتحسّن، زي ما هو، بيسوء — والتلاتة "
             "أزرار. اللي بعد كده كله اختياري وراء «تفاصيل زيادة»: الحالة "
             "النهاردة، والخطة، وتاريخ الخروج المتوقّع. الطبيب واقف عند سرير "
             "وقدامه تمنية، فاللي بيتطلب منه يكتبه هو اللي مش موجود في البرنامج "
             "أصلاً.",
             "<b>A round is one press.</b> Improving, unchanged, worse \u2014 "
             "three buttons. Everything after that is optional and behind "
             "\u201cmore\u201d: how they are, the plan, and when we expect "
             "them home. The doctor is standing at a bed with eight more to "
             "see, so the only thing asked of them is the part the program "
             "does not already hold."),
            ("<b>والراوند الفاضي مرفوض.</b> صف من غير حالة كان هيقفل تنبيه "
             "«محدش شافه النهاردة» من غير ما حد يقرّب من الطفل — نفس القاعدة "
             "بالظبط اللي بترفض قراءة ملاحظات فاضية، ولنفس السبب.",
             "<b>And a blank round is refused.</b> A row with no trend on it "
             "would clear \u201cnobody has been round today\u201d without "
             "anybody having gone near the child \u2014 the same rule that "
             "refuses an empty observation, for the same reason."),
            ("<b>تاريخ الخروج المتوقّع بيتكتب على الراوند مش على الإقامة.</b> "
             "لأن اللي بيتغيّر بيحكي: «قلنا الخميس يوم الاتنين، وقلنا السبت "
             "يوم الأربعا» ده تاريخ الحالة، وعمود واحد على الإقامة كان هيمسح "
             "الإجابة القديمة كل مرة.",
             "<b>The expected discharge is written on the round, not on the "
             "stay.</b> What changed is the story: \u201cwe said Thursday on "
             "Monday and Saturday on Wednesday\u201d is the history, and a "
             "single column on the stay would have overwritten the earlier "
             "answer every time."),
            ("<b>لازم يكون فيه قسم متبني.</b> القسم بيتعمل من إعداد الأسرّة: "
             "قسم نوعه داخلي، وغرف، وسرير أو أكتر في كل غرفة.",
             "<b>A unit has to exist first.</b> It is built from the bed "
             "setup: a unit of kind ward, its rooms, and a bed or more in "
             "each."),
        ],
    },
    {
        "key": "icu",
        "module": "icu",
        "icon": "heart-pulse",
        "title": ("العناية المركزة", "Intensive care"),
        "lines": [
            ("<b>نفس شاشة الداخلي، بتتقرا أربع مرات أكتر.</b> اللي بيفرق هو "
             "كل قد إيه حد بيبص: طلب ملاحظات كل ساعة بدل راوند الصبح، وطفل "
             "آخر قراءة ليه البرنامج قراها «تستاهل تتشاف دلوقتي» بيبقى الحالة "
             "العادية هنا مش الاستثناء.",
             "<b>The ward screen, read four times as often.</b> What differs "
             "is how often somebody looks: an hourly observation order "
             "instead of a morning round, and a child whose last reading the "
             "program calls urgent is the normal case here rather than the "
             "alarm."),
            ("<b>ولا واحدة من الفروق دي في الكود.</b> المدة على طلب الملاحظات "
             "بتاع الطفل، اللي الطبيب كتبه؛ والحدود هي نسخة العيادة الوحيدة في "
             "<b>red_flags</b> و<b>vital_bands</b>. قسم بيحكم على حرارة بقاعدة "
             "خاصة بيه كان هيخلّي الطفل أحمر في شاشة وأخضر في شاشة والاتنين "
             "«مظبوطين».",
             "<b>None of those differences is in code.</b> The interval is on "
             "the child\u2019s own observation order, written by the doctor "
             "who admitted them; the thresholds are the clinic\u2019s single "
             "copy in <b>red_flags</b> and <b>vital_bands</b>. A department "
             "judging a temperature by its own rule would make a child red on "
             "one screen and green on another, each individually correct."),
            ("<b>العزل حيّز مش سرير.</b> صالة العناية فيها الأسرّة، والعزل "
             "بارتشن أو اتنين متعلّمين عزل في إعداد الأسرّة — وسؤال «فيه مكان "
             "عزل فاضي؟» بيتسأل وقت ما حالة معدية بتدخل، مش وقت الفراغ.",
             "<b>Isolation is a space, not a bed.</b> The bay holds the beds, "
             "and isolation is one or two partitions marked as such in the bed "
             "setup \u2014 and \u201cis there an isolation space free?\u201d "
             "is asked at the moment an infectious child is coming in, which "
             "is never a quiet moment."),
        ],
    },
    {
        # Opt-in like every department above it, and not part of `beds`: a
        # theatre is a schedule rather than a place a child sleeps, and a
        # hospital that admits children and operates on none of them must not
        # find a theatre list after an update.
        "key": "theatres",
        "module": "theatres",
        "icon": "scissors",
        "title": ("العمليات الجراحية", "Operating theatres"),
        "lines": [
            ("<b>العمليات جدول مش قسم فيه أسرّة.</b> غرفة العمليات بتتحجز، "
             "وتشتغل ساعة ونص، وتتنضف — مش مكان بينام فيه حد. فهي مش قسم في "
             "إعداد الأسرّة، والمكان اللي الطفل بيروحه بعدها سرير موجود أصلاً: "
             "الإفاقة نوع قسم من زمان، والقراءات المتكررة كل خمس دقايق هي "
             "نفسها الملاحظات.",
             "<b>Theatres are a schedule, not a department with beds.</b> An "
             "operating room is booked, used for ninety minutes and cleaned "
             "\u2014 nobody sleeps in it. So it is not a unit in the bed "
             "setup, and the place a child goes afterwards already exists: "
             "recovery has been a unit kind since the wards were built, and "
             "the five-minute readings it runs on are the observations."),
            ("<b>قايمة الفحص هي قلب الشاشة مش ورقة جنبها.</b> قايمة منظمة "
             "الصحة العالمية: تلات وقفات — قبل التخدير، وقبل أول جرح، وقبل ما "
             "الفريق يسيب الغرفة. وكل وقفة بتتوقّع من حد في لحظة، فالبرنامج "
             "يقدر يقول <b>أي وقفة ماحصلتش</b> — وده اللي بيخلّيها قايمة فحص "
             "مش بوستر.",
             "<b>The checklist is the screen, not a poster beside it.</b> The "
             "WHO checklist has three stops: before anaesthesia, before the "
             "first cut, and before the team leaves the room. Each is signed "
             "by somebody at a moment, so the program can say <b>which stop "
             "nobody made</b> \u2014 which is what makes it a checklist."),
            ("<b>حاجة واحدة بس البرنامج بيرفضها.</b> إنك تدخل الطفل الغرفة "
             "ووقفة «قبل التخدير» لسه ماتوقّعتش. أي حاجة تانية بيسجّلها زي ما "
             "حصلت: وقفة اتوقّعت وفيها بنود مش متعلّم عليها بتتخزّن بالبنود "
             "الناقصة بالاسم — لأن قايمة بتقرّب «أربعة من سبعة» لـ«تمام» "
             "بتعمل توقيع مكانش موجود، وده أسوأ من إنه مفيش قايمة أصلاً.",
             "<b>The program refuses exactly one thing.</b> Starting a case "
             "whose sign-in has not been signed. Everything else it records "
             "as it happened: a stop signed with items unticked is stored "
             "with the unticked ones named \u2014 because a checklist that "
             "rounds \u201cfour of seven\u201d up to \u201cdone\u201d "
             "manufactures a signature, which is worse than no checklist."),
            ("<b>والخروج من الغرفة مش مرفوض لو الوقفة التالتة ناقصة.</b> "
             "لأن رفض إنك تسجّل إن العملية خلصت كان هيسيب الطفل جوّه الغرفة "
             "للأبد في كلام البرنامج نفسه. الشاشة بتقول إن الوقفة ناقصة "
             "وتفضل قايلة — فجوة باينة أحسن من رفض الناس بتلف حواليه.",
             "<b>But finishing is never refused for a missing sign-out.</b> "
             "Refusing to record that an operation ended would leave the "
             "child in theatre for ever in the program\u2019s own telling. "
             "The screen says the stop is missing and goes on saying it "
             "\u2014 a visible gap is worth more than a refusal people work "
             "around."),
            ("<b>العملية بتتحاسب زي أي خدمة، وعلى فاتورة الإقامة الواحدة.</b> "
             "بتختار ليها خدمة من قايمة أسعار العيادة، فالتأمين ونسبة الطبيب "
             "والضريبة والمستهلكات كلها بتمشي من غير أي حاجة زيادة — ونصيب "
             "الطبيب بيتقرا على <b>الجرّاح</b>، مش الطبيب المعالج. والعملية "
             "اللي محدش حطّ عليها خدمة عمرها ما بتوصل لفاتورة، والشاشة بتقول "
             "كده بصوت عالي.",
             "<b>An operation is charged as a service, on the stay\u2019s one "
             "bill.</b> You pick a service from the clinic\u2019s own price "
             "list, so the insurance, the doctor\u2019s share, the tax code "
             "and the consumables all follow with nothing added \u2014 and "
             "the share is read against the <b>surgeon</b>, not the admitting "
             "doctor. An operation nobody priced never reaches a bill, and "
             "the screen says so out loud."),
            ("<b>وحالة اليوم الواحد بتتحاسب على الديسك.</b> الطفل اللي "
             "اتعمل له عملية ومشي من غير تنويم مالوش إقامة تشيل فاتورته، "
             "فالعملية بتظهر في شاشة التحصيل زي أي حاجة تانية لسه ماتحاسبتش "
             "— وأول ما تتحصّل بتتختم بالسطر اللي دفع عنها، فما بترجعش تظهر "
             "تاني في الزيارة الجاية.",
             "<b>And a day case is charged at the desk.</b> A child operated "
             "on who went home without being admitted has no stay to carry "
             "their bill, so the operation shows up on the collection screen "
             "like anything else still unbilled \u2014 and once collected it "
             "is stamped with the line that paid for it, so it does not come "
             "back at the next visit."),
            ("<b>بابين للحجز.</b> الحالة اليومية بتتحجز من جدول العمليات "
             "نفسه؛ والطفل اللي منوّم بيتحجز من شاشة إقامته، لأن ده المكان "
             "اللي اللي بيتابعه واقف فيه. باب واحد كان هيخفي النوع التاني.",
             "<b>Two doors.</b> A day case is booked from the theatre list "
             "itself; a child already in a bed is booked from their stay "
             "screen, because that is where whoever is looking after them is "
             "standing. One door would have hidden the other kind of case."),
        ],
    },
    {
        # Opt-in: a clinic that sends its tests out has no bench, and ordering
        # from the visit screen has never depended on this module.
        "key": "labs",
        "module": "labs",
        "icon": "eyedropper",
        "title": ("المعمل", "The lab"),
        "lines": [
            ("<b>الطلب والقراية كانوا موجودين، والنص الناقص هو اللي المستشفى "
             "بتعيش فيه.</b> الطلب من شاشة الكشف شغّال من زمان، والنتيجة "
             "بترجع للطبيب في صندوق النتايج، والمنحنى بيترسم من الرقم. اللي "
             "مكانش ليه شاشة خالص هو النص: حد بيروح للسرير يسحب العينة، وحد "
             "تاني بيعملها.",
             "<b>The order and the reading already existed; what was missing "
             "is the middle a hospital lives in.</b> Ordering has worked from "
             "the visit screen for years, the answer reaches the doctor in "
             "the results inbox, and the curve is drawn from the number. What "
             "had no screen at all is the part between: somebody walks to the "
             "bed and draws the sample, and somebody else runs it."),
            ("<b>«محدش راح للسرير» و«العينة في الرَف» مش نفس الحاجة.</b> "
             "الأولى محتاجة حد يمشي، والتانية محتاجة وقت بس. طول ما الاتنين "
             "متسجلين «مطلوب» الشاشة مش قادرة تفرّق بينهم — والقايمة اللي "
             "مش قادرة تفرّق دي بيتم مراجعتها بالتليفون.",
             "<b>\u201cNobody has been to the bed\u201d and \u201cit is in "
             "the rack\u201d are not the same thing.</b> The first needs a "
             "person to walk; the second needs only time. While both are "
             "stored as \u201crequested\u201d the screen cannot tell them "
             "apart \u2014 and a list that cannot tell them apart is checked "
             "by phone."),
            ("<b>الرَف مقسوم قسمين، لأنهم شغلانتين.</b> عينات تتسحب، وعينات "
             "تتعمل. والترتيب من الأقدم للأحدث: الرَف بيتشتغل من تحت، "
             "والقايمة اللي بتحط طلب الدقيقة دي فوق هي اللي بتخلّي عينة "
             "الساعة تمانية لسه واقفة الساعة اتنين.",
             "<b>The rack is two lists, because they are two jobs.</b> "
             "Samples to draw, and samples to run. Oldest first, not newest: "
             "a rack is worked from the bottom, and a list that puts this "
             "minute\u2019s order on top is one where the sample taken at "
             "eight is still sitting there at two."),
            ("<b>رقم الأنبوبة بيتكتب لوحده.</b> تاريخ اليوم ورقم الطلب. "
             "سيبها فاضية والبرنامج يكتبها — لأن اللي بيتكتب لوحده هو اللي "
             "بيتكتب فعلاً على الأنبوبة الساعة تلاتة بالليل.",
             "<b>The tube label writes itself.</b> The clinic\u2019s date and "
             "the order\u2019s own number. Leave it blank and one is written "
             "\u2014 because a label nobody has to invent is a label that "
             "actually ends up on the tube at three in the morning."),
            ("<b>مفيش مكان تاني للنتيجة.</b> الرقم بيتكتب على نفس الطلب اللي "
             "بيجاوبه — نفس الصف اللي شاشة الكشف بتعرضه واللي المنحنى "
             "بيتقري منه. جدول نتايج تاني كان هيبقى نسختين من رقم واحد، "
             "والمنحنى يقرا اللي آخر شاشة كتبت فيه.",
             "<b>There is no second place for a result.</b> The number is "
             "written on the order it answers \u2014 the same row the visit "
             "screen shows and the curve is drawn from. A separate results "
             "table would have been two copies of one number, with the curve "
             "reading whichever half the last screen wrote to."),
            ("<b>والمدى المرجعي هو اللي التقرير نفسه قاله.</b> مدى الأطفال "
             "بيتحرك مع العمر ومع الجهاز، ورقم واحد متخزّن ومعروض لكل طفل "
             "ده البرنامج بيخترع حقيقة إكلينيكية — نفس القاعدة اللي جداول "
             "التطعيمات موجودة عشانها.",
             "<b>And the reference range is the one this report printed.</b> "
             "A paediatric range moves with age and with the assay, and one "
             "number stored centrally and shown for every child would be the "
             "program inventing a clinical fact \u2014 the same rule the "
             "vaccine tables exist to keep."),
            ("<b>السعر هو المفتاح.</b> كل تحليل بيتربط بخدمة من قايمة أسعار "
             "العيادة، فالتأمين والخصومات والضريبة بيمشوا عليه من غير أي حاجة "
             "زيادة. وتحليل من غير خدمة بيتطلب ويتسحب ويتعمل وعمره ما يوصل "
             "لفاتورة — وده إزاي مستشفى ما بتحاسبش على المعمل بشكل منفصل "
             "بتقول كده من غير إعداد.",
             "<b>The price is the switch.</b> Each test is tied to a service "
             "from the clinic\u2019s own price list, so the insurance, the "
             "discounts and the tax code all follow with nothing added. A "
             "test with no service is ordered, drawn, run and resulted and "
             "never reaches a bill \u2014 which is how a hospital that does "
             "not bill its lab separately says so, with no setting for it."),
            ("<b>والحساب بيبدأ من ساعة سحب العينة، مش من ساعة الطلب.</b> طلب "
             "اتكتب وبعدين حد عدل عنه ما كلّفش حاجة؛ المستشفى بتكون صرفت أول "
             "ما العينة بقت موجودة. الطفل المنوّم بيتحاسب على فاتورة إقامته، "
             "واللي جه ومشي بيتحاسب على الديسك زي أي حاجة تانية.",
             "<b>And charging starts at the draw, not at the order.</b> An "
             "order somebody wrote and thought better of costs nothing; the "
             "hospital has spent something the moment the sample exists. An "
             "admitted child\u2019s tests go on their stay\u2019s bill; an "
             "outpatient\u2019s reach the desk like everything else."),
        ],
    },
    {
        # Opt-in: a clinic whose families fill their prescriptions outside has
        # no counter, and the prescription writer never depended on this.
        "key": "pharmacy",
        "module": "pharmacy",
        "icon": "prescription2",
        "title": ("الصيدلية", "The pharmacy"),
        "lines": [
            ("<b>الجرعة بالكيلو والتعارضات كانوا موجودين من زمان، ومااتعملوش "
             "تاني.</b> الجرعة في <b>dosing</b> والتعارض والحساسية في "
             "<b>rx_safety</b>، وشاشة الروشتة بتوريهم للطبيب من سنين. نسخة "
             "تانية من أي واحد فيهم كانت هتبقى مجموعة تانية من الأرقام "
             "الإكلينيكية — الحاجة الوحيدة اللي البرنامج ده عمره ما بيعملها "
             "مرتين.",
             "<b>The dose by weight and the interactions already existed and "
             "are not rebuilt.</b> The paediatric dose lives in <b>dosing</b>, "
             "the interaction and allergy checks in <b>rx_safety</b>, and the "
             "prescription writer has shown both to the doctor for years. A "
             "second copy of either would be a second set of clinical numbers "
             "\u2014 the one thing this program never does twice."),
            ("<b>اللي مكانش موجود هو التسليم نفسه.</b> الروشتة كانت بتتكتب "
             "وتتطبع وتخلص خلاص من ناحية البرنامج: العلبة بتخرج من الرف "
             "والمخزن مايعرفش، ومحدش بيتحاسب. الشاشة دي هي الكاونتر — "
             "الطابور، والمراجعة، والتسليم.",
             "<b>What did not exist is the handover.</b> A prescription was "
             "written, printed, and that was the end of it as far as this "
             "software was concerned: the box left the shelf without the "
             "clinic\u2019s own stock knowing, and nothing was charged. This "
             "is the counter \u2014 the queue, the review and the handover."),
            ("<b>الصيدلي بيشوف نفس اللي الطبيب شافه.</b> ده مقصود: عين تانية "
             "بتقرا كتاب تاني مش عين تانية.",
             "<b>The pharmacist sees exactly what the doctor saw.</b> That is "
             "the point: a second pair of eyes reading a different rulebook is "
             "not a second pair of eyes."),
            ("<b>سؤال، مش رفض.</b> الصيدلي اللي بيقرا جرعة شايفها غلط شغلته "
             "إنه يقولها للي كتبها. بيتسجّل كـ<b>سؤال</b> والصنف بيفضل قابل "
             "للتسليم — لأن الرد غالباً «أيوة أنا قاصدها»، والأهل واقفين. "
             "وصيدلية تقدر ترفض روشتة هي صيدلية الروشتات بتتكتب من حواليها.",
             "<b>A question, never a veto.</b> A pharmacist who reads a dose "
             "they think is wrong has one job: to say so, to the person who "
             "wrote it. It is recorded as a <b>question</b> and the line stays "
             "dispensable \u2014 the answer is usually \u201cyes, I meant "
             "it\u201d and the family is standing there. A pharmacy that can "
             "block a prescription is one prescriptions get written around."),
            ("<b>الصنف من غير علبة من رفنا بيتصرف بره، وده الطبيعي.</b> "
             "العيادة اللي بتكتب روشتات والأهل بيصرفوها من الصيدلية اللي "
             "تحت مالهاش دعوة بالشاشة دي خالص: مفيش حاجة بتخرج من مخزننا "
             "ومفيش حاجة بتتحاسب — نفس قاعدة أمر الدوا اللي مش مربوط برف، "
             "والسرير اللي مالوش سعر.",
             "<b>A line with no box of ours on it is filled outside, and that "
             "is the normal case.</b> A clinic that writes prescriptions for "
             "families to fill at the pharmacy downstairs is untouched by this "
             "screen: nothing leaves our stock and nothing is charged \u2014 "
             "the same rule as a ward order with no shelf behind it and a bed "
             "with no rate on it."),
            ("<b>واللي بيتسلّم بيتحاسب وبيخرج من الرف في نفس اللحظة.</b> "
             "السطر بيتحط على فاتورة الديسك، والعلبة بتطلع بإذن صرف واحد "
             "راكب على الفاتورة، فتكلفة البضاعة المباعة بتتقيّد في نفس "
             "القيد. والسطر مالوش خدمة، يعني مفيش نسبة طبيب — محدش بياخد "
             "نسبة على علبة اتسلّمت من على كاونتر.",
             "<b>And what is handed over is charged and leaves the shelf in "
             "the same act.</b> The line goes on the desk\u2019s invoice and "
             "the box leaves under one issue document riding on it, so the "
             "cost of goods is journalled in the same posting. The line "
             "carries no service and therefore no doctor commission \u2014 "
             "nobody\u2019s percentage rides on a box being handed across a "
             "counter."),
            ("<b>والنص التاني من المهنة: مراجعة علاج المنوّمين.</b> الكاونتر "
             "ده الصيدلية اللي بتصرف — طابور ناس واقفة بورق. الصيدلة "
             "الإكلينيكية هي اللي المستشفى بتشتريها: حد بيقرا ورقة علاج كل "
             "طفل في سرير، على وزنه وعلى الأربع حاجات التانية اللي هو "
             "عليها، ويقول للطبيب حاجة **قبل** ما الجرعة تتاخد.",
             "<b>And the other half of the profession: the inpatient chart "
             "review.</b> The counter is the dispensing pharmacy \u2014 a "
             "queue of people holding paper. Clinical pharmacy is what a "
             "hospital buys: somebody who reads the drug chart of every child "
             "in a bed, against that child\u2019s weight and the four other "
             "things they are on, and says something to the doctor "
             "<b>before</b> a dose is given."),
            ("<b>واللوحة بتسأل نفس سؤال الراوند: مين محدش عدّى عليه "
             "النهاردة.</b> ورقة علاج اتراجعت الاتنين ما بتقولش حاجة عن الدوا "
             "اللي اتكتب الأربع. والمراجعة **صف**، مش علامة: إقامة مفيهاش "
             "أسئلة شكلها زي إقامة محدش فتحها، ودول حقيقتين متعاكستين.",
             "<b>And the board asks the round\u2019s own question: whose "
             "chart has nobody been through today.</b> A chart reviewed on "
             "Monday says nothing about the drug started on Wednesday. The "
             "review is a <b>row</b>, not a tick: a stay with no queries on "
             "it looks exactly like a stay nobody opened, and those are "
             "opposite facts."),
            ("<b>والسؤال بيوصل للطبيب في الشاشة اللي هو فيها.</b> السؤال "
             "بيتكتب من الصيدلية وبيظهر على شاشة الإقامة، والطبيب بيرد من "
             "هناك — لأنه أصلاً ما بيفتحش مديول الصيدلية. سؤال مالوش رد إلا "
             "من شاشة اللي المفروض يرد عليها مش بيقدر يفتحها هو سؤال محدش "
             "بيرد عليه، والصيدلي يفضل مستني من غير ما يعرف الفرق بين ده "
             "وبين إن حد تجاهله.",
             "<b>And the question reaches the doctor on the screen they are "
             "already on.</b> It is written from the pharmacy and appears on "
             "the stay screen, and the reply goes back from there \u2014 "
             "because the doctor cannot open the pharmacy module at all. A "
             "question answerable only on a screen the person who has to "
             "answer it cannot reach is a question nobody answers, and the "
             "pharmacist waits with no way to tell that from being ignored."),
            ("<b>والدوا بيتاخد عادي والسؤال مفتوح.</b> الرد غالباً «أيوة أنا "
             "قاصدها» والطفل في السرير، وصيدلية تقدر توقف دوا العنبر هي "
             "صيدلية العنبر بيكتب من حواليها. والسؤال بيفضل مكتوب بعد الرد: "
             "اللي اتسأل واللي رجع هو السجل، ومسحه كان هيسيب جرعة اتغيّرت "
             "من غير حاجة تقول ليه.",
             "<b>And the drug goes on being given while the question is "
             "open.</b> The answer is usually \u201cyes, I meant it\u201d "
             "and the child is in the bed; a pharmacy that can stop a "
             "ward\u2019s drug is one the ward writes around. The question "
             "stays on the order after it is answered: what was asked and "
             "what came back is the record, and clearing it would leave a "
             "changed dose with nothing saying why."),
            ("<b>وعمرها ما بترفض علبة عشان العدد بتاعنا بيقول الرف فاضي.</b> "
             "الصيدلية سلّمت، وده حصل. البرنامج اللي بيرفض يسجّله عشان عدّه "
             "بيقول حاجة تانية بيكون استبدل حقيقة بترتيب — الحركة بتتسجّل، "
             "والرصيد مسموح له ينزل تحت الصفر، والفرق ده شغل الجرد مش دوا "
             "الطفل.",
             "<b>And a box is never refused for want of stock.</b> The "
             "pharmacy handed it over; that happened. A program that declines "
             "to record it because its own count disagrees has replaced a true "
             "fact with a tidy one \u2014 the movement is posted, the stock is "
             "allowed to go negative, and the difference is the store\u2019s "
             "to reconcile rather than a medicine to take back off a child."),
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

            ("<b>قبل ما تدّي الجرعة، البرنامج بيتأكد من 4 حاجات وبيقولك</b>: "
             "إن الجرعة دي مش متسجّلة قبل كده، إن الكورس مش خلص، إن الفاصل "
             "الزمني عن الجرعة اللي قبلها كفاية (بيطلع تحذير بالأيام والحد "
             "الأدنى)، وإنه بيخصم من <u>أقرب أمبولة انتهاءً</u>. التحذير "
             "بتاع الفاصل <b>تحذير مش منع</b> — القرار قرارك.",
             "<b>Before a dose is given the program checks four things and "
             "tells you</b>: that this dose is not already recorded, that the "
             "course is not finished, that enough time has passed since the "
             "previous dose (a warning naming the days and the minimum), and "
             "it deducts from the <u>nearest-expiry</u> vial. The interval "
             "warning is a <b>warning, not a block</b> — the call is yours."),

            ("<b>معلومات كل لقاح طبياً</b> — الأمراض اللي بيغطيها، السن "
             "الأدنى والأقصى، موانع الاستعمال، الاحتياطات، الأعراض الجانبية، "
             "أقل فاصل بين الجرعات، ملاحظات التطعيم مع لقاحات تانية، "
             "وملاحظات اللحاق (catch-up)، والمصدر. كلها بتتكتب من شاشة "
             "اللقاح وبتظهر للي بيدّي الجرعة.",
             "<b>Each vaccine's medical information</b> — diseases covered, "
             "minimum and maximum age, contraindications, precautions, adverse "
             "events, minimum interval, co-administration and catch-up notes, "
             "and the source. All entered on the vaccine's screen and shown to "
             "whoever gives the dose."),

            ("<b>جرعة اتاخدت برّه العيادة</b> بتتسجّل بعلامة «خارج العيادة» "
             "ومكانها. ده بيخلّي الجرعة في ملف الطفل — فالكورس ما بيبتديش من "
             "الأول — من غير ما تتخصم من مخزنك ولا تدخل في فلوسك.",
             "<b>A dose given elsewhere</b> is recorded as \u201cgiven "
             "outside\u201d with the place. That keeps it in the child's "
             "record \u2014 so the course is not restarted \u2014 without "
             "touching your stock or your books."),

            ("<b>الجرعة المسجّلة غلط بتتصلّح، مش بتتمسح وتتكتب تاني.</b> من "
             "الملف تقدر تغيّر <b>رقم الجرعة</b> وتاريخها وهل كانت برّه "
             "العيادة. ده موجود عشان تاريخ متنقول من برنامج قديم بيرقّم "
             "الجرعات بترتيب تواريخها هو شايفها — طفل خد اتنين عندك وواحدة "
             "برّه والبوستر عندك بيطلع 1 و2 و3 وهو في الحقيقة 1 و3 و4. "
             "البرنامج بيخمّن، وانت بتصحّح.",
             "<b>A dose recorded wrongly is corrected, not deleted and "
             "re-entered.</b> From the file you can change its <b>dose "
             "number</b>, its date, and whether it was given outside. This "
             "exists because a history imported from an old program numbers "
             "doses by the order of the dates it can see \u2014 a child who "
             "had two here, one elsewhere and the booster here comes out 1, 2, "
             "3 when they are really 1, 3, 4. The program infers; you "
             "correct."),

            ("<b>لقاحين مختلفين لنفس المرض بيكمّلوا بعض.</b> طفل خد 3 جرعات "
             "سينفلوريكس وبعدين بريفينار مش بيبتدي من الأول. من شاشة اللقاح "
             "تقول «الجرعات دي بتُحتسب من الكورس ده» وتحدد لحد أنهي جرعة. "
             "من غير ده الشهادة بتقول إنه واخد الكورس كله من صنف واحد، وده "
             "مش صحيح.",
             "<b>Two different products can continue one course.</b> A child "
             "who had three Synflorix and then a Prevenar does not start "
             "again. On the vaccine's screen you say \u201cdoses of this one "
             "count towards that course\u201d, up to a dose number you set. "
             "Without it the certificate reads as a whole course of one "
             "brand, which is not what happened."),

            ("<b>الشهادة بتقول الاسم التجاري لكل جرعة</b> والاسم العام فوقه، "
             "وبتميّز الجرعة المنشطة. وفيها كود QR بيفتح صفحة تحقق — الجهة "
             "اللي استلمت الشهادة تقدر تتأكد إنها طالعة من عندك.",
             "<b>The certificate names the brand on every dose</b> with the "
             "generic name above it, and marks a booster as a booster. It "
             "carries a QR code opening a verification page, so whoever "
             "receives it can check it came from you."),
        ],
    },
    {
        # Dentistry is opt-in, so `visible_to` hides this from every clinic
        # that has not switched the module on — which is most of them. A
        # paediatric practice is not shown a guide to a tooth chart it does
        # not have.
        "key": "dentistry",
        "module": "dentistry",
        "icon": "emoji-smile",
        "title": ("عيادة الأسنان", "The dental clinic"),
        "lines": [
            # Added after the module shipped with no way into it: the screens
            # existed and nothing linked to them. A guide that describes what
            # a chart does and not how to open it teaches the wrong half.
            ("<b>إزاي توصله.</b> من ملف المريض ← تاب <b>أسنان</b>، أو من شاشة "
             "الكشف نفسها لما تختار قالب الأسنان. والشريط الجانبي ← أسنان "
             "بيوريك اللي عندهم خطط شغالة دلوقتي.",
             "<b>How to open it.</b> From the patient file, the <b>Teeth</b> "
             "tab — or from the consultation screen itself once the dental "
             "panel is chosen. Sidebar → Dentistry lists the children with a "
             "plan in progress."),
            ("<b>الترتيب من الأول للآخر.</b> افتح الخريطة ← دوس على السن ← "
             "سجّل الحالة والسطح ← «ضيف للخطة» (بياخد رقم السن والسطح معاه) ← "
             "كمّل بنود المسوّدة وسعّرها ← اعرضها على الأهل ← «قبول الخطة» "
             "والعربون ← وكل جلسة علّم البند اللي اتعمل.",
             "<b>The order, start to finish.</b> Open the chart → tap the "
             "tooth → record the condition and the surface → \u201cadd to "
             "plan\u201d (it carries the tooth and the surface across) → "
             "finish and price the draft → show it to the family → "
             "\u201caccept\u201d with a deposit → then tick each item done "
             "as the sessions happen."),
            ("<b>الشكل بيقول قبل ما تقرا.</b> كل سن مرسوم بشكله — قاطعة، ناب، "
             "ضاحك، ضرس — واللبني أصغر وأفتح. المخلوع بيتشطب ومش بيتشال، لأن "
             "الفراغ نفسه معلومة. وقايمة الأسطح بتتغيّر مع السن: السن الأمامي "
             "مالوش سطح طاحن فمش هيتعرض لك.",
             "<b>The drawing says it before you read it.</b> Each tooth is "
             "drawn as what it is \u2014 incisor, canine, premolar, molar "
             "\u2014 with the primary set smaller and lighter. An extracted "
             "tooth is struck through rather than removed, because the gap is "
             "itself a finding. The surface list follows the tooth: a front "
             "tooth has no biting table, so it is not offered one."),
            ("<b>خريطة الأسنان بترقيم FDI</b> — الرقم نفسه بيقول لبني ولا "
             "دائم: 16 ضرس دائم و55 اللبني اللي فوقه. الفكّين بيتعرضوا مع "
             "بعض على طول، لإن الطفل من 6 لـ12 سنة بيبقى عنده الاتنين، "
             "وخريطة بتوري واحد بس بتوري نص الفم.",
             "<b>An FDI tooth chart</b> \u2014 the number itself says primary "
             "or permanent: 16 is the adult molar, 55 the baby one above it. "
             "Both dentitions are always on one page, because between six and "
             "twelve a child has both and a chart showing one shows half a "
             "mouth."),

            ("<b>الملاحظة بتتسجّل على سطح، مش على سن.</b> تسوس على سطح "
             "العض في 55 وحشو على السطح اللي بينه وبين 54 دول حاجتين. "
             "الأسنان الأمامية ملهاش سطح عض والضروس ملهاش حرف قاطع — "
             "البرنامج بيرفض سطح مش موجود في السن ده بدل ما يخزّنه.",
             "<b>A finding belongs to a surface, not to a tooth.</b> Caries on "
             "the biting surface of 55 and a filling between 55 and 54 are two "
             "different facts. Front teeth have no biting table and molars no "
             "incisal edge \u2014 a surface the tooth does not have is refused "
             "rather than stored."),

            ("<b>مفيش حاجة بتتمسح.</b> سن اتحشى السنة اللي فاتت وبيتسوّس "
             "تاني السنة دي ليه تاريخ، والتاريخ ده هو الحجة للتلبيسة. "
             "الخريطة بتوري الأحدث لكل سطح، والملف ماسك الباقي.",
             "<b>Nothing is deleted.</b> A tooth filled last year and decayed "
             "again this year has a history, and that history is the argument "
             "for a crown. The chart shows the latest per surface; the file "
             "keeps the rest."),

            ("<b>الخطة هي الفلوس.</b> المسوّدة بتتكتب وتتسعّر وتترمي من غير "
             "أي أثر في الدفاتر. لما الأهل يوافقوا، «قبول الخطة» بيطلع "
             "<u>فاتورة واحدة بإجمالي متفق عليه</u> — مش فاتورة لكل خطوة — "
             "وكل بند فيها مكتوب عليه السن، عشان الأب يقدر يقارن الكشف "
             "بفم ابنه. بعد القبول الخطة ما بتتعدّلش: ده اللي الأهل "
             "وافقوا عليه.",
             "<b>The plan is the money.</b> A draft is written, priced and "
             "thrown away with nothing in the books. When the family agrees, "
             "\u201caccept\u201d raises <u>one invoice for the agreed "
             "total</u> \u2014 not one per step \u2014 and every line names "
             "its tooth so a parent can hold the statement against their "
             "child's mouth. An accepted plan is not editable: it is what the "
             "family agreed to."),

            ("<b>الدفعة المقدمة دفعة عادية على الفاتورة دي</b> — نفس الرصيد "
             "المتبقي، ونفس كشف الحساب، ونفس تقرير الأعمار. تقدر تحدد نسبة "
             "مقدم في الإعدادات (<b>dental_deposit_percent</b>) والشاشة "
             "هتقولها، <b>بس مش هتمنع أقل منها</b>: أهل بيدفعوا النص "
             "النهاردة والباقي الأحد ده يوم عادي، وبرنامج بيرفض فلوسهم "
             "برنامج الناس بتلفّ حواليه. وتنفيذ بند من الخطة <b>ما بيحاسبش "
             "تاني</b> — الخطة اتحاسبت مرة واحدة عند القبول.",
             "<b>A deposit is an ordinary payment on that invoice</b> "
             "\u2014 same running balance, same statement, same aging report. "
             "You can set an asking percentage in settings "
             "(<b>dental_deposit_percent</b>) and the screen will show it, "
             "<b>but it never refuses less</b>: a parent paying half today and "
             "the rest on Sunday is a normal afternoon, and a program that "
             "refuses their money is one the desk works around. Carrying out a "
             "planned item <b>does not bill again</b> \u2014 the plan was "
             "billed once, at acceptance."),

            ("<b>الخريطة بتناول السن للخطة، ومش بتقترح العلاج.</b> السن "
             "اللي عليه حاجة بيتعلّم، وبيتبعت للمسوّدة برقمه والسطح بتاعه "
             "والملاحظة — <u>من غير إجراء ولا سعر</u>. التسوس ممكن يكون حشو "
             "أو بتر عصب أو خلع حسب عمقه وعمر السن، وده حكمك انت قدام "
             "الطفل. برنامج يقرا «تسوس» ويكتب «حشو» بيوصف علاج من كلمة.",
             "<b>The chart hands a tooth to the plan; it does not suggest the "
             "treatment.</b> A tooth with something on it is marked and can be "
             "sent to the draft with its number, its surface and the finding "
             "\u2014 <u>and no procedure and no price</u>. Caries can be a "
             "filling, a pulpotomy or an extraction depending on how deep it "
             "has gone and how long the tooth has left, and that is your call "
             "in front of the child."),

            ("<b>حافظ المسافة.</b> ضرس لبني راح بدري بيسيب مكان بتزحف عليه "
             "الأسنان اللي جنبه، والضاحك اللي تحته بيلاقي المكان قافل. "
             "الخريطة <b>بترفع السؤال</b> على الضروس اللبنية (المكان 4 و5) "
             "اللي اتخلعت أو مفقودة ومفيش حاجة ماسكة مكانها، وبتقولك السن "
             "الدائم الجاي رقم كام عشان تبص على الأشعة الصح. <u>البرنامج "
             "ما بيقولش «ركّب حافظ»</u> — القرار على الأشعة وعمر الطفل، "
             "والقواطع الأمامية أصلاً بتفقد مسافة قليلة. لما تركّب واحد "
             "بتسجّله على السن (<b>حافظ مسافة</b>) والتنبيه بيقفل.",
             "<b>Space maintainers.</b> A primary molar lost early leaves a "
             "gap the neighbouring teeth drift into, and the premolar "
             "underneath arrives to find it closed. The chart <b>raises the "
             "question</b> on primary molars (positions 4 and 5) that are gone "
             "with nothing holding the space, and names the permanent tooth "
             "due there so you know which X-ray to read. <u>It never says "
             "\u201cfit one\u201d</u> \u2014 that is the X-ray and the "
             "child's age, and front teeth lose very little space anyway. "
             "Recording a fitted maintainer on the tooth closes the prompt."),

            ("<b>الأسعار بتاعتك انت.</b> تعليم «أسنان» في تصطيب البرنامج "
             "بيزرع قائمة أسعار أسنان أطفال — حشو وبتر عصب وتلبيسة ستانلس "
             "وحافظ مسافة وخلع، واللبني متسعّر غير الدائم. كل سعر وكل "
             "نسبة عمولة بتتعدّل من شاشة الخدمات.",
             "<b>The prices are yours.</b> Ticking \u201cdentistry\u201d in "
             "the setup wizard seeds a paediatric dental price list "
             "\u2014 fillings, pulpotomy, stainless steel crown, space "
             "maintainer, extraction, with primary and permanent priced apart. "
             "Every price and commission is editable on the services screen."),
            # Interceptive orthodontics: what a paediatric clinic actually
            # does about a bite. Deliberately not a full ortho module — see
            # the panel fields in specialty_panels.json.
            ("<b>التقويم الاعتراضي.</b> قالب الأسنان بيسأل عن الإطباق ومكان "
             "الإطباق العكسي والبروز بالمليمتر وعلاقة الأرحاء — ومعاهم "
             "<b>القرار</b> و<b>ميعاد المراجعة</b>. القرار وميعاد المراجعة "
             "هما اللي بيخلوه اعتراضي: التدخل بيشتغل في سن معيّن، والنافذة "
             "بتقفل والطفل بيكبر. ولاحظ إن العادات (مص الصباع، التنفس من "
             "الفم) في نفس القالب — لأنها غالباً هي السبب.",
             "<b>Interceptive orthodontics.</b> The dental panel asks about "
             "the bite, where a crossbite is, the overjet in millimetres and "
             "the molar relation \u2014 and with them a <b>decision</b> and a "
             "<b>review date</b>. Those two are what make it interceptive: "
             "the intervention works at a particular age, and the window "
             "closes while the child grows. Note that the habits \u2014 "
             "thumb, dummy, mouth breathing \u2014 are on the same panel, "
             "because they are often the cause."),
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
    "medication_order": ("كتابة أوامر الدواء للأطفال المنوّمين",
                         "Write drug orders for admitted children"),
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


def modules_without_a_section():
    """Modules the guide says nothing about.

    The mirror of :func:`unknown_modules`, and the one that was missing.
    That function catches a section pointing at a module that does not exist;
    nothing caught a **module with no section**, so dentistry was added — a
    tooth chart, treatment plans, deposits — and the guide stayed silent about
    all of it. A dentist opened the handbook and found nothing about the
    screens they spend the day in.

    ``ALWAYS_ON`` members that are pure plumbing are not excused: `settings`
    and `users` both have sections, and `dashboard` does too.
    """
    covered = {s["module"] for s in SECTIONS if s.get("module")}
    return [m for m in MODULES if m not in covered]


def unknown_modules():
    """Sections pointing at a module that does not exist.

    A typo here silently hides a section from everybody — ``can_access`` says
    no to a module nobody has. Checked by a test rather than trusted.
    """
    known = set(MODULES)
    return [s["key"] for s in SECTIONS
            if s.get("module") is not None and s["module"] not in known]
