"""What this program is, who made it, and what is honestly still missing.

The About page used to hold three facts: the product name, the version, and the
licence line. That is a credit, not an answer. The people who ask "what is this
thing, and where is it going?" are the clinic's own staff and whoever is being
shown it — and the honest answer already existed, spread across ``ROADMAP.md``
and half a dozen plan files that nobody in a clinic will ever open.

So the roadmap lives here, in the program, next to the thing it describes.

Two rules kept it from becoming a brochure:

* **The figures are counted, not typed.** :func:`facts` reads the database and
  the shipped reference files every time. A number in a marketing paragraph
  rots the day after it is written; a number that is counted cannot.
* **What is deferred is published too.** ``DEFERRED`` is the most useful
  section of any roadmap and the one always left out. A clinic deciding
  whether to rely on this needs to know that device integration and multi-branch
  are *decisions*, not oversights.

The people section is editable from the page itself (admins only) rather than
hard-coded, because the supervising doctor differs per installation and no
biography of a real person belongs in a source file.
"""
from app.models.setting import Setting

# The developer's credit already existed as the copyright line; this is the
# same person, said properly rather than in 0.64rem type down the side.
DEVELOPER_DEFAULTS = {
    "name": ("م. محمد خفاجة", "Eng. Mohamed Khafaga"),
    "role": ("تصميم وتطوير النظام بالكامل",
             "Design and development of the entire system"),
}

# Settings keys backing the editable people section.
KEYS = [
    "about_developer_note",
    "about_developer_contact",
    "about_supervisor_name",
    "about_supervisor_title",
    "about_supervisor_note",
]

SUMMARY = (
    "نظام إدارة عيادة أطفال متكامل: الملف الطبي والزيارة والنمو والتطعيمات "
    "والروشتة، والدورة المالية والمخزنية، وخدمة المرضى على واتساب — عربي "
    "وإنجليزي بالكامل، ويشتغل على جهاز العيادة نفسه بدون إنترنت في أغلب "
    "شاشاته.",
    "An integrated paediatric clinic system: the medical file, the visit, "
    "growth, vaccinations and prescribing, the financial and inventory "
    "cycles, and patient service over WhatsApp — fully Arabic and English, "
    "and running on the clinic's own machine without internet for most of "
    "its screens.",
)

# Principles the code is actually held to — each one is visible in the program,
# which is the only reason any of them is listed.
PRINCIPLES = [
    ("عربي أولاً", "Arabic first",
     "كل شاشة وكل مطبوعة بالعربي والإنجليزي، RTL أصلي مش ترجمة مقلوبة.",
     "Every screen and every printout in Arabic and English, with real RTL "
     "rather than a mirrored translation."),
    ("بيانات العيادة عند العيادة", "The clinic's data stays at the clinic",
     "قاعدة البيانات على جهاز العيادة، والنسخ الاحتياطي والاستعادة من داخل "
     "البرنامج.",
     "The database lives on the clinic's machine, and backup and restore run "
     "from inside the program."),
    ("كل رقم طبي له مصدر", "Every clinical number carries its source",
     "جرعات المرجع الدوائي بتذكر مرجعها، لأن الجرعة اللي على الشاشة "
     "بتتصدّق.",
     "Doses in the drug reference name their reference, because a dose on a "
     "screen is believed."),
    ("الإعداد من الشاشة", "Configured from the screen",
     "الأدوار والخدمات والقوالب والموديولات بتتظبط من الواجهة، من غير تعديل "
     "ملفات.",
     "Roles, services, templates and modules are all set from the interface, "
     "with no file editing."),
]

DONE = [
    ("الملف الطبي والزيارة مع ICD-10 كامل أوفلاين وتنبيهات الأمان",
     "The medical file and the visit, with the whole of ICD-10 offline and "
     "safety alerts"),
    ("مخططات النمو WHO و CDC بقيم LMS الرسمية",
     "WHO and CDC growth charts from the official LMS tables"),
    ("التطعيمات: جدول لكل طفل، صرف من المخزن FEFO، شهادة، ومتابعة الالتزام",
     "Vaccinations: a schedule per child, FEFO stock issue, a certificate and "
     "compliance tracking"),
    ("الروشتة والمرجع الدوائي وكتالوج الأدوية المصري مع حاسبة الجرعة بالوزن",
     "Prescribing, the drug reference and the Egyptian register with a "
     "weight-based dose calculator"),
    ("الدورة المالية: فاتورة واحدة للزيارة، كاشير بورديات، عمولات، جهات "
     "ومطالبات، وفترات مقفولة",
     "The financial cycle: one invoice per visit, a cashier with shifts, "
     "commissions, payers and claims, and closed periods"),
    ("المخزون المستندي: أذون، تحويلات، جرد، مشتريات وموردين وكارت صنف",
     "Document-driven inventory: receipts, transfers, stocktakes, purchasing, "
     "suppliers and item cards"),
    ("خدمة المرضى على واتساب: قوالب موحّدة، جدولة وحدود إرسال، صندوق وارد، "
     "واستبيان رضا وتحليلاته",
     "Patient service over WhatsApp: unified templates, scheduling and "
     "sending limits, an inbox, and a satisfaction survey with its analysis"),
    ("الفاتورة الإلكترونية المصرية (وضع تجريبي وحقيقي)",
     "Egyptian e-invoicing (demo and live modes)"),
    ("النسخ الاحتياطي والاستعادة من داخل البرنامج",
     "Backup and restore from inside the program"),
    ("هوية المنشأة، معالج أول تشغيل، وتفعيل/تعطيل الموديولات",
     "Facility identity, a first-run wizard, and modules that switch on and "
     "off"),
    ("المساعد الذكي داخل الزيارة مع عداد استهلاك بدون تخزين نصوص أو بيانات مريض",
     "The AI assistant inside the visit, metered without storing text or "
     "patient data"),
    ("سجل تدقيق كامل، أدوار وصلاحيات تتعدّل من الشاشة، وطباعة A4 لكل التقارير",
     "A full audit log, roles and permissions edited from the screen, and A4 "
     "printing across every report"),
]

