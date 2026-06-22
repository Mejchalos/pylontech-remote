# pylontech-rs232-venus

Per-module **Pylontech BMS monitoring** for **Victron Cerbo GX / Venus OS**, read over the
battery's **RS232 console port** through a USB/RS232 (FTDI) adapter — with a ready-made
Node-RED dashboard.

The Victron CAN bus only exposes pack-level aggregates. This package reads the **RS232
console** directly, giving you **per-module and per-cell** data: cell voltages, temperatures,
SOC, SOH, balancing state, cycle counts and BMS protection thresholds — for every module in
the stack.

![Pylontech BMS dashboard — /battery page](docs/dashboard.png)

*Per-module view: pack summary, per-module SOC / current / temp / capacity / SOH / cycles,
15-cell colour bar and BHV history.*

---

## What you get

- **`pylontech_reader.py`** — universal Python reader. Auto-detects the number of modules
  (`bat 1..9`), reads model/capacity from each module, outputs one JSON document.
- **`nodered/pylontech_flow.json`** — self-contained Node-RED flow: poller → reader → parser →
  dashboard widget (Dashboard 2.0). Imports cleanly into a fresh Node-RED.
- **`install.sh`** — one-shot installer for the Cerbo: frees the serial port, installs
  dependencies, deploys the reader, runs a self-test.

Works with any Pylontech US-series stack (US5000 / US3000C / US3000 / US2000…), any module
count, on any Venus OS device.

---

## Hardware

| Item | Detail |
|------|--------|
| Adapter | USB ↔ RS232, **FTDI FT232R** chipset (any brand) |
| Cable | RJ45 → DB9, into the Pylontech **console** port of the **master** module |
| Link | 115200 baud, 8N1, **no flow control**, **DTR/RTS = False** |
| Topology | Master ↔ slaves over the internal RS485 — the console reads them all |

> **DTR/RTS must be False** — with them asserted the battery does not reply. The reader sets
> this; if you test with another tool, set it there too.

---

## Prerequisites on the Cerbo

1. **Root SSH** access (`ssh root@<cerbo-ip>`).
2. **Python 3** (present on Venus OS large images) + **pyserial** (the installer adds it).
3. **Node-RED** with **Dashboard 2.0** (`@flowfuse/node-red-dashboard`) installed — same UI
   framework the flow is built on. Install it from the Node-RED palette manager if missing.

---

## Install

```bash
# on a dev machine: copy the package to the Cerbo
scp -r pylontech-rs232-venus root@<cerbo-ip>:/data/

# on the Cerbo:
ssh root@<cerbo-ip>
cd /data/pylontech-rs232-venus
sh install.sh
```

The installer will:
1. **Auto-detect** the FTDI adapter and its serial number.
2. Write a udev rule (`/etc/udev/rules.d/99-pylontech-ftdi.rules`, mirrored to `/data/etc/...`
   so it survives OS updates) that sets `VE_SERVICE=ignore` for **that specific adapter** —
   so Venus OS `serial-starter` / `gps_dbus` stops grabbing the port.
3. Reload udev and restart `serial-starter`.
4. Install **pyserial** (via `opkg` or `pip3`).
5. Copy the reader to `/data/pylontech_reader.py` and run a **self-test**.

If your adapter is not on `/dev/ttyUSB0`, force it:

```bash
PYLONTECH_PORT=/dev/ttyUSB1 sh install.sh
```

### Import the dashboard

1. Open Node-RED: `http://<cerbo-ip>:1880`
2. Menu → **Import** → paste/upload `nodered/pylontech_flow.json` → **Import** → **Deploy**.
3. Dashboard: `http://<cerbo-ip>:1880/dashboard/battery`

The flow ships its own dashboard page/group, so it won't collide with an existing dashboard.

---

## Configuration

| What | How |
|------|-----|
| Serial port | env `PYLONTECH_PORT` (default `/dev/ttyUSB0`). Set it in the Node-RED **exec** node command if needed: `PYLONTECH_PORT=/dev/ttyUSB1 python3 /data/pylontech_reader.py` |
| Baud | env `PYLONTECH_BAUD` (default `115200`) |
| Poll interval | the **inject** node in the flow (default 120 s) |
| Module capacities | `NOMINAL_AH` map in `pylontech_reader.py` (unknown models default to 74 Ah) |

> The parsed result is stored in `global.pylontech_bms` **in memory** (not the `file` store) —
> reading every ~2 min, persistence would wear the Cerbo flash for no benefit.

---

## How the reader works

