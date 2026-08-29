"""A clinic's own till, and whether the ledger knows it exists.

Two faults that turn out to be one.

The first: a clinic had the five tills the installer made and no way to have a
sixth. That is fine for one room and wrong for every other shape — reception
on two floors is two drawers, and a clinic handing its takings to a safe every
evening had nowhere to hand them to, because the seeded *"الخزنة الرئيسية"* is
the reception drawer itself.

The second is what would have happened the moment the first was fixed.
``post_entry`` looks its lines up by account code and returns None — quietly,
by design, so a half-installed database does not crash — when a code is not in
the chart of accounts. A till created without an account behind it would move
money on every screen in the treasury and post not one line of it to the
ledger: the drawer visibly holding cash, the trial balance certain it does
not, and nothing anywhere saying which to believe.

So the code is allocated rather than typed, and the chart account is created
with the till in the same breath.
"""
import pytest


@pytest.fixture
def boss(clinic):
    return clinic["sign_in"]("boss")


def _add(client, name="خزنة الدور الأول", kind="cash", opening="0"):
    return client.post("/finance/tills/new", data={
        "name": name, "kind": kind, "opening_balance": opening},
        follow_redirects=True)


def _till(clinic, name="خزنة الدور الأول"):
    from app.models import CashAccount

    with clinic["app"].app_context():
        till = CashAccount.query.filter_by(name=name).first()
        if till is None:
            return None
        return {"id": till.id, "code": till.code, "kind": till.kind,
                "active": till.is_active, "opening": till.opening_balance}


def _chart(clinic, code):
    from app.models import Account

    with clinic["app"].app_context():
        account = Account.query.filter_by(code=code).first()
        if account is None:
            return None
        return {"type": account.type, "system": account.is_system,
                "parent": account.parent.code if account.parent else None}


# ------------------------------------------------------- making one at all --
def test_a_clinic_can_add_a_till(boss, clinic):
    """The gap this starts from: five tills and no sixth, for every clinic
    that is not one room."""
    _add(boss)
    assert _till(clinic) is not None


def test_the_new_till_appears_on_the_treasury_screen(boss, clinic):
    """A till the money screen does not list is a till nobody can use."""
    _add(boss)
    page = boss.get("/finance/tills").get_data(as_text=True)
    assert "خزنة الدور الأول" in page


def test_only_an_admin_may_add_one(clinic):
    """A till is an account in the books. Reception opening one would be
    reception writing to the chart of accounts."""
    desk = clinic["sign_in"]("desk")
    _add(desk)
    assert _till(clinic) is None


def test_a_till_with_no_name_is_refused(boss, clinic):
    """Rather than created as a blank row somebody has to go and find."""
    _add(boss, name="   ")
    from app.models import CashAccount

    with clinic["app"].app_context():
        assert CashAccount.query.count() == 0


# --------------------------------------------------------- and its account --
def test_the_till_gets_an_account_in_the_chart(boss, clinic):
    """The whole point. Without this the till moves money on every treasury
    screen and posts none of it to the ledger."""
    _add(boss)
    till = _till(clinic)
    assert _chart(clinic, till["code"]) is not None


def test_the_account_is_an_asset_under_assets(boss, clinic):
    """A till filed anywhere else makes the balance sheet wrong in a way that
    still adds up, which is the hardest kind to find."""
    _add(boss)
    account = _chart(clinic, _till(clinic)["code"])
    assert account["type"] == "asset"
    assert account["parent"] == "1000"


def test_the_clinics_own_account_is_not_marked_system(boss, clinic):
    """`is_system` means the program seeded it and maintains it. A clinic's
    own till is theirs to rename or retire."""
    _add(boss)
    assert _chart(clinic, _till(clinic)["code"])["system"] is False


# ----------------------------------------------------------- the code ------
def test_the_code_clears_the_block_the_program_reserves(boss, clinic):
    """1030 is patients and 1040 is stock. A till landing on either posts the
    clinic's money into somebody else's account."""
    _add(boss)
    assert int(_till(clinic)["code"]) >= 1050


def test_two_tills_do_not_share_a_code(boss, clinic):
    """They would post into each other's account, and no screen would say so
    — both would look right, and the two balances would be one balance."""
    _add(boss, name="أول")
    _add(boss, name="تاني")
    assert _till(clinic, "أول")["code"] != _till(clinic, "تاني")["code"]


def test_a_code_already_worn_by_a_seeded_till_is_skipped(boss, clinic):
    """The chart and the tills are two books, and a code is free only when
    neither of them has it."""
    from app.models import CashAccount

    with clinic["app"].app_context():
        clinic["db"].session.add(
            CashAccount(code="1050", name="خزنة قديمة", kind="cash"))
        clinic["db"].session.commit()

    _add(boss)
    assert _till(clinic)["code"] != "1050"