BUILDING = [
    ("استقبال رسائل واتساب من المزوّدين (Meta / WaPilot) — المنطق جاهز "
     "ومحتاج رابط عام للعيادة",
     "Receiving WhatsApp messages from the providers (Meta / WaPilot) — the "
     "logic is ready and needs a public URL for the clinic"),
    ("توسيع تغطية الجرعات في المرجع الدوائي مادة بمادة، كل واحدة بمرجعها",
     "Widening dose coverage in the drug reference one ingredient at a time, "
     "each with its source"),
    ("استيراد ICD-11 من WHO باعتمادات العيادة — الخيار بيظهر للطبيب لما "
     "البيانات توصل فعلاً",
     "Importing ICD-11 from WHO with the clinic's own credentials — the option "
     "appears to the doctor only once the data is actually there"),
    ("استيراد التاريخ السابق (زيارات وأرصدة قديمة) على دفعات قابلة للتراجع",
     "Importing history (old visits and balances) in batches that can be "
     "rolled back"),
]

NEXT = [
    ("المحرك المحاسبي: شجرة حسابات وقيود تلقائية ومراكز تكلفة",
     "The accounting engine: a chart of accounts, automatic entries and cost "
     "centres"),
    ("كشف حساب المريض وأعمار الديون بشكل أعمق",
     "A patient statement of account, and deeper AR ageing"),
    ("الباقات (كشف + إجراء + تطعيم بسعر باقة) كتعريف من الشاشة",
     "Service packages (consultation + procedure + vaccine at a package "
     "price), defined from the screen"),
    ("قوالب القياس ونتائج الأجهزة بإدخال يدوي وتقرير مطبوع",
     "Measurement templates and device results, entered by hand and printed "
     "as a report"),
    ("لوحة التزام التطعيمات على مستوى العيادة كلها",
     "A clinic-wide vaccination compliance board"),
    ("إيصال حراري 58/80mm للتحصيل السريع",
     "A 58/80mm thermal receipt for fast collection"),
    ("جاهزية FHIR: endpoints قراءة فقط للمريض والزيارة والتطعيم والقياسات",
     "FHIR readiness: read-only endpoints for patient, encounter, "
     "immunisation and observations"),
]

# The section every roadmap leaves out. These are decisions, not gaps.
DEFERRED = [
    ("تكامل الأجهزة الفعلي (SDK/LAN) — النتائج دلوقتي بإدخال يدوي ومرفقات",
     "Real device integration (SDK/LAN) — results are entered by hand with "
     "attachments for now"),
    ("HL7 / DICOM والتكامل الكتابي مع الأنظمة الخارجية",
     "HL7 / DICOM and write integration with external systems"),
    ("تعدد الفروع والشركات بالكامل",
     "Full multi-branch and multi-company"),
    ("بوابة مريض وحجز أونلاين — محتاجة موقع عام واستضافة",
     "A patient portal and online booking — needs a public site and hosting"),
    ("تطبيق موبايل و SaaS والكشف عن بُعد",
     "A mobile app, SaaS and telemedicine"),
]


def people():
    """The developer and (if the clinic filled it in) the medical supervisor.

    Read from settings so no real person's biography is compiled into the
    program. The developer's name is the one constant — it is the copyright
    holder — and everything else is the clinic's to write.
    """
    supervisor_name = (Setting.get("about_supervisor_name") or "").strip()
    return {
        "developer": {
            "name": DEVELOPER_DEFAULTS["name"],
            "role": DEVELOPER_DEFAULTS["role"],
            "note": (Setting.get("about_developer_note") or "").strip(),
            "contact": (Setting.get("about_developer_contact") or "").strip(),
        },
        "supervisor": {
            "name": supervisor_name,
            "title": (Setting.get("about_supervisor_title") or "").strip(),
            "note": (Setting.get("about_supervisor_note") or "").strip(),
        } if supervisor_name else None,
    }


def save_people(form):
    """Persist the editable people fields. Blank clears a field."""
    for key in KEYS:
        Setting.set(key, (form.get(key) or "").strip())


def facts():
    """Counted, never typed.

    Each of these is read at render time from the database or from the
    reference files that ship with the program, so the page cannot drift from
    what the installation actually holds. A figure written by hand into a
    template is true on the day it is written and misleading afterwards.
    """
    from app.models import Drug, GenericDrug, Patient, Role
    from app.models.permissions import MODULES
    from app.utils.facility import enabled_modules
    from app.utils.icd import coverage

    def count(model):
        try:
            return model.query.count()
        except Exception:  # noqa: BLE001 — a fact page never breaks a screen
            return None

    icd = coverage()
    return {
        "modules_total": len(MODULES),
        "modules_enabled": len(enabled_modules()),
        "roles": count(Role),
        "patients": count(Patient),
        "drugs": count(Drug),
        "generics": count(GenericDrug),
        "icd10": icd.get("10", {}).get("total", 0),
        "icd11": icd.get("11", {}).get("total", 0),
    }
