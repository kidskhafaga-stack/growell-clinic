# 🏥 GROWELL CLINIC

نظام إدارة عيادة أطفال متكامل — احترافي، ثنائي اللغة (عربي / إنجليزي).

> An integrated pediatric clinic management system — professional and fully
> bilingual (Arabic / English) from day one.

---

## ✅ المرحلة الحالية: المرحلة 1 — الأساس (Phase 1: Foundation)

اكتملت المرحلة الأولى وتشمل:

- **هيكل المشروع** — تطبيق Flask منظّم (Application Factory + Blueprints).
- **قاعدة البيانات** — SQLite عبر SQLAlchemy، قابلة للترقية إلى PostgreSQL بتغيير `DATABASE_URL` فقط.
- **نظام الترجمة (i18n)** — كل النصوص عبر مفاتيح ترجمة في ملفات JSON، تبديل فوري بين العربية/الإنجليزية مع دعم RTL/LTR.
- **تسجيل الدخول** — مصادقة آمنة (تجزئة كلمات المرور)، "تذكرني"، وسجل دخول/خروج.
- **الصلاحيات** — 5 أدوار (مدير / طبيب / استقبال / محاسب / صيدلية) مع مصفوفة وصول لكل وحدة.
- **إدارة المستخدمين** — إضافة/تعديل/حذف (للمدير فقط).
- **الثيم الأخضر الطبي** — سايدبار بتدرّج لوني + لوحة تحكم تعرض الوحدات المتاحة حسب الدور.
- **سجل النشاط** + **إعدادات النظام** + **صفحات الأخطاء** (403/404/500).

---

## 🛠️ الستاك التقني

| Layer | Technology |
|-------|------------|
| Backend | Python 3 + Flask |
| ORM / DB | Flask-SQLAlchemy + SQLite (→ PostgreSQL) |
| Auth | Flask-Login + Werkzeug password hashing |
| i18n | نظام مفاتيح JSON مخصص (عربي/إنجليزي) |
| Frontend | Jinja2 + CSS (الثيم الأخضر) + Bootstrap Icons |

---

## 🚀 التشغيل (Getting started)

```bash
# 1) إنشاء بيئة افتراضية وتثبيت الاعتماديات
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) (اختياري) ضبط متغيرات البيئة
cp .env.example .env

# 3) تهيئة قاعدة البيانات + إنشاء مستخدمين تجريبيين
flask --app run seed

# 4) التشغيل
python run.py
# ثم افتح http://localhost:5000
```

### أوامر CLI

```bash
flask --app run init-db        # إنشاء الجداول + الإعدادات الافتراضية
flask --app run seed           # مستخدمون تجريبيون (واحد لكل دور)
flask --app run create-admin   # إنشاء حساب مدير تفاعلياً
```

### بيانات الدخول التجريبية (غيّرها في الإنتاج!)

| الدور | المستخدم | كلمة المرور |
|-------|----------|-------------|
| مدير | `admin` | `admin123` |
| طبيب | `doctor` | `doctor123` |
| استقبال | `reception` | `reception123` |
| محاسب | `accountant` | `accountant123` |
| صيدلية | `pharmacy` | `pharmacy123` |

---

## 🗂️ هيكل المشروع

```
growell-clinic/
├── run.py                  # نقطة التشغيل
├── config.py               # الإعدادات (بيئة-معتمدة)
├── requirements.txt
└── app/
    ├── __init__.py         # Application Factory
    ├── extensions.py       # db, login_manager
    ├── cli.py              # أوامر init-db / seed / create-admin
    ├── i18n/               # محرك الترجمة + locales/{ar,en}.json
    ├── models/             # User, Setting, ActivityLog, permissions
    ├── blueprints/         # auth, main, users
    ├── utils/              # decorators (module_required, admin_required)
    ├── templates/          # base, shell, auth, main, users, errors
    └── static/             # css/theme.css, js/app.js
```

---

## 🔭 المراحل القادمة

| المرحلة | المحتوى |
|---------|---------|
| 2 | المرضى + الأسر + رقم الملف + ملف المريض بالتبويبات |
| 3 | المواعيد + جدول الطبيب + شاشة "Today's Appointments" |
| 4 | الزيارة + العلامات الحيوية + ICD-10/11 |
| 5 | مخططات النمو (WHO/CDC/RCPCH) + Percentile/Z-score |
| 6 | التطعيمات + الماركات + المخزون + الموردين |
| 7 | الأدوية + حساب الجرعة + الروشتة |
| 8 | المالي (الخدمات + الفواتير + الخصومات + التعاقدات) |
| 9 | الداشبوردات + البحث العلمي |
| 10 | الرسائل التلقائية (WhatsApp) + AI |

راجع الملف المرجعي للمشروع `CLINIC_PLAN.md` للتفاصيل الكاملة.
