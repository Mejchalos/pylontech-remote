"""Pure parsers for Pylontech console replies (US-series, firmware B69.x).

They read by labels and table headers, not by fixed positions, and keep fields they do not know.
Input is the reply text as received (echo, '@', mixed line endings and prompt included).
"""
import re

PARSER_VERSION = 1

_DATE = re.compile(r'^\d{2,4}-\d{2}-\d{2}$')
_TIME = re.compile(r'^\d{2}:\d{2}:\d{2}$')
_INT = re.compile(r'^-?\d+$')


def lines(text):
    return [l for l in re.split(r'\r\n|\n\r|\r|\n', text)]


def to_int(value):
    if value is None:
        return None
    v = value.strip().rstrip('%')
    return int(v) if _INT.match(v) else None


# -- "Label : value" replies (info, stat, config) ---------------------------------------------

def parse_kv(text):
    """Ordered list of (label, value). Lines without ':' but with a wide gap
    ("Device address           1") count too."""
    out = []
    for line in lines(text):
        if not line.strip() or line.strip() in ('@', '$$') or line.rstrip().endswith('>'):
            continue
        if ':' in line:
            label, value = line.split(':', 1)
        else:
            m = re.match(r'^\s*(\S.*?)\s{2,}(\S.*)$', line)
            if not m:
                continue
            label, value = m.group(1), m.group(2)
        label = label.strip()
        if label:
            out.append((label, value.strip()))
    return out


def _first(pairs, label):
    for k, v in pairs:
        if k == label:
            return v
    return None


def parse_info(text):
    kv = parse_kv(text)
    return {
        'address': to_int(_first(kv, 'Device address')),
        'model':   _first(kv, 'Device name'),
        'barcode': _first(kv, 'Barcode'),
        'fw':      _first(kv, 'Main Soft version'),
        'fields':  kv,
    }


def parse_stat(text):
    kv = parse_kv(text)

    def num(label):
        v = _first(kv, label)
        return to_int(v.split()[0]) if v else None

    return {
        'address':       num('Device address'),
        'event_items':   num('Data Items'),
        'history_items': num('HisData Items'),
        'soh_pct':       num('SOH'),
        'soc_pct':       num('Pwr Percent'),
        'cycles':        num('CYCLE Times'),
        'bat_hv_times':  num('Bat HV Times'),
        'lv_cnt':        num('LV Cnt'),
        'dsg_cap':       num('Dsg Cap'),
        'fields':        kv,
    }


_CONFIG_LABELS = {
    'bov_mv':       'Over Voltage',
    'bhv_mv':       'High Voltage',
    'blv_mv':       'Low Voltage',
    'buv_mv':       'Under Voltage',
    'bal_start_mv': 'Balance Start',
    'bal_delta_mv': 'Balance Volt',
}


def parse_config(text):
    """Cell thresholds as the original reader read them (first line starting with the label)."""
    out = {}
    for key, label in _CONFIG_LABELS.items():
        m = re.search(r'^\s*' + re.escape(label) + r'\s*:\s*(-?\d+)', text, re.MULTILINE)
        out[key] = int(m.group(1)) if m else None
    return out if any(v is not None for v in out.values()) else None


# -- whitespace tables (pwr, bat) ---------------------------------------------------------------

def _header_labels(line):
    """Split a table header into labels; "Base State", "Volt. State" … are one label."""
    tokens = line.split()
    labels = []
    for t in tokens:
        if t == 'State' and labels:
            labels[-1] = labels[-1] + ' State'
        else:
            labels.append(t)
    return labels


def _row_values(labels, tokens):
    """Assign row tokens to labels. 'Time' takes date+time, 'Coulomb' takes a trailing unit."""
    values = {}
    i = 0
    for label in labels:
        if i >= len(tokens):
            values[label] = None
            continue
        tok = tokens[i]
        i += 1
        if label == 'Time' and _DATE.match(tok) and i < len(tokens) and _TIME.match(tokens[i]):
            tok = tok + ' ' + tokens[i]
            i += 1
        elif label == 'Coulomb' and i < len(tokens) and tokens[i].lower() == 'mah':
            i += 1
        values[label] = tok
    extra = tokens[i:]
    return values, extra


def parse_table(text, first_label):
    """Rows of the first table whose header starts with `first_label` (e.g. 'Power', 'Battery').
    Returns (labels, rows); each row is a dict label -> string (None when missing) plus
    '_extra' for unmatched trailing tokens."""
    labels = None
    rows = []
    for line in lines(text):
        tokens = line.split()
        if not tokens:
            continue
        if labels is None:
            if tokens[0] == first_label:
                labels = _header_labels(line)
            continue
        if not _INT.match(tokens[0]):
            if rows:
                break
            continue
        values, extra = _row_values(labels, tokens)
        if extra:
            values['_extra'] = extra
        rows.append(values)
    return labels, rows


