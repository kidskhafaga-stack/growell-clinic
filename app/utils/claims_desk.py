"""The claims desk: a batch by payer and cycle day, the payer's answer line by
line, and what came of every refused line.

Asked as step 5 of the hospital insurance plan — *«دفعات حسب الجهة ويوم
الدورة، والسطور من كل الأقسام، والموافقات معاها، والرفض على كل سطر بسببه،
وإعادة التقديم، والمدفوع فعلاً قصاد المطالب بيه»*.

A claim held whole invoices and the payer's answer was one figure for the
lot. Payers do not answer like that: they accept the consultation, refuse
the CBC «not in the policy», and pay the third night only with its
approval. So a claim now carries its **lines** — each billed line the
payer is asked for, with its department and its approval number — and the
answer is written on each: accepted, part of it, or refused with the reason.

A refused remainder never just disappears. It is **sent again** on a
resubmission claim (which points back at the line it answers), or **let
go** by a person who says so. The claim then reads in four figures:
claimed, accepted, paid, and still open.
"""
from datetime import date, datetime, timedelta

from app.extensions import db


class DeskError(ValueError):
    """A refusal with a key the screen can name (``claims_desk.err_<key>``)."""


# ----------------------------------------------------------- the lines --
def build_lines(claim):
    """The claim's lines from its invoices — one per covered bill line, or
    one per bill claimed before cover was kept per line."""
    from app.models import ClaimLine
    from app.utils.care_setting import of_invoice

    if claim.lines:
        return claim.lines
    for item in claim.items:
        invoice = item.invoice
        if invoice is None:
            continue
        setting = of_invoice(invoice)
        covered = [i for i in invoice.items if (i.payer_amount or 0) > 0]
        if not covered:
            claim.lines.append(ClaimLine(
                claim_item_id=item.id, invoice_id=invoice.id,
                description=invoice.invoice_number, amount=item.amount,
                service_date=invoice.invoice_date, setting=setting))
            continue
        for line in covered:
            claim.lines.append(ClaimLine(
                claim_item_id=item.id, invoice_id=invoice.id,
                invoice_item_id=line.id, description=(line.description or "")[:200],
                service_date=line.service_date or invoice.invoice_date,
                setting=setting,
                approval_number=(line.approval.approval_number
                                 if line.approval is not None else None),
                amount=round(min(line.payer_amount or 0, line.gross), 2)))
    db.session.flush()
    return claim.lines


def ensure_lines(claim):
    """Lines for a claim made before they existed, while it can still be
    answered; a claim already decided reads as it was."""
    if not claim.lines and claim.status in ("draft", "submitted") and claim.items:
        build_lines(claim)
    return claim.lines


# --------------------------------------------------------- the answer --
def _amount(raw):
    raw = (raw or "").strip().replace(",", ".")
    if raw == "":
        return None
    try:
        return round(float(raw), 2)
    except ValueError:
        raise DeskError("bad_amount") from None


def decide(claim, answers, user=None, at=None):
    """Write the payer's answer. ``answers`` is ``{line_id: (accepted,
    reason)}``; an empty accepted box means the whole line was accepted.
    Anything refused must say why."""
    if claim.status != "submitted":
        raise DeskError("not_submitted")
    lines = {ln.id: ln for ln in claim.lines}
    if not lines:
        raise DeskError("no_lines")
    staged = {}
    for line_id, line in lines.items():
        raw, reason = answers.get(line_id, (None, None))
        accepted = _amount(raw)
        if accepted is None:
            accepted = line.amount
        if accepted < 0 or accepted > (line.amount or 0) + 0.005:
            raise DeskError("bad_amount")
        reason = (reason or "").strip()[:200]
        if accepted < (line.amount or 0) - 0.005 and not reason:
            raise DeskError("need_reason")
        staged[line_id] = (accepted, reason)
    for line_id, (accepted, reason) in staged.items():
        line = lines[line_id]
        line.accepted = accepted
        if abs(accepted - (line.amount or 0)) < 0.005:
            line.decision, line.refusal_reason = "accepted", None
        elif accepted <= 0.005:
            line.decision, line.refusal_reason = "refused", reason
        else:
            line.decision, line.refusal_reason = "partial", reason
    claim.approved_amount = round(sum(ln.accepted or 0 for ln in claim.lines), 2)
    claim.status = "approved"
    claim.decided_at = at or datetime.utcnow()
    db.session.flush()
    return claim


def resubmit(claim, line_ids, user=None):
    """Send the refused part of these lines again, on a new draft claim
    that points back at them. Returns the new claim."""
    from app.models import Claim, ClaimItem, ClaimLine

    chosen = [ln for ln in claim.lines if ln.id in set(line_ids) and ln.open_refusal]
    if not chosen:
        raise DeskError("nothing_to_resubmit")
    from app.blueprints.finance.routes import _claim_number

    again = Claim(claim_number=_claim_number(), payer_id=claim.payer_id,
                  date_from=claim.date_from, date_to=claim.date_to,
                  resubmission_of_id=claim.id,
                  created_by=getattr(user, "id", None),
                  notes=f"إعادة تقديم — {claim.claim_number}"[:255])
    db.session.add(again)
    db.session.flush()
    by_invoice = {}
    for ln in chosen:
        item = by_invoice.get(ln.invoice_id)
        if item is None:
            item = ClaimItem(claim_id=again.id, invoice_id=ln.invoice_id, amount=0)
            db.session.add(item)
            db.session.flush()
            by_invoice[ln.invoice_id] = item
        item.amount = round(item.amount + ln.refused, 2)
        again.lines.append(ClaimLine(
            claim_item_id=item.id, invoice_id=ln.invoice_id,
            invoice_item_id=ln.invoice_item_id, description=ln.description,
            service_date=ln.service_date, setting=ln.setting,
            approval_number=ln.approval_number, amount=ln.refused,
            resubmit_of_id=ln.id))
        ln.resubmitted_in_id = again.id
    again.total_amount = round(sum(it.amount for it in by_invoice.values()), 2)
    db.session.flush()
    return again


