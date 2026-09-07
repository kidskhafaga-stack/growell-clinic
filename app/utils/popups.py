"""The nudge, for the person who will not go looking.

A doctor's share follows the money: a refund of half an invoice takes half
their share with it. So a refund is not an administrative detail that happens
near them — it is a number coming off their account, decided by somebody else,
and ``RefundNotice`` exists to tell them the same day.

It was told in one place: «عيادتي», a screen a doctor has no reason to open
on a busy morning. Asked for in one sentence: *"بنعمل بوب أب للطبيب على جنب
علشان نفهمه إن الإشعار موجود، علشان هو ممكن يكسل يفتح الجرس اللي فوق."*

**Three layers, and they say different things.**

* the pop-up  — "this happened just now"; an interruption, and it goes
* the bell    — "there are things that concern you"; a count, and it stays
* «عيادتي»    — the detail, and the objection; the record

Which is why switching the pop-up off loses nothing. The doctor who says it
bothers them is turning off *an interruption*, not the information: the bell
still counts and the screen still holds it. A pop-up on every refund in a busy
clinic is one that gets clicked through unread within a week, so respecting
"stop showing me these" is what keeps attention for the ones nobody muted.

Both switches are **per person**: one doctor silencing their own pop-up does
not silence a colleague's.
"""
#: The kinds a person can switch off. The screen renders from this, and a kind
#: missing from it cannot be muted — so a new pop-up is opted into here on
#: purpose rather than by being forgotten.
KINDS = ("refund",)


#: How many the pop-up shows at once. One more than that is read so the
#: count below can usually be answered without a second query.
SHOWN = 3


def _waiting(user):
    """The unseen notices, read **once per request** and shared.

    The bell wants a count and the pop-up wants the rows — the same filter,
    read twice, on every page anybody opens. One read serves both, and it is
    kept on ``g`` so the two context processors that ask for it in the same
    render do not each pay for it.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    from flask import g

    cached = getattr(g, "_refund_waiting", None)
    if cached is not None:
        return cached
    from app.models import RefundNotice

    rows = (RefundNotice.query
            .filter(RefundNotice.doctor_id == user.id,
                    RefundNotice.seen_at.is_(None))
            .order_by(RefundNotice.created_at.desc())
            .limit(SHOWN + 1).all())
    try:
        g._refund_waiting = rows
    except Exception:      # noqa: BLE001 — outside a request, just don't cache
        pass
    return rows


def unseen_refunds(user, limit=SHOWN):
    """Refund notices this doctor has not been shown yet.

    ``seen_at`` is the model's own field for this and was already there; the
    pop-up marks it, so a notice interrupts once and then lives in the bell
    and on «عيادتي» like everything else.
    """
    return _waiting(user)[:limit]


def pending_count(user):
    """How many refund notices are waiting — **whatever is muted**.

    The count is what the bell shows, and muting the pop-up must not touch
    it. Silencing the knock is not the same as emptying the room, and a
    program that treated them alike would let a doctor lose track of money
    coming off their own account by pressing "don't show me this again".

    Answered from the rows already read, and only counted properly on the
    rare page where a doctor has more than a handful waiting — so the common
    case costs nothing beyond the one read.
    """
    rows = _waiting(user)
    if len(rows) <= SHOWN:
        return len(rows)
    from app.models import RefundNotice

    return (RefundNotice.query
            .filter(RefundNotice.doctor_id == user.id,
                    RefundNotice.seen_at.is_(None)).count())


def for_user(user):
    """What to pop up now, or ``[]``.

    Empty when the person muted this kind — and the bell is unaffected, which
    is the whole distinction this module is built around.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if user.mutes_popup("refund"):
        return []
    return [{"kind": "refund", "notice": n} for n in unseen_refunds(user)]


def mark_seen(user, notice_id):
    """This one has been shown. Returns True when a row was stamped."""
    from datetime import datetime

    from app.extensions import db
    from app.models import RefundNotice

    notice = db.session.get(RefundNotice, notice_id)
    # Somebody else's notice is not this person's to mark read.
    if notice is None or user is None or notice.doctor_id != user.id:
        return False
    if notice.seen_at is None:
        notice.seen_at = datetime.utcnow()
    return True
