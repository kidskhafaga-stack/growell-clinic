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

**Some of these people are staff and some of them are not**, and the row has
to hold both without preferring either. A doctor who logs in already has a
name in two languages, a title, a specialty and a photograph on their user
record; typing all of that a second time here is a second copy that drifts —
they are promoted from Specialist to Consultant, somebody updates the user,
and this page goes on printing last year's title until a person notices.
So a row may be *linked* to a user, and then the user is read at render time
and there is no second copy to go stale.

Equally: a supervising professor, the clinic's owner, somebody who helped and
was thanked — none of them have logins, and none of them ever will. A design
where being credited requires being a user is a design that cannot say what
this page exists to say. The link is optional, the typed columns stay, and a
row with no link behaves exactly as it always did.

The typed name is kept even on a linked row, as the fallback for the day the
user record is deleted. A credit must not vanish from the page because
somebody tidied up a login.
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

    # The staff member this credit is for, when they are one. Nullable, and
    # nullable is the point: see the note at the top of this file. `SET NULL`
    # rather than a cascade — deleting a login is not a decision to remove
    # somebody from the clinic's credits, so the row survives and falls back
    # to whatever was typed into it.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    staff = db.relationship("User", foreign_keys=[user_id])

    def _pick(self, arabic, english, lang):
        """The English column when it is asked for *and* filled in.

        Falling back to Arabic rather than showing an empty line is the whole
        reason the English side can be left blank.
        """
        if lang == "en":
            return (english or "").strip() or (arabic or "").strip()
        return (arabic or "").strip() or (english or "").strip()

    def display_name(self, lang="ar"):
        """The linked user's name when there is one, else what was typed.

        Read every time rather than copied, which is the whole reason the
        link exists: there is no stored second name to disagree with the
        first.
        """
        if self.staff is not None:
            return self.staff.display_name(lang)
        return self._pick(self.name, self.name_en, lang)

    def display_title(self, lang="ar"):
        """What this person is, in the clinic's own words when it gave any.

        The typed title wins over the user's even on a linked row, and
        deliberately: a doctor's user record says what they are *to the
        program* — their specialty — while this page says what they are *to
        this clinic*, and "الإشراف الطبي" is not a specialty. Nothing is
        duplicated by that, because the clinic only typed one of them.
        """
        typed = self._pick(self.title, self.title_en, lang)
        if typed or self.staff is None:
            return typed
        lines = self.staff.doctor_title_lines(lang)
        if lines:
            return lines[0]
        return (self.staff.job_title or "").strip()

    def display_note(self, lang="ar"):
        return self._pick(self.note, self.note_en, lang)

    def photo_path(self):
        """Where this person's picture lives under ``static/``, or None.

        Two folders, because a staff photograph is already uploaded on their
        profile and a credited outsider's is not. Returning the path rather
        than the filename is what lets one macro draw both — the template used
        to hard-code ``uploads/about/`` and would have shown a broken image
        for every linked person.
        """
        if self.staff is not None and self.staff.photo:
            return f"uploads/users/{self.staff.photo}"
        if self.photo:
            return f"uploads/about/{self.photo}"
        return None

    def initial(self, lang="ar"):
        return initial_of(self.display_name(lang))

    def __repr__(self):
        return f"<AboutPerson {self.name!r}>"
