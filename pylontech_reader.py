#!/usr/bin/env python3
"""
Pylontech RS232 console reader for Victron Cerbo GX / Venus OS.
Reads ALL battery modules via the RS232 console port (USB/RS232 FTDI adapter),
auto-detecting the module count (bat 1..9), and prints a JSON document to stdout.

Universal: works with any Pylontech US-series stack (US5000 / US3000C / US3000 /
US2000 ...) on any Venus OS device. Serial port configurable via PYLONTECH_PORT.

Deploy to: /data/pylontech_reader.py
Manual test: python3 /data/pylontech_reader.py
"""
import serial
import time
import json
import sys
import os
import re


# Universal: serial port via env var, defaults to /dev/ttyUSB0.
# Set PYLONTECH_PORT=/dev/ttyUSB1 (etc.) if your FTDI enumerates elsewhere.
PORT = os.environ.get('PYLONTECH_PORT', '/dev/ttyUSB0')
BAUD = int(os.environ.get('PYLONTECH_BAUD', '115200'))

# Nominal capacities: US5000=100Ah (48V/4.8kWh), US3000C=74Ah (48V/3.552kWh)
# Nominal Ah per module model (48V). Unknown models fall back to 74 Ah.
NOMINAL_AH = {
    'US5000':  100.0,   # 4.80 kWh
    'US3000C':  74.0,   # 3.55 kWh
    'US3000':   74.0,
    'US2000C':  50.0,   # 2.40 kWh
    'US2000B':  50.0,
    'US2000':   50.0,
}
NOMINAL_AH_DEFAULT = 74.0


