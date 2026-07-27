"""Sample values for showing a template as the family will receive it.

A template body is written with tokens — ``{patient}``, ``{date}``, ``{queue}``
— and reads fine to whoever typed it. What the parent gets is the filled
version, and the gap between the two is where the embarrassing mistakes live:
a token spelled ``{Patient}``, a sentence that only makes sense when the name
is short, a line break in the wrong place.

So the samples live here, in one place, and both the live preview in the
browser and the test send on the server fill from the same dictionary. Two
copies would drift, and a preview that shows something other than what gets
sent is worse than no preview at all — it is a preview that lies.
"""
import re

# Deliberately ordinary values: a real Egyptian name, a real-looking date, a
# queue number. Placeholder-looking samples ("XXX", "اسم المريض") let a broken
# sentence pass review because nobody reads them as a sentence.
SAMPLES = {
    "patient": "محمد أحمد",
    "clinic": "العيادة",
    "date": "2026-07-10",
    "time": "10:30 ص",
    "doctor": "د. سارة",
    "queue": "3",
    "vaccine": "الروتا",
    "dose": "الجرعة الأولى",
    "next_date": "2026-08-10",
    "due_date": "2026-07-15",
    "year": "2026",
    "old_vaccine": "التطعيم السابق",
    "new_vaccine": "التطعيم البديل",
    "count": "8",
    "list": "1) 10:00 - محمد\n2) 10:30 - سارة\n3) 11:00 - يوسف",
    "link": "https://clinic.example.com/f/aXbY",
    "hours": "السبت–الخميس 16:00 – 22:00",
}

_TOKEN = re.compile(r"\{(\w+)\}")


def samples(clinic_name=None):
    """The sample set, with the clinic's own name if we know it."""
    out = dict(SAMPLES)
    if clinic_name:
        out["clinic"] = clinic_name
    return out


def fill(text, values=None):
    """Replace every ``{token}`` we have a sample for; leave the rest alone.

    An unknown token stays visible on purpose. Silently blanking ``{patinet}``
    would hide the typo — leaving it in the preview is how the typo gets
    noticed.
    """
    values = samples() if values is None else values
    return _TOKEN.sub(lambda m: str(values.get(m.group(1), m.group(0))),
                      text or "")
