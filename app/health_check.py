"""Ask the running clinic whether it is answering. Exit 0 if it is.

Run by ``watchdog.bat`` as ``python -m app.health_check``. Kept in Python
rather than written as a batch one-liner because Server 2012 R2 has no
``curl.exe`` — that arrived with Windows 10 1803 — and PowerShell's
``Invoke-WebRequest`` on the shipped PowerShell 4.0 needs Internet Explorer's
first-run settings before it will fetch anything, which on a fresh server
means it fails for a reason that has nothing to do with the clinic.

Deliberately its own process with its own timeout. Importing the app to check
the app would hang in exactly the case this exists to detect.
"""
import json
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 20


def check(port=None, timeout=TIMEOUT_SECONDS):
    """``(ok, message)`` — whether the clinic answered its health route.

    The timeout is generous on purpose. A clinic PC mid-backup, or one that
    has just come up after a power cut, is slow rather than broken, and a
    watchdog that calls that "dead" turns a slow morning into a restart loop.
    """
    from app.settings_file import load_env

    load_env()
    if port is None:
        from run import chosen_port

        port = chosen_port([])

    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as reply:
            body = json.loads(reply.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except Exception as exc:  # noqa: BLE001 — refused, timed out, anything
        return False, f"{type(exc).__name__}: {exc}"

    if body.get("status") != "ok":
        return False, f"unhealthy: {body}"
    return True, f"ok (version {body.get('version')})"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = None
    if argv:
        try:
            port = int(argv[0])
        except ValueError:
            port = None
    ok, message = check(port)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