def write_off(claim, line_ids, user=None):
    """Let these refused remainders go — somebody's decision, recorded."""
    chosen = [ln for ln in claim.lines if ln.id in set(line_ids) and ln.open_refusal]
    if not chosen:
        raise DeskError("nothing_to_write_off")
    for ln in chosen:
        ln.written_off = True
    db.session.flush()
    return len(chosen)


# --------------------------------------------------------- the figures --
def totals(claim):
    """``{claimed, accepted, refused, open, written_off, resubmitted, paid,
    short}`` — what the claim asked, what the payer said, what came in."""
    lines = claim.lines
    accepted = (round(sum(ln.accepted or 0 for ln in lines), 2) if lines
                else (claim.approved_amount if claim.approved_amount is not None else None))
    paid = claim.paid_amount
    return {
        "claimed": round(claim.total_amount or 0, 2),
        "accepted": accepted,
        "refused": round(sum(ln.refused for ln in lines), 2),
        "open": round(sum(ln.refused for ln in lines if ln.open_refusal), 2),
        "written_off": round(sum(ln.refused for ln in lines if ln.written_off), 2),
        "resubmitted": round(sum(ln.refused for ln in lines if ln.resubmitted_in_id), 2),
        "paid": paid,
        "short": (round((accepted or 0) - (paid or 0), 2)
                  if paid is not None and accepted is not None else None),
    }


def next_batch(payer, today=None):
    """``(date_from, date_to)`` of the payer's next batch, or ``None``.

    From the day after the last claimed period (else the first unclaimed
    bill), up to the contract's cycle day — «anything after the 25th goes on
    next month's batch» — or today when the contract names none."""
    from app.models import Claim, Invoice
    from app.utils.clock import local_today

    today = today or local_today()
    last = (db.session.query(db.func.max(Claim.date_to))
            .filter(Claim.payer_id == payer.id, Claim.status != "rejected",
                    Claim.resubmission_of_id.is_(None)).scalar())
    if last is not None:
        start = last + timedelta(days=1)
    else:
        first = (db.session.query(db.func.min(Invoice.invoice_date))
                 .filter(Invoice.payer_id == payer.id).scalar())
        if first is None:
            return None
        start = first
    contract = payer.active_contract(today) if payer.contracts else None
    cycle = getattr(contract, "cycle_day", None)
    if cycle:
        end = _cycle_date(today.year, today.month, cycle)
        if end > today:
            prev = date(today.year, today.month, 1) - timedelta(days=1)
            end = _cycle_date(prev.year, prev.month, cycle)
    else:
        end = today
    if start > end:
        return None
    return start, end


def _cycle_date(year, month, day):
    import calendar

    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def payer_board(today=None, months=12):
    """``[{payer, batch, claims, claimed, accepted, paid, open}]`` — each
    payer's next batch and how its claims of the last ``months`` stand."""
    from app.models import Claim, PayerEntity
    from app.utils.clock import local_today

    today = today or local_today()
    since = today - timedelta(days=round(months * 30.4))
    out = []
    for payer in PayerEntity.query.order_by(PayerEntity.name).all():
        claims = Claim.query.filter(Claim.payer_id == payer.id,
                                    Claim.date_to >= since).all()
        batch = next_batch(payer, today)
        if not claims and batch is None:
            continue
        sums = [totals(c) for c in claims]
        out.append({
            "payer": payer, "batch": batch, "claims": len(claims),
            "claimed": round(sum(s["claimed"] for s in sums), 2),
            "accepted": round(sum(s["accepted"] or 0 for s in sums), 2),
            "paid": round(sum(s["paid"] or 0 for s in sums), 2),
            "open": round(sum(s["open"] for s in sums), 2),
        })
    return out


# ------------------------------------------------------------ the sheet --
def export(claim, t, lang="ar"):
    """The claim as the payer reads it: one row per line, with the member's
    card, the department and the approval number."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    ensure_lines(claim)
    wb = Workbook()
    ws = wb.active
    ws.title = "Claim"
    ws.sheet_view.rightToLeft = lang == "ar"
    head = ["invoice", "date", "patient", "card", "setting", "line",
            "approval", "amount", "accepted", "reason"]
    ws.append([t(f"claims_desk.col_{h}") for h in head])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for ln in claim.lines:
        inv = ln.invoice
        ws.append([
            inv.invoice_number if inv else "",
            ln.service_date.isoformat() if ln.service_date else "",
            inv.patient.display_name(lang) if inv and inv.patient else "",
            (inv.coverage_card or "") if inv else "",
            t(f"contracts.setting_{ln.setting}") if ln.setting else "",
            ln.description or "", ln.approval_number or "", ln.amount,
            ln.accepted if ln.decision else "", ln.refusal_reason or ""])
    for col, width in zip("ABCDEFGHIJ", (14, 12, 26, 14, 14, 30, 14, 12, 12, 30)):
        ws.column_dimensions[col].width = width
    return wb
