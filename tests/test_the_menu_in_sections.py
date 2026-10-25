"""The side menu: a search at its top, and sections only in a hospital.

Asked after a video of a menu with a search box and sections that fold. A
hospital running every department had 38 doors in one column. The owner's
answer when shown the two side by side: *«نفذ كده»* — the sections where a
hospital department is on, and a clinic keeps the list it had with only the
search added (`utils/nav_menu`).
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _modules(fx, **on):
    from app.models import Setting

    with fx["app"].app_context():
        for name, value in on.items():
            Setting.set(f"mod_enabled:{name}", "1" if value else "0")
        fx["db"].session.commit()


def _nav(page):
    return page[page.index('class="sidebar__nav'):page.index("</nav>")]


def _doors(page):
    """The menu's links, in the order they are drawn."""
    return re.findall(r'class="nav-item gc-press[^"]*"\s+href="([^"]+)"', _nav(page))


# ------------------------------------------------------- a clinic keeps it --
def test_a_clinic_keeps_its_list_and_gains_only_the_search(clinic):
    page = clinic["sign_in"]("boss").get("/dashboard").get_data(as_text=True)
    assert "data-nav-find" in page
    assert "data-nav-sections" not in page and "data-nav-section=" not in page
    doors = _doors(page)
    # The order the menu has always had: the modules, then the doctor's own
    # screens, then complaints and incidents, and the guide last.
    assert doors[0] == "/dashboard"
    assert doors[-1] == "/guide"
    assert doors.index("/complaints/") < doors.index("/incidents/report")


def test_a_lab_films_or_pharmacy_do_not_make_a_clinic_a_hospital(clinic):
    _modules(clinic, labs=True, imaging=True, pharmacy=True)
    page = clinic["sign_in"]("boss").get("/dashboard").get_data(as_text=True)
    assert "data-nav-sections" not in page


# -------------------------------------------------- a hospital in sections --
def test_a_hospital_gets_sections_with_the_same_doors(clinic):
    boss = clinic["sign_in"]("boss")
    before = _doors(boss.get("/dashboard").get_data(as_text=True))
    _modules(clinic, beds=True)
    page = boss.get("/dashboard").get_data(as_text=True)
    assert "data-nav-sections" in page
    after = _doors(page)
    # Same doors, each once — only the order may differ, and the one door
    # the beds module adds.
    assert len(after) == len(set(after))
    assert set(after) - set(before) == {"/beds/"}
    assert set(before) <= set(after)
    nav = _nav(page)
    for section in ("clinic", "hospital", "money", "quality", "reports", "admin"):
        assert f'data-nav-section="{section}"' in nav, section
    # The beds door sits in the hospital's section, the settings in admin.
    hospital = nav[nav.index('data-nav-section="hospital"'):nav.index('data-nav-section="money"')]
    assert 'href="/beds/"' in hospital


def test_the_section_holding_this_page_is_the_one_that_never_folds(clinic):
    _modules(clinic, beds=True)
    page = clinic["sign_in"]("boss").get("/patients/").get_data(as_text=True)
    assert 'navSections(&#34;clinic&#34;)' in page or 'navSections("clinic")' in page


def test_a_section_with_no_door_for_this_person_is_not_drawn(clinic):
    _modules(clinic, beds=True)
    page = clinic["sign_in"]("acct").get("/dashboard").get_data(as_text=True)
    nav = _nav(page)
    assert 'data-nav-section="hospital"' not in nav
    assert 'data-nav-section="money"' in nav


def test_arrange_keeps_the_menu_order_and_loses_nothing():
    from app.utils.nav_menu import arrange

    items = [{"key": k} for k in ("settings", "dashboard", "finance", "patients",
                                  "something_added_later", "beds")]
    out = arrange(items)
    assert [s for s, _ in out] == ["clinic", "hospital", "money", "admin"]
    assert [i["key"] for i in dict(out)["clinic"]] == ["dashboard", "patients"]
    assert [i["key"] for i in dict(out)["admin"]] == ["settings", "something_added_later"]
    assert sum(len(rows) for _, rows in out) == len(items)


