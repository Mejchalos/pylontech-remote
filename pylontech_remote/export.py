"""Logs for a warranty claim, in the format of Pylontech BatteryView.

BatteryView saves, per module, `<barcode>_event_<YYYYMMDDhhmmss>.txt` and
`<barcode>_history_<…>.txt` (see docs/console-protocol.md):

- event file:   `info`, `stat`, `pwr`, `datalist event 0`
- history file: `info`, `stat`, `datalist history 0`

`info`, `stat` and `pwr` are kept as the console sent them. The `datalist` part is rewritten
with CRLF line ends, and where the console paged ("Press [Enter] …") a line of 50 spaces
remains — before table rows 15, 31, 47, … (every 16 rows).

Through the master:
- module 1 (master): the same commands; the tables verbatim from `datalist`;
- other modules: `info N`, `stat N`, `pwr N` as the battery answered them (same content as on
  the module itself, except `pwr N` shows Charge Times / Charge Sec. as 0); `datalist` is not
  relayed, so the tables are rebuilt row by row from `data N event|history I` records in the
  same layout. All value columns match the module's own table (verified on 304 rows); the
  columns the master cannot provide (Rec_chg/dsg_cur, Sys_Rec_chg/dsg_cur, ID Cur) are `-`,
  as in the module's own oldest rows. The table is marked as reconstructed.
"""
import re

LINE_SPLIT = re.compile(rb'\r\r\n|\r\n\r|\n\r|\r\n|\r|\n')
PAGING = re.compile(rb'\r?\n?\r?Press \[Enter\] to be continued,other key to exit\r\r( {0,80})\r')
BLANK = b' ' * 50
CRLF = b'\r\n'
PROMPT = b'pylon_debug>'

DATALIST_HEADER_B69_25 = (
    b'Item  Time               Vo(mV) Cu(mA) Tempr   Tlow    Thigh   Vlowest  Vhighest Base.St   '
    b'Volt.St   Curr.St   Temp.St Per% SysErrCode   Rec_chg/dsg_cur(0.1A) Sys_Rec_chg/dsg_cur(0.1A) '
    + b'ID Cur   ' * 15 + b'(0.1A)  Events  ')

# Columns the master cannot provide for another module: what a module prints in its own rows
# from before it logged them.
_NO_STACK_COLUMNS = ('-'.ljust(7) + '/ ' + '-'.ljust(13) + '-'.ljust(11) + '/ ' + '-'.ljust(13)
                     + '-  -     ' * 15 + ' ' * 8)


def batteryview_table(raw):
    """A `datalist …` console reply as BatteryView stores it: CRLF lines; each paging prompt
    becomes a line of spaces."""
    data = PAGING.sub(lambda m: CRLF + (m.group(1) or BLANK) + CRLF, raw)
    lines = [l for l in LINE_SPLIT.split(data) if l != b'']
    return CRLF.join(lines) + CRLF


def datalist_row(item, rec):
    """One `datalist` row (B69.25 layout) from a parsed `data` record, as bytes without line end."""
    cells = rec['cells']
    volts = [c['v_mv'] for c in cells if c['v_mv'] is not None]
    temps = [c['temp_mc'] for c in cells if c['temp_mc'] is not None]
    fault = rec.get('system_fault')
    sys_err = '' if fault in (None, '0x0') else fault
    row = '%-6d%-19s%-7d%-7d%-8d%-8d%-8d%-9d%-9d%-10s%-10s%-10s%-6s%5d%% %-13s' % (
        item, rec['time'], rec['voltage_mv'], rec['current_ma'], rec['temp_mc'],
        min(temps), max(temps), min(volts), max(volts),
        rec['base_state'], rec['volt_state'], rec['curr_state'], rec['temp_state'],
        rec['percent'], sys_err)
    row += _NO_STACK_COLUMNS + ''.join(n + ' ' for n in rec['event_names'])
    return row.encode('ascii')


def reconstructed_table(kind, module, records):
    """The `datalist <kind> 0` part of a BatteryView file, rebuilt from `data` records (parsed,
    oldest first). Rows are numbered from 0 like the battery does."""
    note = ('[reconstructed by pylontech-remote: module %d read through the master, record by '
            'record with "data %d %s <i>"; columns the master cannot read are "-"]'
            % (module, module, kind)).encode('ascii')
    lines = [b'datalist ' + kind.encode() + b' 0', b'@', note, DATALIST_HEADER_B69_25]
    for i, rec in enumerate(records):
        if i >= 15 and (i - 15) % 16 == 0:
            lines.append(BLANK)
        lines.append(datalist_row(i, rec))
    lines += [b'Command completed successfully', b'$$', PROMPT]
    return CRLF.join(lines) + CRLF


def file_name(barcode, kind, stamp):
    return '%s_%s_%s.txt' % (re.sub(r'[^A-Za-z0-9]', '_', barcode or 'unknown'), kind, stamp)