def test_a_code_already_in_the_chart_is_skipped(boss, clinic):
    """The other book. A till handed a code the chart already uses would post
    into whatever that account is."""
    from app.models import Account

    with clinic["app"].app_context():
        clinic["db"].session.add(
            Account(code="1050", name="حاجة تانية", type="asset"))
        clinic["db"].session.commit()

    _add(boss)
    assert _till(clinic)["code"] != "1050"


# ------------------------------------------------- money actually posts ----
def test_money_moved_into_the_new_till_reaches_the_ledger(boss, clinic):
    """The fault this exists to prevent, end to end.

    A transfer into a till with no chart account is accepted by the treasury,
    shows on both statements, and posts nothing. The drawer holds cash and
    the trial balance says it does not.
    """
    from app.models import Account, CashAccount, JournalEntry, JournalLine
    from app.utils import accounting, treasury

    with clinic["app"].app_context():
        accounting.ensure_seeded()
        source = CashAccount(code="1010", name="الدرج", kind="cash",
                             opening_balance=500, is_active=True)
        clinic["db"].session.add(source)
        clinic["db"].session.commit()
        source_id = source.id

    _add(boss, name="الخزنة")
    safe = _till(clinic, "الخزنة")

    with clinic["app"].app_context():
        db = clinic["db"]
        treasury.record_movement(
            "transfer", db.session.get(CashAccount, source_id), 300,
            to_account=db.session.get(CashAccount, safe["id"]))
        entry = JournalEntry.query.filter_by(source_type="cash_movement").one()
        codes = {line.account.code: (line.debit or 0, line.credit or 0)
                 for line in JournalLine.query.filter_by(entry_id=entry.id)}

    assert codes[safe["code"]] == (300.0, 0)
    assert codes["1010"] == (0, 300.0)


# ------------------------------------------------------------- the repair --
def test_a_till_that_predates_this_is_given_an_account(clinic):
    """The rule above fixes what happens from now on and does nothing for a
    till already sitting in a clinic's database without one."""
    from app.models import Account, CashAccount
    from app.utils.accounting import repair_till_accounts

    with clinic["app"].app_context():
        clinic["db"].session.add(
            CashAccount(code="1077", name="خزنة قديمة", kind="cash"))
        clinic["db"].session.commit()
        assert Account.query.filter_by(code="1077").first() is None

        assert repair_till_accounts() == 1
        clinic["db"].session.commit()
        assert Account.query.filter_by(code="1077").first() is not None


def test_the_repair_leaves_an_account_the_clinic_renamed_alone(clinic):
    """Idempotent, and it does not correct a rename. A clinic that called
    1010 "درج الاستقبال" meant it, and an upgrade is not the moment to
    disagree."""
    from app.models import Account, CashAccount
    from app.utils.accounting import repair_till_accounts

    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(CashAccount(code="1078", name="اسم الخزنة", kind="cash"))
        db.session.add(Account(code="1078", name="اسم اختاره العميل",
                               type="asset"))
        db.session.commit()

        assert repair_till_accounts() == 0
        assert Account.query.filter_by(
            code="1078").one().name == "اسم اختاره العميل"


def test_asking_twice_for_the_same_account_makes_one(clinic):
    """The guard the repair's own guard hides.

    Mutation testing walked straight past this: `repair_till_accounts` checks
    for itself before calling, and `till_new` calls it on a till that has no
    account yet, so nothing ever reached the second call. It is still the
    thing standing between a double-submitted form and an IntegrityError —
    `Account.code` is unique, so making a second one does not produce a
    duplicate, it produces a crash.
    """
    from app.models import Account, CashAccount
    from app.utils.accounting import ensure_till_account

    with clinic["app"].app_context():
        db = clinic["db"]
        till = CashAccount(code="1081", name="خزنة", kind="cash")
        db.session.add(till)
        db.session.commit()

        first = ensure_till_account(till)
        db.session.commit()
        again = ensure_till_account(till)
        db.session.commit()

        assert again.id == first.id
        assert Account.query.filter_by(code="1081").count() == 1


def test_running_the_repair_twice_creates_nothing_the_second_time(clinic):
    """It runs on every upgrade."""
    from app.models import Account, CashAccount
    from app.utils.accounting import repair_till_accounts

    with clinic["app"].app_context():
        clinic["db"].session.add(
            CashAccount(code="1079", name="خزنة", kind="cash"))
        clinic["db"].session.commit()
        repair_till_accounts()
        clinic["db"].session.commit()
        before = Account.query.count()
        assert repair_till_accounts() == 0
        assert Account.query.count() == before
