"""How an inpatient bill adds itself up.

Asked for as a summary over a detail: *«يكون عندك ملخص رئيسي … وفي نفس الوقت
زر عرض التفاصيل»* — الإقامة كذا، العمليات كذا، الأدوية كذا. A summary needs a
grouping, and the service already carried two that could not be it:

* ``category`` — accounting, and a **fixed** list, because the code reads its
  values by name (``vaccination_fee`` decides which half of an invoice is
  posted to vaccination revenue). A clinic inventing one would be inventing a
  rule nothing implements.
* ``service_type`` — operational, and already editable from the screen, but it
  answers "what kind of work is this", not "which part of the bill".

Neither has an accommodation, an anaesthesia or a nursing value, and neither
should be made to. So the bill section is a **third** axis — and unlike the
category it is safe to open, for one reason that these tests exist to hold:
**nothing reads a section by name.** Totals group by whatever exists, and a
percentage charge names the sections it is levied on. A hospital typing
«مستلزمات غرفة العمليات» gets a section that works the same minute.

That last part is not decoration. The service charge an Egyptian private
hospital adds is not a percentage of the total — it is a percentage of the
total *excluding medicines*. "Which sections" is what makes such a charge
definable at all, and checkable by a family afterwards.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A hospital-shaped price list: consultations, a ward, incubators, teeth."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting, User
        from app.utils.invoice_sections import ensure_seeded
        from app.utils.services import seed_services_for_caps

        caps = ["general_consultation", "followup", "ward", "icu", "nicu",
                "dentistry", "laboratory"]
        Setting.set("facility_capabilities", str(caps).replace("'", '"'))
        seed_services_for_caps(caps)
        ensure_seeded()

        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)
        db.session.commit()

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "sign_in": sign_in}


def _svc(code):
    from app.models import Service

    return Service.query.filter_by(code=code).first()


# --------------------------------------------------- nobody labels 300 rows --
def test_a_service_nobody_labelled_still_lands_somewhere(clinic):
    """**The upgrade case.** A clinic with three hundred priced rows is not
    going to label them one at a time before the summary works, so every
    service answers from its category until somebody says otherwise."""
    with clinic["app"].app_context():
        assert _svc("SVC-KASHF").invoice_section is None      # nobody said
        assert _svc("SVC-KASHF").section_key() == "medical"   # and it still lands


def test_the_night_is_accommodation_even_though_its_category_is_other(clinic):
    """**The line everybody reads first.** The night is categorised ``other``
    — it is not a consultation, a procedure or a lab test — so deriving from
    the category alone would drop the headline row of an inpatient bill into
    "unclassified"."""
    with clinic["app"].app_context():
        for code in ("SVC-WARD", "SVC-ICU", "SVC-NICU"):
            assert _svc(code).category == "other"
            assert _svc(code).section_key() == "accommodation", code


def test_placing_the_shipped_ones_is_a_fact_not_a_guess(clinic):
    """Keyed by the code **this program shipped**, the same footing as the
    capability filter. A clinic's own service is never placed by guesswork."""
    from app.models import Service

    with clinic["app"].app_context():
        mine = Service(name="حاجة من عندنا", code="OURS-1", price=100,
                       category="other", is_active=True)
        clinic["db"].session.add(mine)
        clinic["db"].session.commit()
        assert mine.section_key() == "other"      # honest: not classified


def test_what_somebody_chose_beats_what_the_program_derived(clinic):
    with clinic["app"].app_context():
        row = _svc("SVC-KASHF")
        assert row.section_key() == "medical"
        row.invoice_section = "surgery"
        clinic["db"].session.commit()
        assert row.section_key() == "surgery"


def test_nothing_ends_up_unclassified_on_a_shipped_list(clinic):
    """A summary whose biggest row is «غير مصنّف» is a summary nobody trusts."""
    from app.models import Service

    with clinic["app"].app_context():
        stray = [s.name for s in Service.query.all()
                 if s.section_key() == "other"]
        assert not stray, f"unplaced: {stray}"


# ------------------------------------------------- the catalogue is theirs --
def test_the_sections_are_seeded_once_and_only_once(clinic):
    from app.models import InvoiceSection
    from app.utils.invoice_sections import ensure_seeded

    with clinic["app"].app_context():
        before = InvoiceSection.query.count()
        assert ensure_seeded() == 0          # idempotent
        assert InvoiceSection.query.count() == before


