"""Weight and height measured inside one episode — an emergency attendance,
a stay — for the sheets that print them (``utils/er_sheet``,
``utils/history_record``).

Only measurements dated inside the episode count: last month's weight on
today's sheet would read as today's.
"""


def during(patient_id, start, end=None, which="latest"):
    """``(weight_kg, height_cm)`` recorded between ``start`` and ``end``
    (moments, compared by the clinic's own calendar day) — the ``latest`` of
    each, or the ``first`` («on admission»). ``None`` where none was taken."""
    from app.models import GrowthRecord
    from app.utils.clock import local_date

    q = GrowthRecord.query.filter(GrowthRecord.patient_id == patient_id,
                                  GrowthRecord.record_date >= local_date(start))
    if end is not None:
        q = q.filter(GrowthRecord.record_date <= local_date(end))
    order = ((GrowthRecord.record_date.asc(), GrowthRecord.id.asc()) if which == "first"
             else (GrowthRecord.record_date.desc(), GrowthRecord.id.desc()))
    weight = height = None
    for rec in q.order_by(*order):
        if weight is None and rec.weight_kg:
            weight = rec.weight_kg
        if height is None and rec.height_cm:
            height = rec.height_cm
    return weight, height
