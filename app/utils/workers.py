"""More than one server process — for a hospital; a clinic keeps one.

The hospital load test (``docs/LOAD_TEST.md``) found the limit was not the
database and not any one screen: it was that the whole program is **one
Python process**, and one Python process runs Python on one core at a time
however many threads it has. The day board for twelve doctors took its turn
on that one core, and every other screen in the building waited behind it
while three cores sat idle.

``WORKERS=4`` in ``clinic.env`` runs four. The first process opens the port
and hands it to the workers; each is the ordinary program, and the operating
system gives each new connection to whichever is free. SQLite was built for
several processes sharing one file, and the program already writes as if it
had neighbours (``sequences.claim``, ``hold_the_diary``).

**Unset, or 1, changes nothing.** ``run.py`` serves exactly as it always did,
without importing this module — an update must not change how a running
clinic runs.

What one process used to keep to itself, and now has to share or hand over:

* **the login limit** — counted by this first process for all of them, over
  a private pipe (``rate_limit.share``); four separate counts would have let
  a password guesser four times as many tries;
* **the nightly backup** — taken by whichever worker claims it first
  (``backups._claim``); four would each have copied every photo at once;
* **the WhatsApp queue** — sent by whoever claims the turn in the database
  (``Setting.swap``);
* **closing for an update** — the updater waits for *this* process, and this
  process closes the workers before it goes (``ask_everyone_to_close``).

And the workers watch this process: if it is closed from Task Manager, they
go too, rather than living on holding the port and the files an update is
about to replace.
"""
import os
import socket
import sys
import threading
import time

ENV = "WORKERS"
MOST = 16
MASTER_PID = "PEDIAPRO_MASTER_PID"

# In a worker: the first process's "everybody close" signal. ``None`` in a
# single-process program, which is how the rest of the code tells.
_stop = None


def chosen(environ=None):
    """How many processes ``clinic.env`` asks for: 1 unless it says a whole
    number from 2 to 16. Anything else is 1 — a typo must not stop a clinic
    starting, and one is how it always ran."""
    environ = os.environ if environ is None else environ
    try:
        count = int(str(environ.get(ENV) or "1").strip())
    except ValueError:
        return 1
    return count if 1 <= count <= MOST else 1


def master_pid():
    """The process an updater has to wait for: the first one, when there
    are workers; this one, when there are not."""
    try:
        return int(os.environ.get(MASTER_PID) or 0) or os.getpid()
    except ValueError:
        return os.getpid()


def ask_everyone_to_close():
    """From a worker: ask the first process to close them all, itself last.
    Returns False in a single-process program, where there is nobody to ask."""
    if _stop is None:
        return False
    _stop.set()
    return True


def _watch(lifeline):
    """Go when the first process goes. Nothing is ever sent down this pipe;
    it only breaks, and it breaks when the other end is gone."""
    try:
        lifeline.recv()
    except (EOFError, OSError):
        pass
    os._exit(0)


class _AskTheFirst:
    """The login limit, asked of the first process — one connection per
    serving thread, made when that thread first needs it."""

    def __init__(self, address, authkey):
        self.address, self.authkey = address, authkey
        self.mine = threading.local()

    def __call__(self, slot, limit, per_seconds, now):
        from multiprocessing.connection import Client

        conn = getattr(self.mine, "conn", None)
        try:
            if conn is None:
                conn = self.mine.conn = Client(self.address,
                                               authkey=self.authkey)
            conn.send((slot, limit, per_seconds, now))
            return conn.recv()
        except Exception as exc:                    # noqa: BLE001
            self.mine.conn = None
            raise OSError(str(exc)) from exc


def _count_for_everyone(listener):
    """In the first process: one login count for every worker. A thread of
    this process, not a process of its own, so it cannot outlive it."""
    from app.utils.rate_limit import _count

    hits, lock = {}, threading.Lock()

    def answer(conn):
        with conn:
            while True:
                try:
                    slot, limit, per_seconds, now = conn.recv()
                except (EOFError, OSError):
                    return
                conn.send(_count(hits, lock, slot, limit, per_seconds, now))

    while True:
        try:
            conn = listener.accept()
        except Exception:                           # noqa: BLE001
            if getattr(listener, "_listener", None) is None:
                return                              # closed: shutting down
            continue
        threading.Thread(target=answer, args=(conn,), daemon=True).start()


def _work(sock, stop, lifeline, counter, threads, config, options):
    """One worker: the ordinary program, serving the shared port."""
    global _stop
    _stop = stop
    threading.Thread(target=_watch, args=(lifeline,), daemon=True,
                     name="lifeline").start()

    from app.utils import rate_limit

    rate_limit.share(_AskTheFirst(*counter))

    # ``run.py`` builds the app when it is imported, and a worker imports it
    # to start; use that one rather than building a second.
    application = getattr(sys.modules.get("__mp_main__"), "app", None)
    if application is None:
        from app import create_app

        application = create_app(config)

    from waitress import serve

    serve(application, sockets=[sock], threads=threads, **options)


def serve_many(port, workers, threads=8, host="0.0.0.0", config="production",
               options=None, say=print):
    """Open the port, start ``workers`` processes on it, and look after them
    until asked to stop: one that dies is started again; one that dies as it
    starts, three times running, stops the lot with the reason."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")      # the same on every system
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((host, port))
    listener.listen(1024)
    os.environ[MASTER_PID] = str(os.getpid())

    from multiprocessing.connection import Listener

    authkey = os.urandom(32)
    counting = Listener(authkey=authkey)        # a named pipe on Windows
    threading.Thread(target=_count_for_everyone, args=(counting,),
                     daemon=True, name="login-count").start()
    counter = (counting.address, authkey)
    stop = ctx.Event()
    stopping = []
    running = {}                                    # slot -> (process, pipe, started)
    quick_deaths = {}

    def start(slot):
        mine, theirs = ctx.Pipe()
        process = ctx.Process(
            target=_work, name=f"PediaPro-{slot + 1}", daemon=True,
            args=(listener, stop, theirs, counter, threads, config,
                  dict(options or {})))
        process.start()
        theirs.close()
        running[slot] = (process, mine, time.monotonic())

    # Asked to stop (a service manager, the load test): close them all
    # properly, rather than dying first and leaving the workers to notice.
    try:
        import signal

        # Only a flag: the handler runs in the middle of whatever this
        # process was doing, which may be holding the event's own lock.
        signal.signal(signal.SIGTERM, lambda *_args: stopping.append(1))
    except (ValueError, AttributeError, OSError):   # not the main thread
        pass

    for slot in range(workers):
        start(slot)
    say(f" * {workers} server processes on one port")

    code = 0
    try:
        while not stopping and not stop.is_set():
            time.sleep(1.0)
            for slot, (process, pipe, started) in list(running.items()):
                if process.is_alive():
                    continue
                pipe.close()
                if time.monotonic() - started < 5:
                    quick_deaths[slot] = quick_deaths.get(slot, 0) + 1
                else:
                    quick_deaths[slot] = 0
                if quick_deaths[slot] >= 3:
                    say(f"[!] server process {slot + 1} stops as soon as it "
                        f"starts (exit code {process.exitcode}) - closing.")
                    code = 1
                    stop.set()
                    break
                say(f" * server process {slot + 1} stopped "
                    f"(exit code {process.exitcode}) - starting it again")
                start(slot)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for process, _pipe, _started in running.values():
            process.terminate()
        for process, pipe, _started in running.values():
            process.join(10)
            pipe.close()
        counting.close()
        listener.close()
    return code
