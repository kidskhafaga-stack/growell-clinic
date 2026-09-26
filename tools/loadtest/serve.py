"""The server the load test talks to — the clinic's own, on the copy.

    python -m tools.loadtest.serve <db> <port> <threads> [workers]

The production configuration and waitress, exactly as ``run.py`` serves a
clinic, so what is measured is what a clinic runs. Only three things differ,
both passed in by the driver: which file (always a stamped copy) and, when
the test is measuring them, the waitress thread count and SQLite's busy
timeout (``SQLITE_BUSY_TIMEOUT_MS``); and this server believes the address
each simulated person sends (see below).
"""
import os
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path, port, threads = argv[0], int(argv[1]), int(argv[2])
    workers = int(argv[3]) if len(argv) > 3 else 1
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.abspath(path)
    # Each simulated member of staff sends their own address, and only this
    # test server believes it — so the login limit and the audit log see
    # sixteen machines, as a clinic's would, rather than one. The clinic's
    # own server (``run.py``) trusts no proxy, and waitress there drops the
    # header entirely.
    options = dict(ident="loadtest", _quiet=True, trusted_proxy="127.0.0.1",
                   trusted_proxy_headers={"x-forwarded-for"},
                   clear_untrusted_proxy_headers=True)
    if workers > 1:
        # As ``run.py`` serves with ``WORKERS`` set in clinic.env.
        from app.utils.workers import serve_many

        sys.exit(serve_many(port, workers, threads=threads, host="127.0.0.1",
                            config="production", options=options,
                            say=lambda _line: None))
    from waitress import serve

    from app import create_app

    app = create_app("production")
    serve(app, host="127.0.0.1", port=port, threads=threads, **options)


if __name__ == "__main__":
    main()
