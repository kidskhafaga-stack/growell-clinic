"""Can this clinic open yet — and does anything say so before the first family?

A clinic is installed once and configured over a fortnight, in the wrong
order, by whoever is free. The pieces depend on each other and nothing said
so: commissions need services, booking needs working hours, taking money needs
a till. The gap gets found on the first real morning, with somebody at the
desk.

The checklist **inspects** rather than asking. That is the property worth
protecting: it must read the same whether a setting was made in the wizard, on
the ordinary screen, or restored from a backup — otherwise it becomes a second
source of truth about the clinic's own configuration, and the two drift.

Also pinned here: every step points at a screen that can actually be opened.
The first version of this shipped a step aimed at an endpoint needing a
``service_id``, which did not fail quietly — it took the whole page down with a
BuildError, so the screen meant to explain the setup was the one screen a new
clinic could not open.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ============================================== the checklist itself ========
def test_every_step_points_at_a_screen_that_opens(clinic):
    """The bug this replaces, and the reason it deserves a test.

    A step whose endpoint needs a URL argument raises BuildError while the
    page renders — so the checklist, the one screen that explains what is
    missing, is the screen that will not load on a brand-new clinic.
    """
    from flask import url_for

    from app.utils.readiness import STEPS

    with clinic["app"].test_request_context():
        for step in STEPS:
            url_for(step["endpoint"])      # raises if it needs arguments


def test_a_fresh_clinic_is_not_reported_ready(clinic):
    """Guarding the guard. A checklist that says "ready" out of the box is
    worse than none: it teaches somebody to ignore it."""
    from app.utils.readiness import summary

    with clinic["app"].app_context():
        state = summary()
        assert not state["ready"]
        assert state["required_done"] < state["required_total"]


def test_it_reads_the_database_not_a_record_of_being_asked(clinic):
    """Set something the ordinary way — never through the wizard — and the
    checklist has to notice. Otherwise it is a second source of truth about
    the clinic's own configuration, and the two will disagree."""
    from app.models import Setting
    from app.utils.readiness import review

    db = clinic["db"]
    with clinic["app"].app_context():
        before = {r["key"]: r["done"] for r in review()}
        assert not before["identity"]

        Setting.set("clinic_name", "عيادة النور")
        db.session.commit()

        after = {r["key"]: r["done"] for r in review()}
        assert after["identity"]


def test_a_step_waiting_on_another_is_shown_as_waiting(clinic):
    """Order here is dependency, not preference. Offering "doctor shares"
    before any service exists sends somebody to a screen that cannot help
    them yet."""
    from app.utils.readiness import review

    with clinic["app"].app_context():
        rows = {r["key"]: r for r in review()}
        assert rows["schedules"]["blocked_by"], "schedules need a doctor first"
        assert "doctors" in rows["schedules"]["blocked_by"]


def test_a_blocked_step_never_reads_as_done(clinic):
    """"Doctor shares" is satisfied by a clinic with no priced services — it
    passes vacuously. Showing that as a green tick before services exist
    teaches somebody to distrust every tick on the screen."""
    from app.utils.readiness import review

    with clinic["app"].app_context():
        rows = {r["key"]: r for r in review()}
        for row in rows.values():
            if row["blocked_by"]:
                assert not row["done"], f"{row['key']} claims done while blocked"


def test_optional_steps_do_not_hold_a_clinic_back(clinic):
    """A clinic that never wants the AI assistant must still be able to reach
    "ready". Otherwise the word means nothing and the banner never goes."""
    from app.utils.readiness import STEPS, summary

    with clinic["app"].app_context():
        optional = {s["key"] for s in STEPS if not s["required"]}
        assert {"ai", "vaccines", "drugs"} <= optional
        state = summary()
        # `ready` counts required steps only.
        assert state["required_total"] < len(STEPS)


def test_the_next_step_offered_is_one_that_can_be_done_now(clinic):
    """Pointing somebody at a blocked step is how a checklist stops being
    followed."""
    from app.utils.readiness import summary

    with clinic["app"].app_context():
        state = summary()
        assert state["next"] is not None
        assert not state["next"]["blocked_by"]
        assert not state["next"]["done"]


# ============================================== reachable when it is needed =
def test_the_checklist_opens_on_a_clinic_that_is_not_set_up(clinic):
    """The trap it was built inside. An unconfigured clinic redirects its
    owner to the facility form, so the screen that *explains* the setup was
    hidden behind the very step it introduces."""
    from app.models import User

    db = clinic["db"]
    with clinic["app"].app_context():
        boss = db.session.get(User, clinic["ids"]["admin"])
        boss.is_super_admin = True
        db.session.commit()

    response = clinic["sign_in"]("boss").get("/settings/wizard")
    assert response.status_code == 200, "the setup screen redirected away"


