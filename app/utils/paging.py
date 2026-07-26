"""One way of showing a long list: search on top, pages below, and the
clinic decides how many rows fit on a screen.

Every screen that shows a lot of rows had solved this differently. Some
paginated at a number written into the route; some just cut the list off —
``.limit(300)`` on the drug reference, ``.limit(500)`` on the drug catalogue.
A cut-off list is the worse of the two by a distance: with 25,000 medicines on
file, the 501st simply isn't there, the screen says nothing about it, and the
only symptom is a doctor who swears the drug is missing.

So: nothing is truncated, everything is paged, and how many rows a page holds
is one choice the user makes once. It is remembered in the session because
it's a preference about a screen, not about the data — someone on a laptop
wants 25 and someone on a wide monitor in the reception wants 100, and neither
should have to say so again on every screen.
"""
from flask import request, session

# Round numbers a person actually picks. Bounded on purpose: ``?per_page=``
# comes from the URL, and "all of them" on a table of 25,000 rows is a page
# nobody can render and a query nobody should ask for.
PER_PAGE_CHOICES = (25, 50, 100, 200)
DEFAULT_PER_PAGE = 25
_SESSION_KEY = "rows_per_page"


def per_page(default=DEFAULT_PER_PAGE):
    """How many rows this screen shows.

    Taken from ``?per_page=`` when it names one of the offered sizes — and
    remembered from then on. Anything else (a typo, a probe, a stale link)
    falls back to what was remembered, then to ``default``; it is never an
    error, because a bad number in a URL should not cost someone their list.
    """
    asked = request.args.get("per_page", type=int)
    if asked in PER_PAGE_CHOICES:
        session[_SESSION_KEY] = asked
        return asked
    remembered = session.get(_SESSION_KEY)
    if remembered in PER_PAGE_CHOICES:
        return remembered
    return default


def page_number():
    """The requested page, floored at 1 — ``?page=0`` and ``?page=-3`` are the
    first page, not an error page."""
    return max(1, request.args.get("page", 1, type=int) or 1)


def paginate(query, default=DEFAULT_PER_PAGE):
    """Page a query the way every list screen pages one.

    ``error_out=False`` so asking for page 900 of a 3-page list gives an empty
    page rather than a 404 — which is what happens naturally when someone
    narrows a search while standing on a later page.
    """
    return query.paginate(page=page_number(), per_page=per_page(default),
                          error_out=False)


def page_window(pagination):
    """``(first, last)`` row numbers on this page, for "showing 51–75 of 312".

    A page number alone doesn't tell anyone where they are in 25,000 rows.
    """
    if not pagination or not pagination.total:
        return (0, 0)
    first = (pagination.page - 1) * pagination.per_page + 1
    return (first, min(first + len(pagination.items) - 1, pagination.total))
