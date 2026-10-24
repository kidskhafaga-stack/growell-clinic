"""Each payer's record — does it pay on time, what does it refuse, how fast
does it answer an approval (CONTRACTS_PLAN.md ع-٢).

Asked as *«ويعمل ريت لكل شركة من المتعاقد معاها ملتزمه بالدفع فى رفض لحلالات
معينة»*. Worked out from what the claims desk and the approvals already hold —
**never a score somebody types**:

* **Paying on time** — how many days each paid claim took from submission to
  payment (``claim_clock.sent_on`` → ``Claim.paid_at``), beside the days the
  contract gives (``payment_days``); how many were paid after their due day,
  and what sits past it today (``claim_clock.days_overdue``).
* **Refusing** — what was refused of what the payer decided, by amount; the
  reasons, the services and the departments that carry most of it
  (``ClaimLine``). A claim refused whole, with no line decided, counts whole.
* **Approvals** — how many were asked, granted, refused, still waiting, and
  how many days an answer took.
* **A few plain words** from those figures and the thresholds below — «pays
  on time», «pays late», «refuses a lot», «slow to approve» — and «too few to
  say» when there is not enough to read. The figures sit beside the words,
  so every word can be checked.

What the assistant may read of it (the boards' switch) is payers, services,
departments and money: no child, no file number.
"""
from collections import Counter
from datetime import datetime, timedelta

PERIODS = (3, 6, 12)
DEFAULT_MONTHS = 12
#: Fewer decided claims than this (and fewer paid), and the words say «too
#: few to say» instead of judging a company on one batch.
MIN_CLAIMS = 3
#: A share of the decided amount refused at or above this reads «refuses a lot».
REFUSAL_HIGH = 15.0
#: Approvals answered, on average, slower than this many days read «slow».
APPROVAL_SLOW_DAYS = 3.0
TOP = 3
DECIDED = ("approved", "rejected", "paid")

SYSTEM = (
    "You read a paediatric clinic's record of the insurance companies and "
    "payers it has contracts with: how long each takes to pay against the days "
    "its contract gives, what it refuses and why, and how fast it answers "
    "approval requests. Use only these figures: never invent a number, a rate "
    "or a cause. When you suggest a reason, say it is a possibility to check. "
    "Say plainly when a number is too small to conclude anything from. Be "
    "brief: short bullet points, the most important first, and name what the "
    "clinic could raise with each company. Answer in {language}."
)

READ = ("Read this record: which companies pay on time and which do not, what "
        "each refuses most and why, which approvals are slow, and what is too "
        "small to conclude.")


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _top(counter):
    return [(k, round(v, 2)) for k, v in counter.most_common(TOP)]