# --------------------------------------------------------------- the search --
def test_the_search_finds_children_for_whoever_opens_the_files(clinic):
    boss = clinic["sign_in"]("boss")
    rows = boss.get("/nav/find?q=طفل").get_json()
    assert rows and rows[0]["name"] == "طفل"
    assert rows[0]["url"] == f"/patients/{clinic['ids']['child']}"
    assert boss.get("/nav/find?q=P1").get_json()[0]["number"] == "P1"
    # One letter is every child; it waits for the second.
    assert boss.get("/nav/find?q=ط").get_json() == []


def test_the_search_finds_no_child_for_someone_without_the_files(clinic):
    assert clinic["sign_in"]("acct").get("/nav/find?q=طفل").get_json() == []
    reply = clinic["app"].test_client().get("/nav/find?q=طفل")
    assert reply.status_code in (302, 401)


def test_ctrl_k_is_on_the_list_of_shortcuts_and_in_the_guide(clinic):
    with open(os.path.join(ROOT, "app", "templates", "shell.html"), encoding="utf-8") as fh:
        shell = fh.read()
    assert "'Ctrl + K'" in shell and "e.code === 'KeyK'" in shell
    from app.utils.handbook import SECTIONS

    basics = next(s for s in SECTIONS if s["key"] == "basics")
    assert any("Ctrl+K" in ar and "Ctrl+K" in en for ar, en in basics["lines"])


# ------------------------------------------------- the patients' list header --
def test_the_patients_tools_wrap_instead_of_leaving_the_screen(clinic):
    """Ten buttons in a row that never wrapped: at 1366 «إضافة مريض» sat half
    off the screen, and on a phone seven of the ten could not be reached."""
    page = clinic["sign_in"]("boss").get("/patients/").get_data(as_text=True)
    assert "data-patient-tools" in page and "data-add-patient" in page
    rule = page[page.index(".pl-tools {"):]
    assert "flex-wrap:wrap" in rule[:120]
    tools = page[page.index("data-patient-tools"):page.index("data-add-patient")]
    for door in ("/patients/analytics", "/patients/archive", "/patients/import"):
        assert door in tools, door


def test_the_phone_menu_opens_in_arabic_too():
    """`body[dir="rtl"] .sidebar` outweighed `.sidebar.is-open`, so on a
    phone in Arabic the menu button darkened the screen and the menu stayed
    off its edge. Found while checking the new menu on a phone."""
    with open(os.path.join(ROOT, "app", "static", "css", "theme.css"), encoding="utf-8") as fh:
        css = fh.read()
    assert 'body[dir="rtl"] .sidebar.is-open { transform: none; }' in css


def test_the_search_reads_a_phone_and_a_parents_name_like_the_list(clinic):
    """The same search as the patients' list (`apply_patient_search`): a
    phone in any digits, and the name of a parent, find the child."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name="سامح")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, full_name="منى سامح", relation="mother",
                              phone="01001234567"))
        kid = db.session.get(Patient, clinic["ids"]["child"])
        kid.family_id = fam.id
        db.session.commit()
    boss = clinic["sign_in"]("boss")
    for q in ("01001234567", "٠١٠٠١٢٣٤٥٦٧", "منى سامح"):
        rows = boss.get(f"/nav/find?q={q}").get_json()
        assert [r["number"] for r in rows] == ["P1"], q


def test_the_administration_can_switch_the_search_off_for_everybody(clinic):
    """Asked: «هل اقدر افعل او اوقف البحث؟» — and who decides: the
    administration, for the whole clinic. On until then."""
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    settings = boss.get("/settings/").get_data(as_text=True)
    assert "data-nav-find-setting" in settings
    box = settings[settings.index('id="nav_find"'):][:200]
    assert "checked" in box, "the search is on until somebody switches it off"
    with clinic["app"].app_context():
        Setting.set("nav_find", "0")
        clinic["db"].session.commit()
    for who in ("boss", "doc", "desk"):
        page = clinic["sign_in"](who).get("/dashboard").get_data(as_text=True)
        assert 'class="navfind"' not in page and "data-nav-find>" not in page, who
    assert boss.get("/nav/find?q=طفل").get_json() == []
