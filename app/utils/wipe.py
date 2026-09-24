"""إيه اللي بيتمسح لما حد يقول «امسح البيانات» — **ومحسوب مش مكتوب**.

`reset_all` كانت قايمة مكتوبة بالإيد اتكتبت أول ما البرنامج بدأ، وما
اتزوّدتش بعد كده. والنتيجة اتقاست بالتشغيل مش بالقراية:

    ADMISSION SURVIVED: True
    POINTS AT PATIENT: 1   WHICH EXISTS: False

**يعني المريض بيتمسح والإقامة بتفضل بتشاور عليه** — وده بالظبط اللي
دوكسترينج نفس الدالة بيحذّر منه: *"orphans would later crash page loads
after a reset"*. ولما عدّينا، **٥٤ جدول بيتكلم عن طفل كان بره القايمة**:
الملاحظات، وتقييمات الخطر، والتقييد، والإنعاش، والأوامر الشفهية،
والرفض، والقساطر، والاستشارات، والتغذية، والألم، وتقييم التمريض،
والمسؤولية، والإحالات، وملخصات الخروج.

---

**فالقايمة اتشالت.** القاعدة دلوقتي:

* **بيتمسح**: كل صف بيتكلم عن طفل (فيه `patient_id` أو بيوصل لمريض عبر
  زيارة أو إقامة)، **وزيادة** عليه شغل تشغيلي مالوش مريض (مصاريف،
  أوامر شراء، حركة مخزن، رسايل، ورديّات الخزنة).
* **بيعيش**: الكتالوجات والإعدادات — المستخدمين والأدوار والخدمات
  والأصناف والأدوية والتطعيمات والقوايم.
* **والترتيب متحسب من المفاتيح الأجنبية**, الابن قبل الأب — مش مكتوب
  بالإيد كمان، لأن ترتيب غلط بيفشّل المسح نفسه.

**والفايدة إن العبء اتقلب**: جدول إكلينيكي جديد بيتمسح **من غير ما حد
يعدّل حاجة**. الكتالوج الجديد هو اللي محتاج سطر في :data:`KEEP` —
والحارس بيوقف اللي بينسى.
"""
from collections import defaultdict

from app.extensions import db

#: **الجداول اللي بتعيش المسح.** كتالوجات وإعدادات، مش شغل يومي.
#:
#: مكتوبة بالاسم عن قصد: مسح قايمة أسعار عيادة أسوأ بكتير من سيبان صف
#: تجريبي، فالسكوت هنا لازم يكون في ناحية «ما تمسحش».
KEEP = {
    # مين بيشتغل، وإيه صلاحيته.
    "users", "roles", "user_capabilities", "clinical_privileges",
    "doctor_schedules", "duty_roles", "duty_rates",
    # إعدادات البرنامج والمنشأة.
    "settings", "about_people", "clinic_rooms", "nursing_stations",
    "theatres", "warehouses", "lookups", "panel_alert_rules",
    # الكتالوجات اللي العيادة بتبيع وبتصرف منها.
    "services", "service_types", "service_packages", "service_bundle_items",
    "service_consumables", "doctor_service_commissions", "doctor_case_rates",
    "store_items", "invoice_sections", "visit_types", "case_types",
    "client_categories", "named_discounts", "payer_types", "payer_entities",
    "payer_service_rates", "payer_contracts", "payer_contract_rates",
    # المراجع الدوائية والتطعيمات — دي بتتحمّل مرة وبتاخد وقت.
    "drugs", "drug_classes", "drug_interactions", "generic_drugs",
    "generic_dose_bands", "high_alert_drugs", "lasa_pairs",
    "vaccines", "vaccine_brands", "vaccine_brand_doses",
    "vaccine_schedule_templates", "vaccine_schedule_doses",
    # القوالب والاختصارات اللي العيادة كتبتها.
    "message_templates", "quick_replies", "rx_presets", "rx_preset_items",
    "rx_print_templates", "abbreviations", "investigations",
    "medical_devices", "accounts", "accounting_periods", "cash_accounts",
    "import_batches",
    # `IMT.07` — مدد الحفظ سياسة العيادة، ودفتر الإتلاف بيحكي عن ورق
    # اتعدم فعلاً برّه البرنامج. «امسح البيانات» بيبدأ الشغل من جديد، ما
    # بيمحيش إن الورق ده اتعدم.
    "retention_rules", "record_destructions",
    # `SAS.11` — قايمة الغرسات بتاعة المستشفى: كتالوج، زي الخدمات.
    "implant_devices",
}