def record(payer, since, today, claims=None, asked=None):
    """One payer's figures: claims by the day they were sent, approvals by the
    day they were asked, both from ``since`` to ``today``.

    ``claims`` and ``asked``: the payer's rows when :func:`board` already read
    every payer's in one go — forty companies are two reads, not eighty."""
    from app.models import Claim, InsuranceApproval
    from app.utils import claim_clock, claims_desk
    from app.utils.clock import local_date

    if claims is None:
        claims = Claim.query.filter(Claim.payer_id == payer.id,
                                    Claim.submitted_at.isnot(None)).all()
    claims = [c for c in claims
              if claim_clock.sent_on(c) is not None
              and since <= claim_clock.sent_on(c) <= today]

    claimed = accepted = refused = paid = overdue_amount = 0.0
    decided = late = overdue = 0
    pay_days = []
    reasons, services, settings = Counter(), Counter(), Counter()
    for c in claims:
        sums = claims_desk.totals(c)
        claimed += sums["claimed"]
        lines_decided = any(ln.decision for ln in c.lines)
        if lines_decided or c.status in DECIDED or c.approved_amount is not None:
            decided += 1
            if not lines_decided and c.status == "rejected":
                # Refused whole: nothing accepted, all of it refused.
                refused += sums["claimed"]
                reasons[(c.notes or "").strip() or "—"] += sums["claimed"]
            else:
                accepted += sums["accepted"] or 0
                refused += sums["refused"]
        for ln in c.lines:
            gone = ln.refused
            if gone > 0:
                reasons[(ln.refusal_reason or "").strip() or "—"] += gone
                services[(ln.description or "").strip() or "—"] += gone
                if ln.setting:
                    settings[ln.setting] += gone
        due = claim_clock.payment_due(c)
        if c.paid_at is not None:
            paid += c.paid_amount or 0
            on = local_date(c.paid_at)
            pay_days.append((on - claim_clock.sent_on(c)).days)
            if due is not None and on > due:
                late += 1
        elif c.status != "rejected" and claim_clock.days_overdue(c, today) > 0:
            overdue += 1
            overdue_amount += (sums["accepted"] if sums["accepted"] is not None
                               else sums["claimed"])

    if asked is None:
        asked = (InsuranceApproval.query
                 .filter(InsuranceApproval.payer_id == payer.id).all())
    asked = [a for a in asked
             if a.requested_at and since <= local_date(a.requested_at) <= today]
    answer_days = [(a.decided_at - a.requested_at).total_seconds() / 86400
                   for a in asked
                   if a.status in ("approved", "rejected") and a.decided_at]
    judged = accepted + refused
    row = {
        "payer": payer, "claims": len(claims), "decided": decided,
        "claimed": round(claimed, 2), "accepted": round(accepted, 2),
        "refused": round(refused, 2),
        "refused_pct": round(refused * 100 / judged, 1) if judged > 0 else None,
        "paid": round(paid, 2),
        "payment_days": claim_clock.terms(payer, today)[1],
        "avg_days": _avg(pay_days), "longest_days": max(pay_days) if pay_days else None,
        "paid_claims": len(pay_days), "late": late,
        "overdue": overdue, "overdue_amount": round(overdue_amount, 2),
        "reasons": _top(reasons), "services": _top(services), "settings": _top(settings),
        "approvals": len(asked),
        "approved": sum(1 for a in asked if a.status == "approved"),
        "rejected": sum(1 for a in asked if a.status == "rejected"),
        "waiting": sum(1 for a in asked if a.status == "requested"),
        "approval_days": _avg(answer_days),
    }
    row["words"] = words(row)
    return row


def words(row):
    """The plain words, each from a figure on the same row:

    * ``few`` — fewer than :data:`MIN_CLAIMS` claims decided and paid;
    * ``late`` — a claim paid after its due day, or one past it now;
    * ``on_time`` — paid claims, none of them late, nothing overdue;
    * ``refuses`` — :data:`REFUSAL_HIGH` % or more of the decided amount;
    * ``slow_approvals`` — answers slower than :data:`APPROVAL_SLOW_DAYS` days.

    An overdue claim is a fact whatever the count, so ``late`` is said even
    beside ``few``.
    """
    out = []
    few = row["decided"] < MIN_CLAIMS and row["paid_claims"] < MIN_CLAIMS
    if few and row["claims"]:
        out.append("few")
    if row["late"] or row["overdue"]:
        out.append("late")
    elif not few and row["paid_claims"]:
        out.append("on_time")
    if (not few and row["refused_pct"] is not None
            and row["refused_pct"] >= REFUSAL_HIGH):
        out.append("refuses")
    if row["approval_days"] is not None and row["approval_days"] > APPROVAL_SLOW_DAYS:
        out.append("slow_approvals")
    return out


#: The words that call for somebody to look — the rest is good news or «too
#: few to say».
ATTENTION = ("late", "refuses", "slow_approvals")


#: The filters over the list: everybody, the ones that need looking at, or
#: one word. Anything else in the address is «everybody».
SHOWS = ("all", "attention", "late", "refuses", "slow_approvals", "on_time", "few")


def _matches(row, show):
    if show == "attention":
        return bool(row["attention"])
    return show == "all" or show in row["words"]


