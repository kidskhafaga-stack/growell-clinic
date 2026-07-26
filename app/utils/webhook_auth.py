"""Proving an inbound webhook really came from the provider.

The webhook endpoints are the only doors into the clinic that are open to the
whole internet — they have to be, that is how WhatsApp delivers. What arrives
through them is written straight onto patients' records: a message in the
inbox, a rating against a doctor's name, a file filed on a child's record and
tied to the X-ray somebody ordered.

So the question is not "is this JSON well-formed" but "did the provider send
it". The two providers answer that differently:

* **Meta Cloud API** signs every request: ``X-Hub-Signature-256`` is an
  HMAC-SHA256 of the exact bytes of the body, keyed with the app secret. This
  is real proof — nobody can forge it without the secret.

* **WaPilot v2** publishes no signing secret, so the proof is a long random
  token in the URL path that only the clinic and WaPilot know. Weaker (a URL
  ends up in logs and proxies) but it is what the provider offers, and it is
  still the difference between "anyone" and "whoever holds the token".

Both fail **closed**. An endpoint that accepts anything when it hasn't been
configured is not a webhook, it is an open write port onto medical records.
"""
import hashlib
import hmac

# A path token short enough to guess is not a secret. The generated ones are
# ``secrets.token_urlsafe(24)`` — 32 characters — so this only ever catches a
# hand-typed value somebody thought was good enough.
MIN_PATH_SECRET = 20


def meta_signature_ok(raw_body, header_value, app_secret):
    """Whether ``X-Hub-Signature-256`` proves Meta sent these exact bytes.

    ``raw_body`` must be the untouched request body: re-serialising the parsed
    JSON changes the bytes (key order, spacing) and the signature stops
    matching for reasons that look like a Meta outage.
    """
    if not app_secret or not header_value or raw_body is None:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body if isinstance(raw_body, bytes) else str(raw_body).encode(),
        hashlib.sha256,
    ).hexdigest()
    # compare_digest, never ==. A plain comparison returns faster the earlier
    # it finds a mismatched byte, and that timing is enough to recover a valid
    # signature one character at a time.
    return hmac.compare_digest(expected, header_value.strip())


def path_secret_ok(given, configured):
    """Whether the token in a WaPilot webhook URL matches the configured one.

    Refuses when nothing is configured (fail closed) and when the configured
    value is too short to be a secret at all.
    """
    if not configured or not given:
        return False
    if len(configured) < MIN_PATH_SECRET:
        return False
    return hmac.compare_digest(str(configured), str(given))


def verify_token_ok(given, configured):
    """The Meta ``hub.verify_token`` handshake — same rules, same comparison."""
    if not configured or not given:
        return False
    return hmac.compare_digest(str(configured), str(given))
