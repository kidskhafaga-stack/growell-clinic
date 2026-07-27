"""Where the clinic's money actually sits.

Every collection used to post to one ledger account called "الخزنة", whatever
the patient paid with — so InstaPay money sitting in a phone app appeared in
the books as notes in a drawer. That account was not a drawer: it was
"everything that came in by any means, minus everything that went out", a
number nobody can count and nothing can be checked against. A shortage in the
cash was covered by the InstaPay money next to it.

**A till is something you can count.** Cash by hand, a wallet by opening the
app, a bank from the statement, card takings from the settlement that arrives.
That is what ``kind`` says — not what the money is, but *how you check it*.

**The payment method is not the till.** How the family paid and where the
money came to rest are two different facts: a clinic with reception desks on
two floors has both taking cash. So a method names a *default* till, and the
cashier can send a particular payment somewhere else without anybody inventing
a payment method called "cash-emergency".

**The balance is computed, never stored.** A column updated on every movement
is the easiest thing to build and the most dangerous to live with: one
interrupted write and there are two answers to "how much is in this till" with
no way to tell which one is lying.
"""
from app.extensions import db

# How a till is checked against reality. Four, not ten: petty cash, the safe
# and a reception drawer are all counted by hand with the same code — the
# difference between them is policy and a name, not behaviour, and making them
# separate kinds means writing the counting logic (and its bugs) five times.
#
#   cash      counted by hand
#   bank      read off a statement
#   wallet    read out of an app (InstaPay, Vodafone Cash)
#   clearing  money owed to you that has not landed yet
ACCOUNT_KINDS = ["cash", "bank", "wallet", "clearing"]

# Foreign currency is not a kind — it is a field on any of them. And a currency
# field without rates, revaluation and FX gain/loss accounts would give a false
# impression that other currencies are handled, so it ships pinned to one and
# cross-currency transfers are refused until that machinery exists.
DEFAULT_CURRENCY = "EGP"


class CashAccount(db.Model):
    """One place money sits: a drawer, a wallet, a bank account, a settlement."""

    __tablename__ = "cash_accounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    name_en = db.Column(db.String(80))
    # Its account in the chart of accounts. Movements post here.
    code = db.Column(db.String(10), nullable=False, index=True)
    kind = db.Column(db.String(12), default="cash", nullable=False, index=True)
    currency = db.Column(db.String(3), default=DEFAULT_CURRENCY, nullable=False)

    opening_balance = db.Column(db.Float, default=0, nullable=False)
    # Minimum is about making change — a drawer that cannot give a customer
    # their 30 back. Maximum is what actually protects money: too much cash
    # sitting in reception is a theft risk, and the prompt says "bank it".
    min_balance = db.Column(db.Float)
    max_balance = db.Column(db.Float)

    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    # The seed of per-till permissions, and useful on its own: a drawer with
    # nobody's name on it is a drawer nobody is short on.
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # Free text on purpose. This program has no branch entity, and inventing
    # one (stock, reports and permissions per branch) is its own project — a
    # label now is honest; a fake foreign key would not be.
    branch = db.Column(db.String(60))

    # Where a `clearing` till settles: card takings land in the bank days
    # later, minus a fee. Without this, the card account grows forever and
    # nobody can clear it to zero.
    settles_into_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                                nullable=True)
    # Payment methods that default to this till, comma-separated. A method
    # belongs to exactly one till by default; the cashier may override it per
    # payment.
    default_methods = db.Column(db.String(120))

    sort_order = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.String(255))

    owner = db.relationship("User")
    settles_into = db.relationship("CashAccount", remote_side=[id])

    # --- naming --------------------------------------------------------
    def display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    @property
    def methods(self):
        return [m for m in (self.default_methods or "").split(",") if m]

    @property
    def counts_by_hand(self):
        """Whether a shift can be opened on this till, and a count taken.

        Only cash. Nobody hands over an InstaPay balance at the end of the
        evening — it sits there until it is swept to the bank.
        """
        return self.kind == "cash"

    # --- money ---------------------------------------------------------
    def balance(self, upto=None):
        """Opening balance plus every movement — computed, never cached."""
        from app.utils.treasury import account_balance

        return account_balance(self, upto=upto)

    @classmethod
    def for_method(cls, method):
        """The till a payment by ``method`` lands in unless told otherwise."""
        if not method:
            return None
        for account in (cls.query.filter_by(is_active=True)
                        .order_by(cls.sort_order, cls.id).all()):
            if method in account.methods:
                return account
        return None

    @classmethod
    def active(cls):
        return (cls.query.filter_by(is_active=True)
                .order_by(cls.sort_order, cls.id).all())

    def __repr__(self):
        return f"<CashAccount {self.code} {self.name} {self.kind}>"
