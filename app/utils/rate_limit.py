"""A ceiling on how fast one caller can hit the open doors.

Three routes in this program answer strangers: the login form, the two
WhatsApp webhooks, and the satisfaction survey. Everything else is behind a
session. The login form already refuses a *username* after five bad passwords
— which does nothing about someone trying a thousand different usernames from
one machine, because each name is on its first attempt.

So there is a second ceiling, counted per caller rather than per account.

**What this is not.** It is a fixed window held in this process's memory. It
resets when the program restarts, and two worker processes would each keep
their own count. That is the honest size of it: a single-clinic app served by
one process, where the threat is a script hammering the login form, not a
distributed attack. A clinic exposing this to the open internet wants a real
limiter (Redis-backed) or a reverse proxy in front — and this is not a
substitute for either. It is the difference between "a thousand guesses a
second" and "a thousand guesses an hour", which is the difference that matters
for a password that was going to be guessed at all.

**A fixed window, not a sliding one**, on purpose: a caller who spends their
whole allowance at 11:59 gets a fresh one at 12:00, so the real ceiling is
twice the limit across a window boundary. Sliding windows cost a timestamp per
request to close a gap that does not change what the guard is for. The limits
below are set with that doubling assumed.
"""
import threading
import time

from functools import wraps

# (bucket, key) -> [window_started_at, count]
_hits = {}
_lock = threading.Lock()

# Above this many tracked callers, expired windows are swept. Someone rotating
# addresses would otherwise grow this dictionary until the process died —
# which would be a denial of service delivered by the thing meant to prevent
# one.
_SWEEP_AT = 4096

# The ceilings, in one place so the policy can be read without opening four
# blueprints. Per caller, per minute. Each is set well above what the honest
# user does and well below what a script does.
#
# * **Login** — a receptionist mistyping a password twice and getting it right
#   is three posts. Ten a minute leaves room for a shared desk with several
#   people signing in, and still turns a password-guessing run from thousands
#   an hour into six hundred.
# * **Webhooks** — Meta batches deliveries and retries failures, and a busy
#   afternoon at a clinic is nothing like 120 messages a minute. Set high on
#   purpose: dropping a patient's message to slow an attacker who is already
#   being turned away by the signature check would be the wrong trade.
# * **Survey** — one family opens their link once. Twenty covers a refresh, a
#   double-tap and a shared phone.
LOGIN_PER_MINUTE = 10
WEBHOOK_PER_MINUTE = 120
SURVEY_PER_MINUTE = 20


def hit(bucket, key, limit, per_seconds, now=None):
    """Count one request → ``(allowed, retry_after_seconds)``.

    ``allowed`` is False once ``limit`` requests have been counted in the
    current window; ``retry_after`` is how long until that window ends.
    """
    now = time.time() if now is None else now
    slot = (bucket, key)
    with _lock:
        if len(_hits) > _SWEEP_AT:
            _sweep(now, per_seconds)
        started, count = _hits.get(slot, (now, 0))
        if now - started >= per_seconds:
            started, count = now, 0
        count += 1
        _hits[slot] = (started, count)
        if count > limit:
            return False, max(int(per_seconds - (now - started)) + 1, 1)
        return True, 0


def _sweep(now, per_seconds):
    """Drop windows that have expired. Caller holds the lock."""
    for slot in [s for s, (started, _) in _hits.items()
                 if now - started >= per_seconds]:
        _hits.pop(slot, None)


def reset():
    """Forget every counter — for tests, and for nothing else."""
    with _lock:
        _hits.clear()


def limit(bucket, per_minute, methods=("POST",)):
    """Refuse a caller who is going too fast, with 429 and ``Retry-After``.

    Off under ``RATELIMIT_ENABLED = False`` so a test suite that signs in
    forty times isn't fighting the guard; the tests that are *about* the guard
    turn it on.

    ``methods`` keeps the ceiling off the GET that renders the login form —
    counting page loads would lock out a receptionist who refreshed.
    """
    def decorate(view):
        @wraps(view)
        def guarded(*args, **kwargs):
            from flask import current_app, request

            from app.utils.decorators import client_ip

            if (not current_app.config.get("RATELIMIT_ENABLED", True)
                    or request.method not in methods):
                return view(*args, **kwargs)
            ok, retry_after = hit(bucket, client_ip() or "?", per_minute, 60)
            if ok:
                return view(*args, **kwargs)
            return _too_fast(retry_after)
        return guarded
    return decorate


def _too_fast(retry_after):
    """A refusal that says nothing about what was being attempted.

    Deliberately not the login screen's "too many attempts" message: that one
    tells you a real username was found. This one is the same for a guessed
    password, a forged webhook and a survey being scraped.
    """
    from flask import jsonify, request

    if request.accept_mimetypes.best == "application/json" or request.is_json:
        body = jsonify(error="rate_limited")
    else:
        body = "Too many requests"
    return body, 429, {"Retry-After": str(retry_after)}