def test_its_own_buttons_are_not_swallowed_by_that_redirect(clinic):
    """A POST eaten by the same redirect looks like a button that does
    nothing — which is exactly how the drug loader behaved."""
    from app.models import Drug, User

    db = clinic["db"]
    with clinic["app"].app_context():
        boss = db.session.get(User, clinic["ids"]["admin"])
        boss.is_super_admin = True
        db.session.commit()
        before = Drug.query.count()

    clinic["sign_in"]("boss").post("/settings/wizard/seed-drugs",
                                   follow_redirects=True)

    with clinic["app"].app_context():
        assert Drug.query.count() > before


def test_an_admin_is_told_on_the_dashboard(clinic):
    """Nobody opens a settings screen to find out that settings are missing."""
    from app.utils.facility import apply_facility

    db = clinic["db"]
    with clinic["app"].app_context():
        apply_facility("clinic", "عيادة النور", [], [])
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/dashboard",
                                         follow_redirects=True).data.decode()
    assert "/settings/wizard" in page


def test_the_reminder_can_be_switched_off_without_losing_the_screen(clinic):
    """A clinic that decided against vaccinations should not be nagged about
    vaccinations for ever — but "what did we never finish" is a question that
    comes back six months later."""
    from app.utils.facility import apply_facility
    from app.utils.readiness import dismissed

    db = clinic["db"]
    with clinic["app"].app_context():
        apply_facility("clinic", "عيادة النور", [], [])
        db.session.commit()

    client = clinic["sign_in"]("boss")
    client.post("/settings/wizard/dismiss", follow_redirects=True)

    with clinic["app"].app_context():
        assert dismissed()

    page = client.get("/dashboard", follow_redirects=True).data.decode()
    assert "/settings/wizard" not in page
    assert client.get("/settings/wizard").status_code == 200


# ============================================== the catalogues it checks ====
def test_the_whole_of_icd10_is_searchable(clinic):
    """It shipped with 83 codes and a docstring telling the doctor to type
    anything else by hand. A doctor who searches and finds nothing writes free
    text, and a file of free text is one nothing can ever report on."""
    from app.utils.icd import coverage, search_icd

    counts = coverage()
    assert counts["10"]["full"] > 70000, "the full ICD-10 set is not loaded"

    # A code nobody would curate by hand, found by name.
    found = search_icd("Galeazzi", limit=3)
    assert found and all("Galeazzi" in row["en"] for row in found)


def test_the_arabic_diagnoses_a_clinic_writes_daily_still_come_first(clinic):
    """Seventy thousand English titles must not bury the twenty Arabic ones a
    paediatrician actually types. Ranking is the whole design here."""
    from app.utils.icd import search_icd

    top = search_icd("pneumonia", limit=3)[0]
    assert top["code"] == "J18.9"
    assert top["ar"], "an English-only row outranked the curated Arabic one"

    fever = search_icd("حرارة", limit=3)
    assert fever and fever[0]["code"] == "R50.9"


def test_icd11_is_reported_as_absent_rather_than_faked(clinic):
    """WHO publishes ICD-11 through an API needing the clinic's own
    credentials; there is no public file to bundle. Shipping a partial list
    labelled ICD-11 would be worse than saying so — a doctor would search,
    find nothing, and conclude the code does not exist."""
    from app.utils.icd import coverage

    counts = coverage()
    assert "11" in counts
    assert counts["11"]["total"] == 0


def test_an_imported_classification_behaves_like_the_bundled_one(clinic):
    """The path out. An imported ICD-11 has to be a first-class citizen, not a
    second code path that behaves differently."""
    from app.utils.icd import coverage, install_full, lookup_icd, search_icd

    written = install_full("11", [("CA40", "Pneumonia"),
                                  ("1A00", "Cholera")])
    try:
        assert written == 2
        assert coverage()["11"]["full"] == 2
        assert lookup_icd("CA40", version="11")["en"] == "Pneumonia"
        hits = search_icd("Cholera", limit=20, version="11")
        assert any(row["code"] == "1A00" for row in hits)
    finally:
        install_full("11", [])


