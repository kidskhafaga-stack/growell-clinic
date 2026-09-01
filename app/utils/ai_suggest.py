"""Diagnosis suggestions from what the doctor has typed on the visit screen.

Asked for as *"يقترح تشخيصات للطبيب للتسهيل من غير ما نلغي البحث عن التشخيص
يبقى افتراح"*, and then narrowed to what it is really for: *"لو الدكتور مش
حافظ الاكواد او التشخيص مظبوط فا يقترح هو"*. A doctor who has just examined a
child knows what is wrong with them; what they do not carry in their head is
which of eleven thousand ICD titles the classification calls it, and which
four characters go next to it.

**This is not the discussion mode, and the difference is the input.**
:mod:`app.utils.ai_discuss` reasons about a child from their *file* — history,
past visits, a summary — and lives on the patient profile. This reads the
notes being written *right now*, in the room, before the visit is saved, and
lives one field away from the ICD search it feeds. Same model, different
question, so a different prompt.

**The model names the diagnosis. The program owns the code.**

This is the whole safety design and it is worth stating plainly. A model asked
for an ICD code will produce one, confidently, and it will sometimes be a code
that means something else — off by a character, or from the wrong chapter, or
simply invented. A wrong code does not stop at the screen: it goes into the
file, into the report, and into the insurance claim, and every one of those
reads as if a doctor chose it.

So the model is never asked for a code. It is asked for a name, and
:func:`resolve` looks that name up in the clinic's own ICD table — the same
:func:`app.utils.icd.search_icd` the manual search box uses. A suggestion whose
name matches nothing arrives **with no code at all** and says so, which is the
honest outcome: the doctor still has the name, and the search box is right
there.

**Nothing here saves anything.** A suggestion fills the form the doctor was
already filling. They press add, or they do not, and the default type stays
`working` — a machine's opinion does not get to enter a file as `final`.
"""
import json
import re

# How many to ask for. Long lists are not more useful mid-consultation: past
# about five the doctor is reading rather than deciding, which is the opposite
# of what this is for.
MAX_SUGGESTIONS = 5

# Below this there is nothing to reason from, and asking anyway spends the
# clinic's money on producing a plausible list out of an empty screen — which
# is worse than no list, because it looks like the same feature working.
MIN_CHARS = 12

SYSTEM = (
    "You help a paediatrician name the diagnosis they are already thinking "
    "of, so they can find it in a classification. You are given the notes "
    "from a consultation happening right now.\n\n"

    "Reply with JSON and nothing else — no prose before or after, no code "
    "fence. A single object:\n"
    '{"suggestions": [{"ar": "...", "en": "...", "why": "...", '
    '"danger": true|false}]}\n\n'

    f"At most {MAX_SUGGESTIONS} entries.\n"
    "- \"en\": the diagnosis as a medical classification would title it, in "
    "English. This is what will be searched, so give the standard term "
    "(\"Acute tonsillitis\", not \"very sore throat\").\n"
    "- \"ar\": the same diagnosis in Arabic, as an Egyptian paediatrician "
    "would write it.\n"
    "- \"why\": the findings in these notes that point to it — quote the "
    "note's own words. One short line. If nothing in the notes supports it, "
    "do not list it.\n"
    "- \"danger\": true for a diagnosis that must not be missed, whether or "
    "not it is likely.\n\n"

    "Rules that override anything else:\n"
    "- **Never give a code.** No ICD code, no code-like string, in any "
    "field. The program holds the classification and will attach the code "
    "itself; a code from you would be plausible and sometimes wrong, and it "
    "would end up in the child's file.\n"
    "- **Never give a dose**, a strength or a duration. This program has a "
    "dose tool.\n"
    "- Put the dangerous ones first, then the likely ones. Not the other way "
    "round: an ordinary-looking case is exactly where the dangerous one gets "
    "read last.\n"
    "- Do not invent findings. Reason only from the notes given. If they are "
    "too thin to name anything, return an empty list.\n"
    "- No percentages and no confidence scores. A number would be read as "
    "measurement and it is not one.\n\n"

    "CONSULTATION NOTES:\n"
)


