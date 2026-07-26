"""Entry point for GROWELL CLINIC.

Usage:
    python run.py                 (reads the port from clinic.env / PORT)
    python run.py 8080            (or say it here, just this once)
    flask --app run <command>     (the CLI commands — see COMMANDS.md)

The port lives in ``clinic.env`` next to this file so a clinic can change it
without editing a script. Port 5000 collides often — macOS AirPlay holds it,
and so do a few Windows tools — and that is precisely the moment when a stack
trace is the least useful thing to print.

**This runs the clinic, not a demo.** It therefore defaults to the production
configuration and serves with waitress. The debug configuration is a
deliberate choice a developer makes (``FLASK_CONFIG=development``), never
something a clinic ends up in by leaving a default alone — Flask's debugger
puts a Python console on any error page, and this server listens on the whole
network.
"""
import os
import socket
import sys

from app import create_app
from app.settings_file import ensure_secret, load_env

# Read clinic.env before the app is built: it may carry DATABASE_URL and the
# language default as well as the port.
load_env()
# …and make sure this clinic has its own session key before anything signs a
# cookie with the one printed in the source.
ensure_secret()

# "production" unless somebody explicitly asks for the debugger.
app = create_app(os.environ.get("FLASK_CONFIG", "production"))

DEFAULT_PORT = 5000


def chosen_port(argv=None, environ=None):
    """The port to serve on: the command line first, then clinic.env / PORT."""
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    for value in ((argv[0] if argv else None), environ.get("PORT")):
        try:
            port = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535:
            return port
    return DEFAULT_PORT


def port_is_free(port, host="0.0.0.0"):
    """Whether we can actually bind it — asked before serving, not after."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def serve(application, port, host="0.0.0.0"):
    """Serve with waitress when it is installed, Flask's server otherwise.

    Werkzeug's server says so itself on every start: it is not meant for
    production. Waitress is one pure-Python dependency, runs on Windows, and
    is what a clinic PC should actually be answering on.
    """
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        print("    (waitress not installed — using the development server;\n"
              "     run:  pip install -r requirements.txt)")
        application.run(host=host, port=port)
        return
    waitress_serve(application, host=host, port=port, threads=8,
                   ident="GROWELL CLINIC")


if __name__ == "__main__":
    port = chosen_port()
    # The debug reloader runs this file again in a child process while the
    # parent still holds the socket. Checking there would have the clinic
    # refuse to start with "that port is busy" — describing itself.
    reloading = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if not reloading and not port_is_free(port):
        print(f"\n[!] Port {port} is already in use / المنفذ {port} مشغول.\n\n"
              f"    Either the clinic is already running — open "
              f"http://localhost:{port}\n"
              f"    or another program is holding that port.\n\n"
              f"    To use another one:  python run.py 8080\n"
              f"    or set  PORT=8080  in clinic.env next to this file.\n")
        sys.exit(1)
    if not reloading:
        print(f" * GROWELL CLINIC  ->  http://localhost:{port}")
    if app.debug:
        app.run(host="0.0.0.0", port=port)      # the developer asked for it
    else:
        serve(app, port)