def test_the_egyptian_drug_register_is_loadable_and_idempotent(clinic):
    """Twenty-five thousand trade names with their prices. Re-running it on an
    upgrade must not touch a clinic's own edits — their price beats a bundled
    file's every time."""
    from app.models import Drug
    from app.utils.egypt_drugs import available, seed_register

    db = clinic["db"]
    assert available() > 24000

    with clinic["app"].app_context():
        first = seed_register(limit=500)
        assert first > 0
        edited = Drug.query.filter(Drug.price.isnot(None)).first()
        edited.price = 999.0
        db.session.commit()
        edited_name = edited.trade_name

        again = seed_register(limit=500)
        assert again == 0, "a second run duplicated the register"
        kept = Drug.query.filter_by(trade_name=edited_name).one()
        assert kept.price == 999.0, "a re-run overwrote the clinic's own price"


def test_a_register_entry_is_never_linked_to_a_different_ingredient(clinic):
    """The dangerous shortcut this rules out.

    Matching "PARACETAMOL+CAFFEINE" to paracetamol — by prefix, by first
    ingredient, by anything but the whole name — would hand a doctor a
    calculated paediatric dose that ignores the second ingredient entirely,
    and it would look exactly like a real one. So the link is exact or absent.

    A combination that matches a combination we genuinely hold ("Vitamins A +
    D") is a correct link, which is why this checks the *names agree* rather
    than banning the plus sign.
    """
    from app.models import Drug, GenericDrug
    from app.utils.drugbook_seed import seed_drugbook
    from app.utils.egypt_drugs import seed_register

    db = clinic["db"]
    with clinic["app"].app_context():
        seed_drugbook()
        db.session.commit()
        seed_register()

        generics = {g.id: (g.name_en, g.name_ar) for g in GenericDrug.query.all()}
        mismatched = []
        for drug in Drug.query.filter(Drug.generic_id.isnot(None)).all():
            names = {n.strip().upper() for n in generics.get(drug.generic_id, ())
                     if n}
            if (drug.generic_name or "").strip().upper() not in names:
                mismatched.append(drug.trade_name)
        assert not mismatched, (
            "these carry dosing from an ingredient that is not what is in the "
            "box: " + ", ".join(mismatched[:5]))


def test_a_register_entry_with_no_match_is_still_usable(clinic):
    """Most of the register has no ingredient we can dose. Those brands still
    have to be findable and printable — that is the whole reason they are
    seeded — they simply carry no dose calculator."""
    from app.models import Drug
    from app.utils.egypt_drugs import seed_register

    with clinic["app"].app_context():
        seed_register(limit=800)
        unlinked = Drug.query.filter(Drug.generic_id.is_(None)).first()
        assert unlinked is not None
        assert unlinked.trade_name and unlinked.is_active
        assert unlinked.dose_per_kg is None


def test_the_register_arrives_with_the_ordinary_install(clinic):
    """The question that prompted this: does it actually get planted?

    Behind a button it is a feature most clinics never find. Seeded with the
    rest of the catalogues it is simply what the program knows, which is the
    difference between a doctor searching a market and a doctor searching 292
    names.
    """
    from app.models import Drug
    from app.utils.reference import seed_reference

    with clinic["app"].app_context():
        out = seed_reference()
        assert out.get("egypt_drug_register", 0) > 24000
        assert Drug.query.count() > 24000


def test_the_register_gets_its_dosing_whichever_order_the_seeders_run(clinic):
    """Two thousand brands' dose calculators must not rest on a list order.

    The register links to an ingredient on an exact name match, so seeding it
    before the ingredients would link nothing — except that ``_drugbook``
    finishes by running ``link_existing_drugs``, which back-fills whatever is
    still unlinked. That is what makes the order safe, and it is worth pinning:
    without it, moving one line in a seeder list would silently strip the
    paediatric dosing off every register brand while every count on the screen
    still looked right.
    """
    from app.models import Drug, GenericDrug
    from app.utils.drugbook_seed import (link_existing_drugs, seed_drugbook,
                                         seed_interactions)
    from app.utils.egypt_drugs import seed_register

    db = clinic["db"]
    with clinic["app"].app_context():
        # The wrong way round on purpose: register first, ingredients after.
        seed_register(limit=4000)
        assert GenericDrug.query.count() == 0
        assert Drug.query.filter(Drug.generic_id.isnot(None)).count() == 0
        # Held by id, because the curated seeder adds its own 292 brands next
        # and those link at creation — counting all linked drugs afterwards
        # would be satisfied by the curated ones alone and prove nothing.
        register_ids = [d.id for d in Drug.query.all()]

        seed_drugbook()
        link_existing_drugs()
        seed_interactions()
        db.session.commit()

        dosable = Drug.query.filter(Drug.id.in_(register_ids),
                                    Drug.generic_id.isnot(None)).count()
        assert dosable > 50, (
            "register brands seeded before their ingredients never got "
            "linked, so they carry no paediatric dosing")
