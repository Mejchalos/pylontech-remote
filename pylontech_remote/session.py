"""Console session: the only code that writes to the battery's console port.

- every command passes allowlist.check() first;
- the port is opened exclusively (TIOCEXCL) with DTR/RTS low before open (no pulse);
- a reply ends at the prompt (e.g. "pylon_debug>") at the end of the buffer, with idle and total
  timeouts as fallbacks;
- paging prompts are answered with Enter ("other key" would abort the output);
- a minimum pause is kept between the end of one reply and the next command.
"""
import os
import re
import time

from . import allowlist

# The prompt at the very end of the buffer. Normally on its own line; after a reply the master
# cut short (a slave's answer not fully relayed) it follows the truncated text directly.
PROMPT_RE = re.compile(rb'((^|[\r\n])[A-Za-z_]+|pylon[A-Za-z_]*)>\s*$')
PAGING = b'press [enter]'
ENTER = b'\r'


class ConsoleError(Exception):
    pass


class RawReply(object):
    __slots__ = ('command', 'sent_utc', 'duration_s', 'data', 'end_reason', 'pages', 'stale')

    def __init__(self, command, sent_utc, duration_s, data, end_reason, pages, stale):
        self.command = command
        self.sent_utc = sent_utc
        self.duration_s = duration_s
        self.data = data
        self.end_reason = end_reason
        self.pages = pages
        self.stale = stale

    @property
    def text(self):
        return self.data.decode('ascii', errors='replace')

    @property
    def ok(self):
        return self.end_reason == 'prompt'


def port_holders(port):
    """PIDs (other than ours) that have `port` open. Best effort: /proc entries of other users
    are unreadable without root, so an empty result is not a guarantee."""
    try:
        target = os.path.realpath(port)
        pids = [p for p in os.listdir('/proc') if p.isdigit()]
    except OSError:
        return []
    found = []
    for pid in pids:
        if int(pid) == os.getpid():
            continue
        fd_dir = '/proc/%s/fd' % pid
        try:
            for fd in os.listdir(fd_dir):
                if os.path.realpath(os.path.join(fd_dir, fd)) == target:
                    found.append(int(pid))
                    break
        except OSError:
            continue
    return found


def default_port():
    """$PYLONTECH_PORT, else /dev/ttyPYLON (the installer's fixed name; always when installed, so
    that another adapter is never used by mistake), else /dev/ttyUSB0."""
    if os.environ.get('PYLONTECH_PORT'):
        return os.environ['PYLONTECH_PORT']
    if os.path.exists('/dev/ttyPYLON') or os.path.isdir('/data/pylontech'):
        return '/dev/ttyPYLON'
    return '/dev/ttyUSB0'


def missing_port_message(port):
    """For the dashboard when the port does not exist, else None."""
    if os.path.exists(port):
        return None
    if port == '/dev/ttyPYLON':
        return ('battery console cable not connected (no /dev/ttyPYLON) - plug it in; it is found '
                'automatically within a few minutes')
    return 'port %s does not exist' % port


def open_serial(port, baud):
    import serial
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.bytesize = serial.EIGHTBITS
    s.parity = serial.PARITY_NONE
    s.stopbits = serial.STOPBITS_ONE
    s.timeout = 0.1
    s.xonxoff = False
    s.rtscts = False
    s.dsrdtr = False
    s.exclusive = True
    s.dtr = False   # before open(): the lines never pulse high
    s.rts = False
    s.open()
    return s


class ConsoleSession(object):
    def __init__(self, port='/dev/ttyUSB0', baud=115200, gap=1.2, idle=3.0, total=30.0,
                 serial_factory=None, clock=time.monotonic, sleep=time.sleep):
        self.port = port
        self.baud = baud
        self.gap = gap
        self.idle = idle
        self.total = total
        self._factory = serial_factory or open_serial
        self._clock = clock
        self._sleep = sleep
        self._ser = None
        self._last_end = None
        self.greeting = None      # the reply to Enter when the session was opened

    # -- lifecycle -------------------------------------------------------------------------
    def open(self, check_holders=True, settle=1.0):
        if check_holders:
            holders = port_holders(self.port)
            if holders:
                raise ConsoleError('port %s is held by pid %s' % (self.port, holders))
        self._ser = self._factory(self.port, self.baud)
        self._sleep(settle)
        self.greeting = self.resync()
        return self

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- commands --------------------------------------------------------------------------
    def resync(self):
        """Send Enter until a bare prompt comes back. A paging prompt left over from someone
        else's session is paged through (Enter is the safe key there)."""
        for _ in range(3):
            reply = self.command('', idle=1.0, total=10.0, page=True)
            if reply.ok:
                return reply
        raise ConsoleError('no prompt from the console')

    def command(self, command, idle=None, total=None, page=True):
        allowlist.check(command)
        if self._ser is None:
            raise ConsoleError('session is not open')
        self._wait_gap()
        stale = b''
        waiting = self._ser.in_waiting
        if waiting:
            stale = self._ser.read(waiting)
        sent_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        t0 = self._clock()
        self._ser.write(command.encode('ascii') + b'\n')
        data, reason, pages = self._read_reply(idle or self.idle, total or self.total, page)
        t1 = self._clock()
        self._last_end = t1
        return RawReply(command, sent_utc, round(t1 - t0, 3), data, reason, pages, stale)

    def drain(self, quiet=1.0, limit=15.0):
        """Read and discard until the line has been silent for `quiet` seconds (rest of an
        interrupted reply). Returns the discarded bytes."""
        if self._ser is None:
            return b''
        buf = b''
        t0 = last = self._clock()
        while True:
            chunk = self._ser.read(4096)
            now = self._clock()
            if chunk:
                buf += chunk
                last = now
            elif now - last >= quiet or now - t0 >= limit:
                return buf

    def _wait_gap(self):
        if self._last_end is None:
            return
        rest = self.gap - (self._clock() - self._last_end)
        if rest > 0:
            self._sleep(rest)

    def _read_reply(self, idle, total, page):
        buf = b''
        t0 = self._clock()
        last = t0
        pages = 0
        answered_at = 0
        while True:
            chunk = self._ser.read(4096)
            now = self._clock()
            if chunk:
                buf += chunk
                last = now
                if PROMPT_RE.search(buf):
                    return buf, 'prompt', pages
                if page and PAGING in buf[answered_at:].lower():
                    self._ser.write(ENTER)
                    pages += 1
                    answered_at = len(buf)
            if now - last >= idle:
                return buf, 'idle', pages
            if now - t0 >= total:
                return buf, 'total_timeout', pages