def parse_pwr(text):
    """Per-module summary of the whole stack. Absent slots are skipped."""
    _, rows = parse_table(text, 'Power')
    modules = []
    for r in rows:
        if r.get('Base.St') == 'Absent':
            continue
        modules.append({
            'id':          to_int(r.get('Power')),
            'volt_mv':     to_int(r.get('Volt')),
            'curr_ma':     to_int(r.get('Curr')),
            'temp_mc':     to_int(r.get('Tempr')),
            'tlow_mc':     to_int(r.get('Tlow')),
            'thigh_mc':    to_int(r.get('Thigh')),
            'vlow_mv':     to_int(r.get('Vlow')),
            'vhigh_mv':    to_int(r.get('Vhigh')),
            'base_state':  r.get('Base.St'),
            'volt_state':  r.get('Volt.St'),
            'curr_state':  r.get('Curr.St'),
            'temp_state':  r.get('Temp.St'),
            'soc_pct':     to_int(r.get('Coulomb')),
            'time':        r.get('Time'),
            'mos_temp_mc': to_int(r.get('MosTempr')),
            'raw':         r,
        })
    return modules


def parse_bat(text):
    """Cells of one module."""
    _, rows = parse_table(text, 'Battery')
    cells = []
    for r in rows:
        temp = to_int(r.get('Tempr'))
        cells.append({
            'cell':     to_int(r.get('Battery')),
            'v_mv':     to_int(r.get('Volt')),
            'curr_ma':  to_int(r.get('Curr')),
            'temp_c':   round(temp / 1000.0, 1) if temp is not None else None,
            'state':    r.get('Base State'),
            'soc_pct':  to_int(r.get('SOC')),
            'coul_mah': to_int(r.get('Coulomb')),
            'bal':      r.get('BAL') == 'Y',
        })
    return cells


def _event_names(value):
    """'0x2        PHV ' -> ('0x2', ['PHV'])"""
    parts = (value or '').split()
    if not parts:
        return None, []
    return parts[0], parts[1:]


def parse_data_record(text):
    """One history or event record (`data [N] history|event I`)."""
    kv = parse_kv(text)
    get = lambda label: _first(kv, label)
    num = lambda label: to_int((get(label) or '').split()[0]) if get(label) else None
    index = num('Rec Item Index')
    if index is None:
        index = num('Item Index')
    pwr_hex, pwr_names = _event_names(get('Power Events'))
    bat_hex, bat_names = _event_names(get('Bat Events'))
    _, cell_rows = parse_table(text, 'Battery')
    cells = [{
        'cell':      to_int(r.get('Battery')),
        'v_mv':      to_int(r.get('Volt')),
        'curr_ma':   to_int(r.get('Curr')),
        'temp_mc':   to_int(r.get('Tempr')),
        'state':     r.get('Base State'),
        'soc_pct':   to_int(r.get('Coulomb')),
    } for r in cell_rows]
    return {
        'index':        index,
        'time':         get('Time'),
        'voltage_mv':   num('Voltage'),
        'current_ma':   num('Current'),
        'temp_mc':      num('Temperature'),
        'percent':      num('Percent'),
        'base_state':   get('Base State'),
        'volt_state':   get('Volt. State'),
        'curr_state':   get('Curr. State'),
        'temp_state':   get('Tempr. State'),
        'coul_status':  get('Coul. Status'),
        'power_events': pwr_hex,
        'bat_events':   bat_hex,
        'event_names':  pwr_names + bat_names,
        'system_fault': (get('System Fault') or '').split()[0] if get('System Fault') else None,
        'cells':        cells,
    }


def is_complete(text):
    """A command reply that ran to its normal end."""
    return 'Command completed successfully' in text and text.rstrip().endswith('>')


def is_record_reply(text, index, n_cells=None):
    """`data … event|history <index>` answered completely with that very record.

    After the master cut a slave's answer short it sends the rest with the reply to the *next*
    command, so "Command completed" alone is not enough: the record must be the one asked for,
    with its time and the whole cell table."""
    if not is_complete(text):
        return False
    rec = parse_data_record(text)
    if rec['index'] != index or not rec['time'] or not rec['cells']:
        return False
    numbers = [c['cell'] for c in rec['cells']]
    if numbers != list(range(len(numbers))):
        return False
    return n_cells is None or len(numbers) == n_cells


def is_reply_to(text, command):
    """The reply starts with the echo of `command` and ran to its normal end."""
    return is_complete(text) and text.lstrip('\r\n').startswith(command)


def is_refusal(text, command):
    """The battery answered `command` with "Invalid command…" or "Target device is not present"
    (e.g. an index past the end, or a module that does not exist)."""
    return (text.lstrip('\r\n').startswith(command) and text.rstrip().endswith('>')
            and (is_invalid(text) or is_absent(text)))


def is_absent(text):
    return 'Target device is not present' in text


def is_invalid(text):
    return 'Invalid command' in text
