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

# Who may work a till. Deliberately *not* a capability: "may move money" is a
# job, "may open the second-floor drawer" is an assignment, and squeezing the
# second into the first means a new capability every time a clinic adds a desk.
#
# An empty assignment means the till is open to anyone holding the permission
# for what they are doing. That is the only safe default for the tills that
# already exist: naming nobody must not lock everybody out of the drawer they
# were using yesterday.
till_users = db.Table(
    "cash_account_users",
    db.Column("account_id", db.Integer, db.ForeignKey("cash_accounts.id"),
              primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"),
              primary_key=True),
)

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

    # Where this drawer is handed over at the end of a shift. The cashier
    # counts the till, keeps the change float for the next session, and the
    # takings go to the safe — which is what happens over the counter, and
    # what the program used to have no way to record: the drawer's balance
    # simply grew for ever and the safe never saw a day's money.
    #
    # Null means nothing moves, and that is the default for every till that
    # already exists. A clinic that keeps its cash in the drawer it was taken
    # in is not doing anything wrong, and turning the sweep on for them
    # because the column appeared would move their money without being asked.
    sweeps_into_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                               nullable=True)

    # Where a `clearing` till settles: card takings land in the bank days
    # later, minus a fee. Without this, the card account grows forever and
    # nobody can clear it to zero.
    settles_into_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                                nullable=True)
    # What the processor keeps, as a percentage. It belongs to the till and
    # not to the code, because it is a property of *which bank's* machine
    # this is: one gives 2.5%, another 1.9% with a higher ceiling, and a
    # clinic with two POS accounts has both. Only a default — the settlement
    # statement is the authority, so the typed figure always wins.
    fee_percent = db.Column(db.Float)

    # Payment methods that default to this till, comma-separated. A method
    # belongs to exactly one till by default; the cashier may override it per
    # payment.
    default_methods = db.Column(db.String(120))

    # How many days card takings normally take to reach the bank. Used to say
    # "this settlement is late", never to post one: the bank statement is the
    # authority on what actually arrived and what the processor kept, and a
    # program that journals a settlement on a timer is writing down money it
    # has not seen.
    settle_after_days = db.Column(db.Integer)

    sort_order = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.String(255))

    owner = db.relationship("User", foreign_keys=[owner_id])
    settles_into = db.relationship("CashAccount", remote_side=[id],
                                   foreign_keys=[settles_into_id])
    sweeps_into = db.relationship("CashAccount", remote_side=[id],
                                  foreign_keys=[sweeps_into_id])
    # Who is allowed to work this till. Empty = anyone with the permission.
    users = db.relationship("User", secondary=till_users, lazy="selectin")

    # --- naming --------------------------------------------------------
    def display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    @property
    def methods(self):
        return [m for m in (self.default_methods or "").split(",") if m]

    def expected_fee(self, amount):
        """What this till's processor would keep on ``amount``.

        A suggestion for the settlement form, rounded to piastres. Returns 0
        when no rate is configured rather than guessing an industry average —
        a wrong fee silently applied is worse than a blank the user fills in.
        """
        if not self.fee_percent or not amount:
            return 0.0
        return round(float(amount) * float(self.fee_percent) / 100.0, 2)

    @property
    def counts_by_hand(self):
        """Whether a shift can be opened on this till, and a count taken.

        Only cash. Nobody hands over an InstaPay balance at the end of the
        evening — it sits there until it is swept to the bank.
        """
        return self.kind == "cash"

    # --- who may work it -----------------------------------------------
    def may_be_used_by(self, user):
        """Whether ``user`` may act on this till — collect into it, count it,
        open a shift on it, move money out of it.

        This is about *which* drawer, not about *what* may be done to one: the
        capabilities still decide whether somebody may move money or explain a
        difference at all. A till nobody is named on stays open to everyone,
        because that is what every till in an existing clinic looks like and
        locking them all would break the drawer people used yesterday.
        """
        if user is None or not getattr(user, "is_authenticated", True):
            return False
        if getattr(user, "role", None) == "admin":
            return True
        # The person whose name is on the drawer is never locked out of it,
        # even if the assignment list was filled in without them.
        if self.owner_id and self.owner_id == user.id:
            return True
        if not self.users:
            return True
        return any(u.id == user.id for u in self.users)

    @classmethod
    def usable_by(cls, user):
        """Active tills ``user`` may act on, in screen order."""
        return [a for a in cls.active() if a.may_be_used_by(user)]

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
