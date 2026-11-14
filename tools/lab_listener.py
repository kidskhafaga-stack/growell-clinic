"""The laboratory's middleware: speaks to an analyser in its own protocol and
posts each finished message to the program (LAB_GLAB360_PLAN.md م-٢ ب).

Runs on a computer in the laboratory, beside the analyser — the program may
be on a server elsewhere. Python's standard library only (a serial cable
needs ``pyserial``).

    python tools/lab_listener.py --protocol hl7  --port 5000 \
        --url https://clinic-server/lab-intake/3 --key pplab_…
    python tools/lab_listener.py --protocol astm --port 5001 --url … --key …
    python tools/lab_listener.py --protocol astm --serial COM3 --baud 9600 --url … --key …

* **HL7 v2 over MLLP** (TCP): each message ``<VT>…<FS><CR>`` is posted, and
  the analyser gets its ACK — ``AA`` once the program has it, ``AE`` if not.
* **ASTM E1381** (TCP, or serial): ``<ENQ>`` is answered ``<ACK>``; each
  frame's checksum is checked — ``<ACK>`` if right, ``<NAK>`` so the analyser
  sends it again if not; ``<EOT>`` ends the message, which is then posted.
* **Nothing is lost**: a message the program does not take (the network is
  down, the server restarting) is written to the spool folder and posted
  again every minute until it is taken.
* **Every minute** it tells the program it is running, and whether the
  analyser has spoken in the last five minutes — the «devices» screen shows it.
* TLS is verified as always; a clinic with its own certificate authority
  passes it with ``--ca``.
"""
import argparse
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

STX, ETX, ETB, EOT, ENQ, ACK, NAK = b"\x02", b"\x03", b"\x17", b"\x04", b"\x05", b"\x06", b"\x15"
VT, FS, CR = b"\x0b", b"\x1c", b"\r"
ALIVE_SECONDS = 60
LINKED_SECONDS = 300


# ------------------------------------------------------------ protocol ---
def checksum(body):
    """E1381: the sum of the bytes from the frame number to ETX/ETB, mod 256,
    as two upper-case hex digits."""
    return f"{sum(body) % 256:02X}".encode("ascii")


def frame_ok(frame):
    """Whether one ``<STX>…<ETX|ETB>cc<CR><LF>`` frame's checksum is right."""
    if not frame.startswith(STX):
        return False
    end = max(frame.rfind(ETX), frame.rfind(ETB))
    if end < 0 or len(frame) < end + 3:
        return False
    return checksum(frame[1:end + 1]) == frame[end + 1:end + 3].upper()


class AstmSession:
    """One E1381 conversation, fed byte chunks; returns what to answer and,
    when ``<EOT>`` comes, the whole message (its frames as received)."""

    def __init__(self):
        self.frames = []
        self.buf = b""
        self.open = False

    def feed(self, data):
        replies, messages = [], []
        self.buf += data
        while self.buf:
            if not self.open:
                i = self.buf.find(ENQ)
                if i < 0:
                    self.buf = b""
                    break
                self.buf = self.buf[i + 1:]
                self.open, self.frames = True, []
                replies.append(ACK)
                continue
            if self.buf[:1] == EOT:
                self.buf = self.buf[1:]
                self.open = False
                if self.frames:
                    messages.append(b"".join(self.frames))
                self.frames = []
                continue
            if self.buf[:1] != STX:
                # Noise between frames.
                nxt = min([p for p in (self.buf.find(STX), self.buf.find(EOT)) if p >= 0] or [-1])
                if nxt < 0:
                    self.buf = b""
                    break
                self.buf = self.buf[nxt:]
                continue
            end = self.buf.find(b"\n")
            if end < 0:
                break                           # the rest of the frame is coming
            frame, self.buf = self.buf[:end + 1], self.buf[end + 1:]
            if frame_ok(frame):
                self.frames.append(frame)
                replies.append(ACK)
            else:
                replies.append(NAK)             # the analyser sends it again
        return replies, messages


def mllp_messages(buf):
    """``(messages, rest)`` — the whole ``<VT>…<FS><CR>`` messages in a buffer."""
    out = []
    while True:
        start = buf.find(VT)
        end = buf.find(FS + CR, start + 1 if start >= 0 else 0)
        if start < 0 or end < 0:
            return out, buf
        out.append(buf[start + 1:end])
        buf = buf[end + 2:]


