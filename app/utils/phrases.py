"""The doctor's own shorthand: short codes that write long sentences.

Two requests, and they are the same feature seen from two sides.

**Per doctor.** *"طبيب السكر غير طبيب حديثي الولادة، دكتور القلب غير حد تاني،
والغدد"* — the phrases an endocrinologist reaches for are not a
neonatologist's, and one shared clinic list grows until finding a phrase costs
more than typing it. Each doctor keeps their own; the clinic's list is where
they start, not what they are stuck with.

**Short in, long out.** *"ممكن نعمل اختصارات طويلة تبقى باختصار زي نورمال"* —
the visit screen already had one button that wrote a whole normal-examination
paragraph, and that is the thing a doctor wants for every sentence they repeat.
So a phrase can carry a **code**: type it, press space, and the sentence
arrives. A cardiologist's "قلب" can be four lines of normal cardiac
examination and still cost three keystrokes.

**Stored as text, one phrase per line.** ``code|ar|en`` — and a line with two
parts is still ``ar|en``, which is what every clinic already has on disk, so
nothing needs converting and nothing can be lost by reading an old list with
new code. The place that knows this format is this module and nowhere else;
it was previously spelt out in three files, which is why the settings screen
was quietly showing the signed-in doctor's list while claiming to edit the
clinic's.
"""
from app.models import Setting

# The visit fields that take quick phrases. Each has a clinic-wide setting and
# a per-doctor column of the same name.
FIELDS = ("complaint", "exam", "plan")


def key_for(field):
    """The Setting key / User column holding this field's phrases."""
    return f"visit_{field}_chips"


DEFAULTS = {
    "complaint": [
        ("حرارة", "Fever"), ("كحة", "Cough"), ("رشح", "Runny nose"),
        ("إسهال", "Diarrhea"), ("قيء", "Vomiting"), ("مغص", "Colic"),
        ("إمساك", "Constipation"), ("طفح جلدي", "Skin rash"),
        ("التهاب حلق", "Sore throat"), ("التهاب أذن", "Ear infection"),
        ("صعوبة تنفس", "Difficulty breathing"), ("صفير بالصدر", "Wheezing"),
        ("ضعف شهية", "Poor appetite"), ("خمول", "Lethargy"),
        ("تسنين", "Teething"), ("احمرار عين", "Red eye"),
        ("ألم بطن", "Abdominal pain"), ("صداع", "Headache"),
        ("متابعة نمو", "Growth follow-up"),
        ("متابعة تطعيم", "Vaccination follow-up"),
        ("إعادة كشف", "Re-examination"),
    ],
    "exam": [
        ("الحالة العامة جيدة", "General condition good"),
        ("الصدر: دخول هواء ثنائي متساوٍ بدون صفير",
         "Chest: equal bilateral air entry, no wheeze"),
        ("القلب: أصوات منتظمة بدون لغط",
         "Heart: regular sounds, no murmur"),
        ("البطن: لين غير منتفخ غير مؤلم",
         "Abdomen: soft, not distended, non-tender"),
        ("الحلق: محتقن", "Throat: congested"),
        ("الأذن: طبلة محتقنة", "Ear: congested tympanic membrane"),
        ("لا توجد علامات جفاف", "No signs of dehydration"),
        ("الغدد الليمفاوية غير متضخمة", "Lymph nodes not enlarged"),
        ("الجلد: سليم", "Skin: intact"),
    ],
    # The plan box had no phrases at all, which is where the repetition
    # actually is: the same six sentences, typed out, all day.
    "plan": [
        ("خافض حرارة عند اللزوم", "Antipyretic as needed"),
        ("سوائل ورضاعة متكررة", "Fluids and frequent feeds"),
        ("متابعة بعد ٣ أيام", "Review in 3 days"),
        ("متابعة فوراً لو زادت الحرارة أو قل النشاط",
         "Return immediately if fever rises or activity drops"),
        ("تحاليل مطلوبة", "Investigations requested"),
        ("تحويل لأخصائي", "Referral to a specialist"),
    ],
}


def parse(raw, defaults=()):
    """``[{"code","ar","en"}]`` from the stored lines, or the defaults.

    Three parts is ``code|ar|en``; two is ``ar|en`` — the shape every clinic
    already has, kept readable so nobody's list needs converting. Anything
    after the third pipe stays with the English, because a sentence is allowed
    to contain punctuation and a code is not.
    """
    rows = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            code, ar, en = parts[0], parts[1], "|".join(parts[2:])
        else:
            code, ar, en = "", parts[0], (parts[1] if len(parts) > 1 else "")
        ar, en, code = ar.strip(), en.strip(), code.strip()
        if ar or en:
            rows.append({"code": code, "ar": ar, "en": en})
    if rows:
        return rows
    return [{"code": "", "ar": ar, "en": en} for ar, en in defaults]


def serialise(rows):
    """Back to stored text. The inverse of :func:`parse`."""
    out = []
    for row in rows:
        code = (row.get("code") or "").strip()
        ar = (row.get("ar") or "").strip()
        en = (row.get("en") or "").strip()
        if not (ar or en):
            continue
        if code:
            out.append(f"{code}|{ar}|{en}")
        elif en:
            out.append(f"{ar}|{en}")
        else:
            out.append(ar)
    return "\n".join(out)


def clinic_phrases(field):
    """The clinic's list for a field — the starting point for every doctor.

    Deliberately takes no user: the settings screen used to call the
    doctor-aware reader, so an admin who had phrases of their own was shown
    them under a heading that said "the clinic's" and saved them over it.
    """
    return parse(Setting.get(key_for(field)), DEFAULTS.get(field, ()))


def for_user(user, field):
    """A doctor's own phrases for a field, falling back to the clinic's.

    Blank means "use the clinic's" rather than "I have none" — a doctor who
    has never opened the screen should still find sensible phrases under their
    fingers on their first consultation, and clearing the box is how they go
    back to them.
    """
    own = getattr(user, key_for(field), None) if user is not None else None
    if own:
        rows = parse(own)
        if rows:
            return rows
    return clinic_phrases(field)


def text_of(row, lang="ar"):
    """What the chip writes into the box, in the language on screen."""
    if lang == "en" and row.get("en"):
        return row["en"]
    return row.get("ar") or row.get("en") or ""


def codes(user, lang="ar"):
    """``{field: {code: text}}`` — everything the visit screen can expand.

    Codes are compared as typed. Folding them would mean a doctor who defines
    "قلب" could no longer type it as an ordinary word in a sentence, which is
    a worse trade than asking them to type their own shorthand exactly.
    """
    out = {}
    for field in FIELDS:
        found = {}
        for row in for_user(user, field):
            code = (row.get("code") or "").strip()
            if code:
                found[code] = text_of(row, lang)
        out[field] = found
    return out
