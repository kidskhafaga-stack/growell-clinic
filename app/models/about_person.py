"""The people the clinic wants credited on the About page.

This started as a single "medical supervisor" held in three settings keys, and
was wrong in two ways that only show up once a real clinic opens the page.

**A name typed once cannot be shown in two languages.** Every other name in
this program carries both — ``full_name`` / ``full_name_en`` on a user, ``name``
/ ``name_en`` on a service — because the page is Arabic for the family at the
desk and English for whoever is being shown the system, and a single field
means one of those two audiences reads the other one's alphabet. The About page
was the one place that still stored one string and printed it under both
languages.

**A clinic has more than one doctor.** One settings key can hold one person.

So: a row per person, a column per language, and an order the clinic chooses.
The English side is optional throughout — when it is blank the Arabic is shown
in both languages, which is the same fallback ``User.display_name`` uses, and
means nobody is forced to type everything twice to get a working page.
"""
from app.extensions import db

# Titles, not names. Nearly every name on this page begins with one, so an
# initial taken from the first character makes every circle read "د" — the
# same letter for every doctor in the clinic, which is no use to anybody
# scanning the list. The initial comes from the first word that is a name.
HONORIFICS = {
    "د", "دكتور", "دكتورة", "أ", "أ.د", "ا", "م", "مهندس", "الأستاذ", "است",
    "dr", "prof", "professor", "eng", "mr", "mrs", "ms", "miss",
}


# "د/ منى" is written at least as often as "د. منى" in an Egyptian clinic, so
# the slash has to come off the word before it is recognised as a title.
_PUNCT = ".،,/\\-"


def initial_of(name):
    """The letter to put in an empty circle for this name."""
    for word in (name or "").split():
        cleaned = word.strip(_PUNCT).lower()
        if cleaned and cleaned not in HONORIFICS:
            return word.lstrip(_PUNCT)[:1].upper()
    # A name that is nothing but a title still has to render something.
    return (name or "").strip()[:1].upper()


class AboutPerson(db.Model):
    __tablename__ = "about_people"

    id = db.Column(db.Integer, primary_key=True)

    # Arabic is the required side: this is an Arabic-first program, and a
    # person with only an English name would vanish from the Arabic page.
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))

    # What they are to the clinic — "الإشراف الطبي", "استشاري طب الأطفال".
    title = db.Column(db.String(160))
    title_en = db.Column(db.String(160))

    note = db.Column(db.Text)
    note_en = db.Column(db.Text)

    # A filename under ``static/uploads/about``, or nothing. Optional on
    # purpose — a credits page has to look finished before anybody has been
    # asked for a photograph, so a person without one gets their initial in
    # the same circle rather than a hole where a face should be.
    photo = db.Column(db.String(255))

    # The clinic's own order. Ties fall back to id, so rows added without a
    # number still come out in the order they were entered rather than
    # shuffling on every page load.
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    def _pick(self, arabic, english, lang):
        """The English column when it is asked for *and* filled in.

        Falling back to Arabic rather than showing an empty line is the whole
        reason the English side can be left blank.
        """
        if lang == "en":
            return (english or "").strip() or (arabic or "").strip()
        return (arabic or "").strip() or (english or "").strip()

    def display_name(self, lang="ar"):
        return self._pick(self.name, self.name_en, lang)

    def display_title(self, lang="ar"):
        return self._pick(self.title, self.title_en, lang)

    def display_note(self, lang="ar"):
        return self._pick(self.note, self.note_en, lang)

    def initial(self, lang="ar"):
        return initial_of(self.display_name(lang))

    def __repr__(self):
        return f"<AboutPerson {self.name!r}>"
