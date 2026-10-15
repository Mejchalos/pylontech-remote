"""Live data: stack state built from pwr / bat / info / stat / config replies.

`StackState.snapshot()` returns the same JSON shape as the original pylontech_reader.py (so the
existing dashboard widget keeps working), plus freshness information for the live view.
"""
import re
import time

from . import parsers

# `stat` counters of protection / alarm events (everything else ending in "Times" is operation).
_ALARM_RE = re.compile(
    r'^(COC2?|DOC2?|COCA|DOCA|SC|(Bat|Pwr) (OV|HV|LV|UV|SLP)|COT|CUT|DOT|DUT|CHT|CLT|DHT|DLT|'
    r'Shut|Reset|RV|Input OV|BMICERR|LifeWarn|LifeAlarm) Times$')
_TIME_RE = re.compile(r'(Secs?|Hours)$')


def _fmt_duration(label, value):
    n = parsers.to_int(value)
    if n is None:
        return value
    secs = n * 3600 if label.endswith('Hours') else n
    if secs < 3600:
        return '%d s' % secs if secs < 60 else '%d min' % (secs // 60)
    hours = secs / 3600.0
    return '%.1f h' % hours if hours < 48 else '%d d %d h' % (hours // 24, hours % 24)


def group_stats(fields):
    """Split `stat` lines into alarms / operation / time / records for the dashboard.
    Each item is [label, value, shown]: `shown` is the value for display (durations as h / d),
    `value` the raw text from the battery."""
    groups = {'alarms': [], 'operation': [], 'time': [], 'records': []}
    for label, value in fields:
        if label == 'Device address':
            continue
        if _ALARM_RE.match(label):
            groups['alarms'].append([label, value, value])
        elif label.endswith('Items'):
            groups['records'].append([label, value, value])
        elif _TIME_RE.search(label):
            groups['time'].append([label, value, _fmt_duration(label, value)])
        else:
            groups['operation'].append([label, value, value])
    return groups

# Nominal Ah per module model (48 V). Unknown models fall back to 74 Ah.
NOMINAL_AH = {
    'US5000':  100.0,
    'US3000C':  74.0,
    'US3000':   74.0,
    'US2000C':  50.0,
    'US2000B':  50.0,
    'US2000':   50.0,
}
NOMINAL_AH_DEFAULT = 74.0


class StackState(object):
    def __init__(self, clock=time.time):
        self._clock = clock
        self.info = {}         # module id -> parse_info()
        self.stat = {}         # module id -> parse_stat()
        self.thresholds = None
        self.pwr = {}          # module id -> parse_pwr() row
        self.pwr_ts = None
        self.cells = {}        # module id -> parse_bat()
        self.cells_ts = {}     # module id -> time

    # -- updates ---------------------------------------------------------------------------
    def update_pwr(self, text):
        rows = parsers.parse_pwr(text)
        if rows:
            self.pwr = dict((r['id'], r) for r in rows)
            self.pwr_ts = self._clock()
        return rows

    def update_bat(self, module, text):
        cells = parsers.parse_bat(text)
        if cells:
            self.cells[module] = cells
            self.cells_ts[module] = self._clock()
        return cells

    def update_info(self, module, text):
        info = parsers.parse_info(text)
        if info.get('barcode') or info.get('model'):
            old = self.info.get(module)
            if old and old.get('barcode') != info.get('barcode'):
                self.stat.pop(module, None)   # another module in this slot: cached stats are not its
            self.info[module] = info
        return info

    def update_stat(self, module, text):
        stat = parsers.parse_stat(text)
        if stat.get('soh_pct') is not None or stat.get('cycles') is not None:
            stat['read_at'] = int(self._clock())
            self.stat[module] = stat
        return stat

    def update_config(self, text):
        cfg = parsers.parse_config(text)
        if cfg:
            self.thresholds = cfg
        return cfg

    # -- slow-changing data, kept between runs ----------------------------------------------
    _INFO_KEYS = ('address', 'model', 'barcode', 'fw')
    # `fields` (all counters) change on every read: the runner saves after a whole refresh round
    _STAT_KEYS = ('address', 'soh_pct', 'cycles', 'bat_hv_times', 'fields', 'read_at')

    def static_dict(self):
        """Model, serial, firmware, statistics and thresholds — what `info`, `stat` and `config`
        return. Saved between runs so the dashboard is complete from the first update."""
        mods = {}
        for n in sorted(set(self.info) | set(self.stat)):
            entry = {}
            if n in self.info:
                entry['info'] = dict((k, self.info[n].get(k)) for k in self._INFO_KEYS)
            if n in self.stat:
                entry['stat'] = dict((k, self.stat[n].get(k)) for k in self._STAT_KEYS)
            mods[str(n)] = entry
        return {'thresholds': self.thresholds, 'modules': mods}

    def load_static(self, data):
        if not isinstance(data, dict):
            return
        if data.get('thresholds'):
            self.thresholds = data['thresholds']
        for key, entry in (data.get('modules') or {}).items():
            try:
                n = int(key)
            except ValueError:
                continue
            if entry.get('info'):
                self.info[n] = dict(entry['info'], fields=[])
            if entry.get('stat'):
                stat = dict(entry['stat'])
                stat['fields'] = [tuple(f) for f in stat.get('fields') or []]
                self.stat[n] = stat

    @property
    def module_ids(self):
        return sorted(self.pwr) if self.pwr else sorted(self.cells)

    # -- snapshot --------------------------------------------------------------------------
    def _module(self, n, now):
        p = self.pwr.get(n) or {}
        info = self.info.get(n) or {}
        stat = self.stat.get(n) or {}
        cells = self.cells.get(n) or []
        model = info.get('model') or '?'
        nominal = NOMINAL_AH.get(model, NOMINAL_AH_DEFAULT)

        volts = [c['v_mv'] for c in cells if c['v_mv'] is not None]
        temps = [c['temp_c'] for c in cells if c['temp_c'] is not None]
        couls = [c['coul_mah'] for c in cells if c['coul_mah'] is not None]
        socs = [c['soc_pct'] for c in cells if c['soc_pct'] is not None]

        def mc(v):
            return round(v / 1000.0, 1) if v is not None else None

        min_v = p.get('vlow_mv') if p.get('vlow_mv') is not None else (min(volts) if volts else None)
        max_v = p.get('vhigh_mv') if p.get('vhigh_mv') is not None else (max(volts) if volts else None)
        soc = p.get('soc_pct')
        if soc is None:
            soc = stat.get('soc_pct')
        if soc is None and socs:
            soc = round(sum(socs) / float(len(socs)))
        curr_ma = p.get('curr_ma')
        if curr_ma is None and cells:
            curr_ma = cells[0]['curr_ma']

        if couls:
            cap_ah = round(min(couls) / 1000.0, 1)
        elif soc is not None:
            cap_ah = round(nominal * soc / 100.0, 1)
        else:
            cap_ah = None
        per_cell_full = [c['coul_mah'] / (c['soc_pct'] / 100.0) for c in cells
                         if c['coul_mah'] is not None and c['soc_pct'] and c['soc_pct'] > 5]
        full_ah = round(min(per_cell_full) / 1000.0, 1) if per_cell_full else None
        soh_est = round(full_ah / nominal * 100) if full_ah else None
        soh_bms = stat.get('soh_pct') if stat.get('soh_pct') else None
        cycles = stat.get('cycles') if stat.get('cycles') else None

        return {
            'id':           n,
            'model':        model,
            'barcode':      info.get('barcode') or '?',
            'fw':           info.get('fw') or '?',
            'n_cells':      len(cells),
            'cells':        cells,
            'curr_a':       round(curr_ma / 1000.0, 3) if curr_ma is not None else 0.0,
            'min_v_mv':     min_v,
            'max_v_mv':     max_v,
            'avg_v_mv':     round(sum(volts) / float(len(volts)), 1) if volts else None,
            'spread_mv':    (max_v - min_v) if (min_v is not None and max_v is not None) else None,
            'min_temp_c':   mc(p.get('tlow_mc')) if p.get('tlow_mc') is not None else (min(temps) if temps else None),
            'max_temp_c':   mc(p.get('thigh_mc')) if p.get('thigh_mc') is not None else (max(temps) if temps else None),
            'avg_temp_c':   mc(p.get('temp_mc')) if p.get('temp_mc') is not None else (round(sum(temps) / len(temps), 1) if temps else None),
            'mos_temp_c':   mc(p.get('mos_temp_mc')),
            'soc_pct':      soc,
            'cap_ah':       cap_ah,
            'full_ah':      full_ah,
            'nominal_ah':   nominal,
            'soh_pct':      soh_bms if soh_bms is not None else soh_est,
            'soh_source':   'bms' if soh_bms is not None else 'est',
            'cycles':       cycles,
            'bat_hv_times': stat.get('bat_hv_times'),
            'last_hv_date': None,
            'hv_cells':     [],
            'state':        p.get('base_state'),
            'pwr_age_s':    round(now - self.pwr_ts, 1) if (p and self.pwr_ts) else None,
            'cells_age_s':  round(now - self.cells_ts[n], 1) if n in self.cells_ts else None,
            'stats':        group_stats(stat.get('fields') or []),
            'stats_read_at': stat.get('read_at'),
        }

    def snapshot(self, live=True):
        now = self._clock()
        modules = [self._module(n, now) for n in self.module_ids]
        lows = [m['min_v_mv'] for m in modules if m['min_v_mv'] is not None]
        highs = [m['max_v_mv'] for m in modules if m['max_v_mv'] is not None]
        pack = None
        if modules:
            nom = sum(m['nominal_ah'] for m in modules)
            caps = [m['cap_ah'] for m in modules if m['cap_ah'] is not None]
            socs = [m for m in modules if m['soc_pct'] is not None]
            sohs = [m for m in modules if m['soh_pct'] is not None]
            temps = [m['avg_temp_c'] for m in modules if m['avg_temp_c'] is not None]
            cap = round(sum(caps), 1) if caps else None
            pack = {
                'curr_a':      round(sum(m['curr_a'] for m in modules), 2),
                'cap_ah':      cap,
                'nominal_ah':  nom,
                'soc_pct':     round(sum(m['soc_pct'] * m['nominal_ah'] for m in socs) /
                                     sum(m['nominal_ah'] for m in socs)) if socs else None,
                'soh_pct':     round(sum(m['soh_pct'] * m['nominal_ah'] for m in sohs) /
                                     sum(m['nominal_ah'] for m in sohs)) if sohs else None,
                'min_v_mv':    min(lows) if lows else None,
                'max_v_mv':    max(highs) if highs else None,
                'avg_temp_c':  round(sum(temps) / len(temps), 1) if temps else None,
                'energy_kwh':  round(cap * 48.0 / 1000.0, 2) if cap is not None else None,
                'nominal_kwh': round(nom * 48.0 / 1000.0, 2),
            }
        return {
            'ok':              bool(modules),
            'error':           None if modules else 'no data yet',
            'ts':              int(now),
            'n_modules':       len(modules),
            'total_spread_mv': (max(highs) - min(lows)) if (lows and highs) else 0,
            'thresholds':      self.thresholds,
            'pack':            pack,
            'modules':         modules,
            'live':            live,
            'loading':         False,
        }