#: شغل تشغيلي مالوش `patient_id` ولا بيوصل لمريض — بس مش كتالوج.
#:
#: **وتخطيط المستشفى نفسه مش هنا عن قصد.** `care_units` و`care_spaces`
#: و`care_beds` بتعيش المسح: دي المبنى، مش الشغل اللي حصل فيه. مستشفى
#: ضغطت «امسح البيانات» عايزة تبدأ نضيفة، مش تعيد بناء العنابر.
OPERATIONAL = {
    "message_logs", "expenses", "purchase_orders", "purchase_order_items",
    "stock_movements", "store_documents", "suppliers",
    "supplier_payments", "supplier_installments",
    "cash_drawer_days", "cashier_shifts", "cash_movements", "cash_counts",
    "bank_statement_lines", "doctor_settlements",
    "journal_entries", "journal_lines",
    "schedule_exceptions", "waitlist_entries", "activity_log",
    # **والعائلات.** مفيش مفتاح بينزل منها لمريض — المريض هو اللي
    # بيشاور عليها — فالقاعدة الآلية كانت هتسيبها، وهي بيانات ناس
    # حقيقيين مش كتالوج.
    "families",
    "ai_usage", "vaccine_inventory", "vaccine_adjustments",
    "doctor_payouts", "refund_requests", "refund_notices",
    "record_reviews", "record_review_members", "record_review_findings",
    "duty_slots", "duties", "room_assignments", "feedback", "conversations",
    "claims", "claim_items",
    # `SAS.11` — إشعار استدعاء مالوش مريض بنفسه؛ الاتصالات بالأسر بتوصل
    # لمريض عن طريق الغرسة وبتتمسح لوحدها.
    "implant_recalls",
}


def _tables():
    """كل جدول البرنامج بيعرفه، باسمه وبأعمدته."""
    import app.models as models

    out = {}
    for name in dir(models):
        table = getattr(getattr(models, name), "__table__", None)
        if table is not None:
            out[table.name] = table
    return out


def about_a_patient(table, tables, seen=None):
    """الصف ده بيتكلم عن طفل — **حتى لو بعيد بخطوتين**.

    `PainAssessment` مثلاً مالهاش `patient_id`... لأ عندها؛ إنما
    `SurgicalCountItem` بتوصل للمريض عبر العملية. فالسؤال بيتبع
    المفاتيح لحد ما يلاقي `patients` أو `visits` أو `admissions`.
    """
    seen = seen if seen is not None else set()
    if table.name in seen:
        return False
    seen.add(table.name)
    for column in table.columns:
        for fk in column.foreign_keys:
            parent = fk.column.table.name
            if parent in ("patients", "visits", "admissions", "families"):
                return True
            other = tables.get(parent)
            if other is not None and about_a_patient(other, tables, seen):
                return True
    return False


def wiped_tables():
    """أسامي الجداول اللي المسح بيفضّيها."""
    tables = _tables()
    return {name for name, table in tables.items()
            if name not in KEEP
            and (name in OPERATIONAL or about_a_patient(table, tables))}


def _edges(tables):
    """(ابن، أب، العمود) لكل مفتاح أجنبي بين جدولين مختلفين."""
    out = []
    for name, table in tables.items():
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent != name:
                    out.append((name, parent, column))
    return out


