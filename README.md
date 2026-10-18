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
| Cable found automatically | A new or replaced cable is found without the installer, a CH340 is checked whenever it appears ([A new or replaced cable](#a-new-or-replaced-cable)). Implemented and tested in simulation; not yet tested on hardware. |
| Venus OS updates | The udev rule is restored at every boot from `/data` (see [Keep Venus OS away from the port](#keep-venus-os-away-from-the-port)). Verified after a restart (the rule is in place before serial-starter starts; it no longer touches the port). Not yet verified across a Venus OS update. |
| Installation | [From a USB stick](#from-a-usb-stick-no-ssh) without SSH, or [over SSH](#over-ssh). USB stick used on two Cerbos (Venus OS v3.80 and v3.81), SSH on one. Uninstall from a USB stick: not yet tested. |
| Other batteries | Only tested on US3000C with firmware B69.25. Other models, firmwares and stacks still need testing; console output and relaying of the other modules may differ. Every installation saves the battery's raw replies (`diagnostics.txt`) to adapt the program to them. |
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
- Finding the cable sends only Enter, and only to a USB serial converter that is not a Victron
  device and on which Venus OS has found no device; while such an adapter stays silent, at most
  once an hour after the first hour ([details](#a-new-or-replaced-cable)).

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

### A new or replaced cable

The program finds the cable itself (`pylontech_adopt.py`, started by `boot.sh` at boot and by a
udev rule in `/run` whenever a USB serial adapter is plugged in). Only the battery's own answer
counts: Enter is answered with the Pylontech prompt (`pylon>`, `pylon_debug>`). Timing alone never
decides.

**Cable missing** (`/dev/ttyPYLON`: no cable configured yet, or the cable was replaced). Venus OS
first gets a head start of a minute (two at boot) to find its own devices. Then, for each
adapter that may be the console:

- skipped: Victron devices (VE.Direct, MK3, Victron RS485), anything that is not a USB serial
  converter chip (FTDI, CH340, CP210x, PL2303 — so no 4G modems or GPS receivers), adapters
  reserved by other programs, and adapters on which Venus OS has found a device (a D-Bus service
  for that port, by name or by `/Mgmt/Connection`, e.g. an energy meter). These are never asked;
- the others: Venus OS lets go of the adapter (its own `serial-starter/stop-tty.sh`), the adapter
  gets **Enter only**, and the console is adopted (the udev rule above; the old rule is kept in
  `/data/pylontech/backup/`). Any other adapter goes straight back to Venus OS (`start-tty.sh`).
  An adapter that stays silent (battery off, cable not yet in the battery) is asked again every
  10 min for the first hour, then once an hour, until the battery answers or the adapter is
  unplugged or taken by Venus OS.

**Cable bound to a USB socket** (CH340, no serial number). The rule matches any CH340 in that
socket, so the adapter is checked whenever it appears (boot, plugged in):

| Answer to Enter | Result |
|---|---|
| Pylontech prompt | confirmed |
| silent (battery off, or e.g. a Modbus meter converter, which only answers its own protocol) | asked again every 2 min for 30 min, then given to Venus OS |
| something else, twice | given to Venus OS at once |

Given to Venus OS means the rule is moved to `/data/pylontech/backup/` and the search above takes
over: an energy meter is then found by Venus OS and never touched again, the battery console is
found again as soon as the battery answers. A cable with a serial number (FTDI) is not checked:
its rule matches that one cable only.

Each change is written to `/data/pylontech/adapter.log`. Timing: `pylontech_remote/adapters.py`.

---

## Install

Requirements on the Cerbo: Venus OS **Large** (Python 3 and pyserial included), Node-RED switched
on (Settings → Integrations) with **Dashboard 2.0** (`@flowfuse/node-red-dashboard`, installed from
the Node-RED palette manager).
Plug the console cable into the Cerbo first (or later: it is then
[found automatically](#a-new-or-replaced-cable)). Two ways, same result:

### From a USB stick (no SSH)

1. Download [`venus-runtime-pylontech-install.tar.gz`](https://github.com/Mejchalos/pylontech-remote/releases/latest/download/venus-runtime-pylontech-install.tar.gz)
   from the [latest release](https://github.com/Mejchalos/pylontech-remote/releases/latest) and copy
   it, unchanged, to the root of a FAT32 USB stick.
2. Plug the stick into any free USB port of the Cerbo. About a minute later the program is
   installed: Venus OS unpacks every `venus-runtime-*.tar.gz` from an inserted stick into `/data`
   and runs its install hook as root, which runs `install.sh` without questions (the cable is
   [found automatically](#a-new-or-replaced-cable)).
3. Remove the stick. It is **reusable**: the archive stays on it, so the same stick installs the
   next Cerbo. On the stick, per Cerbo (its VRM portal ID):
   - `pylontech-results.txt`: one line per installation — date, Cerbo, result (`OK`,
     `INSTALLED, BATTERY NOT REACHED YET`, `FAILED`);
   - `pylontech-logs/<id>-install-log.txt`: the installer's output, newest run first;
   - `pylontech-logs/<id>-diagnostics.txt`: the battery's raw replies (they contain the modules'
     serial numbers).

   Plugging the stick in again repeats the installation and the test (e.g. after fixing the
   cable). Do not leave the stick in the Cerbo: Venus OS also stores VRM log backlog on inserted
   sticks. A stick left in is processed again at boot; nothing is done then if this version is
   already installed.

The same file updates an installation. The archives can also be built from the repository:
`python venus/usb/build.py` (→ `dist/usb/`).

### Over SSH

On the Cerbo, as root:

```bash
wget -O /tmp/pylontech-install.sh https://raw.githubusercontent.com/Mejchalos/pylontech-remote/main/install.sh
sh /tmp/pylontech-install.sh
```

The installer checks the Cerbo, installs the program into `/data/pylontech`, lists the USB
adapters and asks which one is the cable (Enter: find it automatically), sets up the boot hook,
and reads the battery once to show the modules. Every change is shown before it is made;
`--dry-run` only shows them. The same command updates an installation (settings, state and
exports are kept); `--reconfigure` chooses the adapter again. Without internet on the Cerbo: copy
the repository to it and run `sh install.sh --source <dir>`.

### Node-RED

Menu → **Import** → **Local** (library) → `pylontech-remote` → **Import** → **Deploy** (when
updating, delete the old **Battery** tab first).

Dashboard:
- remotely: VRM → the installation → Venus OS Large → **Node-RED Dashboard 2.0**;
- local network: `https://<cerbo-ip>:1881/dashboard/battery` (the Cerbo's own certificate: confirm
  the browser's warning once).

Like every Node-RED page on Venus OS, the dashboard has no password of its own: on the local
network it is open to anyone who can reach the Cerbo; through VRM it needs the VRM login. The
Node-RED editor is protected by the Cerbo's password (Settings → General → Access & security) —
set one.

### Internet

Needed only to download the files and to install Dashboard 2.0 from the palette manager. The
program, the USB stick installation, Live and the log exports work without internet on the Cerbo;
the dashboard is then reachable on the local network.

### Uninstall

- USB stick: [`venus-runtime-pylontech-uninstall.tar.gz`](https://github.com/Mejchalos/pylontech-remote/releases/latest/download/venus-runtime-pylontech-uninstall.tar.gz),
  the same way as the installation (log: `pylontech-uninstall-log.txt`). It removes the boot hook,
  the udev rules and `/data/pylontech` including the exported logs, and stops Live if it runs.
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

Options (`python3 pylontech_live.py --help`): `--port` (or env `PYLONTECH_PORT`; default
`/dev/ttyPYLON` when installed, else `/dev/ttyUSB0`), `--interval`, `--gap`, `--max-minutes`,
`--once`, `--state-file`, `--raw-dump FILE` (every command with its raw reply).

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
pylontech_adopt.py        finds the console cable among the USB serial adapters
pylontech_remote/         allow-list, console session, parsers, stack state, export format
nodered/                  Node-RED flow (Dashboard 2.0)
tests/                    unit tests with recorded console replies
install.sh, uninstall.sh  installer / uninstaller (run on the Cerbo)
venus/boot.sh             boot hook: restores the udev rule, starts the cable search
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
socket than before. The search for it is in `/data/pylontech/adapter.log`;
`python3 /data/pylontech/app/pylontech_adopt.py --list` shows the adapters and why each one is
skipped.

**Battery returns nothing** — check that the cable is in the **Console** socket of the master and
nothing else holds the port. `python3 /data/pylontech/app/pylontech_live.py --once` prints the error;
with `--raw-dump /tmp/raw.txt` also every raw reply.

---

## Credits

Original project [**pylontech-rs232-venus**](https://github.com/tejno/pylontech-rs232-venus) by **Martin (tejno)** — reader, installer and the
dashboard widget this project builds on. If it saved you time, support him:
[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/tejnoo) → **[ko-fi.com/tejnoo](https://ko-fi.com/tejnoo)**

## License

MIT — see [LICENSE](LICENSE) (copyright Martin (tejno); changes under the same license).

Not affiliated with Pylontech or Victron Energy. Use at your own risk.
