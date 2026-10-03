# The laboratory as its own sector, and the diagnostic studies in one place — plan

Asked for as *«ياريت كافة الملاحظات الى بعتها وانت متوقف تبص عليها وتحللها
ونحطها معانا فى التعديلات والاصلاحات ونبداء نتابعها وياريت نظبط القصه ترتيب
منطقى المعمل ده سكتور لواحده»*.

Every item below is one of the clinic's own notes, in the order the work has
to happen — each step stands on the one before it. A step is ticked only
when it is merged.

---

## Where the lab stands today (read from the code, not remembered)

| Exists | Where | Note |
|---|---|---|
| The bench's own rack — lab orders only | `/labs/` · `labs.index` | Echo was taken off it in an earlier fix (`tests/test_an_echo_is_not_a_blood_test.py`) |
| Radiology and the treating team's studies, two lists | `/imaging/` and `/imaging/diagnostics` | **Reached only from a link on the lab page** — no door of its own in the menu |
| Sample code | `labs.collect` | Generated when «the sample was taken» is pressed with the box blank (`YYMMDD-00001`). Not before — so nothing to stick on a tube before drawing |
| Barcodes | `app/utils/barcode39.py` | Used for store items only. **No tube label, no scan-to-open** |
| Results per analyte, flags, critical values | `lab_results.py`, `/labs/critical` | Merged (#455) |
| The catalogue | `/labs/tests` | **Lists lab, imaging and diagnostic rows together**, each with a sample and a unit box — which is how an echo reads like a blood test there |
| Add one test | `labs.add_test` | Name, kind, unit, sample, price service only |
| Stop a test | `is_active` on the edit row | Exists, but not said as «stop» |
| Analytes and reference ranges | import only (`/labs/tests/import`), shown read-only at `/labs/tests/<id>/ranges` | **No way to add or correct one by hand** |
| Sheet in / sheet out | `lab_import.py` — name, aliases, category, analyte, unit, age/sex ranges, critical, specimen, tube, TAT, where, preparation, source | **No price, no cost, no consumables** |
| Consumables taken off the shelf | `ServiceConsumable` — deducted **when billed** | Through the test's price service. Not when the sample is run, and not from a lab store |
| Several stores | `Warehouse` (`kind`, keepers) | A lab store can be one; nothing ties a test to it yet |

---

## The order of work

### Step 1 — One place for the studies, out of the lab
*«الاشعة ازاي داخله فى المعمل … يبقى مكان واحد»*

- A door of its own in the menu: **«الأشعة والفحوصات التشخيصية»**, with tabs
  inside — Radiology (X-ray, dental panoramic, CT, MRI, any other) · Echo ·
  Ultrasound · EEG · ECG. The two lists that exist become tabs of one screen;
  the module stays `labs` (switching on a new module would hide outstanding
  scans on upgrade — the reason is written at the top of `imaging/routes.py`).
- **ECG in emergency is done on the spot**: ordered from the emergency
  screen, it is marked done there by whoever did it, without a trip to
  another list.
- **EEG that needs a booking** (sleep EEG): the order can carry an
  appointment — a date and time and «needs sleep» — and the list shows the
  booked day. A routine EEG behaves like any other study.
- The catalogue gets the same split: tabs by kind, and an imaging or
  diagnostic row has **no sample and no unit** fields — what it has is the
  room that does it and whether it needs booking or preparation.

### Step 2 — The sample number before the needle, a label, and a scanner
*«ليه مش بيولد رقم العينة؟ ويقدر يطبها وتتقراء بالباركود؟»*

- The number is generated **when the order reaches the lab** (or on «print
  label»), not after drawing, so the label is on the tube before the blood.
- A tube label: child's name, file number, test(s), tube colour, the date,
  and the code as a Code-39 barcode (`barcode39.py` already draws it) — sized
  for a label printer, several tests on one tube where the tube is shared.
- **Scan to open**: a box on the lab screen that takes a barcode reader's
  input (a reader types the code and Enter) and opens that order — to mark it
  collected, received, or to enter its result.

### Step 3 — Adding and correcting a test's details by hand
*«فى تحاليل … مش مفتوح ان المعمل يدخلها او يغيراها بايده؟ ليه»*

- On a test's page: add an analyte, its unit, and its ranges (age band, sex,
  low/high, critical low/high) **one by one**, with the same approval as an
  imported range — a range typed by hand is a draft until the lab head
  approves it, exactly like an imported one. Correcting an approved range
  makes a new draft; the approved one stays in force until the new one is
  approved, and every result keeps the range it was judged against.
- «Stop this test» said in words, with the reason; a stopped test is out of
  the search for new orders, and every old order and result stays.

### Step 4 — Price, cost, and what a test uses
*«بيخصم برده مستهلكات وليه مخزن شرايط التحاليل»*

- On each test: the **price** (the service it is charged as — exists), the
  **cost**, and its **consumables** (strip, reagent, tube, needle…) with the
  quantity per test.
- A **lab store** (a `Warehouse` of kind lab) that the bench draws from.
- Consumables come off the lab store **when the sample is run** (the moment
  the result is entered, or the run is marked), not when the bill is
  printed — the strip is used whether or not the family has paid. A
  re-run takes them again and says so.
- The cost per test then reads from what was actually used, and the lab's
  margin report follows from it.

### Step 5 — The whole definition in one sheet, or one at a time
*«متاح رفعها او انزال نموذج تضاف بشكل كامل وترفع او اضافة واحد لواحد
بالخطوات المطلوبة»*

- The import sheet grows the columns from step 4: price, cost, consumable
  code and quantity (one row per consumable, like one row per analyte today).
- **«Download an empty template»** with every column and one filled example
  row, beside «download what we have».
- **A step-by-step add** for one test, in the order the program needs it:
  1. name and kind → 2. sample and tube (lab only) → 3. what it measures and
  the ranges → 4. price and cost → 5. consumables → 6. review and save.
  A test is orderable when steps 1 and 4 are done; the rest can follow.

---

## Later — written down so it is not lost

- Sample rejection with the reason (haemolysed, clotted, too little), and a
  re-draw order.
- Send-out manifest to an outside lab, and that lab's account.
- Results that come back as a PDF: read by the assistant, **confirmed by a
  person** before anything reaches the file.
- Analyser connection — only from the analyser's official documentation and
  a test setup, never from memory.
