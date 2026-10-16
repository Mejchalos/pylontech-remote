# Architecture — Pylontech Remote

Status 2026-10-16: the parts below marked *built* run on the test stack; current state, limits and
next steps are in [docs/STATUS.md](docs/STATUS.md). Console facts: [docs/CONSOLE-NOTES.md](docs/CONSOLE-NOTES.md).
Every change on the Cerbo: [CHANGES-ON-CERBO.md](CHANGES-ON-CERBO.md).

## 1. Goal and scope

**Goal:** remotely obtain the logs Pylontech support needs for a warranty claim — per module the
BatteryView `.txt` files `<barcode>_event_<stamp>.txt` and `<barcode>_history_<stamp>.txt` — with
access to the **master's console only**, through a Victron Cerbo GX (VRM).

Extras: a live view of the stack (pack, modules, cells) and the lifetime counters of each module.

Not goals: keeping history beyond what the battery stores (~37 days — the logs cover it);
changing any battery setting; anything on the Victron side (ESS, DVCC, BMS selection, settings).

## 2. Hard constraints

| Constraint | Consequence |
|---|---|
| Battery gets **read-only** commands only | One allow-list (`pylontech_remote/allowlist.py`), checked in the only code that writes to the port; tests assert that every known writing/clearing/test command is refused. No raw console pass-through anywhere. |
| BMS-CAN must not be affected | Nothing touches CAN, D-Bus battery services or Victron settings. |
| One owner of the console port | Live and export are never started together (Node-RED port controller); the port is opened exclusively (TIOCEXCL), `fuser` checked first. |
| Customer can only help by phone | Everything is driven remotely from the dashboard (through VRM). |
| Flash wear | Only small files on change (`static.json`), the export ZIPs (last 5 kept). |
| No package installs | Python 3 stdlib + pyserial (both on Venus OS Large); Node-RED Dashboard 2.0 from the palette. |

## 3. Overview (*built*)

```
 Node-RED (Dashboard 2.0, /dashboard/battery, LAN or VRM)
   Live switch ──┐     "Logy pro reklamaci" / "Zrušit" ──┐
                 ▼                                      ▼
          Port controller: idle | live | export  (one at a time; export stops Live)
                 │ exec (spawn)                         │ exec (spawn)
                 ▼                                      ▼
        pylontech_live.py                       pylontech_export.py
        JSON snapshot every 8 s                 JSON progress lines, then a ZIP
                 │                                      │
                 └──────── pylontech_remote/ ───────────┘
                   allowlist · session · parsers · live · export
                                 │  RS232 console of the master (USB adapter)
                                 ▼
                         Pylontech stack (master relays the slaves)

 /data/pylontech/app      code          /data/pylontech/state    static.json (live)
 /data/pylontech/exports  ZIPs          GET /pylontech/exports/<name>  (only pylontech_logs_*.zip)
```

## 4. Components (*built*)

**`allowlist.py`** — full-match patterns: `help [cmd]`, `pwr [N]`, `config`, `info [N]`, `bat N`,
`stat [N]`, `data [N] event|history I`, `datalist event|history I`, `log`, bare Enter.

**`session.py`** — DTR/RTS low before open, exclusive open, a minimum gap between commands; a
reply ends at the prompt (also right after text the master cut short), paging answered with Enter
only (any other key aborts the output); `resync()`, `drain()`.

**`parsers.py`** — pure functions, by label and table header: `pwr`, `bat`, `info`, `stat`,
`config`, `data` records; checks `is_record_reply()` (the record asked for, with time and the full
cell table — needed because the rest of a cut reply arrives with the next command), `is_refusal()`.

**`live.py` + `pylontech_live.py`** — holds the port while Live is on; each cycle `pwr` + `bat N`
for every module, one snapshot per cycle in the original reader's JSON shape (dashboard widget);
`config`/`info N`/`stat N` at start (missing ones in the first cycle) and `stat N` every 10 min;
model/serial/firmware/counters kept in `static.json` so the page is complete at once.

**`export.py` + `pylontech_export.py`** — the claim logs:
- master: `info`, `stat`, `pwr`, `datalist event 0`, `datalist history 0`; tables stored as
  BatteryView stores them (CRLF, a line of 50 spaces where the console paged);
- other modules: `info N`, `stat N`, `pwr N`, then every record `data N event|history i` from the
  newest down (survives the ring buffer dropping its oldest 8 meanwhile, deduplicated), each reply
  validated and re-read when cut short; tables rebuilt in the master's B69.25 layout, unreadable
  stack columns `-`, marked as reconstructed;
- if the master has no `datalist`, module 1 is read record by record too;
- ZIP: the BatteryView-format files, `README.txt`, `raw/` (every reply), `raw/failed/` (rejected
  replies); last 5 ZIPs kept; `--limit N` makes a marked incomplete test export.

**Node-RED flow** (`nodered/pylontech_flow.json`) — port controller, Live switch and status, export
button/cancel, progress panel with ETA and download link, widget (pack, modules, cells, counters
panel per module, BHV counter increases), download endpoint.

## 5. Planned

### 5.1 Boot persistence and installer
- `install.sh` (rewrite): detect the adapter (FTDI by serial, others by USB path), write the udev
  rule as `zz-pylontech-console.rules` (must sort after Venus OS's `serial-starter.rules`), copy
  the app, create `state/` and `exports/` owned by `nodered`, show every change before making it.
  No `opkg`/`pip`, no serial-starter restart, no global `udevadm trigger`.
- `boot.sh` from `/data/rc.local` (runs late at boot): restore the rule into `/etc/udev/rules.d/`
  if missing, reload udev, re-trigger only the matching tty with `--action=add`. Idempotent.
- `uninstall.sh`.

### 5.2 Capability check
Read-only probe per stack: firmware of every module (`info N`), `datalist` header, whether
`data N …` and `pwr N` are relayed. Shown on the dashboard; also usable as a standalone script to
collect samples from other firmwares/models.

### 5.3 Phone-guided cable move (fallback)
When slaves cannot be read through the master, or support needs verbatim slave files: the
technician runs a wizard on the dashboard while the customer moves the cable by phone. The
dashboard shows which module is connected (live `info`: serial, device address) and the next
target with its serial; on each module the export reads `info`, `stat`, `pwr`,
`datalist event 0`, `datalist history 0` verbatim (~2 min). The USB end stays in the Cerbo, so the
udev identity does not change.

**Risk: wrong socket.** Console, Link and CAN/RS485 sockets look alike; pulling Link or BMS-CAN
disturbs the system. The call script: touch only the cable that ends in the Cerbo; only the socket
labelled **Console**. The dashboard shows a photo of the module front and, read-only, what the
Cerbo receives over BMS-CAN (`N/…` MQTT topics: alarms, modules online) and warns on any change.

## 6. Not planned

- History archive, background sync, long-running service: the battery's own ~37 days, read when a
  claim is needed, are enough.
- MQTT / D-Bus publishing of live data (never as `com.victronenergy.battery`).
- Remote BatteryView through a network bridge of the port (it would allow any command).

## 7. Repository

```
pylontech_live.py  pylontech_export.py
pylontech_remote/  allowlist.py session.py parsers.py live.py export.py
nodered/pylontech_flow.json
tests/  (unit tests, fake console/stack, sanitised fixtures)   tools/console_capture.py
docs/   STATUS.md CONSOLE-NOTES.md FOR-PYLONTECH-SUPPORT.md
install.sh pylontech_reader.py udev/   legacy, from the original project (tejno, MIT)
```
