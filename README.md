# pylontech-remote

Pylontech BatteryView-style logs and live view on a **Victron Cerbo GX / Venus OS**, in Node-RED:
remote access to **Pylontech** battery logs and live data through the RS232 console of the
battery, without a technician on site.

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
| Venus OS updates | The udev rule is restored at every boot from `/data` (see [Keep Venus OS away from the port](#keep-venus-os-away-from-the-port)). Verified after a restart (the rule is in place before serial-starter starts; it no longer touches the port). Not yet verified across a Venus OS update. |
| Installation | [From a USB stick](#from-a-usb-stick-no-ssh) without SSH, or [over SSH](#over-ssh). Both used on one Cerbo so far, the USB stick also with the port held by Venus OS. Uninstall from a USB stick: not yet tested. |
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
probe traffic to the battery console. The installer adds a udev rule that sets
`VE_SERVICE=ignore` for the console adapter only and gives it the fixed name `/dev/ttyPYLON`:

- adapter with a serial number (FTDI): matched by the serial number, any USB socket;
- adapter without one (CH340): matched by vendor/product and the USB socket.

The rule is kept in `/data/pylontech/udev.rules`. At every boot `/data/rcS.local` runs
`/data/pylontech/boot.sh` (before Venus OS starts serial-starter), which puts it into
`/run/udev/rules.d/` and applies it. Nothing in `/etc` is changed, so a Venus OS update does not
remove it. `/data/pylontech/boot.log` shows the result of the last boot.

---

## Install

Requirements on the Cerbo: Venus OS **Large** (Python 3 and pyserial included), Node-RED with
**Dashboard 2.0** (`@flowfuse/node-red-dashboard`, installed from the Node-RED palette manager).
Plug the console cable into the Cerbo first. Two ways, same result:

### From a USB stick (no SSH)

1. Download [`venus-runtime-pylontech-install.tar.gz`](https://github.com/Mejchalos/pylontech-remote/releases/latest/download/venus-runtime-pylontech-install.tar.gz)
   from the [latest release](https://github.com/Mejchalos/pylontech-remote/releases/latest) and copy
   it, unchanged, to the root of a FAT32 USB stick.
2. Plug the stick into any free USB port of the Cerbo. About a minute later the program is
   installed: Venus OS unpacks every `venus-runtime-*.tar.gz` from an inserted stick into `/data`
   and runs its install hook as root, which runs `install.sh` without questions (the adapter is
   configured when it is the only USB serial adapter that is not a Victron device).
3. Remove the stick. On it: `pylontech-install-log.txt` with the result; the archive is renamed to
   `….installed` so it runs only once. Remove the stick in any case: Venus OS also stores VRM log
   backlog on inserted sticks.

The same file updates an installation. The archives can also be built from the repository:
`python venus/usb/build.py` (→ `dist/usb/`).

### Over SSH

On the Cerbo, as root:

```bash
wget -O /tmp/pylontech-install.sh https://raw.githubusercontent.com/Mejchalos/pylontech-remote/main/install.sh
sh /tmp/pylontech-install.sh
```

The installer checks the Cerbo, installs the program into `/data/pylontech`, finds the USB
adapter and asks before using it, sets up the boot hook, and reads the battery once to show the
modules. Every change is shown before it is made; `--dry-run` only shows them. The same command
updates an installation (settings, state and exports are kept); `--reconfigure` chooses the
adapter again (another USB socket, a new cable). Without internet on the Cerbo: copy the
repository to it and run `sh install.sh --source <dir>`.

### Node-RED

Menu → **Import** → **Local** (library) → `pylontech-remote` → **Import** → **Deploy** (when
updating, delete the old **Battery** tab first). Dashboard: `http://<cerbo-ip>:1880/dashboard/battery`.

### Internet

Needed only to download the files and to install Dashboard 2.0 from the palette manager. The
program, the USB stick installation, Live and the log exports work without internet on the Cerbo;
the dashboard is then reachable on the local network.

### Uninstall

- USB stick: [`venus-runtime-pylontech-uninstall.tar.gz`](https://github.com/Mejchalos/pylontech-remote/releases/latest/download/venus-runtime-pylontech-uninstall.tar.gz),
  the same way as the installation (log: `pylontech-uninstall-log.txt`). It removes the boot hook,
  the udev rule and `/data/pylontech` including the exported logs, and stops Live if it runs.
  Never put the install and the uninstall archive on the same stick.
- SSH: `sh /data/pylontech/uninstall.sh` (asks before deleting `/data/pylontech`).

Then delete the **Battery** tab in Node-RED. After the next restart Venus OS uses the USB adapter
again: unplug the console cable from the battery before that.

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
install.sh, uninstall.sh  installer / uninstaller (run on the Cerbo)
venus/boot.sh             boot hook: restores the udev rule (installed to /data/pylontech)
venus/usb/                install from a USB stick: install hook and the archive builder
docs/console-protocol.md  console commands, record formats, BatteryView file format
```

Tests: `python -m unittest discover -s tests -t .`

---

## Troubleshooting

**Live does not start / `port_open: … held by pid …`** — something else has the port:
```bash
cat /data/pylontech/boot.log                                     # result of the last boot
fuser /dev/ttyPYLON                                              # who holds the port
udevadm info -q property -n /dev/ttyPYLON | grep VE_SERVICE      # must be "ignore"
```
No `/dev/ttyPYLON`: the cable is unplugged, or (adapter without serial number) in another USB
socket than at installation — run the installer with `--reconfigure`.

**Battery returns nothing** — check that the cable is in the **Console** socket of the master and
nothing else holds the port. `python3 /data/pylontech/app/pylontech_live.py --once` prints the error.

---

## Credits

Original project [**pylontech-rs232-venus**](https://github.com/tejno/pylontech-rs232-venus) by **Martin (tejno)** — reader, installer and the
dashboard widget this project builds on. If it saved you time, support him:
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/tejnoo) → **[ko-fi.com/tejnoo](https://ko-fi.com/tejnoo)**

## License

MIT — see [LICENSE](LICENSE) (copyright Martin (tejno); changes under the same license).

Not affiliated with Pylontech or Victron Energy. Use at your own risk.