def test_a_hospital_can_add_its_own_section(clinic):
    """The whole reason this axis opens where the category does not."""
    from app.models import InvoiceSection

    clinic["sign_in"]().post("/finance/services/sections/new",
                             data={"name": "مستلزمات غرفة العمليات",
                                   "name_en": "OR supplies"},
                             follow_redirects=True)
    with clinic["app"].app_context():
        row = InvoiceSection.query.filter_by(is_system=False).first()
        assert row is not None
        assert row.name_ar == "مستلزمات غرفة العمليات"
        assert row.key and row.key.isascii(), "the key must be stable ASCII"


def test_a_built_in_section_cannot_be_deleted(clinic):
    """Deleting «الإقامة» would detach every night already billed under it."""
    from app.models import InvoiceSection

    with clinic["app"].app_context():
        sid = InvoiceSection.query.filter_by(key="accommodation").first().id
    clinic["sign_in"]().post(f"/finance/services/sections/{sid}/delete",
                             follow_redirects=True)
    with clinic["app"].app_context():
        assert InvoiceSection.query.filter_by(key="accommodation").first()


def test_a_section_in_use_is_not_deleted_from_under_the_money(clinic):
    """Reassigning silently would move money onto a summary row nobody chose."""
    from app.models import InvoiceSection

    client = clinic["sign_in"]()
    client.post("/finance/services/sections/new",
                data={"name": "بند مؤقت", "name_en": "Temp"},
                follow_redirects=True)
    with clinic["app"].app_context():
        row = InvoiceSection.query.filter_by(is_system=False).first()
        sid, key = row.id, row.key
        _svc("SVC-KASHF").invoice_section = key
        clinic["db"].session.commit()

    client.post(f"/finance/services/sections/{sid}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert InvoiceSection.query.get(sid) is not None, "deleted under a service"


def test_one_the_clinic_added_and_nobody_uses_can_go(clinic):
    from app.models import InvoiceSection

    client = clinic["sign_in"]()
    client.post("/finance/services/sections/new",
                data={"name": "غلط", "name_en": "Oops"}, follow_redirects=True)
    with clinic["app"].app_context():
        sid = InvoiceSection.query.filter_by(is_system=False).first().id
    client.post(f"/finance/services/sections/{sid}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert InvoiceSection.query.get(sid) is None


def test_renaming_never_moves_the_key(clinic):
    """A clinic renaming «الإقامة» to «الفندقة» must not thereby detach every
    night already billed under it."""
    from app.models import InvoiceSection

    with clinic["app"].app_context():
        row = InvoiceSection.query.filter_by(key="accommodation").first()
        sid = row.id
    clinic["sign_in"]().post("/finance/services/sections/save",
                             data={f"sname_{sid}": "الفندقة",
                                   f"sactive_{sid}": "1"},
                             follow_redirects=True)
    with clinic["app"].app_context():
        row = InvoiceSection.query.get(sid)
        assert row.key == "accommodation"
        assert row.name_ar == "الفندقة"
        assert _svc("SVC-WARD").section_key() == "accommodation"


# ------------------------------------------------------------- the screen --
def test_the_screen_offers_the_sections(clinic):
    html = clinic["sign_in"]().get("/finance/services").get_data(as_text=True)
    assert 'name="invoice_section"' in html
    assert "/finance/services/sections/new" in html


def test_automatic_is_an_answer_not_a_blank(clinic):
    """Leaving it empty means "let the program work it out", and the screen
    says which section that would be — so somebody can see they may not need
    to choose at all."""
    from app.i18n import t

    html = clinic["sign_in"]().get("/finance/services").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        assert t("services.section_auto") in html


def test_saving_an_unknown_section_stores_nothing(clinic):
    """A typed value the catalogue does not know would be a service filed
    under a heading that never appears in the summary."""
    from app.models import Service

    with clinic["app"].app_context():
        sid = _svc("SVC-KASHF").id
    clinic["sign_in"]().post(f"/finance/services/{sid}/edit",
                             data={"name": "كشف", "price": "250", "se": "1",
                                   "invoice_section": "not-a-section"},
                             follow_redirects=True)
    with clinic["app"].app_context():
        row = clinic["db"].session.get(Service, sid)
        assert row.invoice_section is None
        assert row.section_key() == "medical"


# ------------------------------------------------ the point of the exercise --
def test_a_bill_can_be_totalled_by_section(clinic):
    """What the whole axis exists for — and it groups by **whatever sections
    exist**, never by a name written into the code."""
    from app.models import Service

    with clinic["app"].app_context():
        totals = {}
        for s in Service.query.filter_by(is_active=True).all():
            totals[s.section_key()] = round(
                totals.get(s.section_key(), 0) + (s.price or 0), 2)
        assert totals.get("accommodation"), "the stay has no total"
        assert "medical" in totals
        assert all(k for k in totals), "a section with no key"