def hl7_ack(message, ok=True, text=""):
    """The MLLP-wrapped ACK the analyser waits for."""
    raw = message.decode("utf-8", "replace").replace("\n", "\r")
    msh = next((s for s in raw.split("\r") if s.startswith("MSH")), "MSH|^~\\&")
    sep = msh[3] if len(msh) > 3 else "|"
    f = msh.split(sep)

    def g(i):
        return f[i] if len(f) > i else ""

    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    head = sep.join(["MSH", g(1) or "^~\\&", g(4), g(5), g(2), g(3), stamp, "", "ACK",
                     g(9), "P", g(11) or "2.5"])
    msa = sep.join(["MSA", "AA" if ok else "AE", g(9), text[:80]])
    return VT + f"{head}\r{msa}\r".encode("utf-8") + FS + CR


# -------------------------------------------------------- to the program ---
class Program:
    """Posts messages and the heartbeat; spools what could not be posted."""

    def __init__(self, url, key, spool, ca=None, timeout=20):
        self.url = url.rstrip("/")
        self.key = key
        self.spool = spool
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
        self.last_heard = 0.0
        os.makedirs(spool, exist_ok=True)

    def _post(self, path, body, kind):
        req = urllib.request.Request(f"{self.url}/{path}", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.key}",
                                              "Content-Type": kind})
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.context) as resp:
            return resp.status, resp.read()

    def send(self, message):
        """True when the program took it; otherwise it is spooled."""
        self.last_heard = time.time()
        try:
            status, _ = self._post("message", message, "application/octet-stream")
            if status == 200:
                return True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"post failed, spooled: {exc}", file=sys.stderr)
        name = os.path.join(self.spool, f"{time.time():.6f}.msg")
        with open(name, "wb") as fh:
            fh.write(message)
        return False

    def resend_spool(self):
        for name in sorted(os.listdir(self.spool)):
            path = os.path.join(self.spool, name)
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                status, _ = self._post("message", data, "application/octet-stream")
            except (urllib.error.URLError, OSError, ValueError):
                return                          # still down; next minute
            if status == 200:
                os.remove(path)

    def alive(self):
        linked = (time.time() - self.last_heard) < LINKED_SECONDS
        try:
            self._post("alive", json.dumps({"linked": linked}).encode(), "application/json")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"heartbeat failed: {exc}", file=sys.stderr)


def heartbeat(program):
    while True:
        program.alive()
        program.resend_spool()
        time.sleep(ALIVE_SECONDS)


# ------------------------------------------------------------ transport ---
def serve_tcp(port, protocol, program, host="0.0.0.0"):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"listening for {protocol} on {host}:{port}")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle, args=(conn, protocol, program), daemon=True).start()


def _handle(conn, protocol, program):
    with conn:
        session, buf = AstmSession(), b""
        while True:
            data = conn.recv(65536)
            if not data:
                return
            program.last_heard = time.time()
            if protocol == "hl7":
                messages, buf = mllp_messages(buf + data)
                for message in messages:
                    conn.sendall(hl7_ack(message, ok=program.send(message)))
            else:
                replies, messages = session.feed(data)
                for reply in replies:
                    conn.sendall(reply)
                for message in messages:
                    program.send(message)


def serve_serial(device, baud, program):
    import serial  # pyserial — only for a serial cable

    port = serial.Serial(device, baud, timeout=1)
    session = AstmSession()
    print(f"listening for astm on {device} at {baud}")
    while True:
        data = port.read(4096)
        if not data:
            continue
        program.last_heard = time.time()
        replies, messages = session.feed(data)
        for reply in replies:
            port.write(reply)
        for message in messages:
            program.send(message)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--protocol", choices=("astm", "hl7"), required=True)
    p.add_argument("--port", type=int, help="TCP port to listen on")
    p.add_argument("--serial", help="serial device (ASTM), e.g. COM3 or /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--url", required=True, help="the device's intake address")
    p.add_argument("--key", default=os.environ.get("PEDIAPRO_LAB_KEY"),
                   help="the device's key (or PEDIAPRO_LAB_KEY)")
    p.add_argument("--spool", default="lab_spool")
    p.add_argument("--ca", help="the clinic's own certificate authority, if it has one")
    args = p.parse_args(argv)
    if not args.key:
        p.error("--key (or PEDIAPRO_LAB_KEY) is required")
    program = Program(args.url, args.key, args.spool, ca=args.ca)
    threading.Thread(target=heartbeat, args=(program,), daemon=True).start()
    if args.serial:
        if args.protocol != "astm":
            p.error("a serial cable carries ASTM")
        serve_serial(args.serial, args.baud, program)
    elif args.port:
        serve_tcp(args.port, args.protocol, program)
    else:
        p.error("--port or --serial")


if __name__ == "__main__":
    main()
