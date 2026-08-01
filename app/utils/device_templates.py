"""What each kind of device actually measures.

The program seeds a catalogue of devices and a priced service for each — and
then seeded no measurement fields at all, so every device arrived **configured,
priced, and unusable**: opening a study said "this device has no measurement
template, define its fields first". A device you cannot record a result on is
not a feature, and a clinic is unlikely to guess that the missing piece is a
form somewhere in settings.

**On normal ranges, and why most of these are blank.**

A range here decides whether a printed report says a child's result is out of
range. In paediatrics most of these numbers move with age — a heart rate of 140
is normal at two months and alarming at twelve years — so a single adult range
would flag healthy infants as abnormal on a document that goes home with a
parent.

So ranges are filled in **only where they genuinely do not depend on age**, and
left blank everywhere else. A blank range prints no verdict, which is the honest
output when the program does not know the child's expected value. The clinic can
add its own per-device ranges, and its numbers will be better than ours because
they know their population and their machine.

The seeding follows the same rule as the vaccine schedules and the chart of
accounts: fill in what is missing, never touch what is there. A device that
already has fields is left completely alone, including one whose fields somebody
deleted on purpose.
"""

# device_type -> [(name_ar, name_en, unit, normal_low, normal_high)]
#
# Where a range is None it is because the value is age-dependent in children,
# free text, or a category — not because nobody got round to it.
DEFAULT_MEASUREMENTS = {
    "spirometry": [
        ("FEV1", "FEV1", "L", None, None),          # age/height dependent
        ("FVC", "FVC", "L", None, None),            # age/height dependent
        # The ratio is the one spirometry number that holds across childhood;
        # below ~80% suggests obstruction at any age.
        ("FEV1/FVC", "FEV1/FVC", "%", 80, None),
        ("PEF", "PEF", "L/s", None, None),
        ("FEF 25-75", "FEF 25-75", "L/s", None, None),
        ("نسبة التحسن بعد الموسع", "Post-bronchodilator change", "%", None, None),
    ],
    "ecg": [
        # Deliberately no range: normal paediatric heart rate runs from about
        # 160 in a newborn to about 60 in a teenager. One range would be wrong
        # for nearly every child who walks in.
        ("معدل ضربات القلب", "Heart rate", "bpm", None, None),
        ("الإيقاع", "Rhythm", None, None, None),
        ("PR", "PR interval", "ms", None, None),    # age dependent
        ("QRS", "QRS duration", "ms", None, None),  # age dependent
        # QTc is the exception: > 460 ms is prolonged throughout childhood.
        ("QTc", "QTc", "ms", None, 460),
        ("المحور", "Axis", "°", None, None),
        ("ملاحظات", "Notes", None, None, None),
    ],
    "echo": [
        # Ejection fraction is a ratio, so it does not move with body size.
        ("الكسر القذفي (EF)", "Ejection fraction (EF)", "%", 55, 70),
        ("الكسر القصري (FS)", "Fractional shortening (FS)", "%", 28, 44),
        ("LVEDD", "LVEDD", "mm", None, None),       # scales with body size
        ("LVESD", "LVESD", "mm", None, None),       # scales with body size
        ("IVS", "IVS", "mm", None, None),
        ("الصمامات", "Valves", None, None, None),
        ("الحاجز بين الأذينين/البطينين", "ASD / VSD", None, None, None),
        ("ارتشاح التامور", "Pericardial effusion", None, None, None),
        ("الانطباع", "Impression", None, None, None),
    ],
    "eeg": [
        ("الإيقاع الأساسي", "Background rhythm", None, None, None),
        ("شحنات صرعية", "Epileptiform discharges", None, None, None),
        ("بؤرة بطيئة", "Focal slowing", None, None, None),
        ("التنفس العميق/التنبيه الضوئي", "Hyperventilation / photic", None, None, None),
        ("الانطباع", "Impression", None, None, None),
    ],
    "ultrasound": [
        ("المنطقة", "Region", None, None, None),
        ("النتائج", "Findings", None, None, None),
        ("القياسات", "Measurements", None, None, None),
        ("الانطباع", "Impression", None, None, None),
    ],
    "audiometry": [
        # Hearing thresholds are one of the few paediatric numbers with a fixed
        # cut-off: above 20 dB HL is a hearing loss at any age.
        ("متوسط النغمة النقية — يمين", "PTA — right", "dB HL", None, 20),
        ("متوسط النغمة النقية — يسار", "PTA — left", "dB HL", None, 20),
        ("عتبة استقبال الكلام — يمين", "SRT — right", "dB HL", None, 20),
        ("عتبة استقبال الكلام — يسار", "SRT — left", "dB HL", None, 20),
        ("تمييز الكلام — يمين", "Speech discrimination — right", "%", 90, None),
        ("تمييز الكلام — يسار", "Speech discrimination — left", "%", 90, None),
    ],
    "tympanometry": [
        ("النوع — يمين", "Type — right", None, None, None),
        ("النوع — يسار", "Type — left", None, None, None),
        ("الضغط — يمين", "Pressure — right", "daPa", -100, 50),
        ("الضغط — يسار", "Pressure — left", "daPa", -100, 50),
        ("المطاوعة — يمين", "Compliance — right", "ml", 0.3, 1.6),
        ("المطاوعة — يسار", "Compliance — left", "ml", 0.3, 1.6),
        ("منعكس الركابية", "Stapedial reflex", None, None, None),
    ],
    "holter": [
        ("أقل معدل", "Minimum HR", "bpm", None, None),
        ("أعلى معدل", "Maximum HR", "bpm", None, None),
        ("متوسط المعدل", "Mean HR", "bpm", None, None),
        ("أطول توقف", "Longest pause", "s", None, None),
        ("نبضات بطينية خارجة", "Ventricular ectopics", None, None, None),
        ("نبضات فوق بطينية", "Supraventricular ectopics", None, None, None),
        ("الانطباع", "Impression", None, None, None),
    ],
    # `other` is deliberately absent: a device the catalogue could not classify
    # has no fields anybody can guess, and inventing some would be worse than
    # the empty form the clinic has to fill in anyway.
}


def measurements_for(device_type):
    """The default fields for a device type — empty for one we cannot guess."""
    return DEFAULT_MEASUREMENTS.get(device_type or "", [])


def seed_device_measurements(device=None):
    """Give devices their measurement fields. Returns how many were created.

    Only ever fills an **empty** device. One that already has fields is left
    exactly as the clinic left it — including one somebody stripped down to
    three fields on purpose, which a "top up the missing ones" rule would
    quietly undo every time it ran.
    """
    from app.extensions import db
    from app.models import DeviceMeasurement, MedicalDevice

    devices = [device] if device is not None else MedicalDevice.query.all()
    made = 0
    for dev in devices:
        if dev is None or dev.measurements:
            continue
        fields = measurements_for(dev.device_type)
        for order, (name, name_en, unit, low, high) in enumerate(fields):
            db.session.add(DeviceMeasurement(
                device_id=dev.id, name=name, name_en=name_en, unit=unit,
                normal_low=low, normal_high=high, sort_order=order))
            made += 1
    if made:
        db.session.commit()
    return made
