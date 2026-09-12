"""How a bill adds itself up — the summary over the detail.

Asked for in one sentence: *«يكون عندك ملخص رئيسي … وفي نفس الوقت زر عرض
التفاصيل»*. A fortnight in a hospital produces sixty or seventy lines — every
night, every dose, every round — and nobody, family or insurer, reads it line
by line first. They read six numbers: الإقامة كذا، العمليات كذا، الأدوية كذا.
Then they open the one that looks wrong.

So there are two views of the same lines and **one set of arithmetic**: the
section totals are the lines' own nets added up, never a second figure kept
anywhere. A summary that could disagree with its detail is a summary that
costs more to check than the detail did.

**Nothing here reads a section by name.** The grouping is whatever sections
exist, in whatever order the clinic put them — which is why the axis was safe
to open in the first place. A hospital that types «مستلزمات غرفة العمليات»
gets a row in this summary the same minute, and no code changed.
"""
from app.models import Service
from app.models.service import INVOICE_SECTION_ICONS
from app.utils import invoice_sections as isec


OTHER = "other"


def _section_of(item):
    """Which part of the bill this line belongs under.

    A line with no service — a box off the pharmacy shelf, a free-text charge
    somebody typed — has no classification to read, and gets ``other`` rather
    than a guess. Guessing here would put money under a heading nobody chose,
    which is precisely what a summary is read to rule out.
    """
    service = getattr(item, "service", None)
    if service is None and getattr(item, "service_id", None):
        service = Service.query.get(item.service_id)
    if service is None:
        return OTHER
    return service.section_key() or OTHER


def by_section(invoice, lang="ar"):
    """The bill grouped into its sections, in the clinic's own order.

    Each row carries the section (or ``None`` for the unclassified bucket),
    its label, its lines and their total. Empty sections are left out: a
    summary listing eight headings of which five read zero is a summary
    nobody's eye can land on.
    """
    if invoice is None:
        return []
    known = {row.key: row for row in isec.all_sections()}
    order = {key: i for i, key in enumerate(known)}

    buckets = {}
    for item in invoice.items:
        buckets.setdefault(_section_of(item), []).append(item)

    rows = []
    for key, items in buckets.items():
        section = known.get(key)
        rows.append({
            "key": key,
            "section": section,
            # The clinic's icon, then the built-in one for that key, then a
            # neutral mark. The middle step is what makes an **unseeded**
            # catalogue draw properly: ``all_sections`` falls back to rows
            # built from the built-in keys, and those carry no icon of their
            # own — so without this the summary of a clinic mid-upgrade is a
            # column of blank squares.
            "icon": (getattr(section, "icon", None)
                     or INVOICE_SECTION_ICONS.get(key)
                     or "bi-three-dots"),
            "label": (section.display_name(lang) if section is not None
                      else None),
            "items": items,
            # The lines' own nets, added up. There is no second number.
            "total": round(sum(i.net for i in items), 2),
        })
    # Unclassified last, whatever it is called: it is the bucket somebody
    # should empty, not a heading the bill leads with.
    rows.sort(key=lambda r: (r["section"] is None, order.get(r["key"], 999)))
    return rows


def by_day(items):
    """One section's lines grouped by the day the work was done.

    The second question after "how much was the stay" is "what happened on
    the Tuesday", and until the line carried its own date there was no way to
    ask it — the day lived inside the description text of the bed's lines and
    nowhere at all on anybody else's.

    Lines whose day nobody recorded fall back to the invoice's own date
    (:attr:`InvoiceItem.on_date`), so they group with the day the bill was
    raised rather than forming a nameless pile.
    """
    days = {}
    for item in items:
        days.setdefault(item.on_date, []).append(item)
    return [{"day": day,
             "items": rows,
             "total": round(sum(i.net for i in rows), 2)}
            # ``None`` only when the invoice itself has no date, which the
            # column forbids — but sorting must not raise if it ever happens.
            for day, rows in sorted(days.items(),
                                    key=lambda kv: (kv[0] is None, kv[0]))]


def spans_days(invoice):
    """Whether this bill covers more than one day.

    What decides if the detail is worth grouping by day at all: an afternoon's
    receipt broken into one heading per day is noise, and a fortnight's stay
    without it is unreadable.
    """
    if invoice is None:
        return False
    return len({i.on_date for i in invoice.items}) > 1
