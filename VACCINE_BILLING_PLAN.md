# Vaccines + Billing + Cashier — Phased Plan

Captures the reception/vaccine/payment workflow. Built in small phases, each
tested + committed + reviewed. **Reuses existing models — no duplication.**

## What already exists (reused, not rebuilt)
- **Service pricing/commissions/discounts** → `Service`, `DoctorServiceCommission`, `ServiceBundleItem`.
- **Vaccine pricing** → `VaccineBrand.price` (sell) + `purchase_price` (cost) + `max_discount`.
- **Billing & collection** → `Invoice` / `InvoiceItem` / `Payment` (paid / balance / discount per line; doctor share; payer/coverage).
- **Discounts by category/date** → `NamedDiscount` (has `client_category`, `start/end_date`, `applies_to(patient, doctor_id, on_date)`).
- **Contracts/insurance** → `PayerEntity` / `PayerContract`.
- **Vaccine schedule & history** → `Vaccine`, `VaccineBrand`, `VaccineScheduleTemplate`, `PatientVaccine`, `patient_plan()` / `next_due_dose()`.
- **Stock** → `VaccineInventory` batches (FEFO deduction already in the give-dose route).
- **Reminders** → giving a dose already sends the WhatsApp `vaccine_given` template with the next-due date; mandatory vaccines already skip stock.

## Phases

### Phase 1 — Multi-dose vial inventory unit ✅ (done)
- `VaccineBrand.doses_per_vial` (1 = single-dose ampoule/patient; N = one vial covers N patients).
- Stock counted in **patient doses**; add-batch accepts **vials** (× doses/vial) or doses; stock shows "N doses (≈M vials)".
- Brand management + add-batch UI updated.

### Phase 2 — Vaccine as a bookable service
- Appointment `service = vaccine` (free service): reception searches patient → picks "vaccine" service → picks the vaccine (commercial name) + dose number → booking shows in the board as "vaccine".
- Mandatory vaccines = info-only (no stock, no charge); optional brands carry a price.

### Phase 3 — Doctor adds vaccine in the room → reception charge
- In the visit/exam, doctor records the administered vaccine (dose), with a **"given outside clinic"** flag that skips stock + charge.
- Clinic-given dose → deduct 1 dose from stock (FEFO) + flag a pending charge for reception.
- Whether a walk-in exam patient also wants a vaccine surfaces to reception.

### Phase 4 — Collection / cashier screen
- Per-patient "dues today" (exam/consult + vaccine) with paid / remaining / discount.
- Charge vaccine on exit; **refund request** when the doctor changes exam→consult after reception charged exam.
- End-of-day cashier drawer reconciliation (collected − refunds).

### Phase 5 — Reminders, certificate, messaging polish
- Reminder for the **next** dose after each given dose (per schedule); booster/seasonal: "done" vs "needs a yearly booster".
- Certificate shows the dose **timeline** with labels (first / second / third / booster / seasonal).
- Only doctor-recorded doses appear in the patient file; mandatory-status is information for the doctor.

### Phase 6 — Discounts/category everywhere
- Link a patient to their category + contract/discount from anywhere it's relevant (booking, visit, invoice), surfaced consistently and without re-entry.

### Done since
- **Per-doctor pricing** (`DoctorServiceCommission.price_override`, incl. free).
- **Visit type → service mapping** (`utils/pricing.py`).
- **Visit → invoice container**: billing a visit pre-fills the base line at the doctor's price.
- **Doctor account statement** (Reports → Staff → كشف حساب): cases by service + doctor share, printable.

### Doctor economics on vaccines (requested)
- Add `VaccineBrand.doctor_fee` = the part of the vaccine price that goes to the
  doctor (his cut per dose). So a vaccine dose, when billed, records a doctor
  share like any service line, and shows up in the doctor statement.
- **Profit/loss per vaccine** = `price − purchase_price − doctor_fee` (clinic
  margin). A vaccine margin report so the clinic knows it profits vs loses.

### Mandatory vs optional vaccines (confirmed understanding)
- **Mandatory / government** vaccines: given at government units, **not** in the
  clinic → **no stock, no charge**. Info-only: the doctor tracks the child's
  status. (Code already skips stock when `is_mandatory`.)
- **Optional** vaccines: given in the clinic → tracked in stock + billed.

### Stocktake
- Store stocktake exists (Inventory → Store → Stocktake) for general items.
- A vaccine-batch stocktake (count vs system per batch) is still TODO.

## Open decisions
- Refund on exam→consult: actual cash back vs paper drawer adjustment.
- Vaccine doctor share as a per-brand `doctor_fee` (recommended) vs a separate
  vaccination-fee service.