def enough_to_ask(brief):
    """Whether there is anything here to reason from.

    Checked before the call, not after: a screen with nothing on it should say
    "write the complaint first", not spend a clinic's money finding out that a
    model will describe a plausible child from no information at all.
    """
    return len(_meat(brief)) >= MIN_CHARS


def _meat(brief):
    """The brief minus its own labels — what the doctor actually contributed.

    Without this the length check passes on an empty visit, because the header
    lines ("Age: 3y 2m", "Sex: male") are themselves longer than the minimum
    and are written by the program, not by the doctor.
    """
    return "".join(line.split(":", 1)[1].strip()
                   for line in brief.splitlines()
                   if ":" in line and not line.startswith("Age:")
                   and not line.startswith("Sex:"))


# What the screen may send instead of what the database holds, and the length
# each is trimmed to. A runaway paste must not become a runaway bill.
TYPED_FIELDS = {"cc": "Complaint", "exam": "Examination", "notes": "Notes"}
MAX_FIELD_CHARS = 4000


def case_brief(visit, lang="ar", typed=None):
    """What is on the screen now, as text for the model.

    ``typed`` is what the doctor has in the boxes *this second*, which is not
    always what the visit row holds. The suggestion is asked for mid-
    consultation — the complaint has just been written and the examination is
    still being written — and a brief built only from the saved row would
    reason about the previous state of the screen and look, to the doctor who
    just typed three lines, like a model that ignored them. So the typed text
    wins where it is present, and the stored value stands where it is not.

    Deliberately not the patient's file. The file has its own mode with its
    own prompt and its own switch; sending it from here would mean a doctor
    who turned on "suggest a diagnosis" had also, without being asked, turned
    on "send this child's history to a vendor".

    The child is never named. Nothing here needs a name — age, sex and the
    findings are the whole of what a differential turns on — so this does not
    depend on the anonymise setting being on. It simply never has the name.
    """
    from app.utils import panels

    patient = visit.patient
    years, months = patient.age_parts[0], patient.age_parts[1]
    lines = [f"Age: {years}y {months}m", f"Sex: {patient.gender}"]

    # Prematurity, when it is known. It changes the differential in a way age
    # alone does not, and the file already distinguishes "term" from "nobody
    # said" — so this passes on that distinction rather than flattening it.
    if patient.is_preterm:
        lines.append(f"Born preterm: {patient.gestation_weeks}"
                     f"+{patient.gestation_days or 0} weeks")

    for label, value in (("Allergies", patient.allergies),
                         ("Chronic", patient.chronic_diseases)):
        if (value or "").strip():
            lines.append(f"{label}: {value.strip()}")

    stored = {"cc": visit.chief_complaint, "exam": visit.clinical_exam,
              "notes": visit.notes}
    typed = typed or {}
    for field, label in TYPED_FIELDS.items():
        value = typed.get(field)
        if not (value or "").strip():
            value = stored.get(field)
        if (value or "").strip():
            lines.append(f"{label}: {value.strip()[:MAX_FIELD_CHARS]}")

    vitals = visit.vitals
    if vitals is not None:
        readings = []
        for label, value, unit in (
                ("Temp", vitals.temperature_c, "C"),
                ("Pulse", vitals.pulse_bpm, "/min"),
                ("Resp", vitals.resp_rate, "/min"),
                ("SpO2", vitals.spo2, "%"),
                ("Weight", vitals.weight_kg, "kg"),
                ("Height", vitals.height_cm, "cm"),
                ("Head circ", vitals.head_circ_cm, "cm")):
            if value is not None:
                readings.append(f"{label} {value}{unit}")
        if vitals.bp_systolic and vitals.bp_diastolic:
            arm = f" ({vitals.bp_arm} arm)" if vitals.bp_arm else ""
            readings.append(f"BP {vitals.bp_systolic}/"
                            f"{vitals.bp_diastolic}{arm}")
        if readings:
            lines.append("Vitals: " + ", ".join(readings))

    # The specialty panel's own readings, under their English labels. A
    # cardiology or dental panel is where the specific finding was written,
    # and a brief that carried the general exam but not the panel would be
    # missing the part the doctor filled in most carefully.
    taken = panels.all_readings(visit)
    if taken:
        key = (visit.specialty_panel or "").strip()
        meta = panels.panel(key)
        labels = {field["code"]: field.get("label_en") or field["code"]
                  for field in (meta or {}).get("fields", [])}
        entries = [f"{labels.get(code, code)} {row.value}"
                   for code, row in taken.items()
                   if (row.value or "").strip()]
        if entries:
            lines.append(f"Panel ({key}): " + ", ".join(entries))

    return "\n".join(lines)


