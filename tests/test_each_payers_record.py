"""Each payer's record — pays on time, refuses what, answers approvals how
fast (CONTRACTS_PLAN.md ع-٢, ``utils/payer_record``).

Asked as *«ويعمل ريت لكل شركة من المتعاقد معاها ملتزمه بالدفع فى رفض لحلالات
معينة»*. The record is worked out from the claims and the approvals, never
typed; each word on it comes from a figure printed beside it; one batch is
«too few to say»; and the assistant reads payers and money, never a child.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


def _noon(days_ago):
    """Midday, ``days_ago`` days back — far from midnight in any zone."""
    return datetime.combine(local_today() - timedelta(days=days_ago), time(12, 0))


@pytest.fixture()
def payers(clinic):
    """Two companies on contract, 30 days to pay."""
    from app.models import PayerContract, PayerEntity

    db = clinic["db"]
    with clinic["app"].app_context():
        ids = {}
        for key, name in (("good", "شركة ملتزمة"), ("slow", "شركة متأخرة")):
            payer = PayerEntity(name=name, name_en=key.title() + " Co",
                                entity_type="insurance", is_active=True)
            db.session.add(payer)
            db.session.flush()
            db.session.add(PayerContract(
                payer_id=payer.id, number=f"C-{key}",
                start_date=local_today() - timedelta(days=500),
                end_date=local_today() + timedelta(days=400),
                is_active=True, payment_days=30))
            ids[key] = payer.id
        db.session.commit()
    clinic["payers"] = ids
    return clinic


def _claim(fx, payer, sent_ago, paid_ago=None, lines=((1000, "accepted", 1000, None, "كشف", None),),
           status=None, notes=None):
    """A claim sent ``sent_ago`` days back, paid ``paid_ago`` days back (or
    not), with ``lines`` of (amount, decision, accepted, reason, service, dept)."""
    from app.models import Claim, ClaimLine

    db = fx["db"]
    with fx["app"].app_context():
        n = Claim.query.count() + 1
        total = sum(ln[0] for ln in lines)
        accepted = sum((ln[2] or 0) for ln in lines if ln[1])
        claim = Claim(claim_number=f"CLM-{n}", payer_id=fx["payers"][payer],
                      date_from=(local_today() - timedelta(days=sent_ago + 30)),
                      date_to=(local_today() - timedelta(days=sent_ago + 1)),
                      status=status or ("paid" if paid_ago is not None else "submitted"),
                      total_amount=total, submitted_at=_noon(sent_ago), notes=notes)
        if paid_ago is not None:
            claim.paid_at = _noon(paid_ago)
            claim.paid_amount = accepted
        db.session.add(claim)
        db.session.flush()
        for amount, decision, acc, reason, service, dept in lines:
            db.session.add(ClaimLine(claim_id=claim.id, amount=amount, decision=decision,
                                     accepted=acc, refusal_reason=reason,
                                     description=service, setting=dept))
        db.session.commit()
        return claim.id


def _approval(fx, payer, asked_ago, answered_after=None, status="requested"):
    from app.models import InsuranceApproval

    db = fx["db"]
    with fx["app"].app_context():
        row = InsuranceApproval(patient_id=fx["ids"]["child"], payer_id=fx["payers"][payer],
                                status=status, requested_at=_noon(asked_ago),
                                description="رسم قلب")
        if answered_after is not None:
            row.decided_at = row.requested_at + timedelta(days=answered_after)
        db.session.add(row)
        db.session.commit()


def _row(fx, payer, months=12):
    from app.utils import payer_record

    with fx["app"].app_context():
        data = payer_record.board(months)
        for r in data["rows"]:
            if r["payer"].id == fx["payers"][payer]:
                return {k: v for k, v in r.items() if k != "payer"}
    return None


# ----------------------------------------------------------- the figures --
def test_a_payer_that_pays_inside_its_terms_reads_on_time(payers):
    for sent, paid in ((80, 60), (60, 45), (40, 20)):
        _claim(payers, "good", sent, paid)
    r = _row(payers, "good")
    assert r["claims"] == 3 and r["paid_claims"] == 3
    assert r["payment_days"] == 30
    assert r["avg_days"] == round((20 + 15 + 20) / 3, 1)
    assert r["longest_days"] == 20
    assert r["late"] == 0 and r["overdue"] == 0
    assert r["words"] == ["on_time"]


def test_paid_after_its_day_or_past_it_now_reads_late(payers):
    _claim(payers, "slow", 120, 60)                 # 60 days for a 30-day term
    _claim(payers, "slow", 90, 70)                  # inside its terms
    _claim(payers, "slow", 50, lines=((700, "accepted", 700, None, "كشف", None),))  # unpaid, 20 days late
    _claim(payers, "slow", 10)                      # unpaid, not due yet
    r = _row(payers, "slow")
    assert r["late"] == 1
    assert r["overdue"] == 1 and r["overdue_amount"] == 700
    assert "late" in r["words"] and "on_time" not in r["words"]


def test_refusals_by_amount_with_their_reasons_services_and_departments(payers):
    _claim(payers, "good", 60, 30, lines=(
        (1000, "accepted", 1000, None, "كشف", "outpatient"),
        (500, "refused", 0, "مش مغطى في العقد", "أشعة مقطعية", "emergency"),
        (300, "partial", 100, "فوق السعر", "تحاليل", "outpatient")))
    _claim(payers, "good", 40, 10, lines=(
        (400, "refused", 0, "مش مغطى في العقد", "أشعة مقطعية", "emergency"),))
    # Refused whole, with no line answered: all of it is refused.
    _claim(payers, "good", 30, status="rejected", notes="المطالبة اتأخرت",
           lines=((600, None, None, None, "كشف", None),))
    r = _row(payers, "good")
    assert r["decided"] == 3
    assert r["accepted"] == 1100
    assert r["refused"] == 500 + 200 + 400 + 600
    assert r["refused_pct"] == round(1700 * 100 / 2800, 1)
    assert r["reasons"][0] == ("مش مغطى في العقد", 900)
    assert ("المطالبة اتأخرت", 600) in r["reasons"]
    assert r["services"][0] == ("أشعة مقطعية", 900)
    assert r["settings"][0] == ("emergency", 900)
    assert "refuses" in r["words"]


def test_one_batch_is_too_few_to_judge(payers):
    _claim(payers, "good", 60, 30, lines=((500, "refused", 0, "سبب", "كشف", None),))
    r = _row(payers, "good")
    assert r["words"] == ["few"]


def test_approvals_counted_and_how_fast_they_are_answered(payers):
    _approval(payers, "slow", 30, 5, "approved")
    _approval(payers, "slow", 20, 7, "rejected")
    _approval(payers, "slow", 3)
    r = _row(payers, "slow")
    assert (r["approvals"], r["approved"], r["rejected"], r["waiting"]) == (3, 1, 1, 1)
    assert r["approval_days"] == 6.0
    assert "slow_approvals" in r["words"]
    # A payer with approvals and no claim is on the record, and nothing is
    # said about paying it has never been asked to do.
    assert r["claims"] == 0
    assert "few" not in r["words"] and "on_time" not in r["words"]


def test_the_period_counts_a_claim_by_the_day_it_was_sent(payers):
    _claim(payers, "good", 200, 150)
    assert _row(payers, "good", months=3) is None
    assert _row(payers, "good", months=12)["claims"] == 1


# ------------------------------------------------------------- the screen --
def test_the_screen_its_doors_and_who_opens_it(payers):
    _claim(payers, "good", 60, 30)
    _claim(payers, "slow", 50)
    boss = payers["sign_in"]()
    page = boss.get("/finance/payers/record").get_data(as_text=True)
    assert "data-record-payer" in page
    assert "شركة ملتزمة" in page and "شركة متأخرة" in page
    assert 'data-word="late"' in page
    assert "data-record-rules" in page
    # Three months, six, twelve; anything else is the default.
    assert boss.get("/finance/payers/record?months=3").status_code == 200
    assert boss.get("/finance/payers/record?months=7").status_code == 200
    # Doors: the claims desk, the payers page and «All reports».
    for url in ("/finance/claims", "/finance/payers", "/reports/"):
        assert "/finance/payers/record" in boss.get(url).get_data(as_text=True), url
    # The reception does not open the money screens.
    assert payers["sign_in"]("desk").get("/finance/payers/record").status_code in (302, 403)


def test_an_empty_clinic_sees_a_sentence_not_a_blank_page(clinic):
    page = clinic["sign_in"]().get("/finance/payers/record").get_data(as_text=True)
    assert "data-record-empty" in page


# ---------------------------------------------------------- the assistant --
def _ai(fx, boards=True):
    from app.models import Setting

    with fx["app"].app_context():
        for key, value in (("ai_enabled", "1"), ("ai_provider", "claude"),
                           ("ai_api_key", "test-key"), ("ai_model", "test-model"),
                           ("ai_boards", "1" if boards else "0")):
            Setting.set(key, value)
        fx["db"].session.commit()


@pytest.fixture()
def asked(monkeypatch):
    from app.utils import ai

    calls = []

    def fake_chat(messages, system=None, config=None, feature=None):
        calls.append({"text": messages[0]["content"], "system": system, "feature": feature})
        return {"ok": True, "text": "- شركة متأخرة بتدفع بعد ميعادها."}

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


def test_the_assistant_is_off_until_the_boards_switch_is_on(payers, asked):
    _claim(payers, "slow", 50)
    _ai(payers, boards=False)
    boss = payers["sign_in"]()
    assert "data-board-ai-read" not in boss.get("/finance/payers/record").get_data(as_text=True)
    page = boss.post("/finance/payers/record/ai", data={"read": "1"}).get_data(as_text=True)
    assert "data-board-ai-error" in page
    assert asked == []


def test_the_assistant_reads_payers_and_money_never_a_child(payers, asked):
    from app.models import ActivityLog

    _claim(payers, "slow", 50, lines=((700, "refused", 0, "مش مغطى", "أشعة", "emergency"),))
    _approval(payers, "slow", 10, 2, "approved")
    _ai(payers)
    boss = payers["sign_in"]()
    page = boss.get("/finance/payers/record").get_data(as_text=True)
    assert "data-board-ai-read" in page
    # Its own words, not the clinic board's «read the period».
    assert "اقرا التقييم" in page and "اقرا الفترة" not in page
    got = boss.post("/finance/payers/record/ai?months=6", data={"read": "1"})
    body = got.get_data(as_text=True)
    assert "data-board-ai-reply" in body and "بتدفع بعد ميعادها" in body
    assert len(asked) == 1
    sent = asked[0]["text"]
    assert "شركة متأخرة" in sent and "مش مغطى" in sent and "أشعة" in sent
    assert "طفل" not in sent and "P1" not in sent
    assert asked[0]["feature"] == "payer_record"
    assert "insurance companies" in asked[0]["system"]
    with payers["app"].app_context():
        assert ActivityLog.query.filter_by(action="ai.board_payers").count() == 1


# ------------------------------------------------------- many companies --
def _many(fx, n):
    """``n`` more companies, each with three claims paid inside its terms."""
    from app.models import PayerContract, PayerEntity

    db = fx["db"]
    with fx["app"].app_context():
        for i in range(n):
            payer = PayerEntity(name=f"جهة {i:02d}", entity_type="insurance", is_active=True)
            db.session.add(payer)
            db.session.flush()
            db.session.add(PayerContract(payer_id=payer.id, number=f"M-{i}",
                                         start_date=local_today() - timedelta(days=500),
                                         end_date=local_today() + timedelta(days=400),
                                         is_active=True, payment_days=30))
            fx["payers"][f"m{i}"] = payer.id
        db.session.commit()
    for i in range(n):
        for sent, paid in ((80, 60), (60, 45), (40, 20)):
            _claim(fx, f"m{i}", sent, paid)


def _queries(fx):
    from sqlalchemy import event

    from app.utils import payer_record

    seen = []
    with fx["app"].app_context():
        engine = fx["db"].engine
        record = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", record)
        try:
            rows = payer_record.board()["rows"]
        finally:
            event.remove(engine, "before_cursor_execute", record)
    return len(seen), len(rows)


def test_forty_companies_cost_the_same_reads_as_four(payers):
    _many(payers, 4)
    few, rows_few = _queries(payers)
    _many(payers, 36)
    many, rows_many = _queries(payers)
    assert (rows_few, rows_many) == (4, 40)
    assert many == few


def test_the_ones_that_need_looking_at_come_first_and_can_be_shown_alone(payers):
    _many(payers, 12)
    _claim(payers, "slow", 50)                        # past its due day
    for sent, paid in ((90, 60), (70, 50), (50, 30)):
        _claim(payers, "good", sent, paid, lines=(
            (1000, "accepted", 600, None, "كشف", None),
            (400, "refused", 0, "سبب", "أشعة", None)))
    boss = payers["sign_in"]()
    page = boss.get("/finance/payers/record").get_data(as_text=True)
    order = [page.index(f'data-record-payer="{payers["payers"][k]}"')
             for k in ("slow", "good", "m0")]
    assert order == sorted(order)                     # overdue, refuses, then the rest
    assert "data-record-search" in page and "data-record-open" in page
    only = boss.get("/finance/payers/record?show=attention").get_data(as_text=True)
    assert only.count("data-record-payer=") == 2
    assert f'data-record-payer="{payers["payers"]["m0"]}"' not in only
    # The period buttons keep the filter.
    assert 'name="show" value="attention"' in only


def test_attention_alone_with_nothing_wrong_says_so(payers):
    _many(payers, 3)
    page = payers["sign_in"]().get("/finance/payers/record?show=attention").get_data(as_text=True)
    assert "data-record-all-fine" in page
