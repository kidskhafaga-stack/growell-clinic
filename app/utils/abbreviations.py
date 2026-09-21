"""الفاحص — `IMT.04` دليل ٤: *violation … is **monitored***.

**اللي البرنامج بيضيفه هنا مش المنع، ده الرؤية.** `rx_shorthand`
و`phrases` شغالين من زمان على إن اللي بيتخزّن يبقى الكلام الطويل. الناقص
كان: مين بيقرا اللي اتكتب فعلاً ويقول فين اتخالفت القايمة.

---

**والمطابقة هي كل الشغل هنا.** «MS» اختصار ممنوع، بس «ms» جوّه كلمة
مش هو، و«U» لوحدها غير الـ«U» اللي في «BUN». فالفاحص بيدوّر على الرمز
**كلمة كاملة**، وبيفرّق بين الكبير والصغير، وبيعرف إن العربي مالوش
`\\b` في بايثون زي الإنجليزي.
"""
import re

from app.models.abbreviation import (Abbreviation, APPROVED, BANNED, CONTEXTS,
                                     FAMILY, NOTE)

#: الحقول اللي الفاحص بيقراها، **باسمها**.
#:
#: مش كل حقل نص في البرنامج: الفحص اللي بيشمل كل حاجة بيطلّع ضوضاء
#: ومحدّش بيفتحه. دول اللي المعيار بيسمّيهم في دليل الفحص — *"medication
#: orders and inpatient medical records"* — وزيادة عليهم اللي بيروح
#: للأهل، لأن (د) بيحكم عليه بقاعدة أصرم.
SCANNED = {
    "Prescription": (NOTE, ("diagnosis", "complaint", "notes")),
    "Visit": (NOTE, ("chief_complaint", "clinical_exam", "plan", "notes",
                     "nurse_instructions")),
    "RoundNote": (NOTE, ("assessment", "plan")),
    # (د) — دول بيروح منهم ورق للأهل، فحتى المسموح ممنوع فيهم.
    "DischargeSummary": (FAMILY, ("diagnosis", "findings", "condition",
                                  "diet", "medicines", "followup")),
    "Consent": (FAMILY, ("statement", "notes")),
}


def _rule_rows(kind=None):
    query = Abbreviation.query.filter(Abbreviation.is_active.is_(True))
    if kind is not None:
        query = query.filter(Abbreviation.kind == kind)
    return query.order_by(Abbreviation.text).all()


# **ومفيش `rules()` عامة.** كتبتها غلاف أحلى لـ`_rule_rows`، والحارس
# وقفها: شاشة الإعدادات محتاجة **كل** الصفوف، الموقوفة كمان، علشان
# تقدر ترجّعها؛ والفاحص محتاج الشغّالة بس. فمفيش حد عايز اللي كانت
# بترجّعه بالظبط — غلاف من غير نداء، مش واجهة.


def _pattern(text):
    """الرمز ككلمة كاملة.

    **و`\\b` لوحدها ما بتكفيش.** في بايثون `\\b` بتشتغل على
    `[A-Za-z0-9_]`، فالعربي بيعدّي منها غلط: «ق.ي» جوّه كلمة عربية
    أطول ما بيتمسكش صح. فالحدود هنا **مش حرف ولا رقم عربي ولا لاتيني**،
    مكتوبة بإيد.
    """
    body = re.escape(text)
    letter = r"[^\W\d_]"          # أي حرف، عربي أو لاتيني
    # **ورقم قبل الاختصار ما بيلغيهوش.** «10U» هي بالظبط الحالة اللي
    # القوايم الممنوعة موجودة علشانها: بتتقرا «100». فالحد الشمالي حرف
    # بس — «BUN» مش مخالفة، و«10U» مخالفة.
    #
    # والرقم **بعده** بيلغيه، لأن «U2» رمز حاجة تانية مش جرعة.
    return re.compile(rf"(?<!{letter}){body}(?!{letter})(?![0-9])")


def find(text, context=NOTE, rows=None):
    """الاختصارات اللي اتخالفت في النص ده.

    بيرجّع ``[{"text":…, "kind":…, "means":…}]``.

    * **في أي مكان**: الممنوع مخالفة.
    * **وفي سياق الأهل**: المسموح كمان مخالفة — (د) بالنص.
    """
    if context not in CONTEXTS:
        raise ValueError("unknown context")
    body = text or ""
    if not body.strip():
        return []
    out = []
    for row in (rows if rows is not None else _rule_rows()):
        if row.kind == APPROVED and context != FAMILY:
            continue
        if _pattern(row.text).search(body):
            out.append({"text": row.text, "kind": row.kind,
                        "means": row.means})
    return out


def clean(text, context=NOTE, rows=None):
    return not find(text, context, rows)


def _model(name):
    import app.models as models

    return getattr(models, name, None)


def violations(limit=200, per_model=200):
    """**الرصد** — دليل ٤.

    بيمشي على الحقول اللي في :data:`SCANNED` بس، بكلامها. بيرجّع
    ``[{"model":…, "row":…, "field":…, "context":…, "found":[…]}]``.

    والقايمة فاضية لما العيادة ما تكونش كتبت قايمتها — زي كل رقم
    وسياسة تانية في البرنامج ده: ساكت لحد ما المكان يقول رأيه.
    """
    rows = _rule_rows()
    if not rows:
        return []
    out = []
    for name, (context, fields) in SCANNED.items():
        model = _model(name)
        if model is None:
            continue
        for record in (model.query
                       .order_by(model.id.desc())
                       .limit(per_model).all()):
            for field in fields:
                found = find(getattr(record, field, None), context, rows)
                if found:
                    out.append({"model": name, "row": record, "field": field,
                                "context": context, "found": found})
                    if len(out) >= limit:
                        return out
    return out


def counts():
    """كام مخالفة، وكام رمز في كل قايمة — للوحة."""
    found = violations()
    return {
        "violations": len(found),
        "approved": len(_rule_rows(APPROVED)),
        "banned": len(_rule_rows(BANNED)),
    }
