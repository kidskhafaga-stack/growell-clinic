"""مين يقدر يقرا ملف الطفل — GAHAR `IMT.05`.

> 3. There is a list of authorized individuals with access to the patient's
>    medical record.
> 4. Only authorized individuals have access to patient's medical records.
> 5. There is a signed confidentiality agreement in each staff member's
>    personal file.

**دليل ٤ كان متحقّق من زمان** — كل طريق في البرنامج ورا صلاحية، ومحروس
بـ`test_permission_sweep`. **ودليل ٣ لأ**: الصلاحيات موجودة ومطبّقة، بس
مفيش ورقة بتقول «مين له حق». والمراجِع بيطلب الورقة.

---

**والقايمة محسوبة، مش مكتوبة.** بتسأل كل مستخدم نفس الأسئلة اللي الطريق
نفسه بيسألها — `can_open` و`can` — فمش ممكن تقول حاجة غير اللي البرنامج
بيعمله فعلاً. قايمة مكتوبة بالإيد كانت هتبقى صح يوم ما اتكتبت، وبعدها
أول دور يتعدّل أو موديول يتقفل بيخلّيها تكدب — ومحدّش بياخد باله، لأن
الورقة شكلها رسمي.

و`can_open` مش `can_access`: الموديول اللي العيادة قافلاه مش مفتوح لحد،
حتى لو الدور مسموحله. نفس الفرق اللي `User.can_open` بيشرحه.
"""
from datetime import date

from app.extensions import db
from app.models import Setting, User

#: أجزاء الملف بالترتيب اللي حد بيقراه بيه — وكل واحد بيتسأل بنفس
#: سؤال الطريق اللي بيفتحه.
AREAS = (
    ("file", "patients", None),
    ("clinical", "patients", "patient_medical"),
    ("visits", "visits", None),
    ("prescriptions", "prescriptions", None),
    ("labs", "labs", None),
    ("stays", "beds", None),
)


def reaches(user, module, capability=None):
    """نفس سؤال الطريق: الموديول مفتوح، **والصلاحية لو ليها**."""
    if not user.can_open(module):
        return False
    return capability is None or bool(user.can(capability))


def areas_for(user):
    """``{المنطقة: True/False}`` بترتيب :data:`AREAS`."""
    return {key: reaches(user, module, cap) for key, module, cap in AREAS}


def own_visits_only(user):
    """طبيب مقفول على زياراته — نفس `privacy.doctor_locked_id` بس لمستخدم
    مش لازم يكون هو اللي داخل دلوقتي."""
    if user.is_admin or user.role != "doctor":
        return False
    return Setting.get("doctors_see_own_only", "1") != "0"


def rows():
    """كل مستخدم شغّال: مين، وبيوصل لإيه، ووقّع ولا لأ.

    **الشغّالين بس** — حساب اتقفل مابيقراش حاجة، وظهوره في «مين له حق»
    كان هيكدب في الاتجاه التاني.
    """
    users = (User.query.filter(User.is_active.is_(True))
             .order_by(User.role, User.full_name).all())
    out = []
    for user in users:
        areas = areas_for(user)
        out.append({"user": user, "areas": areas,
                    "reads_record": any(areas.values()),
                    "own_only": own_visits_only(user),
                    "signed_on": user.confidentiality_signed_on})
    return out


def unsigned():
    """اللي بيقروا الملف ومحدّش سجّل إنهم وقّعوا — دليل ٥."""
    return [row["user"] for row in rows()
            if row["reads_record"] and row["signed_on"] is None]


def record_signature(user, on=None, recorder=None):
    """الإقرار اتوقّع — **اليوم اللي اتوقّع فيه**، مش النهارده بالضرورة.

    الورقة ممكن تكون اتوقّعت يوم التعيين من سنتين، واللي بيسجّل دلوقتي
    بيسجّل تاريخها. ويوم في المستقبل بيترفض: ورقة ما اتوقّعتش لسه.
    """
    on = on or date.today()
    if on > date.today():
        raise ValueError("a signature cannot be in the future")
    user.confidentiality_signed_on = on
    user.confidentiality_recorded_by = getattr(recorder, "id", None)
    db.session.flush()
    return user
