"""The child's file header in the design the owner chose: two buttons, the
rest under «خيارات أخرى» — and not one door lost on the way."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _page(clinic, who):
    return clinic["sign_in"](who).get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)


def _header(page):
    start = page.index("data-file-header")
    return page[start:page.index("<!-- Tabs -->", start)]


def test_two_buttons_and_every_other_door_in_the_menu(clinic):
    page = _header(_page(clinic, "doc"))
    actions = page[page.index("data-file-actions"):]
    before_menu = actions[:actions.index("data-file-more")]
    assert before_menu.count('class="btn ') == 2, "edit and a new prescription, nothing else"
    menu = actions[actions.index("data-file-more"):]
    for door in ("data-to-wristband", "data-fhir-export", "data-ips-export", "data-log-complaint",
                 "data-archive-exempt", "/archive", "ph2-danger"):
        assert door in menu, door
    assert menu.index("ph2-danger") > menu.index("data-archive-exempt"), "delete stays last"


def test_reception_gets_a_booking_instead_of_a_prescription(clinic):
    actions = _header(_page(clinic, "desk"))
    actions = actions[actions.index("data-file-actions"):actions.index("data-file-more")]
    assert "/prescriptions/new" not in actions
    assert "data-book-from-file" in actions


def test_it_is_drawn_from_the_theme_s_tokens():
    """Light and dark come from the same rules: no fixed white in the header."""
    css = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "css", "theme.css"),
               encoding="utf-8").read()
    block = css[css.index(".profile-header.ph2 {"):css.index("@media (max-width: 760px) { .ph2-actions")]
    assert "#fff;" not in block.replace("color: #fff;", "")
    assert ':root[data-theme="dark"] .profile-header.ph2' in css
    assert "prefers-reduced-motion: no-preference" in block
