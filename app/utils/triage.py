"""Which message is the one to answer first.

The inbox sorts by who has waited longest, and for a list of questions about
appointments and prices that is exactly right. It is wrong for one of them:
"الولد سخن ٤٠ وبيتنفس بصعوبة" does not wait its turn behind eleven people
asking about opening hours, however long they have been waiting.

So a conversation carries what it is about, and one of those topics — urgent —
jumps the queue outright.

The clinic sets it, or the program suggests it. The suggestion is a *guess
shown as a guess*: it puts the thread at the top and says why, and a person
can disagree in one click. Nothing here decides that a message is **not**
urgent — the flag only ever raises a thread, never lowers one, because the
cost of the two mistakes is not remotely the same.
"""
TOPICS = ("urgent", "result", "appointment", "price", "complaint", "other")

# Words that, in a paediatric clinic, mean "read this one now". Deliberately
# about the child's state rather than the parent's tone: "زعلان" is a
# complaint, "مش بيتنفس" is an emergency.
URGENT_WORDS = (
    "اسعاف", "إسعاف", "طوارئ", "طوارىء", "خطر", "تشنج", "تشنجات",
    "بيتنفس بصعوبة", "صعوبة تنفس", "صعوبة في التنفس", "مش بيتنفس",
    "نهجان", "ازرق", "أزرق", "ازرقاق", "اغماء", "إغماء", "فقد الوعي",
    "مش بيفوق", "بيرجع دم", "نزيف", "دم", "حرارة ٤٠", "حرارة 40",
    "سخن جدا", "سخن جداً", "تسمم", "بلع", "حساسية شديدة", "ورم في الوش",
    "emergency", "seizure", "convulsion", "not breathing", "unconscious",
    "bleeding", "blue", "choking",
)

TOPIC_WORDS = {
    "result": ("نتيجة", "نتايج", "تحليل", "تحاليل", "اشعة", "أشعة", "سونار",
               "تقرير", "result", "report", "x-ray", "lab"),
    "appointment": ("ميعاد", "معاد", "مواعيد", "حجز", "احجز", "أحجز", "موعد",
                    "الكشف امتى", "فاضي", "appointment", "booking"),
    "price": ("سعر", "بكام", "كام", "تكلفة", "حساب", "فلوس", "الكشف بكام",
              "price", "cost", "how much"),
    "complaint": ("شكوى", "زعلان", "مستاء", "استنيت", "تأخير", "مش راضي",
                  "وحش", "سيء", "complaint", "unhappy", "waiting too long"),
}


def suggest_topic(text):
    """What this message looks like it is about — a guess, and only a guess.

    Urgency is checked first and on its own: a message can be about a result
    *and* be an emergency, and when it is both, it is an emergency.
    """
    body = (text or "").strip().lower()
    if not body:
        return None
    if any(word.lower() in body for word in URGENT_WORDS):
        return "urgent"
    for topic, words in TOPIC_WORDS.items():
        if any(word.lower() in body for word in words):
            return topic
    return None


def rank(conv):
    """Sort key for the inbox — lower comes first.

    Urgent above everything, whether a person marked it or the program
    guessed it. Then the closing windows, then the longest wait. A queue that
    puts a feverish child behind eleven pricing questions is not a queue, it
    is a list.
    """
    urgent = (conv.get("topic") == "urgent"
              or conv.get("suggested_topic") == "urgent")
    return (
        not conv.get("open"),          # answered threads last
        not urgent,                    # emergencies first
        not conv.get("closing"),       # then what is about to time out
        conv.get("hours_left") if conv.get("closing") else 0,
        -(conv.get("waiting_hours") or 0),
        -conv["last"].created_at.timestamp(),
    )


def topic_label(topic, lang="ar"):
    from app.i18n import t

    return t(f"triage.topic_{topic}") if topic in TOPICS else ""