def cycle_breakers(tables=None, wanted=None):
    """الأعمدة اللي لازم تتفضّى قبل المسح — **لأن فيه دواير**.

    `visits.based_on_id` بتشاور على `visit_investigations`، و
    `visit_investigations.visit_id` بتشاور على `visits`. والتعليق في
    الموديل بيقول ليه: *"the question it came from are one chain rather
    than three loose rows"*.

    يعني **مفيش ترتيب حذف صح أصلاً** — أي واحد فيهم يتمسح الأول، التاني
    بيفضل بيشاور عليه. فالحل مش ترتيب أذكى، ده تفضية العمود اللي بيقفل
    الدايرة الأول.

    **والبحث بالتقشير مش بالمشي**: المشي بيقطع أول حرف يصادفه، وده
    بيتغيّر مع ترتيب الجداول في الذاكرة. التقشير بيشيل اللي مالوش أبناء
    لحد ما يقف، واللي فاضل هو الدواير بالظبط — إجابة واحدة كل مرة.
    """
    tables = tables if tables is not None else _tables()
    wanted = set(wanted) if wanted is not None else wiped_tables()
    edges = [(child, parent, column)
             for child, parent, column in _edges(tables)
             if child in wanted and parent in wanted]

    breakers = []
    cut = set()
    while True:
        live = [(c, p, col) for c, p, col in edges if id(col) not in cut]
        has_children = defaultdict(set)
        for child, parent, _col in live:
            has_children[parent].add(child)

        remaining = set(wanted)
        while True:
            leaves = {name for name in remaining
                      if not (has_children.get(name, set()) & remaining)}
            if not leaves:
                break
            remaining -= leaves

        if not remaining:
            return breakers

        # اللي فاضل كله دواير. اقطع حرف واحد **قابل للتفضية** منها،
        # وأعد التقشير — علشان القطع يفضل أقل ما يمكن.
        spare = next(((c, p, col) for c, p, col in live
                      if c in remaining and p in remaining and col.nullable),
                     None)
        if spare is None:
            # دايرة من أعمدة مش nullable — تصميم مالوش مخرج. ما حصلش
            # هنا، ولو حصل يوم فالسكوت عنه أسوأ من الوقوف.
            raise RuntimeError(f"unbreakable cycle: {sorted(remaining)}")
        breakers.append(spare[2])
        cut.add(id(spare[2]))


def delete_order(wanted=None):
    """الابن قبل الأب — **محسوب من المفاتيح مش مكتوب بالإيد**.

    ترتيب غلط مش بيسيب يتيم وبس، ده بيفشّل المسح نفسه بخطأ مفتاح
    أجنبي على PostgreSQL — وساعتها اللي ضغط الزرار بيلاقي نص البيانات
    اتمسح.

    والدواير بتتقطع في :func:`cycle_breakers` قبل ما الترتيب ده يتحسب،
    فاللي فاضل شجرة.

    **والمجموعة معامل مش ثابت.** «امسح البيانات التجريبية بس» بيمسح
    جداول المسح العادي بيسيبها — تخطيط المستشفى — فمحتاج نفس الحساب ده
    على مجموعة أوسع. الترتيب واحد، اللي بيتغيّر هو نطاقه.
    """
    tables = _tables()
    wanted = set(wanted) if wanted is not None else wiped_tables()
    broken = {id(col) for col in cycle_breakers(tables, wanted)}

    children = defaultdict(set)
    for child, parent, column in _edges(tables):
        if id(column) in broken:
            continue
        if child in wanted and parent in wanted:
            children[parent].add(child)

    order, done = [], set()

    def visit(name, stack=()):
        if name in done or name in stack:
            return
        for child in children.get(name, ()):
            visit(child, stack + (name,))
        done.add(name)
        order.append(name)

    for name in wanted:
        visit(name)
    return order


def wipe():
    """يفضّي البيانات التشغيلية. المتصل بيعمل commit.

    بيرجّع ``{اسم الجدول: كام صف اتمسح}`` — علشان اللي ضغط يشوف إيه
    اللي حصل، مش «تم».
    """
    tables = _tables()
    # **الدايرة بتتقطع الأول.** من غير كده مفيش ترتيب بيمشي: أي طرف
    # يتمسح، التاني بيفضل بيشاور عليه.
    for column in cycle_breakers(tables):
        db.session.execute(
            column.table.update().values({column.name: None}))
    counts = {}
    for name in delete_order():
        table = tables.get(name)
        if table is None:
            continue
        removed = db.session.execute(table.delete()).rowcount
        if removed:
            counts[name] = removed
    return counts
