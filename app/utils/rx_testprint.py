"""A prescription made of nothing, for aiming the printer at the paper.

Asked for so a clinic can check a layout **before** committing to it — and
above all on pre-printed letterhead, where the whole question is whether the
text lands under the printed header or on top of it. Three millimetres nobody
would notice on white paper is the doctor's name over the logo here, and the
only thing that answers it is putting real ink on the real paper and looking.

Two decisions carry this file.

**The data is invented, and obviously so.** Aligning margins by reprinting the
last real prescription would put a named child's weight, allergy and medicines
onto sheet after sheet of paper that goes in the bin. The sample child does not
exist and reads as such at a glance.

**The test page occupies exactly the space a real one does.** Anything that
adds a line — a banner saying "sample", an extra note — moves everything below
it and the page stops testing the thing it was printed for. So the marking is a
watermark *over* the layout and a rule drawn *at* the offset, neither of which
takes part in the flow.

It renders through the real ``_paper.html``. A second, simpler mock-up of the
prescription would drift from the true one, and then the preview would agree
with itself and disagree with the printer — which is the failure this feature
exists to prevent.
"""
from datetime import date

from app.utils.clock import local_today


class _Sample:
    """A stand-in that answers what the template asks of it, and nothing more.

    Plain objects rather than unsaved models: an unsaved ``Prescription`` in a
    session is one ``commit()`` elsewhere away from becoming a real
    prescription for a child who does not exist.
    """

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def _patient(lang="ar"):
    ar = lang != "en"
    return _Sample(
        id=0,
        patient_number="—",
        full_name="محمد أحمد (نموذج)" if ar else "Sample Patient",
        full_name_en="Sample Patient",
        display_name=lambda _lang="ar": ("محمد أحمد (نموذج)" if _lang != "en"
                                         else "Sample Patient"),
        date_of_birth=date(local_today().year - 2, 1, 1),
        # ``age_label`` reads these off the model rather than computing from
        # the birth date, so the stand-in has to answer them too. Two years is
        # a deliberate choice: a paediatric age label at its longest.
        age_parts=(2, 3),
        age_years=2,
        age_days=820,
        gender="male",
        allergies="بنسلين" if ar else "Penicillin",
        chronic_diseases="ربو" if ar else "Asthma",
        # Both blocks are filled on purpose: a test page that leaves them out
        # proves the layout fits only for the tidiest child in the clinic.
        latest_growth=_Sample(weight_kg=12.5, height_cm=87.0,
                              head_circ_cm=48.0, record_date=local_today()),
    )


def _with_growth(patient):
    """Give the sample its percentiles from the real growth engine.

    Computed rather than hardcoded, so a test print shows the same numbers the
    program would actually print. A made-up "P50" would make a template look
    correct while hiding how wide a real percentile badge is.
    """
    from app.utils.growth import summarise

    record = patient.latest_growth
    patient.growth_picture = {"record": record,
                              "rows": summarise(patient, record)}
    return patient


def _items(lang="ar"):
    ar = lang != "en"
    rows = [
        ("Augmentin 457mg/5ml", "5 مل" if ar else "5 ml",
         "كل ١٢ ساعة" if ar else "every 12h", "٧ أيام" if ar else "7 days",
         "بعد الأكل" if ar else "after food"),
        ("Brufen 100mg/5ml", "7 مل" if ar else "7 ml",
         "عند اللزوم" if ar else "as needed", "٣ أيام" if ar else "3 days", ""),
        ("Vitamin D drops", "٤٠٠ وحدة" if ar else "400 IU",
         "يومياً" if ar else "daily", "مستمر" if ar else "ongoing", ""),
    ]
    return [_Sample(printed=True, drug_name=n, dose=d, frequency=f,
                    duration=u, instructions=i) for n, d, f, u, i in rows]


def sample(doctor, lang="ar"):
    """A prescription object the paper template can render.

    ``doctor`` is the real signed-in doctor, deliberately: their name, title
    and licence are the longest and most awkward strings on the page, and a
    made-up short name would make a layout look like it fits when it does not.
    """
    ar = lang != "en"
    patient = _with_growth(_patient(lang))
    growth = patient.latest_growth
    return _Sample(
        id=0,
        rx_date=local_today(),
        patient=patient,
        doctor=doctor,
        visit=None,
        share_token=None,
        complaint="كحة وحرارة من ٣ أيام" if ar else "Cough and fever, 3 days",
        diagnosis="التهاب رئوي" if ar else "Pneumonia",
        diagnosis_code="J18.9",
        diagnosis_stage=None,
        items=_items(lang),
        # Methods on the real model, so they have to be callable here.
        labs=lambda: [_Sample(
            notes="",
            display_name=lambda _l="ar": ("صورة دم كاملة" if _l != "en"
                                          else "Full blood count"))],
        imaging=lambda: [_Sample(
            notes="",
            display_name=lambda _l="ar": ("أشعة صدر" if _l != "en"
                                          else "Chest X-ray"))],
        notes="",
        _growth=growth,
    )
