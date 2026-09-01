# Emergency, jaundice and the preterm newborn — plan

Asked for as *"وفى الجزء بتاع الطوارئ محتاجين نبنيه ونحطله خطة والحالات بتاعت
الصفراء مع NICU الحضانات او الاطفال المبتثرين والصفراء"*.

Two decisions were taken before any of this was written:

- **The bilirubin threshold is a calculator, never the assistant.** The number
  decides phototherapy or an exchange transfusion. This program already
  refuses to let the model give a drug dose, for a reason written down in
  `ai_discuss.py`: *a second, less careful road to the same number is how a
  program ends up with two answers to "how much" and no way to know which one
  a nurse read.* A threshold is that same category. The model may **explain**
  the calculator's answer; it may not produce it.
- **`birth_time` is added.** Optional, three-valued like `is_preterm` — see
  Phase 1.

---

## What already exists (reused, not rebuilt)

| Thing | Where | Note |
|---|---|---|
| Gestation as weeks **and days** | `Patient.gestation_weeks/_days` | Stored as "36+4", never 36.57, because that is how a discharge summary prints it |
| Birth weight | `Patient.birth_weight_kg` | Optional; blank means nobody said |
| Preterm, three-valued | `Patient.is_preterm` | `None` = nobody said, which is not "no" |
| Corrected age | `app/utils/growth.py:age_for` | Already used by the growth charts |
| Transfer out | `Visit.referred_at / referred_to / referral_note` | Reversible; a referral written on the wrong child happens |
| Urgent triage of *messages* | `app/utils/triage.py` | WhatsApp only. Raises a thread, never lowers one |
| An urgent consultation service | `services.py: emergency_care` | `SVC-URGENT`, 350 |
| Vitals incl. BP by arm | `VitalSigns` | |

### And one thing that exists in the wrong place

The **age-banded paediatric vital ranges** — heart rate and respiratory rate
by age, with a normal band and a tolerated band — live only in the browser, in
`record.html`'s Alpine component as `_peds`. Nothing in Python can read them.

That matters here because triage has to run on the server: the nursing station
needs it, a report needs it, and a colour computed in one screen's JavaScript
cannot be the same colour anywhere else. Phase 2 moves the table into Python
and has the screen read the one copy, rather than adding a second that can
disagree with it.

---

## Phase 1 — `birth_time`, and the hours that depend on it

Neonatal jaundice thresholds move **by the hour** through the first days.
`Patient.date_of_birth` is a `Date`. Without a time, the program is guessing
±24 hours, and at 48 hours of age that is the whole distance between "go home"
and "start phototherapy".

- `Patient.birth_time` — nullable `Time`, plus migration.
- `Patient.age_hours` — `None` when no birth time is recorded. **Not** a
  fallback to midnight: a made-up hour is exactly the failure this phase
  exists to prevent, and a screen that silently assumed one would be confidently
  wrong for twelve hours either way.
- The patient form takes it beside gestation and birth weight, optional,
  labelled so blank reads as *nobody said*.
- Everything hour-dependent refuses to compute without it and says which field
  is missing.

## Phase 2 — Triage in Python, and one table for the ranges

- `app/utils/triage_vitals.py`: the `_peds` table, moved, plus
  `band(kind, age_months, value)` returning `ok | warn | bad | unknown`.
- `record.html` reads it from the server instead of holding its own copy.
  Guard test: the numbers appear in exactly one place in the repository.
- `triage(patient, vitals)` → a colour and **the readings that caused it**.
  The reason travels with the verdict; a red badge nobody can account for gets
  ignored on the second day.
- Never lowers: like the message triage, it can only raise. A child a nurse
  called urgent stays urgent whatever the numbers say.

## Phase 3 — The emergency encounter

`emergency_care` is a capability today that maps to `{"visits"}` — a name with
no screen. The same shape as dentistry before it got a front door.

- An emergency visit is a `Visit` with `channel="emergency"`, not a new model.
  It is the same encounter with a different tempo, and a parallel model would
  split one child's history across two tables.
- **Repeated observations.** The one thing an emergency needs that a
  consultation does not: `VitalSigns` is `unique(visit_id)` — one set per
  visit. A child under observation is measured every fifteen minutes. So
  `Observation`: many rows per visit, each timed, each triaged, shown as a
  strip so the *trend* is visible. Deterioration is a shape, not a reading.
- The landing page lists who is currently under observation and how long they
  have been, and **must be reachable from the sidebar** — the guard test added
  in #312 will fail otherwise, which is the point of it.

## Phase 4 — Jaundice: the calculator

- `app/utils/jaundice.py`, deterministic, offline, no AI:
  - inputs: hours of age, gestational weeks, total serum bilirubin,
    neurotoxicity risk factors
  - outputs: the phototherapy threshold, the exchange threshold, where this
    child sits against each, and when to repeat
- Thresholds live in `app/data/jaundice_thresholds.json` with the edition they
  came from named in the file, so a clinic on a different guideline replaces
  data and not code — the same reason the specialty panels are data.
- **It refuses rather than guesses.** No birth time, no gestation, no
  bilirubin → it says which one is missing. A threshold computed from an
  assumed gestation is a number nobody can audit.
- The AI, when the clinic has it on, **explains** the result and never
  restates the number as its own: what is driving it, what would change it,
  what to watch for. Its own switch, off by default.

## Phase 5 — Transfer to NICU

A clinic does not run a NICU; it decides a baby needs one and sends them.
What the receiving unit needs is exactly what gets lost on the phone.

- Extend the existing referral rather than build a second one: a NICU transfer
  is a referral that carries gestation, birth weight, hours of age, the
  bilirubin series with times, feeding, and the reason.
- Printable, because that is what physically travels with the baby.

---

## What this plan deliberately does not do

- **No inpatient module.** `ward`, `nicu`, `icu` stay capabilities without
  screens. A clinic that admits patients needs a bed census, handovers and
  drug rounds; that is a different program and pretending otherwise with three
  screens would be worse than the honest gap.
- **No dose anywhere in it.** Phototherapy is not dosed here and no drug is.
  The dose tool exists and stays the only road to a number.
- **No automatic escalation.** Nothing calls anybody, and nothing marks a
  child safe. The program raises and shows; a person decides.
