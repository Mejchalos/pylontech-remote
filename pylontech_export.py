#!/usr/bin/env python3
"""Download the battery logs for a warranty claim: one ZIP in BatteryView's file format.

Two modes:
- whole stack (default): every module through the master's console. The master's files are
  verbatim; the other modules' tables are rebuilt from their records (`data N ...`).
- --connected: only the module the cable is plugged into, verbatim like BatteryView
  (`info`, `stat`, `pwr`, `datalist event 0`, `datalist history 0`). Move the cable from module
  to module for a complete set.

Per module `<barcode>_event_<stamp>.txt` and `<barcode>_history_<stamp>.txt`
(see pylontech_remote/export.py), plus README.txt and raw/ with every console reply verbatim.

Progress, the result and errors are printed as JSON lines on stdout:
  {"type": "progress", "step": ..., "module": 2, "kind": "history", "done": 812, "total": 1796,
   "records_done": ..., "records_total": ..., "eta_s": ...}
  {"type": "done", "file": "/data/pylontech/exports/pylontech_logs_….zip", "size": …, …}
  {"type": "error", "error": "…"}

Only allow-listed read commands are sent. Holds the port for the whole run (stop Live first).

  python3 pylontech_export.py [--connected] [--gap 0.2] [--outdir /data/pylontech/exports]
"""
import argparse
import hashlib
import io
import json
import os
import signal
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pylontech_remote import export, parsers                     # noqa: E402
from pylontech_remote.session import ConsoleSession, ConsoleError, default_port  # noqa: E402

RETRIES = 5
CRLF = '\r\n'
_stop = False


class Cancelled(Exception):
    pass


def _on_signal(signum, frame):
    global _stop
    _stop = True


