"""The About page's photo upload, made the same thing as everywhere else.

Asked for plainly: *"the picture upload on the About page — I want it like
the profile pictures and the patient pictures, the same system."* It was
three bare `<input type="file">` boxes: the browser's own control, which
shows a file name and no picture, has no way to see what is already there,
and hands the server whatever shape and size the phone's camera produced.

The rest of the program has had one answer to this for a while — a thumbnail
of what is stored now, one button, and a square cropper that opens on pick so
the person uploading decides which part of the photograph survives. These
photographs are drawn inside circles by the page's own `face()` macro, so an
uncropped one is cropped regardless; the only question was who chose.

Three places on one page, and they were three copies of the same markup, so
they are now one macro. The count is asserted, because a fourth copy pasted
in later is exactly how the first three happened.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PAGE = os.path.join(ROOT, "app/templates/main/about.html")


@pytest.fixture()
def page(clinic):
    """The About page as an admin sees it, with a person already credited."""
    from app.extensions import db
    from app.utils import project

    with clinic["app"].app_context():
        person = project.add_person({"name": "د. تجربة", "title": "استشاري"}, {})
        # With a photograph on file, because half of what the picker has to
        # show — the thumbnail and the way back to no photograph — only
        # exists when there is one.
        person.photo = "face.png"
        db.session.commit()

    return clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()


# ------------------------------------------------------- the same widget

def test_the_bare_browser_file_box_is_gone(page):
    """`class="input" type="file"` is the control that shows a file name and
    nothing else. Its absence is the request, stated exactly."""
    assert not re.search(r'<input[^>]*class="input"[^>]*type="file"', page), \
        "the About page still uses the plain browser file box"


def test_the_picker_crops_like_the_profile_photo_does(page):
    """`data-crop="square"` is what opens the cropper — one attribute, the
    same one the profile photo carries, handled by the same listener."""
    boxes = re.findall(r'<input type="file"[^>]*name="photo"[^>]*>', page)

    assert boxes, "there is no photo input on the page at all"
    for box in boxes:
        assert 'data-crop="square"' in box, box
        assert "hidden" in box, \
            "the file input is still visible, so the styled button is decoration"


def test_it_is_the_same_attribute_the_shared_cropper_listens_for(page):
    """Written against the JavaScript rather than assumed: a test that pins an
    attribute nothing reads passes for ever while the feature does nothing."""
    with open(os.path.join(ROOT, "app/static/js/app.js"), encoding="utf-8") as fh:
        source = fh.read()

    assert 'input[type="file"][data-crop="square"]' in source


def test_what_is_already_there_is_shown(page):
    """The half a file name cannot do. Uploading a replacement without being
    able to see the current one is guessing."""
    from app.utils import project

    assert 'uploads/about/' in page or "person-avatar" in page

    # And the picker itself carries a preview slot rather than only the page's
    # display copy: the two are in different places on the screen.
    with open(PAGE, encoding="utf-8") as fh:
        macro = fh.read().split("{% macro photo_box")[1].split("{% endmacro %}")[0]
    assert "uploads/about/" in macro, \
        "the picker shows no thumbnail of the stored photograph"


# --------------------------------------------------- one copy, not three

def test_the_three_places_are_one_macro(page):
    """A credited person, the developer block and the add form. They were
    three copies of the same markup, which is how they came to differ."""
    with open(PAGE, encoding="utf-8") as fh:
        source = fh.read()

    assert source.count("{% macro photo_box") == 1
    assert source.count("photo_box(") == 4, \
        "the macro is defined and called three times — no more, no fewer"


def test_removing_a_photo_still_works(page):
    """The checkbox was the only way back to no photograph at all, and it
    survived the rewrite. An empty file input means "unchanged", not "clear"."""
    assert 'name="drop_photo"' in page


def test_the_add_form_still_says_what_it_wants(page):
    """The hint about the photograph belongs on the form where somebody is
    adding one for the first time, and only there."""
    from app.i18n import t

    with open(PAGE, encoding="utf-8") as fh:
        source = fh.read()

    assert source.count("about.photo_hint") == 1


# ------------------------------------------------------- it still uploads

def test_a_photograph_still_reaches_the_page(clinic):
    """The picker is markup; this is the thing it exists to do.

    This posts the field itself, so it holds the *route* — it cannot see a
    form control renamed in the template, which is what the `name="photo"`
    assertion above is for. Measured: rename the input and this still passes.
    """
    import io

    from app.extensions import db
    from app.utils import project

    with clinic["app"].app_context():
        person = project.add_person({"name": "د. صورة"}, {})
        db.session.commit()
        person_id = person.id

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    clinic["sign_in"]("boss").post(
        "/about/people",
        data={"action": "edit", "id": str(person_id), "name": "د. صورة",
              "photo": (io.BytesIO(png), "face.png")},
        content_type="multipart/form-data", follow_redirects=True)

    with clinic["app"].app_context():
        again = project.people()
        mine = [p for p in again["doctors"] if p.id == person_id]
        assert mine and mine[0].photo, "the upload did not reach the record"
