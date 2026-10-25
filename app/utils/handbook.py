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
            ("<b>القايمة الجانبية:</b> فوقها خانة «دوّر على صفحة أو طفل» — اكتب "
             "اسم الصفحة أو اسم الطفل أو رقم ملفه أو تليفون الأهل، واختار بالأسهم "
             "وEnter، أو اضغط Ctrl+K من أي مكان. الصفحات اللي بتطلع هي اللي "
             "مسموحلك تفتحها بس، والمدير يقدر يقفل الخانة للعيادة كلها من "
             "الإعدادات ← «شعار العيادة». في المستشفى القايمة متقسمة أقسام (العيادة، "
             "المستشفى، الفلوس والمخزن، الجودة، التقارير والرسايل، الإدارة)، وكل "
             "قسم بيتقفل ويتفتح من عنوانه والاختيار بيفضل محفوظ على الجهاز ده؛ "
             "القسم اللي فيه الصفحة اللي انت فيها بيفضل مفتوح. وزرار [ بيصغّر "
             "القايمة لأيقونات.",
             "<b>The side menu:</b> at its top, «Find a page or a child» — type a "
             "page's name, a child's name, file number or a parent's phone, pick "
             "with the arrows and Enter, or press Ctrl+K from anywhere. Only pages "
             "you may open are offered; the administration can switch the box "
             "off for the whole clinic in Settings → «Clinic logo». In a hospital the menu is in sections "
             "(Clinic, Hospital, Money and stock, Quality, Reports and messages, "
             "Administration); each folds from its title and stays as you left it "
             "on this computer, and the section holding the page you are on stays "
             "open. The [ key shrinks the menu to icons."),
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
            ("<b>إيقاف ملف لحين موافقة</b>: من ملف المريض ← «سجّل تنبيه مالي» — "
             "السبب مشكلة في الحساب أو مشكلة مع الأهل، و«منع مؤقت» بيوقف الحجز "
             "والتنويم المخطط لحد ما المدير المالي أو المدير المناوب (صلاحية "
             "«المدير المناوب» من المستخدمين) يوافق، وموافقته بتتسجّل باسمه. "
             "<b>الطوارئ عمرها ما بتتوقف</b> — التنبيه بيظهر بس. قايمة "
             "«الملفات الموقوفة» من المرضى، وتنبيه في الجرس للي منهم موجود النهارده.",
             "<b>A file on hold until a manager says</b>: patient file → «raise a "
             "financial note» — the account or the family; a hold stops bookings "
             "and planned admissions until the finance manager or the manager on "
             "duty (the «manager on duty» capability, under Users) says go ahead, "
             "recorded by name. <b>The emergency is never held</b> — the note "
             "only shows. «Files on hold» under Patients, and a bell for the "
             "ones here today."),
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
            ("<b>ملف الطفل لمستشفى تانية</b>: من صفحة المريض «ملف FHIR كامل» "
             "بينزّل الملف كله بصيغة FHIR R4، و«ملخص IPS» بينزّل ملخص المريض "
             "الدولي (المشاكل والحساسية والأدوية الحالية والتطعيمات "
             "والنتائج) للمستشفى اللي هتشوف الطفل لأول مرة. تنزيل بس — "
             "مفيش حاجة بتتبعت — وكل تنزيل بيتسجّل: مين، ولمين، وأنهي صيغة.",
             "<b>The child's file for another hospital</b>: on the patient's "
             "page, \"Full FHIR file\" downloads the whole record as FHIR R4, "
             "and \"IPS summary\" downloads the International Patient Summary "
             "(problems, allergies, current medicines, immunisations and "
             "results) for a hospital meeting the child for the first time. "
             "A download only — nothing is sent — and every download is "
             "logged: who, whose record, and which shape."),
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
            ("<b>طلبات المواعيد</b>: الأهل اللي بيطلبوا ميعاد بالتليفون أو "
             "الواتساب بيتسجّل طلبهم من «سجّل طلب» — لطفل عنده ملف، أو باسم "
             "ورقم للرد. <b>الطلب مش حجز</b>: مش ماسك ميعاد، ومفيش حاجة "
             "بتتقال للأهل غير لما الحجز يتعمل فعلاً. «احجز» بيفتح شاشة "
             "الحجز بكل مراجعاتها، و«اعتذر» لازم يتكتب معاه السبب.",
             "<b>Booking requests</b>: a family asking for an appointment by "
             "phone or WhatsApp is recorded under \"Take a request\" — for a "
             "child on file, or by a name and number to call back. <b>A "
             "request is not a booking</b>: it holds no slot, and nothing is "
             "said to the family until the booking is really made. \"Book\" "
             "opens the booking screen with all its checks, and \"Decline\" "
             "needs a reason."),
            ("<b>البطاقة جنب كل طلب</b>: سنّ الطفل وآخر زيارة والتطعيم الجاي، "
             "وتنبيه أحمر لو عنده ميعاد فعلاً، وجنبها <b>أقرب ميعاد فاضي</b> مع "
             "الدكتور المطلوب (أو أول دكتور فاضي). «احجز الميعاد ده» بيفتح شاشة "
             "الحجز والميعاد متعبّي — البطاقة بتقترح وإنت اللي بتحجز.",
             "<b>The card beside each request</b>: the child's age, last "
             "visit and next vaccine, a red warning if they already hold a "
             "booking, and beside it the <b>soonest free time</b> with the "
             "doctor asked for (or the first doctor free). \"Book this "
             "time\" opens the booking screen with it filled in — the card "
             "suggests, you book."),
            ("<b>الطارئ فوق</b>: الطلب اللي كلام الأهل فيه كلمة طوارئ (نفس "
             "قايمة صندوق الواتساب: تشنج، مش بيتنفس، ازرقاق…) بيطلع أول "
             "القايمة بالأحمر، والكلمة متعلّمة جوّه كلامهم — وبيبان التحذير "
             "وإنت لسه بتكتب. «مش طارئ» بتنزّله بضغطة، و«علّمه طارئ» بتطلّع "
             "طلب الكلمات فاتته، واسم اللي قال بيتسجّل. البرنامج بيرفع بس، "
             "ما بينزّلش، وما بيبعتش للأهل حاجة.",
             "<b>The urgent first</b>: a request whose words carry an "
             "emergency word (the WhatsApp inbox's own list: seizure, not "
             "breathing, turning blue…) goes to the top in red, the word "
             "marked in their words — and the warning shows while you are "
             "still typing. \"Not urgent\" takes it down in one click, and "
             "\"Mark urgent\" raises one the words missed; who said it is "
             "kept. The program only ever raises, and sends the family "
             "nothing."),
            ("<b>طلب من محادثة الواتساب</b>: من المحادثة نفسها «سجّل طلب ميعاد "
             "من المحادثة» — الطفل متختار، وكلام الأهل من آخر رد متنقل، ونوع "
             "الزيارة واليوم بضغطة. والمحادثة بتوريك الطلب واقف فين: اتسجّل، "
             "عند الدكتور، اتوافق، اتحجز.",
             "<b>A request from a WhatsApp chat</b>: from the chat itself, "
             "\"Take a booking request from this chat\" — the child already "
             "chosen, the family's words since the last reply copied, the "
             "visit type and the day one tap each. And the chat shows where "
             "the request stands: taken, with the doctor, approved, booked."),
            ("<b>«الاقتراح اتاخد كام مرة؟»</b> (زرار في شاشة الطلبات): كل طلب "
             "بيتحجز بيتسجّل جنبه الميعاد اللي البرنامج كان مقترحه، والاستقبال "
             "عمل بيه إيه — خده زي ما هو، ولا غيّر الساعة أو اليوم أو الدكتور. "
             "والشاشة بتوري النسبة لكل نوع زيارة. قياس بس، ما بيغيّرش الحجز.",
             "<b>\"How often is the suggestion kept?\"</b> (a button on the "
             "requests screen): every request booked keeps, beside it, the "
             "time the program suggested and what the desk did with it — "
             "kept it, or changed the time, the day or the doctor. The screen "
             "shows the share for each visit type. It only measures; booking "
             "is unchanged."),
            ("<b>مين يوافق على الطلب</b>: قاعدة العيادة «الاستقبال وبعده "
             "الدكتور» إلا لو اتغيّرت من الإعدادات. الاستقبال بيدوس «ابعته "
             "للدكتور»، والدكتور بيلاقيه فوق شاشته في «طلبات مستنية "
             "موافقتك» — يوافق (ومعاه ملاحظة لو حب) أو يعتذر بسبب — وبعدها "
             "بس الاستقبال يقدر يحجز، <b>ومع نفس الدكتور</b>.",
             "<b>Who approves a request</b>: the clinic's rule is \"reception, "
             "then the doctor\" unless changed in Settings. Reception presses "
             "\"Send to the doctor\", and the doctor finds it at the top of "
             "their screen under \"Requests waiting for your approval\" — "
             "approve (with a note if they like) or decline with a reason — "
             "and only then can reception book it, <b>with that same "
             "doctor</b>."),
            ("<b>كل طبيب ليه اختياره</b>: من «حسابي» الطبيب يسيب طلباته "
             "للاستقبال لوحده، أو يطلب إنه يوافق عليها حتى لو قاعدة العيادة "
             "الاستقبال بس. المدير يقدر يغيّرها من صفحة الطبيب؛ ومحدّش تاني. "
             "والموافقة ما بتتعملش غير من الطبيب اللي الطلب اتبعت له — مش "
             "طبيب تاني ولا الاستقبال ولا المدير.",
             "<b>Each doctor chooses</b>: under \"My profile\" a doctor can "
             "leave their requests to reception alone, or ask to approve them "
             "even where the clinic's rule is reception only. The admin can "
             "change it from the doctor's page; nobody else can. Only the "
             "doctor the request was sent to can approve it — not another "
             "doctor, not reception, not the admin."),
            ("<b>ميعاد واحد لطفل واحد</b>: لو مكتبين حجزوا نفس الدكتور في "
             "نفس الوقت في نفس اللحظة، واحد بس بياخده والتاني بيتقال له إن "
             "الميعاد اتاخد. ورجوع موعد ملغي أو «لم يحضر» لـ«محجوز» بيتأكد "
             "الأول إن وقته لسه فاضي — ولو اتاخد بيطلب منك تختار وقت جديد.",
             "<b>One slot, one child</b>: if two desks book the same doctor "
             "at the same time at the same moment, one gets it and the other "
             "is told the time is gone. Bringing a cancelled or missed "
             "booking back to \"scheduled\" first checks its time is still "
             "free — and if it was given away, asks you to choose a new "
             "one."),
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
            ("<b>كشوف جاهزة لكل شكوى:</b> اكتب الشكوى والفحص والخطة مرة لالتهاب "
             "الحلق مثلاً ودوس «احفظ الكشف كقالب»، واربط بيه روشتة جاهزة لو حبيت. "
             "المرة الجاية ضغطة على اسمه فوق خانة الشكوى بتكتب في الخانات "
             "الفاضية بس — واللي انت كاتبه بيفضل زي ما هو — وبيظهر زرار «اكتب "
             "الروشتة من» يفتح الروشتة جاهزة. تتعدّل أو تتشارك من «الكشوف الجاهزة».",
             "<b>A ready visit for each complaint:</b> write the complaint, "
             "examination and plan once — for a sore throat, say — press «Save "
             "the visit as a template», and link a ready prescription if you like. "
             "Next time one press on its name above the complaint box writes into "
             "the empty boxes only — what you wrote stays — and «Write the "
             "prescription from» opens the prescription ready. Edit or share them "
             "under «Ready visits»."),
            ("<b>تكرار روشتة المرض المزمن:</b> جنب كل مشكلة نشطة في قايمة مشاكل "
             "المريض زرار «كرر آخر روشتة» — في الكشف وفي شاشة الروشتة. بيفتح روشتة "
             "جديدة فيها نفس الأدوية: اللي جرعته بالوزن بتتحسب من جديد على وزن "
             "النهارده ومكتوب جنبه لو اتغيرت وكانت كام وعلى أنهي وزن، واللي جرعته مش "
             "بالوزن بيفضل زي آخر مرة. آخر وزن في الملف بيظهر بتاريخه، ولو قديم مش "
             "بيتحط غير لما تدوس «استخدم الوزن ده». وفحص الحساسية والتداخلات شغال عادي.",
             "<b>Repeating a long-term prescription:</b> beside each active "
             "problem on the patient's problem list is «Repeat last prescription» — "
             "on the visit and on the prescription screen. It opens a new "
             "prescription with the same medicines: one dosed by weight is worked "
             "out again on today's weight and says when it changed, what it was and "
             "on which weight; one not dosed by weight keeps last time's dose. The "
             "latest weight on file shows with its date, and an old one is used only "
             "when you press «Use this weight». Allergy and interaction checks run "
             "as usual."),
            ("<b>أدوات التقييم جوه الكشف:</b> تحت خانة الفحص «أدوات التقييم»: درجة "
             "الخانوق (Westley)، ودرجة الجفاف (Clinical Dehydration Scale)، ودرجة الحلق "
             "(Centor / McIsaac). علّم اللي شايفه والبرنامج بيجمع الدرجة وبيكتب الفئة "
             "لو المرجع نفسه بيحددها — والنتيجة درجة مش قرار. المرجع مكتوب تحت كل "
             "أداة، وآخر درجة من زيارة قبل كده جنبها، وزرار «اكتبها في الفحص». الدرجة "
             "الكاملة بتتحفظ مع الكشف وبتطلع في منحنيات المريض.",
             "<b>Assessment tools in the visit:</b> under the examination box, "
             "«Assessment tools»: the Westley croup score, the Clinical Dehydration "
             "Scale and the Centor / McIsaac sore-throat score. Mark what you see; "
             "the score is added up, with its band where the source itself defines "
             "one — a score, not a decision. The source is written under each tool, "
             "the last score from an earlier visit beside it, and «Write it in the "
             "examination» adds it to the text. A finished score is saved with the "
             "visit and shows in the patient's curves."),
            ("<b>أدوات بترخيص (c-ACT وACT للربو):</b> صياغة أسئلتها محمية بحقوق، "
             "فالبرنامج فيه شكلها بس (عدد الأسئلة ونقط كل إجابة). لو العيادة معاها "
             "ترخيص، المدير بيكتب النص الرسمي وصاحب الترخيص من «الإعدادات ← أدوات "
             "بترخيص»، والأداة بتظهر في «أدوات التقييم» زي التانيين. من غير كده "
             "بتفضل مخفية.",
             "<b>Licensed tools (c-ACT and ACT for asthma):</b> their wording is "
             "copyrighted, so the program carries only their shape (how many "
             "questions, each answer's points). If the clinic holds a licence, an "
             "administrator enters the official text and the licence holder under "
             "«Settings → Licensed tools», and the tool appears among the assessment "
             "tools like the others. Until then it stays hidden."),
            ("<b>تحويل لطبيب:</b> تحت «تحويل للطوارئ» في الكشف: «حوّل لطبيب» — "
             "لطبيب جوه العيادة من القايمة (بيلاقي الطفل عنده في «محوّلين ليك» وعلى "
             "زيارة الطفل لما يفتحها، ومعاه زرار حجز)، أو لطبيب بره باسمه وتخصصه "
             "ومكانه (بيتحفظ في دفتر العيادة ويتختار المرة الجاية). السبب مطلوب. "
             "«خطاب التحويل» بيتطبع بقالب الروشتة وفيه الشكوى والفحص والتشخيص "
             "والأدوية والحساسية، وللطبيب اللي بره ورقة رد تحت. وعلامة «في الروشتة» "
             "بتكتب «محوّل إلى د. …» على روشتة الكشف. الرد بيرجع للطبيب اللي حوّل "
             "يراجعه — من الكشف أو من شاشة الإحالات.",
             "<b>Referral to a doctor:</b> under «Emergency referral» on the visit: "
             "«Refer to a doctor» — to a doctor in the clinic, picked from the list "
             "(they find the child under «Referred to you» and on the child's visit "
             "when they open it, with a booking button), or to a doctor outside, by "
             "name, specialty and place (kept in the clinic's book for next time). "
             "The reason is required. «Referral letter» prints on the prescription "
             "layout with the complaint, examination, diagnosis, medicines and "
             "allergies, and a reply slip for an outside doctor. Ticking «on the "
             "prescription» prints «Referred to Dr. …» on the visit's prescription. "
             "The reply comes back to the referring doctor to review — on the visit "
             "or on the referrals screen."),
            ("<b>الإملاء بالصوت:</b> مقفول لحد ما الإدارة تفتحه من الإعدادات (جنب "
             "المساعد الذكي)، لأن المتصفح بيبعت الصوت لخدمة جوجل علشان يحوّله لكلام. "
             "لما يتفتح، تحت الشكوى والفحص وقصة الحالة زرار «إملاء»: اضغط واتكلم، "
             "واضغط تاني توقف، و«ع / EN» بيغيّر اللغة. الكلام بيتضاف آخر الخانة — "
             "راجعه قبل الحفظ. بيشتغل في كروم وإيدج.",
             "<b>Voice dictation:</b> off until the administration switches it on "
             "in Settings (beside the assistant), because the browser sends the "
             "voice to Google's speech service. Once on, the complaint, examination "
             "and case history have a «Dictate» button: press and speak, press "
             "again to stop; the language button beside it switches Arabic and English. The words are added at "
             "the end of the box — check them before saving. Works in Chrome and "
             "Edge."),
            ("<b>اختصارات الكيبورد:</b> في الكشف Ctrl+S بيحفظ (حتى وانت بتكتب)، "
             "وR روشتة، وC شهادة، وB حجز متابعة؛ وفي الروشتة Ctrl+S حفظ وطباعة وP "
             "طباعة. اضغط ? (أو زرار الكيبورد تحت) تشوف اختصارات الصفحة. الحروف "
             "بتشتغل والكيبورد عربي، ومش بتشتغل وانت في خانة كتابة، ولو فيه كلام "
             "ما اتحفظش بتسأل قبل ما تسيب الصفحة.",
             "<b>Keyboard shortcuts:</b> on the visit, Ctrl+S saves (even while "
             "typing), R opens a prescription, C a certificate, B a follow-up "
             "booking; on the prescription, Ctrl+S saves and prints and P prints. "
             "Press ? (or the keyboard button below) to see the page's shortcuts. "
             "Letters work with the keyboard on Arabic, not inside a box, and ask "
             "before leaving the page when something typed is not saved."),
            ("<b>رسايل للأهل بعد الكشف:</b> تحت «تعليمات المتابعة» في الكشف: «ابعت "
             "التعليمات للأهل» بيبعت كلام الطبيب نفسه دلوقتي — على القناة اللي الأهل "
             "بيكلمونا منها لو الرد لسه مسموح فيها، وإلا على واتساب. و«فكّرهم بميعاد "
             "المتابعة» بيتجدول قبلها بيوم، ولو حجزوا أو جم قبلها ما بيتبعتش. و«اسأل "
             "على الطفل بعد … يوم» بيبعت «عامل إيه؟»، والرد بيدخل صندوق خدمة العملاء. "
             "التذكير والسؤال محتاجين الإرسال التلقائي شغال من إعدادات واتساب، ونصوصهم "
             "بتتعدل من قوالب الرسايل.",
             "<b>Messages to the family after the visit:</b> under «Follow-up "
             "instructions» on the visit: «Send the instructions to the family» "
             "sends the doctor's own words now — on the channel the family writes "
             "from when a reply is still allowed there, otherwise WhatsApp. «Remind "
             "them of the follow-up» is queued a day before, and is not sent if they "
             "have booked or come. «Ask how the child is after … days» sends «how is "
             "he doing?», and the answer lands in the customer-service inbox. The "
             "reminder and the check-in need automatic sending switched on in the "
             "WhatsApp settings; their wording is edited in the message templates."),
            ("<b>الشهادات من الكشف:</b> زرار «شهادة من الكشف» تحت الكشف بيطلّع إجازة "
             "مرضية / عدم حضور، أو شهادة لياقة طبية، أو تقرير مختصر للزيارة — "
             "بالعربي أو الإنجليزي. الاسم والسن والتاريخ بييجوا من الكشف، والطبيب "
             "بيكتب عدد الأيام أو الغرض بس. التشخيص ما بيظهرش غير لو الأهل "
             "وافقوا. كل شهادة ليها رقم وبتتسجل في ملف المريض (تاب الروشتات) بمين "
             "طلّعها وإمتى، وتتطبع تاني بنفس الكلام، وتتلغي بسبب ومش بتتمسح. وبتتطبع "
             "على نفس قالب روشتة الطبيب (الترويسة والتوقيع والختم والمقاس) بخط Cairo، "
             "واللي جاي من الكشف بيتطبع بخط تقيل. ونص كل نوع بيتعدّل من «الإعدادات ← "
             "نصوص الشهادات»: الكلام بتكتبه زي ما تحب، والاسم والسن والتواريخ مربعات "
             "ثابتة بتتحط بزرار.",
             "<b>Certificates from the visit:</b> «Certificate from the visit» "
             "under the visit issues a sick leave / absence, a medical fitness "
             "certificate or a short visit report — in Arabic or English. The "
             "name, age and date come from the visit; the doctor writes only the "
             "days or the purpose. The diagnosis appears only if the family agreed. "
             "Each certificate has a number and is kept in the patient's file "
             "(prescriptions tab) with who issued it and when; it reprints with "
             "the same words and is cancelled with a reason, never deleted. It "
             "prints on the doctor's prescription layout (letterhead, signature, "
             "stamp, size) in Cairo, with what came from the visit in bold. The "
             "wording of each kind is edited under «Settings → Certificate "
             "wording»: type the words freely; the name, age and dates are fixed "
             "blocks added with a button."),
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
            ("<b>أسرع في الإدخال:</b> الاختيارات أزرار بضغطة واحدة (وضغطة "
             "تانية تلغي)، والأرقام ١، ٢، ٣ بتختار، وEnter بينقلك للخانة اللي "
             "بعدها. جنب كل خانة إجابة الزيارة اللي فاتت بتاريخها، و«زي آخر "
             "مرة» بتنقل الاختيار بس — الأرقام عمرها ما بتتنقل، واللي بيتقرر كل "
             "جلسة ما لوش زرار. واللي اتنقل بيبان «منقول — راجعه». وجنب الرقم "
             "خط صغير بآخر قراءاته، وأول ما تكتب رقم النهارده بيظهر الفرق عن آخر "
             "مرة («↓ −3 % عن آخر مرة») — بلون واحد، والحكم عليه ليك. والأعراض "
             "(زي «أعراض من آخر زيارة» في القلب) أزرار بأيقونات: ضغطة = نعم، "
             "التانية = لأ، و«مفيش جديد» بتعلّم الباقي لأ؛ اللي ما تلمسوش ما "
             "بيتسجلش. والقايمة بتنطوي في سطر بيقول اللي اتسجل، وبتفضل مقفولة "
             "لو قفلتها. وبعض "
             "الخانات بتظهر بس لما تلزم (سبب التخدير الكلي مع التخدير الكلي). "
             "و<b>قوالبك</b>: املا اللوح زي الكشف الروتيني ودوس «احفظ اللوح كقالب»، "
             "والمرة الجاية ضغطة على اسمه تملا الخانات الفاضية؛ وتتشارك مع "
             "أطباء التخصص أو تتعدل من «قوالب لوح التخصص».",
             "<b>Faster entry:</b> answers are one-tap buttons (a second tap "
             "clears), the number keys 1, 2, 3 pick, and Enter moves to the next "
             "box. Beside each box is the last visit's answer and its date; «Same "
             "as last time» copies a choice only — numbers are never copied, and "
             "what is decided each session has no button. What was copied shows "
             "«Copied — check it». Beside a number is a small line of its last "
             "readings, and as you type today's the difference from last time "
             "appears («↓ −3 % from last time») — in one colour; the judgement is "
             "yours. Symptoms (such as «Symptoms since the last visit» in "
             "cardiology) are picture buttons: one tap = yes, a second = no, and "
             "«Nothing new» marks the rest no; what you don't touch isn't "
             "recorded. The list folds to one line saying what was recorded, and "
             "stays folded if you fold it. Some boxes appear only when they apply (the "
             "reason for general anaesthesia, with general anaesthesia). And "
             "<b>your templates</b>: fill the panel as a routine visit goes and "
             "press «Save the panel as a template»; next time one press on its "
             "name fills the empty boxes; share or edit them under «Specialty "
             "panel templates»."),
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
            ("<b>خريطة الأسرّة الحية:</b> كل سرير مرسوم بشكله — سرير، سرير "
             "رعاية، حضّانة، كبسولة، ترولي — وجنب كل طفل التشخيص وعدّاد الإقامة "
             "(ساعات في القسم اللي بيتحاسب بالساعة، وأيام في الباقي). فوق كل "
             "قسم إشغاله دلوقتي وفي آخر ٣٠ يوم. دوس على سرير فيه طفل تشوف "
             "التشخيص والعلاج الشغّال والتحاليل والأشعة المستنية واللي خلص، "
             "ودوس على سرير فاضي تدخّل طفل برقم ملفه. والخريطة بتتحدّث "
             "لوحدها. والقسم اللي مابقاش مستخدم يتقفل بسبب «مابقاش مستخدم» "
             "ويختفي منها أول ما يفضى.",
             "<b>The live bed map:</b> each bed drawn as what it is — bed, "
             "ICU bed, incubator, capsule, trolley — with each child's "
             "diagnosis and how long they have stayed (hours in a unit billed "
             "by the hour, days elsewhere). Each unit shows how full it is now "
             "and over the last 30 days. Tap a taken bed for the diagnosis, "
             "current drugs, and the tests and imaging waiting or back; tap a "
             "free one to admit a child by file number. It updates itself. A "
             "unit no longer used is closed with the reason «No longer used» "
             "and leaves the map once it is empty."),
            ("<b>إقرار الدخول على الشاشة:</b> بعد ما تدخّل طفل من الخريطة، "
             "الشاشة بتعرض إقرار الدخول لولي الأمر يقراه ويأكّد إنه فهمه "
             "ويوقّع بصباعه. الكلام هو نص «الدخول والإقامة» في الموافقات، "
             "والمستشفى تعدّله من إعدادات نصوص الموافقات بقواعدها (الزيارة، "
             "المرافق…). والسرير اللي إقراره لسه ما اتوقّعش عليه علامة «مستني "
             "توقيع».",
             "<b>Admission consent on the screen:</b> after admitting from "
             "the map, the screen shows the guardian the admission consent to "
             "read, confirm and sign with a finger. The words are the "
             "«Admission and stay» consent text, which the hospital edits "
             "with its own rules (visiting, companions…) in the consent "
             "wording settings. A bed whose consent is not signed yet is "
             "marked «awaiting signature»."),
            ("<b>القسم لطاقمه:</b> من «تجهيز الأقسام» ← «طاقم القسم» تختار "
             "الأطباء والتمريض بتوع كل قسم. اللي مش من الطاقم بيشوف في الخريطة "
             "إن السرير مشغول بس، ولو محتاج يفتح الحالة (نبطشية، استدعاء) بيكتب "
             "السبب، وبتفتحله ١٢ ساعة وبيتسجّل باسمه، والمدير بيشوف السجل تحت "
             "في نفس الشاشة. القسم اللي مالوش طاقم بيفضل مفتوح للكل زي الأول.",
             "<b>A unit kept to its team:</b> under «Units and beds» → «Unit "
             "team», choose each unit's doctors and nurses. Anyone else sees on "
             "the map that a bed is taken, and to open the case (on call, a "
             "call to help) writes a reason — it opens for 12 hours under their "
             "name, and the manager reads the log on the same screen. A unit "
             "with no team stays open to everyone, as before."),
            ("<b>اسم اتكتب غلط بيتصلّح:</b> من «تجهيز الأقسام» زرار «تعديل» "
             "جنب كل قسم وحيّز وسرير — الاسم، ونوع الحيّز (غرفة/بارتشن) ونوع "
             "السرير (سرير/حضّانة/كبسولة). حتى لو نام فيه أطفال: الإقامة "
             "بتشاور على السرير نفسه مش على اسمه. والمسح بس للي عمره ما اتسكن.",
             "<b>A name typed wrong can be fixed:</b> in the ward setup, Edit "
             "beside every unit, space and bed changes the name, the space's "
             "kind (room, partition) and the bed's kind (bed, incubator, "
             "capsule), even where children have stayed: a stay points at the "
             "bed, not at its name. Deleting is only for what was never used."),
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
            ("<b>«ادفع الأول وبعدين يتنفذ»</b> (من الإعدادات ← السياسات، مقفول "
             "افتراضياً): للحالة اللي اتفرزت <b>غير عاجلة</b> بس — الطبيب بيكتب "
             "عادي، والإعطاء والعمل مستنيين الخزنة لحد «اتدفع — يكمل». الحالة "
             "العاجلة أو اللي لسه ما اتفرزتش <b>عمرها ما بتستنى</b>، وإعادة الفرز "
             "عاجل بتشيل الانتظار فوراً (قرار 1063 لسنة 2014). «الحالات الحرجة — "
             "أول 48 ساعة» من سجل الطوارئ: الحالات العاجلة واللي اتحاسب عليه في "
             "أول 48 ساعة للمطالبة بيه.",
             "<b>«Pay first, then it is done»</b> (Settings → Policies, off by "
             "default): only for a child triaged <b>non-urgent</b> — the doctor "
             "writes as always, and giving and doing wait for the desk's «Paid — "
             "go ahead». An urgent or not-yet-triaged child <b>never waits</b>, "
             "and re-triaging urgent lifts the wait at once (decree 1063 of "
             "2014). «Urgent cases — first 48 hours» from the register: the "
             "urgent attendances and what their first 48 hours were billed, to "
             "be claimed."),
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
            ("<b>قايمة كل قسم</b>: فوق قايمة المعمل تبويب لكل قسم فيه شغل "
             "مستني (أمراض الدم، الكيمياء، الهرمونات…) بعدده، وعلامة البرق لو فيه "
             "مستعجل. اختار قسمك والقايمة تبقى بتاعته بس — المستعجل الأول وبعده "
             "الأقدم — وبتفتح عليه المرة الجاية لحد ما تختار «كل الأقسام». "
             "والتحليل اللي لسه ما اتحطش في قسم بيظهر تحت «من غير قسم».",
             "<b>Each section's list</b>: above the lab's list, a tab for each "
             "section with work waiting (haematology, chemistry, hormones…) with "
             "its count, and the lightning mark when something is urgent. Pick "
             "your section and the list is its own — urgent first, then the "
             "oldest — and opens on it next time until you choose «All "
             "sections». A test not yet in a section shows under «No section»."),
            ("<b>مكونات التحليل وأقسامه ومراجعه</b> (المعمل ← التحاليل): "
             "التحليل المعروف (بول، براز، صورة دم، صفراء، وظائف كبد وكلى، "
             "فيتامينات…) بيتعرض عليه مكوناته بأساميها ووحداتها من غير ولا "
             "رقم — علّم على اللي بيطلع في تقريركم واحفظ. وكل تحليل بيتحط في "
             "قسم من قايمة ثابتة زي عيلة الدوا («رتّب في أقسام»)، و«الفئة» "
             "بتاعة الدكتور زي ما هي. والمراجع بتيجي من نشرة الكيت بتاعة "
             "جهازكم: الشيت، أو باليد، أو «اقرا المراجع من نشرة الكيت» — "
             "وكلها مسودة لحد ما مدير المعمل يوافق.",
             "<b>A test's components, sections and ranges</b> (Lab → Tests): a "
             "known test (urine, stool, CBC, bilirubin, liver and kidney "
             "function, vitamins…) is offered its components by name and unit, "
             "with no figure — tick what your report prints and save. Each test "
             "goes into one section from a fixed list, like a medicine's family "
             "(«Sort into sections»); the doctor's category stays as it is. "
             "Ranges come from your analyser's kit insert: the sheet, by hand, "
             "or «Read ranges from the kit insert» — all drafts until the "
             "laboratory director approves."),
            ("<b>القيم الحرجة</b>: حدودها لكل تحليل من شاشة نطاقاته، والنتيجة "
             "اللي تعدّيها بتتعلّم لوحدها. النتيجة اللي ملهاش رقم (مزرعة إيجابية) "
             "الفني يعلّمها حرجة بسبب مكتوب. وعلى الطلب «سجّل الإبلاغ»: اتبلّغ مين، "
             "إزاي، وإمتى، وهل الطبيب كرّر القيمة. قايمة القيم الحرجة بتقول مين "
             "اتبلّغ ومين لسه.",
             "<b>Critical values</b>: each test's limits on its ranges screen, "
             "and a result past them is flagged by itself. A result with no "
             "number (a positive culture) the technician marks critical, with "
             "the reason. On the order, «record the call»: who was told, how, "
             "when, and whether the doctor read the value back. The critical "
             "list says who was told and who not yet."),
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
        # GAHAR CSS.06 / .07 / .10 — opt-in, for the hospitals that run them.
        "key": "programs",
        "module": "programs",
        "icon": "clipboard2-heart",
        "title": ("برامج الرعاية الخاصة", "Care programmes"),
        "lines": [
            ("<b>الغسيل الكلوي والعلاج الكيماوي والتأهيل</b>: الطفل بيتسجّل في البرنامج "
             "بخطته (النوع والوصلة، البروتوكول والدورات، الأهداف)، وكل جلسة فيها التقييم "
             "قبلها واتسمح بيها ولا لأ، والمتابعة أثناءها، والمضاعفات واللي اتعمل. "
             "تثقيف الأهل بيتسجّل، والتأهيل ما بيتقفلش من غير خطة خروج.",
             "<b>Dialysis, chemotherapy and rehabilitation</b>: a child is enrolled with "
             "the plan (modality and access, protocol and cycles, goals), and each session "
             "carries the check before it and whether it was cleared, the monitoring during "
             "it, complications and the action. The family's education is recorded, and "
             "rehabilitation does not end without a discharge plan."),
            ("<b>تحاليل الفيروسات للغسيل</b> بالفترة اللي المستشفى بتحددها، والتحوّل من "
             "سلبي لإيجابي بيبان على اللوحة. البرنامج مافيهوش بروتوكول ولا فترة من عنده.",
             "<b>Dialysis viral markers</b> by the hospital's interval, and a "
             "negative-to-positive change shows on the board. The program holds no "
             "protocol and no interval of its own."),
        ],
    },
    {
        # GAHAR ICD.02 — opt-in, for a hospital with its own ambulance.
        "key": "ambulance",
        "module": "ambulance",
        "icon": "truck-front",
        "title": ("الإسعاف", "Ambulance"),
        "lines": [
            ("<b>كل مكالمة سجل</b>: اتستلمت إمتى ومن فين، والعربية والطاقم، والأربع "
             "لحظات بضغطة لكل واحدة (اتحركت، وصلت للطفل، سابت المكان، وصلت المستشفى)، "
             "واللي الطاقم لقاه وعمله في الطريق، وسلّموه لمين. الطفل اللي وصل ما بيتقفلش "
             "من غير التقييم والرعاية والتسليم.",
             "<b>Every call is a record</b>: when it came in and from where, the vehicle "
             "and crew, the four moments one press each (sent, reached the child, left "
             "the scene, arrived here), what the crew found and did on the way, and who "
             "received the child. A run that brought a child does not close without the "
             "assessment, the care and the handover."),
            ("<b>زمن الاستجابة</b> بيتقاس من المكالمة، والأهداف أرقام المستشفى — من غيرها "
             "البرنامج بيقيس وما بيحكمش. وفحص جاهزية كل عربية والناقص بإجرائه، والتدريبات.",
             "<b>Response times</b> are measured from the call, against the hospital's "
             "own targets — without them the program measures and does not judge. And "
             "each vehicle's readiness checks, what was missing and what was done, and "
             "the drills."),
        ],
    },
    {
        # GAHAR ACT.16 — opt-in, for a hospital that sees children remotely.
        "key": "telemedicine",
        "module": "telemedicine",
        "icon": "camera-video",
        "title": ("الكشف عن بُعد", "Telemedicine"),
        "lines": [
            ("<b>الطلب بالفرز</b>: الطفل ينفع يتشاف عن بُعد ولا لأ بمعايير المستشفى، "
             "واللي ما ينفعش بيتقال لأهله يعملوا إيه. و<b>ما بيبدأش</b> غير لما يتكتب "
             "اتأكدنا من هوية الطفل إزاي، والطفل فين والطبيب فين، والمنصة.",
             "<b>Requested through triage</b>: whether the child may be seen remotely, by "
             "the hospital's criteria, and what the family was told if not. It <b>does not "
             "start</b> until the identity check and where the child and the doctor are "
             "have been written, and the platform."),
            ("<b>البداية بتفتح زيارة عادية</b> على قناتها، فالكشف والتشخيص والروشتة "
             "بيتكتبوا على شاشة الزيارة المعتادة، والزيارة في ملف الطفل زي أي زيارة. "
             "والتقييم الدوري بالأرقام: اتطلب كام، كام ما ينفعش، كام احتاج ييجي، والمدة.",
             "<b>Starting opens an ordinary visit</b> on its own channel, so the "
             "examination, diagnosis and prescription are written on the usual visit "
             "screen and the visit sits in the child's file like any other. And the "
             "periodic evaluation in figures: how many asked, how many were not "
             "eligible, how many needed to come in, and how long."),
        ],
    },
    {
        # GAHAR ATH — opt-in, for a teaching hospital.
        "key": "teaching",
        "module": "teaching",
        "icon": "mortarboard",
        "title": ("التعليم والأبحاث", "Teaching and research"),
        "lines": [
            ("<b>كل متدرّب بمشرفه</b>: الطالب أو طبيب الامتياز أو النائب ما بيتسجّلش من "
             "غير المشرف اللي مسؤول عنه وحدود شغله. والتوجيه بند بند، وكل دورة بتقييمها، "
             "والتقييم بأداة واسم المقيّم — ومحدّش بيقيّم نفسه.",
             "<b>Every trainee with their supervisor</b>: a student, house officer or "
             "resident is not entered without the supervisor who answers for them and "
             "the scope they work within. The orientation item by item, each rotation "
             "with its evaluation, and each assessment with its tool and its assessor — "
             "nobody assesses themselves."),
            ("<b>ما فيش طفل في بحث</b> من غير بروتوكول وافقت عليه لجنة أخلاقيات البحث "
             "ولسه سارية، ومن غير موافقة البحث موقّعة من ولي الأمر في ملف الطفل. والأهل "
             "بيسحبوا من غير ما يقولوا ليه، وأي مشكلة سلامة بتتكتب بإمتى اتبلّغوا واللي "
             "اتعمل. والقلق اللي المتدرّبين بيرفعوه مفتوح لحد ما يتكتب اللي اتعمل.",
             "<b>No child is in a study</b> without a protocol the research ethics "
             "committee approved and that is still current, and without the guardian's "
             "signed research consent on the child's file. A family withdraws without "
             "giving a reason, and any safety issue is written with when they were told "
             "and what was done. A concern a learner raises stays open until what was "
             "done is written."),
        ],
    },
    {
        # «المعمل مديول لواحده والاشعة مديول». Opt-in like the lab, and
        # switched on once on upgrade wherever the lab was on.
        "key": "imaging",
        "module": "imaging",
        "icon": "radioactive",
        "title": ("الأشعة", "Radiology"),
        "lines": [
            ("<b>صفحة الأشعة الخاصة بيها</b>: الأشعة بتتفتح على صفحة الأشعة (مش "
             "صفحة المعمل)، وعليها التقرير — الوصف والانطباع — و<b>الجرعة والصبغة</b>: "
             "الجرعة زي ما الجهاز طلّعها (DLP / CTDIvol / DAP / mSv / وقت الفلورو)، "
             "والصبغة: اسمها وطريقتها وكميتها ورد فعل الطفل. قبل أي أشعة جديدة "
             "الصفحة بتوري اللي الطفل اتعرّض له قبل كده، ورد الفعل السابق للصبغة "
             "بالأحمر، وملف الطفل بيجمّع الجرعات (كل مقياس لوحده — ما بيتجمعوش "
             "على بعض). الحد المرجعي لكل أشعة المستشفى بتحطّه في قايمة التحاليل "
             "والأشعات، واللي فوقه بيظهر الأول في «مراجعة الجرعات والصبغة».",
             "<b>Radiology's own page</b>: a scan opens on radiology's page (not "
             "the lab's), with the report — findings and impression — and the "
             "<b>dose and contrast</b>: the dose as the machine reported it "
             "(DLP / CTDIvol / DAP / mSv / fluoroscopy time), and the contrast's "
             "name, route, amount and the child's reaction. Before any new scan "
             "the page shows what the child had before, and an earlier contrast "
             "reaction in red; the child's file adds the doses up (each measure "
             "on its own — never summed together). The hospital sets each scan's "
             "reference level in the tests list, and scans above it come first "
             "in «Dose and contrast review»."),
            ("<b>الأشعة مديول لوحدها، مش جزء من المعمل.</b> الأشعة العادية "
             "والبانوراما والمقطعية والرنين بتتعمل وبيتكتب تقريرها في غرفة "
             "الأشعة، ومش كل مكان فيه معمل فيه أشعة. أي عيادة كان المعمل "
             "شغّال عندها، الأشعة اشتغلت عندها لوحدها مع التحديث.",
             "<b>Radiology is its own module, not part of the lab.</b> Films, "
             "panoramic, CT and MRI are taken and reported in the X-ray room, "
             "and not every place with a lab has one. Wherever the lab was on, "
             "radiology was switched on with the update."),
            ("<b>القايمة شغلانتين: لسه ماتعملتش، واتعملت ومستنية تقرير.</b> "
             "«اتعملت» بتسجّل وقت الأشعة نفسها — مفيش رقم عينة على أشعة. "
             "والتقرير بيتكتب على شاشة الطلب، ويرجع للطبيب في صندوق النتايج.",
             "<b>The list is two jobs: not done yet, and done and awaiting a "
             "report.</b> «Done» records when the film was taken — a film has "
             "no sample number. The report is written on the order screen and "
             "reaches the doctor in the results inbox."),
            ("<b>الإيكو والسونار ورسم القلب ورسم المخ وقياس التنفس مش هنا.</b> "
             "دول دراسات أجهزة بتتعمل في أي عيادة وجنب أي سرير، وليهم شاشة "
             "«الفحوصات التشخيصية» جنب الكشف، بالحجز وقالب كل جهاز.",
             "<b>Echo, ultrasound, ECG, EEG and spirometry are not here.</b> "
             "They are device studies, done in any clinic and at any bedside, "
             "with their own «Diagnostic studies» board beside the visit — "
             "bookings and each device's template."),
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
            ("<b>والنص التاني من الصيدلة الإكلينيكية شغل بنش مش قراية: "
             "تحضير أدوية العنابر.</b> قبل راوند الصبح حد بيحضّر جرعات كل "
             "طفل لليوم، مكتوب عليها اسمه. ده في أغلب المستشفيات الجزء "
             "الأكبر من الشغلانة، والبرنامج مكانش عنده ليه حاجة خالص: "
             "الجرعة مكانتش موجودة كصف إلا لحظة ما الممرضة تسجّل إنها "
             "اتعطت، فسؤال «دوا الطفل ده جاهز؟» مكانش ليه إجابة في أي مكان.",
             "<b>And the other half of clinical pharmacy is bench work rather "
             "than reading: making the wards\u2019 doses up.</b> Before the "
             "morning round somebody makes up each child\u2019s doses for the "
             "day, labelled with their name. In most hospitals that is the "
             "larger half of the job, and the program had nothing for it at "
             "all: a dose existed only at the moment a nurse recorded giving "
             "it, so \u201cis this child\u2019s drug ready?\u201d had no "
             "answer anywhere."),
            ("<b>والعدد حساب على أمر الطبيب نفسه.</b> كل ٦ ساعات ليوم = "
             "أربعة، وخلاص — مش حكم على اللي الطفل محتاجه. والأمر «عند "
             "اللزوم» مالوش عدد أصلاً، لأن مفيش ساعة هو مستحق فيها، "
             "والبرنامج ما بيدّعيش إنه عارف تبعتوا كام.",
             "<b>And the count is arithmetic on the doctor\u2019s own "
             "order.</b> Six-hourly for a day is four, and that is all it "
             "ever is \u2014 never a judgement about what a child needs. A "
             "\u201cwhen needed\u201d order has no count at all, because "
             "there is no hour it is owed at, and the program does not pretend "
             "to know how many to send up."),
            ("<b>و«هو جه؟» بيتسأل عند الترولي، فبيتجاوب عند الترولي.</b> "
             "لوحة دورة الدوا بتقول «متحضّر» جنب الأمر — مش على شاشة "
             "الصيدلية اللي كانت هتخلّي حد يمشي في الطرقة عشان يعرف. "
             "والعنبر اللي بياخد دواه من رفه ما بيشوفش الكلام ده أصلاً.",
             "<b>And \u201cis it here?\u201d is asked at the trolley, so it "
             "is answered at the trolley.</b> The drug round board says "
             "\u201cmade up\u201d beside the order \u2014 not on the "
             "pharmacy\u2019s own screen, which would send somebody down a "
             "corridor to find out. A ward that takes its drugs off its own "
             "shelf never sees any of it."),
            ("<b>وأدوية عالية الخطورة — والقايمة بتاعة المستشفى نفسها.</b> "
             "معايير إدارة الدواء بتقول كده بالنص: المستشفى بتبني قايمتها من "
             "استخدامها هي ومن أخطاءها هي اللي حصلت أو كادت. فالبرنامج ما "
             "بيجيش بقايمة جاهزة — قسم أورام أطفال وعيادة في قرية مش خايفين "
             "من نفس الأدوية، والغلط في القايمة دي غلط في الأدوية اللي "
             "بتقتل لما تغلط.",
             "<b>And high-alert medicines \u2014 the list is the "
             "hospital\u2019s own.</b> The medication-management standards "
             "say so in as many words: the hospital builds its list from its "
             "own utilisation and its own errors and near misses. So nothing "
             "ships with the software \u2014 a paediatric oncology unit and a "
             "village clinic do not fear the same molecules, and being wrong "
             "about this list is being wrong about the medicines that kill "
             "people when they go wrong."),
            ("<b>والسبب مطلوب مع الاسم.</b> «أنسولين» في قايمة ومفيش حاجة "
             "جنبه ما بيقولش لممرضة الليل حاجة؛ «أخطاء بعشر أضعاف — لازم حد "
             "تاني يراجع الوحدات» بيقولها كل حاجة. والعلامة بتظهر عند "
             "الترولي مش على شاشة الصيدلية بس: علامة عايشة عند الصيدلية "
             "بتحذّر اللي مش ماسك السرنجة.",
             "<b>And the reason is required with the name.</b> "
             "\u201cInsulin\u201d on a list with nothing beside it tells a "
             "night nurse nothing; \u201cten-fold errors \u2014 a second "
             "person checks the units\u201d tells them everything. And the "
             "flag appears at the trolley, not only on the pharmacy\u2019s "
             "screen: a warning that lives with the pharmacy warns the person "
             "who is not holding the syringe."),
            ("<b>وأدوية بتتلخبط في بعضها.</b> أزواج الأسماء المتشابهة، "
             "والقايمة بتاعة المستشفى برضه: اللي بيتلخبط بيعتمد على اللي على "
             "الرفوف وعلى خط اللي بيكتب وعلى اللغة. والزوج متخزّن مرة واحدة "
             "وبيتقري في الاتجاهين، فمستحيل ينحذف نصه ويحذّر في اتجاه واحد — "
             "ودي طريقة كل قايمة أزواج بتتكتب بالإيد بتقع بيها.",
             "<b>And look-alike, sound-alike pairs.</b> The hospital\u2019s own "
             "list again: which names get mixed up depends on the shelves, the "
             "handwriting and the language. A pair is stored once and read "
             "both ways, so it cannot end up half-deleted and warning in one "
             "direction only \u2014 the failure mode of every hand-maintained "
             "pair list."),
            ("<b>وتبليغ أخطاء الدواء — ومفيش خانة لمين غلط.</b> نظام تبليغ "
             "فيه خانة زي دي ما بيجمّعش حاجة بعد أول شهر، وده أقدم درس في "
             "سلامة المرضى. اللي بيتسجّل: المرحلة، والدوا، واللي حصل، وهل "
             "وصل للطفل ولا اتمسك. والنتيجة بتصنيف NCC MERP من A لـI، لأن "
             "مستشفى بتقارن ربع بربع محتاجة نفس الخانات اللي الناس كلها "
             "بتستعملها.",
             "<b>And medication-error reporting \u2014 with no field for who "
             "made the mistake.</b> A reporting system with one collects "
             "nothing after the first month, the oldest finding in patient "
             "safety. What is recorded is the stage, the drug, what happened "
             "and whether it reached the child. The outcome uses the NCC MERP "
             "index A\u2013I, because a hospital comparing its own quarters "
             "needs the same buckets as everybody else."),
            ("<b>واللي اتمسك قبل ما يوصل هو النص المفيد.</b> غلط اتمسك عند "
             "الكاونتر ماأذاش حد وهو أرخص درس ممكن؛ ونظام بيسجّل بس اللي وصل "
             "للأطفال بيجمّع الدروس الغالية بس. عشان كده البلاغ مش محتاج طفل "
             "أصلاً. <b>والملخّص هو اللي قايمة الخطورة بتتراجع عليه</b> — "
             "وده بالظبط اللي المعيار طالبه: القايمة تتبني من أخطاء المستشفى "
             "نفسها، يعني لازم يكون فيه حاجة بتعدّها.",
             "<b>And the near miss is the valuable half.</b> An error caught "
             "at the counter harmed nobody and is the cheapest possible "
             "lesson; a system that records only what reached a child collects "
             "the expensive lessons only. So a report needs no patient. "
             "<b>And the summary is what the high-alert list is revised "
             "against</b> \u2014 which is exactly what the standard asks: the "
             "list is built from the hospital\u2019s own errors, so something "
             "has to be counting them."),
            ("<b>ومطابقة أدوية الخروج.</b> داخل على إيه، وعليه إيه دلوقتي، "
             "وخارج على إيه — تلات قوايم جنب بعض. والمقارنة على المادة "
             "الفعالة مش على الاسم، لأن العنبر بيكتب «أوجمنتين» والقايمة "
             "بتقول «أموكسيسيلين/كلافولانيك»، ومقارنة بالنص كانت هتعتبرهم "
             "دوا جديد ودوا اتوقف. <b>والشاشة ما بتقررش حاجة</b>: تكمّل ولا "
             "توقّف قرار، وبرنامج بيحلّها لوحده بيكون بيكتب روشتة خروج محدش "
             "أمضاها.",
             "<b>And discharge reconciliation.</b> What they came in on, what "
             "they are on now, what they go home with \u2014 three lists side "
             "by side. Matched on the active ingredient rather than the name, "
             "because a ward writes \u201cAugmentin\u201d against a home list "
             "that says \u201camoxicillin/clavulanate\u201d and a text "
             "comparison would call that a new drug and a stopped one. <b>The "
             "screen decides nothing</b>: continuing and stopping are both "
             "decisions, and a program that resolved them quietly would be "
             "writing a discharge prescription nobody signed."),
            ("<b>ومراجعة الصيدلي للأمر قبل الصرف — بتتسجّل وما بتتفرضش.</b> "
             "المعايير بتطلب إن صيدلي يبص على الأمر قبل ما يتصرف، والبرنامج "
             "بقى يسجّل مين راجع وإمتى ويقول مين مااتراجعش. بس ما بيمنعش: "
             "مستشفى الساعة تلاتة بالليل ومفيش صيدلي موجود بتدي المضاد "
             "الحيوي، وبرنامج بيرفض ده هيتلف من حواليه آخر أول ليلة — وده "
             "إزاي أي إجراء بيبطل يعني حاجة. الفجوة بتتعرض وتفضل معروضة، "
             "نفس اختيار توقيع الخروج من غرفة العمليات.",
             "<b>And the pharmacist\u2019s check before dispensing is "
             "recorded, never enforced.</b> The standards ask that a "
             "pharmacist review an order before it is dispensed, and the "
             "program now records who checked and when, and says which orders "
             "nobody has. It does not block: a hospital at three in the "
             "morning with no pharmacist on site still gives the antibiotic, "
             "and a program that refused would be worked around by the end of "
             "the first night \u2014 which is how a control stops meaning "
             "anything. The gap is made visible and kept visible, the same "
             "choice the surgical sign-out makes."),
            ("<b>واللي البرنامج مش هيعمله، ومهم يتقال:</b> ما بيختارش مذيب "
             "ولا حجم ولا مدة تسريب ولا مدة صلاحية بعد الخلط، وما بيركّبش "
             "تغذية وريدية، وما بيعدّلش جرعة على وظائف كلى. كل واحدة من دي يا "
             "رقم إكلينيكي يا كتاب قواعد — ونفس القاعدة اللي منعت البرنامج "
             "يخترع حد تنبيه بتمنعه يخترع دول. العيادة اللي عندها وصفتها "
             "بتكتبها على الأمر، حيث بني آدم كتبها.",
             "<b>And what the program will not do, which is worth saying "
             "plainly:</b> it does not choose a diluent, a volume, an infusion "
             "time or a stability window, it does not formulate parenteral "
             "nutrition, and it does not adjust a dose for a kidney. Every one "
             "of those is a clinical number or a rulebook, and the same rule "
             "that stopped it inventing an alert threshold stops it inventing "
             "these. A clinic with its own recipe writes it on the order, "
             "where a person wrote it."),
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
        # The rota, and deliberately not a corner of `beds`: the night shift
        # is a clinic thing before it is a hospital thing.
        "key": "duty",
        "module": "duty",
        "icon": "calendar-week",
        "title": ("المناوبات ومستحقاتها", "The duty rota and what it owes"),
        "lines": [
            ("<b>ده اتجاه تاني للفلوس، مش شاشة جديدة على القديم.</b> كل رقم "
             "في البرنامج قبل كده كان نصيب من حاجة الأهل دفعوها — سطر في "
             "فاتورة، أو فِي على جرعة. الطبيب المقيم اللي قاعد في القسم من "
             "عشرة بالليل لتمانية الصبح <b>مش بيفوتر على حد</b>، فمفيش فاتورة "
             "نصيبه يتحسب منها. المناوبة مستحق على العيادة نفسها.",
             "<b>This is a second direction for money, not another screen "
             "over the first.</b> Every figure in this program used to be a "
             "share of something a family paid — a line on a bill, a fee "
             "on a dose. A resident sitting in the department from ten at "
             "night until eight in the morning <b>bills nobody</b>, so there "
             "is no invoice to take a share of. Cover is owed by the clinic."),
            ("<b>ومش للمستشفيات بس.</b> العيادة اللي عندها مقيم بيغطّي الليل "
             "بتستعمل نفس الشاشة، والقسم <b>اختياري</b> — عشان كده المناوبات "
             "مديول لوحده مش جزء من الأسرّة. لو كانت جوّه الأسرّة، أكتر "
             "العيادات اللي محتاجاها ماكانتش هتشوفها.",
             "<b>And it is not only for hospitals.</b> A clinic with a "
             "resident covering the night uses the same screen, and the "
             "department is <b>optional</b> — which is why the rota is "
             "its own module rather than part of the beds. Behind the beds, "
             "most of the clinics that need it would never have seen it."),
            ("<b>«مجدولة» مش «اتعملت».</b> الاسم في خانة على جدول الحيطة "
             "خطة، والدفع على خطة دفع على لا حاجة. فالمناوبة بتتكتب وهي "
             "بصفر، ومحدش بياخد عليها حاجة غير لما حد يقول إنها حصلت. "
             "والبرنامج <b>ما بيأكّدش لوحده</b>: مفيش حاجة فيه بتشوف الطرقة "
             "الساعة تلاتة بالليل.",
             "<b>Rostered is not worked.</b> A name in a square on a wall "
             "chart is a plan, and paying for a plan is paying for nothing. "
             "So a duty is written worth zero and pays only once somebody "
             "says it happened. The program <b>never confirms by itself</b>: "
             "nothing in it can see the corridor at three in the morning."),
            ("<b>واللي عدّى يومه ومحدش قال حصل فيه إيه بيفضل باين.</b> مش "
             "بيتقفل ولا بيتحسب — بيتعرض في أول الشاشة. لأن الصفوف دي لو "
             "اتسابت بتتقفل بالتخمين آخر الشهر، وساعتها ليلة اتغطّت بتضيع "
             "وليلة ماحصلتش بتتدفع.",
             "<b>And a duty whose day has passed with nobody speaking for it "
             "stays visible.</b> Not closed and not counted — listed at "
             "the top of the screen. Left alone, those rows get closed by "
             "guesswork at month end, and that is when a night that was "
             "covered is missed and one that was not is paid."),
            ("<b>الشيفتات وأسعارها بتتكتب من الشاشة.</b> الساعات بتختلف من "
             "قسم لقسم ومن بلد لبلد، ورمضان بيحرّكها، والعيادة اللي بتشغّل "
             "شيفتين مش تلاتة مالهاش لازمة مسا فاضي. وفيه سعر خاص للطبيب "
             "لو الاتفاق معاه غير سعر الشيفت — نفس فكرة نسبة الطبيب على "
             "الخدمة. <b>والسعر بيتصوّر على المناوبة ساعة ما تتكتب</b>، "
             "فتعديل السعر في مارس ما بيعيدش كتابة فبراير.",
             "<b>The shifts and their rates are typed on the screen.</b> The "
             "hours differ between departments and countries, Ramadan moves "
             "them, and a clinic that runs two shifts has no use for an empty "
             "evening. A doctor may have their own figure where the agreement "
             "differs — the same shape as a service commission. <b>And "
             "the rate is snapshotted onto the duty when it is written</b>, "
             "so a rate edited in March does not rewrite February."),
            ("<b>والاستشاري حكاية تانية.</b> اللي بيتحاسب بالحالة أو بالزيارة "
             "بيمشي على الفاتورة زي أي خدمة، ونصيبه بيتقرا من <b>سطره هو</b> "
             "مش من الفاتورة كلها. اللي بيتحاسب مبلغ ثابت على المرور كله "
             "بيتكتب هنا كمناوبة. <b>واحدة بس مش الاتنين لنفس اليوم</b> — "
             "غير كده بيتحسب مرتين.",
             "<b>A consultant is a different case.</b> One paid per case or "
             "per visit goes on the bill like any other service, and their "
             "share is read from <b>their own line</b> rather than from the "
             "whole invoice. One paid a flat figure for the round is written "
             "here as a duty. <b>One of the two for a given day, never "
             "both</b> — otherwise it is counted twice."),
            ("<b>ليستة لكل دور</b>: الجراحة · التخدير · التمريض. ليستة واحدة "
             "فيها تلات أنواع ناس محدش يقدر يقراها بسرعة، والسرعة هي السبب "
             "الوحيد لوجودها. والقايمة مفتوحة — مستشفى عايزة ليستة «أشعة» "
             "تحت الطلب تكتبها وتشتغل.",
             "<b>A list per rota</b>: surgery · anaesthesia · nursing. One "
             "list with three kinds of person on it is a list nobody can read "
             "at speed, and speed is the only reason it exists. The list is "
             "open — a hospital that wants a radiology rota types one and it "
             "works."),
            ("<b>«موجود» و«تحت الطلب» حاجتين مختلفتين</b>: واحد تجيبه، وواحد "
             "تكلّمه وتستنّاه. والأجر مختلف — والمهم إن <b>تحت الطلب ما "
             "بياخدش أجر الحضور لو محدش حدّده</b>: العيادة اللي ما اتفقتش على "
             "أجر الليلة اللي في البيت بتشوف خانة فاضية وتتسأل، مش رقم "
             "البرنامج قرّره لوحده.",
             "<b>Present and on call are two different things</b>: one you "
             "fetch, one you ring and then wait for. They pay differently — "
             "and crucially <b>on call never inherits the presence rate</b>: "
             "a clinic that has not agreed what a night at home is worth sees "
             "an empty figure and is asked, rather than having one decided "
             "for it."),
            ("<b>شاشة «مين موجود دلوقتي»</b> (من شاشة العمليات أو "
             "<code>/duty/now</code>): بتقرا الوقت بساعة العيادة وبتطلّع "
             "اللي شغّالين <b>دلوقتي</b> — ودي بتحسب الوردية اللي بتعدّي "
             "نص الليل صح: الساعة اتنين بالليل اللي مغطّي هو نوبتجية "
             "<b>إمبارح</b>. والليستة اللي مفيش عليها حد <b>بتتقال بالاسم</b> "
             "مش بتتساب فاضية.",
             "<b>The \"who is on now\" screen</b> (from the theatre screen or "
             "<code>/duty/now</code>) reads the clinic's clock and shows who "
             "is covering <b>right now</b> — getting the overnight shift "
             "right: at two in the morning the person covering is on "
             "<b>yesterday's</b> rota. And a rota with nobody on it is "
             "<b>named</b> rather than left as an empty column."),
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
            ("<b>الدفع = وصل</b>: التحصيل في الاستقبال لميعاد النهارده اللي لسه "
             "«محجوز» بيعلّمه «وصل» ويدخّل الطفل طابور الانتظار — خطوة واحدة "
             "بدل اتنين. ميعاد يوم تاني، أو طفل جوّه أصلاً، ما بيتلمسش، والدفع "
             "أونلاين من البيت ما بيعلّمش وصول. والعيادة تقدر تقفلها من "
             "الإعدادات.",
             "<b>Paid means here</b>: collecting at the desk for today's "
             "booking that is still \"scheduled\" marks it arrived and puts "
             "the child in the waiting queue — one step instead of two. A "
             "booking for another day, or a child already inside, is left "
             "alone, and paying online from home does not mark an arrival. "
             "The clinic can turn it off in Settings."),
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
            ("<b>الدفع أونلاين</b> (لو العيادة مفعّلة بوابة دفع): على الفاتورة "
             "«اعمل لينك دفع بالمتبقي» و«ابعته للأهل واتساب». الفاتورة "
             "<b>ما بتتعلّمش مدفوعة غير لما البوابة نفسها تأكّد</b> — مش "
             "صورة تحويل ولا الصفحة اللي الأهل بيرجعوا عليها — والفلوس "
             "بتنزل في خزنة «تحت التحصيل» بتاعة البوابة لحد ما تتسوّى في "
             "البنك. مبلغ مختلف عن المطلوب ما بيتكتبش على الفاتورة: بيتعلّم "
             "وبيتعرض على حد يراجعه. ومن غير بوابة مفعّلة، التحصيل في "
             "الاستقبال زي ما هو.",
             "<b>Online payment</b> (when the clinic has a gateway switched "
             "on): on the invoice, \"Make a payment link for the balance\" "
             "and \"Send it to the family on WhatsApp\". The bill is "
             "<b>marked paid only when the gateway itself confirms</b> — not "
             "a transfer screenshot, not the page the family lands on — and "
             "the money goes to the gateway's \"under collection\" till "
             "until it settles into the bank. An amount different from the "
             "one asked is not written on the bill: it is flagged for a "
             "person to review. With no gateway on, reception collects "
             "exactly as before."),
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
            ("<b>باقات الجلسات</b>: عدد جلسات بسعر واحد. بتتعرّف من نفس "
             "الشاشة (الخدمة · عدد الجلسات · السعر · مدة الصلاحية لو فيه)، "
             "والخدمة بتفضل تتباع بالجلسة زي ما هي — الاتنين مع بعض.",
             "<b>Session packages</b>: a number of sessions for one price, "
             "defined on the same screen (service · sessions · price · an "
             "optional window). The service goes on selling per session "
             "exactly as before — both, side by side."),
            ("<b>الفلوس بتتحرّك مرة واحدة</b>: الباقة بند عادي على فاتورة "
             "عادية. بعد كده كل جلسة بتنزل على فاتورة يومها <b>بصفر</b> "
             "ومكتوب عليها «جلسة ٣ من ١٠» — فالأهل يشوفوا الجلسة اتسجلت "
             "وما اتحاسبوش عليها تاني. والرصيد بيبان في ملف الطفل وعلى شاشة "
             "التحصيل قبل ما حد يقول سعر.",
             "<b>The money moves once</b>: the package is an ordinary line on "
             "an ordinary invoice. Each session then appears on that day's "
             "bill at <b>zero</b>, reading \"session 3 of 10\" — so the "
             "family sees it recorded and is not charged again. The balance "
             "shows on the child's file and on the collect screen before "
             "anybody quotes a price."),
            ("<b>الباقة اللي قربت تخلص مدتها بتتصرف الأول</b>، وباقة اتباعت "
             "ما بتتمسحش — بتتعطّل، عشان اللي الأهل دفعوه يفضل مقروء.",
             "<b>The course closest to expiring is spent first</b>, and an "
             "offer somebody bought is switched off rather than deleted, so "
             "what a family paid for stays readable."),
            ("<b>نوع الحالة</b> (خاصة / مستشفى / طوارئ): نفس العملية بنفس "
             "الجراح بتبقى سعر مختلف وأتعاب مختلفة. تحت «لكل طبيب» في "
             "الخدمة تقدر تحط استثناء لكل نوع: سيب السعر فاضي = سعره "
             "العادي، وسيب العمولة «زي العادي» = عمولته العادية، و«بدون» "
             "معناها ما بياخدش على النوع ده. وحالة من غير نوع بتتسعّر "
             "بسعر الطبيب العادي زي ما كانت بالظبط.",
             "<b>The kind of case</b> (private / hospital / emergency): the "
             "same operation by the same surgeon is a different price and a "
             "different fee. Under \"per doctor\" on the service you can set "
             "an exception per kind — a blank price means their ordinary "
             "price, \"as usual\" means their ordinary commission, and "
             "\"none\" means they are paid nothing on that kind. A case with "
             "no kind prices at the doctor's ordinary rate exactly as before."),
            ("<b>تعليم مكان الجراحة بيتسجّل بناحيته</b> — وبند «تعليم مكان "
             "الجراحة» في الـchecklist بيتقرا منه. خانة بتقول «اتعلّم» من "
             "غير ما تقول <b>أنهي</b> مكان هي بالظبط إزاي عملية بتتعمل في "
             "الناحية الغلط وعليها توقيع بيقول إنها اتراجعت. و<b>«مش منطبق» "
             "إجابة صحيحة</b> — عملية زي اللوز مالهاش ناحية، ومنعها كان "
             "هيخلّي الناس تختار «شمال» عشان تعدّي من الشاشة.",
             "<b>The surgical site is recorded with its side</b> — and the "
             "checklist's site item is read from it. A box saying \"marked\" "
             "without saying <b>which</b> site is precisely how a wrong-side "
             "operation ends up with a signature saying it was verified. And "
             "<b>\"not applicable\" is a correct answer</b> — a tonsillectomy "
             "has no side, and refusing it would have people picking \"left\" "
             "to get past the screen."),
            ("<b>الدم حقيقتين مش واحدة</b>: «محتاج دم؟» قرار الجرّاح، "
             "و«محجوز ومتوفّر؟» جواب بنك الدم. علامة واحدة كانت هتخلّي "
             "«محدش سأل» و«مش محتاج» نفس الجملة — وفي السؤال ده الفرق طفل "
             "بينزف وحد بيتكلّم في التليفون.",
             "<b>Blood is two facts, not one</b>: whether it is needed is the "
             "surgeon's decision, whether it is reserved is the bank's "
             "answer. One flag would make \"nobody asked\" and \"none "
             "needed\" the same sentence — and on this question the "
             "difference is a child bleeding while somebody telephones."),
            ("<b>تقييمين مش واحد</b>: «ما قبل التخدير» قبل بأيام، و<b>«ما "
             "قبل الاستحثاث»</b> في غرفة التخدير قبل الاستحثاث على طول. وبند "
             "<b>«فحص التخدير»</b> في الـchecklist بقى بيتقرا من التاني — "
             "وتقييم من يوم تاني بيتقرا «مش بتاع يوم العملية» مش بيتحسب، لأن "
             "المعيار طالب تقييم <b>فوري</b> مش تقييم موجود في الملف.",
             "<b>Two assessments, not one</b>: the pre-anaesthetic look days "
             "ahead, and the <b>pre-induction</b> one in the anaesthetic room "
             "immediately before. The checklist's <b>anaesthetic item</b> is "
             "read from the second — and one from another day reads as "
             "\"not from the day of the operation\" and does not count, "
             "because the standard asks for an <b>immediate</b> assessment, "
             "not one on file."),
            ("<b>خطة التخدير بستة عناصر</b>: نوع التخدير · تقنية الاستحثاث "
             "بالأدوية وجرعاتها ووقتها · تأمين مجرى الهوا · إدارة السوائل · "
             "اللي اتدّى أثناء التخدير · أي حدث غير معتاد. <b>العناوين من "
             "المعيار والكلام كله من طبيب التخدير</b> — البرنامج ما بيكتبش "
             "ولا كلمة منهم. والأربعة اللي بيتكتبوا قبل الحالة لو ناقص منهم "
             "حاجة <b>بتتسمّى بالاسم</b> مش بتتعدّ.",
             "<b>The anaesthesia plan has six elements</b>: the kind of "
             "anaesthetic · the induction technique with drugs, doses and "
             "times · securing the airway · fluid management · what was given "
             "during · any unusual event. <b>The headings are the standard's "
             "and every word under them is the anaesthetist's</b> — the "
             "program writes none of it. Whatever is missing from the four "
             "written before the case is <b>named</b>, not counted."),
            ("<b>بند «الموافقة» في الـchecklist بيتقرا من الإقرار</b>، مش "
             "بيتعلّم بالإيد. في صفحة العملية بتربط الإقرار اللي بيغطّيها من "
             "إقرارات ملف الطفل، والبند بيتعلّم لوحده لو الإقرار <b>موقّع "
             "ومش مسحوب ومدته سارية يوم العملية</b> — وبيتشال لوحده لو لأ، "
             "حتى لو حد علّمه. الشاشة بتقول السبب بالظبط: مش مربوط · من غير "
             "توقيع · اتسحب · انتهت مدته.",
             "<b>The checklist's consent item is read from the consent</b>, "
             "not ticked by hand. On the case screen you link which of the "
             "child's consents covers it, and the item ticks itself when that "
             "consent is <b>signed, not withdrawn, and still standing on the "
             "day of the operation</b> — and unticks itself when it is not, "
             "however firmly somebody ticked. The screen names which of the "
             "four it is: not linked · unsigned · withdrawn · expired."),
            ("<b>وما بيمنعش العملية</b>: المستشفى ممكن تمشي، والبرنامج "
             "بيسجّل مش بيقفل. اللي مش هيحصل إن النقص ده يتحسب علامة خضرا — "
             "بيفضل ظاهر كنقص في الـchecklist.",
             "<b>And it refuses nothing</b>: a hospital may proceed, and the "
             "program records rather than blocks. What it will not do is show "
             "the gap as a green tick — it stays visible as a missed item."),
            ("<b>الإفاقة والخروج</b>: بعد ما العملية تخلص، زرار «دخلت "
             "الإفاقة»، وبعدين شاشة الخروج. شاشة <b>الإفاقة</b> بتوريك مين "
             "في الأوضة دلوقتي، و<b>مين خلّص ولسه ما خرجش</b> — حتى لو محدش "
             "علّم دخوله الإفاقة أصلاً، وده بالظبط اللي بيتنسي.",
             "<b>Recovery and discharge</b>: when the case finishes, one "
             "press moves the child to recovery, then the discharge screen. "
             "The <b>recovery</b> screen shows who is in the room now and "
             "<b>who finished and has not gone home</b> — including cases "
             "nobody marked into recovery at all, which are exactly the ones "
             "that get forgotten."),
            ("<b>قرار المتابعة ما ينفعش يتسكّت عنه</b>: الخروج بيترفض من غير "
             "إجابة «محتاج متابعة؟ أيوه/لأ». السبب إن «مش محتاج» و«محدش سأل» "
             "لو اتحطوا في خانة واحدة بيبقوا نفس الحاجة — والطفل اللي محدش "
             "شافه تاني بيكون التاني مش الأول.",
             "<b>The follow-up decision cannot be skipped</b>: a discharge is "
             "refused without a yes or no. If \"not needed\" and \"nobody "
             "asked\" share one column they become the same thing — and the "
             "child nobody sees again is the second, not the first."),
            ("<b>تعليمات بعد الجراحة بتتكتب على العملية</b> (في الخدمة)، "
             "وبتتبعت للأهل وهم واقفين على الباب — مش بكرة. العملية اللي "
             "مفيش لها تعليمات ما بتبعتش رسالة فاضية، والشاشة بتقولك إنها "
             "ناقصة عشان تتكتب المرة الجاية.",
             "<b>Post-operative instructions are written per procedure</b> "
             "(on the service) and sent to the family at the door, not "
             "tomorrow. A procedure with none sends nothing rather than an "
             "empty message, and the screen says so, so it can be written "
             "before the next one."),
            ("<b>التخدير بند لوحده</b> لما العيادة تسعّره: الجراح والمخدّر "
             "اتنين بيشتغلوا، وكل واحد أتعابه على بنده. سعّر خدمة "
             "<b>SVC-ANAES</b> بصفر وما هتشوفش البند خالص — العيادة اللي سعر "
             "العملية عندها شامل التخدير ما بيتغيّرش عندها حاجة.",
             "<b>Anaesthesia is its own line</b> where the clinic prices it: "
             "the surgeon and the anaesthetist both worked, and each is paid "
             "on their own line. Leave the <b>SVC-ANAES</b> service at zero "
             "and the line never appears — a clinic whose operation price "
             "already includes the anaesthetic sees no change at all."),
            ("<b>الرعاية التمريضية والطبية — بالطريقتين</b>. المستشفيات "
             "بتحسبها بشكلين: <b>مبلغ يومي</b> بيتضرب في عدد الليالي، أو "
             "<b>نسبة</b> من الفاتورة. البرنامج ما بيختارش لك — انت بتعرّف "
             "القاعدة بشكلها، وتقدر تحط الاتنين مع بعض. والعيادة اللي ما "
             "تعرّفش ولا واحدة ما بيتغيّرش عندها حاجة خالص.",
             "<b>Nursing and medical care — both ways</b>. Hospitals work it "
             "out in two shapes: a <b>daily amount</b> times the nights, or a "
             "<b>percentage</b> of the bill. The program does not choose for "
             "you — you define the rule in its shape, and you may have both. "
             "A clinic that defines neither sees no change at all."),
            ("<b>النسبة بتتحسب على الأقسام اللي انت تسمّيها</b> — الشائع في "
             "مصر إنها على كل حاجة ما عدا الأدوية والدمغة، وده بالظبط اللي "
             "بند الفاتورة اتعمل عشانه. ما تختارش أقسام = الفاتورة كلها. "
             "و<b>النسبة عمرها ما بتتحسب على بند رعاية تاني</b> — لا على "
             "نفسها ولا على التانية.",
             "<b>The percentage is taken of the sections you name</b> — the "
             "common Egyptian practice is everything except medicines and "
             "stamps, which is exactly what the bill-section axis exists for. "
             "Naming none means the whole bill. And <b>a percentage is never "
             "levied on another care charge</b> — not on itself, not on the "
             "other one."),
            ("<b>بند الرعاية بيتصحّح مش بيتزاد</b>: الإقامة الطويلة بتترحّل "
             "كل يوم، ولو البند كان بيتزاد كان رعاية الليلة الرابعة هتتحسب "
             "أربع مرات. وقاعدة بتتقفل بيتشال بندها بدل ما يفضل واقف برقم "
             "إمبارح.",
             "<b>The care line is corrected, not added to</b>: a long stay is "
             "posted every day, and a line that accumulated would bill the "
             "fourth night's nursing four times. A rule switched off has its "
             "line removed rather than left standing at yesterday's figure."),
            ("<b>بند الفاتورة</b> هو اللي الفاتورة بتتجمّع بيه في الملخّص "
             "(إقامة · عمليات · أدوية · مستلزمات …). سيبه فاضي والبرنامج "
             "يستنتجه من تصنيف الخدمة، والقايمة نفسها تتزوّد وتتعدّل من "
             "الشاشة — مفيش كود بيقرا اسم قسم، فالمستشفى تضيف «مستلزمات غرفة "
             "عمليات» وتشتغل نفس الدقيقة.",
             "The <b>bill section</b> is what the summary groups by "
             "(accommodation · surgery · medicines · supplies …). Leave it "
             "blank and the program derives it from the service's category; "
             "the list itself is added to and edited on this screen — no "
             "code reads a section by name, so a hospital adding «theatre "
             "supplies» gets a working section the same minute."),
        ],
    },
    {
        "key": "payers",
        "module": "finance",
        "capability": "finance_manage",
        "icon": "file-earmark-medical",
        "title": ("الجهات والمطالبات", "Payers & claims"),
        "lines": [
            ("<b>كارت التأمين والاستقبال:</b> في ملف الطفل (العيلة ← التأمين) الكارت فيه "
             "رقم العضوية وفئة الاشتراك وصاحب الاشتراك وصلته بالطفل وتاريخ الإصدار والانتهاء "
             "وصورته وش وضهر. حالة الكارت بتظهر جنب اسم الطفل عند الحجز وفي لوحة اليوم "
             "وعند الخزنة: ساري · هينتهي خلال ١٤ يوم · منتهي · عقد الشركة منتهي. ولو الكارت "
             "منتهي، الأهل بيدفعوا كاش عادي من غير أي قرار، والفاتورة بتستنى الكارت الجديد "
             "«المهلة» (٣٠ يوم، وبتتغير من الإعدادات). أول ما الكارت الجديد يتسجّل بتاريخ إصداره "
             "وصورته، كل فاتورة مستنية ويومها جوه مدة الكارت بتتحول للشركة لوحدها، والفرق بيروح "
             "رصيد في حساب الأسرة (ياخدوه كاش من «رد الرصيد» لو طلبوا). خصم الفئة النقدي بيتشال "
             "من الخدمة اللي الشركة بتغطيها، والخدمة اللي محتاجة موافقة بتستنى الموافقة، والفاتورة "
             "مش بتتحول لو هتعمل على الأهل فلوس. و«كاش نهائي» للي مش هيجددوا. الإقامة بتتحسب "
             "بيوم الدخول. وقايمة «كروت "
             "التأمين اللي هتنتهي» (من التقارير أو ملف الطفل) عشان تكلّم الأهل قبل الزيارة — "
             "ومنها «ذكّر الأهل» لأسرة واحدة، أو «ذكّر كل اللي في القايمة» (ما عدا اللي اتبعتلهم "
             "الأسبوع ده واللي ملهمش رقم): رسالة «تذكير بتجديد كارت التأمين» اللي بتتكتب في "
             "قوالب الرسايل، بالواتساب أو الـSMS زي باقي الرسايل، والصف بيكتب إمتى اتبعتت.",
             "<b>The insurance card and reception:</b> in the child's file (Family → "
             "Insurance) the card holds the membership number, the plan, the subscription "
             "holder and relation, the issue and expiry dates and its photo front and back. "
             "Its state shows beside the child's name at booking, on the day's board and at "
             "the till: valid · ends within 14 days · expired · payer's contract ended. With "
             "an expired card the family pays in cash with no decision asked, and the bill "
             "waits for the new card for the clinic's wait (30 days, changed in Settings). "
             "Once the new card is saved with its issue date and photo, every waiting bill "
             "whose day it covers turns into a contract bill by itself and the difference goes "
             "to the family's account (handed back from «Give back the balance» if they ask). "
             "The cash-category discount comes off what the payer covers, a line needing an "
             "approval waits for it, and a bill is never converted into a debt for the "
             "family. «Cash for good» is for a family that will not renew. A stay is judged "
             "on its first day. «Insurance cards running "
             "out» (from Reports or the child's file) is the list to call families from — "
             "and to message them: «Remind the family» for one, or «Remind everyone on the "
             "list» (except those reminded this week and those with no number), with the "
             "«Insurance card renewal reminder» template written under message templates, "
             "by WhatsApp or SMS like every other message; the row says when it went."),
            ("<b>الجهات</b> (تأمين/نادي/نقابة) وجدول التغطية لكل خدمة.",
             "<b>Payers</b> (insurer / club / syndicate) and the per-service "
             "benefits table."),
            ("الخصم اللي أخده العضو بيفضل <b>مستحقاً على الجهة</b>، وتطبع "
             "مطالبة بالفترة لكل جهة وتتابع تحصيلها.",
             "The member's discount stays <b>claimable from the payer</b>; "
             "print a per-period claim per payer and track its collection."),
            ("<b>عقد جديد من تاريخ</b>: من العقد القديم ← «نسخة جديدة» بالتواريخ "
             "الجديدة (وممكن «زوّد كل الأسعار بنسبة» في نفس الخطوة) — بيشتغل لوحده "
             "يوم ما يبدأ. على شاشة أسعاره: زيادة على خدمة أو قسم أو الكل مع "
             "التقريب، أو نزّل الشيت Excel وعدّله وارفعه؛ الاتنين بيوروك التغييرات "
             "(سعر اتغيّر، بقى متغطي، طلع من العقد) قبل الحفظ. التذكير قبل الانتهاء "
             "بعدد أيام من الإعدادات، والعقد اللي انتهى من غير تجديد وأعضاؤه "
             "كارتهم ساري بيتنبّه عليه بالأحمر.",
             "<b>A new contract from a date</b>: from the old contract → «new "
             "copy» with the new dates (optionally «raise every price by» in the "
             "same step) — it bills by itself from its first day. On its rates "
             "screen: a raise on a service, a category or everything with "
             "rounding, or download the Excel sheet, edit and upload it; both "
             "show the changes (price changed, now covered, out of the contract) "
             "before saving. The reminder comes the number of days set in "
             "Settings, and a contract that ended with no renewal while members "
             "still hold cards is flagged in red."),
            ("<b>الموافقة وخطابها</b>: الرد بيتسجّل برقمه ومعاه صورة الخطاب (PDF أو "
             "صورة). ولكل عقد سياسة للبند اللي مستني موافقة: «نعمل ونستنى» "
             "(الأسرة ما بتدفعش)، أو «الأسرة تدفع ونرجّع» — ولما الموافقة تيجي "
             "الفاتورة بتتغطّى واللي اتدفع زيادة بيروح لحساب المريض الدائن. "
             "الحالة العاجلة في الطوارئ عمرها ما بتدفع وهي مستنية. والدفعة "
             "المقدّمة المقترحة لكل قسم من الإعدادات (للكاش) ومن شروط العقد "
             "(للمؤمَّن عليه) بتظهر على شاشة الإقامة.",
             "<b>The approval and its letter</b>: the answer is recorded with "
             "its number and the letter's scan (PDF or image). Each contract "
             "chooses what happens while a line waits: «do it and wait» (the "
             "family does not pay), or «the family pays, refunded» — when the "
             "approval comes the bill is covered and what was overpaid goes to "
             "the patient account. An urgent emergency child never pays while "
             "it waits. The suggested deposit per department, from Settings "
             "(cash) and the contract's terms (members), shows on the stay."),
            ("<b>مكتب المطالبات</b>: أول شاشة المطالبات فيها كل جهة ودفعتها "
             "الجاية (من بعد آخر فترة اتطالب بيها لحد يوم الدورة في العقد) بزرار "
             "«اعمل المطالبة»، والمطالب بيه والمقبول والمدفوع فعلاً والمرفوض المفتوح. "
             "المطالبة فيها سطورها — كل بند بقسمه ورقم موافقته — وردّ الجهة بيتكتب "
             "على كل سطر: مقبول أو جزء أو مرفوض بسببه. المرفوض يا يتعاد تقديمه في "
             "مطالبة جديدة مربوطة بيه، يا نتنازل عنه بقرار — ومينفعش الاتنين. "
             "والمطالبة بتتنزل شيت Excel للجهة.",
             "<b>The claims desk</b>: the claims screen opens on each payer's "
             "next batch (from after its last claimed period to its contract's "
             "cycle day) with «Make the claim», and what was claimed, accepted, "
             "actually paid, and refused and still open. A claim carries its "
             "lines — each item with its department and approval number — and "
             "the payer's answer is written per line: accepted, part, or "
             "refused with the reason. A refusal is either resubmitted on a new "
             "claim tied to it, or written off by decision — never both. The "
             "claim downloads as an Excel sheet for the payer."),
            ("<b>تقييم كل جهة</b> (من المطالبات أو الجهات، أو «كل التقارير»): لكل "
             "شركة — صف واحد في جدول بالصفحات، واللي محتاجة انتباه فوق، وفلتر "
             "بكل كلمة («محتاجة انتباه»، «بتتأخر»، «بترفض كتير»…) بعددها، وبحث "
             "بالاسم في كل الصفحات، و«التفاصيل» تحت الصف: بتدفع بعد كام يوم فعلاً قصاد الأيام اللي في العقد، وكام مطالبة "
             "اتدفعت متأخر وكام عدّت ميعادها النهارده؛ ونسبة المرفوض من اللي ردّت "
             "عليه، وأكتر أسباب الرفض والخدمات والأقسام؛ والموافقات: كام اتطلبت "
             "واتقبلت واترفضت ولسه، وبترد في كام يوم. وكلمة بسيطة — «ملتزمة» أو "
             "«بتتأخر» أو «بترفض كتير» أو «موافقاتها بطيئة» — كل كلمة من رقم "
             "مكتوب جنبها، و«العدد قليل» لما المطالبات أقل من إنها تتحكم. ولو "
             "مساعد اللوحات شغال: «اقرا التقييم» — بيروح له أرقام وأسماء شركات "
             "وخدمات بس، من غير أي طفل.",
             "<b>Each payer's record</b> (from the claims or the payers screen, "
             "or «All reports»): one row per company, in pages, the ones "
             "that need attention on top, a filter for each word («Need "
             "attention», «Pay late», «Refuse a lot»…) with its count, a search "
             "by name across every page, and «Details» under the row — how many days it actually "
             "takes to pay against the days its contract gives, how many claims "
             "were paid late and how many are past their day now; the share "
             "refused of what it answered, with its top refusal reasons, "
             "services and departments; and approvals: asked, granted, refused, "
             "waiting, and the days it takes to answer. A plain word — «pays on "
             "time», «pays late», «refuses a lot», «slow to approve» — each from "
             "a figure printed beside it, and «too few to say» when there are "
             "not enough claims. With the boards' assistant on: «Read the "
             "record» — it is sent figures and the names of companies and "
             "services only, no child."),
            ("<b>مجموعات جوه العقد</b> (شاشة أسعار العقد ← «مجموعات جوه العقد»): "
             "اجمع أي خدمات تحت اسم من عندك — تختارها بالبحث أو تضيف فئة كاملة — "
             "ولكل مجموعة: الشركة بتغطي كام في المية، والأهل ياخدوا خصم كام في "
             "المية على اللي عليهم، أو الاتنين. «نقدي 10%» = الشركة 0 والأهل خصم "
             "10؛ «تعاقد 25%» = الشركة 25. الخدمة في مجموعة واحدة بس في العقد، "
             "والقاعدة اللي على الخدمة لوحدها بتغلب المجموعة، والمجموعة بتغلب "
             "الفئة. سطر الفاتورة بيقول من أنهي مجموعة وكام خصم الأهل، والمطالبة "
             "بتاخد نصيب الشركة بس. ونسبة الطبيب على السطر ده بتتحسب بعد خصم الأهل، "
             "إلا لو العقد مكتوب فيه «قبل الخصم» (اختيار تحت المجموعات). التجديد "
             "بينقل المجموعات، و«انسخ المجموعات من عقد تاني» بيجيبها من عقد تاني "
             "من غير ما يلمس اللي هنا.",
             "<b>Groups inside a contract</b> (the contract's rates screen → «Groups "
             "inside the contract»): gather any services under a name of your "
             "own — picked by search, or a whole category at once — and give "
             "each group what the payer covers in percent, the family's discount "
             "in percent on its own share, or both. «Cash 10%» is payer 0 and "
             "family 10; «contract 25%» is payer 25. A service is in one group of "
             "a contract at most; a rule for the service alone wins over its "
             "group, and a group wins over a category. The bill line says which "
             "group and the family's discount, and the claim takes the payer's "
             "share only. The doctor's share on such a line is worked out after "
             "the family's discount, unless the contract is set to «before the "
             "discount» (a choice under the groups). A renewal carries the "
             "groups, and «Copy the groups "
             "from another contract» brings another's in without touching what "
             "is here."),
            ("<b>نصيب الأسرة وسقوف الجهة</b> على شاشة أسعار العقد: مبلغ ثابت "
             "على الأسرة في كل فاتورة لكل قسم، وأقصى ما الجهة تدفعه في الفاتورة "
             "وفي ليلة السرير (الغرفة الخاصة فرقها على الأسرة)، والتحمّل وسقف "
             "السنة للعضو. كل سطر في الفاتورة بيقول ليه الأسرة بتدفعه، "
             "والمطالبة بتاخد اللي على الجهة بعد الشروط دي بس.",
             "<b>Family share and payer ceilings</b> on the contract's rates "
             "screen: a fixed family share per bill in each department, the "
             "most the payer pays per bill and per bed night (a private room's "
             "difference is the family's), and the member's yearly deductible "
             "and ceiling. Each bill line says why the family pays it, and "
             "the claim takes only what the payer owes after these terms."),
            ("<b>حساب المريض الدائن</b>: الدفعة المقدّمة للإقامة، أو فلوس "
             "أكتر من خطة الأسنان، بتتحفظ على حساب المريض (من ملفه ← "
             "الحسابات، أو من صفحة الإقامة). منه تتسدّد فواتيره بزرار "
             "«سداد من الرصيد»، واللي يفضل يترد له. النقدي بيدخل الوردية، "
             "والسداد من الرصيد ما بيتعدّش في الدرج تاني. مفعّل تلقائي في "
             "المستشفى والأسنان، ويتفتح أو يتقفل من السياسات.",
             "<b>Patient account</b>: a stay deposit, or more than a dental "
             "plan's bill, is held on the patient's account (patient file → "
             "finance, or the stay's page). It pays their bills with «Pay "
             "from account», and what is left is handed back. Cash enters "
             "the shift; paying from the account is not counted in the "
             "drawer again. On by itself for a hospital or a dental clinic, "
             "and switched in the policies."),
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
            ("<b>شكل الفاتورة</b>: فوق البنود <b>ملخّص</b> بأقسام الفاتورة "
             "— الإقامة كذا، العمليات كذا، الأدوية كذا — وتحته التفاصيل. "
             "ولو الفاتورة على أكتر من يوم (إقامة داخلي مثلاً) التفاصيل "
             "بتتقسّم <b>باليوم</b> جوّه كل قسم، لأن كل بند بقى شايل تاريخ "
             "شغله مش تاريخ الفاتورة. وقايمة الفواتير فيها فلتر "
             "<b>داخلي/خارجي</b>.",
             "<b>The shape of a bill</b>: a <b>summary</b> by bill section "
             "above the lines — accommodation, surgery, medicines — with the "
             "detail below it. When the bill covers more than one day (a "
             "stay), the detail is grouped <b>by day</b> inside each section, "
             "because every line now carries the day its work was done rather "
             "than the day of the bill. The invoice list has an "
             "<b>inpatient / outpatient</b> filter."),
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
            ("<b>كل التقارير في صفحة واحدة:</b> شاشة التقارير فيها تقاريرها وتقارير "
             "الأقسام (الإحالات، زمن المعمل والأشعة، الصيدلية، العمليات، رضا المرضى…) "
             "متقسمة مالية وطبية وتشغيل وجودة، وكل واحد بيشوف اللي يقدر يفتحه بس. "
             "اكتب كلمة في خانة البحث (أو اضغط /) تلاقي التقرير، والنجمة بتحطه في "
             "«المفضلة» فوق — ليك لوحدك ومن أي جهاز.",
             "<b>All reports on one page:</b> the reports screen lists its own "
             "reports and the departments' (referrals, lab and imaging turnaround, "
             "pharmacy, theatres, patient satisfaction…), grouped as finance, medical, "
             "operations and quality, each shown only to whoever may open it. Type a "
             "word in the search box (or press /) to find a report, and the star puts "
             "it under «Starred» at the top — yours alone, on any computer."),
            ("<b>منشئ التقارير:</b> من «كل التقارير» ← «منشئ التقارير». اختار المصدر "
             "(الزيارات، التشخيصات، الأدوية، الحجوزات، الفواتير، الخدمات المفوترة) والفترة، "
             "وتعدّ إيه أو تجمع إيه، وقسّمه بالشهر أو الطبيب أو جهة الدفع أو السن. «قارن "
             "الفترة بـ» بتحط الفترة جنب اللي قبلها أو نفس التواريخ السنة اللي فاتت (أول "
             "٦ شهور السنة دي قصاد اللي فاتت شهر بشهر)، و«جنب بعض بـ» بتحط طبيب جنب طبيب أو "
             "نقدي جنب تعاقد أو شركة جنب شركة. وللسن والمبالغ فيه إحصاء وصفي: المتوسط "
             "والوسيط والانحراف المعياري. الأرقام مجمّعة من غير أسماء، والفلوس بصلاحية "
             "المالية بس. وتقدر تصدّره Excel وتحفظه لنفسك أو لزمايلك.",
             "<b>Report builder:</b> from «All reports» → «Report builder». Pick the source "
             "(visits, diagnoses, medicines, bookings, bills, billed services) and the period, "
             "what to count or add up, and split it by month, doctor, payer or age. «Compare "
             "the period with» puts it beside the period before or the same dates last year "
             "(this year's first six months against last year's, month by month), and «side "
             "by side by» puts doctor beside doctor, cash beside contracts or payer beside "
             "payer. Ages and amounts have descriptive statistics: mean, median and standard "
             "deviation. Figures are totals without names, and money needs the finance "
             "rights. Export it to Excel and save it for yourself or your colleagues."),
            ("<b>اسأل التقارير:</b> لو الذكاء الاصطناعي شغال و«اسأل التقارير» متشغّلة من "
             "الإعدادات، فوق منشئ التقارير فيه خانة تكتب فيها سؤالك بالكلام («إيرادات كل دكتور "
             "الشهر ده قصاد اللي فات»، «أكتر التشخيصات تحت سنتين»). التقرير بيطلع بإعداداته، "
             "فتشوف فهم إيه وتعدّل وتحفظ. اللي بيروح للذكاء الاصطناعي سؤالك وأسماء الخانات بس، "
             "وأسماء الدكاترة والشركات اللي في السؤال بتتطابق جوه البرنامج. و«اشرح النتيجة» "
             "بيبعت الجدول بأرقامه والدكاترة بأكواد.",
             "<b>Ask the reports:</b> with the assistant set up and «Ask the reports» on "
             "in Settings, the report builder has a box for a question in words («each "
             "doctor's revenue this month against last», «the commonest diagnoses under "
             "two»). The report comes out with its settings, so you see what was "
             "understood, change it and save it. Only your question and the builder's "
             "words go to the assistant; doctors and payers named in the question are "
             "matched inside the program. «Explain the result» sends the table's "
             "figures, doctors as codes."),
            ("<b>مؤشرات المستشفى</b> (التقارير ← مؤشرات المستشفى) — بتظهر بس لو عندك قسم "
             "من الأقسام دي شغال، وكل جزء مع قسمه: <b>الطوارئ</b> — من الوصول للفرز، ومن الوصول "
             "للطبيب، ومدة البقاء (الوسيط)، واللي مشي قبل ما يتشاف، واللي رجع خلال ٧٢ ساعة؛ و«الطبيب "
             "شافه» بيتسجّل بزرار «الطبيب شاف الطفل» في صفحة الحضور، أو لوحده من أول أمر يكتبه "
             "الطبيب. <b>العمليات</b> — الوقت المستخدم من المحجوز، وأول عملية في اليوم في ميعادها، "
             "والوقت بين عملية والتانية، والإلغاء والتأجيل وأسبابهم. <b>العناية والحضانة</b> — "
             "اللي رجعوا خلال ٤٨ ساعة من الخروج. <b>السلامة</b> — السقوط وقرح الفراش وأخطاء "
             "الأدوية اللي وصلت للطفل لكل ١٠٠٠ يوم إقامة، من البلاغات زي ما اتكتبت. أرقام مش "
             "أحكام، وجنب كل رقم نفس المدة اللي قبلها.",
             "<b>Hospital indicators</b> (Reports → Hospital indicators) — shown only "
             "with one of these departments running, each part with its own: "
             "<b>Emergency</b> — arrival to triage, arrival to doctor and length of stay "
             "(medians), left unseen, back within 72 hours; «seen by a doctor» is "
             "recorded by «Doctor has seen the child» on the attendance, or by itself "
             "from the doctor's first order. <b>Theatres</b> — time used of time booked, "
             "the first case of the day on time, changeover between cases, and "
             "cancellations and postponements with their reasons. <b>ICU and NICU</b> — "
             "back within 48 hours of leaving. <b>Safety</b> — falls, pressure injuries "
             "and medication errors reaching the child per 1000 bed days, from the "
             "reports as filed. Numbers, not judgements, each beside the stretch before."),
            ("<b>لوحة الاستهلاك</b> (التقارير ← الاستهلاك): استهلكنا أد إيه "
             "وبكام في أي فترة، جنب نفس المدة اللي قبلها — المخزن كله (حسب "
             "القسم والمخزن ونوع الصنف)، والأدوية، ومستهلكات المعمل (وتكلفة كل "
             "تحليل قدام سعره)، والذكاء الاصطناعي بالمكالمات والتوكنز. الهالك "
             "لوحده، والصرف اللي من غير تكلفة متقال.",
             "<b>Consumption board</b> (Reports → Consumption): how much was "
             "used and what it cost over any period, beside the same stretch "
             "before — the whole store (by department, warehouse and item "
             "type), medicines, lab consumables (each test's cost against its "
             "price), and the AI assistant in calls and tokens. Waste is apart, "
             "and issues recorded without a cost are said."),
            ("<b>مالية</b>: الدخل، أعمار الديون، الخصومات، الضريبة، الميزان، "
             "والميزانية.",
             "<b>Financial</b>: income, AR ageing, discounts, VAT, trial "
             "balance and balance sheet."),
            ("<b>مراكز التكلفة</b>: كل قسم بإيراده ومصروفه المباشر والباقي "
             "منه. الإيراد بيروح لقسمه لوحده من مكان ما الفاتورة جت، والمصروف "
             "بتختار قسمه وإنت بتسجّله، ولو ما اخترتش بيبقى مشترك في سطر "
             "لوحده. والمجموع هو نفس صافي قائمة الدخل.",
             "<b>Cost centres</b>: each part of the clinic with its revenue, "
             "its direct costs and what is left. Revenue reaches its centre by "
             "itself from where the bill came from; an expense takes the "
             "centre you choose when you record it, and with none it is shared, "
             "on a line of its own. The total is the income statement's net."),
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
        "title": ("خدمة عملاء المرضى", "Patient Care"),
        "lines": [
            ("<b>التقييم بعد كل خدمة، مش بعد الكشف بس:</b> بعد الخروج من "
             "الداخلي والحضّانات والطوارئ الأهل بيوصلهم تقييم بتلات نواحي — "
             "الطبية والخدمية والمالية — ومرة واحدة في الأسبوع بالكتير. "
             "ولو ناحية نجمتين أو أقل بتوصل لصندوق الرسايل كشكوى. وما بيتبعتش "
             "أبداً بعد وفاة أو تحويل. <b>والخروج على المسؤولية</b> بيتسأل "
             "فيه «ماشيين ليه؟» بضغطة، والقايمة بتتعدّل من القوايم.",
             "<b>A rating after every service, not only after a visit:</b> "
             "after leaving the ward, the NICU or emergency the family is "
             "sent a survey on three sides — medical, service and money — at "
             "most once a week. A side rated two stars or less reaches the "
             "inbox as a complaint. It is never sent after a death or a "
             "transfer. <b>Leaving against advice</b> asks \"why?\" in one "
             "tap, from a list the clinic edits."),
            ("<b>الشكاوى برقم ومتابعة:</b> أي حد شغال يسجّل شكوى من زرار "
             "«سجّل شكوى» فوق، ويدّي العميل رقمها — أو يطبع الاستمارة الفاضية، "
             "أو يبعتله لينك يكتبها بنفسه. الشكوى بتروح لخدمة العملاء "
             "(صلاحية «متابعة الشكاوى»): يكلّموه، ويكتبوا لقينا إيه وعملنا إيه "
             "وقلناله إيه، والرد بيوصله ومعاه لينك يقيّم الحل — لو قال ما "
             "نفعش بتتفتح تاني لوحدها. والشكوى اللي عدّت مواعيد سياسة "
             "المستشفى بتظهر متأخرة (معيار PCC.16).",
             "<b>Complaints with a number and follow-up:</b> anyone on the "
             "staff logs one from the «Log a complaint» button at the top "
             "and hands the family its number — or prints the blank form, or "
             "sends them a link to write it themselves. It goes to customer "
             "service (the «Handle complaints» permission): they contact the "
             "family, write what was found, what was done and what they were "
             "told, and the answer reaches the family with a link to rate it "
             "— a low rating reopens it by itself. A complaint past the "
             "hospital's policy timeframes shows as late (PCC.16)."),
            ("<b>استبيان بيمشي ورا الإجابات:</b> من «محرّر الاستبيان» ← «الأسئلة "
             "والقفزات» تضيف أسئلة المؤسسة وترتّبها، وعلى كل إجابة تقول «روح "
             "لسؤال كذا» أو «اخلص». السؤال الفرعي ما بيظهرش غير لما إجابة تودّي "
             "عليه، والعيلة بتشوف سؤال واحد في كل شاشة. وفي الآخر شاشة شكر "
             "بلوجو المؤسسة: اللي قيّم وحش بيتقاله «هنكلّمك»، واللي قيّم 9 أو "
             "10 بيتعرض عليه لينك تقييم جوجل. ولوحة خدمة العملاء بتعرض "
             "إجابات أسئلة المؤسسة.",
             "<b>A survey that follows the answers:</b> under the survey "
             "editor → «Questions and jumps», add the organisation's own "
             "questions, order them, and on each answer say «go to question "
             "N» or «finish». A branch question appears only when an answer "
             "leads to it, and families see one question per screen. It ends "
             "on a thank-you in the organisation's name and logo: an unhappy "
             "family is told someone will call, one that scored 9 or 10 is "
             "offered the Google review link. The customer-service board "
             "shows the answers to the organisation's questions."),
            ("<b>صفحة التقييم اللي برّه البرنامج:</b> صفحة صغيرة على النت "
             "(Vercel) الأهل بيقيّموا منها، والبرنامج بيفضل جوّه العيادة. "
             "اللي بيطلع اسم المؤسسة واللوجو واسم القسم والأسئلة بس — من غير "
             "اسم الطفل ولا التليفون. البرنامج بيسحب الردود كل ١٠ دقايق "
             "وبيمسحها من برّه. عنوانها ومفتاحها في clinic.env، والخطوات في "
             "outside/survey/README.md.",
             "<b>The survey page outside the program:</b> a small page on "
             "the internet (Vercel) families rate from, while the program "
             "stays inside the clinic. What leaves is the organisation's "
             "name and logo, the unit's name and the questions — no child's "
             "name or phone. The program collects answers every 10 minutes "
             "and deletes them outside. Its address and key live in "
             "clinic.env; the steps are in outside/survey/README.md."),
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
            ("<b>رسايل SMS</b> (قناة إضافية، مقفولة لحد ما تشغّلها): من «الاتصال "
             "بواتساب والإعدادات ← رسايل SMS» اختار شركتك من الجاهز (SMS Misr، Victory Link، "
             "CEQUENS) أو اكتب بيانات أي شركة تانية زي شرحها — العنوان، واسم المرسل، "
             "واسم المستخدم والمفتاح، وشكل الطلب، وكود اللغة — أو اختار OpenSMS لموبايل "
             "Android على شبكة العيادة، وجرّب برسالة تجربة قبل أول رسالة. علّم أنهي أنواع رسايل تروح SMS بدل واتساب، أو خليها "
             "تتبعت SMS لما الرسالة ما توصلش على واتساب — لو الإرسال فشل، أو واتساب رجع "
             "قال بعدها إن الرقم ملوش واتساب. والـSMS ظاهرة كمان في «القنوات» بحالتها "
             "(شغالة، محتاجة إعداد، مقفولة) ولينك إعداداتها. ولو الشركة بتبعت تقارير وصول، حط "
             "العنوان اللي في الشاشة عندها، والرسالة بتتعلّم «وصلت» أو «فشلت». "
             "الرسالة العربي ٧٠ حرف والجزء ٦٧. بيشتغل مع الإرسال التلقائي بس.",
             "<b>SMS messages</b> (an extra channel, off until switched on): under "
             "«WhatsApp connection & settings → SMS messages» enter your SMS company's "
             "details — pick yours from the presets (SMS Misr, Victory Link, CEQUENS) "
             "or enter any other company's as its documentation gives them: "
             "address, sender name, user name and key, request body and language "
             "code — or pick OpenSMS for an Android phone on the clinic's "
             "network, and send a test before the first message. Tick which message types go by SMS instead of "
             "WhatsApp, or have a message sent by SMS when it does not reach "
             "WhatsApp — when sending fails, or when WhatsApp reports later that "
             "the number has no WhatsApp. SMS also shows on «Channels» with its "
             "state (sending, needs setting up, off) and a link to its settings. If "
             "the company sends delivery reports, give it the address on the "
             "screen and messages are marked delivered or failed. An Arabic SMS "
             "is 70 characters, 67 per part. Automatic sending only."),
            ("<b>اختيار شركة SMS في مصر:</b> الشركات بتبيع باقات رسايل مدفوعة مقدماً، "
             "والرسالة بتتحسب بقروش (بتقل كل ما الباقة تكبر)، وكل جزء من الرسالة "
             "الطويلة بيتحسب لوحده. اسم المرسل (اسم العيادة بالإنجليزي) لازم يتسجل "
             "الأول، ومحتاج غالباً السجل التجاري وخطاب من العيادة، وبياخد من أسبوعين "
             "لتلاتة؛ والأسماء العامة زي INFO ما بتتقبلش. قبل ما تختار اسأل الشركة: "
             "عندها API؟ بتبعت تقارير وصول على عنوان؟ بتغطي الأربع شبكات؟ وخد منها "
             "شرح الـAPI علشان تملا خانات الشاشة.",
             "<b>Choosing an SMS company in Egypt:</b> companies sell prepaid "
             "message bundles; each message costs a fraction of a pound (less in "
             "larger bundles), and every part of a long message is charged. The "
             "sender name (the clinic's name in English) must be registered first, "
             "usually with the commercial registration and a letter from the "
             "clinic, and takes two to three weeks; generic names such as INFO are "
             "refused. Before choosing, ask the company: does it have an API? Does "
             "it send delivery reports to an address? Does it cover all four "
             "networks? And get its API documentation to fill in the screen."),
        ],
    },
    {
        # CONNECTHUB_PLAN.md — every channel in the one inbox, and the
        # families who asked and have not come yet.
        "key": "channels_desk",
        "module": "messages",
        "icon": "diagram-3",
        "title": ("كل القنوات في صندوق واحد والعملاء المحتملين",
                  "Every channel in one inbox, and leads"),
        "lines": [
            ("<b>الصندوق واحد لكل القنوات</b>: واتساب وماسنجر وإنستجرام وتليجرام "
             "وتيك توك وإيميل العيادة — كل محادثة عليها علامة قناتها، والرد بيطلع "
             "على القناة اللي الأهل كتبوا منها آخر مرة.",
             "<b>One inbox for every channel</b>: WhatsApp, Messenger, "
             "Instagram, Telegram, TikTok and the clinic's e-mail — each "
             "conversation shows its channel, and a reply goes out on the "
             "channel the family last wrote from."),
            ("<b>الشخص بيتعرف من رقمه أو حسابه، عمره ما بيتعرف من اسمه.</b> "
             "المحادثة اللي مش مربوطة بملف بتفضل لوحدها لحد ما تربطها بنفسك "
             "بـ«اربط بملف» — وبعدها كل رسايلها بتنقل على ملف الطفل، والجديد "
             "بيوصل هناك لوحده.",
             "<b>A person is known by their number or account, never by "
             "their name.</b> A conversation not on a file stays apart until "
             "you link it yourself — then all its messages move to the "
             "child's file, and new ones arrive there by themselves."),
            ("<b>قبل ما تكتب الشاشة بتقولك المسموح</b>: ماسنجر وإنستجرام ٢٤ ساعة "
             "من آخر رسالة منهم (وبعدها بس رد موظف لحد ٧ أيام لو العيادة واخدة "
             "موافقة Meta)، تيك توك ١٠ ردود في ٤٨ ساعة، إنستجرام لحد ١٠٠٠ بايت. "
             "و<b>التعليق على بوست</b> ليه رد خاص واحد بس في خلال ٧ أيام — "
             "ومفيش أي كلام طبي في التعليقات العامة.",
             "<b>Before you type, the screen says what is allowed</b>: "
             "Messenger and Instagram 24 hours after their last message (then "
             "only a person's reply for up to 7 days, if the clinic is "
             "approved by Meta), TikTok 10 replies in 48 hours, Instagram up "
             "to 1000 bytes. A <b>comment on a post</b> gets one private "
             "reply within 7 days — and nothing medical in public comments."),
            ("<b>العملاء المحتملين</b> (خدمة العملاء ← «العملاء المحتملين»): كل "
             "حد سأل ولسه ما حجزش، من أي قناة — حتى المكالمة والحضور والتعليق "
             "اللي شفته بإيدك. سجّله بالمصدر والحملة، وحط مسؤول وميعاد "
             "متابعة؛ المتابعة اللي ميعادها فات بتطلع فوق. والتعليق والإعلان "
             "بيعملوه لوحدهم.",
             "<b>Leads</b> (Customer service → «Leads»): everyone who asked "
             "and has not booked, from any channel — even a call, a walk-in "
             "or a comment you saw yourself. Log the source and campaign, "
             "give it an owner and a follow-up date; overdue follow-ups come "
             "first. Comments and ads create them by themselves."),
            ("<b>«حوّله لطلب موعد»</b> بيوديه لنفس طابور الطلبات ونفس موافقة "
             "الدكتور — ومحتاج رقم تليفون. «غير مكتمل» محتاج سبب. وتحت اللوحة: "
             "جم منين، كام اتحوّل، وكام اتحجز فعلاً، لكل قناة ولكل حملة.",
             "<b>«Make a booking request»</b> sends it to the same request "
             "queue and the same doctor approval — and needs a phone number. "
             "«Not completed» needs a reason. Under the board: where they "
             "came from, how many became a request and how many actually "
             "booked, per channel and per campaign."),
            ("<b>الصور والملفات</b> اللي الأهل بيبعتوها على أي قناة بتتحفظ — "
             "مش لينك — ولو الشخص مربوط بملف بتنزل في ملف الطفل ومكتوب عليها "
             "جت منين. و<b>رد خارج المواعيد</b> بيتبعت على نفس القناة مرة كل "
             "١٢ ساعة.",
             "<b>Photos and files</b> families send on any channel are kept — "
             "not a link — and, when the person is on a file, land in the "
             "child's file marked with where they came from. The <b>out-of-"
             "hours reply</b> goes on the same channel once every 12 hours."),
        ],
    },
    {
        "key": "channels_setup",
        "module": "messages",
        "capability": "messages_setup",
        "icon": "plug",
        "title": ("ربط القنوات وصفحة «اطلب موعد»", "Connecting channels, and the request page"),
        "lines": [
            ("<b>القنوات</b> (خدمة العملاء ← «القنوات»): علّم على القنوات اللي "
             "العيادة بتستخدمها بس. القناة اللي مش متربطة بتشتغل تسجيل يدوي "
             "بمصدرها.",
             "<b>Channels</b> (Customer service → «Channels»): tick only the "
             "channels the clinic uses. A channel not connected works as "
             "logging by hand with its source."),
            ("<b>ربط الحسابات</b> (للمدير): تطبيق Meta بتاع العيادة لصفحة فيسبوك "
             "وإنستجرام (مربوط بالصفحة، أو من غير صفحة بتسجيل دخول إنستجرام "
             "ومفتاح بيتجدد لوحده كل ٦٠ يوم)، بوت تليجرام بزرار «اربط تليجرام»، تطبيق "
             "تيك توك باسم المؤسسة («اربط حساب تيك توك» ثم «فعّل استقبال "
             "الرسايل»)، وصندوق الإيميل (IMAP/SMTP بكلمة سر، أو بتسجيل دخول "
             "Google أو Microsoft بتطبيق المؤسسة و«ربط صندوق الإيميل»). "
             "المفاتيح بتتحفظ ومش بتظهر تاني. وكل منصة ليها شروطها مكتوبة جنبها.",
             "<b>Connecting accounts</b> (admin): the clinic's Meta app for "
             "its Facebook Page and Instagram (linked to the Page, or with no "
             "Page through Instagram Login, its key renewed every 60 days), the "
             "Telegram bot with «Connect Telegram», the organisation's own "
             "TikTok app («Connect the TikTok account», then «Turn on "
             "receiving messages»), and the mailbox (IMAP/SMTP with a "
             "password, or by signing in with Google or Microsoft through the "
             "organisation's own app and «Connect the mailbox»). Keys are "
             "saved and never shown again; each platform's conditions are "
             "written beside it."),
            ("<b>صفحة «اطلب موعد» العامة</b>: مقفولة لحد ما تفتحها. بتكتب طلب "
             "في الطابور العادي وبتقول للأهل «طلبك وصل وهنكلمك» — عمرها ما "
             "بتقول «اتحجزلك» — ولو كلامهم فيه طوارئ بتقولهم فوراً يتصلوا أو "
             "يروحوا الطوارئ.",
             "<b>The public «Request an appointment» page</b>: closed until "
             "you open it. It writes a request into the ordinary queue and "
             "tells the family «your request arrived, we will call» — never "
             "«booked» — and if their words sound urgent it tells them at "
             "once to call or go to the emergency department."),
            ("<b>لينكات الحملات</b>: لكل بوست أو إعلان لينك بعلامة مصدر (ومعاه "
             "دكتور لو حبيت)، عشان تقرير العملاء المحتملين يقولك أنهي حملة "
             "جابت حجوزات.",
             "<b>Campaign links</b>: one link per post or ad, with a source "
             "tag (and a doctor if you like), so the leads report says which "
             "campaign brought bookings."),
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
            ("<b>موافقة الطبيب على طلبات الحجز</b>: على صفحة الطبيب المدير "
             "يقدر يخلّيه على قاعدة العيادة، أو «الاستقبال لوحده»، أو "
             "«الاستقبال وبعده الدكتور».",
             "<b>A doctor's approval of booking requests</b>: on the doctor's "
             "page the admin can leave them on the clinic's rule, or set "
             "\"Reception alone\" or \"Reception, then the doctor\"."),
            ("<b>سجل التدقيق</b>: مين عمل إيه وإمتى ومن أي جهاز.",
             "<b>Audit log</b>: who did what, when, and from which device."),
            ("<b>دخول المطوّر</b> (لصاحب المنشأة): حساب المبرمج ما بيدخلش "
             "غير لما إنت تفتح له الباب — لمدة إنت بتحددها وبسبب إنت بتكتبه. "
             "جوّه المدة معاه صلاحياتك، ما عدا حسابات الموظفين ومسح البيانات "
             "واسترجاع نسخة والترخيص والباب نفسه. وكل صفحة وكل حفظ بيتسجّل، "
             "ولما المدة تخلص بيخرج مع أول ضغطة.",
             "<b>Developer access</b> (for the owner): the developer's account "
             "signs in only when you open the door — for a time you choose, "
             "for a reason you write. Inside, it holds your powers, except "
             "staff accounts, wiping data, restoring a backup, the licence and "
             "the door itself. Every page and every save is recorded, and "
             "when the time is up it is signed out on its next click."),
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
            ("<b>التحقق من النسخة</b>: كل نسخة بتتفحص لوحدها أول ما تتعمل — "
             "بتتفتح ويتقرا كل ملف جواها والصور كمان، ويتأكد إن قاعدة البيانات "
             "سليمة وبتاعة البرنامج ده — وجنبها «سليمة» أو «فيها مشكلة» "
             "والسبب، ولما تقف عليها بتقول فيها كام مريض وزيارة وفاتورة وملف. "
             "زرار «تحقق» بيفحص أي نسخة تاني في أي وقت (مثلاً بعد ما ترجّعها "
             "من فلاشة). لو آخر نسخة فيها مشكلة الجرس بيقول للمدير، "
             "والاسترجاع بيرفض النسخة اللي فيها مشكلة قبل ما يلمس الداتا.",
             "<b>Checking a backup</b>: every backup is checked on its own as "
             "soon as it is made — opened, every file in it read, photos "
             "included, and the database checked to be sound and to belong to "
             "this program — and shows «Sound» or «Has a problem» with the "
             "reason; hovering says how many patients, visits, invoices and "
             "files it holds. «Verify» checks any backup again at any time "
             "(for example after bringing it back from a flash drive). If "
             "the latest backup has a problem, the bell tells the "
             "administrator, and a restore refuses a backup with a problem "
             "before touching the data."),
            ("<b>فحص الفلوس بالقرش</b> (أدوات البيانات ← «فحص الفلوس بالقرش»): "
             "كل حساب فلوس في البرنامج بقى بالقرش، والتقريب نص لفوق (١٥٪ من "
             "٠٫٥٠ = ٠٫٠٨)، والمبلغ اللي فيه أكتر من رقمين بعد العلامة بيترفض بدل ما "
             "يتقرّب من غير ما حد يعرف. الشاشة بتدوّر على أي مبلغ متخزن بكسور زيادة "
             "من قبل، وبتتأكد إن القيود مقفولة ومفيش فاتورة متدفع فيها أكتر من "
             "قيمتها؛ و«قرّب للقرش» بياخد نسخة احتياطية قبل وبعد ويسجّل كل رقم اتغير. "
             "والحسابات اللي بالسالب (موظف أو أسرة هيتحاسبوا بعدين) بتتعرض بس وما "
             "بتتغيرش.",
             "<b>Money check to the piastre</b> (Data tools → «Money check to "
             "the piastre»): every money calculation is now done in piastres, "
             "rounded half up (15% of 0.50 = 0.08), and an amount typed with "
             "more than two places after the point is refused instead of being "
             "rounded unseen. The screen looks for any amount stored earlier with "
             "extra decimals, checks that journal entries balance and that no "
             "invoice took more than it came to; «Round to the piastre» takes a "
             "backup before and after and records every figure it changes. "
             "Accounts below zero (staff or a family who will settle later) are "
             "shown only, never changed."),
            ("<b>أنواع الزيارات</b> و<b>الأجهزة</b> وأدوات البيانات — "
             "و<b>منطقة الخطر</b> لمسح كل البيانات (بتتطلب كتابة DELETE).",
             "<b>Visit types</b>, <b>devices</b> and data tools — plus a "
             "<b>danger zone</b> that wipes everything (type DELETE)."),
            ("<b>البيانات التجريبية على الأقسام المفتوحة</b>: «تحميل البيانات "
             "التجريبية» بيحمّل للعيادة، ولكل قسم مفتوح نصيبه — العنابر "
             "والعلامات الحيوية والمعمل والصيدلية والعمليات والأسنان "
             "والنوبتجيات — والقسم المقفول ما بيتحمّلش له حاجة. قسم اتفتح "
             "بعدين؟ الزرار بيبقى «حمّل للأقسام اللي لسه مالهاش» وبيحمّل له "
             "هو بس.",
             "<b>Demo data for the sections you use</b>: \"Load demo data\" "
             "loads the clinic and gives each switched-on section its share "
             "— wards, vital signs, the lab, the pharmacy, theatres, "
             "dentistry and duty rosters — and nothing for a section that is "
             "off. Switched a section on later? The button becomes \"Load "
             "for the sections that have none yet\" and loads for that "
             "section only."),
            ("<b>امسح التجريبية بس</b>: بيشيل اللي التحميل عمله بالظبط، "
             "والحقيقي بيفضل مكانه؛ وصف تجريبي اتبنى عليه شغل حقيقي بيتساب "
             "ويتقال إنه اتساب. وبيانات تجريبية اتحمّلت في نسخة قديمة، قبل "
             "ما البرنامج يسجّل اللي بيحمّله؟ «دوّر على البيانات التجريبية "
             "القديمة» (لصاحب المنشأة) بيلاقيها من لحظة التحميل في سجل "
             "النشاط، <b>وبيعرض اللي لقاه قبل ما حاجة تتمسح</b>.",
             "<b>Remove the demo data only</b>: removes exactly what loading made, "
             "and the real data stays; a demo row that real work is built on "
             "is kept and reported. Demo data loaded by an older version, "
             "before the program recorded what it loads? \"Find the old demo "
             "data\" (for the owner) finds it from the moment it was loaded "
             "in the activity log, <b>and shows what it found before anything "
             "is removed</b>."),
            ("<b>مستشفى على جهاز واحد</b>: <code>WORKERS=4</code> في ملف "
             "<code>clinic.env</code> بيشغّل البرنامج على أربع عمليات بدل "
             "واحدة، فالأنوية كلها بتشتغل والشاشات ما بتبطّأش لما الناس "
             "تكتر. من غيره البرنامج شغّال زي ما هو. اتجرّب على لينكس؛ "
             "قبل ما مستشفى تعتمد عليه على ويندوز، الفني يعمل التجربة اللي "
             "في دليل التشغيل على أكتر من عملية.",
             "<b>A hospital on one machine</b>: <code>WORKERS=4</code> in "
             "<code>clinic.env</code> runs the program as four processes "
             "instead of one, so every core works and the screens stay quick "
             "as people are added. Without it the program runs exactly as "
             "before. Tested on Linux; before a hospital relies on it on "
             "Windows, the technician runs the check in the more-than-one-"
             "process guide."),
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
    "complaints_manage": ("متابعة الشكاوى والرد عليها وقفلها",
                          "Handle, answer and close complaints"),
    "incident_manage": ("مراجعة بلاغات الحوادث وتصنيفها والتحقيق فيها وقفلها",
                        "Classify, investigate and close incident reports"),
    "infection_control": ("مكافحة العدوى: تنبيه الميكروبات المنذرة والرد عليه، وتقارير نظافة الأيدي",
                          "Infection control: alert organisms and their answer, and hand-hygiene reports"),
    "antimicrobial_stewardship": ("ترشيد المضادات الحيوية: الموافقة على المقيّد والمراجعة بعد المزرعة",
                                  "Antimicrobial stewardship: restricted approvals and post-culture review"),
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
