"""The About page opened empty on every new install.

The developer's name and role are constants — they are the copyright holder —
and everything under them was the clinic's to type: the two biographies, the
contact, the photographs, and the doctor beside them. So a fresh install
showed two headings and nothing beneath them until somebody sat down and wrote
it all out again.

Asked for in one line: *«أنا عايز أضيف الاتنين دول في أي نسخة وأعدّل عليهم وقت
ما أحب»*.

**Seeded, not compiled**, and the distinction is the whole of it. A biography
written into the source is a paragraph the clinic cannot touch; this program's
rule is that what is on a screen is edited from that screen. These arrive as
ordinary settings and an ordinary row, they go through the same edit form as
anything typed by hand, and deleting one is a decision the clinic is allowed
to make.

**Which is why it runs once and remembers.** A seed that re-ran would put a
deleted person back on every update — and the migration beside it already
refuses to do exactly that: *"cannot resurrect somebody who was deliberately
deleted"*.

**And the photographs ship as files.** A stored photograph used to be a bare
filename under ``uploads/``, which is per-install and empty on a machine
nobody has uploaded to. A value with a path in it is a file that came with the
program; a bare one is still an upload. Both resolve through one function, so
replacing a shipped picture from the screen writes an upload and leaves the
shipped file alone.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ------------------------------------------------------- where a photo lives

@pytest.mark.parametrize("stored,path", [
    ("khafaga.jpg", "uploads/about/khafaga.jpg"),      # everything typed so far
    ("img/about/khafaga.jpg", "img/about/khafaga.jpg"),  # ships with the code
    ("", None),
    (None, None),
])
def test_a_photograph_is_found_wherever_it_lives(stored, path):
    from app.models.about_person import photo_path_of

    assert photo_path_of(stored) == path


def test_a_linked_staff_photo_still_wins(clinic):
    """The rule that was already there: a credited person who logs in has a
    picture on their profile, and there is no second copy of it here."""
    from app.models import User
    from app.models.about_person import AboutPerson

    with clinic["app"].app_context():
        doctor = clinic["db"].session.get(User, clinic["ids"]["doctor"])
        doctor.photo = "face.jpg"
        row = AboutPerson(name="د. فلان", photo="img/about/khafaga.jpg",
                          user_id=doctor.id)
        clinic["db"].session.add(row)
        clinic["db"].session.flush()
        assert row.photo_path() == "uploads/users/face.jpg"


# ------------------------------------------------------------- the seeding

def _seed(fx):
    from app.utils.project import seed_credits

    with fx["app"].app_context():
        made = seed_credits()
        fx["db"].session.commit()
        return made


def test_a_fresh_install_has_both_of_them(clinic):
    from app.models import Setting
    from app.models.about_person import AboutPerson

    made = _seed(clinic)
    assert made["doctors"] == 1 and made["developer"] > 0

    with clinic["app"].app_context():
        assert Setting.get("about_developer_note")
        assert Setting.get("about_developer_contact")
        assert AboutPerson.query.filter_by(name="أحمد جمال قنديل").first()


def test_nothing_is_seeded_pointing_at_a_picture_that_is_not_there(clinic):
    """A row pointing at a missing file draws a **broken circle**, which is
    worse than the initial it was meant to replace — the model says so itself.
    So the seed only claims a photograph it can see on disk, and this holds
    whether or not the files have been added yet."""
    from app.models import Setting
    from app.models.about_person import AboutPerson, photo_path_of

    _seed(clinic)
    root = os.path.join(os.path.dirname(__file__), "..", "app", "static")
    with clinic["app"].app_context():
        doc = AboutPerson.query.filter_by(name="أحمد جمال قنديل").first()
        claimed = [photo_path_of(Setting.get("about_developer_photo")),
                   doc.photo_path()]
    missing = [p for p in claimed if p
               and not os.path.exists(os.path.join(root, *p.split("/")))]
    assert missing == [], f"seeded but not shipped: {missing}"


def test_the_faces_are_picked_up_the_day_the_files_land(clinic):
    """No second change needed. The seed names the two paths; dropping the
    files in is the whole of it."""
    from app.utils.project import DEVELOPER_SEED, DOCTOR_SEED, shipped_photo

    named = [DEVELOPER_SEED["about_developer_photo"], DOCTOR_SEED[0]["photo"]]
    assert all(p.startswith("img/about/") for p in named), named

    root = os.path.join(os.path.dirname(__file__), "..", "app", "static")
    for path in named:
        on_disk = os.path.exists(os.path.join(root, *path.split("/")))
        assert (shipped_photo(path) == path) is on_disk


def test_running_it_again_adds_nothing(clinic):
    """Idempotent, like every other seed here."""
    _seed(clinic)
    again = _seed(clinic)
    assert again == {"developer": 0, "doctors": 0}


def test_a_person_the_clinic_deleted_stays_deleted(clinic):
    """The promise the migration beside this one already makes. An update that
    put somebody back would be the program overruling a decision the clinic
    made on purpose."""
    from app.models.about_person import AboutPerson

    _seed(clinic)
    db = clinic["db"]
    with clinic["app"].app_context():
        row = AboutPerson.query.filter_by(name="أحمد جمال قنديل").first()
        db.session.delete(row)
        db.session.commit()

    _seed(clinic)
    with clinic["app"].app_context():
        assert AboutPerson.query.filter_by(name="أحمد جمال قنديل").first() is None


def test_what_the_clinic_wrote_is_never_written_over(clinic):
    """A note somebody typed is theirs. The seed fills what is empty and
    stops."""
    from app.models import Setting

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("about_developer_note", "كلامنا إحنا")
        db.session.commit()

    _seed(clinic)
    with clinic["app"].app_context():
        assert Setting.get("about_developer_note") == "كلامنا إحنا"
        # and the fields it *had* nothing for still arrived
        assert Setting.get("about_developer_contact")


def test_they_can_be_edited_from_the_screen_like_anything_else(clinic):
    """The whole reason this is a seed and not a constant."""
    from app.models.about_person import AboutPerson

    _seed(clinic)
    db = clinic["db"]
    with clinic["app"].app_context():
        row = AboutPerson.query.filter_by(name="أحمد جمال قنديل").first()
        row.title = "استشاري وحدة الحضّانات"
        db.session.commit()

    _seed(clinic)
    with clinic["app"].app_context():
        row = AboutPerson.query.filter_by(name="أحمد جمال قنديل").first()
        assert row.title == "استشاري وحدة الحضّانات"


def test_the_page_draws_them(clinic):
    """End to end: the seed, the resolver and the template together."""
    _seed(clinic)
    page = clinic["sign_in"]("boss").get("/about").get_data(as_text=True)
    assert "أحمد جمال قنديل" in page
    assert "استشاري طب الأطفال وحديثي الولادة" in page
    assert "kids_khafaga@msn.com" in page
    # The circle draws whichever it has: a face once the files are shipped,
    # an initial until then. Never a broken image.
    assert "person-avatar" in page


# ------------------------------- the photograph that arrived one update late --
def _hide_shipped_photos(tmp_path):
    """Take the shipped pictures off the disk and give them back later."""
    import os
    import shutil

    here = os.path.join("app", "static", "img", "about")
    moved = []
    for name in ("khafaga.jpg", "kandil.jpg"):
        src = os.path.join(here, name)
        if os.path.exists(src):
            shutil.move(src, os.path.join(str(tmp_path), name))
            moved.append(name)

    def restore():
        # Idempotent: the test restores deliberately mid-way and the `finally`
        # calls it again, so a second run must be a no-op rather than a crash
        # that hides whatever the test was actually asserting.
        for name in list(moved):
            src = os.path.join(str(tmp_path), name)
            if os.path.exists(src):
                shutil.move(src, os.path.join(here, name))
    return restore


def test_a_face_that_shipped_later_still_arrives(clinic, tmp_path):
    """The gap this closes, reported from a real install.

    ``shipped_photo`` only claims a picture it can see, and seeding marks
    itself done — so a clinic that took the credits in one update and the
    photographs in the next kept its empty circles **for ever**, with both
    files sitting on its own disk.

    A missing face is not a decision somebody made, so it is filled in
    whenever a file exists to fill it with.
    """
    from app.models import Setting
    from app.models.about_person import AboutPerson
    from app.utils.project import seed_credits

    restore = _hide_shipped_photos(tmp_path)
    try:
        with clinic["app"].app_context():
            seed_credits()
            clinic["db"].session.commit()
            assert not (Setting.get("about_developer_photo") or "")
            assert not (AboutPerson.query.first().photo or "")
            restore()                      # the next update brings the files
            seed_credits()
            clinic["db"].session.commit()
            assert Setting.get("about_developer_photo") == "img/about/khafaga.jpg"
            assert AboutPerson.query.first().photo == "img/about/kandil.jpg"
    finally:
        restore()


def test_a_picture_the_clinic_chose_is_never_replaced(clinic, tmp_path):
    """The half that keeps the fix safe. An uploaded photograph is somebody's
    decision; only an **empty** one is an absence."""
    from app.models import Setting
    from app.models.about_person import AboutPerson
    from app.utils.project import seed_credits

    with clinic["app"].app_context():
        seed_credits()
        Setting.set("about_developer_photo", "theirs.jpg")
        person = AboutPerson.query.first()
        person.photo = "also-theirs.jpg"
        clinic["db"].session.commit()
        seed_credits()
        clinic["db"].session.commit()
        assert Setting.get("about_developer_photo") == "theirs.jpg"
        assert AboutPerson.query.first().photo == "also-theirs.jpg"


def test_the_words_are_still_only_written_once(clinic):
    """Only the face is refilled — every other field stays once-only.

    The backfill had to be narrowed to photographs deliberately: widening it
    to "anything empty" would put the shipped biography back on a clinic that
    deleted it on purpose, and deleting it **is** a decision. Checked across
    all the text fields rather than one, because widening the loop is a
    one-word mistake and a single-field check happens to survive it.
    """
    from app.models import Setting
    from app.utils.project import DEVELOPER_SEED, seed_credits

    words = [k for k in DEVELOPER_SEED if not k.endswith("_photo")]
    assert words, "no text fields to protect"
    with clinic["app"].app_context():
        seed_credits()
        clinic["db"].session.commit()
        for key in words:
            Setting.set(key, "")          # the clinic cleared them on purpose
        clinic["db"].session.commit()
        seed_credits()
        clinic["db"].session.commit()
        rewritten = [k for k in words if (Setting.get(k) or "").strip()]
    assert not rewritten, f"seeding wrote back over: {rewritten}"