One serial session per poll:

```
\n              wake the console, wait for the ">" prompt
bat 1..9        per-cell voltage / current / temp / SOC% / coulombs (stops at "Invalid")
config          BMS protection thresholds (once — same for all modules)
info N          model (Device name), barcode, firmware
stat N          SOH, SOC (Pwr Percent), cycles, Dsg Cap, Bat HV Times, LV Cnt
```

Timing matters: 1.2–2.0 s between commands (slave modules answer over RS485), serial timeout
0.5 s, paging prompts (`[enter]`, `--more--`, `continued`) are answered automatically. A full
read of 6 modules takes ~60–90 s.

### SOH

1. **BMS-native** (`stat N` → `SOH`) if it reports > 0.
2. **Coulomb estimate** fallback (per-cell): `full_ah = min(coul_mah / (soc/100)) / 1000`,
   `soh = full_ah / nominal × 100`. The per-cell method avoids the underestimate you get from
   `min(coulombs) / avg_soc`.

Pack SOH is the capacity-weighted average of module SOH (not `cap_ah/nominal`, which is SOC).

### JSON output (`global.pylontech_bms`)

```json
{
  "ok": true, "ts": 1234567890, "n_modules": 6, "total_spread_mv": 12,
  "thresholds": { "bov_mv": 3650, "bhv_mv": 3600, "blv_mv": 3050,
                  "buv_mv": 2800, "bal_start_mv": 3360, "bal_delta_mv": 5 },
  "pack": { "curr_a": -12.3, "cap_ah": 198.4, "nominal_ah": 470, "soc_pct": 72,
            "soh_pct": 91, "min_v_mv": 3301, "max_v_mv": 3318, "avg_temp_c": 24.1,
            "energy_kwh": 9.52, "nominal_kwh": 22.56 },
  "modules": [ {
    "id": 1, "model": "US5000", "barcode": "...", "fw": "B69.16", "n_cells": 15,
    "curr_a": -2.1, "min_v_mv": 3301, "max_v_mv": 3318, "spread_mv": 17,
    "avg_temp_c": 24.1, "soc_pct": 72, "cap_ah": 33.2, "soh_pct": 95,
    "soh_source": "bms", "cycles": null, "bat_hv_times": 0,
    "cells": [ { "cell": 1, "v_mv": 3312, "temp_c": 24.1, "soc_pct": 72,
                 "coul_mah": 23904, "bal": false } ]
  } ]
}
```

---

## Dashboard widget

- Pack summary: SOC, current, temperature, capacity (Ah + kWh), SOH, total spread (mV).
- Per module: model, barcode, fw, SOC, current, temp, capacity, SOH (`bms`/`est`), cycles,
  Bat-HV alarm count.
- 15-cell colour bar using the **absolute** thresholds from `bms.thresholds`
  (green normal, amber near-alarm, red ≥ BHV / ≤ BLV).

---

## Troubleshooting

**Port busy / no reply after reboot**
```bash
fuser /dev/ttyUSB0                 # who holds the port
svc -d /service/serial-starter
kill -9 $(fuser /dev/ttyUSB0) 2>/dev/null
svc -u /service/serial-starter
```

**Battery returns nothing** — verify the port is free and DTR/RTS off:
```bash
python3 - << 'EOF'
import serial, time
s = serial.Serial('/dev/ttyUSB0', 115200, timeout=0.5, xonxoff=False, rtscts=False, dsrdtr=False)
s.dtr = False; s.rts = False; time.sleep(1.0); s.write(b'\n')
buf=b''; t0=time.time()
while time.time()-t0 < 5:
    c=s.read(256); buf+=c
    if b'>' in buf: break
print(repr(buf)); s.close()
EOF
```
Expect something like `b'\n\rpylon_debug>'`. Empty → udev rule / `fuser` issue.

**`VE_SERVICE` not `ignore`** — the udev rule didn't apply:
```bash
udevadm info -q property -n /dev/ttyUSB0 | grep VE_SERVICE
# re-apply:
cp /data/etc/udev/rules.d/99-pylontech-ftdi.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger --name-match=ttyUSB0
svc -d /service/serial-starter && sleep 1 && svc -u /service/serial-starter
```

**After a Venus OS update** — the rule in `/etc` may be gone (the `/data` copy persists):
re-run `sh install.sh`, or copy the rule from `/data/etc/udev/rules.d/` back to `/etc/...`.

---

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with Pylontech or Victron Energy. Use at your own risk; reading the console is
passive but you are responsible for your own battery system.
