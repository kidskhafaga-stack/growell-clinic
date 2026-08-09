"""Answering "when did Omar last come?" from the register, not from a model.

The clinic asked to be able to ask the program about anything in it: *"when
did so-and-so last come"*, *"what vaccines has he had"*, *"I need a report for
this case addressed to the school"*.

Those three are not one kind of question, and treating them as one is the trap.

**Two of them are facts.** The date of a visit and the list of doses given are
rows. There is a correct answer and the program is holding it. Passing them
through a language model converts a certainty into a paraphrase — and a
paraphrased date is worse than no date, because it arrives with the same
confidence as a true one and a parent is told their child had a vaccine they
did not have. Nothing in here calls a model. It reads the register and returns
what it found, and when it cannot find the person it says so rather than
guessing which Ahmed was meant.

**The third one is language.** "Write me a letter for the school" is genuinely
a writing task, and that is the one worth a model — but it should be writing
*from* these rows rather than from its own recollection of a conversation. So
this module also builds the fact sheet that gets handed to the assistant when
somebody carries a question on into the chat.

The split is the whole design: the program answers what it knows, and the
model is only ever asked to phrase it.
"""
from app.utils.clock import local_today


def find_patients(term, limit=6):
    """Who could the question be about? Real rows, ranked, never guessed.

    Returns a list rather than a best match on purpose. "أحمد" is half the
    register, and a lookup that silently picks one Ahmed is a lookup that will
    eventually report the wrong child's vaccinations to somebody who believes
    it. Picking between them is a human's job and takes one click.
    """
    from app.models import Patient
    from app.utils.patients import apply_patient_search

    term = (term or "").strip()
    if len(term) < 2:
        return []
    rows = (apply_patient_search(Patient.query, term)
            .order_by(Patient.full_name).limit(limit + 1).all())
    return rows[:limit]


def facts(patient, lang="ar"):
    """Everything the register knows about this child, as data not prose.

    Each entry is a plain value the screen renders itself. Nothing here is
    phrased, formatted into a sentence, or rounded — a screen can present a
    date however it likes, and a caller that wants to hand this to a model
    can, but the numbers leave here exactly as they are stored.
    """
    from app.models import Prescription, Visit

    visits = (Visit.query.filter_by(patient_id=patient.id)
              .order_by(Visit.visit_date.desc(), Visit.id.desc()).all())
    last = visits[0] if visits else None
    today = local_today()

    out = {
        "patient": patient,
        "visits_total": len(visits),
        "last_visit": last,
        "days_since_last": ((today - last.visit_date).days
                            if last and last.visit_date else None),
        "recent_visits": visits[:5],
        "allergies": (patient.allergies or "").strip() or None,
        "chronic": (patient.chronic_diseases or "").strip() or None,
        "problems": [p for p in getattr(patient, "problems", [])
                     if getattr(p, "status", "") == "active"],
        "prescriptions": (Prescription.query
                          .filter_by(patient_id=patient.id)
                          .order_by(Prescription.rx_date.desc(),
                                    Prescription.id.desc()).limit(3).all()),
    }
    out.update(_vaccines(patient, lang))
    return out


def _vaccines(patient, lang):
    """Doses given here, and the next one owing.

    Wrapped because the plan is computed from a schedule and a catalogue, and
    a child with an odd birthday or a discontinued brand should cost the whole
    lookup nothing. A missing vaccine section is a visibly missing section; an
    exception is a blank screen.
    """
    try:
        from app.utils.vaccines import next_due_dose, patient_plan, plan_summary

        plan = patient_plan(patient, lang)
        given = []
        for vaccine in plan:
            for dose in vaccine["doses"]:
                if dose["status"] == "done":
                    given.append({"vaccine": vaccine["vaccine"],
                                  "dose": dose.get("dose_number"),
                                  "date": dose.get("given_date")})
        given.sort(key=lambda row: row["date"] or "", reverse=True)
        nxt = next_due_dose(plan)
        return {"vaccines_given": given,
                "vaccines_summary": plan_summary(plan),
                "next_dose": ({"vaccine": nxt[1], "brand": nxt[2],
                               "due": nxt[3].get("due_date"),
                               "number": nxt[3].get("dose_number")}
                              if nxt else None)}
    except Exception:                   # noqa: BLE001 - a lookup is not a plan
        return {"vaccines_given": [], "vaccines_summary": None,
                "next_dose": None}


def fact_sheet(data, anonymize=False):
    """The same facts as text, for the model that will be asked to write.

    Handed over as a closed list with an instruction not to go outside it. The
    model's job at that point is the letter's wording, not its content — the
    content is above it, already true.
    """
    patient = data["patient"]
    years, months = patient.age_parts[0], patient.age_parts[1]
    who = ("(anonymised)" if anonymize
           else f"{patient.display_name()} (#{patient.patient_number})")
    lines = [f"Patient: {who} — {years}y {months}m, {patient.gender}"]

    last = data.get("last_visit")
    if last:
        lines.append(f"Visits on record: {data['visits_total']}; "
                     f"most recent {last.visit_date} "
                     f"({data['days_since_last']} days ago)")
    else:
        lines.append("Visits on record: none")
    for visit in data.get("recent_visits") or []:
        dx = ", ".join(d.title for d in visit.final_diagnoses()) or "—"
        lines.append(f"  Visit {visit.visit_date}: dx={dx}"
                     + (f"; plan={visit.plan}" if visit.plan else ""))
    if data.get("allergies"):
        lines.append(f"Allergies: {data['allergies']}")
    if data.get("chronic"):
        lines.append(f"Chronic conditions: {data['chronic']}")
    for problem in data.get("problems") or []:
        lines.append(f"Active problem: {problem.display_title('en')}")
    for row in (data.get("vaccines_given") or [])[:20]:
        name = getattr(row["vaccine"], "code", None) or row["vaccine"]
        lines.append(f"Vaccine given: {name} dose {row['dose']} on {row['date']}")
    nxt = data.get("next_dose")
    if nxt:
        name = getattr(nxt["vaccine"], "code", None) or nxt["vaccine"]
        lines.append(f"Next dose owing: {name} dose {nxt['number']} due {nxt['due']}")
    return "\n".join(lines)


# The instruction that keeps the model inside the rows above. Stated as a
# prohibition rather than a preference because "try not to invent dates" is
# not a rule anything obeys under pressure to be helpful.
SYSTEM = (
    "You are helping the staff of a paediatric clinic. The RECORD below is "
    "the clinic's own data and is authoritative. Answer only from it. If the "
    "record does not contain what was asked, say that it does not — never "
    "estimate, infer or fill in a date, a dose or a diagnosis that is not "
    "written here. When asked to draft a letter or report, use only these "
    "facts and leave a blank for anything the record does not hold.\n\n"
    "RECORD:\n"
)
