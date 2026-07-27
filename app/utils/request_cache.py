"""Ask the database once per request, not once per row.

Some answers don't change while a page is being built: what the clinic's
settings say, what a role is allowed to do, what a visit type is called. They
were being looked up wherever they were needed, which on a busy screen means
the same row fetched hundreds of times — a day's appointment board asked the
``roles`` table 146 times and the cashier screen asked ``settings`` 329 times
to render one page.

None of that is slow enough to notice on a laptop with fifty patients on file.
It is what turns into a two-second page on a clinic PC after two years of
records, at the exact moment when the waiting room is full.

So they are remembered for the length of one request and forgotten after it.
Not a cache in the usual sense — nothing survives the response, so there is no
staleness to reason about and no invalidation to get wrong. A write inside the
same request drops what it changed (see ``forget``), because a settings screen
has to show what it just saved.
"""
from flask import g, has_app_context

_BUCKET = "_request_cache"


def _store():
    """The per-request bucket, or None when there is no request to hang it on.

    Outside an app context — a CLI command, a background job — this returns
    None and every caller falls through to the database. Correct, and slower
    only where nobody is waiting.
    """
    if not has_app_context():
        return None
    bucket = getattr(g, _BUCKET, None)
    if bucket is None:
        bucket = {}
        setattr(g, _BUCKET, bucket)
    return bucket


def remember(key, produce):
    """``produce()`` once per request for this key; the same answer after."""
    bucket = _store()
    if bucket is None:
        return produce()
    if key not in bucket:
        bucket[key] = produce()
    return bucket[key]


def forget(key=None):
    """Drop one key (or everything) — for when this request just changed it."""
    bucket = _store()
    if bucket is None:
        return
    if key is None:
        bucket.clear()
    else:
        bucket.pop(key, None)
