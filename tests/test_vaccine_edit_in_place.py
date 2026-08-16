"""Editing a vaccine or a brand no longer opens a box on top of the page.

Reported from the screen: the pencil opened a 300px column pinned over the
list. It covered the two cards under it, ran off the edge of the window, and
the labels sat one on top of the other. The screenshot showed a form floating
across three vaccines at once.

The fields are the same fields. What changed is where they are: inside the
card, in the flow of the page, so opening one pushes the rest down instead of
hiding it. These tests check that — not the wording, and not the CSS.
"""
import os
import sys
from html.parser import HTMLParser

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _one_of_each(clinic):
    """A vaccine the clinic sells, with a brand — both rows have a pencil."""
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand

    with clinic["app"].app_context():
        vaccine = Vaccine(code="ROT1", name_ar="الروتا", is_mandatory=False,
                          sort_order=1)
        db.session.add(vaccine)
        db.session.flush()
        db.session.add(VaccineBrand(vaccine_id=vaccine.id, name="Rotarix",
                                    manufacturer="GSK", price=900.0))
        db.session.commit()


def _page(clinic):
    _one_of_each(clinic)
    return clinic["sign_in"]("boss").get("/vaccinations/manage").data.decode()


class _Ancestry(HTMLParser):
    """Records the open-tag stack above every named form control.

    Written this way because the fault was never in the field — it was in what
    the field was *inside*. Asserting on the field alone would have passed on
    the broken page too.
    """

    VOID = {"input", "br", "img", "hr", "meta", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag not in self.VOID:
            self.stack.append((tag, d))
        name = d.get("name")
        if tag in ("input", "select", "textarea") and name:
            self.found.setdefault(name, list(self.stack))
        if tag in self.VOID:
            return

    def handle_startendtag(self, tag, attrs):
        d = dict(attrs)
        name = d.get("name")
        if name:
            self.found.setdefault(name, list(self.stack))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def _ancestors_of(page, field):
    parser = _Ancestry()
    parser.feed(page)
    assert field in parser.found, \
        f"the field {field!r} is not on the screen at all any more"
    return parser.found[field]


# ------------------------------------------------------- nothing floats now

def test_no_edit_form_is_pinned_over_the_list(clinic):
    """`popform` was the class that took the form out of the page."""
    page = _page(clinic)

    assert "popform" not in page, \
        "an edit form is still positioned on top of the vaccine list"


@pytest.mark.parametrize("field", ["replaced_by_id", "margin_percent"])
def test_neither_form_hangs_off_the_pencil_any_more(clinic, field):
    """Both forms used to be children of the little row of icon buttons.

    A form in there is as wide as a button, which is why it had to be pulled
    out of the flow and pinned over the page to be usable at all. Being a
    sibling of that row instead of a child of it is the whole fix, so it is
    what is asserted — not the class name that used to do the pinning.
    """
    page = _page(clinic)

    for tag, attrs in _ancestors_of(page, field):
        style = (attrs.get("style") or "").replace(" ", "")
        # A *row* of flex children is what squeezed the form to a button's
        # width. The brand list is a flex column, which stacks full-width
        # blocks and is what the panel is supposed to be one of.
        in_a_row = "display:flex" in style and "flex-direction:column" not in style
        assert not in_a_row, \
            f"{field} is still inside the row of icon buttons (<{tag}>)"
        assert "position:absolute" not in style and "position:fixed" not in style, \
            f"{field} is inside a <{tag}> that is taken out of the flow"
        assert "popform" not in (attrs.get("class") or ""), \
            f"{field} is still in the floating box"


# ------------------------------------- and the fields themselves are all here

def test_every_field_that_was_editable_still_is(clinic):
    """The complaint was about the shape. Removing the form would 'fix' it."""
    page = _page(clinic)
    parser = _Ancestry()
    parser.feed(page)

    for field in ("name_ar", "replaced_by_id", "sort_order", "is_discontinued",
                  "manufacturer", "price", "purchase_price", "doctor_fee",
                  "price_policy", "margin_percent", "max_discount",
                  "doses_per_vial", "dose_ages", "catch_up_notes"):
        assert field in parser.found, f"{field} can no longer be edited"


def test_the_panel_can_actually_be_opened(clinic):
    """It is hidden until asked for, so something has to ask for it."""
    page = _page(clinic)

    assert page.count('x-show="edit"') >= 2, \
        "the vaccine panel, the brand panel, or both, can never be shown"
    assert page.count("edit = !edit") >= 2, \
        "there is no button that opens the panel"


def test_the_panel_has_a_state_to_read(clinic):
    """`x-show` with no `x-data` above it is a form nobody can ever open."""
    page = _page(clinic)

    for field in ("replaced_by_id", "margin_percent"):
        holders = [attrs for _tag, attrs in _ancestors_of(page, field)
                   if "x-data" in attrs]
        assert holders, f"{field} sits under no x-data — the panel is inert"
        assert any("edit" in (a.get("x-data") or "") for a in holders), \
            f"the x-data above {field} does not declare `edit`"


def test_saving_still_posts_to_the_same_places(clinic):
    """The routes did not change and nothing here should have moved them."""
    page = _page(clinic)

    assert "/vaccinations/manage/vaccine/" in page
    assert "/brand/" in page or "/manage/brand/" in page