def emit(obj):
    try:
        sys.stdout.write(json.dumps(obj, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        raise SystemExit(0)


class Exporter(object):
    def __init__(self, session, clock=time.time, limit=None):
        self.s = session
        self.clock = clock
        self.limit = limit        # test runs: only the newest `limit` records per slave table
        self.raw = {}             # zip path -> bytes (every reply, verbatim)
        self.files = {}           # zip path -> bytes (BatteryView-format files)
        self.summary = []         # per module, for README / result
        self.retries = 0
        self.failed = []          # (command, attempt, RawReply) of rejected replies
        self.cells = {}           # module -> cell count (from info), to check record replies
        self.records_total = 0
        self.records_done = 0
        self.started = clock()
        self.mode = 'stack'

    # -- console -----------------------------------------------------------------------------
    def unique_barcode(self, barcode, n):
        """Serial for file names; never the same twice (missing or repeated serials)."""
        used = set(m['barcode'] for m in self.summary)
        name = barcode or 'module%d' % n
        return name if name not in used else '%s_M%d' % (name, n)

    def run(self, command, idle=8.0, total=60.0, check=None, expect=None):
        """A valid reply, or ConsoleError after RETRIES attempts.

        Valid = `check(text)` when given, else: the echo of `command`, the normal end, and
        `expect` (a text the reply must contain) — or an explicit "Invalid command" /
        "Target device is not present". When the master cuts a slave's answer short it sends the
        rest with the next reply, so a reply is never trusted on "Command completed" alone.
        Rejected replies are kept in raw/failed/; the line is left to go quiet and the console is
        resynced before the next attempt."""
        for attempt in range(RETRIES):
            if _stop:
                raise Cancelled()
            reply = self.s.command(command, idle=idle, total=total)
            text = reply.text
            if check is not None:
                ok = check(text)
            else:
                ok = parsers.is_reply_to(text, command) and (expect is None or expect in text)
            if ok or parsers.is_refusal(text, command):
                return reply
            self.retries += 1
            self.failed.append((command, attempt, reply))
            sys.stderr.write('rejected reply to %r (attempt %d, %s, %d bytes, stale %d)\n' % (
                command, attempt + 1, reply.end_reason, len(reply.data), len(reply.stale)))
            self.s.drain(quiet=1.5)
            try:
                self.s.resync()
            except ConsoleError as e:
                sys.stderr.write('resync after %r failed: %s\n' % (command, e))
                self.s.drain(quiet=3.0)
        raise ConsoleError('no complete reply to %r after %d attempts' % (command, RETRIES))

    def progress(self, **kw):
        elapsed = self.clock() - self.started
        eta = None
        if self.records_done and self.records_total:
            eta = int(elapsed / self.records_done * (self.records_total - self.records_done))
        kw.update(type='progress', records_done=self.records_done,
                  records_total=self.records_total, elapsed_s=int(elapsed), eta_s=eta)
        emit(kw)

    # -- verbatim, like BatteryView ----------------------------------------------------------
    def master(self, stamp):
        """Returns False when this firmware has no `datalist` (then module 1 is read like a slave)."""
        self.progress(step='master', module=1)
        info = self.run('info', expect='Barcode')
        stat = self.run('stat', expect='CYCLE Times')
        pwr = self.run('pwr', expect='Power Volt')
        return self.verbatim(1, info, stat, pwr, stamp, 'verbatim (datalist on the master)')

    def verbatim(self, n, info, stat, pwr, stamp, source):
        """`datalist event|history 0` of the module whose console this is; False without datalist."""
        self.progress(step='datalist', module=n, kind='event')
        ev = self.run('datalist event 0', idle=10.0, total=120.0)
        self.progress(step='datalist', module=n, kind='history')
        hi = self.run('datalist history 0', idle=10.0, total=600.0)
        complete = parsers.is_complete(ev.text) and parsers.is_complete(hi.text)
        if not complete or parsers.is_invalid(ev.text) or parsers.is_invalid(hi.text):
            return False
        barcode = self.unique_barcode(parsers.parse_info(info.text).get('barcode'), n)
        # BatteryView: event file = info, stat, pwr, datalist event; history = info, stat, datalist history
        self.files[export.file_name(barcode, 'event', stamp)] = (
            info.data + stat.data + pwr.data + export.batteryview_table(ev.data))
        self.files[export.file_name(barcode, 'history', stamp)] = (
            info.data + stat.data + export.batteryview_table(hi.data))
        for r, name in ((info, 'info'), (stat, 'stat'), (pwr, 'pwr'),
                        (ev, 'datalist_event'), (hi, 'datalist_history')):
            self.raw['raw/%s_%s.txt' % (barcode, name)] = r.data
        st = parsers.parse_stat(stat.text)
        self.summary.append({'module': n, 'barcode': barcode,
                             'fw': parsers.parse_info(info.text).get('fw'),
                             'source': source,
                             'event': st.get('event_items'), 'history': st.get('history_items'),
                             'missing': {}})
        return True

    # -- slaves: record by record ---------------------------------------------------------------
    def slave_header(self, n):
        info = self.run('info %d' % n, expect='Barcode')
        stat = self.run('stat %d' % n, expect='CYCLE Times')
        pwr = self.run('pwr %d' % n, expect='System Fault')   # the module's own detail
        st = parsers.parse_stat(stat.text)
        n_cells = parsers.to_int(dict(parsers.parse_kv(info.text)).get('Cell Number'))
        self.cells[n] = n_cells
        return info, stat, pwr, st

    def read_records(self, n, kind, count, known=None):
        """Read `data n kind i` from the newest record down to 0. When the battery drops its oldest
        block meanwhile, indexes shift: reading downwards only re-reads a few (deduplicated).
        With `known` (records already read) it stops at the first record it already has."""
        records = {}
        raw = io.BytesIO()
        missing = []
        lowest = max(0, count - self.limit) if self.limit else 0
        for i in range(count - 1, lowest - 1, -1):
            try:
                reply = self.run('data %d %s %d' % (n, kind, i),
                                 check=lambda t, i=i: parsers.is_record_reply(t, i, self.cells.get(n)))
            except ConsoleError:
                missing.append(i)
                continue
            finally:
                self.records_done += 1
            if parsers.is_invalid(reply.text):
                continue                                  # past the end after a shift
            raw.write(reply.data)
            rec = parsers.parse_data_record(reply.text)
            if not rec.get('time'):
                missing.append(i)
                continue
            body = reply.data[reply.data.find(b'Time'):]
            key = (rec['time'], hashlib.sha1(body).hexdigest())
            if known is not None and key in known:
                break
            records[key] = rec
            if i % 20 == 0 or i == count - 1:
                self.progress(step='records', module=n, kind=kind, done=count - i, total=count)
        return records, raw.getvalue(), missing

    def slave(self, n, info, stat, pwr, st, stamp):
        barcode = self.unique_barcode(parsers.parse_info(info.text).get('barcode'), n)
        missing = {}
        for kind, count in (('event', st.get('event_items') or 0),
                            ('history', st.get('history_items') or 0)):
            records, raw, miss = self.read_records(n, kind, count)
            # records written while we were reading
            again = parsers.parse_stat(self.run('stat %d' % n, expect='CYCLE Times').text)
            new_count = again.get('%s_items' % kind) or count
            if new_count != count:
                self.records_total += max(new_count - count, 1)
                more, raw2, miss2 = self.read_records(n, kind, new_count, known=records)
                records.update(more)
                raw += raw2
                miss += miss2
            ordered = [records[k] for k in sorted(records)]
            head = info.data + stat.data + (pwr.data if kind == 'event' else b'')
            self.files[export.file_name(barcode, kind, stamp)] = (
                head + export.reconstructed_table(kind, n, ordered))
            self.raw['raw/%s_data_%s.txt' % (barcode, kind)] = raw
            if miss:
                missing[kind] = sorted(set(miss))
        self.raw['raw/%s_info.txt' % barcode] = info.data
        self.raw['raw/%s_stat.txt' % barcode] = stat.data
        self.raw['raw/%s_pwr.txt' % barcode] = pwr.data
        self.summary.append({'module': n, 'barcode': barcode,
                             'fw': parsers.parse_info(info.text).get('fw'),
                             'source': 'reconstructed from data %d event|history <i>' % n,
                             'event': st.get('event_items'), 'history': st.get('history_items'),
                             'missing': missing})

    # -- whole stack ------------------------------------------------------------------------------
    def run_all(self):
        pwr = self.run('pwr', expect='Power Volt')
        modules = parsers.parse_pwr(pwr.text)
        ids = [m['id'] for m in modules]
        if not ids:
            raise ConsoleError('no modules in pwr')
        battery_time = modules[0].get('time') or ''
        digits = ''.join(ch for ch in battery_time if ch.isdigit())
        stamp = digits if len(digits) == 14 else time.strftime('%Y%m%d%H%M%S', time.gmtime())
        self.raw['raw/pwr.txt'] = pwr.data
        by_records = ids[1:] if self.master(stamp) else ids
        heads = {}
        for n in by_records:
            self.progress(step='slave_header', module=n)
            heads[n] = self.slave_header(n)
            st = heads[n][3]
            for c in (st.get('event_items') or 0, st.get('history_items') or 0):
                self.records_total += min(c, self.limit) if self.limit else c
        for n in by_records:
            info, stat, pwr, st = heads[n]
            self.slave(n, info, stat, pwr, st, stamp)
        return stamp, battery_time

    # -- only the connected module ---------------------------------------------------------------
    def run_connected(self):
        """The module whose console the cable is plugged into, verbatim like BatteryView."""
        self.mode = 'connected'
        self.progress(step='connected')
        info = self.run('info', expect='Barcode')
        n = parsers.to_int(dict(parsers.parse_kv(info.text)).get('Device address')) or 0
        self.progress(step='connected', module=n, barcode=parsers.parse_info(info.text).get('barcode'))
        stat = self.run('stat', expect='CYCLE Times')
        # the master prints the stack table, any other module its own detail
        pwr = self.run('pwr', check=lambda t: parsers.is_reply_to(t, 'pwr') and
                       ('Power Volt' in t or 'System Fault' in t))
        rows = parsers.parse_pwr(pwr.text)
        battery_time = (rows[0].get('time') if rows else None) or ''
        digits = ''.join(ch for ch in battery_time if ch.isdigit())
        stamp = digits if len(digits) == 14 else time.strftime('%Y%m%d%H%M%S', time.localtime(self.clock()))
        source = 'verbatim (datalist on the connected module, device address %d)' % n
        if not self.verbatim(n, info, stat, pwr, stamp, source):
            raise ConsoleError('this module does not answer datalist')
        return stamp, battery_time

    def readme(self, stamp, battery_time):
        if self.mode != 'connected':
            return self.readme_stack(stamp, battery_time)
        m = self.summary[0]
        return CRLF.join([
            'Pylontech battery logs for a warranty claim',
            '==========================================',
            '',
            'Created by pylontech-remote on a Victron Cerbo GX.',
            'Cerbo time (UTC): %s' % time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()),
            'Battery clock (battery local time): %s' % (battery_time or 'not shown by this module'),
            '',
            'Read on the console of the module itself (device address %d), as BatteryView does:' % m['module'],
            '  %s_event_%s.txt    info + stat + pwr + datalist event 0' % (m['barcode'], stamp),
            '  %s_history_%s.txt  info + stat + datalist history 0' % (m['barcode'], stamp),
            'Console replies verbatim; the datalist tables stored the way BatteryView stores them',
            '(CRLF lines, a line of spaces where the console paged).',
            'raw/: every console reply exactly as received.',
            '',
            'Module: %s  fw %s  events %s  history %s' % (m['barcode'], m['fw'], m['event'], m['history']),
            '',
        ]).encode('ascii', errors='replace')

    def readme_stack(self, stamp, battery_time):
        lines = [
            'Pylontech battery logs for a warranty claim',
            '==========================================',
            '',
        ] + ([
            '*** TEST EXPORT - INCOMPLETE: only the newest %d records per table of modules 2+. ***' % self.limit,
            '*** Do not send to support. ***',
            '',
        ] if self.limit else []) + [
            'Created by pylontech-remote on a Victron Cerbo GX.',
            'Cerbo time (UTC): %s' % time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()),
            'Battery clock at start (battery local time): %s' % battery_time,
            '',
            'Files per module, as saved by Pylontech BatteryView:',
            '  <barcode>_event_%s.txt    info + stat + pwr + event table' % stamp,
            '  <barcode>_history_%s.txt  info + stat + history table' % stamp,
            '',
            'All modules were read through the console of the master (module 1).',
            'Master: console replies verbatim; tables from "datalist event|history 0" stored the way',
            '  BatteryView stores them (CRLF lines, a line of spaces where the console paged).',
            'Other modules: "info N", "stat N", "pwr N" as the battery answered them (the same',
            '  content as on the module\'s own console, except that "pwr N" shows Charge Times and',
            '  Charge Sec. as 0). The tables are rebuilt row by row from the module\'s own records',
            '  ("data N event|history <i>") in the same layout; all value columns are the module\'s',
            '  own values. Rec_chg/dsg_cur, Sys_Rec_chg/dsg_cur and ID Cur cannot be read through',
            '  the master and are "-". Those tables are marked "[reconstructed ...]".',
            'raw/: every console reply exactly as received (raw/failed/: replies the master cut',
            '  short; those records were read again).',
            '',
            'Modules:',
        ]
        for m in self.summary:
            lines.append('  M%d  %s  fw %s  events %s  history %s  %s%s' % (
                m['module'], m['barcode'], m['fw'], m['event'], m['history'], m['source'],
                ('  MISSING %s' % m['missing']) if m['missing'] else ''))
        lines += ['', 'Read retries: %d' % self.retries, '']
        return CRLF.join(lines).encode('ascii', errors='replace')