def board(months=DEFAULT_MONTHS, today=None, show="all", q=""):
    """Every payer with a claim sent or an approval asked in the period, the
    ones that need looking at first (overdue money, then refusals, then slow
    approvals), then by name.

    ``q`` keeps the payers whose name (either language) holds it; ``show``
    one of :data:`SHOWS`. ``counts`` says how many each filter would show
    with the same search, so the buttons carry their numbers.

    Every claim with its lines and every approval are read once for all the
    payers, so the page costs the same with four companies or forty."""
    from collections import defaultdict

    from sqlalchemy.orm import selectinload

    from app.models import Claim, InsuranceApproval, PayerEntity
    from app.utils.clock import local_today

    today = today or local_today()
    months = months if months in PERIODS else DEFAULT_MONTHS
    since = today - timedelta(days=round(months * 30.4))
    # A day either side: ``sent_on`` reads the clinic's calendar, the column
    # is UTC; the exact edge is judged in :func:`record`.
    edge = datetime.combine(since - timedelta(days=1), datetime.min.time())
    by_payer = defaultdict(list)
    for c in (Claim.query.filter(Claim.submitted_at.isnot(None),
                                 Claim.submitted_at >= edge)
              .options(selectinload(Claim.lines)).all()):
        by_payer[c.payer_id].append(c)
    asked_by = defaultdict(list)
    for a in InsuranceApproval.query.filter(InsuranceApproval.requested_at >= edge).all():
        asked_by[a.payer_id].append(a)
    payers = (PayerEntity.query
              .filter(PayerEntity.id.in_(set(by_payer) | set(asked_by)))
              .options(selectinload(PayerEntity.contracts)).all()
              if by_payer or asked_by else [])
    rows = []
    for payer in payers:
        row = record(payer, since, today, by_payer.get(payer.id, []),
                     asked_by.get(payer.id, []))
        if row["claims"] or row["approvals"]:
            row["attention"] = [w for w in ATTENTION if w in row["words"]]
            rows.append(row)
    rows.sort(key=lambda r: ([w not in r["attention"] for w in ATTENTION],
                             -r["overdue_amount"], r["payer"].name))
    total = len(rows)
    show = show if show in SHOWS else "all"
    q = " ".join((q or "").split())[:80]
    if q:
        needle = q.casefold()
        rows = [r for r in rows
                if needle in (r["payer"].name or "").casefold()
                or needle in (r["payer"].name_en or "").casefold()]
    counts = {key: sum(1 for r in rows if _matches(r, key)) for key in SHOWS}
    return {"rows": [r for r in rows if _matches(r, show)], "counts": counts,
            "total": total, "show": show, "q": q, "since": since, "today": today,
            "months": months}


def facts(data, lang="ar"):
    """The record as the assistant reads it: payers, services, departments
    and money — no child."""
    def listed(pairs):
        return ", ".join(f"{k} ({v})" for k, v in pairs) or "none"

    out = [f"Payers' record. Claims sent and approvals asked from {data['since']} "
           f"to {data['today']}. Amounts in the clinic's currency."]
    for r in data["rows"]:
        out.append(
            f"- {r['payer'].display_name(lang)}: {r['claims']} claims sent, "
            f"{r['decided']} decided; claimed {r['claimed']}, accepted {r['accepted']}, "
            f"refused {r['refused']} ({r['refused_pct'] if r['refused_pct'] is not None else '—'}% "
            f"of what was decided); paid {r['paid']} on {r['paid_claims']} claims. "
            f"Contract gives {r['payment_days'] or 'no stated'} days to pay; "
            f"average days to pay {r['avg_days'] if r['avg_days'] is not None else '—'}, "
            f"longest {r['longest_days'] if r['longest_days'] is not None else '—'}; "
            f"paid late {r['late']}; overdue now {r['overdue']} claims ({r['overdue_amount']}). "
            f"Most refused for: {listed(r['reasons'])}. "
            f"Most refused services: {listed(r['services'])}. "
            f"Most refused departments: {listed(r['settings'])}. "
            f"Approvals asked {r['approvals']}: granted {r['approved']}, refused "
            f"{r['rejected']}, waiting {r['waiting']}; average days to answer "
            f"{r['approval_days'] if r['approval_days'] is not None else '—'}.")
    return "\n".join(out)


def ask(data, question=None, lang="ar"):
    """The assistant's reading of the record — the boards' own call and
    switch, with this record's instructions."""
    from app.utils import board_ai

    return board_ai.ask(facts(data, lang), board_ai._Codes(), question, lang=lang,
                        system=SYSTEM, feature="payer_record", read=READ)
