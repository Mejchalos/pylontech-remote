# pylontech-rs232-venus

Remote access to **Pylontech** battery logs and live data on a **Victron Cerbo GX / Venus OS**,
through the RS232 console of the battery's master module and a Node-RED dashboard.

- **Logs for a warranty claim** — the event and history logs as the files Pylontech BatteryView
  saves, as a ZIP from the dashboard: of the module the cable is plugged into (verbatim), or of
  the whole stack through the master. Works through VRM, without a technician on site.
- **Live view** — pack, modules and cells of the whole stack, updated every 8 s, plus the
  lifetime counters of each module.

The Victron CAN bus only exposes pack-level values. The console of the **master** module gives
per-module and per-cell data for the whole stack, and the stored records of every module.

Based on the original project by **Martin (tejno)** — see [Credits](#credits).

![Pylontech BMS dashboard](docs/dashboard.png)

---

## Project status

**Work in progress.** Live view and both log exports work and are in use on one stack:
4× US3000C, firmware B69.25.0.0, Cerbo GX with Venus OS v3.81. The goal is a setup that runs on
the Cerbo unattended for years, through Venus OS updates. Not there yet:

| Topic | State |
|---|---|
| USB adapter | The original project was built with an **FTDI** (FT232R) adapter. This version is developed and tested with a **CH340** adapter (udev rule bound to the USB socket). Moving back to FTDI (rule bound to the adapter's serial number) is planned. |
| Venus OS updates | The udev rule lives in `/etc` and is **lost on a Venus OS update**; it has to be re-created by hand. Restoring it automatically at boot is planned. |
| Installation | Manual (see [Install](#install)). A one-command installer is being prepared. |
| Other batteries | Only tested on US3000C with firmware B69.25. Other models, firmwares and stacks still need testing; console output and relaying of the other modules may differ. |
| Export of the connected module | Tested with the cable on the master. With the cable on another module: implemented, not yet tested on hardware. |

---

## Safety

- The battery only receives **read** commands. Every command passes one allow-list
  (`pylontech_remote/allowlist.py`) before a byte is written; commands that change, clear, test or
  control anything (`time`, `datac`, `config <x> <val>`, `shut`, `ctrl`, …) are refused. Tests
  assert this.
- Nothing on the Victron side is changed (no ESS/DVCC/BMS settings, no D-Bus battery service). The
  BMS-CAN link is not touched.
- The port is opened exclusively, with DTR/RTS low before opening.

---

## Hardware

| Item | Detail |
|---|---|
| Adapter | USB ↔ RS232. **FTDI (FT232R) recommended** — it has a serial number, so the udev rule follows the cable to any USB socket. CH340 works too, but has no serial number: the rule then matches the USB socket. |
| Cable | RJ45 → DB9 into the **Console** port of the **master** module only — the master relays the other modules. |
| Link | 115200 8N1, no flow control, DTR/RTS off |

Tested with: 4× US3000C, firmware B69.25.0.0, Venus OS v3.81, Cerbo GX.

### Keep Venus OS away from the port

Venus OS's `serial-starter` probes every USB serial adapter as one of its own devices and writes
probe traffic to the battery console. A udev rule must set `VE_SERVICE=ignore` for the adapter:

- name the file so it sorts **after** `serial-starter.rules`, e.g.
  `/etc/udev/rules.d/zz-pylontech-console.rules` (a `99-…` rule is processed first and then
  overridden);
- `/etc` is replaced by a Venus OS update — re-create the rule after updating (see
  [Project status](#project-status)).

```
# FTDI: by serial number   (udevadm info -q property -n /dev/ttyUSB0 | grep ID_SERIAL_SHORT)
ACTION=="add", SUBSYSTEM=="tty", ENV{ID_SERIAL_SHORT}=="YOURSERIAL", ENV{VE_SERVICE}="ignore"
# adapter without serial (e.g. CH340): by vendor/product + USB socket   (… | grep -E 'ID_VENDOR_ID|ID_MODEL_ID|ID_PATH')
ACTION=="add", SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="7523", ENV{ID_PATH}=="platform-1c14400.usb-usb-0:1:1.0", ENV{VE_SERVICE}="ignore"
```

Apply it to that port only (serial-starter then releases the port by itself):

```bash
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=tty --sysname-match=ttyUSB0
udevadm info -q property -n /dev/ttyUSB0 | grep VE_SERVICE     # → VE_SERVICE=ignore
fuser /dev/ttyUSB0                                               # → nothing
```

---

## Install

Requirements on the Cerbo: root SSH, Venus OS **Large** (Python 3 and pyserial included),
Node-RED with **Dashboard 2.0** (`@flowfuse/node-red-dashboard`, from the palette manager).

```bash
# from a checkout of this repository on your PC
ssh root@<cerbo-ip> 'mkdir -p /data/pylontech/app/pylontech_remote /data/pylontech/state /data/pylontech/exports && chown nodered:nodered /data/pylontech/state /data/pylontech/exports'
scp pylontech_live.py pylontech_export.py root@<cerbo-ip>:/data/pylontech/app/
scp pylontech_remote/*.py root@<cerbo-ip>:/data/pylontech/app/pylontech_remote/

# test on the Cerbo: one full read, prints one JSON line
ssh root@<cerbo-ip> 'python3 /data/pylontech/app/pylontech_live.py --once'
```

Then in Node-RED: Menu → **Import** `nodered/pylontech_flow.json` → **Deploy** (choose
*Modified Flows* so other flows are not restarted) → open
`http://<cerbo-ip>:1880/dashboard/battery`.

To remove: delete the **Battery** tab in Node-RED, `rm -r /data/pylontech` and the udev rule.

---

## Logs for a warranty claim

The **Warranty logs** card on the dashboard has two exports. Both write a ZIP to
`/data/pylontech/exports/`, downloadable from the dashboard, with per module
`<barcode>_event_<stamp>.txt` (`info`, `stat`, `pwr`, event table) and
`<barcode>_history_<stamp>.txt` (`info`, `stat`, history table) — the files BatteryView saves —
plus `README.txt` and `raw/` (every console reply as received). Live is paused meanwhile.

**Export connected module** (`python3 pylontech_export.py --connected`): the module the cable is
plugged into, read on its own console exactly as BatteryView does (`info`, `stat`, `pwr`,
`datalist event 0`, `datalist history 0`), ~2 min. The module is recognised by its `info`
(device address and serial). For a complete set move the cable from module to module (Console
port); the card lists every module exported so far. ZIP `pylontech_module_<barcode>_<stamp>.zip`,
the last 30 kept.

**Export whole stack** (`python3 pylontech_export.py`): every module through the master's console,
without moving the cable, ~1–1.5 h. ZIP `pylontech_logs_<stamp>.zip`, the last 5 kept.

- master: identical to BatteryView's files;
- other modules: the master does not relay their tables, so each table is rebuilt from the
  module's own records (`data N event|history <i>`). Every value column matches BatteryView's file
  of that module. `Rec_chg/dsg_cur`, `Sys_Rec_chg/dsg_cur` and `ID Cur` cannot be read through
  the master and are written as `-`; the table is marked as reconstructed. ~30 min per module.

Every reply is checked; replies the master cut short (~1 %) are read again, and records the
battery drops from its ring buffer during the run are handled. Details:
[docs/console-protocol.md](docs/console-protocol.md).

## Dashboard

Dark page with a header and two buttons, **Start Live** / **Stop Live** (the active one is
filled). Live needs the cable on the master. It reads the stack summary (`pwr`) and the cells of
every module (`bat N`) every **8 s**; the whole page updates at once. Model, serial, firmware,
SOH, cycles and thresholds are kept in `/data/pylontech/state/static.json`, so the page is
complete from the first update. Live switches itself off after **30 min** and frees the port.

- **Stack**: SOC (Ah, kWh), power, voltage, cell spread with the lowest and highest cell,
  temperatures, SOH and cycles.
- **Alerts**: module warnings and protections (`pwr` state columns), cells beyond the battery's
  limits, large cell spread, temperature, SOC difference between modules, stale data.
- **Cells**: every cell of the stack in one grid. Colour = deviation in mV from the average of the
  whole stack, on a fixed scale (green within a few mV, then yellow, orange, red, violet from
  80 mV), so a cell out of line stands out wherever it is. Switchable to deviation from the
  module's average, cell SOC or temperature. A dot marks a balancing cell; a cell beyond the
  BMS limit blinks.
- **Modules**: state, alarm chips, SOC, current, voltage, cell range and spread, temperature,
  capacity, SOH, cycles. **Click a module** to open its lifetime counters (`stat N`, ~120 values):
  alarms and protections, operation, time in current / SOC / temperature ranges, stored records.

The dark look is a style of this page only; the dashboard theme and other pages are not changed.

Options (`python3 pylontech_live.py --help`): `--port` (or env `PYLONTECH_PORT`, default
`/dev/ttyUSB0`), `--interval`, `--gap`, `--max-minutes`, `--once`, `--state-file`.

---

## Limitations

- The console has one user: Live and the log export never run at the same time, and BatteryView
  cannot be used on the same port while either runs.
- Live needs the cable on the master; on another module's console it stops with an error.

---

## Repository

```
pylontech_live.py         live reader (JSON lines on stdout)
pylontech_export.py       logs for a warranty claim -> ZIP
pylontech_remote/         allow-list, console session, parsers, stack state, export format
nodered/                  Node-RED flow (Dashboard 2.0)
tests/                    unit tests with recorded console replies
tools/console_capture.py  saves raw console replies (allow-listed commands only)
docs/console-protocol.md  console commands, record formats, BatteryView file format
```

Tests: `python -m unittest discover -s tests -t .`

---

## Troubleshooting

**Live does not start / `port_open: … held by pid …`** — something else has the port:
```bash
fuser /dev/ttyUSB0                                           # who holds it
udevadm info -q property -n /dev/ttyUSB0 | grep VE_SERVICE   # must be "ignore"
```
If `VE_SERVICE` is not `ignore`, the udev rule is missing (e.g. after a Venus OS update) or the
cable is in a different USB socket than the rule expects.

**Battery returns nothing** — check that the cable is in the **Console** socket of the master and
nothing else holds the port. `python3 pylontech_live.py --once` prints the error.

---

## Credits

Original project **pylontech-rs232-venus** by **Martin (tejno)** — reader, installer and the
dashboard widget this project builds on. If it saved you time, support him:
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/tejnoo) → **[ko-fi.com/tejnoo](https://ko-fi.com/tejnoo)**

## License

MIT — see [LICENSE](LICENSE) (copyright Martin (tejno); changes under the same license).

Not affiliated with Pylontech or Victron Energy. Use at your own risk.
