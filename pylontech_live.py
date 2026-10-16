#!/usr/bin/env python3
"""Stream live Pylontech data as JSON lines (one snapshot per line on stdout).

Holds the console port for as long as it runs. Each cycle reads the stack summary (`pwr`) and
the cells of every module (`bat N`); while start-up data is pending (`config`, `info N`,
`stat N`, and `stat N` again every 10 min) one of those as well. Then it emits one snapshot, so
everything on the dashboard changes at once. A cycle starts every --interval seconds, or as soon
as the previous one is done if that takes longer. At least --gap seconds pass between commands.

Each line has the shape of the original project's reader output (dashboard compatible).
Stops on SIGTERM/SIGINT, when stdout goes away, or after --max-minutes.

  python3 pylontech_live.py                 # live stream
  python3 pylontech_live.py --once          # one full snapshot, then exit
"""
import argparse
import collections
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pylontech_remote import parsers                      # noqa: E402
from pylontech_remote.live import StackState              # noqa: E402
from pylontech_remote.session import ConsoleSession, ConsoleError   # noqa: E402

STATIC_REFRESH_S = 600
MAX_FAILURES = 3

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


def emit(obj):
    try:
        sys.stdout.write(json.dumps(obj, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        raise SystemExit(0)   # the reader of our output (Node-RED) is gone


def error_line(msg):
    return {'ok': False, 'error': msg, 'modules': [], 'live': False}


class StaticStore(object):
    """Model/serial/firmware/statistics/thresholds kept between runs (a small JSON file).
    Written only when the content changed."""

    def __init__(self, path):
        self.path = path
        self._saved = None

    def load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        self._saved = json.dumps(data, sort_keys=True)
        return data

    def save(self, data):
        text = json.dumps(data, sort_keys=True)
        if text == self._saved:
            return False
        tmp = self.path + '.tmp'
        try:
            with open(tmp, 'w') as f:
                f.write(text)
            os.replace(tmp, self.path)     # atomic; also overwrites on Windows (tests)
        except OSError as e:
            sys.stderr.write('cannot save %s: %s\n' % (self.path, e))
            return False
        self._saved = text
        return True


class Runner(object):
    """Per cycle: `pwr`, the cells of every module (`bat N`), then slow-changing data
    (`config`, `info N`, `stat N`); one snapshot at the end of the cycle.

    Slow-changing data missing for a module is read in the same cycle, so the first snapshot is
    already complete. Data known from an earlier run (StaticStore) is shown at once and refreshed
    in the background, one item per cycle."""

    def __init__(self, session, state, interval, store=None):
        self.s = session
        self.state = state
        self.interval = interval
        self.store = store
        self.static = collections.deque()    # background refresh, one per cycle
        self.urgent = collections.deque()    # missing data, read before the next snapshot
        self.known = set()
        self.last_static = None
        self.failures = 0
        if store is not None:
            state.load_static(store.load())

    def run_cmd(self, command):
        reply = self.s.command(command)
        if not reply.ok:
            self.failures += 1
            if self.failures >= MAX_FAILURES:
                self.failures = 0
                self.s.resync()
            return None
        self.failures = 0
        return reply.text

    def do_pwr(self):
        text = self.run_cmd('pwr')
        if text is None:
            return
        rows = self.state.update_pwr(text)
        ids = set(r['id'] for r in rows)
        new = sorted(ids - self.known)
        self.known = ids
        if new:
            (self.static if self.state.thresholds else self.urgent).append(('config', None))
            for n in new:
                queue = self.static if (n in self.state.info and n in self.state.stat) else self.urgent
                queue.extend((('info', n), ('stat', n)))

    def do_task(self, task):
        kind, n = task
        if kind == 'config':
            text = self.run_cmd('config')
            if text is not None:
                self.state.update_config(text)
            return
        if n not in self.known:
            return
        text = self.run_cmd('%s %d' % (kind, n))
        if text is None or parsers.is_absent(text):
            return
        getattr(self.state, 'update_' + kind)(n, text)

    def window(self):
        """pwr + cells of every module, then one snapshot: the dashboard updates all at once."""
        self.do_pwr()
        ids = sorted(self.known)
        for n in ids:
            if _stop:
                return
            self.do_task(('bat', n))
        had_urgent = bool(self.urgent)
        while self.urgent and not _stop:
            self.do_task(self.urgent.popleft())
        emit(self.state.snapshot())
        # background refresh after the snapshot: it shows up in the next cycle
        if self.static and not had_urgent and not _stop:
            self.do_task(self.static.popleft())
            if not self.static:
                self.last_static = time.time()
        elif (not self.static and self.last_static is not None
              and time.time() - self.last_static >= STATIC_REFRESH_S):
            self.last_static = time.time()
            self.static.extend(('stat', n) for n in ids)   # SOH, cycles, alarm counters
        if had_urgent and not self.static and self.last_static is None:
            self.last_static = time.time()
        self.save_static()

    def save_static(self):
        # not in the middle of a background round: one write per round, not one per module
        if self.store is not None and self.state.info and not self.static:
            self.store.save(self.state.static_dict())

    def once(self):
        self.do_pwr()
        for n in sorted(self.known):
            self.do_task(('bat', n))
        while (self.urgent or self.static) and not _stop:
            self.do_task((self.urgent or self.static).popleft())
        self.save_static()
        return self.state.snapshot(live=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default=os.environ.get('PYLONTECH_PORT', '/dev/ttyUSB0'))
    ap.add_argument('--interval', type=float, default=8.0,
                    help='seconds per cycle (pwr + all cells takes ~7.5 s with --gap 1.2)')
    ap.add_argument('--gap', type=float, default=1.2, help='minimum pause between commands (s)')
    ap.add_argument('--max-minutes', type=float, default=35.0)
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--state-file', default=os.environ.get(
        'PYLONTECH_STATE', '/data/pylontech/state/static.json'),
        help="model/serial/firmware/statistics kept between runs ('' = do not keep)")
    a = ap.parse_args()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    session = ConsoleSession(a.port, gap=a.gap)
    try:
        session.open()
    except Exception as e:     # port missing, busy or silent
        emit(error_line('port_open: %s' % e))
        return 2

    state = StackState()
    store = StaticStore(a.state_file) if a.state_file else None
    runner = Runner(session, state, a.interval, store)
    try:
        if a.once:
            emit(runner.once())
            return 0
        deadline = time.time() + a.max_minutes * 60
        while not _stop and time.time() < deadline:
            start = time.time()
            runner.window()
            while not _stop and time.time() - start < a.interval:
                time.sleep(0.1)
        snap = state.snapshot(live=False)
        emit(snap)
        return 0
    except ConsoleError as e:
        emit(error_line('console: %s' % e))
        return 3
    except SystemExit:
        raise
    except Exception as e:
        emit(error_line('%s: %s' % (type(e).__name__, e)))
        return 3
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
