"""How big a doctor's signature and stamp come out on paper.

Asked for directly: *"the images uploaded for the doctor — the signature —
can I control its size in printing, and the stamp too."* The answer was no.
The printed box was two pairs of numbers written into the prescription
template — 60×200 for a signature, 90×140 for a stamp — so a scan that came
out postage-stamp sized stayed that way for ever, and one that swallowed the
bottom of the page did too. Nobody can retake a stamp; it is an object in a
drawer.

**Both dimensions, together.** A box that grew in height alone squashes a
wide signature instead of enlarging it, which is the exact failure this
exists to fix.

**Clamped.** A percentage typed or posted from anywhere cannot make the image
vanish or eat the sheet. The range is 40–250; outside it the number is pulled
back rather than refused, because a doctor dragging a slider is not filling in
a form that can be wrong.

**Silence is not a reset.** Only read when the form actually posted it. There
are two screens that carry these uploads — the doctor's own profile and the
admin's setup page — and a third that carries neither must not be able to
return a doctor's stamp to 100% by saying nothing.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def doctor(clinic):
    """A doctor with a signature and a stamp already on file."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = User.query.filter_by(role="doctor").first()
        doc.signature_file = "sig.png"
        doc.stamp_file = "stamp.png"
        db.session.commit()
        return clinic, doc.id


# ------------------------------------------------------------ the arithmetic

def test_the_default_is_what_the_paper_always_printed(doctor):
    """Nothing moves for a clinic that never touches this."""
    clinic, doc_id = doctor
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        assert doc.print_image_box("signature_file") == (60, 200)
        assert doc.print_image_box("stamp_file") == (90, 140)


def test_it_grows_in_both_directions(doctor):
    """Height alone squashes a wide signature rather than enlarging it."""
    clinic, doc_id = doctor
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        doc.signature_scale = 200
        db.session.commit()

        height, width = doc.print_image_box("signature_file")

    assert (height, width) == (120, 400)


def test_the_two_are_set_apart_from_each_other(doctor):
    """One knob for both would be no answer: a stamp is round and a signature
    is wide, and they are different objects on different scanners."""
    clinic, doc_id = doctor
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        doc.stamp_scale = 150
        db.session.commit()

        assert doc.print_image_box("stamp_file") == (135, 210)
        assert doc.print_image_box("signature_file") == (60, 200)


@pytest.mark.parametrize("posted,expected", [
    (0, 40), (-5, 40), (9999, 250), ("", 100), ("abc", 100), (None, 100)])
def test_a_size_that_would_break_the_page_is_pulled_back(posted, expected):
    from app.models.user import clamp_print_scale

    assert clamp_print_scale(posted) == expected


# ------------------------------------------------------------- on the paper

def test_the_prescription_uses_it(doctor):
    """The template asks the doctor rather than carrying the numbers.

    Read out of the rendered style attribute, because the failure this
    replaces was a literal in exactly that place.
    """
    clinic, doc_id = doctor
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        doc.stamp_scale = 200
        db.session.commit()

    with open(os.path.join(os.path.dirname(__file__), "..",
                           "app/templates/prescriptions/_paper.html"),
              encoding="utf-8") as fh:
        source = fh.read()

    assert "max-height:90px;max-width:140px" not in source, \
        "the stamp's printed size is still written into the template"
    assert "max-height:60px;max-width:200px" not in source, \
        "the signature's printed size is still written into the template"
    assert source.count("print_image_box") == 2


# ------------------------------------------------------------- the screens

def test_the_doctor_can_set_it_on_their_own_profile(clinic):
    from app.extensions import db
    from app.models import User

    client = clinic["sign_in"]("doc")
    page = client.get("/profile", follow_redirects=True).data.decode()

    assert 'name="signature_scale"' in page and 'name="stamp_scale"' in page, \
        "the doctor's own profile offers no way to set it"

    client.post("/profile", data={"signature_scale": "180",
                                  "stamp_scale": "70"},
                follow_redirects=True)

    with clinic["app"].app_context():
        doc = User.query.filter_by(role="doctor").first()
        assert (doc.signature_scale, doc.stamp_scale) == (180, 70)


def test_the_admin_can_set_it_when_setting_the_doctor_up(clinic):
    """The stamp is in the office manager's hand on the doctor's first day,
    which is the whole reason the uploads live on this screen too."""
    from app.extensions import db
    from app.models import User

    with clinic["app"].app_context():
        doc_id = User.query.filter_by(role="doctor").first().id

    client = clinic["sign_in"]("boss")
    page = client.get(f"/users/doctors/{doc_id}",
                      follow_redirects=True).data.decode()
    assert 'name="stamp_scale"' in page, \
        "the setup screen uploads a stamp and cannot size it"

    client.post(f"/users/doctors/{doc_id}/rx",
                data={"signature_scale": "140", "stamp_scale": "160"},
                follow_redirects=True)

    with clinic["app"].app_context():
        doc = db.session.get(User, doc_id)
        assert (doc.signature_scale, doc.stamp_scale) == (140, 160)


def test_a_form_that_does_not_carry_it_leaves_it_alone(clinic):
    """Silence is not a reset. Posting the profile form from a screen without
    the slider must not quietly return the stamp to 100%."""
    from app.extensions import db
    from app.models import User

    client = clinic["sign_in"]("doc")
    client.post("/profile", data={"stamp_scale": "175"}, follow_redirects=True)
    client.post("/profile", data={"full_name": "د. تجربة"},
                follow_redirects=True)

    with clinic["app"].app_context():
        assert User.query.filter_by(role="doctor").first().stamp_scale == 175


# --------------------------------------------------------------- the plumbing

def test_the_new_columns_are_registered_for_an_existing_database(clinic):
    """A column added to a table that already exists is not created by
    `create_all`. An installation upgrading in place would crash on the
    profile page instead."""
    from app.utils.schema import ADDITIONS

    registered = {(table, column) for table, column, *_ in ADDITIONS}
    for column in ("signature_scale", "stamp_scale"):
        assert ("users", column) in registered, column


def test_the_wording_exists_in_both_languages(clinic):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert "print_size" in json.load(fh)["profile"], lang