def write_zip(outdir, stamp, files, raw, readme, keep, prefix='pylontech_logs_'):
    """`<prefix><stamp>.zip`; the newest `keep` ZIPs with the same prefix are kept.
    Whole stack: pylontech_logs_<stamp>.zip; one module: pylontech_module_<barcode>_<stamp>.zip."""
    os.makedirs(outdir, exist_ok=True)
    name = '%s%s.zip' % (prefix, stamp)
    path = os.path.join(outdir, name)
    tmp = path + '.tmp'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', readme)
        for p in sorted(files):
            z.writestr(p, files[p])
        for p in sorted(raw):
            z.writestr(p, raw[p])
    os.replace(tmp, path)
    kind = 'pylontech_module_' if prefix.startswith('pylontech_module_') else prefix
    old = sorted((f for f in os.listdir(outdir) if f.startswith(kind) and f.endswith('.zip')),
                 key=lambda f: (os.path.getmtime(os.path.join(outdir, f)), f))
    for f in old[:-keep] if keep > 0 else []:
        os.remove(os.path.join(outdir, f))
    return path, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default=default_port())
    ap.add_argument('--gap', type=float, default=0.2, help='minimum pause between commands (s)')
    ap.add_argument('--outdir', default='/data/pylontech/exports')
    ap.add_argument('--connected', action='store_true',
                    help='only the module the cable is plugged into, verbatim (datalist)')
    ap.add_argument('--keep', type=int, default=None,
                    help='keep this many ZIPs of the same kind (default: 5 stack, 30 single module)')
    ap.add_argument('--limit', type=int, default=None,
                    help='TEST ONLY: newest N records per slave table (the ZIP is marked incomplete)')
    a = ap.parse_args()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    session = ConsoleSession(a.port, gap=a.gap)
    try:
        session.open()
    except Exception as e:
        emit({'type': 'error', 'error': 'port_open: %s' % e})
        return 2
    t0 = time.time()
    ex = Exporter(session, limit=a.limit)
    try:
        stamp, battery_time = ex.run_connected() if a.connected else ex.run_all()
    except Cancelled:
        emit({'type': 'error', 'error': 'cancelled'})
        return 4
    except Exception as e:
        emit({'type': 'error', 'error': '%s: %s' % (type(e).__name__, e)})
        return 3
    finally:
        session.close()
    if a.limit:
        stamp += '_TEST'
    for k, (command, attempt, reply) in enumerate(ex.failed):
        ex.raw['raw/failed/%02d_%s_try%d_%s.txt' % (k, command.replace(' ', '_'), attempt + 1,
                                                    reply.end_reason)] = reply.data
    if a.connected:
        prefix, keep = 'pylontech_module_%s_' % ex.summary[0]['barcode'], a.keep or 30
    else:
        prefix, keep = 'pylontech_logs_', a.keep or 5
    path, name = write_zip(a.outdir, stamp, ex.files, ex.raw, ex.readme(stamp, battery_time), keep, prefix)
    emit({'type': 'done', 'mode': ex.mode, 'file': path, 'name': name, 'size': os.path.getsize(path),
          'duration_s': int(time.time() - t0), 'retries': ex.retries, 'modules': ex.summary})
    return 0


if __name__ == '__main__':
    sys.exit(main())
