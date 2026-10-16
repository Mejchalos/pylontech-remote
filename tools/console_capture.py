#!/usr/bin/env python3
"""
Capture raw Pylontech console replies, verbatim, for diagnostics.

Sends one or more READ-ONLY commands and stores each reply byte-for-byte
(<outdir>/<stamp>_<command>.raw) plus metadata (.json: timing, byte count,
how the read ended). Nothing is parsed or altered.

Safety:
  * Only commands matching ALLOWED are ever written to the port.
  * The port is opened exclusively (TIOCEXCL) with DTR/RTS low before open.
  * Paging prompts are NOT answered unless --page-key is given; the reply
    simply ends on the idle timeout and the paging text stays in the capture.

Usage (on the Cerbo):
  python3 console_capture.py --outdir /data/pylontech-captures help
  python3 console_capture.py --outdir DIR "stat 1" "info 1"
"""
import argparse
import json
import os
import re
import sys
import time

import serial

# Read-only commands. Extend only after checking `help` and getting approval.
ALLOWED = [
    r'help( [a-z]+)?',
    r'pwr( [1-9][0-9]?)?',
    r'config',
    r'info( [1-9])?',
    r'bat [1-9]',
    r'stat( [1-9])?',
    r'data (event|history) [0-9]{1,4}( [1-9])?',
    r'data [1-9] (event|history) [0-9]{1,4}',
    r'log',
    r'datalist( (event|history))?( (item|bat))?( [0-9]{1,4})?( (volt|curr|temp|coul))?( [0-9]{1,4})?',
    r'datalist [1-9] (event|history) [0-9]{1,4}',
]

# A line that is only a prompt word followed by '>' (e.g. "pylon>",
# "pylon_debug>"), at the very end of the buffer.
PROMPT_RE = re.compile(rb'(^|[\r\n])[A-Za-z_]+>\s*$')

PAGE_KEYS = {'enter': b'\r', 'space': b' '}


def allowed(command):
    return any(re.fullmatch(p, command) for p in ALLOWED)


def open_port(port, baud):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.bytesize = serial.EIGHTBITS
    s.parity = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.timeout = 0.2
    s.xonxoff = False
    s.rtscts = False
    s.dsrdtr = False
    s.exclusive = True
    s.dtr = False   # set before open() so the lines never pulse high
    s.rts = False
    s.open()
    time.sleep(1.0)
    return s


def read_reply(s, idle, total, page_key=None, max_pages=None):
    """Read until a prompt ends the buffer, `idle` s of silence, or `total` s.
    Returns (bytes, end_reason, n_page_answers)."""
    buf = b''
    t0 = time.time()
    last = t0
    pages = 0
    answered_at = 0
    while True:
        chunk = s.read(4096)
        now = time.time()
        if chunk:
            buf += chunk
            last = now
            if PROMPT_RE.search(buf):
                return buf, 'prompt', pages
            if page_key and (max_pages is None or pages < max_pages):
                low = buf[answered_at:].lower()
                if b'[enter]' in low or b'--more--' in low or b'continued' in low:
                    s.write(PAGE_KEYS[page_key])
                    pages += 1
                    answered_at = len(buf)
        if now - last >= idle:
            return buf, 'idle', pages
        if now - t0 >= total:
            return buf, 'total_timeout', pages


def safe_name(command):
    return re.sub(r'[^A-Za-z0-9]+', '_', command).strip('_')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('commands', nargs='+')
    ap.add_argument('--port', default=os.environ.get('PYLONTECH_PORT', '/dev/ttyUSB0'))
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--gap', type=float, default=2.0, help='pause between commands (s)')
    ap.add_argument('--idle', type=float, default=3.0, help='end reply after this much silence (s)')
    ap.add_argument('--total', type=float, default=60.0, help='hard limit per reply (s)')
    ap.add_argument('--page-key', choices=sorted(PAGE_KEYS), default=None)
    ap.add_argument('--max-pages', type=int, default=None, help='stop answering paging prompts after N')
    a = ap.parse_args()

    bad = [c for c in a.commands if not allowed(c)]
    if bad:
        sys.exit('refused (not in ALLOWED): %r' % bad)

    os.makedirs(a.outdir, exist_ok=True)
    s = open_port(a.port, a.baud)
    try:
        # Wake the console and sync to a prompt; keep this reply too.
        jobs = [('', 'wake')] + [(c, safe_name(c)) for c in a.commands]
        for i, (command, name) in enumerate(jobs):
            if i:
                time.sleep(a.gap)
            stale = s.read(s.in_waiting or 1) if s.in_waiting else b''
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            t_send = time.time()
            s.write(command.encode('ascii') + b'\n')
            data, reason, pages = read_reply(s, a.idle, a.total, a.page_key, a.max_pages)
            t_end = time.time()
            base = os.path.join(a.outdir, '%s_%s' % (stamp, name))
            with open(base + '.raw', 'wb') as f:
                f.write(data)
            meta = {
                'command': command,
                'sent_utc': stamp,
                'duration_s': round(t_end - t_send, 3),
                'bytes': len(data),
                'end_reason': reason,
                'page_answers': pages,
                'stale_bytes_before_send': len(stale),
                'port': a.port,
            }
            with open(base + '.json', 'w') as f:
                json.dump(meta, f, indent=1)
            print(json.dumps(meta))
            sys.stdout.flush()
    finally:
        s.close()


if __name__ == '__main__':
    main()