def parse(text):
    """The model's reply as a list, or ``[]`` — never an exception.

    Models wrap JSON in prose and in code fences however firmly they are told
    not to, and a consultation screen must not show a stack trace because one
    did. Anything unparseable is no suggestions, which the screen already
    knows how to say.
    """
    if not (text or "").strip():
        return []
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    else:
        start, end = body.find("{"), body.rfind("}")
        if start != -1 and end > start:
            body = body[start:end + 1]

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    out = []
    for item in (data.get("suggestions") or [])[:MAX_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        ar = str(item.get("ar") or "").strip()
        en = str(item.get("en") or "").strip()
        if not (ar or en):
            continue
        out.append({"ar": ar or en, "en": en or ar,
                    "why": str(item.get("why") or "").strip(),
                    "danger": bool(item.get("danger"))})
    return out


# A code, or something shaped like one, anywhere in a field the model wrote.
# `J06.9`, `J069`, `A15`, and the ICD-11 shape `1A00`. Matched loosely on
# purpose: this is not parsing, it is refusing.
_CODEISH = re.compile(r"\b[A-Z][0-9]{2}[0-9A-Z.]*\b"
                      r"|\b[0-9][A-Z][0-9A-Z.]{2,}\b")


def strip_codes(suggestions):
    """Take out any code the model produced despite being told not to.

    The prompt forbids it; this makes the prompt's compliance irrelevant. A
    code the model invented must not reach the screen at all, because a code
    on the screen next to a diagnosis reads as *the* code for it — and the one
    thing worse than a doctor not knowing the code is a doctor being shown a
    wrong one by their own program.
    """
    for item in suggestions:
        for field in ("ar", "en", "why"):
            cleaned = _CODEISH.sub("", item[field])
            item[field] = re.sub(r"\s{2,}", " ", cleaned).strip(" -—·،,")
    return [item for item in suggestions if item["ar"] or item["en"]]


def resolve(suggestions, version="10"):
    """Attach the clinic's own code to each suggestion, where one matches.

    Searched by the English title, because the full classification this
    program ships is titled in English — the Arabic sits on the curated
    entries only. Matching on the Arabic would find the eighty-odd common ones
    and nothing else, which would look like the feature working while quietly
    failing on everything uncommon, and uncommon is when a doctor needs the
    code most.

    A suggestion that matches nothing keeps its name and gets no code. That is
    not a failure to hide: the doctor has the term, and the search box beside
    this will take it.
    """
    from app.utils.icd import search_icd

    for item in suggestions:
        item["code"] = ""
        item["icd_title"] = ""
        item["icd_version"] = version
        for term, is_single_word in _attempts(item["en"]):
            hits = search_icd(term, limit=1, version=version)
            if not hits:
                continue
            title = hits[0].get("en") or hits[0].get("ar") or ""
            # A single word has to appear in the matched title *as a word*.
            # `search_icd` matches any substring, which is right for somebody
            # typing "diarr" into a live picker and wrong for a fallback
            # nobody is watching: "Made up thing disease" fell through to the
            # word "thing" and matched **K00.7, Teething syndrome**.
            if is_single_word and not re.search(
                    r"\b" + re.escape(term) + r"\b", title, re.I):
                continue
            item["code"] = hits[0]["code"]
            item["icd_title"] = title
            item["icd_version"] = hits[0]["version"]
            break
    return suggestions


# Head nouns that carry no diagnosis on their own. The fallback in
# :func:`_attempts` searches a term's last word when the fuller forms find
# nothing, and for these that search is guaranteed to return something
# irrelevant rather than nothing — which is far worse, because a code that
# arrived from a real row looks exactly like a correct one.
#
# Caught by the test for a diagnosis the table does not have: "Zzzqqx
# nonexistent condition" fell through to "condition" and came back **A51.49,
# other secondary syphilitic conditions**. Nothing about that suggestion would
# have looked wrong on the screen.
#
# Blocking them costs nothing real. A term like "Kawasaki disease" or "Celiac
# disease" matches in full; the fallback only ever fires once the full form
# has already failed, and at that point searching "disease" alone cannot
# produce a right answer.
EMPTY_WORDS = {
    # Containers: a word that holds a diagnosis but is not one.
    "condition", "conditions", "disease", "diseases", "disorder", "disorders",
    "syndrome", "syndromes", "illness", "illnesses", "state", "problem",
    "problems", "symptom", "symptoms", "signs", "unspecified", "nos",
    "other", "complaint", "complaints", "abnormality", "abnormalities",
    # Qualifiers: true of thousands of rows, so they select none of them.
    # "Imaginary paediatric syndrome" reached G47.33 — obstructive sleep
    # apnoea — through the word "paediatric" alone.
    "acute", "chronic", "recurrent", "severe", "mild", "moderate",
    "paediatric", "pediatric", "infantile", "neonatal", "childhood",
    "juvenile", "congenital", "suspected", "possible", "probable",
}


def _attempts(term):
    """``[(form, is_single_word), …]`` to look this diagnosis up under.

    Two things go wrong when the term was written by a model rather than typed
    by a doctor, and each of them returns *nothing at all* rather than a worse
    match — which is how they hide.

    **Spelling.** The bundled classification is the US clinical modification.
    "anaemia", "diarrhoea", "oesophagitis" match no row in it.

    **Length.** :func:`app.utils.icd.search_icd` wants its query as one
    contiguous run of characters in the title. A doctor types "diarr" and
    finds it; a model writes "Acute diarrhoea" and matches nothing, because
    the table's own title is "Diarrhea, unspecified" and the two words are not
    adjacent in that order. So the term's own words are tried singly — after
    the fuller forms, never before, so "Iron deficiency anaemia" reaches D50.9
    rather than the plain anaemia it ends in.

    Longest word first, and not simply the last one: the table titles Kawasaki
    disease as *"Mucocutaneous lymph node syndrome [Kawasaki]"*, so the phrase
    matches nothing and the last word is the one that carries no meaning.

    The doctor sees the matched title next to the code on the screen, which is
    the check on all of this: a fallback that reached too far is visible
    before anybody clicks it.
    """
    from app.utils.icd import americanise

    words = [w.strip(".,;()[]") for w in re.split(r"[\s,;]+", term or "")]
    # Longest first, because in a medical phrase the longest word that is not
    # a qualifier is almost always the specific one: "Kawasaki disease" is
    # found under "Kawasaki", never under "disease".
    single = sorted((w for w in words
                     if len(w) >= 5 and w.lower() not in EMPTY_WORDS),
                    key=len, reverse=True)

    forms, seen = [], set()
    for candidate, is_single_word in (
            [(term, False), (americanise(term), False)]
            + [(form, True) for word in single
               for form in (word, americanise(word))]):
        candidate = (candidate or "").strip()
        if candidate and candidate.lower() not in seen:
            seen.add(candidate.lower())
            forms.append((candidate, is_single_word))
    return forms


def suggest(visit, lang="ar", typed=None, chat=None):
    """The whole path: brief, ask, parse, de-code, resolve.

    ``chat`` is injectable so the steps either side of the model can be tested
    without one — the parsing and the code resolution are where this gets
    things wrong, and they must not be untestable because they sit behind a
    paid network call.
    """
    if chat is None:
        from app.utils.ai import chat

    brief = case_brief(visit, lang, typed)
    if not enough_to_ask(brief):
        return {"ok": False, "error": "too_thin"}

    result = chat([{"role": "user", "content": brief}],
                  system=SYSTEM, feature="dx_suggest")
    if not result.get("ok"):
        return result
    found = resolve(strip_codes(parse(result.get("text", ""))))
    return {"ok": True, "suggestions": found}
