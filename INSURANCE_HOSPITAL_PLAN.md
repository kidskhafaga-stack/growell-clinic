# Contracts, approvals and deposits for a hospital — plan

Asked for as *«فى المستشفى وفى مستشفيات لاقيتها فى الطوارئ بتاخد تأمين فلوس
ولو هو تعاقد لازم موافقات على حجات معينة لان دي بتتبعت مع المطالبات … نظام
التأمين ده شغال على كل الاقسام الطوارئ والداخلى والحضانة وحسب كل عقد ايه الى
داخل على العقد وايه الى المريض بيحاسب عنده … خيار يدفع الاول وبعدين يتنفذ
والحالة الخطر تتنفذ على طول»*.

The answer to the first question was **both**: a cash deposit, and approvals
from the payer for named items that travel with the claim.

**Nothing below is a gateway or an integration.** Payers' own portals and
electronic claim formats are connected only from their official
documentation and a test account, never from memory.

---

## One rule before everything — the law on emergency care

The Prime Minister's decree **1063 of 2014** obliges private, investment and
university hospitals to treat **emergencies and accidents free for the
first 48 hours**, the state carrying the cost; the Minister of Health
repeated it in **September 2025** with closure for a hospital that asks for
money for emergency treatment. Emergency here means a condition that
threatens life and needs immediate intervention.

So in this program:

- **A critical case is never held for money or for an approval.** Not a
  setting, not a default — the option does not exist for it.
- «Pay first, then do it» is a choice the hospital may switch on **only for
  cases triaged as non-urgent**, and the triage level that counts as
  critical is the hospital's own (its triage scale is already its own).
- The program never asks the family for a deposit on a critical case; what
  it does is **record** the case so the 48 hours can be claimed from whoever
  pays them. How that claim is filed is a legal and administrative question
  — **the hospital's lawyer confirms the exact text and the procedure before
  this part is built**; a news report is not the decree.

---

## What already exists (reused, not rebuilt)

| Thing | Where | Note |
|---|---|---|
| Payers and their kinds | `PayerEntity`, `PayerType` | Company, insurer, union, club… |
| Contracts with dates, renewals and price lists | `PayerContract`, `PayerContractRate` | Per service: special price + what the payer covers (percent or amount) |
| Filing and payment deadlines | `PayerContract.filing_days/payment_days/cycle_day`, `claim_clock.py` | |
| The child's membership | `PatientCoverage` | Number and expiry |
| Claims and their lines | `Claim`, `ClaimItem` | Draft → submitted → decided → paid |
| A deposit as a payment against an invoice | `dental_money.take_deposit` | The pattern to reuse — a deposit is not a new kind of money |

What a **clinic** contract needed was a price list. What a **hospital**
contract needs, and is missing:

---

## The order of work

### Step 1 — A contract that knows the departments
- **Coverage per care setting**: the same contract says one thing for the
  outpatient clinic, another for emergency, inpatient, NICU, ICU and
  theatre. A row can be by **service**, by **category** (all labs 80%, all
  imaging 70%) or **everything else in this department**; the most specific
  row wins.
- **What the family pays**: a percentage share, a fixed amount per visit, a
  deductible, and **items the contract excludes** (paid in full by the
  family).
- **Ceilings**: per admission, per year, per night by room class (the
  contract pays a ward bed; a private room is the difference).
- The bill then splits **every line** into «on the contract» and «on the
  family», and says why («not covered», «over the ceiling», «needs
  approval»).

### Step 2 — Approvals that travel with the claim
- On the contract: **which items need prior approval** (by service or
  category, above an amount, or per admission).
- An **approval request** made from the order or the admission: what is
  asked, the estimate, sent; then the payer's answer — **approval number**,
  amount approved, valid until, and the scan of the letter.
- An item that needs approval and has none is **flagged on the bill and on
  the claim**, not silently charged to the family. While it waits, the
  administration decides per contract: do it and wait, or collect from the
  family and refund on approval — **never for a critical case**.
- The claim carries each line's approval number; a claim line with a
  missing approval is held back with the reason.

### Step 3 — Deposits on admission and in emergency
- An **open invoice for the stay** from the first hour; the deposit is an
  ordinary payment against it (the dental pattern), so it is never «lost
  cash» in a drawer.
- A **suggested deposit** per department and per contract (the family's
  share of an estimate, or a fixed figure the hospital sets) — a figure the
  desk can read, never computed by the assistant.
- **Top-up alert** when what has been used passes what was paid; at
  discharge the balance is collected or **refunded** on the same screen.

### Step 4 — «Pay first, then do it» in emergency, by case and by policy
- A hospital setting, per contract: **pay before / do and bill later**.
- **Applies only to cases triaged below the hospital's critical level.**
  The critical levels always proceed immediately, whatever is set.
- On the emergency screen an order in «waiting for payment» shows that
  state in the «waiting on» chips, so nobody wonders why it has not been
  done.

### Step 5 — The claim screen grows into a claims desk
- Batch by payer and cycle day, the lines from every department, approvals
  attached, refusals per line with the reason, re-submission, and what the
  payer actually paid against what was claimed.

---

## Sources for the emergency rule (to be confirmed by the hospital's lawyer)

- EIPR on decree 1063/2014 (2014) — eipr.org
- Youm7, 20 Jan 2018 — the Minister: binding on 2,067 private hospitals,
  penalty closure or licence withdrawal
- Youm7 and Masrawy, 2 Sep 2025 — the Minister's directive on free
  emergency treatment in the first 48 hours
- Al-Dostor — closure for a private hospital that asks for money for
  emergency treatment
