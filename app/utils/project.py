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
hard-coded, because the doctors a clinic credits differ per installation and no
biography of a real person belongs in a source file. Each of them carries both
languages: this page is read in Arabic by the clinic and in English by whoever
is being shown the system, and one string cannot serve both.
"""
from app.models.setting import Setting

# The developer's credit already existed as the copyright line; this is the
# same person, said properly rather than in 0.64rem type down the side.
DEVELOPER_DEFAULTS = {
    "name": ("م. محمد خفاجة", "Eng. Mohamed Khafaga"),
    "role": ("تصميم وتطوير النظام بالكامل",
             "Design and development of the entire system"),
}

# Settings keys backing the developer block. The note is a pair like every
# other piece of writing on this page: the Arabic screen must not print an
# English paragraph at an Arabic reader, and the reverse. The contact is a
# single field on purpose — an email address and a phone number are the same
# in both languages, and asking for them twice invites them to disagree.
KEYS = [
    "about_developer_note",
    "about_developer_note_en",
    "about_developer_contact",
]

# The single supervisor these three keys used to hold now lives in the
# ``about_people`` table. They are read once, carried over, and cleared —
# see :func:`carry_over_supervisor`.
LEGACY_SUPERVISOR_KEYS = [
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
    """The developer, and whichever doctors the clinic chose to credit.

    Read from settings and the ``about_people`` table so no real person's
    biography is compiled into the program. The developer's name is the one
    constant — it is the copyright holder — and everything else is the
    clinic's to write.
    """
    from app.models.about_person import (AboutPerson, initial_of,
                                         photo_path_of)

    try:
        doctors = (AboutPerson.query
                   .order_by(AboutPerson.sort_order, AboutPerson.id).all())
    except Exception:  # noqa: BLE001 — a credits list never breaks the page
        doctors = []

    return {
        "developer": {
            "name": DEVELOPER_DEFAULTS["name"],
            "role": DEVELOPER_DEFAULTS["role"],
            "note": ((Setting.get("about_developer_note") or "").strip(),
                     (Setting.get("about_developer_note_en") or "").strip()),
            "contact": (Setting.get("about_developer_contact") or "").strip(),
            "photo": (Setting.get("about_developer_photo") or "").strip(),
            "photo_path": photo_path_of(Setting.get("about_developer_photo")),
            # A pair, like the name it is taken from, so the circle follows
            # whichever language the page is being read in.
            "initial": tuple(initial_of(n) for n in DEVELOPER_DEFAULTS["name"]),
        },
        "doctors": doctors,
    }


def save_people(form, files=None):
    """Persist the developer block. Blank clears a field."""
    for key in KEYS:
        Setting.set(key, (form.get(key) or "").strip())

    current = (Setting.get("about_developer_photo") or "").strip()
    saved = save_photo((files or {}).get("photo"))
    if saved:
        drop_photo(current)
        Setting.set("about_developer_photo", saved)
    elif form.get("drop_photo"):
        drop_photo(current)
        Setting.set("about_developer_photo", "")


# ---------------------------------------------------------------- photographs
#
# A photograph of a person is a raster image, so SVG is not on this list even
# though the staff-photo upload elsewhere allows it: an SVG is a document that
# can carry script, and nothing here needs one.
ALLOWED_PHOTO = {"png", "jpg", "jpeg", "webp", "gif"}


def _photo_dir():
    """``static/uploads/about`` — kept apart from the staff photo folder.

    These are two different things that happen to both be pictures of people:
    one identifies a user who signs in, the other is a credit on a public-ish
    page. Mixing them means deleting a credit can reach a staff file.
    """
    import os

    from flask import current_app

    path = os.path.join(current_app.static_folder, "uploads", "about")
    os.makedirs(path, exist_ok=True)
    return path


def save_photo(storage):
    """Store an uploaded photo and return its filename, or None."""
    import os
    import uuid

    from werkzeug.utils import secure_filename

    if not storage or not getattr(storage, "filename", ""):
        return None
    name = storage.filename
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_PHOTO:
        return None
    stored = f"{uuid.uuid4().hex}.{ext}"
    storage.save(os.path.join(_photo_dir(), secure_filename(stored)))
    return stored


def drop_photo(name):
    """Delete a stored photo. Silent when it is already gone."""
    import os

    if not name:
        return
    path = os.path.join(_photo_dir(), name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:      # a locked or read-only file is not worth a 500
            pass


# Fields a person row carries, in the order the form asks for them.
PERSON_FIELDS = ["name", "name_en", "title", "title_en", "note", "note_en"]


def _read_person(form, person, files=None):
    """Copy the submitted fields onto a row. Blank clears; Arabic name stays."""
    for field in PERSON_FIELDS:
        value = (form.get(field) or "").strip()
        # The Arabic name is the one thing that cannot be emptied — a row
        # without it would be a person with no name on the Arabic page, which
        # is every page in this clinic by default.
        if field == "name" and not value:
            continue
        setattr(person, field, value or None)
    try:
        person.sort_order = int(form.get("sort_order") or 0)
    except (TypeError, ValueError):
        person.sort_order = 0

    # Who they are in the program, when they are anybody. Blank is a real
    # answer and the commonest one — a supervising professor, the clinic's
    # owner, somebody who helped once — so it clears the link rather than
    # being ignored. An id that names nobody clears it too, instead of
    # leaving a row pointing at a user that is not there.
    person.user_id = _staff_id(form.get("user_id"))

    # A new upload replaces the old file rather than orphaning it, and the
    # checkbox is the only way back to no photo at all — an empty file input
    # means "I did not choose a new one", never "remove the one there is".
    saved = save_photo((files or {}).get("photo"))
    if saved:
        drop_photo(person.photo)
        person.photo = saved
    elif form.get("drop_photo"):
        drop_photo(person.photo)
        person.photo = None
    return person


def _staff_id(value):
    """A user id from the form, or None — and None for anything that is not
    a user this installation actually has."""
    from app.extensions import db
    from app.models import User

    try:
        user_id = int(value)
    except (TypeError, ValueError):
        return None
    return user_id if db.session.get(User, user_id) is not None else None


def creditable_staff():
    """Everybody who could be picked from the program's own users.

    Deliberately not "doctors": a clinic credits its matron, its lab
    supervisor and its manager as readily as its paediatricians, and a filter
    that decided for them would send them back to typing.
    """
    from app.models import User

    try:
        return (User.query.filter_by(is_active=True)
                .order_by(User.full_name).all())
    except Exception:  # noqa: BLE001 — a credits form never breaks the page
        return []


def add_person(form, files=None):
    """Add a credited person. Returns the row, or None if unnamed."""
    from app.extensions import db
    from app.models.about_person import AboutPerson

    if not (form.get("name") or "").strip():
        return None
    person = _read_person(form, AboutPerson(name=(form.get("name")).strip()),
                          files)
    db.session.add(person)
    return person


def _person(person_id):
    """Look one up by the id a form posted — a string, or nothing at all."""
    from app.extensions import db
    from app.models.about_person import AboutPerson

    try:
        return db.session.get(AboutPerson, int(person_id))
    except (TypeError, ValueError):
        return None


def edit_person(person_id, form, files=None):
    person = _person(person_id)
    if person is None:
        return None
    return _read_person(form, person, files)


def delete_person(person_id):
    from app.extensions import db

    person = _person(person_id)
    if person is not None:
        # The row is going; leaving its picture on disk would leave a face in
        # the uploads folder that nothing in the program can reach or remove.
        drop_photo(person.photo)
        db.session.delete(person)
    return person


def carry_over_supervisor():
    """Move the old single supervisor into the new table, once.

    Whatever the clinic typed into the three ``about_supervisor_*`` settings
    is a real person they chose to credit; a schema change is not a reason for
    it to disappear from their page. Runs from ``apply_schema``, does nothing
    once the keys are cleared, and refuses to run at all if the table already
    has rows — so it cannot resurrect somebody who was deliberately deleted.

    Returns True when a row was created.
    """
    from app.extensions import db
    from app.models.about_person import AboutPerson

    name = (Setting.get("about_supervisor_name") or "").strip()
    if not name:
        return False
    if AboutPerson.query.first() is not None:
        for key in LEGACY_SUPERVISOR_KEYS:
            Setting.set(key, "")
        return False

    db.session.add(AboutPerson(
        name=name,
        title=(Setting.get("about_supervisor_title") or "").strip() or None,
        note=(Setting.get("about_supervisor_note") or "").strip() or None,
        sort_order=0,
    ))
    for key in LEGACY_SUPERVISOR_KEYS:
        Setting.set(key, "")
    return True


# --- the credits that ship with the program --------------------------------
#
# The page used to open **empty** on a fresh install: the developer's name and
# role are constants (they are the copyright holder), and everything under them
# — the two biographies, the contact, the photographs, and the doctor beside
# them — was the clinic's to type. So every new install showed two headings and
# nothing beneath them until somebody sat down and wrote it out.
#
# Asked for in one line: *«أنا عايز أضيف الاتنين دول في أي نسخة وأعدّل عليهم
# وقت ما أحب»*.
#
# **Seeded, not compiled.** The distinction is the whole of it and the file
# already made it once: a biography written into the source is a paragraph the
# clinic cannot touch, and this program's rule is that what is on a screen is
# editable from that screen. These land as ordinary rows and settings, they go
# through the same edit form as anything typed by hand, and deleting one is a
# decision the clinic is allowed to make.
#
# **Which is why it runs once and remembers.** A seed that re-ran would put a
# deleted person back on every update, and the migration beside it already
# refuses to do exactly that: *"cannot resurrect somebody who was deliberately
# deleted"*. The flag is what keeps that promise while still letting the seed
# reach an existing clinic that never had these rows.
CREDITS_SEEDED_KEY = "about_credits_seeded"

DEVELOPER_SEED = {
    "about_developer_note":
        "مدير تكنولوجيا المعلومات والعمليات، يتمتع بخبرة واسعة تزيد عن 20 عاماً "
        "في إدارة وتشغيل المستشفيات، وتحديداً في قطاع رعاية الأطفال. حاصل على "
        "دبلوم في الإدارة المتكاملة للمستشفيات عام 2016، يجمع بين الفهم العميق "
        "لبيئة العمل الطبي والقيادة التكنولوجية لتصميم البنية التحتية وتطوير "
        "أنظمة متقدمة لإدارة العيادات لرفع الكفاءة التشغيلية.",
    "about_developer_note_en":
        "IT and Operations Manager with over 20 years of specialized experience "
        "in hospital operations, specifically within pediatric healthcare. "
        "Holding a Diploma in Integrated Hospital Management (2016), he combines "
        "deep healthcare domain knowledge with technology leadership to design "
        "robust IT infrastructures and develop highly customized, user-centric "
        "clinic management systems.",
    "about_developer_contact": "kids_khafaga@msn.com | +20 109 162 6165",
    "about_developer_photo": "img/about/khafaga.jpg",
}

#: The doctors credited by default. A list, because the reason
#: ``about_people`` is a table at all is that a clinic has more than one.
DOCTOR_SEED = [
    {
        "name": "أحمد جمال قنديل",
        "name_en": "Ahmed Gamal Kandil",
        "title": "استشاري طب الأطفال وحديثي الولادة",
        "title_en": "Consultant Pediatrician and Neonatologist",
        "note":
            "ساهم د/ أحمد جمال بشكل محوري في تطوير الجانب الإكلينيكي للنظام. "
            "قدّم الرؤية الطبية الدقيقة لتصميم نظام التطعيمات المتكامل، "
            "بالإضافة إلى توجيه المسارات السريرية الخاصة بحديثي الولادة "
            "والأطفال المبتسرين، مما عزّز من كفاءة وموثوقية البرنامج لخدمة "
            "الأطباء والمرضى.",
        "note_en":
            "Dr. Ahmed Gamal provided instrumental clinical guidance in the "
            "development of PediaPro. He played a key role in designing the "
            "comprehensive vaccination module and formulating precise clinical "
            "workflows for neonates and premature infants, significantly "
            "enhancing the system's medical reliability.",
        "photo": "img/about/kandil.jpg",
        "sort_order": 0,
    },
]


def shipped_photo(value):
    """``value`` when that file is actually in the build, else ``None``.

    A seeded row pointing at a picture that is not there draws a **broken
    circle**, which is worse than the initial it was meant to replace — the
    model already says so: *"a person without one gets their initial rather
    than a hole where a face should be"*. So the seed only claims a photograph
    it can see on disk, and the day the files are added they are picked up
    with no other change.
    """
    import os

    if not value:
        return None
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "static", *value.split("/"))
    return value if os.path.exists(path) else None


def seed_credits():
    """Put the shipped credits in, once, and never over anything.

    Returns ``{"developer": n, "doctors": n}`` — how many fields and rows it
    actually created, which is zero on every run after the first.
    """
    from app.extensions import db
    from app.models.about_person import AboutPerson

    if (Setting.get(CREDITS_SEEDED_KEY) or "") == "1":
        return {"developer": 0, "doctors": 0}

    filled = 0
    for key, value in DEVELOPER_SEED.items():
        if key.endswith("_photo"):
            value = shipped_photo(value)
            if not value:
                continue
        # Only where the clinic has written nothing. A note somebody typed is
        # theirs, and a first run that overwrote it would be the one thing this
        # must never do.
        if not (Setting.get(key) or "").strip():
            Setting.set(key, value)
            filled += 1

    added = 0
    for row in DOCTOR_SEED:
        exists = AboutPerson.query.filter_by(name=row["name"]).first()
        if exists is None:
            db.session.add(AboutPerson(**dict(row,
                                              photo=shipped_photo(row["photo"]))))
            added += 1

    Setting.set(CREDITS_SEEDED_KEY, "1")
    db.session.flush()
    return {"developer": filled, "doctors": added}


def support():
    """What somebody needs to know before they can help — counted, never asked.

    The first three questions in every support conversation are the same:
    which version, what is enabled, how much data. Nobody in a clinic can
    answer the second and third, and the answer to the first is usually "the
    new one". So they are gathered here, on the screen a person is already
    looking at when something is wrong, in a block they can copy into one
    message.

    The schema fingerprint is the reason this exists at all rather than being
    a nicety. ``version.py`` was written because of a real report — *"I
    restored a backup and got a load of problems"* — where the restore was
    fine and the schema behind it was a version old. That number is computed,
    goes into every archive, and until now appeared on no screen a person
    opens when something has gone wrong.

    Nothing here is a secret and nothing here is a patient. No filesystem
    paths, no passphrase, no names — a block meant to be pasted into WhatsApp
    has to be safe to paste into WhatsApp.

    Every line is wrapped, because a support panel that raises is a support
    panel that is missing exactly when it is needed.
    """
    import platform
    import sys

    from app.utils.version import (APP_VERSION, schema_generation,
                                   schema_version)

    def safe(fn, fallback=None):
        try:
            return fn()
        except Exception:  # noqa: BLE001 — see the docstring
            return fallback

    def db_size_mb():
        import os

        from app.utils.backups import db_path

        path = db_path()
        if not path or not os.path.isfile(path):
            return None
        return round(os.path.getsize(path) / (1024 * 1024), 1)

    def backup():
        from datetime import date

        from app.utils.backups import last_backup_at

        when = last_backup_at()
        if when is None:
            return {"at": None, "days": None}
        return {"at": when.strftime("%Y-%m-%d"),
                "days": (date.today() - when.date()).days}

    def modules():
        from app.models.permissions import MODULES
        from app.utils.facility import enabled_modules

        return f"{len(enabled_modules())}/{len(MODULES)}"

    def counted(model_name):
        from app import models

        return getattr(models, model_name).query.count()

    return {
        "app_version": APP_VERSION,
        "schema": safe(schema_version),
        "generation": safe(schema_generation),
        "python": sys.version.split()[0],
        "platform": safe(lambda: f"{platform.system()} {platform.release()}"),
        "db_mb": safe(db_size_mb),
        "backup": safe(backup, {"at": None, "days": None}),
        "modules": safe(modules),
        "patients": safe(lambda: counted("Patient")),
        "visits": safe(lambda: counted("Visit")),
        "users": safe(lambda: counted("User")),
    }


def support_lines(data=None):
    """The support block as plain text, one fact per line.

    Built here rather than in the template so that what is copied and what is
    shown cannot drift apart — they are the same list, rendered twice.
    """
    d = data or support()
    backup = d.get("backup") or {}
    if backup.get("at"):
        when = f"{backup['at']} ({backup['days']}d ago)"
    else:
        when = "never"
    return [
        f"PediaPro {d['app_version']}",
        f"schema {d['schema']} · gen {d['generation']}",
        f"python {d['python']} · {d['platform']}",
        f"modules {d['modules']}",
        f"db {d['db_mb']} MB" if d['db_mb'] is not None else "db —",
        f"last backup {when}",
        f"patients {d['patients']} · visits {d['visits']} · users {d['users']}",
    ]


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