def open_port():
    s = serial.Serial(
        PORT, BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.5,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    s.dtr = False
    s.rts = False
    time.sleep(1.0)
    return s


def drain(s):
    time.sleep(0.2)
    while s.in_waiting:
        s.read(s.in_waiting)
        time.sleep(0.1)


def read_until_prompt(s, timeout=12.0):
    buf = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = s.read(512)
        if chunk:
            buf += chunk
            low = buf.lower()
            if b'[enter]' in low or b'--more--' in low or b'continued' in low:
                s.write(b' ')
            if b'>' in buf:
                break
    return buf.decode('ascii', errors='replace')


def cmd(s, command, timeout=8.0):
    drain(s)
    time.sleep(1.2)
    s.write((command + '\n').encode())
    return read_until_prompt(s, timeout)


def parse_field(text, label):
    """Extract value after 'Label : value' pattern."""
    m = re.search(r'^\s*' + re.escape(label) + r'\s*:\s*(.+)$', text, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_int_field(text, label):
    val = parse_field(text, label)
    if val is None:
        return None
    try:
        return int(val.split()[0])
    except (ValueError, IndexError):
        return None


def parse_info(text):
    return {
        'model':   parse_field(text, 'Device name') or '?',
        'barcode': parse_field(text, 'Barcode') or '?',
        'fw':      parse_field(text, 'Main Soft version') or '?',
    }


def parse_stat(text):
    soh = parse_int_field(text, 'SOH')
    soc = parse_int_field(text, 'Pwr Percent')
    cycles = parse_int_field(text, 'CYCLE Times')
    dsg_cap = parse_int_field(text, 'Dsg Cap')
    bat_hv = parse_int_field(text, 'Bat HV Times')
    lv_cnt = parse_int_field(text, 'LV Cnt')
    return {
        'soh_bms_pct': soh if soh is not None and soh > 0 else None,
        'soc_bms_pct': soc,
        'cycles':      cycles if cycles is not None and cycles > 0 else None,
        'dsg_cap_mah': dsg_cap,
        'bat_hv_times': bat_hv,
        'lv_cnt':      lv_cnt,
    }


def parse_event(text):
    # 'data event N' is not a valid command on US3000C/US5000 firmware B69.x
    # Specific cells are not available — return empty values
    return {'last_hv_date': None, 'hv_cells': []}


def parse_config(text):
    def get_mv(label):
        m = re.search(r'^\s*' + re.escape(label) + r'\s*:\s*([-0-9]+)', text, re.MULTILINE)
        return int(m.group(1)) if m else None
    result = {
        'bov_mv':       get_mv('Over Voltage'),
        'bhv_mv':       get_mv('High Voltage'),
        'blv_mv':       get_mv('Low Voltage'),
        'buv_mv':       get_mv('Under Voltage'),
        'bal_start_mv': get_mv('Balance Start'),
        'bal_delta_mv': get_mv('Balance Volt'),
    }
    return result if any(v is not None for v in result.values()) else None



def parse_module(text):
    cells = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 10 and parts[0].isdigit():
            try:
                cell_id  = int(parts[0])
                volt_mv  = int(parts[1])
                curr_ma  = int(parts[2])
                temp_c   = round(int(parts[3]) / 1000.0, 1)
                state    = parts[4]
                soc_pct  = int(parts[8].replace('%', ''))
                coul_mah = int(parts[9])
                bal      = (parts[11] == 'Y') if len(parts) > 11 else False
                cells.append({
                    'cell':     cell_id,
                    'v_mv':     volt_mv,
                    'curr_ma':  curr_ma,
                    'temp_c':   temp_c,
                    'state':    state,
                    'soc_pct':  soc_pct,
                    'coul_mah': coul_mah,
                    'bal':      bal,
                })
            except (ValueError, IndexError):
                continue
    return cells


def summarize(module_id, cells, info, stat=None, event=None):
    if not cells:
        return None
    volts = [c['v_mv'] for c in cells]
    temps = [c['temp_c'] for c in cells]
    socs  = [c['soc_pct'] for c in cells]
    couls = [c['coul_mah'] for c in cells]
    cap_ah = round(min(couls) / 1000.0, 1)
    model = info.get('model', '?') if info else '?'
    nominal = NOMINAL_AH.get(model, NOMINAL_AH_DEFAULT)
    # Per-cell full-capacity estimate: coul / (soc/100) — pairs each cell's
    # coulombs with its own SOC, avoids min/avg mismatch that underestimates.
    per_cell_full = [c['coul_mah'] / (c['soc_pct'] / 100.0)
                     for c in cells if c['soc_pct'] > 5]
    full_ah = round(min(per_cell_full) / 1000.0, 1) if per_cell_full else None
    soh_est_pct = round(full_ah / nominal * 100) if full_ah else None
    soh_bms_pct  = stat.get('soh_bms_pct')  if stat else None
    soc_bms_pct  = stat.get('soc_bms_pct')  if stat else None
    cycles       = stat.get('cycles')        if stat else None
    bat_hv_times = stat.get('bat_hv_times') if stat else None
    last_hv_date = event.get('last_hv_date') if event else None
    hv_cells     = event.get('hv_cells', []) if event else []

    mod = {
        'id':      module_id,
        'model':   model,
        'barcode': info.get('barcode', '?') if info else '?',
        'fw':      info.get('fw', '?') if info else '?',
        'n_cells': len(cells),
        'cells':        cells,
        'curr_a':       round(cells[0]['curr_ma'] / 1000.0, 3),
        'min_v_mv':     min(volts),
        'max_v_mv':     max(volts),
        'avg_v_mv':     round(sum(volts) / len(volts), 1),
        'spread_mv':    max(volts) - min(volts),
        'min_temp_c':   min(temps),
        'max_temp_c':   max(temps),
        'avg_temp_c':   round(sum(temps) / len(temps), 1),
        'soc_pct':      soc_bms_pct if soc_bms_pct is not None else round(sum(socs) / len(socs)),
        'cap_ah':       cap_ah,
        'full_ah':      full_ah,
        'nominal_ah':   nominal,
        'soh_pct':      soh_bms_pct if soh_bms_pct is not None else soh_est_pct,
        'soh_source':   'bms' if soh_bms_pct is not None else 'est',
        'cycles':       cycles,
        'bat_hv_times': bat_hv_times,
        'last_hv_date': last_hv_date,
        'hv_cells':     hv_cells,
    }
    return mod


def main():
    for attempt in range(2):
        try:
            s = open_port()
        except Exception as e:
            print(json.dumps({'ok': False, 'error': 'port_open: ' + str(e), 'modules': []}))
            return

        try:
            s.write(b'\n')
            resp = read_until_prompt(s, timeout=8.0)

            if '>' not in resp:
                print(json.dumps({'ok': False, 'error': 'no_prompt', 'modules': []}))
                s.close()
                return

            # Phase 1: bat N — cell voltages for all modules
            bat_data = {}
            for n in range(1, 10):
                drain(s)
                time.sleep(2.0)
                s.write(('bat ' + str(n) + '\n').encode())
                resp = read_until_prompt(s, timeout=12.0)
                if not resp.strip():
                    drain(s)
                    time.sleep(2.0)
                    s.write(('bat ' + str(n) + '\n').encode())
                    resp = read_until_prompt(s, timeout=12.0)
                if not resp.strip():
                    continue
                if 'Invalid' in resp or 'invalid' in resp:
                    break
                cells = parse_module(resp)
                if cells:
                    bat_data[n] = cells

            # Phase 1b: config thresholds (read once — same for all modules)
            thresholds = None
            try:
                thresholds = parse_config(cmd(s, 'config'))
            except Exception:
                pass

            # Phase 2: info N + stat N per module
            info_data = {}
            stat_data = {}
            event_data = {}
            for n in sorted(bat_data.keys()):
                info_data[n] = parse_info(cmd(s, 'info ' + str(n)))
                try:
                    stat_data[n] = parse_stat(cmd(s, 'stat ' + str(n)))
                except Exception:
                    stat_data[n] = None
                # 'data event N' is not a supported command — skip

            s.close()

            modules = []
            for n in sorted(bat_data.keys()):
                mod = summarize(n, bat_data[n], info_data.get(n), stat_data.get(n), event_data.get(n))
                if mod:
                    modules.append(mod)

            all_volts = [c['v_mv'] for m in modules for c in m['cells']]
            total_spread = (max(all_volts) - min(all_volts)) if all_volts else 0

            # Pack-level aggregates
            pack = None
            if modules:
                pack_curr_a   = round(sum(m['curr_a'] for m in modules), 2)
                pack_cap_ah   = round(sum(m['cap_ah'] for m in modules), 1)
                pack_nom_ah   = sum(m['nominal_ah'] for m in modules)
                pack_soc_pct  = round(sum(m['soc_pct'] * m['nominal_ah'] for m in modules) / pack_nom_ah)
                _soh_mods = [m for m in modules if m.get('soh_pct') is not None]
                pack_soh_pct  = round(sum(m['soh_pct'] * m['nominal_ah'] for m in _soh_mods) /
                                      sum(m['nominal_ah'] for m in _soh_mods)) if _soh_mods else None
                pack_min_v    = min(m['min_v_mv'] for m in modules)
                pack_max_v    = max(m['max_v_mv'] for m in modules)
                pack_avg_temp = round(sum(m['avg_temp_c'] for m in modules) / len(modules), 1)
                pack = {
                    'curr_a':     pack_curr_a,
                    'cap_ah':     pack_cap_ah,
                    'nominal_ah': pack_nom_ah,
                    'soc_pct':    pack_soc_pct,
                    'soh_pct':    pack_soh_pct,
                    'min_v_mv':   pack_min_v,
                    'max_v_mv':   pack_max_v,
                    'avg_temp_c': pack_avg_temp,
                    'energy_kwh': round(pack_cap_ah * 48.0 / 1000.0, 2),
                    'nominal_kwh': round(pack_nom_ah * 48.0 / 1000.0, 2),
                }

            print(json.dumps({
                'ok':              True,
                'error':           None,
                'ts':              int(time.time()),
                'n_modules':       len(modules),
                'total_spread_mv': total_spread,
                'thresholds':      thresholds,
                'pack':            pack,
                'modules':         modules,
            }))
            return  # success

        except serial.SerialException as e:
            try:
                s.close()
            except Exception:
                pass
            if attempt == 0:
                time.sleep(3.0)
                continue
            print(json.dumps({'ok': False, 'error': str(e), 'modules': []}))
            return
        except Exception as e:
            try:
                s.close()
            except Exception:
                pass
            print(json.dumps({'ok': False, 'error': str(e), 'modules': []}))
            return


main()
